"""نوع‌های کارِ برنامه و پیوندشان به بخش‌های پنل.

هر نوع: (برچسبِ فارسی، کلیدِ صفحهٔ پنل که آن را می‌سازد، آیا به سرورِ پردازش (GPU) نیاز دارد، گروه).
کلیدِ صفحه همان کلیدِ ``apps.panel.registry`` است؛ نشانی از همان‌جا خوانده می‌شود، پس با عوض‌شدنِ مسیر خودکار درست می‌ماند.
"""
from __future__ import annotations

from apps.panel import registry as panel_registry

# kind: (label, section(page key), needs_node, group)
KINDS: dict[str, tuple[str, str, bool, str]] = {
    "profile": ("پروفایل، بایو و هایلایت", "campaigns", False, "content"),
    "ideas": ("بانکِ ایده", "ideas", False, "setup"),
    "trends": ("ترند و رقبا", "trends", True, "setup"),
    "post": ("پست", "campaigns", False, "content"),
    "carousel": ("کاروسل", "campaigns", False, "content"),
    "story": ("استوری", "campaigns", False, "content"),
    "reel": ("ریلز", "campaigns", False, "content"),
    "image": ("تصویرِ هوش مصنوعی (FLUX)", "thumbnail_maker", True, "media"),
    "thumbnail": ("کاور و تامنیل", "thumbnail_maker", True, "media"),
    "character": ("شخصیتِ برند", "brandchar_studio", True, "media"),
    "motion": ("ویدیوی موشن", "motion", True, "media"),
    "voiceover": ("گوینده (لایهٔ تلفظ)", "audio_speech", True, "media"),
    "music": ("موسیقیِ زمینه", "audio_music", True, "media"),
    "video_edit": ("ویدیو از ارائه", "design_deck", True, "media"),
    "up3d": ("ویدیوی سه‌بعدی", "video3d", True, "media"),
    "catalog": ("کاتالوگ محصولات", "design_catalog", False, "design"),
    "deck": ("ارائه (اسلاید)", "design_deck", False, "design"),
    "landing": ("پیش‌نویسِ صفحهٔ فرود", "design_ui", False, "design"),
    "email": ("ایمیل (پیش‌نویس)", "growth_templates", False, "outreach"),
    "sms": ("پیامک و ارسالِ گروهی (پیش‌نویس)", "inbox_broadcasts", False, "outreach"),
    "dm": ("دایرکت و پیامِ مشتری‌یاب (پیش‌نویس)", "growth_finder_drafts", False, "outreach"),
    "finder": ("مأموریتِ مشتری‌یاب", "growth_finder", False, "growth"),
    "leads_review": ("بازبینیِ لیدها", "growth_finder_results", False, "growth"),
    "inbox": ("راه‌اندازیِ صندوقِ پیام", "inbox_bot", False, "setup"),
    "review": ("بازبینی و تصمیمِ مالک", "performance", False, "owner"),
    "testimonial": ("نظرِ واقعیِ مشتری (از شما)", "campaigns", False, "owner"),
}

GROUPS = {
    "setup": "راه‌اندازی",
    "content": "محتوا",
    "media": "رسانه (روی سرورِ پردازش)",
    "design": "طراحی",
    "outreach": "پیام‌رسانی",
    "growth": "جذبِ مشتری",
    "owner": "تصمیم‌های شما",
}

STATUS_FA = {
    "PLANNED": "برنامه‌ریزی شد",
    "DRAFTED": "پیش‌نویس آماده",
    "WAITING_NODE": "منتظرِ سرورِ پردازش",
    "RUNNING": "در حالِ ساخت",
    "READY": "آماده برای تأیید",
    "NEEDS_YOU": "نیازمندِ شما",
    "FAILED": "ناموفق",
}
DECISION_FA = {"approved": "تأیید شد", "done": "منتشر / انجام شد", "skipped": "رد شد"}


def label(kind: str) -> str:
    return KINDS.get(kind, (kind,))[0]


def default_section(kind: str) -> str:
    return KINDS[kind][1] if kind in KINDS else ""


def needs_node(kind: str) -> bool:
    return bool(KINDS[kind][2]) if kind in KINDS else False


def group_of(kind: str) -> str:
    return KINDS[kind][3] if kind in KINDS else "content"


def page_paths() -> dict[str, str]:
    """{کلیدِ صفحه: الگوی مسیر («/stores/:id/motion»)} از دفترِ پنل."""
    out: dict[str, str] = {}
    for _sk, _st, _staff, _desc, pages in panel_registry.SECTIONS:
        for key, _title, path, _d, _features in pages:
            out[key] = path
    return out


def page_titles() -> dict[str, str]:
    out: dict[str, str] = {}
    for _sk, _st, _staff, _desc, pages in panel_registry.SECTIONS:
        for key, title, _path, _d, _features in pages:
            out[key] = title
    return out


def url_for(page_key: str, store_id: int) -> str:
    path = page_paths().get(page_key, "")
    return path.replace(":id", str(store_id)) if path else ""
