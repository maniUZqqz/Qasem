"""One edit, every network: the frame sizes an Iranian shop actually posts to, and how one finished project becomes each of them.

A size is more than width × height.  Each carries the network's safe-zone set (where the app draws its own buttons, so captions and titles
move), the export preset (bitrate, loudness-free limits, maximum length), and — when the picture's shape changes — the subject-following
reframe with composition (`framing`): a 16:9 interview becomes a 9:16 reel whose window follows the speaker's face, eyes on the upper third,
and not a blind centre crop.

`derive_steps(size)` is the plan of tool calls (the director's own vocabulary) that turns any project into that size, so a derived project is
an ordinary editable project; `catalogue()` is what the panel lists.  Nothing here renders: the web layer makes one project per size and sends
each through the normal export (site or processing node), so progress, cancel, node fallback and the audio check all work as for any export.
"""
from __future__ import annotations

from dataclasses import dataclass, field

#: Telegram, Bale, Eitaa and WhatsApp play the video inline and re-compress it; keep it small
SIZES: dict[str, dict] = {
    "ig_reel": {"title": "ریلز اینستاگرام", "network": "اینستاگرام", "aspect": "9:16", "preset": "reel", "zone": "reels", "export": "reels", "max_seconds": 90, "size": (1080, 1920)},
    "ig_story": {"title": "استوری اینستاگرام", "network": "اینستاگرام", "aspect": "9:16", "preset": "reel", "zone": "story", "export": "reels", "max_seconds": 60, "size": (1080, 1920)},
    "ig_post": {"title": "پست اینستاگرام (۴:۵)", "network": "اینستاگرام", "aspect": "4:5", "preset": "feed", "zone": "feed", "export": "feed", "max_seconds": 60, "size": (1080, 1350)},
    "ig_square": {"title": "پست مربع", "network": "اینستاگرام", "aspect": "1:1", "preset": "square", "zone": "feed", "export": "feed", "max_seconds": 60, "size": (1080, 1080)},
    "yt_wide": {"title": "یوتیوب (افقی ۱۶:۹)", "network": "یوتیوب", "aspect": "16:9", "preset": "wide", "zone": "feed", "export": "youtube", "max_seconds": None, "size": (1920, 1080)},
    "yt_shorts": {"title": "شورتسِ یوتیوب", "network": "یوتیوب", "aspect": "9:16", "preset": "reel", "zone": "shorts", "export": "reels", "max_seconds": 180, "size": (1080, 1920)},
    "tiktok": {"title": "تیک‌تاک", "network": "تیک‌تاک", "aspect": "9:16", "preset": "reel", "zone": "tiktok", "export": "tiktok", "max_seconds": 180, "size": (1080, 1920)},
    "telegram": {"title": "تلگرام / ایتا (افقی، کم‌حجم)", "network": "پیام‌رسان", "aspect": "16:9", "preset": "wide", "zone": "feed", "export": "telegram", "max_seconds": None, "size": (1280, 720)},
    "aparat": {"title": "آپارات (افقی)", "network": "آپارات", "aspect": "16:9", "preset": "wide", "zone": "feed", "export": "aparat", "max_seconds": None, "size": (1920, 1080)},
}
#: the set a person who just says «همهٔ شبکه‌ها» gets (one per distinct shape, the most used first)
DEFAULT_SET = ("ig_reel", "ig_post", "yt_wide")


def catalogue() -> list[dict]:
    return [{"key": k, "title": v["title"], "network": v["network"], "aspect": v["aspect"], "width": v["size"][0], "height": v["size"][1],
             "max_seconds": v["max_seconds"], "zone": v["zone"], "export": v["export"]} for k, v in SIZES.items()]


def for_platform(platform: str) -> str:
    """The director's platform key (reels, story, tiktok, shorts, feed, square, youtube) → the matching size key."""
    return {"reels": "ig_reel", "story": "ig_story", "tiktok": "tiktok", "shorts": "yt_shorts", "feed": "ig_post", "square": "ig_square",
            "youtube": "yt_wide"}.get(platform, "ig_reel")


def clean_keys(keys) -> list[str]:
    out: list[str] = []
    for k in keys or []:
        k = str(k)
        if k in SIZES and k not in out:
            out.append(k)
    return out


def derive_steps(key: str) -> list[dict]:
    """The director steps that make a project fit size `key`: the frame, the subject-following window with composition, captions kept
    clear of that network's buttons."""
    s = SIZES[key]
    steps = [{"tool": "set_format", "params": {"preset": s["preset"]}, "why": f"قاب برای {s['title']}"}]
    steps.append({"tool": "reframe", "params": {"clip": "all", "aspect": s["aspect"], "follow": "auto", "compose": True},
                  "why": "قاب دنبالِ سوژه با ترکیب‌بندی (چهره روی خطِ یک‌سوم، فضای سر)"})
    steps.append({"tool": "caption_style", "params": {"style": "pop"}, "why": f"زیرنویس بیرون از دکمه‌های {s['network']}", "optional": True})
    return steps


@dataclass
class Derived:
    key: str
    title: str
    project: dict
    results: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def derive(project: dict, key: str, ctx=None) -> Derived:
    """The project made to fit size `key` (a deep copy; the original is untouched).  A step that cannot run (no captions to restyle, no subject
    to follow) is reported in `notes`, never fatal."""
    from .director.runner import apply_steps
    from .director.spec import Ctx

    s = SIZES[key]
    steps = [{k: v for k, v in step.items() if k != "optional"} for step in derive_steps(key)]
    new, results = apply_steps(project, steps, ctx or Ctx(), platform=s["zone"])
    notes = [f"{r['title']}: {r['message']}" for r, st in zip(results, derive_steps(key)) if not r["ok"] and not st.get("optional")]
    new = dict(new)
    block = dict(new.get("export") or {})
    block["preset"] = s["export"]
    new["export"] = block
    meta = dict(new.get("autoedit") or {})
    meta["size"] = key
    new["autoedit"] = meta
    length = max((float(c.get("at", 0)) + _length(c) for t in new.get("tracks", []) for c in t.get("clips", [])), default=0.0)
    if s["max_seconds"] and length > s["max_seconds"]:
        notes.append(f"طولِ ویدیو {round(length)} ثانیه است و این شبکه تا {s['max_seconds']} ثانیه می‌پذیرد؛ کوتاهش کنید.")
    return Derived(key=key, title=s["title"], project=new, results=results, notes=notes)


def _length(clip: dict) -> float:
    if clip.get("type") == "text":
        return float(clip.get("duration") or 0)
    sp = float(clip.get("speed") or 1) or 1.0
    return (float(clip.get("end") or 0) - float(clip.get("start") or 0)) / sp if clip.get("kind") != "image" else float(clip.get("end") or 0)
