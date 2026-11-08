"""«مدل‌های سرورِ پردازش»: همهٔ بسته‌های دانلودیِ گره در یک فهرست — نه فقط Ollama.

مالک (۱۴۰۵/۰۸/۱۷): «دانلودِ مدل‌ها برای اولاما گذاشتی؛ چرا برای مدل‌های حذفِ پس‌زمینه برای عکس و ویدیو، هاگینگ‌فیس و …
نگذاشتی». بسته‌ها همان‌هایی‌اند که `processing/downloads/*.json` تعریف می‌کند (حذفِ پس‌زمینه، صدا، ویدیوی Wan، …).

* فهرست و حجم از همان فایل‌های json ِ سایت (همان درختی که گره با Update.bat می‌گیرد) خوانده می‌شود؛
* وضعیتِ نصب، حجمِ مانده، دانلودِ در جریان و «منتظرِ بازهٔ شبانه» از گزارشِ خودِ گره (`capabilities.models`، عامل ۱٫۸ به بعد)؛
* دانلودهای در صف (کارِ node.models که هنوز به گره نرسیده) هم کنارِ هر بسته گفته می‌شود.

دانلود خودش همان راهِ همیشگی است: `POST /api/v1/compute/nodes/<id>/models/download/ {packages, when}` ⇒ کارِ node.models ⇒
عامل `download_models.py --only <بسته‌ها>` را در پس‌زمینه اجرا می‌کند (ادامه‌پذیر، sha256، بازهٔ شبانه).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from django.conf import settings

from .models import ComputeJob, ComputeNode

logger = logging.getLogger(__name__)

#: گروه‌های نمایشی ⇐ گروه‌های فایل‌های json (photo.json ِ BiRefNet کنارِ حذفِ پس‌زمینه می‌آید)
GROUPS = [
    {"key": "matting", "title": "حذفِ پس‌زمینه (عکس و ویدیو)", "from": ("matting", "photo"),
     "note": "مدل‌ها فقط روی سرورِ پردازش اجرا می‌شوند. «اجرا روی کارتِ گرافیک» را هم بگیرید تا سریع‌تر شود."},
    {"key": "voice", "title": "صدا: گفتار، افکت و موسیقی", "from": ("voice",), "note": ""},
    {"key": "video", "title": "ویدیوی هوش مصنوعی (Wan)", "from": ("video",),
     "note": "سنگین‌اند (چند ده گیگابایت)؛ بهتر است در بازهٔ شبانه دانلود شوند."},
]
OTHER = {"key": "other", "title": "دیگر بسته‌ها", "from": (), "note": ""}

#: بسته ⇒ (نامِ فارسی، توضیحِ کوتاه). بسته‌ای که این‌جا نیست با نامِ انگلیسیِ خودش می‌آید.
LABELS = {
    "photo-background": ("حذفِ پس‌زمینهٔ عکس — BiRefNet سبک", "دقیق‌ترین مدلِ عکس؛ ادیتورِ عکس با آن کار می‌کند"),
    "matting-isnet": ("حذفِ پس‌زمینهٔ عکس — IS-Net", "کیفیتِ خوب با حجمِ متوسط"),
    "matting-u2netp": ("حذفِ پس‌زمینهٔ عکس — U²-Net سبک", "خیلی کوچک و سریع؛ کیفیتِ معمولی"),
    "video-matting": ("حذفِ پس‌زمینهٔ ویدیو — RVM", "فریم‌به‌فریم و پایدار، برای ویرایشگرِ ویدیو"),
    "matting-runtime": ("اجرای حذفِ پس‌زمینه روی کارتِ گرافیک",
                        "onnxruntime-directml در محیطی جدا؛ بی آن، حذفِ پس‌زمینه روی پردازندهٔ معمولی (کند) اجرا می‌شود"),
    "python": ("پایتونِ ۳٫۱۲", "فقط اگر روی سرور نباشد نصب می‌شود"),
    "moss-code": ("کدِ MOSS", "لازمِ گفتارِ فارسی و صدای محیط"),
    "moss-tts": ("گفتارِ فارسی و کلونِ صدا (MOSS-TTS)", ""),
    "moss-sfx": ("صدای محیط و افکت (MOSS-SFX)", ""),
    "acestep": ("موسیقیِ زمینه (ACE-Step)", ""),
    "wan22-flf": ("ویدیوی هوش مصنوعی — Wan 2.2 (کیفیتِ بالا)", "و «ساختِ دوبارهٔ یک تکه»"),
    "wan22-4step": ("Wan 2.2 — LoRAِ ۴ گامی", "ساختِ سریع‌ترِ ویدیو"),
    "wan-i2v-legacy": ("Wan 2.2 — LoRAِ ۸ گامیِ پروفایل‌های قدیمی", "پروفایل‌های ۴۸۰p"),
    "fun-inp": ("ساختِ دوبارهٔ سریعِ تکه — Wan Fun-InP 1.3B", "کاملاً در کارتِ ۱۲ گیگابایتی جا می‌شود"),
}

_cache: dict = {"key": None, "data": None}


def downloads_dir() -> Path:
    return Path(getattr(settings, "NM_PROCESSING_DIR", "") or (Path(settings.BASE_DIR).parent / "processing")) / "downloads"


def catalog() -> dict:
    """{بسته: {group, title, optional, size_mb}} از processing/downloads/*.json (با کش بر اساسِ زمانِ تغییرِ فایل‌ها)."""
    folder = downloads_dir()
    try:
        files = sorted(folder.glob("*.json"))
        key = tuple((f.name, f.stat().st_mtime) for f in files)
    except OSError:
        return {}
    if _cache["key"] == key and _cache["data"] is not None:
        return _cache["data"]
    out: dict = {}
    for f in files:
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.warning("model packages: cannot read %s: %s", f.name, exc)
            continue
        if not isinstance(d, dict):
            continue
        group = str(d.get("group") or f.stem)
        titles = d.get("packages") if isinstance(d.get("packages"), dict) else {}
        for item in d.get("items") or []:
            if not isinstance(item, dict):
                continue
            pk = str(item.get("package") or item.get("id") or "").strip()
            if not pk:
                continue
            row = out.setdefault(pk, {"group": group, "title": "", "optional": True, "size": 0, "items": 0})
            try:
                row["size"] += int(item.get("size") or 0)
            except (TypeError, ValueError):
                pass
            row["items"] += 1
            row["optional"] = row["optional"] and bool(item.get("optional"))
            t = titles.get(pk)
            row["title"] = (t if isinstance(t, str) else "") or row["title"] or str(item.get("title") or "")
    for row in out.values():
        row["size_mb"] = round(row.pop("size") / 2 ** 20)
    _cache.update(key=key, data=out)
    return out


def _display_group(json_group: str, package: str) -> str:
    for g in GROUPS:
        if json_group in g["from"]:
            return g["key"]
    p = package.lower()
    if p.startswith("matting") or "background" in p:
        return "matting"
    if p.startswith(("moss", "acestep", "voice")):
        return "voice"
    if p.startswith(("wan", "fun-")):
        return "video"
    return "other"


def _queued_downloads(node: ComputeNode) -> dict:
    """{بسته: متنِ صف} برای کارهای node.models ِ همین گره که هنوز تمام نشده‌اند."""
    out: dict = {}
    for j in ComputeJob.objects.filter(kind="node.models", node_wanted=node.name,
                                       state__in=[ComputeJob.State.QUEUED, ComputeJob.State.CLAIMED, ComputeJob.State.RUNNING]):
        p = j.payload or {}
        if p.get("action") not in (None, "", "download"):
            continue
        text = j.message or ("در صف" if j.state == ComputeJob.State.QUEUED else "به سرور رسید")
        for pk in p.get("packages") or []:
            out[str(pk)] = text
    return out


def for_node(node: ComputeNode) -> dict:
    caps = node.capabilities or {}
    models = caps.get("models") if isinstance(caps.get("models"), dict) else {}
    status = models.get("packages") if isinstance(models.get("packages"), dict) else {}
    cat = catalog()
    queued = _queued_downloads(node)
    progress = models.get("progress") if isinstance(models.get("progress"), dict) else None
    waiting = models.get("waiting") if isinstance(models.get("waiting"), dict) else None
    running_pkgs = set((progress or {}).get("packages") or []) if models.get("running") else set()
    waiting_pkgs = set((waiting or {}).get("packages") or [])

    keys = list(cat) + [k for k in status if k not in cat]
    groups: dict = {g["key"]: {**g, "packages": []} for g in GROUPS + [OTHER]}
    for key in keys:
        c = cat.get(key) or {}
        s = status.get(key) if isinstance(status.get(key), dict) else None
        fa_title, note = LABELS.get(key, ("", ""))
        installed = None if s is None else bool(s.get("installed"))
        if key in running_pkgs:
            state = "downloading"
        elif installed:
            state = "installed"
        elif key in waiting_pkgs:
            state = "waiting_window"
        elif key in queued:
            state = "queued"
        elif installed is None:
            state = "unknown"
        else:
            state = "missing"
        row = {
            "key": key,
            "title": fa_title or (s or {}).get("title") or c.get("title") or key,
            "title_en": (s or {}).get("title") or c.get("title") or "",
            "note": note,
            "optional": bool((s or {}).get("optional", c.get("optional", False))),
            "installed": installed,
            "state": state,
            "queued_text": queued.get(key, ""),
            "total_mb": int((s or {}).get("total_mb") or c.get("size_mb") or 0),
            "missing_mb": None if s is None else int(s.get("missing_mb") or 0),
            "in_comfyui": int((s or {}).get("in_comfyui") or 0),
        }
        groups[_display_group(str(c.get("group") or ""), key)]["packages"].append(row)
    out_groups = [{"key": g["key"], "title": g["title"], "note": g["note"], "packages": g["packages"]}
                  for g in groups.values() if g["packages"]]
    return {
        "node": {"id": node.pk, "name": node.name, "online": node.online, "enabled": node.enabled,
                 "agent": caps.get("agent"), "last_seen": node.last_seen},
        "reported": bool(status),
        "running": bool(models.get("running")),
        "progress": progress,
        "waiting": waiting,
        "error": str(models.get("error") or "")[:300],
        "groups": out_groups,
    }


def listing() -> dict:
    nodes = [n for n in ComputeNode.objects.all() if n.enabled]
    nodes.sort(key=lambda n: (not n.online, n.name))
    return {"nodes": [for_node(n) for n in nodes], "ollama_page": "/admin/providers"}
