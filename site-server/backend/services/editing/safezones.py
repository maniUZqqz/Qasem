"""Safe zones: the parts of a vertical frame that the platform's own interface covers (profile name, caption, like/share
buttons, reply bar). Titles, captions and logos should stay out of them. Values are fractions of the frame, measured on the
public UI layouts of each app — approximate on purpose (apps move their buttons), so the panel labels them «تقریبی».

One source of truth: the panel reads `catalogue()` and draws the same bands; the director places captions with `margins()`;
the critique checks against it.
"""
from __future__ import annotations

ZONES: dict[str, dict] = {
    "reels": {"title": "ریلز اینستاگرام", "hint": "بالا: نام‌ و دوربین؛ پایین: کپشن و دکمه‌ها؛ راست: لایک و کامنت",
              "margins": {"top": 0.13, "bottom": 0.22, "left": 0.05, "right": 0.14}},
    "story": {"title": "استوریِ اینستاگرام", "hint": "بالا: نوارِ پروفایل؛ پایین: جوابِ استوری",
              "margins": {"top": 0.13, "bottom": 0.13, "left": 0.05, "right": 0.05}},
    "tiktok": {"title": "تیک‌تاک", "hint": "پایین: توضیح و موسیقی؛ راست: ستونِ دکمه‌ها",
               "margins": {"top": 0.11, "bottom": 0.24, "left": 0.05, "right": 0.17}},
    "shorts": {"title": "شورتسِ یوتیوب", "hint": "پایین: عنوان و کانال؛ راست: دکمه‌ها",
               "margins": {"top": 0.10, "bottom": 0.20, "left": 0.05, "right": 0.14}},
    "feed": {"title": "پستِ اینستاگرام", "hint": "حاشیهٔ امنِ معمول",
             "margins": {"top": 0.05, "bottom": 0.05, "left": 0.05, "right": 0.05}},
}
#: project preset → the zone assumed when the owner did not name a platform
DEFAULT_FOR_PRESET = {"reel": "reels", "feed": "feed", "square": "feed", "wide": "feed"}


def catalogue() -> list[dict]:
    return [{"key": k, "title": v["title"], "hint": v["hint"], "margins": dict(v["margins"])} for k, v in ZONES.items()]


def margins(key: str | None, preset: str = "reel") -> dict:
    zone = ZONES.get(key or "") or ZONES[DEFAULT_FOR_PRESET.get(preset, "feed")]
    return dict(zone["margins"])


def inside(key: str | None, y: float, *, preset: str = "reel", pad: float = 0.0) -> bool:
    """Is a vertical centre `y` (0..1) clear of the top and bottom bands of the platform?"""
    m = margins(key, preset)
    return m["top"] + pad <= y <= 1 - m["bottom"] - pad
