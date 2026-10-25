"""The three GPU audio engines of the processing nodes, as the site sees them.

    moss   MOSS-TTS-Realtime + Persian LoRA   speech and voice cloning   Apache-2.0      voice.tts / voice.clone (engine moss-fa)
    sfx    MOSS-SoundEffect v2.0              ambience and effects       Apache-2.0      voice.sfx
    music  ACE-Step 1.5                       instrumental music beds    MIT             voice.music

All three are commercially usable, unlike Pocket (CC-BY-NC) and the unofficial Edge voices. They run only on
a processing node (agent 1.7+, after Download-Models.bat): each node reports `capabilities.audio` =
{"moss": bool, "sfx": bool, "music": bool}, and jobs go to a node that has the engine (node_wanted). A node
without the models would only fail the job, so the site says why before queueing anything.

MOSS speaks in the voice of a reference clip. The default voices are the reference clips shipped with the
voice kit (processing/tools/PersianAiKit/Voice/voice/voices) whose licence allows commercial use, plus the
Persian LoRA's own reference; a shop's cloned voice brings its own reference (services.audio.voice_clone).
"""
from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path

from django.conf import settings

from .tts import BaseTTSProvider, TTSError, _require_output

logger = logging.getLogger(__name__)

ENGINES = {
    "moss": {"label": "MOSS-TTS فارسی", "what": "گفتار و کلونِ صدا", "license": "Apache-2.0", "commercial": True,
             "package": "moss-tts", "gb": 15, "kinds": ("voice.tts", "voice.clone")},
    "sfx": {"label": "MOSS-SoundEffect", "what": "صدای محیط و افکت", "license": "Apache-2.0", "commercial": True,
            "package": "moss-sfx", "gb": 12, "kinds": ("voice.sfx",)},
    "music": {"label": "ACE-Step 1.5", "what": "موسیقیِ زمینه", "license": "MIT", "commercial": True,
              "package": "acestep", "gb": 12, "kinds": ("voice.music",)},
}

KIT_VOICES = (Path(settings.BASE_DIR).parent / "processing" / "tools" / "PersianAiKit" / "Voice" / "voice" / "voices"
              / "voices.json")
#: licences of a reference clip that keep MOSS's output commercially usable
COMMERCIAL_REF_LICENSES = {"CC0", "MIT", "Apache-2.0", "CC-BY-4.0"}
#: the LoRA repository's own reference (Apache-2.0); not in the kit, the node has it in models\moss-tts\persian-lora
LORA_PRESET = {"id": "lora", "name": "نسیم", "gender": "female", "note": "صدای پیش‌فرضِ مدل؛ زن، طبیعی",
               "source": "MOSS-TTS-Realtime-Persian-lora", "license": "Apache-2.0"}
GENDER = {"زن": "female", "مرد": "male", "female": "female", "male": "male"}


class NodeAudioError(Exception):
    """Said in Persian; `code` is one of offline | missing | old_agent."""

    def __init__(self, message, code="offline"):
        super().__init__(message)
        self.code = code


# ───────────────────────────── default MOSS voices

def presets() -> list[dict]:
    """The reference voices MOSS can speak in without any recording from the shop."""
    rows = []
    try:
        data = json.loads(KIT_VOICES.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = []
    for row in data:
        if not isinstance(row, dict) or row.get("license") not in COMMERCIAL_REF_LICENSES:
            continue          # Pocket's sample voices are CC-BY-NC: never a reference for commercial speech
        rows.append({"id": row["id"], "name": row.get("name") or row["id"], "gender": GENDER.get(row.get("gender"), "male"),
                     "note": row.get("note") or "", "license": row.get("license"), "source": row.get("source") or ""})
    rows.append(dict(LORA_PRESET))
    order = {"mana": 0, "lora": 1}
    return sorted(rows, key=lambda r: (r["gender"] != "female", order.get(r["id"], 9), r["name"]))


def preset(voice_id: str) -> dict | None:
    voice_id = (voice_id or "").replace("preset:", "").replace("moss:", "")
    return next((p for p in presets() if p["id"] == voice_id), None)


def default_preset(gender: str = "male") -> str:
    return "mana" if gender == "female" else "arash"


# ───────────────────────────── which node has which engine

#: the four switches of «سرورهای پردازش › مدل‌های صدا» and the engine each one uses
ROWS = {"speech": "moss", "clone": "moss", "sfx": "sfx", "music": "music"}
OFF_MESSAGE = {
    "speech": "گفتارِ MOSS برای سرورِ پردازش خاموش است (سرورهای پردازش › مدل‌های صدا)؛ گویندهٔ بعدیِ فهرست می‌خواند.",
    "clone": "کلونِ صدا خاموش است (سرورهای پردازش › مدل‌های صدا).",
    "sfx": "صدای محیطِ ساختهٔ ماشین خاموش است (سرورهای پردازش › مدل‌های صدا)؛ صداهای کتابخانه و صدای ساخته‌شده با کد به "
           "کار می‌روند.",
    "music": "موسیقیِ ساختهٔ ماشین خاموش است (سرورهای پردازش › مدل‌های صدا)؛ از کتابخانهٔ صداها یا موسیقیِ خودتان "
             "استفاده کنید.",
}


def node_settings(desired) -> dict:
    """The panel's switches for one node (ComputeNode.desired["audio"]); missing = on, unload after 15 minutes."""
    d = (desired or {}).get("audio") or {}
    out = {k: d.get(k) is not False for k in ROWS}
    try:
        out["idle_min"] = max(1, min(240, int(d.get("idle_min") or 15)))
    except (TypeError, ValueError):
        out["idle_min"] = 15
    return out


def _purpose_for(key: str, purpose) -> str:
    return purpose if purpose in ROWS else next(r for r, k in ROWS.items() if k == key)


def node_rows() -> list[dict]:
    from apps.compute.models import ComputeNode

    rows = []
    for node in ComputeNode.objects.filter(enabled=True).order_by("name"):
        caps = node.capabilities or {}
        audio = caps.get("audio") if isinstance(caps.get("audio"), dict) else None
        rows.append({"name": node.name, "online": node.online, "agent": caps.get("agent") or "", "audio": audio,
                     "gpu": caps.get("gpu") or "", "last_seen": node.last_seen,
                     "running": {k: bool(caps.get(k)) for k in ENGINES},
                     "settings": node_settings(node.desired), "models": caps.get("models") or {}})
    return rows


def downloading(row: dict, key: str):
    """None, or how far this node's background download of the engine's models is (0-100)."""
    models = row.get("models") or {}
    if not models.get("running"):
        return None
    pkg = ENGINES[key]["package"]
    pr = models.get("progress") or {}
    in_run = pkg in (pr.get("packages") or []) or not ((models.get("packages") or {}).get(pkg) or {}).get("installed", True)
    if not in_run:
        return None
    total = pr.get("bytes_total") or 0
    return round(100.0 * (pr.get("bytes_done") or 0) / total, 1) if total else 0.0


def status() -> dict:
    """For the panel: per engine, is it usable right now, and if not, what exactly to do."""
    rows = node_rows()
    out = {}
    for key, eng in ENGINES.items():
        installed = [r["name"] for r in rows if (r["audio"] or {}).get(key)]
        purpose = _purpose_for(key, None)
        online = [r["name"] for r in rows if r["online"] and (r["audio"] or {}).get(key) and r["settings"][purpose]]
        code = ""
        try:
            pick_node(key, rows=rows, purpose=purpose)
            message = ""
        except NodeAudioError as exc:
            message, code = str(exc), exc.code
        pct = next((d for d in (downloading(r, key) for r in rows if r["online"]) if d is not None), None)
        out[key] = {**{k: v for k, v in eng.items() if k != "kinds"}, "ready": bool(online), "installed_on": installed,
                    "online_on": online, "message": message, "code": code, "downloading": pct,
                    "enabled": any(r["settings"][purpose] for r in rows) if rows else True}
    return {"engines": out, "nodes": [{k: v for k, v in r.items() if k != "last_seen"} | {
        "last_seen": r["last_seen"].isoformat() if r["last_seen"] else None} for r in rows]}


def _gb(key):
    return ENGINES[key]["gb"]


def pick_node(key: str, prefer: str = "", rows=None, purpose=None, allow_pending: bool = False) -> str:
    """A node that is online, has this engine installed and switched on (for this purpose). Raises NodeAudioError
    saying what to do. allow_pending: a node still downloading the models is good enough (the job waits in the queue
    until the model is there - compute.claim keeps it back)."""
    rows = rows if rows is not None else node_rows()
    eng = ENGINES[key]
    purpose = _purpose_for(key, purpose)
    ready = [r for r in rows if r["online"] and (r["audio"] or {}).get(key) and r["settings"][purpose]]
    if ready:
        names = [r["name"] for r in ready]
        return prefer if prefer in names else names[0]
    online = [r for r in rows if r["online"]]
    if online and not any(r["settings"][purpose] for r in online):
        raise NodeAudioError(OFF_MESSAGE[purpose], "disabled")
    pending = [r for r in online if r["settings"][purpose] and downloading(r, key) is not None]
    if pending:
        if allow_pending:
            return pending[0]["name"]
        raise NodeAudioError(
            f"مدل‌های {eng['label']} روی سرورِ پردازش ({pending[0]['name']}) در حالِ دانلود است "
            f"({downloading(pending[0], key):.0f}٪) و بعد از پایانِ دانلود آماده می‌شود.", "downloading")
    if not online:
        seen = "، ".join(f"«{r['name']}»" for r in rows[:2]) or "هیچ سروری ثبت نشده"
        raise NodeAudioError(
            f"{eng['label']} ({eng['what']}) فقط روی سرورِ پردازش (کامپیوترِ گرافیکی) اجرا می‌شود و الان هیچ سرورِ "
            f"پردازشی روشن نیست ({seen}). آن کامپیوتر را روشن و START.bat را اجرا کنید.", "offline")
    old = [r for r in online if r["audio"] is None]
    if old and len(old) == len(online):
        raise NodeAudioError(
            f"نسخهٔ عاملِ سرورِ پردازش ({old[0]['agent'] or '?'}) هنوز {eng['label']} را نمی‌شناسد. روی آن کامپیوتر پوشهٔ "
            "پردازش را به‌روز کنید (git pull) و START.bat را دوباره باز کنید.", "old_agent")
    raise NodeAudioError(
        f"مدل‌های {eng['label']} ({eng['what']}) روی سرورِ پردازش ({online[0]['name']}) نصب نیست. در «سرورهای پردازش › "
        f"مدل‌های صدا» دکمهٔ «دانلود» را بزنید، یا START.bat را روی آن کامپیوتر دوباره باز کنید تا خودش دانلود کند "
        f"(حدود {_gb(key)} گیگابایت).", "missing")


def friendly(error: str) -> str:
    text = (error or "").strip()
    if "MODELS_MISSING" in text:
        return text.split("|", 1)[1].strip() if "|" in text else text
    from .voice_clone import friendly as clone_friendly

    return clone_friendly(text)


# ───────────────────────────── jobs

def enqueue(key: str, kind: str, payload: dict, files: dict | None = None, *, store=None, origin: str = "audio",
            timeout_s: int = 1200, prefer: str = "", dedupe: bool = True, priority: int = 60, purpose=None,
            allow_pending: bool = False):
    from apps.compute import services as compute

    node = pick_node(key, prefer, purpose=purpose, allow_pending=allow_pending)
    try:
        return compute.enqueue(kind, payload, files or {}, store=store, origin=origin, priority=priority,
                               timeout_s=timeout_s, node=node, dedupe=dedupe)
    except compute.ComputeUnavailable as exc:
        raise NodeAudioError(str(exc), "offline") from exc


def output_file(job, suffix: str = ".wav") -> Path | None:
    from apps.compute import services as compute

    for out in job.outputs():
        if str(out.get("name", "")).lower().endswith(suffix):
            path = compute.output_path(job, out["name"])
            if path.is_file():
                return path
    return None


def run_and_wait(key: str, kind: str, payload: dict, files: dict | None = None, *, store=None, origin="audio",
                 wait_s: int = 1200, prefer: str = "", purpose=None) -> Path:
    """Enqueue on a node with the engine and wait (Celery tasks, short web requests). Raises NodeAudioError."""
    from apps.compute import services as compute

    job = enqueue(key, kind, payload, files, store=store, origin=origin, timeout_s=wait_s, prefer=prefer, purpose=purpose)
    try:
        job = compute.wait(job, wait_s)
    except compute.ComputeError as exc:
        job.refresh_from_db()
        raise NodeAudioError(friendly(job.error or str(exc)), "failed") from exc
    path = output_file(job)
    if path is None:
        raise NodeAudioError("سرورِ پردازش فایلِ صوتی برنگرداند.", "failed")
    return path


# ───────────────────────────── narration: MOSS as a voice engine (AudioEngine kind NODE_MOSS)

class NodeMossProvider(BaseTTSProvider):
    """Persian narration with MOSS-TTS on a processing node, in one of the default reference voices.
    A failure raises TTSError, so the admin's next engine (Edge, Piper) takes over - unlike a cloned voice."""

    name = "moss"
    is_local = True            # our own processing server: the text stays inside the company
    wait_s = 900

    def __init__(self, voice_id: str):
        self.voice = (voice_id or "arash").replace("preset:", "").replace("moss:", "")
        row = preset(self.voice) or {}
        self.processor = f"MOSS-TTS فارسی روی سرورِ پردازش — صدای «{row.get('name') or self.voice}» (Apache-2.0)"
        self._takes: dict[str, int] = {}

    def synthesize(self, text: str, out_path) -> Path:
        out = Path(out_path).with_suffix(".wav")
        out.parent.mkdir(parents=True, exist_ok=True)
        takes = self._takes.get(text, 0)
        self._takes[text] = takes + 1
        payload = {"text": text, "engine": "moss-fa", "voice": self.voice, "out": "speech.wav", "strict": True}
        if takes:
            payload["seed"] = 7919 * takes + len(text)      # a retake must be a different take
        try:
            path = run_and_wait("moss", "voice.tts", payload, origin="narration", wait_s=self.wait_s, purpose="speech")
        except NodeAudioError as exc:
            raise TTSError(str(exc)) from exc
        shutil.copyfile(path, out)
        return _require_output(out, "MOSS-TTS")

    def describe(self) -> dict:
        out = super().describe()
        out.update({"license": "Apache-2.0", "commercial": True})
        return out


def moss_ready() -> tuple[bool, str]:
    """Readiness of the NODE_MOSS / NODE_SFX engine rows: a node is on and has the models."""
    try:
        pick_node("moss", purpose="speech")
        return True, ""
    except NodeAudioError as exc:
        return False, str(exc)


def sfx_ready() -> tuple[bool, str]:
    try:
        pick_node("sfx", purpose="sfx")
        return True, ""
    except NodeAudioError as exc:
        return False, str(exc)
