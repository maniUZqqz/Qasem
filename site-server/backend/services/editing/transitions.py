"""The transition library: ffmpeg `xfade` kinds with Persian names, grouped for the panel.

A transition sits on the CUT between two clips of a track (Premiere's «centered at cut»): the window is
`[cut - d/2, cut + d/2]`, the outgoing clip plays its out-point handle (or holds its last frame when the source has
no more footage) and the incoming one plays its in-point handle (or holds its first frame). `compose.py` renders
the window with `xfade` and lays it over the track; the browser previews the same kinds with CSS clip-paths and
transforms (an approximation — «پیش‌نمایش دقیق» renders the real thing).

Legacy kinds of the first manual workspace keep working: ``fade`` = dip to black (xfade `fadeblack`) and
``crossfade`` = dissolve (xfade `fade`).
"""
from __future__ import annotations

#: key (xfade name) → (Persian title, group)
XFADE: dict[str, tuple[str, str]] = {
    "fade": ("محو (دیزالو)", "dissolve"),
    "fadeblack": ("محو از سیاه", "dissolve"),
    "fadewhite": ("محو از سفید", "dissolve"),
    "fadegrays": ("محو خاکستری", "dissolve"),
    "fadefast": ("محو تند", "dissolve"),
    "fadeslow": ("محو کند", "dissolve"),
    "dissolve": ("پراکندگی", "dissolve"),
    "pixelize": ("پیکسلی", "dissolve"),
    "distance": ("فاصله", "dissolve"),
    "wipeleft": ("پاک‌کردن به چپ", "wipe"),
    "wiperight": ("پاک‌کردن به راست", "wipe"),
    "wipeup": ("پاک‌کردن به بالا", "wipe"),
    "wipedown": ("پاک‌کردن به پایین", "wipe"),
    "wipetl": ("پاک‌کردن از گوشهٔ بالا-چپ", "wipe"),
    "wipetr": ("پاک‌کردن از گوشهٔ بالا-راست", "wipe"),
    "wipebl": ("پاک‌کردن از گوشهٔ پایین-چپ", "wipe"),
    "wipebr": ("پاک‌کردن از گوشهٔ پایین-راست", "wipe"),
    "slideleft": ("لغزش به چپ", "slide"),
    "slideright": ("لغزش به راست", "slide"),
    "slideup": ("لغزش به بالا", "slide"),
    "slidedown": ("لغزش به پایین", "slide"),
    "smoothleft": ("لغزش نرم به چپ", "slide"),
    "smoothright": ("لغزش نرم به راست", "slide"),
    "smoothup": ("لغزش نرم به بالا", "slide"),
    "smoothdown": ("لغزش نرم به پایین", "slide"),
    "coverleft": ("پوشاندن از چپ", "cover"),
    "coverright": ("پوشاندن از راست", "cover"),
    "coverup": ("پوشاندن از بالا", "cover"),
    "coverdown": ("پوشاندن از پایین", "cover"),
    "revealleft": ("آشکارکردن به چپ", "cover"),
    "revealright": ("آشکارکردن به راست", "cover"),
    "revealup": ("آشکارکردن به بالا", "cover"),
    "revealdown": ("آشکارکردن به پایین", "cover"),
    "circleopen": ("دایره‌ی بازشونده", "shape"),
    "circleclose": ("دایره‌ی بسته‌شونده", "shape"),
    "circlecrop": ("دایره‌ی برشی", "shape"),
    "rectcrop": ("مستطیلِ برشی", "shape"),
    "radial": ("چرخشی", "shape"),
    "vertopen": ("بازشدنِ عمودی", "shape"),
    "vertclose": ("بسته‌شدنِ عمودی", "shape"),
    "horzopen": ("بازشدنِ افقی", "shape"),
    "horzclose": ("بسته‌شدنِ افقی", "shape"),
    "diagtl": ("قطری بالا-چپ", "shape"),
    "diagtr": ("قطری بالا-راست", "shape"),
    "diagbl": ("قطری پایین-چپ", "shape"),
    "diagbr": ("قطری پایین-راست", "shape"),
    "zoomin": ("زومِ ورودی", "zoom"),
    "squeezeh": ("فشردن افقی", "zoom"),
    "squeezev": ("فشردن عمودی", "zoom"),
    "hlslice": ("تکه‌های افقی (چپ)", "slice"),
    "hrslice": ("تکه‌های افقی (راست)", "slice"),
    "vuslice": ("تکه‌های عمودی (بالا)", "slice"),
    "vdslice": ("تکه‌های عمودی (پایین)", "slice"),
    "hblur": ("تاری افقی", "slice"),
}

GROUPS = {"dissolve": "محو و پراکندگی", "wipe": "پاک‌کردن", "slide": "لغزش", "cover": "پوشاندن و آشکارکردن", "shape": "شکل‌ها",
          "zoom": "زوم و فشردن", "slice": "تکه‌تکه"}

#: the two kinds the first workspace used
LEGACY = {"fade": "fadeblack", "crossfade": "fade"}


def xfade_name(kind: str) -> str:
    """The name ffmpeg's xfade knows for a clip's transition kind (legacy names are translated)."""
    if kind in LEGACY:
        return LEGACY[kind]
    return kind if kind in XFADE else "fade"


def catalogue() -> dict:
    return {
        "legacy": [{"key": "fade", "title": "محو به سیاه"}, {"key": "crossfade", "title": "محوشدنِ تدریجی"}],
        "groups": [{"key": k, "title": v} for k, v in GROUPS.items()],
        "kinds": [{"key": k, "title": v[0], "group": v[1]} for k, v in XFADE.items()],
    }
