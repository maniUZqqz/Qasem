"""An OpenAI-compatible chat provider, shaped like OllamaProvider.

Almost every hosted model today speaks the OpenAI chat-completions dialect —
OpenAI itself, OpenRouter, Groq, Together, vLLM, LM Studio, LiteLLM and most
Iranian resellers. One adapter therefore covers "switch to an API" for text
and vision, and it deliberately exposes the same `generate` / `generate_json`
surface as the local provider so callers cannot tell them apart.

Errors are re-raised as the Ollama error types on purpose: the retry, repair
and job-failure handling around AI calls already understands those, and a
second parallel hierarchy would mean touching every call site.
"""
from __future__ import annotations

import base64
import json
import logging
import time
from pathlib import Path

import requests

from .ollama import (
    OllamaError,
    OllamaMalformedOutput,
    OllamaTimeout,
    OllamaUnavailable,
    extract_json_block,
    repair_json,
    strip_reasoning,
)

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 300
RETRIES = 2
BACKOFF = 2.0


def _image_data_url(path) -> str:
    raw = Path(path).read_bytes()
    suffix = Path(path).suffix.lower().lstrip(".") or "png"
    mime = "jpeg" if suffix in ("jpg", "jpeg") else suffix
    return f"data:image/{mime};base64,{base64.b64encode(raw).decode()}"


class OpenAICompatProvider:
    """Chat completions over any OpenAI-compatible endpoint."""

    def __init__(self, base_url, api_key="", model=None, timeout=None, options=None):
        self.base_url = (base_url or "").rstrip("/")
        self.api_key = api_key or ""
        self.model = model
        self.timeout = timeout or DEFAULT_TIMEOUT
        self.options = options or {}

    # ------------------------------------------------------------------

    def _url(self) -> str:
        # accept both ".../v1" and a bare host
        base = self.base_url
        if not base.endswith("/v1") and "/v1/" not in base:
            base = f"{base}/v1"
        return f"{base}/chat/completions"

    def _headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _messages(self, prompt, system=None, images=None) -> list[dict]:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        if images:
            content = [{"type": "text", "text": prompt}]
            for image in images:
                content.append(
                    {"type": "image_url", "image_url": {"url": _image_data_url(image)}}
                )
            messages.append({"role": "user", "content": content})
        else:
            messages.append({"role": "user", "content": prompt})
        return messages

    # ------------------------------------------------------------------

    def generate(
        self,
        prompt,
        *,
        model=None,
        system=None,
        images=None,
        temperature=None,
        num_predict=None,
        timeout=None,
        json_mode=False,
        **_ignored,
    ) -> str:
        """Plain text out. Signature mirrors OllamaProvider.generate."""
        if not self.base_url:
            raise OllamaUnavailable("آدرس سرویس هوش مصنوعی تنظیم نشده است.")

        payload = {
            "model": model or self.model,
            "messages": self._messages(prompt, system, images),
        }
        if temperature is not None:
            payload["temperature"] = temperature
        if num_predict:
            payload["max_tokens"] = num_predict
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        payload.update(self.options)

        wait = timeout or self.timeout
        last: Exception | None = None

        for attempt in range(1, RETRIES + 2):
            started = time.monotonic()
            try:
                response = requests.post(
                    self._url(), json=payload, headers=self._headers(), timeout=wait
                )
            except requests.Timeout as exc:
                last = OllamaTimeout(f"سرویس در {wait} ثانیه پاسخ نداد.")
                logger.warning("openai-compat timeout (try %s): %s", attempt, exc)
            except requests.RequestException as exc:
                last = OllamaUnavailable(f"اتصال به سرویس ممکن نشد: {exc}")
                logger.warning("openai-compat unreachable (try %s): %s", attempt, exc)
            else:
                if response.status_code == 401:
                    raise OllamaUnavailable("کلید API پذیرفته نشد (۴۰۱).")
                if response.status_code == 429:
                    last = OllamaUnavailable("سهمیه‌ی سرویس تمام شده است (۴۲۹).")
                elif response.status_code >= 400:
                    detail = response.text[:300]
                    last = OllamaError(f"خطای سرویس {response.status_code}: {detail}")
                    # a bad request will fail again identically — do not retry
                    if response.status_code < 500:
                        raise last
                else:
                    text = self._text_from(response.json())
                    logger.info(
                        "openai-compat %s ok in %.1fs",
                        payload["model"], time.monotonic() - started,
                    )
                    return strip_reasoning(text)

            if attempt <= RETRIES:
                time.sleep(BACKOFF ** attempt)

        raise last or OllamaError("سرویس هوش مصنوعی پاسخ نداد.")

    @staticmethod
    def _text_from(data: dict) -> str:
        try:
            message = data["choices"][0]["message"]
        except (KeyError, IndexError, TypeError):
            raise OllamaMalformedOutput("پاسخ سرویس ساختار مورد انتظار را نداشت.")
        content = message.get("content")
        if isinstance(content, list):  # some gateways return content parts
            content = "".join(
                part.get("text", "") for part in content if isinstance(part, dict)
            )
        return content or ""

    # ------------------------------------------------------------------

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
        schema_keys=None,
    ):
        """Structured output. **Signature and return type match OllamaProvider.**

        That is not cosmetic. `apps.ai.services._single_call` calls this with a
        positional model and unpacks `(parsed, raw)`; when this method took only
        a keyword model and returned a bare dict, every switch of TEXT to an API
        died with a TypeError before the first request left the machine. Nothing
        caught it because every test at that layer mocks the provider — the
        mismatch only appears against a real row.

        Returns:
            (parsed_dict, raw_text)
        """
        json_options = {"temperature": 0.2}
        json_options.update(options or {})

        text = self.generate(
            prompt,
            model=model or self.model,
            system=system,
            images=images,
            json_mode=True,
            temperature=json_options.get("temperature"),
            num_predict=json_options.get("num_predict"),
            timeout=timeout,
        )

        parsed = extract_json_block(text)
        if parsed is None:
            parsed = repair_json(text)
        if parsed is None and repair_attempts > 0:
            # Same ladder as the local provider: hand the broken output back
            # once with the complaint attached. Remote models fail this way for
            # the same reason local ones do — a stray sentence before the brace.
            text = self.generate(
                f"{prompt}\n\nخروجی قبلی JSON معتبر نبود. فقط JSON برگردان، بدون توضیح.",
                model=model or self.model,
                system=system,
                json_mode=True,
                temperature=0,
                timeout=timeout,
            )
            parsed = extract_json_block(text) or repair_json(text)
        if parsed is None:
            raise OllamaMalformedOutput(
                f"خروجی سرویس JSON معتبر نبود: {text[:200]}"
            )
        if schema_keys:
            missing = [key for key in schema_keys if key not in parsed]
            if missing:
                raise OllamaMalformedOutput(
                    f"کلیدهای لازم در خروجی نبود: {', '.join(missing)}"
                )
        return parsed, text

    # ------------------------------------------------------------------

    def health(self) -> tuple[bool, str]:
        """Cheap reachability probe for the admin's «تست اتصال»."""
        if not self.base_url:
            return False, "آدرس تنظیم نشده است."
        try:
            self.generate("ping", num_predict=4, timeout=20)
        except OllamaError as exc:
            return False, str(exc)
        except Exception as exc:  # noqa: BLE001 — surface anything to the admin
            return False, f"{type(exc).__name__}: {exc}"
        return True, "پاسخ داد."


def json_default(obj):
    """Small helper so callers can dump options safely."""
    return json.dumps(obj, ensure_ascii=False)
