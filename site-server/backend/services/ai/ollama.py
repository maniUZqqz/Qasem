"""
Ollama provider — the only place in the codebase that talks to the Ollama API.

Configured entirely via settings.UPMARKET_AI (environment variables), so the
same code works on the dev machine and the main system (where the models run).
"""

import json
import logging
import re
import time

import requests
from django.conf import settings

from services.net import is_listening

logger = logging.getLogger(__name__)

# Reasoning models (QwQ / Qwen3-VL) may emit <think>…</think> blocks.
# These must never reach JSON parsing or end users.
THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)

# ```json ... ``` fences some models wrap their answer in.
CODE_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)

# Appended when the model ran out of output budget mid-answer. Asking for a
# shorter answer is the only retry that can actually fit: it costs no extra
# VRAM and needs no bigger context window.
SHORTER_SUFFIX = (
    "\n\nIMPORTANT: your previous answer was cut off because it was too long. "
    "Answer again with the SAME JSON keys but much shorter: at most 3 items per "
    "list, one short sentence per string value. The complete JSON object matters "
    "more than the detail."
)

# The self-repair round (asking the model to fix its own JSON) is a last
# resort and must never cost as much as the real call.
REPAIR_TIMEOUT = 180
REPAIR_NUM_PREDICT = 2048

# Trailing comma right before a closing bracket: {"a": 1,} / [1, 2,]
TRAILING_COMMA_RE = re.compile(r",\s*([}\]])")

# A value ending (string/number/bool/null/close-bracket) followed by a newline
# and the next quoted key, with the comma between them missing.
MISSING_COMMA_RE = re.compile(r"([\"\d}\]]|true|false|null)(\s*\n\s*)\"")


class OllamaError(Exception):
    """Base error for Ollama provider failures."""


class OllamaTimeout(OllamaError):
    pass


class OllamaMalformedOutput(OllamaError):
    pass


class OllamaTruncated(OllamaError):
    """The model hit its token budget mid-answer (`done_reason: "length"`).

    Carries whatever arrived so a caller can still salvage it, but the answer
    is incomplete by definition: half the JSON keys are simply missing.
    """

    def __init__(self, message, partial: str = ""):
        super().__init__(message)
        self.partial = partial


class OllamaUnavailable(OllamaError):
    """Ollama itself is not reachable (not running / wrong OLLAMA_BASE_URL).

    Distinct from a model failure: trying a different model against the same
    dead endpoint can only waste more of the user's time.
    """


def strip_reasoning(text: str) -> str:
    """Remove explicit <think>...</think> blocks from model output.

    QwQ's chat template opens the `<think>` itself, so the text that comes back
    often holds only the CLOSING tag: "reasoning… </think>{json}". Without the
    second rule the reasoning stayed in, and its first "{" (a draft object the
    model was thinking about) was taken as the start of the answer.
    """
    if not text:
        return ""
    text = THINK_RE.sub("", text)
    if "</think>" in text:
        text = text.rsplit("</think>", 1)[1]
    return text.strip()


def extract_json_block(text: str):
    """Controlled repair: try to pull the outermost JSON object from raw text."""
    if not text:
        return None

    start = text.find("{")
    end = text.rfind("}")

    if start == -1 or end == -1 or end <= start:
        return None

    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None


def close_truncated_json(text: str) -> str:
    """
    Best-effort completion of JSON that was cut off mid-generation
    (e.g. the model hit its token limit): close an open string, drop a
    dangling key/comma, and close every unclosed { or [.
    """
    start = text.find("{")
    if start == -1:
        return text
    text = text[start:]

    stack = []
    in_string = False
    escaped = False
    for ch in text:
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch in "{[":
            stack.append(ch)
        elif ch in "}]":
            if stack:
                stack.pop()

    if in_string:
        text += '"'

    # a truncated `"key":` / `"key"` or a trailing comma cannot be closed —
    # cut back to the last complete value
    text = re.sub(r'[,{\[]\s*"[^"]*"?\s*:?\s*$', lambda m: m.group(0)[0], text)
    text = re.sub(r",\s*$", "", text)

    for opener in reversed(stack):
        text += "}" if opener == "{" else "]"
    return text


def repair_json(text: str):
    """
    Staged, deterministic repair of model output that should be JSON.
    Returns the parsed dict or None. Never raises.
    """
    if not text:
        return None

    candidates = [text]

    fence = CODE_FENCE_RE.search(text)
    if fence:
        candidates.append(fence.group(1))

    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start : end + 1])

    for candidate in list(candidates):
        fixed = TRAILING_COMMA_RE.sub(r"\1", candidate)
        fixed = MISSING_COMMA_RE.sub(r'\1,\2"', fixed)
        if fixed != candidate:
            candidates.append(fixed)

    # last resort: assume the output was cut off mid-JSON and close it
    truncated = close_truncated_json(text)
    truncated = TRAILING_COMMA_RE.sub(r"\1", truncated)
    truncated = MISSING_COMMA_RE.sub(r'\1,\2"', truncated)
    candidates.append(truncated)

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def extract_ollama_text(data: dict) -> str:
    """
    Extract the actual model answer from an Ollama /api/generate response.

    Normal response:
        {
            "response": "...",
            "thinking": "...",
            "done": true
        }

    Qwen3-VL + JSON mode can, on some Ollama versions, return:
        {
            "response": "",
            "thinking": "{\"key\":\"value\"}",
            "done": true
        }

    In that case, only use `thinking` as a fallback when it is itself
    valid JSON. This prevents normal reasoning text from being exposed
    as the model's answer.
    """

    response_text = data.get("response") or ""

    if response_text.strip():
        return strip_reasoning(response_text)

    # Qwen3-VL/Ollama JSON-mode compatibility fallback.
    thinking_text = data.get("thinking") or ""

    if thinking_text.strip():
        thinking_clean = strip_reasoning(thinking_text)

        # Only accept thinking as output when it is actually valid JSON.
        try:
            json.loads(thinking_clean)
            logger.warning(
                "Ollama returned empty 'response'; using JSON from 'thinking' "
                "as compatibility fallback."
            )
            return thinking_clean
        except json.JSONDecodeError:
            pass

    return ""


class OllamaProvider:
    def __init__(self, base_url=None, timeout=None, retries=None, backoff=2.0, model=None):
        conf = settings.UPMARKET_AI
        self.base_url = (base_url or conf["OLLAMA_BASE_URL"]).rstrip("/")
        self.timeout = timeout or conf["OLLAMA_TIMEOUT"]
        self.retries = conf["OLLAMA_RETRIES"] if retries is None else retries
        self.backoff = backoff
        # The model the admin row (or .env) named for this provider. Callers
        # still pass a model per call; this one only goes first in the
        # candidate list (see `select_models`).
        self.model = model or ""
        # How long the model stays resident after the call. On one 12 GB card
        # a lingering 18 GB model starves the next one (beter.md v2 #9).
        self.keep_alive = conf.get("OLLAMA_KEEP_ALIVE", "60s")
        self.num_ctx = conf.get("OLLAMA_NUM_CTX", 0)

    # ------------------------------------------------------------------

    @property
    def is_remote(self) -> bool:
        """Served by a processing node through the compute queue (agent://),
        or by one because nothing listens on the configured local URL."""
        from . import ollama_remote

        return ollama_remote.use_remote(self.base_url)

    def select_models(self, candidates):
        """Which model names to try, in order, given the router's candidates.

        The router names Ollama models (.env), which is exactly what this
        provider runs, so the list passes through — the admin row's own model
        just goes first when it names a different one.
        """
        names = [m for m in (candidates or []) if m]
        if self.model and self.model not in names:
            names.insert(0, self.model)
        return names or ([self.model] if self.model else [])

    def _answer_from(self, data: dict, model: str, format_json: bool) -> str:
        """The text out of one Ollama /api/generate answer (local or remote)."""
        text = extract_ollama_text(data)

        # Helpful diagnostic when Ollama returns an empty response.
        if not text:
            logger.error(
                "Ollama returned empty model output: "
                "model=%s response_chars=%s thinking_chars=%s "
                "done=%s done_reason=%s",
                model,
                len(data.get("response") or ""),
                len(data.get("thinking") or ""),
                data.get("done"),
                data.get("done_reason"),
            )

        if format_json and data.get("done_reason") == "length" and text:
            raise OllamaTruncated(
                f"Model {model} ran out of output budget mid-answer "
                f"({len(text)} chars)",
                partial=text,
            )
        return text

    def generate(
        self,
        model,
        prompt,
        *,
        system=None,
        images=None,
        format_json=False,
        options=None,
        timeout=None,
    ) -> str:
        """
        Single completion.

        `images` is a list of base64-encoded images for vision models.
        `timeout` overrides the configured one for this call only (used to keep
        the self-repair round cheap).
        """

        url = f"{self.base_url}/api/generate"
        call_timeout = timeout or self.timeout

        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,
        }

        if system:
            payload["system"] = system

        if images:
            payload["images"] = images

        if format_json:
            payload["format"] = "json"

        if self.keep_alive:
            payload["keep_alive"] = self.keep_alive

        opts = {
            "temperature": 0.7,
        }
        if self.num_ctx:
            opts["num_ctx"] = self.num_ctx

        opts.update(options or {})
        payload["options"] = opts

        # No Ollama on this machine: the model lives on a processing node, so
        # the same body goes through the compute queue (services/ai/ollama_remote.py)
        # and comes back as Ollama's own JSON. Images travel as input files.
        if self.is_remote:
            from . import ollama_remote

            remote_payload = {k: v for k, v in payload.items() if k != "images"}
            data = ollama_remote.generate(
                remote_payload, base_url=self.base_url, timeout_s=call_timeout, images=images,
            )
            return self._answer_from(data, model, format_json)

        # Ollama switched off is not a transient error: answer in under a
        # second instead of burning three refused connections plus backoff.
        if not getattr(settings, "IS_TEST", False) and not is_listening(self.base_url):
            raise OllamaUnavailable(
                f"Ollama در دسترس نیست ({self.base_url}) — سرویس Ollama را روشن کنید "
                "یا OLLAMA_BASE_URL را در backend/.env.local بنویسید (این فایل مخصوص همین سیستم است)."
            )

        last_error = None

        for attempt in range(self.retries + 1):
            attempt_started = time.monotonic()
            try:
                response = requests.post(
                    url,
                    json=payload,
                    timeout=call_timeout,
                )

                response.raise_for_status()

                data = response.json()

                return self._answer_from(data, model, format_json)

            except OllamaTruncated:
                raise

            except requests.Timeout as exc:
                last_error = OllamaTimeout(
                    f"Ollama timed out after {call_timeout}s (model={model})"
                )

                logger.warning(
                    "Ollama timeout (attempt %s/%s): %s",
                    attempt + 1,
                    self.retries + 1,
                    exc,
                )

                # Retrying a timeout just spends the same minutes again (three
                # attempts x 600s = 30 minutes of "loading" for the user).
                # A slow model is better handled by falling back to a smaller
                # one, which the caller does. (beter.md v2 #3)
                break

            except requests.HTTPError as exc:
                detail = getattr(exc.response, "text", "")[:500]

                last_error = OllamaError(
                    f"Ollama request failed (model={model}): "
                    f"{exc} — {detail}"
                )

                logger.warning(
                    "Ollama error (attempt %s/%s): %s",
                    attempt + 1,
                    self.retries + 1,
                    exc,
                )

                status_code = getattr(exc.response, "status_code", 0)

                if 400 <= status_code < 500:
                    break

                # A 500 that took most of the timeout is the model failing to
                # fit / run, not a blip — retrying only burns the same minutes.
                if time.monotonic() - attempt_started > call_timeout * 0.5:
                    break

            except requests.ConnectionError as exc:
                last_error = OllamaUnavailable(
                    "Ollama در دسترس نیست ("
                    f"{self.base_url}) — سرویس Ollama را روشن کنید یا "
                    f"OLLAMA_BASE_URL را در backend/.env.local بنویسید (مخصوص همین سیستم). جزئیات: {exc}"
                )

                logger.warning(
                    "Ollama unreachable at %s (attempt %s/%s)",
                    self.base_url,
                    attempt + 1,
                    self.retries + 1,
                )

            except (requests.RequestException, ValueError) as exc:
                last_error = OllamaError(
                    f"Ollama request failed (model={model}): {exc}"
                )

                logger.warning(
                    "Ollama error (attempt %s/%s): %s",
                    attempt + 1,
                    self.retries + 1,
                    exc,
                )

            if attempt < self.retries:
                time.sleep(self.backoff * (2**attempt))

        raise last_error

    def generate_json(
        self,
        model,
        prompt,
        *,
        system=None,
        images=None,
        options=None,
        repair_attempts=1,
        timeout=None,
    ):
        """
        Completion that must return JSON.

        Malformed output is first repaired deterministically (code fences,
        trailing/missing commas, truncated output); if that fails, the broken
        output is sent back to the model once (`repair_attempts`) with the
        parse error so it can correct itself.

        Returns:
            (parsed_dict, raw_text)
        """

        # JSON tasks want determinism and enough room to finish the object —
        # callers can still override both through `options`.
        json_options = {
            "temperature": 0.2,
            "num_predict": settings.UPMARKET_AI.get("OLLAMA_NUM_PREDICT_JSON", 3000),
        }
        json_options.update(options or {})

        try:
            raw = self.generate(
                model,
                prompt,
                system=system,
                images=images,
                format_json=True,
                options=json_options,
                timeout=timeout,
            )
        except OllamaTruncated as cut:
            # The budget, not the model, is the problem. Asking for a shorter
            # answer costs no extra VRAM and no bigger context, and it is the
            # only retry that can actually fit. (A repaired truncated object
            # parses fine but is missing half its keys, which then fails
            # validation and loses the whole job.)
            logger.warning("%s — asking for a shorter answer", cut)
            try:
                raw = self.generate(
                    model,
                    prompt + SHORTER_SUFFIX,
                    system=system,
                    images=images,
                    format_json=True,
                    options=json_options,
                    timeout=timeout,
                )
            except OllamaTruncated as cut_again:
                # still too long: salvage what arrived rather than lose it all
                logger.warning("%s — falling back to the partial answer", cut_again)
                raw = cut_again.partial

        if not raw:
            raise OllamaMalformedOutput(
                f"Model {model} returned empty output"
            )

        try:
            return json.loads(raw), raw
        except json.JSONDecodeError as exc:
            parse_error = f"{exc.msg} (line {exc.lineno}, char {exc.pos})"

        repaired = repair_json(raw)
        if repaired is not None:
            logger.warning(
                "Ollama output needed local JSON repair (model=%s, %s chars): %s",
                model,
                len(raw),
                parse_error,
            )
            return repaired, raw

        if repair_attempts > 0:
            logger.warning(
                "Ollama output unrepairable locally (model=%s): %s — asking the "
                "model to fix its own JSON.",
                model,
                parse_error,
            )
            fix_prompt = (
                "Your previous answer was INVALID JSON and could not be parsed.\n"
                f"Parse error: {parse_error}\n\n"
                "Broken output:\n"
                f"{raw[:6000]}\n\n"
                "Return the SAME content as one single valid JSON object. "
                "Output nothing but the corrected JSON."
            )
            # A repair round must stay cheap: on a model that is already
            # crawling, a second full-length generation would double a
            # ten-minute wait for nothing. Cap it hard.
            return self.generate_json(
                model,
                fix_prompt,
                system=system,
                options={**(options or {}), "num_predict": REPAIR_NUM_PREDICT},
                repair_attempts=repair_attempts - 1,
                timeout=min(timeout or self.timeout, REPAIR_TIMEOUT),
            )

        raise OllamaMalformedOutput(
            f"Model {model} returned non-JSON output "
            f"({len(raw)} chars; {parse_error})"
        )









