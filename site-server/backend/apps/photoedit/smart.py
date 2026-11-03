"""«ویرایشِ هوشمند با دستور» روی سرورِ سایت — وقتی سرورِ پردازش (کیت) خاموش است یا اولویتِ هوشِ مصنوعی «اول متیس» است.

دو مسیر برای یک کار (``kit_smart``):

* ``node`` — اولویتِ بینایی «اول لوکال» است **و** یک سرورِ پردازشِ ``photo`` آنلاین است: مثلِ همیشه کارِ ``photo.edit`` با
  ``goal`` در صفِ سرورِ پردازش می‌رود (مدلِ بینا و موتورِ کیت آن‌جاست).
* ``site`` — در بقیهٔ حالت‌ها خودِ سایت از ``services.ai.gateway.vision_provider`` (مسیریابِ لوکال ⇄ متیس؛ ترتیب = تنظیمِ مالک در
  «اولویتِ هوش مصنوعی» و اگر اولی جواب نداد دومی) یک عکسِ ≤۷۶۸ پیکسلی، اندازه‌گیری‌ها، فهرستِ لغزنده‌ها و فیلترهای کیت و
  دستورِ کاربر را می‌فرستد و جوابِ JSON را **سخت‌گیرانه** وارسی می‌کند (کلیدِ ناشناخته دور، مقدار در بازه، فقط ابزارهای
  امنِ سرورِ سایت). نتیجه یک کارِ ``develop`` (لغزنده‌ها روی سرورِ سایت با ``develop_np``) + چند ابزارِ سبک است.
  اگر هر دو مسیرِ هوش مصنوعی جواب ندادند: ``auto_tone`` از روی اندازه‌گیری‌ها، با یادداشتی صادقانه (هیچ‌وقت خطا نمی‌دهد).

هر جا هوش مصنوعی جواب داد، ``meta`` می‌گوید چه کسی (لوکال/متیس، کدام مدل، آیا پشتیبان بود و چرا) تا پنل نشانش بدهد.
"""
from __future__ import annotations

import base64
import functools
import io
import json
import logging
import math
import re

from . import catalog, develop_np

logger = logging.getLogger(__name__)

#: ابزارهایی که هوشِ مصنوعی اجازه دارد اضافه کند (همه سبک و روی سرورِ سایت)
SAFE_TOOLS = ("auto_tone", "look", "color", "crop_format", "rotate", "resize")
#: اگر کاربر همین ابزار را از قبل داشت، انتخابِ کاربر می‌ماند (هندسه). بقیه را انتخابِ تازهٔ هوش مصنوعی عوض می‌کند.
USER_WINS = ("crop_format", "rotate", "resize")
#: ترتیبِ اجرا (مثلِ ترتیبِ قراردادیِ ادیتور): هندسه، سپس رنگ، سپس اندازه
_RANK = {"rotate": 0, "crop_format": 1, "auto_tone": 2, "look": 3, "color": 4, "resize": 5}

IMAGE_SIDE = 768
VISION_TIMEOUT = 120          # ثانیه برای هر مسیر؛ بدترین حالت (هر دو مسیر کند) < ۵ دقیقه
MAX_AI_OPS = 4
NOTES_MAX = 300
MIN_RESIZE = 600
FALLBACK_LABEL = "بدون هوش مصنوعی — نور و رنگِ خودکارِ سبک"
NODE_LABEL = "لوکال (سرورِ پردازش)"


# ───────────────────────────── انتخابِ مسیر

def _first_for_vision() -> str:
    from services.ai import priority

    try:
        return priority.config().first_for(priority.VISION)
    except Exception:  # noqa: BLE001 — پیش از مهاجرت / بی‌دیتابیس
        return priority.LOCAL


def _node_online() -> bool:
    from . import services

    try:
        return bool(services.node_status()["online"])
    except Exception:  # noqa: BLE001
        return False


def decide_path(store=None) -> dict:
    """``{"path": "node"|"site", "first": "local"|"metis", "node_online": bool, "reason": جملهٔ فارسی}``.

    node ⇐ «اول لوکال» و یک سرورِ پردازشِ photo آنلاین؛ وگرنه site. ``store`` برای آیندهٔ سیاستِ هر فروشگاه است."""
    from services.ai import priority

    first = _first_for_vision()
    online = _node_online()
    if first == priority.LOCAL and online:
        reason = "اولویتِ بینایی «اول لوکال» است و سرورِ پردازش آنلاین است ⇐ کار روی سرورِ پردازش انجام می‌شود."
        return {"path": "node", "first": first, "node_online": True, "reason": reason}
    if first == priority.METIS:
        reason = "اولویتِ هوش مصنوعیِ بینایی «اول متیس» است ⇐ هوشِ مصنوعی از سایت صدا زده می‌شود (لوکال پشتیبان است)."
    else:
        reason = "سرورِ پردازش خاموش است ⇐ هوشِ مصنوعی از سایت صدا زده می‌شود (طبقِ ترتیبِ تنظیماتِ هوش مصنوعی)."
    return {"path": "site", "first": first, "node_online": online, "reason": reason}


def path_help(decision: dict) -> str:
    """توضیحِ راستِ کارِ «ویرایش با دستور» برای پنل (در plan)."""
    if decision["path"] == "node":
        return ("هوشِ مصنوعیِ بینای سرورِ پردازش عکس و اندازه‌گیری‌ها را می‌بیند و لغزنده‌های کیت را تنظیم می‌کند؛ "
                "یک بار نتیجه را می‌بیند و اصلاح می‌کند.")
    first = "متیس" if decision["first"] == "metis" else "لوکال"
    second = "لوکال" if first == "متیس" else "متیس"
    return (f"هوشِ مصنوعیِ بینا از سرورِ سایت صدا زده می‌شود: اول {first}، اگر جواب نداد {second}. لغزنده‌ها روی "
            "سرورِ سایت اعمال می‌شود؛ اگر هیچ‌کدام جواب ندادند فقط نور و رنگِ خودکارِ سبک.")


# ───────────────────────────── اتصال به هوشِ مصنوعی

def _vision(store):
    """مسیریابِ بینایی (لوکال ⇄ متیس) برای این فروشگاه. زیرِ آزمون، بی جایگزینِ ساختگی، هیچ‌وقت شبکه صدا نمی‌زند."""
    from django.conf import settings

    from services.ai import gateway

    fn = gateway.vision_provider
    if getattr(settings, "IS_TEST", False) and getattr(fn, "__module__", "") == gateway.__name__:
        raise RuntimeError("زیرِ آزمون هوشِ مصنوعیِ واقعی صدا زده نمی‌شود.")
    return fn(store)


def _candidate_models() -> list[str]:
    from services.ai.router import TASK_VISION, models_for

    return models_for(TASK_VISION)


def _model_for(provider) -> str:
    """نامِ مدلی که این provider واقعاً به کار می‌برد (مثلِ apps.shoot.checks.vision_check)."""
    try:
        from apps.ai.services import _models_for_provider

        found = _models_for_provider(provider, _candidate_models())
        return str(found[0]) if found else ""
    except Exception as exc:  # noqa: BLE001
        logger.info("photoedit.smart: model lookup failed: %s", exc)
        return ""


def _describe(provider, model: str) -> dict:
    """کی جواب داد: via/model/label/fell_back/reason. providerِ ساده (بی مسیریاب) فقط نامِ مدل را دارد."""
    info: dict = {}
    fn = getattr(provider, "describe", None)
    if callable(fn):
        try:
            got = fn()
            info = dict(got) if isinstance(got, dict) else {}
        except Exception:  # noqa: BLE001
            info = {}
    via = str(info.get("via") or "")
    used = str(info.get("model") or model or "")
    fell = bool(info.get("fell_back"))
    label = str(info.get("label") or "")
    if not label:
        try:
            from services.ai import priority

            label = priority.answer_label(via, used, fell) if via else ""
        except Exception:  # noqa: BLE001
            label = ""
    if not label:
        label = used or "هوش مصنوعی"
    return {"via": via, "model": used, "label": label, "fell_back": fell,
            "reason": str(info.get("fallback_reason") or "")[:400]}


def _why(exc: Exception) -> str:
    """دلیلِ شکست به فارسیِ قابل‌فهم؛ AllProvidersFailed خودش هر دو دلیل را می‌گوید."""
    text = str(exc or "").strip()
    if exc.__class__.__name__ == "AllProvidersFailed" and text:
        return text[:500]
    try:
        from services.ai import priority

        return priority.classify(exc).sentence()[:500]
    except Exception:  # noqa: BLE001
        return (text or exc.__class__.__name__)[:300]


# ───────────────────────────── ساختِ پرسش

def _fa(x) -> str:
    return str(x)


@functools.lru_cache(maxsize=1)
def _catalogue_text() -> str:
    """لغزنده‌ها (کلید، عنوان، بازه، پیش‌فرضِ غیرِ صفر) به تفکیکِ گروه + فیلترهای کیت — ثابت است، یک بار ساخته می‌شود."""
    kit = catalog.kit()
    groups = {g["key"]: g["title"] for g in kit["groups"]}
    lines = []
    for gkey, gtitle in groups.items():
        bits = []
        for p in kit["params"]:
            if p["group"] != gkey:
                continue
            d = p["default"]
            tail = f" پیش‌فرض {d:g}" if abs(d) > 1e-9 else ""
            bits.append(f"{p['key']}({p['title']} {p['min']:g}..{p['max']:g}{tail})")
        if bits:
            lines.append(f"{gtitle}: " + "، ".join(bits))
    presets = "، ".join(f"{p['key']}={p['title']}" for p in kit["presets"] if p["kind"] == "look")
    return "\n".join(lines) + f"\nفیلترهای آماده (preset، اختیاری، فقط یکی): {presets}"


_TOOLS_TEXT = (
    "ابزارهای سبکِ دیگر (فقط اگر دستور صریحاً خواست؛ در «ops»): "
    'auto_tone{"strength":0..100}، '
    'look{"style":"vivid|warm|cool|bw|sepia|fade","strength":0..100}، '
    'color{"brightness":-100..100,"contrast":-100..100,"saturation":-100..100,"warmth":-100..100,"sharpness":0..100}، '
    'rotate{"turn":"0|90|180|270","straighten":-15..15}، '
    'crop_format{"format":"square|portrait|story|landscape|wide|store","fit":"cover|contain"}، '
    'resize{"long_edge":600..8000}'
)

_MEASURES = (("p50", "نورِ میانه"), ("p5", "تیره‌ترین"), ("p95", "روشن‌ترین"), ("contrast", "کنتراست"),
             ("clip_hi", "سفیدِ سوخته"), ("clip_lo", "سیاهِ له‌شده"), ("saturation", "اشباع"),
             ("cast_rb", "رنگ‌زدگیِ قرمز−آبی"), ("cast_g", "رنگ‌زدگیِ سبز−ارغوانی"), ("sharpness", "تیزی"), ("noise", "نویز"))


def _measures_text(asset) -> str:
    facts = asset.facts or {}
    bits = []
    for key, title in _MEASURES:
        v = facts.get(key)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            bits.append(f"{title} {v * 100:.1f}٪" if key in ("clip_hi", "clip_lo") else f"{title} {v:g}")
    size = f"{facts.get('width') or asset.width}×{facts.get('height') or asset.height}"
    notes = [str(f.get("note")) for f in (asset.findings or []) if isinstance(f, dict) and f.get("note")]
    text = "اندازه‌گیریِ عکس (روشنایی ۰ تا ۲۵۵): " + "، ".join(bits) + f"؛ ابعاد {size}."
    if notes:
        text += "\nمشاهداتِ برنامه: " + "؛ ".join(notes[:6]) + "."
    return text


def build_prompt(asset, goal: str, base: dict | None = None) -> str:
    base = base or {}
    cur = ""
    if base.get("adjust") or base.get("curve") or base.get("ops"):
        cur = ("\nتنظیماتِ فعلیِ عکس (از ویرایشِ قبلی؛ عکسِ پیوست هنوز بی‌ویرایش است): "
               + json.dumps({k: base[k] for k in ("adjust", "curve", "ops") if base.get(k)}, ensure_ascii=False)
               + "\nاین یک «اصلاح» است: فقط کلیدهایی را بده که باید عوض شوند، با مقدارِ نهاییِ خودشان؛ بقیه می‌ماند.")
    return (
        "تو یک رتوشگرِ حرفه‌ای عکس (مثلِ Lightroom) هستی. عکسِ پیوست را ببین و طبقِ «دستورِ کاربر» لغزنده‌های ظهورِ عکس را تنظیم کن.\n\n"
        f"دستورِ کاربر: «{goal}»\n\n"
        f"{_measures_text(asset)}{cur}\n\n"
        "لغزنده‌های مجاز (کلید(عنوان کمینه..بیشینه)؛ پیش‌فرض ۰ مگر نوشته شده):\n"
        f"{_catalogue_text()}\n\n{_TOOLS_TEXT}\n\n"
        "قاعده‌ها: فقط کلیدهای همین فهرست؛ فقط آن‌چه دستور و عکس لازم دارد؛ مقدارها معقول (مثلاً exposure بینِ −۱ و ۱، "
        "بقیه معمولاً زیرِ ۴۰)؛ برای هر کلید «مقدارِ نهایی» نه اختلاف؛ ابزارِ دیگر و برش و چرخش فقط اگر دستور صریحاً خواست؛ "
        "هیچ متنِ اضافه، فقط JSON.\n"
        'فقط این JSON: {"adjust": {"exposure": 0.3, "temperature": 12}, "curve": {}, "preset": "", "ops": [], '
        '"notes": "یک یا دو جملهٔ کوتاهِ فارسی که چه کردی"}'
    )


# ───────────────────────────── وارسیِ جوابِ مدل

def _num(v):
    """عددِ متناهی یا None؛ bool و متنِ نامعتبر دور ریخته می‌شود."""
    if isinstance(v, bool):
        return None
    if isinstance(v, str):
        t = v.strip().translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩٫", "01234567890123456789."))
        t = t.replace("−", "-").replace("+", "")
        try:
            x = float(t)
        except ValueError:
            return None
    elif isinstance(v, (int, float)):
        x = float(v)
    else:
        return None
    return x if math.isfinite(x) else None


def clean_adjust(obj) -> dict:
    """{کلید: مقدار} فقط کلیدهای کیت (بی‌توجه به بزرگیِ حروف)، در بازه. مقدارِ پیش‌فرض می‌ماند (می‌تواند مقدارِ فعلی را خنثی کند)."""
    spec = catalog.kit_params()
    lower = {k.lower(): k for k in spec}
    out: dict = {}
    if not isinstance(obj, dict):
        return out
    for key, val in obj.items():
        real = lower.get(key.lower()) if isinstance(key, str) else None
        x = _num(val)
        if real is None or x is None:
            continue
        c = spec[real]
        out[real] = round(max(c["min"], min(c["max"], x)), 3)
    return out


def _noop(tool: str, p: dict) -> bool:
    if tool in ("auto_tone", "look"):
        return not p["strength"]
    if tool == "color":
        return not any(p[k] for k in ("brightness", "contrast", "saturation", "warmth", "sharpness"))
    if tool == "rotate":
        return p["turn"] == "0" and not p["straighten"] and not p["flip_h"] and not p["flip_v"]
    if tool == "resize":
        return int(p["long_edge"]) < MIN_RESIZE
    return False


def clean_ops(raw) -> list[dict]:
    """فهرستِ {tool, params} ⇐ فقط ابزارهای امن، پارامترهای سخت‌گیرانه‌وارسی‌شده، بی تکرار، بی‌اثرها دور."""
    out: list[dict] = []
    seen: set[str] = set()
    for item in (raw if isinstance(raw, list) else [])[:12]:
        if not isinstance(item, dict):
            continue
        tool = item.get("tool")
        if not isinstance(tool, str) or tool not in SAFE_TOOLS or tool in seen:
            continue
        try:
            params = catalog.normalize_params(tool, item.get("params") if isinstance(item.get("params"), dict) else {},
                                              strict=True)
        except Exception:  # noqa: BLE001 — مقدارِ ناپذیرفتنی ⇒ کلِ آن کار دور
            continue
        if _noop(tool, params):
            continue
        seen.add(tool)
        out.append({"tool": tool, "params": params})
        if len(out) >= MAX_AI_OPS:
            break
    return out


def clean_notes(v) -> str:
    if isinstance(v, (list, tuple)):
        v = " ".join(str(x) for x in v if isinstance(x, (str, int, float)) and not isinstance(x, bool))
    if not isinstance(v, str):
        return ""
    v = re.sub(r"[\x00-\x1f\x7f]+", " ", v)
    return re.sub(r"\s+", " ", v).strip()[:NOTES_MAX]


def validate_reply(parsed) -> dict | None:
    """جوابِ خامِ مدل ⇐ {adjust, curve, preset, ops, notes} یا None اگر هیچ تغییرِ قابل‌استفاده‌ای نبود."""
    if not isinstance(parsed, dict):
        return None
    src = parsed
    if "adjust" not in src and isinstance(src.get("recipe"), dict):   # «نسخهٔ ویرایشِ کیت» را هم بپذیر
        src = dict(src["recipe"], notes=parsed.get("notes") or src["recipe"].get("notes"))
    adjust = clean_adjust(src.get("adjust"))
    curve = catalog.normalize_curve(src.get("curve"))
    preset = src.get("preset")
    preset = preset if isinstance(preset, str) and catalog.kit_presets().get(preset, {}).get("kind") == "look" else ""
    ops_ = clean_ops(src.get("ops"))
    out = {"adjust": adjust, "curve": curve, "preset": preset, "ops": ops_, "notes": clean_notes(src.get("notes"))}
    if not (develop_np.normalize_adjust(adjust) or curve or preset or ops_):
        return None
    return out


# ───────────────────────────── جایگزینِ قطعی

def fallback_result(asset, reason: str, goal: str = "") -> dict:
    """هر دو مسیرِ هوش مصنوعی جواب ندادند ⇒ ``auto_tone`` (شدت از روی اندازه‌گیری‌ها) + یادداشتِ صادقانه."""
    kinds = {f.get("what") for f in (asset.findings or []) if isinstance(f, dict)}
    strength = 75 if kinds & {"dark", "flat"} else 60 if kinds & {"cast", "bright", "clipped"} else 50
    ops_ = [{"tool": "auto_tone", "params": catalog.normalize_params("auto_tone", {"strength": strength}, strict=False)}]
    if "blurry" in kinds:
        ops_.append({"tool": "color", "params": catalog.normalize_params("color", {"sharpness": 35}, strict=False)})
    note = ("هوشِ مصنوعی در دسترس نبود، پس فقط نور و رنگِ خودکارِ سبک اعمال شد و دستورِ شما اجرا نشد؛ "
            "کمی بعد دوباره امتحان کنید.")
    return {"adjust": {}, "curve": {}, "preset": "", "ops": ops_, "notes": note,
            "meta": {"via": "", "model": "", "label": FALLBACK_LABEL, "fell_back": True,
                     "reason": (reason or "")[:500], "fallback": True}}


# ───────────────────────────── اجرا

def _image_b64(asset) -> str:
    from . import ops, services

    img = services.preview_source(asset)
    img = ops.flatten(img)
    img.thumbnail((IMAGE_SIDE, IMAGE_SIDE))
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "JPEG", quality=82)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def run_site_smart(asset, goal: str, store, base: dict | None = None) -> dict:
    """عکس + دستور ⇒ ``{adjust, curve, preset, ops, notes, meta}``؛ هیچ‌وقت به‌خاطرِ شکستِ هوشِ مصنوعی خطا نمی‌دهد.

    ``base`` = تنظیماتِ فعلی (برای «اصلاح»): ``{adjust, curve, ops}``؛ فقط در پرسش می‌آید."""
    goal = re.sub(r"\s+", " ", str(goal or "")).strip()[:300]
    try:
        b64 = _image_b64(asset)
    except Exception as exc:  # noqa: BLE001
        logger.warning("photoedit.smart: image for asset %s failed: %s", getattr(asset, "pk", None), exc)
        return fallback_result(asset, "عکس برای هوش مصنوعی آماده نشد.", goal)
    prompt = build_prompt(asset, goal, base)
    model = ""
    try:
        provider = _vision(store)
        model = _model_for(provider)
        got = provider.generate_json(model, prompt, images=[b64], timeout=VISION_TIMEOUT)
        parsed = got[0] if isinstance(got, tuple) else got
    except Exception as exc:  # noqa: BLE001 — هر شکستی (هر دو مسیر، سیاست، پیکربندی) ⇒ جایگزینِ قطعی
        why = _why(exc)
        logger.info("photoedit.smart: AI unavailable for asset %s: %s", getattr(asset, "pk", None), why)
        return fallback_result(asset, why, goal)
    info = _describe(provider, model)
    result = validate_reply(parsed)
    if result is None:
        who = info["label"] or "هوش مصنوعی"
        logger.info("photoedit.smart: unusable reply from %s for asset %s", who, getattr(asset, "pk", None))
        return fallback_result(asset, f"{who} جوابِ قابل‌استفاده نداد.", goal)
    result["meta"] = {"via": info["via"], "model": info["model"], "label": info["label"], "fell_back": info["fell_back"],
                      "reason": info["reason"], "fallback": False}
    return result


# ───────────────────────────── ابزارهای یک ویرایش ⇐ ابزارهای سرورِ سایت

def _kit_conversion(operations: list[dict]) -> dict:
    """کارهای کیتِ یک نسخه که همتای سرورِ سایت دارند ⇐ لغزنده‌ها و ابزارهای سبک؛ بقیه (پس‌زمینه، قاب، بزرگ‌نمایی) می‌مانند.

    همان قراردادِ ``services.preset_operations`` (وقتی گره خاموش است): فیلترِ کیت ⇐ لغزنده‌هایش، زیرِ نویزگیری، شارپ و
    لغزنده‌های خودِ کاربر. ``develop``های موجود (از ویرایشِ قبلیِ سرورِ سایت) هم لغزنده‌های فعلی حساب می‌شوند."""
    node_ops, server_ops = catalog.split(operations)
    goal = ""
    preset = den = sharp = None
    adj: list[dict] = []
    extras: list[dict] = []
    keep: list[dict] = []
    spots: list[dict] = []
    for o in node_ops:
        t, p = o["tool"], o["params"]
        if t == "kit_smart":
            goal = p.get("goal", "")
        elif t == "kit_auto":
            extras.append({"tool": "auto_tone", "params": catalog.normalize_params("auto_tone", {"strength": 70}, strict=False),
                           "reason": "بهبودِ خودکار (نسخهٔ سبک روی سرورِ سایت)"})
        elif t == "kit_preset":
            preset = p
        elif t == "kit_denoise":
            den = p
        elif t == "kit_sharpen":
            sharp = p
        elif t == "kit_adjust":
            adj.append(p)
        elif t == "kit_heal":
            spots.extend(p.get("spots") or [])
        else:
            keep.append(o)
    adjust: dict = {}
    curve: dict = {}
    if preset:
        rec = catalog.kit_presets().get(preset["preset"], {}).get("recipe") or {}
        adjust.update(rec.get("adjust") or {})
        curve.update(catalog.normalize_curve(rec.get("curve")))
    if den:
        adjust.update({"noiseLuma": den["luma"], "noiseColor": den["color"]})
    if sharp:
        adjust.update({"sharpen": sharp["amount"], "sharpenRadius": sharp["radius"], "sharpenMasking": sharp["masking"]})
    for p in adj:
        adjust.update(p.get("adjust") or {})
        curve.update(p.get("curve") or {})
    rest: list[dict] = []
    export = None
    for o in server_ops:
        if o["tool"] == "develop":     # لغزنده‌های فعلی از ویرایشِ قبلی
            adjust.update(o["params"].get("adjust") or {})
            curve.update(o["params"].get("curve") or {})
            spots.extend(o["params"].get("spots") or [])
        elif o["tool"] == "export":
            export = o
        else:
            rest.append(o)
    return {"goal": goal, "adjust": adjust, "curve": curve, "spots": spots, "extras": extras, "keep_node": keep,
            "server": rest, "export": export}


def base_of(operations: list[dict]) -> dict:
    """تنظیماتِ فعلیِ یک ویرایش (برای «اصلاح»): {adjust, curve, ops}؛ خالی اگر چیزی نبود."""
    conv = _kit_conversion(operations)
    ops_ = [{"tool": o["tool"], "params": o["params"]} for o in conv["server"] if o["tool"] in SAFE_TOOLS]
    ops_ += [{"tool": o["tool"], "params": o["params"]} for o in conv["extras"]]
    return {"adjust": develop_np.normalize_adjust(conv["adjust"]), "curve": catalog.normalize_curve(conv["curve"]),
            "ops": ops_}


def _compose(operations: list[dict], result: dict, order: int = 1) -> tuple[list[dict], bool]:
    """``order`` = ``PhotoEdit.stats["order"]``: ۲ ⇒ کارهای سرورِ سایت به ترتیبِ قراردادیِ «قاب‌اول» (catalog.SERVER_ORDER_V2) چیده می‌شوند."""
    conv = _kit_conversion(operations)
    adjust, curve = dict(conv["adjust"]), dict(conv["curve"])
    if result.get("preset"):
        rec = catalog.kit_presets().get(result["preset"], {}).get("recipe") or {}
        adjust.update(rec.get("adjust") or {})
        curve.update(catalog.normalize_curve(rec.get("curve")))
    adjust.update(result.get("adjust") or {})
    curve.update(result.get("curve") or {})
    adjust = develop_np.normalize_adjust(adjust)
    spots = conv["spots"][:60]
    meta = result.get("meta") or {}
    note = result.get("notes") or ""
    who = meta.get("label") or ""
    reason = (f"{who}: {note}" if who and not meta.get("fallback") else note or "ویرایشِ هوشمند")[:300]

    user_tools = {o["tool"] for o in conv["server"]}
    ai_ops: list[dict] = []
    for o in result.get("ops") or []:
        if o["tool"] in USER_WINS and o["tool"] in user_tools:
            continue
        ai_ops.append({"tool": o["tool"], "params": o["params"], "reason": "پیشنهادِ هوش مصنوعی" if not meta.get("fallback") else note})
    ai_tools = {o["tool"] for o in ai_ops}
    extras = [o for o in conv["extras"] if o["tool"] not in user_tools and o["tool"] not in ai_tools]
    ai_ops.sort(key=lambda o: _RANK.get(o["tool"], 9))
    # کارِ کاربرِ هم‌نام که انتخابِ تازهٔ هوش مصنوعی جایش را می‌گیرد (رنگ و فیلتر) برداشته می‌شود
    rest = [o for o in conv["server"] if not (o["tool"] in ai_tools and o["tool"] not in USER_WINS)]

    body: list[dict] = []
    if not develop_np.is_neutral(adjust, curve, spots):
        body.append({"tool": "develop", "reason": reason,
                     "params": catalog.normalize_params("develop", {"adjust": adjust, "curve": curve, "spots": spots},
                                                        strict=False)})
    body += ai_ops + extras + rest
    rank = getattr(catalog, "_RANK_V2", None)
    if int(order or 1) >= 2 and rank:
        mid = rank.get("compose", 9)
        body.sort(key=lambda o: rank.get(o["tool"], mid))      # sort پایدار است
    out: list[dict] = list(conv["keep_node"]) + body
    if conv["export"]:
        out.append(conv["export"])
    effective = any(o["tool"] != "export" and o not in conv["keep_node"] for o in out)
    return out, effective


def apply_site(asset, operations: list[dict], result: dict, order: int = 1) -> tuple[list[dict], dict]:
    """نتیجهٔ هوشِ مصنوعی ⇐ (فهرستِ تازهٔ کارها، نتیجهٔ نهایی). اگر هیچ اثری نداشت، جایگزینِ قطعی."""
    new_ops, effective = _compose(operations, result, order)
    if not effective:
        goal = _kit_conversion(operations)["goal"]
        result = fallback_result(asset, "هوش مصنوعی تغییری پیشنهاد نکرد.", goal)
        new_ops, _ = _compose(operations, result, order)
    return new_ops, result


def stats_record(result: dict, goal: str, seconds: float | None = None) -> dict:
    """آنچه در ``PhotoEdit.stats["smart"]`` می‌ماند و پنل نشان می‌دهد."""
    meta = result.get("meta") or {}
    rec = {"path": "site", "via": meta.get("via", ""), "model": meta.get("model", ""), "label": meta.get("label", ""),
           "fell_back": bool(meta.get("fell_back")), "reason": meta.get("reason", ""),
           "adjust": develop_np.normalize_adjust(result.get("adjust") or {}), "notes": result.get("notes", ""),
           "fallback": bool(meta.get("fallback")), "goal": goal, "preset": result.get("preset", ""),
           "tools": [o["tool"] for o in result.get("ops") or []]}
    if seconds is not None:
        rec["seconds"] = round(float(seconds), 1)
    return rec


def residual_node_ops(operations: list[dict]) -> list[dict]:
    """کارهای کیتی که حتی با مسیرِ سایت هم سرورِ پردازش می‌خواهند (پس‌زمینه، قابِ مربع، بزرگ‌نمایی)."""
    return _kit_conversion(operations)["keep_node"]


def node_record(kit: dict, prev: dict | None = None) -> dict:
    """مسیرِ سرورِ پردازش: جوابِ کیت ⇐ همان قالبِ ``stats["smart"]``. کیت اگر مدلِ بینا نداشت، خودش بهبودِ خودکار زد."""
    prev = prev or {}
    used = kit.get("usedAi")
    recipe = kit.get("recipe") if isinstance(kit.get("recipe"), dict) else {}
    notes = kit.get("notes")
    notes = " ".join(str(x) for x in notes) if isinstance(notes, list) else str(notes or "")
    base = {"path": "node", "goal": prev.get("goal", ""), "adjust": develop_np.normalize_adjust(recipe.get("adjust") or {}),
            "notes": clean_notes(notes), "preset": str(recipe.get("preset") or ""), "tools": []}
    if used is False:
        return base | {"via": "", "model": "", "label": "بدون هوش مصنوعی — بهبودِ خودکارِ کیت", "fell_back": True,
                       "fallback": True, "reason": str(kit.get("error") or "مدلِ بینا روی سرورِ پردازش در دسترس نبود.")[:300]}
    model = str(kit.get("model") or "")
    if not model and used is True:
        try:
            from services.ai import priority

            model = priority.local_model(priority.VISION)
        except Exception:  # noqa: BLE001
            model = ""
    return base | {"via": "local", "model": model, "label": NODE_LABEL, "fell_back": False, "fallback": False, "reason": ""}
