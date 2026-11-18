"""«توصیف کن، بساز»: توصیفِ فارسیِ یک سبک ⇒ پیش‌نویسِ توکن‌های سبک.

دو مسیر، همیشه با همان اعتبارسنجِ custom.sanitize و نگهبانِ کنتراست:
  · هوش مصنوعی (مسیریابِ متنِ پروژه: مدلِ محلیِ گره ⇄ متیس): مدل فقط «توکن» می‌نویسد، از فهرستِ بسته‌ای از نوع‌ها؛ هر بخشِ نامعتبر کنار می‌رود و جایش از
    پیش‌نویسِ قاعده‌ای می‌آید؛ پالتِ ناخوانا خودکار اصلاح می‌شود.
  · قاعده‌ای (بدونِ مدل؛ اعتبارِ متیس تمام یا گره خاموش): واژه‌های کلیدیِ فارسی/انگلیسی ⇒ یک سبکِ پایه از همین کاتالوگ (۹۶ سبک) + رنگ‌مایه + شخصیتِ حرکت.
    همیشه جواب می‌دهد، پس صفحه بی‌هوش‌مصنوعی هم کار می‌کند و با برگشتنِ هوش مصنوعی همان دکمه از مسیرِ اصلی می‌رود.
"""
from __future__ import annotations

import copy
import logging
import re

from . import ai, catalog, custom, motionlib

logger = logging.getLogger(__name__)

#: واژه‌های کلیدی ⇒ شناسهٔ سبکِ پایه (اولین تطابق برنده است؛ ترتیب = اولویت)
BASES = [
    (("پیکسل", "آرکید", "۱۶ بیت", "16bit", "pixel", "گیم", "بازی"), "pixel-art"),
    (("سایبر", "cyber", "نئون", "neon", "آینده‌نگر", "علمی"), "cyberpunk"),
    (("سینت", "synthwave", "ویپور", "vapor", "دههٔ ۸۰", "دهه ۸۰", "هشتاد"), "synthwave"),
    (("گچ", "تخته", "کلاس", "درس", "آموزش", "chalk"), "chalkboard"),
    (("آبرنگ", "watercolor", "ملایم و نقاشی", "نقاشی"), "watercolor"),
    (("کولاژ", "collage", "دست‌ساز", "دستساز", "کاغذ"), "paper-collage"),
    (("شیشه", "شفاف", "glass"), "glassmorphism"),
    (("لوکس", "اشرافی", "luxury", "گران", "آرت‌دکو", "آرتدکو", "deco"), "art-deco"),
    (("ورزش", "باشگاه", "تناسب", "قدرت", "انرژی", "gym", "sport", "fitness"), "sport-energy"),
    (("کودک", "بچه", "کارتون", "cartoon", "کاواییی", "کاوایی"), "cartoon-network-inspired"),
    (("نقشه", "مهندس", "فنی", "blueprint"), "blueprint"),
    (("نوآر", "noir", "جنایی", "کارآگاه", "سیاه‌وسفید", "سیاه و سفید"), "film-noir"),
    (("کاشی", "ایرانی", "سنتی", "persian", "گره‌چینی", "اسلیمی"), "persian-tile"),
    (("سه‌بعدی", "سه بعدی", "3d", "خمیر", "clay"), "claymation-3d"),
    (("روزنامه", "خبر", "news"), "newspaper"),
    (("گلیچ", "glitch", "خراب", "اختلال"), "glitch-art"),
    (("طبیعت", "گیاه", "ارگانیک", "جنگل", "سبزه", "ghibli", "جیبلی"), "ghibli-inspired"),
    (("تایپ", "نوشتار", "kinetic", "تایپوگرافی"), "kinetic-typography"),
    (("رترو", "retro", "دههٔ ۷۰", "دهه ۷۰", "هفتاد", "vintage", "قدیمی"), "retro-70s"),
    (("کمیک", "comic", "پاپ", "pop"), "comic-art"),
    (("سینمایی", "فیلم", "تیره و سینمایی", "cinematic", "درام"), "cineview"),
    (("مینیمال", "minimal", "ساده", "تمیز", "سفید", "بی‌تکلف", "حداقلی"), "dan-koe-style"),
    (("ایزومتریک", "isometric"), "isometric"),
    (("شب", "ستاره", "افسانه", "جادو", "رؤیا"), "disney-inspired"),
    (("هندسی", "باهاوس", "bauhaus", "مدرن"), "bauhaus"),
    (("تخت", "flat", "وکتور", "شرکتی", "اداری", "سازمانی"), "flat-vector"),
]
#: واژهٔ رنگ ⇒ رنگمایه (۰..۱)
HUES = [
    (("قرمز", "red", "سرخ", "گلی"), 0.0), (("نارنجی", "orange", "نارنج"), 0.07), (("طلایی", "زرد", "yellow", "gold", "کهربایی"), 0.13), (("سبز", "green", "یشمی", "زمردی"), 0.36),
    (("فیروزه", "تیل", "teal", "cyan", "سیان"), 0.5), (("آبی", "blue", "دریایی", "اقیانوسی", "لاجوردی", "سرمه"), 0.6), (("بنفش", "purple", "ارغوانی", "violet"), 0.75),
    (("صورتی", "pink", "رز"), 0.93), (("قهوه‌ای", "قهوه", "brown", "شکلات", "خاکی"), 0.07),
]
DARK_WORDS = ("تیره", "شب", "مشکی", "سیاه", "dark", "night", "سینمایی", "نئون", "عمیق")
LIGHT_WORDS = ("روشن", "سفید", "پاستل", "ملایم", "light", "bright", "روز", "شاد", "روشن و", "تمیز")
ENERGY = [
    (("بازیگوش", "فنری", "جهنده", "شاد", "bounce", "کودک"), "bouncy"), (("پرانرژی", "ضربه", "تند", "سریع", "قدرتمند", "punch", "energetic"), "punchy"),
    (("پله", "استاپ", "stop-motion", "stop motion", "خمیر"), "stepped"), (("دست‌ساز", "دستساز", "لرزان", "نقاشی", "handmade"), "handmade"),
    (("گلیچ", "دیجیتال", "خراب", "glitch"), "glitchy"), (("سنگین", "سینمایی", "باوقار", "رسمی", "cinematic", "heavy"), "heavy"),
    (("نرم", "آرام", "ملایم", "شناور", "soft", "calm", "slow"), "soft"), (("تیز", "دقیق", "snappy", "مدرن", "تمیز"), "snappy"),
]


def _has(text: str, words) -> bool:
    low = text.lower()
    return any(w in low for w in words)


def pick_base(text: str, base_id: str | None = None) -> str:
    if base_id and catalog.get(base_id):
        return base_id
    for words, sid in BASES:
        if _has(text, words) and catalog.get(sid):
            return sid
    return "flat-vector"


def make_name(text: str, base_name: str) -> str:
    """نامِ فارسی از خودِ توصیف (۲ تا ۳ واژهٔ اصلی)؛ نشد ⇒ «سبکِ <پایه>»."""
    stop = {"یک", "با", "و", "از", "به", "در", "که", "را", "برای", "یا", "این", "آن", "سبک", "رنگ", "رنگی", "طرح", "ظاهر", "حس", "حال", "هوای", "شبیه", "مثل", "مانند", "خیلی", "کمی", "بیشتر"}
    words = [w for w in re.findall(r"[آ-یA-Za-z‌]{2,}", text or "") if w not in stop]
    nm = " ".join(words[:2]).strip()
    return ("سبکِ " + nm)[:32] if nm else ("سبکِ " + base_name)[:32]


def rules_style(text: str, base_id: str | None = None) -> dict:
    """بدونِ مدل: توصیف ⇒ سبکِ پاک‌شده. همیشه معتبر و خوانا."""
    text = (text or "").strip()
    sid = pick_base(text, base_id)
    base = copy.deepcopy(catalog.get(sid))
    st = custom.sanitize({**base, "name_fa": make_name(text, base["name_fa"]), "name_en": "", "about": text[:200], "tags": base.get("tags", [])[:4]})
    pal = dict(st["palette"])
    dark = None
    if _has(text, DARK_WORDS):
        dark = True
    elif _has(text, LIGHT_WORDS):
        dark = False
    hue = next((h for words, h in HUES if _has(text, words)), None)
    if hue is not None or dark is not None:
        cur_dark = custom.lum(pal["bg"]) < 0.3
        want_dark = cur_dark if dark is None else dark
        if hue is not None:
            seed = custom.hsl_hex(hue, 0.62, 0.5)
            seeds = [seed, custom.hsl_hex(hue + 0.08, 0.6, 0.5), custom.hsl_hex(hue - 0.1, 0.65, 0.52)]
            pal = custom.palette_from_colors(seeds, dark=want_dark)
        else:
            keep = [pal["accent"], pal["accent2"], pal["accent3"]]
            pal = custom.palette_from_colors(keep, dark=want_dark)
        st["palette"] = pal
    energy = next((pid for words, pid in ENERGY if _has(text, words)), None)
    if energy:
        pers = next(p for p in custom.PERSONALITIES if p["id"] == energy)
        st["motion"] = {**st["motion"], **copy.deepcopy(pers["motion"])}
        st["trans"] = {"kind": pers["trans"][0], "frames": pers["trans"][1]}
    if _has(text, ("بزرگ", "درشت", "حروف بزرگ", "uppercase")):
        st["font"]["case"] = "upper"
    st["palette"] = custom.fix_palette(st)
    return custom.sanitize(st)


# ───────────────────────────────────────────── the model path

def _vocab() -> str:
    sch = custom.schema()
    return (
        "پس‌زمینه (bg.kind): " + ", ".join(catalog.BG_KINDS) + "\n"
        "تزئین (decor[].kind): " + ", ".join(catalog.DECOR_KINDS) + "\n"
        "بافت (tex[].kind): " + ", ".join(catalog.TEX_KINDS) + "\n"
        "افکتِ متن (text.fx): " + ", ".join(catalog.TEXT_FX) + "\n"
        "ورود (motion.enter): " + ", ".join(catalog.ENTER_KINDS) + "\n"
        "گذار (trans.kind): " + ", ".join(catalog.TRANS_KINDS) + "\n"
        "منحنی (motion.ease): " + ", ".join(motionlib.EASES) + "\n"
        "قلم لاتین: " + ", ".join(k for k, v in custom.fonts().items()) + "\n"
        "قلم فارسی: " + ", ".join(k for k, v in custom.fonts().items() if v["fa"]) + "\n"
        "پارامترهای پس‌زمینهٔ ‏linear: " + ", ".join(sch["bg"]["linear"]) + "؛ ‏radial: " + ", ".join(sch["bg"]["radial"])
    )


def _prompt(text: str, base: dict) -> tuple[str, str]:
    system = (
        "تو طراحِ موشن‌گرافیک هستی. توصیفِ فارسیِ یک سبک را به «توکن‌های سبک» (JSON) تبدیل کن. فقط JSON برگردان، بدونِ توضیح.\n"
        "قاعده‌ها: palette باید دقیقاً ۸ کلید داشته باشد (bg, bg2, ink, paper, accent, accent2, accent3, muted) با رنگِ hex شش‌رقمی؛ ink باید روی bg "
        "حداقل کنتراستِ ۴٫۵ داشته باشد. نوع‌ها فقط از فهرستِ مجاز بیایند (چیزِ جدید نساز). مقدارِ رنگ در پارامترها یا نامِ یکی از ۸ نقش است یا hex.\n"
        "کلیدها: name_fa, about, palette, font{latin,fa,weight,case,track,lh}, bg{kind,...}, bg2 (اختیاری), tex[], text{fx,...}, "
        "shape{radius,border,shadow,fill}, decor[], motion{enter,spring[میرایی,سفتی,جرم],ease,stagger,stepFps,wobble}, trans{kind,frames}.\n"
        "فهرستِ مجاز:\n" + _vocab()
    )
    user = f"توصیف: {text}\n\nنقطهٔ شروع (فقط ساختار؛ هر چه لازم است عوض کن):\n" + __import__("json").dumps(
        {k: base[k] for k in ("palette", "font", "bg", "text", "motion", "trans")}, ensure_ascii=False)
    return system, user


def describe(store, text: str, *, base_id: str | None = None, provider=None) -> dict:
    """⇒ {"style", "source": "ai"|"rules", "message", "notes"[]}. هرگز خطا نمی‌دهد جز برای توصیفِ خالی."""
    text = (text or "").strip()
    if len(text) < 3:
        raise custom.StyleError("سبک را توصیف کنید (حداقل چند کلمه)؛ مثلاً «تیره و سینمایی با رنگِ طلایی، حرکتِ آرام».")
    text = text[:600]
    draft = rules_style(text, base_id)
    note = ""
    parkable = False
    try:
        prov = provider if provider is not None else ai.get_provider(store)
        ai.ensure_available(prov)
        system, user = _prompt(text, draft)
        data = ai._call_json(prov, user, system, {"type": "object"}, temperature=0.5, num_predict=1800)
        if not isinstance(data, dict) or not data.get("palette"):
            raise ValueError("پاسخِ هوش مصنوعی قابل‌استفاده نبود.")
        notes: list = []
        merged = {**draft, **{k: v for k, v in data.items() if k in ("name_fa", "about", "palette", "font", "bg", "bg2", "tex", "text", "shape", "decor", "motion", "trans", "fx", "tags")}}
        merged["name_fa"] = (str(data.get("name_fa") or "").strip() or draft["name_fa"])[:40]
        try:
            st = custom.sanitize(merged, notes=notes)
        except custom.StyleError as exc:
            # one invalid section must not throw the whole answer away: keep the rule-based draft and take over only what survives, section by section
            notes.append(str(exc))
            st = draft
            for key in ("palette", "font", "motion", "trans", "text", "shape"):
                if key in data:
                    try:
                        st = custom.sanitize({**st, key: data[key]}, notes=notes)
                    except custom.StyleError:
                        continue
        before = custom.contrast_report(st)
        if not before["ok"]:
            st = {**st, "palette": custom.fix_palette(st)}
            notes.append("کنتراستِ رنگ‌ها خودکار اصلاح شد.")
        return {"style": st, "source": "ai", "message": "؛ ".join(notes[:3]), "notes": notes}
    except Exception as exc:  # noqa: BLE001 — هر شکستِ مسیرِ مدل ⇒ پیش‌نویسِ قاعده‌ای
        logger.info("motion style describe: falling back to rules (%s)", exc)
        note = f"{ai.MSG_UNAVAILABLE}: {ai.explain(exc)}" if not isinstance(exc, (ValueError, custom.StyleError)) else "پاسخِ هوش مصنوعی قابل‌استفاده نبود"
        # «با صبر درست می‌شود» (گرهٔ پردازش خاموش/شلوغ، اعتبارِ متیس، مهلت) ⇒ view می‌تواند «در صف تا روشن شدنِ سرورِ پردازش» بگذارد (compute.deferred)
        parkable = (not isinstance(exc, (ValueError, custom.StyleError))) and ai._outage(exc)
    base = pick_base(text, base_id)
    msg = ai._then(note, f". پیش‌نویس با قاعده‌های ساده از روی توصیفِ شما (پایه: «{(catalog.get(base) or {}).get('name_fa', base)}») ساخته شد؛ ویرایشش کنید یا بعداً دوباره امتحان کنید.")
    return {"style": draft, "source": "rules", "message": msg, "notes": [], "base": base, "parkable": bool(parkable)}


def deferred_describe(store, *, text: str, base_id: str | None = None, _user_id=None) -> dict:
    """اجرای صف‌دار (compute.deferred): همان describe با هوش مصنوعیِ واقعی؛ جواب قاعده‌ای ⇒ هنوز در دسترس نیست ⇒ در صف می‌ماند."""
    res = describe(store, text, base_id=base_id or None)
    res["contrast"] = custom.contrast_report(res["style"])                 # همان کلیدی که view به پاسخِ همزمان می‌افزاید
    return res
