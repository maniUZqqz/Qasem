"""SOURCE: ported from InstAI:instai/styles/style_base.py @ 2f8aa90, adapted for store advertising (NMarketing).
تغییر: فقط سربرگ.

Shared building blocks of the built-in art/animation styles: negative-prompt bases, technique sets and the maker used by `styles_more.py`.

Kept apart from `builtin_styles.py` so that module and `styles_more.py` can both import it without a circular import.
No studio, franchise, artist or character name may appear in anything built here (tests/test_styles.py scans for them).
"""
from __future__ import annotations

from .schema import GEN_FIELDS, normalize_style

NEG_BASE = "blurry, low quality, jpeg artifacts, watermark, logo, text, signature, deformed hands, extra fingers, bad anatomy, cropped"
NEG_BASE_TEXT_OK = "blurry, low quality, jpeg artifacts, watermark, logo, signature, deformed hands, extra fingers, bad anatomy, cropped"
NEG = {
    "live_like": NEG_BASE + ", cartoon, anime, illustration, painting, oversaturated, plastic skin, cgi look",
    "illustration": NEG_BASE + ", photograph, 3d render, flat vector",
    "anime": NEG_BASE + ", photorealistic, 3d render, western cartoon, realistic skin pores, sketch",
    "western_2d": NEG_BASE + ", photorealistic, 3d render, anime eyes, painterly shading",
    "cg_3d": NEG_BASE + ", 2d drawing, flat shading, anime, sketch, uncanny valley, dead eyes",
    "stop_motion": NEG_BASE + ", smooth cg, digital gloss, anime, line art",
    "graphic": NEG_BASE + ", photorealistic, gradients, 3d render, clutter, tiny text",
    "handmade": NEG_BASE + ", photorealistic, 3d render, glossy cg, plastic",
}
VNEG = {
    "default": "morphing faces, melting shapes, flicker, warping, identity change, sudden style change, camera shake, extra limbs",
    "stop": "smooth fluid motion, motion blur, morphing, melting, flicker, warping",
    "limited": "too smooth interpolation, morphing, melting, flicker, warping, identity change, 3d camera orbit",
}

STILL = ["still_kenburns", "parallax_25d"]
PUPPET = ["puppet_2d", "still_kenburns", "parallax_25d"]
HERO = ["still_kenburns", "parallax_25d", "wan_i2v"]
GRAPHIC = ["motion_graphics", "still_kenburns"]

# generation hints by kind of look; a style names one and overrides single fields
GEN_PRESETS = {
    "flux": {},
    "flux_soft": {"guidance": 3.0, "steps": 26},
    "flux_sharp": {"guidance": 4.0, "steps": 28},
    "flux_lora": {"guidance": 3.5, "steps": 28},
    "anime": {"model": "flux_dev", "alt_model": "sdxl_anime", "steps": 26},
    "sdxl_anime": {"model": "sdxl_anime", "alt_model": "flux_dev", "sampler": "euler_ancestral", "scheduler": "normal", "cfg": 5.0, "guidance": 0.0, "steps": 28},
}
SUIT = {"i": "image", "v": "video", "c": "character"}


def suit(code: str) -> list[str]:
    return [SUIT[c] for c in code if c in SUIT]


def gen(preset: str = "flux", **over) -> dict:
    return {**GEN_FIELDS, **GEN_PRESETS[preset], **over}


def mk(key, group, realism, family, anim, fps, fa, en, dfa, den, pos, vid, pal, light, mood, tech, sample, theme, tags,
       *, s="ivc", motif="", g=None, neg=None, vneg=None) -> tuple[str, dict]:
    """One style. `s` = suitability letters (i image, v video, c character); `g` = gen() hints; `neg` replaces the family negative."""
    return key, normalize_style({
        "name_fa": fa, "name_en": en, "description_fa": dfa, "description_en": den, "realism": realism, "family": family, "animation": anim, "fps_feel": fps,
        "image_positive": pos, "image_negative": neg or NEG[family],
        "video_positive": vid,
        "video_negative": vneg or (VNEG["stop"] if family == "stop_motion" else VNEG["limited"] if anim in ("limited_2d", "cutout") else VNEG["default"]),
        "palette": pal, "lighting": light, "mood": mood, "techniques": tech, "sample_prompt": sample, "theme_key": theme, "tags": tags,
        "group": group, "suitability": suit(s), "gen": g or gen(), "motif": motif})
