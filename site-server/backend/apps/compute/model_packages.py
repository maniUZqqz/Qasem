"""«مدل‌های سرورِ پردازش»: همهٔ بسته‌های دانلودیِ گره در یک فهرست — نه فقط Ollama.

مالک (۱۴۰۵/۰۸/۱۷): «دانلودِ مدل‌ها برای اولاما گذاشتی؛ چرا برای مدل‌های حذفِ پس‌زمینه برای عکس و ویدیو، هاگینگ‌فیس و …
نگذاشتی». (۱۴۰۵/۰۸/۲۳): «قرار بود هاگینگ‌فیس، ComfyUI و منبع‌های دیگرِ مفید هم باشد» — بسته‌ها همان‌هایی‌اند که
`processing/downloads/*.json` تعریف می‌کند (حذفِ پس‌زمینه، صدا، ویدیوی Wan، و کاتالوگِ تازه: تصویر FLUX/SDXL، بزرگ‌کردن و ترمیمِ
چهره، ControlNet و IP-Adapter، عمق، Wan 5B و LTX و RIFE).

* فهرست و حجم از همان فایل‌های json ِ سایت (همان درختی که گره با Update.bat می‌گیرد) خوانده می‌شود؛ هر بسته می‌تواند
  `package_info` داشته باشد: گروهِ نمایشی، متنِ فارسی، مجوز (`license_class`: open / restricted / noncommercial)، جای‌گیریِ VRAM،
  «کجا به کار می‌آید» (`features`)، «به چه نیاز دارد» (`needs`) و «خودکار» (`auto`)؛
* وضعیتِ نصب، حجمِ مانده، دانلودِ در جریان و «منتظرِ بازهٔ شبانه» از گزارشِ خودِ گره (`capabilities.models`)؛
* دانلودهای در صف (کارِ node.models که هنوز به گره نرسیده) هم کنارِ هر بسته گفته می‌شود؛
* فضای خالیِ گره و اینکه هر بسته در آن جا می‌شود یا نه (`fits`)، و وضعیتِ «دانلودِ خودکار» (`auto_models.py`).

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

#: ترتیبِ نمایش: تصویر، ویدیو، بزرگ‌کردن و ترمیم، کنترل و ثبات، عمق و سه‌بعدی، صدا، حذفِ پس‌زمینه
GROUPS = [
    {"key": "image", "title": "تصویر: ساختِ عکس با هوش مصنوعی", "from": ("image",),
     "note": "FLUX و SDXL روی ComfyUI. همه روی کارتِ ۱۲ گیگابایتی کار می‌کنند؛ مدل‌های سنگین‌تر کمی کندترند. مدل‌های «غیرتجاری» هرگز خودکار دانلود نمی‌شوند."},
    {"key": "video", "title": "ویدیوی هوش مصنوعی و نرم‌کردنِ حرکت", "from": ("video", "video-extra"),
     "note": "Wan ۲٫۲ سنگین‌اند (چند ده گیگابایت)؛ بهتر است در بازهٔ شبانه دانلود شوند. Wan ۵B و LTX سبک‌ترند."},
    {"key": "upscale", "title": "بزرگ‌کردن و ترمیمِ عکس", "from": ("upscale",),
     "note": "بزرگ‌کردنِ ۴ برابریِ عکس و ترمیمِ چهره؛ همه کوچک‌اند."},
    {"key": "control", "title": "کنترل و ثبات (ControlNet و IP-Adapter)", "from": ("control",),
     "note": "نگه‌داشتنِ ژست، چیدمان، سبک و چهره از روی عکسِ مرجع."},
    {"key": "depth", "title": "عمق و سه‌بعدی", "from": ("depth", "multiangle"),
     "note": "نقشهٔ عمق برای ویدیوی سه‌بعدی، پارالکس و چندزاویه (حرکتِ دوربینِ ۲٫۵بعدی)."},
    {"key": "voice", "title": "صدا: گفتار، افکت و موسیقی", "from": ("voice",), "note": ""},
    {"key": "matting", "title": "حذفِ پس‌زمینه (عکس و ویدیو)", "from": ("matting", "photo"),
     "note": "مدل‌ها فقط روی سرورِ پردازش اجرا می‌شوند. «اجرا روی کارتِ گرافیک» را هم بگیرید تا سریع‌تر شود."},
]
OTHER = {"key": "other", "title": "دیگر بسته‌ها", "from": (), "note": ""}

#: «کجا به کار می‌آید»: کلید ⇒ (برچسبِ فارسی، سوئیچِ دانلودِ خودکار؟، پیش‌فرضِ روشن بودن). سوئیچ‌دارها در صفحهٔ «دانلودِ مدل‌ها» قابلِ
#: خاموش/روشن‌اند؛ بقیه فقط برچسبِ «به چه کاری می‌آید» هستند.
FEATURES = {
    "image_studio": ("ساختِ تصویر (استودیوی تصویر)", True, True),
    "photo_enhance": ("بزرگ‌کردنِ عکس (ادیتورِ عکس)", True, True),
    "smooth_motion": ("نرم‌کردنِ حرکتِ ویدیو", True, True),
    "depth_3d": ("عمق و ویدیوی سه‌بعدی", True, True),
    "design_styles": ("سبک‌های طراحی (SDXL، ControlNet، IP-Adapter)", True, False),
    "video_ai": ("ویدیوی هوش مصنوعیِ سبک (Wan 5B)", True, False),
    "face_restore": ("ترمیمِ چهره", True, False),
    "thumbnails": ("بندانگشتی و پستِ شبکه‌های اجتماعی", False, False),
    "consistency": ("ثباتِ چهره و سبک", False, False),
    "image_edit": ("ویرایشِ تصویر با دستور و پرکردنِ بخشی از عکس", False, False),
    "photo_matting": ("ادیتورِ عکس: حذفِ پس‌زمینه", False, False),
    "video_matte": ("ویرایشگرِ ویدیو: حذفِ پس‌زمینه", False, False),
    "voice_studio": ("استودیوی صدا (گفتار، افکت، موسیقی)", False, False),
    "video_wan": ("ویدیوی هوش مصنوعی (Wan ۲٫۲) و ساختِ دوبارهٔ یک تکه", False, False),
    "multiangle": ("چندزاویه از یک دوربین (ویرایشگرِ ویدیو)", False, False),
}

#: بسته ⇒ (نامِ فارسی، توضیحِ کوتاه). بسته‌ای که این‌جا نیست از package_info ِ manifest یا با نامِ انگلیسیِ خودش می‌آید.
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
    "multiangle-runtime": ("چندزاویه — محیطِ پایتون (OpenCV، onnxruntime-directml)", "خودِ سرور آن را نصب می‌کند؛ روی کارتِ گرافیک اجرا می‌شود"),
    "multiangle-detect": ("چندزاویه — تشخیصِ چهره و آدم (YuNet، YOLOS-tiny)", "کوچک؛ می‌داند چه کسی کجای قاب است"),
    "multiangle-depth": ("چندزاویه — عمق (Depth-Anything-V2-Small، ONNX)", "برای حرکتِ دوربینِ ۲٫۵بعدی"),
}

#: بسته‌های قدیمی (manifest‌شان package_info ندارد): گروه، مجوز، VRAM و «کجا به کار می‌آید»
_OLD = {
    "photo-background": ("matting", "MIT", "open", "full", ["photo_matting"]),
    "matting-isnet": ("matting", "Apache-2.0", "open", "full", ["photo_matting"]),
    "matting-u2netp": ("matting", "Apache-2.0", "open", "full", ["photo_matting"]),
    "video-matting": ("matting", "GPL-3.0", "open", "full", ["video_matte"]),
    "matting-runtime": ("matting", "MIT", "open", "full", ["photo_matting", "video_matte"]),
    "python": ("voice", "PSF", "open", "", ["voice_studio"]),
    "moss-code": ("voice", "Apache-2.0", "open", "", ["voice_studio"]),
    "moss-tts": ("voice", "Apache-2.0", "open", "offload", ["voice_studio"]),
    "moss-sfx": ("voice", "Apache-2.0", "open", "offload", ["voice_studio"]),
    "acestep": ("voice", "MIT", "open", "full", ["voice_studio"]),
    "wan22-flf": ("video", "Apache-2.0", "open", "offload", ["video_wan"]),
    "wan22-4step": ("video", "Apache-2.0", "open", "offload", ["video_wan"]),
    "wan-i2v-legacy": ("video", "Apache-2.0", "open", "offload", ["video_wan"]),
    "fun-inp": ("video", "Apache-2.0", "open", "full", ["video_wan"]),
    "multiangle-runtime": ("depth", "BSD-3-Clause / Apache-2.0 / MIT", "open", "full", ["multiangle"]),
    "multiangle-detect": ("depth", "MIT / Apache-2.0", "open", "full", ["multiangle"]),
    "multiangle-depth": ("depth", "Apache-2.0", "open", "full", ["multiangle", "depth_3d"]),
}

VRAM_TEXT = {
    "full": "کاملاً در کارتِ ۱۲ گیگابایتی جا می‌شود",
    "offload": "جا می‌شود؛ بخشی در رم می‌ماند و کمی کندتر است",
    "tight": "سنگین است؛ فقط با کندیِ زیاد روی ۱۲ گیگابایت کار می‌کند",
}
LICENSE_TEXT = {"open": "تجاری مجاز", "restricted": "با شرط", "noncommercial": "فقط غیرتجاری"}
#: فضایی که پس از دانلود باید روی دیسکِ گره بماند (دانلودِ دستی؛ دانلودِ خودکار سقفِ بزرگ‌تری دارد)
MANUAL_RESERVE_MB = 2048

_cache: dict = {"key": None, "data": None}


def downloads_dir() -> Path:
    return Path(getattr(settings, "NM_PROCESSING_DIR", "") or (Path(settings.BASE_DIR).parent / "processing")) / "downloads"


def _repo_of(url: str) -> str:
    """https://huggingface.co/<owner>/<repo>/blob/... ⇒ «owner/repo»؛ هر نشانیِ دیگر همان‌طور."""
    url = str(url or "")
    for prefix in ("https://huggingface.co/", "https://github.com/"):
        if url.startswith(prefix):
            parts = url[len(prefix):].split("/")
            return "/".join(parts[:2]) if len(parts) >= 2 else url
    return url


def catalog() -> dict:
    """{بسته: {group, display, title, title_fa, note_fa, optional, size_mb, license, license_class, vram, features, needs, auto, ...}}
    از processing/downloads/*.json (با کش بر اساسِ زمانِ تغییرِ فایل‌ها)."""
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
        infos = d.get("package_info") if isinstance(d.get("package_info"), dict) else {}
        for item in d.get("items") or []:
            if not isinstance(item, dict):
                continue
            pk = str(item.get("package") or item.get("id") or "").strip()
            if not pk:
                continue
            row = out.setdefault(pk, {"group": group, "title": "", "optional": True, "size": 0, "items": 0, "kinds": [],
                                      "sources": []})
            try:
                row["size"] += int(item.get("size") or 0)
            except (TypeError, ValueError):
                pass
            row["items"] += 1
            row["optional"] = row["optional"] and bool(item.get("optional"))
            t = titles.get(pk)
            row["title"] = (t if isinstance(t, str) else "") or row["title"] or str(item.get("title") or "")
            kind = str(item.get("kind") or "")
            if kind and kind not in row["kinds"]:
                row["kinds"].append(kind)
            src = _repo_of(item.get("source") or item.get("url") or "")
            if src and src not in row["sources"]:
                row["sources"].append(src)
            info = infos.get(pk) if isinstance(infos.get(pk), dict) else {}
            if info and "info" not in row:
                row["info"] = info
    for pk, row in out.items():
        row["size_mb"] = round(row.pop("size") / 2 ** 20)
        info = row.pop("info", {})
        old = _OLD.get(pk)
        klass = str(info.get("license_class") or (old[2] if old else "open"))
        if klass not in LICENSE_TEXT:
            klass = "noncommercial"                     # کلاسِ ناشناخته ⇒ محتاطانه‌ترین
        vram = info.get("vram") if isinstance(info.get("vram"), dict) else ({"fit": old[3]} if old and old[3] else {})
        row.update({
            "display": str(info.get("display") or ""),
            "title_fa": str(info.get("title_fa") or ""), "note_fa": str(info.get("note_fa") or ""),
            "license": str(info.get("license") or (old[1] if old else "")), "license_class": klass,
            "vram": {"fit": str(vram.get("fit") or ""), "gb": vram.get("gb"), "note": str(vram.get("note_fa") or "")},
            "features": [str(x) for x in (info.get("features") or (old[4] if old else []))],
            "needs": [str(x) for x in info.get("needs") or []],
            "auto": bool(info.get("auto")) and klass == "open",
            "priority": int(info.get("priority") or 50),
            "needs_restart": bool(info.get("needs_restart")),
            "provenance": str(info.get("provenance") or ""),
        })
        if klass != "open":
            row["optional"] = True                       # مجوزِ غیرباز ⇒ هرگز در مجموعهٔ پیش‌فرض
    for row in out.values():
        row["size_with_needs_mb"] = row["size_mb"] + sum(out[d]["size_mb"] for d in _closure(out, row["needs"]) if d in out)
    _cache.update(key=key, data=out)
    return out


def _closure(cat: dict, keys) -> list:
    """بسته‌های لازمِ `keys` (گذرا، بی‌تکرار، بی‌خودِ keys)."""
    seen: list = []
    queue = list(keys)
    while queue:
        cur = queue.pop(0)
        if cur in seen:
            continue
        seen.append(cur)
        queue.extend((cat.get(cur) or {}).get("needs") or [])
    return seen


def expand_needs(packages) -> list:
    """نام‌های داده‌شده + هرچه لازم دارند (بی‌تکرار، ترتیبِ پایدار)."""
    cat = catalog()
    out: list = []
    for p in packages:
        for q in [p] + [d for d in _closure(cat, (cat.get(p) or {}).get("needs") or [])]:
            if q not in out:
                out.append(q)
    return out


def _display_group(json_group: str, package: str, display: str = "") -> str:
    keys = {g["key"] for g in GROUPS}
    if display in keys:
        return display
    old = _OLD.get(package)
    if old and old[0] in keys:
        return old[0]
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


# ───────────────────────────── دیسک و بازبینیِ پیش از دانلود

def free_mb(node: ComputeNode):
    """فضای خالیِ جایی که مدل‌ها می‌روند (مگابایت)؛ کوچک‌ترِ دیسکِ داده و دیسکِ ComfyUI. نامعلوم ⇒ None."""
    caps = node.capabilities or {}
    models = caps.get("models") if isinstance(caps.get("models"), dict) else {}
    disk = models.get("disk_mb") if isinstance(models.get("disk_mb"), dict) else {}
    vals = [v for v in (disk.get("data_free"), disk.get("comfy_free")) if isinstance(v, (int, float))]
    if vals:
        return int(min(vals))
    gb = caps.get("disk_free_gb")
    return int(gb * 1024) if isinstance(gb, (int, float)) else None


def missing_mb_of(node: ComputeNode, packages) -> int | None:
    """حجمِ آنچه برای این بسته‌ها (با نیازهایشان) هنوز باید دانلود شود، از گزارشِ گره؛ نامعلوم ⇒ None."""
    caps = node.capabilities or {}
    models = caps.get("models") if isinstance(caps.get("models"), dict) else {}
    status = models.get("packages") if isinstance(models.get("packages"), dict) else {}
    if not status:
        return None
    total = 0
    for p in expand_needs(packages):
        s = status.get(p)
        if isinstance(s, dict) and not s.get("installed"):
            total += int(s.get("missing_mb") or 0)
    return total


def preflight(node: ComputeNode, packages) -> str:
    """متنِ فارسیِ مشکلِ دانلود («عاملِ قدیمی»، «جا نیست») یا ''. دانلودِ دستی را سایت پیش از ساختنِ کار بررسی می‌کند."""
    caps = node.capabilities or {}
    models = caps.get("models") if isinstance(caps.get("models"), dict) else {}
    status = models.get("packages") if isinstance(models.get("packages"), dict) else {}
    cat = catalog()
    if status:
        # فقط بسته‌های کاتالوگِ تازه (دارای package_info): عاملِ قدیمی آن‌ها را نمی‌شناسد؛ بسته‌های قدیمی مثل همیشه
        unknown = [p for p in packages if (cat.get(p) or {}).get("display") and p not in status]
        if unknown:
            return ("نرم‌افزارِ این سرور هنوز بسته‌های تازهٔ مدل را نمی‌شناسد (%s). سرور با روشن‌بودن خودش به‌روز می‌شود (به‌روزرسانیِ خودکار)؛ "
                    "بعدش همین دانلود را دوباره بزنید، یا بگذارید «دانلودِ خودکار» کارش را بکند. اگر عجله دارید «به‌روزرسانی» را از «دستورها» بزنید." % "، ".join(unknown[:3]))
    need = missing_mb_of(node, packages)
    free = free_mb(node)
    if need and free is not None and need + MANUAL_RESERVE_MB > free:
        return ("فضای دیسکِ سرور برای این دانلود کم است: حدود %s مگابایت لازم است و %s مگابایت خالی است (باید دست‌کم ۲ گیگابایت هم بماند)."
                % (need, free))
    return ""


# ───────────────────────────── نمای هر گره

def _feature_rows(keys) -> list:
    return [{"key": k, "label": FEATURES[k][0], "switch": FEATURES[k][1]} for k in keys if k in FEATURES]


def _auto_view(key: str, c: dict, optional_default: bool, auto_cfg: dict, wanted: set, node_states: dict, switch_on: set) -> dict:
    """وضعیتِ «دانلودِ خودکار» ِ یک بسته: default (جزءِ مجموعهٔ پیش‌فرضِ گره) | on | off | never | manual."""
    klass = c.get("license_class", "open")
    if not optional_default:
        return {"mode": "default", "state": "", "text": "جزوِ مجموعهٔ پیش‌فرض؛ سرور خودش دانلودش می‌کند"}
    if klass != "open":
        return {"mode": "never", "state": "", "text": "به‌خاطرِ مجوز هرگز خودکار دانلود نمی‌شود؛ فقط با دکمه"}
    if not c.get("auto"):
        return {"mode": "manual", "state": "", "text": "اختیاری؛ با یک کلیک"}
    if key in wanted:
        return {"mode": "on", "state": node_states.get(key, ""), "text": "خودکار دانلود می‌شود"}
    feats = [FEATURES[f][0] for f in c.get("features", []) if f in FEATURES and FEATURES[f][1]]
    return {"mode": "off", "state": "", "text": "خودکار نیست؛ با روشن‌کردنِ «%s» خودکار می‌شود" % " یا ".join(feats) if feats else "خودکار نیست"}


def for_node(node: ComputeNode) -> dict:
    from . import auto_models

    caps = node.capabilities or {}
    models = caps.get("models") if isinstance(caps.get("models"), dict) else {}
    status = models.get("packages") if isinstance(models.get("packages"), dict) else {}
    cat = catalog()
    queued = _queued_downloads(node)
    progress = models.get("progress") if isinstance(models.get("progress"), dict) else None
    waiting = models.get("waiting") if isinstance(models.get("waiting"), dict) else None
    running_pkgs = set((progress or {}).get("packages") or []) if models.get("running") else set()
    waiting_pkgs = set((waiting or {}).get("packages") or [])
    node_auto = models.get("auto") if isinstance(models.get("auto"), dict) else {}
    node_states = node_auto.get("states") if isinstance(node_auto.get("states"), dict) else {}
    auto_cfg = auto_models.load()
    wanted = set(auto_models.wanted(auto_cfg)) if auto_cfg["enabled"] else set()
    switch_on = {k for k, v in auto_cfg["features"].items() if v}
    free = free_mb(node)
    reserve_mb = auto_cfg["reserve_gb"] * 1024

    keys = list(cat) + [k for k in status if k not in cat]
    groups: dict = {g["key"]: {**g, "packages": []} for g in GROUPS + [OTHER]}
    for key in keys:
        c = cat.get(key) or {}
        s = status.get(key) if isinstance(status.get(key), dict) else None
        fa_title, note = LABELS.get(key, ("", ""))
        fa_title = fa_title or c.get("title_fa") or ""
        note = note or c.get("note_fa") or ""
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
        optional = bool((s or {}).get("optional", c.get("optional", False)))
        needs = list(c.get("needs") or [])
        need_rows = [{"key": d, "title": (LABELS.get(d, ("", ""))[0] or (cat.get(d) or {}).get("title_fa") or d),
                      "installed": None if status.get(d) is None else bool((status.get(d) or {}).get("installed")),
                      "mb": int((status.get(d) or {}).get("missing_mb") or (cat.get(d) or {}).get("size_mb") or 0)}
                     for d in _closure(cat, needs)]
        total_mb = int((s or {}).get("total_mb") or c.get("size_mb") or 0)
        missing_mb = None if s is None else int(s.get("missing_mb") or 0)
        needs_missing = sum(r["mb"] for r in need_rows if r["installed"] is not True)
        download_mb = (missing_mb if missing_mb is not None else total_mb) + needs_missing if state in ("missing", "unknown") else 0
        fits = None
        if free is not None and download_mb:
            fits = download_mb + MANUAL_RESERVE_MB <= free
        vram = c.get("vram") or {}
        klass = c.get("license_class", "open")
        row = {
            "key": key,
            "title": fa_title or (s or {}).get("title") or c.get("title") or key,
            "title_en": (s or {}).get("title") or c.get("title") or "",
            "note": note,
            "optional": optional,
            "installed": installed,
            "state": state,
            "queued_text": queued.get(key, ""),
            "total_mb": total_mb,
            "missing_mb": missing_mb,
            "in_comfyui": int((s or {}).get("in_comfyui") or 0),
            "license": c.get("license") or "",
            "license_class": klass,
            "license_text": LICENSE_TEXT.get(klass, ""),
            "commercial": klass == "open",
            "vram_fit": vram.get("fit") or "",
            "vram_text": VRAM_TEXT.get(vram.get("fit") or "", ""),
            "vram_note": vram.get("note") or "",
            "vram_gb": vram.get("gb"),
            "features": _feature_rows(c.get("features") or []),
            "needs": need_rows,
            "download_mb": download_mb,
            "fits": fits,
            "needs_restart": bool(c.get("needs_restart")),
            "kind": "node" if c.get("kinds") == ["git"] else "files",
            "sources": list(c.get("sources") or [])[:4],
            "provenance": c.get("provenance") or "",
            "auto": _auto_view(key, c, optional, auto_cfg, wanted, node_states, switch_on),
        }
        groups[_display_group(str(c.get("group") or ""), key, str(c.get("display") or ""))]["packages"].append(row)
    out_groups = []
    for g in groups.values():
        if not g["packages"]:
            continue
        g["packages"].sort(key=lambda r: ((cat.get(r["key"]) or {}).get("priority", 50), r["key"]))
        out_groups.append({"key": g["key"], "title": g["title"], "note": g["note"], "packages": g["packages"]})
    pending_mb = sum(r["download_mb"] for g in out_groups for r in g["packages"] if r["auto"]["mode"] == "on" and r["state"] == "missing")
    return {
        "node": {"id": node.pk, "name": node.name, "online": node.online, "enabled": node.enabled,
                 "agent": caps.get("agent"), "last_seen": node.last_seen,
                 "disk_free_mb": free, "disk_total_gb": caps.get("disk_total_gb")},
        "reported": bool(status),
        "running": bool(models.get("running")),
        "progress": progress,
        "waiting": waiting,
        "error": str(models.get("error") or "")[:300],
        "auto": {"enabled": auto_cfg["enabled"], "reserve_gb": auto_cfg["reserve_gb"], "wanted": len(wanted),
                 "pending_mb": pending_mb, "reported": bool(node_auto), "states": node_states,
                 "why": node_auto.get("why") if isinstance(node_auto.get("why"), dict) else {}},
        "groups": out_groups,
    }


# ───────────────────────────── Ollama کنارِ بسته‌ها

def ollama_view() -> dict:
    """مدل‌های متن/بینایی (Ollama): فهرستِ مجازِ دانلود با وضعِ نصب + دانلودهای فعال و اخیر — همان داده‌ای که «موتورهای AI» نشان می‌دهد."""
    try:
        from services.ai import model_catalog, model_pull, routing

        known = routing.node_models()
        installed = {tag: (any(model_pull._same(tag, m) for m in known) if known else None) for tag in model_catalog.pullable()}
        rows = model_pull.catalog_view(installed)
        listed = set(model_catalog.pullable())
        extra = [{"tag": m, "label": m, "size_mb": 0, "purpose": "روی سرور نصب است (بیرون از فهرستِ مجازِ دانلود؛ دست‌نخورده می‌ماند)",
                  "vision": False, "installed": True} for m in known if not any(model_pull._same(t, m) for t in listed)]
        return {"models": rows, "extra": extra, "pulls": model_pull.jobs_view(), "pull_nodes": model_pull.node_summary(),
                "known": bool(known)}
    except Exception as exc:  # noqa: BLE001 — Ollama نباید فهرستِ بسته‌ها را بیندازد
        logger.info("ollama view unavailable: %s", exc)
        return {"models": [], "extra": [], "pulls": [], "pull_nodes": [], "known": False, "error": "فهرستِ مدل‌های Ollama الان در دسترس نیست."}


def listing() -> dict:
    from . import auto_models

    nodes = [n for n in ComputeNode.objects.all() if n.enabled]
    nodes.sort(key=lambda n: (not n.online, n.name))
    return {"nodes": [for_node(n) for n in nodes], "ollama": ollama_view(), "auto": auto_models.view(),
            "ollama_page": "/admin/providers"}
