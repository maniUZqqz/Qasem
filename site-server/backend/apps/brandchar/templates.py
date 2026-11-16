"""قالب‌های پست و استوری با شخصیتِ برند (استودیوی تصویر): ۱۰ قالبِ آماده؛ متنِ حباب و کپشن از لحنِ ثبت‌شدهٔ برند می‌آید (یا جمله‌های بی‌ادعای عمومی)
و همیشه از نگهبانِ ادعا می‌گذرد. هر قالب با ``render_shot`` ساخته می‌شود؛ پس کَش، کتابخانهٔ ادیتورِ عکس و بررسیِ رنگ همان است."""
from __future__ import annotations

from apps.mascot.engine import compose, copy_guard, scenes

from .models import BrandCharacter, CharacterRender

#: id، نام، اندازه، ژست، حالت، موقعیت، (موقعیتِ جملهٔ پرسونا برای حباب، متنِ پیش‌فرضِ حباب)، (کپشنِ پیش‌فرض یا "@catch" = شعارِ برند، "@none")
TEMPLATES: list[dict] = [
    {"id": "tip", "fa": "نکتهٔ امروز", "size": "ig_portrait", "pose": "point_up", "expression": "happy", "bubble": ("explain", "این را ببین"), "caption": "نکتهٔ امروز", "kind": "say"},
    {"id": "greet", "fa": "سلام و خوشامد (استوری)", "size": "story", "pose": "wave", "expression": "happy", "bubble": ("greeting", "سلام!"), "caption": "@none", "kind": "say"},
    {"id": "ready", "fa": "آماده‌ای؟", "size": "ig_square", "pose": "thumbs_up", "expression": "happy", "bubble": ("invite", "آماده‌ای؟"), "caption": "@none", "kind": "say"},
    {"id": "question", "fa": "سؤال از مخاطب (استوری)", "size": "story", "pose": "think", "expression": "neutral", "bubble": (None, "سؤالی داری؟ بپرس"), "caption": "سؤالِ امروز", "kind": "think"},
    {"id": "cheer", "fa": "جشن و تبریک", "size": "ig_square", "pose": "cheer", "expression": "laugh", "bubble": (None, "ایول!"), "caption": "@none", "kind": "shout"},
    {"id": "slogan", "fa": "شعارِ برند", "size": "ig_portrait", "pose": "stand", "expression": "happy", "bubble": (None, ""), "caption": "@catch", "kind": "say"},
    {"id": "reminder", "fa": "یادآوری", "size": "ig_square", "pose": "stop", "expression": "neutral", "bubble": ("reminder", "یادت نره"), "caption": "@none", "kind": "say"},
    {"id": "answer", "fa": "پاسخ به پرسش", "size": "ig_portrait", "pose": "hold", "expression": "happy", "bubble": ("reply_question", "پاسخ را این‌جا می‌گویم"), "caption": "پرسش و پاسخ", "kind": "say"},
    {"id": "signoff", "fa": "خداحافظی (استوری)", "size": "story", "pose": "wave", "expression": "happy", "bubble": ("signoff", "هر وقت خواستی، همین‌جا هستم."), "caption": "@none", "kind": "say"},
    {"id": "wide_cover", "fa": "کاورِ افقی", "size": "wide", "pose": "point_right", "expression": "happy", "bubble": ("explain", "نگاه کن"), "caption": "@catch", "kind": "say"},
]
BY_ID = {t["id"]: t for t in TEMPLATES}


def _clean(text: str) -> str:
    t = " ".join(str(text or "").split())
    return "" if copy_guard.check_text(t) else t


def persona_line(persona: dict | None, situation: str | None, default: str) -> str:
    if persona:
        if situation == "greeting" and persona.get("greeting"):
            return _clean(persona["greeting"]) or default
        if situation == "signoff" and persona.get("signoff"):
            return _clean(persona["signoff"]) or default
        for row in persona.get("sample_lines") or []:
            if row.get("situation") == situation and _clean(row.get("text", "")):
                return row["text"]
    return default


def defaults(tid: str, persona: dict | None) -> dict:
    t = BY_ID[tid]
    bubble = persona_line(persona, t["bubble"][0], t["bubble"][1]) if t["bubble"][1] or t["bubble"][0] else ""
    cap = t["caption"]
    if cap == "@catch":
        cap = (persona or {}).get("catchphrases", [""])[0] if persona and persona.get("catchphrases") else ""
    elif cap == "@none":
        cap = ""
    return {"bubble": bubble[:140], "caption": _clean(cap)[:140]}


def listing(c: BrandCharacter, persona: dict | None) -> list[dict]:
    out = []
    for t in TEMPLATES:
        s = compose.SIZES[t["size"]]
        d = defaults(t["id"], persona)
        if t["caption"] == "@catch" and not d["caption"]:
            continue                                  # شعاری ثبت نشده؛ قالبِ «شعار» پیشنهاد نمی‌شود
        out.append({"id": t["id"], "fa": t["fa"], "size": t["size"], "size_fa": s["fa"], "aspect": s["aspect"], "w": s["w"], "h": s["h"], "pose": t["pose"], "expression": t["expression"],
                    "bubble": d["bubble"], "caption": d["caption"], "kind": t["kind"]})
    return out


def options_for(c: BrandCharacter, tid: str, persona: dict | None, over: dict | None = None) -> dict:
    t = BY_ID.get(tid)
    if t is None:
        raise KeyError(tid)
    over = over or {}
    d = defaults(tid, persona)
    bubble_text = str(over["bubble_text"]) if "bubble_text" in over else d["bubble"]
    caption_text = str(over["caption_text"]) if "caption_text" in over else d["caption"]
    bg = over.get("background") or (scenes.BACKGROUNDS and None) or None
    from apps.mascot.engine import brand as B

    role_bg = (B.ROLES.get(c.role) or B.ROLES[B.DEFAULT_ROLE])["background"]
    opts = {"size": over.get("size") or t["size"], "pose": over.get("pose") or t["pose"], "expression": over.get("expression") or t["expression"], "background": bg or role_bg,
            "position": over.get("position") or "center", "flip": bool(over.get("flip")), "allow_claims": bool(over.get("allow_claims"))}
    if bubble_text.strip():
        opts["bubble"] = {"text": bubble_text, "kind": t["kind"]}
    if caption_text.strip():
        opts["caption"] = {"text": caption_text, "position": "top"}
    return opts


def render(c: BrandCharacter, user, tid: str, over: dict | None = None) -> tuple[CharacterRender, bool]:
    from . import services as S

    persona = S.persona_data(c.store)
    opts = options_for(c, tid, persona, over)
    row, cached = S.render_shot(c, user, opts)
    if row.kind != "template" or (row.params or {}).get("template") != tid:
        row.kind = "template"
        row.params = {**(row.params or {}), "template": tid}
        row.save(update_fields=["kind", "params", "updated_at"])
    S.log_use(c.store, c, "post_template", f"{tid}:{row.pk}", {"template": tid}, user=user)
    return row, cached
