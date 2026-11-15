"""Rules that turn an InstAI style into an NMarketing motion style, and the table of what NM already has.

SOURCE: ported from InstAI:remotion/src/kit/motion.ts, kit/theme.ts and instai/styles/builtin_styles.py @ 2f8aa90 (v0.14.0), adapted for NMarketing store
ads: InstAI describes a look with 6 colour roles + one of 10 "animation approaches" + a motif; NM's engine wants an 8-colour palette, a spring, a stagger,
a stop-motion rate and background / decoration kinds. Everything here is plain data + three small pure functions (palette, motion, spring check) so a
test can prove the properties (contrast, damping) instead of trusting the numbers.
"""
from __future__ import annotations

import colorsys
import math

# ───────────────────────────────────────────────────────────────────────── palette: 6 InstAI roles -> 8 NM roles
# InstAI: background, primary, secondary, accent, shadow, highlight.   NM: bg, bg2, ink, paper, accent, accent2, accent3, muted.
MIN_INK = 7.0         # text on the background (AAA for body text; the style is read on a phone in a feed)
MIN_ACCENT = 4.5      # the accent colour carries the kicker / the price / the call to action / the emphasised word: small text on a phone, so normal-text AA (real renders:
                      # qa.py measures the pixels behind each word and a 3:1 accent on a patterned background came out at 1.5-2.5, i.e. unreadable)
MIN_ACCENT_BG2 = 3.9  # ... and on the second surface (bg2: stripes, blobs, cards) that the accent also sits on
MIN_ACCENT2 = 1.9     # decoration colour: qa.py (accent_contrast) flags anything below this
MIN_ON_ACCENT = 4.0   # the label on an accent-filled button / badge: the engine writes #111111 on an accent lighter than L 0.42 and white on the rest (util.onColor)


def _rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _hex(c) -> str:
    return "#%02x%02x%02x" % tuple(max(0, min(255, round(v))) for v in c)


def mix(a: str, b: str, t: float) -> str:
    x, y = _rgb(a), _rgb(b)
    return _hex([x[i] + (y[i] - x[i]) * t for i in range(3)])


def _lin(v: float) -> float:
    v /= 255.0
    return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4


def luminance(h: str) -> float:
    r, g, b = _rgb(h)
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def contrast(a: str, b: str) -> float:
    la, lb = luminance(a), luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def _toward(c: str, target: str, need: float, bg: str) -> str:
    """c moved toward `target` (white or black) in 5 % steps until it has contrast `need` with bg"""
    for i in range(21):
        x = mix(c, target, i / 20)
        if contrast(x, bg) >= need:
            return x
    return target


def _fit_hue(c: str, bg: str, need: float, dark_bg: bool) -> str:
    """c's lightness is moved (hue kept, saturation raised a little so it does not turn grey) until it reaches contrast `need` on bg"""
    if contrast(c, bg) >= need:
        return c
    r, g, b = [v / 255 for v in _rgb(c)]
    h, light, sat = colorsys.rgb_to_hls(r, g, b)
    if sat > 0.12:
        sat = max(sat, 0.45)
    x = c
    for _ in range(100):
        light = min(1.0, max(0.0, light + (0.01 if dark_bg else -0.01)))
        rr, gg, bb = colorsys.hls_to_rgb(h, light, sat)
        x = _hex((rr * 255, gg * 255, bb * 255))
        if contrast(x, bg) >= need:
            return x
    return x


def _need(bg: str, bg2: str, dark_bg: bool) -> tuple[float, float]:
    """the accent floors on bg and on bg2, lowered only where black / white themselves cannot reach them (mid-tone backgrounds). bg2 is a DARKER mix of the background on a light
    theme (an accent that reads on the background reads on it after a little more darkening), but a LIGHTER mix on a dark theme, where an accent lighter than both cannot exist:
    there only the background counts (the real renders showed the trouble only on light themes)"""
    toward = "#ffffff" if dark_bg else "#000000"
    n1 = min(MIN_ACCENT, contrast(toward, bg) - 0.05)
    n2 = 0.0 if dark_bg else min(MIN_ACCENT_BG2, contrast(toward, bg2) - 0.05)
    return n1, n2


def _fit_accent(c: str, bg: str, bg2: str, dark_bg: bool) -> str:
    """the accent, hue kept, moved in lightness (away from the background) until it reads on the background AND on the second surface"""
    n1, n2 = _need(bg, bg2, dark_bg)
    if contrast(c, bg) >= n1 and contrast(c, bg2) >= n2:
        return c
    r, g, b = [v / 255 for v in _rgb(c)]
    h, light, sat = colorsys.rgb_to_hls(r, g, b)
    if sat > 0.12:
        sat = max(sat, 0.45)
    x = c
    for _ in range(100):
        light = min(1.0, max(0.0, light + (0.01 if dark_bg else -0.01)))
        rr, gg, bb = colorsys.hls_to_rgb(h, light, sat)
        x = _hex((rr * 255, gg * 255, bb * 255))
        if contrast(x, bg) >= n1 and contrast(x, bg2) >= n2:
            return x
    return x


def engine_text_on(c: str) -> str:
    """the label colour the motion engine writes on a button / badge filled with `c` (motion/remotion/src/util.ts onColor: #111111 above luminance 0.42, else white)"""
    return "#111111" if luminance(c) > 0.42 else "#ffffff"


def _button_safe(c: str, dark_bg: bool) -> str:
    """that rule picks white on a mid-bright accent (a golden L 0.415 got white text at 2.2:1 in the real render: «شروع رایگان» unreadable): such an accent is moved on, hue kept,
    lighter on a dark theme (until the engine writes dark text on it) and darker on a light theme (until white text reads)"""
    if contrast(engine_text_on(c), c) >= MIN_ON_ACCENT:
        return c
    r, g, b = [v / 255 for v in _rgb(c)]
    h, light, sat = colorsys.rgb_to_hls(r, g, b)
    x = c
    for _ in range(100):
        light = min(1.0, max(0.0, light + (0.01 if dark_bg else -0.01)))
        rr, gg, bb = colorsys.hls_to_rgb(h, light, sat)
        x = _hex((rr * 255, gg * 255, bb * 255))
        if contrast(engine_text_on(x), x) >= MIN_ON_ACCENT:
            return x
    return x


def _muddy(c: str) -> bool:
    """a dark yellow / orange / lime is olive or brown: darkening a bright warm accent gives mud, not a deeper version of itself"""
    r, g, b = [v / 255 for v in _rgb(c)]
    h, light, sat = colorsys.rgb_to_hls(r, g, b)
    return 28 <= h * 360 <= 72 and light < 0.42 and sat > 0.3


def pick_accent(cands: list[str], bg: str, bg2: str, dark_bg: bool) -> str:
    """the InstAI accent (then its secondary / primary) made readable with the least change: every candidate is fitted, the one that moved least wins; a candidate that
    would only turn muddy brown when darkened, and a later one in the list, pay a penalty (so the accent stays the style's own colour whenever that is possible)"""
    n1, n2 = _need(bg, bg2, dark_bg)
    best = None
    for i, c in enumerate(cands):
        f = _fit_accent(c, bg, bg2, dark_bg)
        if contrast(f, bg) < n1 or contrast(f, bg2) < n2:
            continue
        light = lambda v: colorsys.rgb_to_hls(*[x / 255 for x in _rgb(v)])[1]
        score = abs(light(f) - light(c)) + 0.12 * i + (0.5 if (f != c and _muddy(f)) else 0.0)
        if best is None or score < best[0]:
            best = (score, f)
    return best[1] if best else _fit_accent(cands[0], bg, bg2, dark_bg)


def _chroma(c: str) -> int:
    v = _rgb(c)
    return max(v) - min(v)


def derive_palette(p6: list[str], over: dict | None = None) -> dict:
    """InstAI [background, primary, secondary, accent, shadow, highlight] -> NM palette (8 roles). `over` replaces single roles by hand (documented in the recipe)."""
    bg, prim, sec, acc, shadow, hi = [c.lower() for c in p6]
    dark = contrast("#ffffff", bg) > contrast("#000000", bg)      # the text goes the way that has more room: white on a darker background, black on a lighter one
    bg2 = mix(bg, prim, 0.55 if dark else 0.2)
    ink = _toward(hi if dark else shadow, "#ffffff" if dark else "#000000", MIN_INK, bg)
    if dark:
        paper = hi if luminance(hi) > 0.6 else mix(hi, "#ffffff", 0.5)
    else:
        paper = hi if luminance(hi) > 0.85 else mix(bg, "#ffffff", 0.7)
    cand = [acc, sec, prim]
    first = pick_accent(cand, bg, bg2, dark)
    rest = [c for c in cand if c != first]
    second = next((c for c in rest if contrast(c, bg) >= MIN_ACCENT2), None) or _fit_hue(max(rest, key=_chroma), bg, MIN_ACCENT2, dark)
    rest2 = [c for c in rest if c != second]
    third = rest2[0] if rest2 else mix(first, bg, 0.4)
    pal = {"bg": bg, "bg2": bg2, "ink": ink, "paper": paper, "accent": first, "accent2": second, "accent3": third, "muted": mix(ink, bg, 0.45)}
    pal.update({k: v.lower() for k, v in (over or {}).items()})
    pal["accent"] = _button_safe(_fit_accent(pal["accent"], pal["bg"], pal["bg2"], dark), dark)      # also for a hand-picked accent: the rule is about reading, not about who chose it
    return pal


# ───────────────────────────────────────────────────────────────────────── motion: InstAI "animation approach" -> NM motion
# Columns: default enter, spring (damping, stiffness, mass), stagger (frames between items), stepped?, wobble (deg in InstAI), camera push-in (fraction of the frame).
# Targets of kit/motion.ts: `overshoot` is the share an entrance overshoots (0.28 = rubber hose) - the spring's damping ratio zeta = damping / (2 sqrt(stiffness * mass))
# must give that overshoot: overshoot = exp(-pi zeta / sqrt(1 - zeta^2)).  tests_looks.py checks it (OVERSHOOT / zeta_for).
MOTION: dict[str, dict] = {
    "live_camera":      {"enter": "bloom",  "spring": (30, 80, 1.2),  "stagger": 8, "stepped": False, "wobble_deg": 0.0, "cam": {"zoom": 0.07},                  "overshoot": 0.0},
    "limited_2d":       {"enter": "pop",    "spring": (18, 200, 0.8), "stagger": 6, "stepped": True,  "wobble_deg": 0.0, "cam": None,                              "overshoot": 0.05},
    "full_2d":          {"enter": "rise",   "spring": (14, 120, 1.0), "stagger": 6, "stepped": False, "wobble_deg": 0.0, "cam": {"zoom": 0.02},                  "overshoot": 0.08},
    "rubber_hose":      {"enter": "squash", "spring": (8, 170, 0.7),  "stagger": 5, "stepped": False, "wobble_deg": 1.2, "cam": None,                              "overshoot": 0.28},
    "cutout":           {"enter": "slide",  "spring": (17, 140, 1.0), "stagger": 8, "stepped": True,  "wobble_deg": 1.6, "cam": None,                              "overshoot": 0.04},
    "motion_graphics":  {"enter": "slide",  "spring": (30, 190, 1.0), "stagger": 4, "stepped": False, "wobble_deg": 0.0, "cam": None,                              "overshoot": 0.0},
    "stop_motion":      {"enter": "rise",   "spring": (24, 140, 1.0), "stagger": 9, "stepped": True,  "wobble_deg": 1.1, "cam": None,                              "overshoot": 0.0},
    "cg_3d":            {"enter": "rise",   "spring": (14, 110, 1.0), "stagger": 6, "stepped": False, "wobble_deg": 0.0, "cam": {"zoom": 0.04, "rot": 1.0},       "overshoot": 0.06},
    "toon_3d":          {"enter": "pop",    "spring": (13, 160, 0.85), "stagger": 6, "stepped": True, "wobble_deg": 0.6, "cam": {"zoom": 0.03},                  "overshoot": 0.14},
    # stagger 7, not InstAI's 10: a 14-word ad subtitle entered at 10 was still fading in at 2.8 s of a 3 s scene in the real render (the last words blurred at the "late" still)
    "painted_parallax": {"enter": "float",  "spring": (28, 70, 1.3),  "stagger": 7, "stepped": False, "wobble_deg": 0.0, "cam": {"zoom": 0.05, "pan": [-22, -4]}, "overshoot": 0.0},
}
WOBBLE_PER_DEG = 2.5     # NM's `wobble` is in its own unit (stickman 4, stop-motion 3): InstAI's degrees x 2.5


def zeta(spring) -> float:
    d, k, m = spring
    return d / (2.0 * math.sqrt(k * m))


def overshoot_of(spring) -> float:
    """the fraction a spring entrance overshoots 1 (0 when it is critically damped or over-damped)"""
    z = zeta(spring)
    return 0.0 if z >= 1.0 else math.exp(-math.pi * z / math.sqrt(1.0 - z * z))


def motion_for(animation: str, fps_feel: int) -> dict:
    """NM `motion` dict of an InstAI style: stepped approaches hold each pose 30/fps_feel frames (stepFps = poses per second), the rest play smoothly"""
    m = MOTION[animation]
    out = {"enter": m["enter"], "spring": list(m["spring"]), "stagger": m["stagger"],
           "stepFps": int(fps_feel) if m["stepped"] else None, "wobble": round(m["wobble_deg"] * WOBBLE_PER_DEG), "cam": dict(m["cam"]) if m["cam"] else None}
    return out


# ───────────────────────────────────────────────────────────────────────── what NM has / does not port (the diff against NM's 66 ids)
# status "have": the same look exists in NM (`to` = NM id).  "near": NM has a close look (or a ported one covers it) and a second row would only be a
# colour swap.  "skip": cannot be drawn by a CSS/SVG motion-graphics engine (it needs real footage or a character) - never faked.
# Every InstAI key is in exactly one of: HAVE, NEAR, SKIP, or the recipes (ported); tests_looks.py and the generator both check it.
HAVE = {
    "noir_bw": "film-noir", "comic_ink": "comic-art", "cyberpunk_neon": "cyberpunk", "painterly_pastoral": "ghibli-inspired",
    "western_2d_tv": "cartoon-network-inspired", "flat_vector_motion": "flat-vector", "whiteboard_explainer": "whiteboard",
    "chalkboard_classroom": "chalkboard", "pixel_art_16bit": "pixel-art", "paper_cutout": "papercraft", "watercolour_storybook": "watercolor",
    "islamic_geometric_graphic": "persian-tile", "toon_shaded_3d": "cel-shading", "claymation_stopmotion": "claymation", "low_poly_3d": "low-poly",
    "isometric_diorama": "isometric", "vaporwave_synth": "synthwave", "photoreal_cgi": "photoreal-cgi", "layered_parallax_25d": "parallax-2-5d",
    "cineview_widescreen": "cineview", "fairytale_feature_2d": "disney-inspired", "flat_2d_character": "flat-2d", "stickman_doodle": "stickman",
    "cel_shading_render": "cel-shading", "silhouette_cutout": "silhouette", "glow_sketch": "glow-sketch", "line_art_mono": "line-art",
    "pencil_sketchbook": "pencil-sketch", "steampunk_brass": "steampunk", "graffiti_street": "graffiti", "early_console_3d": "ps2-style",
    "voxel_art": "voxel-art", "toy_brick_3d": "lego-bricks", "fast_3d_explainer": "zackd-inspired", "cgi_motion_graphics": "cgi-motion",
    "clay_3d_render": "claymation-3d", "glassmorphism_ui": "glassmorphism", "chrome_metal_type": "chrome-22k", "stop_motion_puppet": "stop-motion",
    "papercraft_layers": "papercraft", "origami_fold": "origami", "paper_collage": "paper-collage", "stained_glass": "stained-glass",
    "pop_art_halftone": "pop-art", "blueprint_technical": "blueprint", "corporate_flat_people": "corporate-memphis", "memphis_80s": "memphis",
    "bauhaus_geometric": "bauhaus", "neo_brutalism": "neo-brutalism", "risograph_print": "risograph", "art_deco_gilded": "art-deco",
    "groovy_70s": "retro-70s", "minimal_bw_essay": "dan-koe-style", "kinetic_typography": "kinetic-typography", "infographic_data": "infographic",
    "particle_field": "particles", "wireframe_hud": "sci-fi-hud", "vaporwave_dream": "vaporwave", "glitch_datamosh": "glitch-art",
    "vhs_analog": "vhs-tape", "neon_sign_glow": "neon-sign", "terminal_ascii": "retro-terminal", "cinematic_realistic": "cineview",
}
# "near" values: the NM id that covers it (an id of the 66, or of a ported style: the generator checks it exists in the final catalog)
NEAR = {
    "painterly_semi_real": ("oil-impressionist", "نقاشیِ دیجیتالِ نیمه‌واقع‌گرا ⇒ همان لکه‌های رنگِ روغنیِ سبکِ تازه"),
    "anime_realistic_drama": ("anime-inspired", "خانوادهٔ انیمه: همین آسمان و خط‌های سرعت؛ فرقِ اصلی در طراحیِ شخصیت است نه در سطحِ ویدیو"),
    "anime_film_cinematic": ("anime-inspired", "خانوادهٔ انیمه (شخصیت‌محور)"),
    "anime_dark_fantasy": ("dark-fantasy-art", "فانتزیِ تاریک ⇒ سبکِ تازهٔ نقاشیِ فانتزیِ تاریک"),
    "anime_noir_thriller": ("film-noir", "تریلرِ نوآر ⇒ همان نوآر"),
    "modern_tv_anime": ("anime-inspired", "انیمهٔ تلویزیونی"),
    "anime_90s_cel": ("anime-inspired", "انیمهٔ سلیِ قدیمی"),
    "anime_80s_ova": ("synthwave", "انیمهٔ دههٔ ۸۰ با سطحِ سینت‌ویو"),
    "shonen_action": ("anime-inspired", "انیمهٔ اکشن"),
    "shojo_romance": ("kawaii-pastel", "انیمهٔ عاشقانه با سطحِ کاوایی"),
    "anime_slice_of_life": ("anime-inspired", "انیمهٔ روزمره"),
    "anime_chibi": ("kawaii-pastel", "چیبی با سطحِ کاوایی"),
    "anime_mecha_scifi": ("cyberpunk", "مکا با سطحِ شهرِ نئونی"),
    "anime_isekai_fantasy": ("anime-inspired", "انیمهٔ ماجراجویی"),
    "anime_horror_gothic": ("gothic-puppets", "ترسِ گوتیک ⇒ سبکِ تازهٔ عروسکِ گوتیک"),
    "anime_lofi_night": ("neon-sign", "شبِ لوفای با نورِ نئون"),
    "bold_angular_tv_toon": ("cartoon-network-inspired", "کارتونِ تلویزیونیِ زاویه‌دار"),
    "cg_family_3d": ("cgi-motion", "سه‌بعدیِ خانوادگی ⇒ استودیوی روشنِ CGI"),
    "felt_plush_stopmotion": ("stop-motion", "نمد و پشمالو ⇒ همان استاپ‌موشن (فونتِ نمدی)"),
    "chalk_neon_board": ("chalkboard", "تختهٔ گچیِ نئونی ⇒ تختهٔ گچی با نوشتهٔ درخشان (glow-sketch)"),
    "lowfi_cozy_pixel": ("pixel-art", "اتاقِ پیکسلیِ لوفای"),
}
SKIP = {
    "documentary_real": "نمای مستندِ زنده؛ به عکس/فیلمِ واقعی نیاز دارد و با کد کشیدنی نیست (NM به‌جایش در «ادیتورِ ویدیو» از فیلمِ خودِ فروشگاه کار می‌کند)",
    "rotoscope_look": "خط‌کشیِ دستی روی حرکتِ واقعی؛ به فیلمِ ورودی نیاز دارد، نه به سبکِ نوشتاری",
}
# kinds of the engine that carry a ported InstAI "look maker" (InstAI motif -> NM kind), for the doc and the tests
LOOK_KINDS = {
    "mosaic": ("bg", "mosaic"), "nouveau": ("bg", "ornament"), "miniature": ("bg", "ornament"), "woodblock": ("bg", "waves"),
    "holo": ("bg", "holo"), "doubleexp": ("bg", "doubleexp"), "tiltshift": ("bg", "tiltshift"), "stitch": ("bg", "cloth"), "kawaii": ("decor", "kawaii"),
}
# InstAI motifs that NM already draws with its own kinds (nothing to port)
MOTIF_HAVE = {
    "pixel": "bands + pixels", "chalk": "chalk", "whiteboard": "whiteboard", "blueprint": "grid", "stained": "stained", "glass": "mesh + glass card",
    "brutal": "grid", "vapor": "sunset", "synth": "sunset", "glitch": "noise", "vhs": "noise + vhs", "noir": "blinds",
    "halftone": "halftone", "riso": "paper", "duotone": "linear", "paper": "paper", "collage": "paper", "origami": "lowpoly", "lowpoly": "lowpoly",
    "voxel": "isocubes", "iso": "isogrid", "bricks": "studs", "watercolor": "wash", "paint": "hills / wash", "ink": "wash / parchment",
    "sketch": "paper", "crayon": "paper + doodles", "terminal": "radial + crt", "wire": "hud", "particles": "constellation", "neon": "bricks + neon-tube",
    "neoncity": "skyline", "deco": "fans / rays", "groovy": "arcs", "memphis": "dots + shapes", "bauhaus": "bauhaus",
    "geometric": "girih", "constructivist": "stripes + shapes", "steam": "parchment + gears", "graffiti": "bricks + splats", "infographic": "grid + bars",
    "type": "solid", "kinetic": "solid + speed", "felt": "wood", "clay": "radial + orbs", "sticker": "dots + shapes", "corp": "linear + blobs",
    "stick": "notebook", "chrome": "radial + chrome", "y2k": "radial + chrome", "grain": "linear + grain / scratches",
}
# InstAI motifs deliberately without an own surface in InstAI too (the family backdrop is the look): nothing to port
MOTIF_PLAIN = ["film", "photo", "anime", "cg", "flat", "wobble", "silhouette", "parallax", "surreal", "console"]
