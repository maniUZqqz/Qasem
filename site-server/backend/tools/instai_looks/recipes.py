"""The 30 InstAI looks that NM did not have, written as NM recipes (the hand-made part of the conversion).

SOURCE: ported from InstAI:instai/styles/builtin_styles.py (the style's palette, animation approach, fps feel, motif) and
InstAI:remotion/src/kit/Look.tsx (the drawn surface of the motif) @ 2f8aa90 (v0.14.0), adapted for NMarketing store ads.

A recipe holds only what is NM-specific: the Persian name / `about` / `fits` (which kind of shop the look suits), the fonts (NM's OFL set), the engine
kinds (bg / decor / tex / text fx / card shape / transition) and a few motion overrides. The generator (backend/tools/gen_instai_looks.py) adds the rest
from the InstAI style itself: the 8-colour palette (derive_palette: contrast guaranteed) and the motion personality of its animation approach (motion_for).

Every colour a recipe names is a palette role ("accent", "bg2" ...) or a literal; no studio / brand / creator name may appear in an id, a name, an
`about`, a `fits` or a tag (tests_looks.py scans them).
"""
from __future__ import annotations

# `pal`: single-role overrides of the derived palette (every one is explained in a comment).
# `motion`: overrides on top of motion_for(animation, fps_feel) (enter is the usual one).
RECIPES: list[dict] = [
    # ───────────────────────────────────────────── cartoon
    dict(id="manga-ink", src="manga_bw_ink", fa="مانگای جوهری", en="Manga Ink", group="cartoon",
         pal={"accent": "#d62828"},  # InstAI manga is pure black and white; one spot red is added for the price / the call to action (derive_palette then deepens any accent to the contrast floor)
         font={"latin": "staatliches", "fa": "kufam", "weight": 900, "case": "upper", "track": 0.02, "lh": 1.15},
         bg={"kind": "halftone", "base": "bg", "dot": "muted", "size": 24, "angle": 125, "maskA": 0.95, "maskB": 0.04},
         text={"fx": "hard", "color": "ink", "shadow": "accent", "depth": 6},
         shape={"radius": 0, "border": 6, "bc": "ink", "shadow": "hard", "sc": "ink", "offset": 9, "fill": "paper", "tilt": 0.8},
         decor=[{"kind": "speed", "n": 30, "color": "ink", "rate": 10}],
         tex=[{"kind": "grain", "opacity": 0.1}],
         motion={"enter": "slam"}, trans=("wipe-diag", 10),
         about="خطِ سیاهِ ضخیم، نقطه‌چینِ چاپی و خط‌های تمرکز با یک لکهٔ قرمز؛ حسِ یک صفحهٔ مانگا.",
         fits="معرفیِ محصولِ جوان‌پسند، حراجِ «فقط امروز»، کتاب و سرگرمی.", tags=("مانگا", "سیاه‌وسفید", "پرانرژی")),

    dict(id="die-cut-sticker", src="die_cut_sticker", fa="برچسبِ برش‌خورده", en="Die-cut Sticker", group="cartoon",
         pal={"accent": "#e5457d", "accent2": "#4d96ff", "accent3": "#ffd93d"},  # InstAI's three sticker colours in the order pink, blue, yellow (the derived order made the yellow a muddy mustard)
         font={"latin": "bungee", "fa": "baloo-bhaijaan-2", "weight": 800, "track": 0.01, "lh": 1.2},
         bg={"kind": "dots", "base": "bg", "dot": "bg2", "size": 52, "r": 7, "drift": 8},
         text={"fx": "sticker", "color": "ink", "sticker": "paper"},
         shape={"radius": 30, "border": 8, "bc": "paper", "shadow": "float", "fill": "paper", "tilt": 2, "badge": "accent"},
         decor=[{"kind": "shapes", "n": 12, "kinds": ["circle", "half", "tri", "cross", "ring"], "colors": ["accent", "accent2", "accent3"], "outline": True, "size": 0.9, "spin": 16, "avoid": True},
                {"kind": "sparkles", "n": 6, "colors": ["accent", "paper"]}],
         tex=[{"kind": "grain", "opacity": 0.05}],
         motion={"enter": "pop", "wobble": 3}, trans=("flip", 14),
         about="برچسب‌هایِ رنگیِ لبه‌سفید که روی صفحه می‌چسبند و کمی تکان می‌خورند؛ شاد و قابلِ اشتراک.",
         fits="محصولِ کادویی و جوان‌پسند، لوازم‌التحریر، مناسبت‌هایِ فروش و قرعه‌کشی.", tags=("برچسب", "شاد", "جوان")),

    dict(id="kawaii-pastel", src="kawaii_pastel", fa="کاوایی پاستلی", en="Kawaii Pastel", group="cartoon",
         pal={"accent": "#e0467c"},  # the derived pink was too pale for the price tag: a deeper pink of the same hue
         font={"latin": "londrina-solid", "fa": "baloo-bhaijaan-2", "weight": 900, "track": 0.01},
         bg={"kind": "dots", "base": "bg", "dot": "accent2", "size": 46, "r": 8, "drift": 6},
         text={"fx": "hard", "color": "ink", "shadow": "accent2", "depth": 5},
         shape={"radius": 40, "border": 5, "bc": "accent", "shadow": "hard", "sc": "accent2", "offset": 6, "fill": "paper", "tilt": -1, "badge": "accent"},
         decor=[{"kind": "kawaii", "n": 14, "colors": ["accent", "accent2", "accent3", "paper"]}],
         tex=[{"kind": "grain", "opacity": 0.04}],
         motion={"enter": "swing"}, trans=("flip", 14),
         about="نقطه‌هایِ صورتی، قلب و ستاره و ابرِ خندان که آرام بالا می‌روند؛ نرم و بامزه.",
         fits="لوازم‌التحریر و اکسسوری، شیرینی و دسر، محصولاتِ دخترانه.", tags=("بامزه", "پاستلی", "دخترانه")),

    dict(id="crayon-doodle", src="kids_crayon_doodle", fa="نقاشیِ شمعیِ کودکانه", en="Kids' Crayon Doodle", group="cartoon",
         pal={"accent": "#0a5fa8"},  # the derived blue measured 3.5 on the paper texture (9:16 floor 3.6): a deeper blue of the same hue
         font={"latin": "chelsea-market", "fa": "harmattan", "weight": 700, "lh": 1.35},   # Persian font: not lemonada (its غ reads as ف: «چفر» in the real render)
         bg={"kind": "paper", "base": "bg", "fiber": 0.35},
         text={"fx": "hand", "color": "ink"},
         shape={"radius": 16, "border": 5, "bc": "accent", "dash": True, "shadow": "none", "fill": "paper", "filter": "url(#nm-rough)"},
         decor=[{"kind": "doodles", "color": "accent2", "sw": 9, "arrow": True}, {"kind": "confetti", "n": 12, "colors": ["accent", "accent2", "accent3"], "size": 1.1, "speed": 0.4}],
         tex=[{"kind": "paper", "opacity": 0.3}, {"kind": "grain", "opacity": 0.1}],
         motion={"enter": "pop"}, trans=("wipe", 12),
         about="خطِ شمعیِ نامرتب، دایره و فِلِش‌هایِ دست‌کشیده روی کاغذ؛ ساده و صمیمی.",
         fits="محصولِ کودک، لوازم‌التحریر، مهدکودک و کلاس‌هایِ هنری.", tags=("کودک", "شمعی", "شاد")),

    dict(id="rubber-hose-1930s", src="retro_rubberhose", fa="کارتونِ قدیمیِ دههٔ سی", en="1930s Rubber-hose Cartoon", group="cartoon",
         pal={"accent": "#7d2e24"},  # the derived brick red measured 2.9 on the dark ray stripes (+ grain, scratches, vignette): a deeper brick red of the same hue
         font={"latin": "luckiest-guy", "fa": "lalezar", "weight": 400, "track": 0.02},
         bg={"kind": "rays", "a": "bg", "b": "bg2", "n": 16, "speed": 4, "cy": 52},
         text={"fx": "hard", "color": "ink", "shadow": "accent2", "depth": 7},
         shape={"radius": 40, "border": 6, "bc": "ink", "shadow": "hard", "sc": "ink", "offset": 8, "fill": "paper", "tilt": 1.2},
         decor=[{"kind": "bubbles", "n": 6, "color": "paper"}],
         tex=[{"kind": "scratches", "opacity": 0.3}, {"kind": "grain", "opacity": 0.2}, {"kind": "flicker", "opacity": 0.1}, {"kind": "vignette", "opacity": 0.4}],
         motion={"stepFps": 12}, trans=("iris", 16),  # 1930s cartoons were drawn "on twos": 12 poses a second (InstAI's table keeps rubber hose smooth)
         about="پرتوهایِ پس‌زمینه، خراش و دانهٔ نوار و جهشِ کش‌دارِ حروف؛ حالوهوایِ کارتون‌هایِ اولِ سینما.",
         fits="نانوایی و بستنی‌فروشی، برندِ خانوادگی و قدیمی.", tags=("کارتونِ قدیمی", "رترو", "شوخ")),

    # ───────────────────────────────────────────── painted (the new group: paintings and hand prints)
    dict(id="oil-impressionist", src="impressionist_oil", fa="رنگ‌روغنِ امپرسیونیستی", en="Impressionist Oil", group="painted",
         font={"latin": "dm-serif-display", "fa": "amiri", "weight": 700, "lh": 1.3},
         bg={"kind": "hills", "sky": ["bg", "bg2"], "colors": ["bg2", "accent"], "layers": 3, "amp": 0.05, "spread": 0.3, "horizon": 0.6, "parallax": 0.8, "speed": 3,
             "sun": True, "sunColor": "accent3", "sunY": 0.22},
         text={"fx": "emboss", "color": "ink"},
         shape={"radius": 22, "border": 0, "shadow": "soft", "fill": "rgba(255,255,255,0.8)"},
         decor=[{"kind": "dust", "n": 26}, {"kind": "petals", "n": 9, "colors": ["accent", "paper"]}],
         tex=[{"kind": "paper", "opacity": 0.3}, {"kind": "grain", "opacity": 0.06}, {"kind": "bloom", "color": "paper", "opacity": 0.12}],
         motion={"enter": "bloom"}, trans=("fade", 26),
         about="لکه‌هایِ رنگِ ضخیمِ روغنی روی منظره‌ای نرم؛ نور و رنگ مهم‌تر از جزئیات است.",
         fits="هنر و دکور، گل و گیاه، کافه و رستوران، کالایِ دست‌ساز.", tags=("نقاشی", "رنگ‌روغن", "نرم")),

    dict(id="gouache-storybook", src="gouache_storybook", fa="گواشِ کتابِ کودک", en="Gouache Picture Book", group="painted",
         pal={"accent": "#14594f"},  # the teal layer sits right behind the kicker: measured 3.0 (9:16 floor 3.6) with the first veil; a deeper teal and a stronger veil
         font={"latin": "patrick-hand", "fa": "baloo-bhaijaan-2", "weight": 700, "lh": 1.3},
         bg={"kind": "layers", "base": "bg", "colors": ["accent2", "accent", "accent3", "bg2"], "n": 4, "veil": 0.86, "veilColor": "bg"},  # a stronger veil: the accent-coloured layer sat right behind the kicker (contrast 1.5 in the real render)
         text={"fx": "marker", "color": "ink", "hi": "accent3"},
         shape={"radius": 30, "border": 0, "shadow": "float", "fill": "paper"},
         decor=[{"kind": "blobs", "n": 4, "colors": ["accent", "accent2", "accent3"], "op": 0.3, "size": 1}, {"kind": "birds", "n": 3, "color": "ink"}],
         tex=[{"kind": "paper", "opacity": 0.3}, {"kind": "grain", "opacity": 0.06}],
         motion={"enter": "float"}, trans=("curtain", 22),
         about="شکل‌هایِ مات و ساده با رنگ‌هایِ گرم و لایه‌لایه، مثلِ تصویرِ یک کتابِ کودک.",
         fits="اسباب‌بازی و کتابِ کودک، لباسِ بچه، شیرینی و نانوایی.", tags=("کودک", "گرم", "داستانی")),

    dict(id="art-nouveau", src="art_nouveau_botanical", fa="آرنوو گیاهی", en="Art Nouveau Botanical", group="painted",
         font={"latin": "abril-fatface", "fa": "amiri", "weight": 700, "lh": 1.3},
         bg={"kind": "ornament", "mode": "vine", "base": "bg", "line": "accent3", "a": "accent2", "b": "accent", "sway": 0.35, "veil": 0.5, "veilColor": "bg"},
         text={"fx": "plain", "color": "ink"},
         shape={"radius": 26, "border": 4, "bc": "accent3", "shadow": "soft", "fill": "paper", "extra": "corner"},
         decor=[{"kind": "petals", "n": 8, "colors": ["accent", "paper"]}],
         tex=[{"kind": "paper", "opacity": 0.25}, {"kind": "grain", "opacity": 0.05}, {"kind": "vignette", "opacity": 0.2}],
         motion={"enter": "grow"}, trans=("iris", 22),
         about="ساقه و برگ و گلِ پیچان در دو لبهٔ قاب با رنگ‌هایِ خاکی و طلایی؛ ظریف و پُرکار.",
         fits="لوازمِ آرایشی و بهداشتی، عطر و گل‌فروشی، جواهر و صنایع‌دستی.", tags=("گل‌وگیاه", "ظریف", "تزئینی")),

    dict(id="linocut-print", src="linocut_print", fa="چاپِ لینولئوم", en="Linocut Print", group="painted",
         pal={"accent": "#7a1a1d"},  # the derived crimson measured 3.4 on the stripes (9:16 floor 3.6): a deeper crimson of the same hue
         font={"latin": "black-ops-one", "fa": "kufam", "weight": 900, "track": 0.02},
         bg={"kind": "stripes", "a": "bg", "b": "bg2", "w": 14, "angle": 78, "move": 0},
         text={"fx": "hard", "color": "ink", "shadow": "accent", "depth": 5},
         shape={"radius": 2, "border": 6, "bc": "ink", "shadow": "hard", "sc": "accent", "offset": 7, "fill": "paper", "tilt": 0.5},
         decor=[{"kind": "frame", "mode": "double", "color": "ink"}],
         tex=[{"kind": "grain", "opacity": 0.16}, {"kind": "crosshatch", "color": "ink", "opacity": 0.05}, {"kind": "paper", "opacity": 0.2}],
         motion={"enter": "stamp", "wobble": 2}, trans=("wipe", 12),
         about="کاغذِ کاهی، جوهرِ سیاه با یک لکهٔ قرمز و نارنجی و خط‌هایِ حکاکی؛ لبه‌هایِ زبرِ چاپِ دستی.",
         fits="محصولِ دست‌ساز و ارگانیک، قهوه و چای، بسته‌بندیِ سنتی.", tags=("چاپ", "دست‌ساز", "اصیل")),

    dict(id="woodblock-waves", src="ukiyoe_woodblock", fa="چاپِ چوبیِ موج‌دار", en="Woodblock Wave Print", group="painted",
         font={"latin": "rock-salt", "fa": "katibeh", "weight": 400},   # not rakkas (its چ loses its dots: «صغر» in the real render)
         bg={"kind": "waves", "base": "bg", "colors": ["accent2", "bg2"], "line": "ink", "size": 62, "op": 0.85, "speed": 14, "soft": 0.58, "veil": 0.55, "veilColor": "bg"},
         text={"fx": "ink", "color": "ink"},
         shape={"radius": 4, "border": 4, "bc": "ink", "shadow": "hard", "sc": "accent", "offset": 6, "fill": "paper", "extra": "band", "bandColor": "accent"},
         decor=[{"kind": "birds", "n": 4, "color": "ink"}],
         tex=[{"kind": "paper", "opacity": 0.3}, {"kind": "grain", "opacity": 0.1}, {"kind": "vignette", "opacity": 0.25}],
         motion={"enter": "wipe"}, trans=("wipe", 16),
         about="موج‌هایِ هم‌پوشان، جوهرِ سیاه، لاجوردی و قرمزِ مُهر روی کاغذِ کاهی؛ سبکِ چاپِ چوبیِ ژاپنی.",
         fits="رستورانِ دریایی و سوشی، چای و لوازمِ آشپزخانه، هنر و دکور.", tags=("چاپ چوبی", "موج", "ژاپنی")),

    dict(id="charcoal-sketch", src="charcoal_drawing", fa="طرحِ زغال", en="Charcoal Sketch", group="painted",
         pal={"accent": "#3d3c39"},  # the derived grey measured 3.4 on the paper texture: a darker charcoal
         font={"latin": "special-elite", "fa": "markazi-text", "weight": 700, "lh": 1.3},
         bg={"kind": "paper", "base": "bg", "fiber": 0.65, "edge": 0.1},
         text={"fx": "ink", "color": "ink"},
         shape={"radius": 4, "border": 3, "bc": "ink", "dash": True, "shadow": "none", "fill": "paper", "filter": "url(#nm-rough)"},
         decor=[{"kind": "smoke", "n": 5, "color": "ink", "op": 0.1}, {"kind": "doodles", "color": "ink", "sw": 5, "op": 0.5}],
         tex=[{"kind": "crosshatch", "color": "ink", "opacity": 0.07}, {"kind": "grain", "opacity": 0.14}, {"kind": "vignette", "opacity": 0.3}],
         motion={"enter": "bloom"}, trans=("fade", 24),
         about="خطِ زغالیِ تیره روی کاغذِ زبر با لکه و دودگرفتگی؛ دراماتیک و خام.",
         fits="هنر و گالری، آموزشِ طراحی، لوازم‌التحریر و دکور.", tags=("زغال", "طراحی", "دراماتیک")),

    dict(id="sumi-ink-wash", src="ink_wash_sumi", fa="آب‌مرکبِ شرقی", en="Ink Wash (Sumi)", group="painted",
         pal={"accent": "#7a1313"},  # the seal red measured 2.9 on the grey ink washes: a deeper seal red
         font={"latin": "major-mono-display", "fa": "markazi-text", "weight": 700, "lh": 1.35},
         bg={"kind": "wash", "base": "bg", "colors": ["ink", "muted", "accent"], "n": 5, "op": 0.2},
         text={"fx": "ink", "color": "ink"},
         shape={"radius": 14, "border": 0, "shadow": "soft", "fill": "rgba(255,255,255,0.7)"},
         decor=[{"kind": "smoke", "n": 4, "color": "ink", "op": 0.08}, {"kind": "birds", "n": 3, "color": "ink"}],
         tex=[{"kind": "paper", "opacity": 0.35}, {"kind": "grain", "opacity": 0.08}, {"kind": "vignette", "opacity": 0.18}],
         motion={"enter": "wipe"}, trans=("fade", 28),
         about="لکه‌هایِ مرکبِ رقیق روی کاغذِ برنج و یک مُهرِ قرمز؛ آرام و خلوت.",
         fits="چای و دمنوش، سلامت و یوگا، فروشگاهِ آرامش‌بخش.", tags=("مرکب", "آرام", "شرقی")),

    dict(id="calligraphy-ink", src="calligraphy_ink_art", fa="خوشنویسیِ جوهری", en="Calligraphic Ink", group="painted",
         font={"latin": "cinzel", "fa": "katibeh", "weight": 700, "lh": 1.4},
         bg={"kind": "parchment", "base": "bg"},
         text={"fx": "hard", "color": "ink", "shadow": "accent", "depth": 4},
         shape={"radius": 8, "border": 3, "bc": "accent3", "shadow": "soft", "fill": "paper", "extra": "corner"},
         decor=[{"kind": "frame", "mode": "double", "color": "accent3"}, {"kind": "dust", "n": 22}],
         tex=[{"kind": "paper", "opacity": 0.25}, {"kind": "grain", "opacity": 0.06}, {"kind": "vignette", "opacity": 0.3}],
         motion={"enter": "unfold"}, trans=("curtain", 24),
         about="کاغذِ آهارمُهره‌نما، مرکبِ سیاه با سایهٔ قرمز و قابِ طلایی؛ باشکوه و فارسی.",
         fits="کتاب و لوازم‌التحریر، هدیه‌هایِ فرهنگی، تبریک‌ها.", tags=("خوشنویسی", "فارسی", "باشکوه")),

    dict(id="dark-fantasy-art", src="dark_fantasy_painting", fa="نقاشیِ فانتزیِ تاریک", en="Dark Fantasy Painting", group="painted",
         font={"latin": "cinzel", "fa": "amiri", "weight": 700, "track": 0.04},   # aref-ruqaa under a glow turned «چغر» into a smear in the real render
         bg={"kind": "nightsky", "from": "bg", "to": "bg2", "stars": 60, "castle": True, "moon": True, "bld": "#05060a", "win": "accent"},
         text={"fx": "softglow", "color": "ink", "glow": "accent"},
         shape={"radius": 6, "border": 2, "bc": "muted", "shadow": "glow", "sc": "accent", "fill": "bg2"},
         decor=[{"kind": "smoke", "n": 6, "color": "paper", "op": 0.1}, {"kind": "dust", "n": 40}],
         tex=[{"kind": "vignette", "opacity": 0.55}, {"kind": "grain", "opacity": 0.12, "blend": "overlay", "rgb": [255, 255, 255]}, {"kind": "flicker", "opacity": 0.05}],
         motion={"enter": "blur"}, trans=("dip", 26),
         about="قصرِ سیاه‌نما زیرِ ماه، مه و جرقه‌هایِ کهربایی؛ تیره و سنگین.",
         fits="بازی و سرگرمی، کتاب و رمان، کافه‌هایِ موضوعی.", tags=("تاریک", "فانتزی", "بازی")),

    dict(id="pulp-scifi", src="retro_pulp_scifi", fa="پالپِ علمی‌تخیلی", en="Retro Pulp Sci-fi", group="painted",
         pal={"accent": "#154a60"},  # the derived teal measured 3.0 on the orange burst behind the kicker: a deeper teal
         font={"latin": "bowlby-one", "fa": "kufam", "weight": 900, "track": 0.01},
         bg={"kind": "halftone", "base": "bg", "dot": "accent2", "size": 30, "angle": 150, "maskA": 0.9, "maskB": 0.08},
         text={"fx": "hard", "color": "ink", "shadow": "accent", "depth": 8},
         shape={"radius": 6, "border": 5, "bc": "ink", "shadow": "hard", "sc": "accent2", "offset": 8, "fill": "paper", "tilt": -1.2},
         decor=[{"kind": "burst", "color": "accent3", "stroke": "ink", "spikes": 14, "r": 0.5, "cy": 0.5, "spin": 0.05}],
         tex=[{"kind": "halftone", "color": "ink", "size": 16, "opacity": 0.07}, {"kind": "grain", "opacity": 0.12}, {"kind": "paper", "opacity": 0.2}],
         motion={"enter": "swing"}, trans=("wipe-diag", 12),
         about="نقطه‌هایِ چاپی، انفجارِ زرد و رنگ‌هایِ داغِ جلدِ مجله‌هایِ قدیمی.",
         fits="کتاب و مجله، بازی و سرگرمی، حراجِ ویژه.", tags=("رترو", "علمی‌تخیلی", "جلد")),

    dict(id="persian-miniature", src="persian_miniature", fa="مینیاتورِ ایرانی", en="Persian Miniature Painting", group="painted",
         font={"latin": "amiri", "fa": "aref-ruqaa", "weight": 700, "lh": 1.4},
         bg={"kind": "ornament", "mode": "frame", "base": "bg", "line": "accent3", "a": "accent2", "b": "accent3", "veil": 0.55, "veilColor": "bg"},
         text={"fx": "plain", "color": "ink"},
         shape={"radius": 4, "border": 3, "bc": "accent3", "shadow": "soft", "fill": "paper", "extra": "corner"},
         decor=[{"kind": "dust", "n": 18}],
         tex=[{"kind": "paper", "opacity": 0.25}, {"kind": "grain", "opacity": 0.06}, {"kind": "vignette", "opacity": 0.3}],
         motion={"enter": "unfold", "stepFps": None, "wobble": 0}, trans=("curtain", 22),  # ornate pages glide: InstAI's "cutout" steps on eights, kept smooth here
         about="صفحهٔ تذهیب‌شده با لاجورد و زر و ترنجِ گوشه‌ها؛ زبانِ نگارگریِ ایرانی.",
         fits="شیرینی و سوغات، صنایع‌دستی، کتاب و هدیه‌هایِ ایرانی.", tags=("ایرانی", "تذهیب", "سنتی")),

    dict(id="surreal-dream", src="surreal_dream_collage", fa="رؤیایِ سورئال", en="Surreal Dreamscape", group="painted",
         font={"latin": "unbounded", "fa": "kufam", "weight": 900, "lh": 1.3},
         bg={"kind": "clouds", "sky": ["bg2", "bg"], "cloud": "paper", "shadow": "accent2", "n": 7, "band": 0.7, "speed": 1.2},
         text={"fx": "plain", "color": "ink"},
         shape={"radius": 40, "border": 0, "shadow": "float", "fill": "rgba(255,255,255,0.82)"},
         decor=[{"kind": "orbs", "mode": "clay", "n": 4, "colors": ["accent", "accent2", "accent3"], "size": 0.9},
                {"kind": "shapes", "n": 6, "kinds": ["ring", "half", "tri"], "colors": ["accent", "accent3"], "outline": True, "size": 1.0, "spin": 6, "avoid": True}],
         tex=[{"kind": "grain", "opacity": 0.06, "blend": "overlay"}, {"kind": "bloom", "color": "paper", "opacity": 0.14}],
         motion={"enter": "float"}, trans=("fade", 24),
         about="آسمانِ هلویی با ابرِ شناور، کره‌هایِ خمیری و هندسهٔ معلق؛ فضایِ خیال.",
         fits="محصولِ خلاقانه و هنری، عطر و خواب، تبلیغِ مفهومی.", tags=("خیال", "سورئال", "هنری")),

    # ───────────────────────────────────────────── graphic
    dict(id="travel-poster", src="vintage_travel_poster", fa="پوسترِ سفرِ قدیمی", en="Vintage Travel Poster", group="graphic",
         pal={"accent": "#00525f"},  # the derived teal measured 3.2 for the kicker on the sunburst rays (9:16 floor 3.6): a deeper teal of the same hue
         font={"latin": "bebas-neue", "fa": "kufam", "weight": 900, "case": "upper", "track": 0.04, "lh": 1.15},
         bg={"kind": "rays", "a": "bg", "b": "bg2", "n": 14, "speed": 3, "cy": 62},
         text={"fx": "hard", "color": "ink", "shadow": "accent2", "depth": 6},
         shape={"radius": 6, "border": 5, "bc": "ink", "shadow": "hard", "sc": "accent", "offset": 8, "fill": "paper", "extra": "band", "bandColor": "accent2"},
         decor=[{"kind": "frame", "mode": "double", "color": "ink"}, {"kind": "birds", "n": 4, "color": "ink"}],
         tex=[{"kind": "grain", "opacity": 0.14}, {"kind": "paper", "opacity": 0.2}, {"kind": "vignette", "opacity": 0.2}],
         motion={"enter": "drop", "spring": [20, 150, 1.0], "stagger": 6}, trans=("slide", 18),     # a poster slams down: InstAI's painted-parallax spring settled too slowly for the drop
         about="پرتوهایِ خورشید، قابِ پوستر و حروفِ فشرده با رنگ‌هایِ گرمِ پوسترهایِ مسافرتیِ قدیمی.",
         fits="آژانسِ مسافرتی، اقامتگاه و کافه، محصولِ سوغاتی و فصلی.", tags=("پوستر", "سفر", "نوستالژی")),

    dict(id="duotone-gradient", src="duotone_gradient", fa="دوتونِ گرادیانی", en="Duotone Gradient", group="graphic",
         font={"latin": "syncopate", "fa": "kufam", "weight": 700, "case": "upper", "track": 0.1},
         bg={"kind": "linear", "from": "bg", "mid": "bg2", "to": "accent3", "angle": 200, "drift": 10, "flip": True},
         text={"fx": "plain", "color": "ink"},
         shape={"radius": 24, "border": 1, "bc": "rgba(255,255,255,0.3)", "shadow": "soft", "fill": "glass"},
         decor=[{"kind": "shapes", "n": 6, "kinds": ["ring", "half"], "colors": ["accent", "accent2"], "outline": True, "size": 1.3, "spin": 4, "avoid": True}, {"kind": "shine", "speed": 0.2}],
         tex=[{"kind": "grain", "opacity": 0.06, "blend": "screen", "rgb": [255, 255, 255]}, {"kind": "vignette", "opacity": 0.3}],
         motion={"enter": "slide"}, trans=("push", 14),
         about="دو رنگِ همسایه از تیره تا روشن، بدونِ شلوغی؛ مدرن و تمیز.",
         fits="اپلیکیشن و خدماتِ آنلاین، برندِ مینیمال، معرفیِ ویژگی‌ها.", tags=("مدرن", "دورنگ", "مینیمال")),

    dict(id="constructivist-poster", src="constructivist_poster", fa="پوسترِ ساختن‌گرا", en="Constructivist Poster", group="graphic",
         pal={"accent": "#9c1a20", "accent2": "#1a1a1a", "accent3": "#8d8d8d"},  # red first (the derived order picked the black: the poster needs its red wedge); a deeper red: the kicker measured 3.5 (9:16 floor 3.6)
         font={"latin": "rubik-mono-one", "fa": "kufam", "weight": 900, "case": "upper", "lh": 1.1},
         bg={"kind": "stripes", "a": "bg", "b": "bg2", "w": 150, "angle": -35, "move": 20},
         bg2={"kind": "solid", "c": "#ee4b43"},  # the red scene: a vermilion the black text reads on (4.8:1); the first try, the deep accent with a `pal` flip to cream text, never took effect: the engine does not read a `pal` of a background spec, so the list title was black on deep red (measured 2.9)
         text={"fx": "hard", "color": "ink", "shadow": "accent", "depth": 7},
         shape={"radius": 0, "border": 6, "bc": "ink", "shadow": "hard", "sc": "accent", "offset": 9, "fill": "paper", "tilt": -1.5},
         decor=[{"kind": "shapes", "n": 6, "kinds": ["tri", "circle", "ring"], "colors": ["accent", "accent3"], "size": 1.5, "spin": 3, "avoid": True},
                {"kind": "speed", "mode": "h", "n": 12, "color": "ink", "rate": 8}],
         tex=[{"kind": "grain", "opacity": 0.12}, {"kind": "halftone", "color": "ink", "size": 14, "opacity": 0.05}],
         motion={"enter": "slide"}, trans=("wipe-diag", 12),
         about="مورب‌هایِ تند، قرمز و سیاه و کرم و حروفِ سنگین؛ حسِ یک پوسترِ اعلامیه‌ای.",
         fits="اعلامِ حراج و قرعه‌کشی، رویداد و کارگاه، پیامِ فوری.", tags=("پوستر", "مورب", "فوری")),

    dict(id="midcentury-modern", src="midcentury_modern_2d", fa="مدرنِ نیمهٔ قرن", en="Mid-century Modern", group="graphic",
         font={"latin": "righteous", "fa": "lalezar", "weight": 400, "track": 0.01},
         bg={"kind": "solid", "c": "bg", "alt": "bg2"},
         text={"fx": "plain", "color": "ink"},
         shape={"radius": 18, "border": 0, "shadow": "float", "fill": "paper", "extra": "band", "bandColor": "accent"},
         decor=[{"kind": "shapes", "n": 11, "kinds": ["half", "circle", "tri", "ring", "cross"], "colors": ["accent", "accent2", "accent3"], "size": 1.2, "spin": 5, "avoid": True}],
         tex=[{"kind": "grain", "opacity": 0.1}, {"kind": "paper", "opacity": 0.15}],
         motion={"enter": "swing"}, trans=("push", 14),
         about="هندسهٔ ساده، فیروزه‌ای و نارنجی و خردلی روی کرم؛ حسِ طراحیِ دهه‌هایِ ۵۰ و ۶۰ میلادی.",
         fits="مبلمان و دکور، لوازمِ خانگی، برندِ طراحی‌محور.", tags=("رترو", "هندسی", "دکور")),

    # ───────────────────────────────────────────── digital
    dict(id="y2k-bubble", src="y2k_bubble_chrome", fa="حبابِ ایک‌دو‌کی", en="Y2K Bubble Gloss", group="digital",
         font={"latin": "audiowide", "fa": "baloo-bhaijaan-2", "weight": 800, "track": 0.02},
         bg={"kind": "clouds", "sky": ["bg2", "bg"], "cloud": "paper", "shadow": "accent2", "n": 7, "band": 0.6, "speed": 1.6},
         text={"fx": "extrude", "color": "ink", "shadow": "accent", "depth": 8},        # chrome type was silver on a light sky (unreadable in the sample sheet): a navy face with a bright-blue 3D side
         shape={"radius": 36, "border": 3, "bc": "paper", "shadow": "float", "fill": "paper"},
         decor=[{"kind": "bubbles", "n": 14, "color": "paper"}, {"kind": "sparkles", "n": 10, "glow": True, "colors": ["accent", "paper"]}],
         tex=[{"kind": "bloom", "color": "paper", "opacity": 0.2}, {"kind": "grain", "opacity": 0.03}],
         motion={"enter": "pop"}, trans=("flash", 12),
         about="آسمانِ آبیِ روشن، حباب و ستاره و حروفِ سه‌بعدیِ براق؛ خوش‌بینیِ سال‌هایِ ۲۰۰۰.",
         fits="لوازمِ دیجیتال و موبایل، مد و اکسسوری، فروشِ جوان‌پسند.", tags=("براق", "حباب", "نوستالژی")),

    dict(id="holo-foil", src="holographic_foil", fa="فویلِ هولوگرافیک", en="Holographic Foil", group="digital",
         font={"latin": "russo-one", "fa": "kufam", "weight": 700, "track": 0.02},
         bg={"kind": "holo", "base": "bg", "stops": ["accent", "accent2", "accent3", "paper"], "angle": 115, "sparkles": 16, "op": 0.5},
         text={"fx": "emboss", "color": "ink"},
         shape={"radius": 26, "border": 2, "bc": "paper", "shadow": "glow", "sc": "accent", "fill": "paper"},
         decor=[{"kind": "sparkles", "n": 8, "glow": True, "colors": ["paper", "accent"]}],
         tex=[{"kind": "bloom", "color": "paper", "opacity": 0.18}, {"kind": "grain", "opacity": 0.04, "blend": "screen", "rgb": [255, 255, 255]}],
         motion={"enter": "lightup"}, trans=("flash", 12),
         about="فویلِ لغزانِ صورتی و فیروزه‌ای با جرقه و درخششِ عبوری؛ رؤیایی و براق.",
         fits="لوازمِ آرایشی، کاورِ موبایل، اکسسوری و کادو.", tags=("هولوگرام", "براق", "رؤیایی")),

    # ───────────────────────────────────────────── craft
    dict(id="embroidery-knit", src="embroidery_textile", fa="گلدوزی و بافتنی", en="Embroidery & Knit", group="craft",
         font={"latin": "comic-neue", "fa": "mada", "weight": 900, "lh": 1.35},   # not lemonada (غ reads as ف)
         bg={"kind": "cloth", "base": "bg", "thread": "accent", "thread2": "accent2", "thread3": "accent3", "weave": 9, "size": 18, "band": 0.085},
         text={"fx": "felt", "color": "ink"},
         shape={"radius": 18, "border": 4, "bc": "accent", "dash": True, "shadow": "soft", "fill": "paper"},
         decor=[{"kind": "shapes", "n": 10, "kinds": ["cross", "dots"], "colors": ["accent", "accent2", "accent3"], "size": 0.8, "spin": 0, "avoid": True}],
         tex=[{"kind": "stitch", "color": "accent"}, {"kind": "grain", "opacity": 0.08}],
         motion={"enter": "swing"}, trans=("slide", 12),
         about="پارچهٔ بافت‌دار با نوارِ دوخت‌ضربدری و درزِ خط‌چین و حرکتِ پله‌ایِ ۸ فریم‌بر‌ثانیه.",
         fits="پوشاک و پارچه، صنایع‌دستی، هدیه‌هایِ دست‌ساز و نوروزی.", tags=("گلدوزی", "پارچه", "دست‌ساز")),

    dict(id="mosaic-tiles", src="mosaic_tiles", fa="موزاییک و کاشی", en="Mosaic Tiles", group="craft",
         font={"latin": "cairo", "fa": "reem-kufi", "weight": 900, "lh": 1.25},
         bg={"kind": "mosaic", "base": "bg", "grout": "ink", "colors": ["accent", "accent2", "accent3", "bg2"], "size": 70, "gap": 5, "soft": 0.5, "tilt": 3, "veil": 0.78, "veilColor": "bg"},
         text={"fx": "plain", "color": "ink"},
         shape={"radius": 8, "border": 5, "bc": "ink", "shadow": "soft", "fill": "paper"},
         decor=[{"kind": "frame", "mode": "double", "color": "accent3"}],
         tex=[{"kind": "vignette", "opacity": 0.3}, {"kind": "grain", "opacity": 0.05}],
         motion={"enter": "build", "stagger": 6}, trans=("blocks", 14),
         about="تکه‌هایِ رنگیِ بندکشی‌شده با برقِ آرامِ نور؛ پُرکار و ماندگار.",
         fits="کاشی و سرامیک، مبلمان و دکور، رستورانِ سنتی.", tags=("کاشی", "موزاییک", "سنتی")),

    dict(id="gothic-puppets", src="gothic_whimsy_puppet", fa="عروسکِ گوتیکِ شیطنت‌آمیز", en="Gothic Whimsy Puppets", group="craft",
         font={"latin": "fredericka-the-great", "fa": "markazi-text", "weight": 700, "lh": 1.3},   # aref-ruqaa in a 3-D puppet text was unreadable
         bg={"kind": "stripes", "a": "bg", "b": "bg2", "w": 46, "angle": -18, "move": 0},
         text={"fx": "hard", "color": "ink", "shadow": "accent", "depth": 5},
         shape={"radius": 10, "border": 4, "bc": "accent", "shadow": "hard", "sc": "bg", "offset": 7, "fill": "bg2", "tilt": 1},
         decor=[{"kind": "smoke", "n": 5, "color": "paper", "op": 0.12}, {"kind": "birds", "n": 4, "color": "paper"}],
         tex=[{"kind": "vignette", "opacity": 0.5}, {"kind": "grain", "opacity": 0.12}, {"kind": "flicker", "opacity": 0.06}],
         motion={"enter": "drop", "stagger": 6}, trans=("dip", 16),
         about="راه‌راهِ تیره، مه و خفاش با حرکتِ عروسکیِ ۱۲ فریم‌بر‌ثانیه؛ ترسناکِ بامزه.",
         fits="رویداد و مراسمِ شبانه، بازی و کتاب، کافه‌هایِ موضوعی.", tags=("گوتیک", "عروسکی", "شیطنت")),

    # ───────────────────────────────────────────── dimensional
    dict(id="tilt-shift", src="tilt_shift_miniature", fa="مینیاتورِ تیلت‌شیفت", en="Tilt-shift Miniature", group="dimensional",
         pal={"accent": "#e0522a"},  # the derived orange-red had too little contrast on the pale sky; same hue, a little deeper
         font={"latin": "fredoka", "fa": "baloo-bhaijaan-2", "weight": 700, "lh": 1.25},
         bg={"kind": "tiltshift", "sky": ["bg2", "bg"], "ground": "accent3", "colors": ["accent", "accent2", "accent3", "paper"], "n": 14, "band": 0.34, "blur": 11, "speed": 12, "veil": 0.5, "veilColor": "bg"},
         text={"fx": "sticker", "color": "ink", "sticker": "paper"},
         shape={"radius": 26, "border": 0, "shadow": "float", "fill": "paper"},
         decor=[{"kind": "dust", "n": 14}],
         tex=[{"kind": "vignette", "opacity": 0.2}],
         motion={"enter": "squash"}, trans=("fade", 20),
         about="شهرِ اسباب‌بازیِ رنگی که بالا و پایینش محو است؛ همه‌چیز کوچک و خواستنی به‌نظر می‌رسد.",
         fits="ملک و مجتمع، شهربازی و گردشگری، محصولِ خرد و کادویی.", tags=("اسباب‌بازی", "دیوراما", "شاد")),

    dict(id="vinyl-toy", src="vinyl_toy_figure", fa="فیگورِ وینیلی", en="Designer Vinyl Toy", group="dimensional",
         font={"latin": "changa", "fa": "changa", "weight": 800, "lh": 1.25},
         bg={"kind": "studio", "from": "paper", "to": "bg2", "horizon": 0.72},
         text={"fx": "clay", "color": "ink"},
         shape={"radius": 40, "shadow": "inner", "fill": "paper", "fillGradient": 160},
         decor=[{"kind": "orbs", "mode": "gloss", "n": 5, "colors": ["accent", "accent2", "accent3"]}],
         tex=[{"kind": "vignette", "opacity": 0.15}, {"kind": "grain", "opacity": 0.04}],
         motion={"enter": "squash", "spring": [10, 130, 0.85]}, trans=("zoom", 14),
         about="کره‌هایِ براق و پف‌کرده روی پس‌زمینهٔ استودیو با جهشِ لاستیکی؛ حسِ یک فیگورِ کلکسیونی.",
         fits="اسباب‌بازی و کلکسیون، هدیه و محصولِ کوچک، فروشِ جوان‌پسند.", tags=("اسباب‌بازی", "کلکسیونی", "براق")),

    # ───────────────────────────────────────────── cinematic
    dict(id="double-exposure", src="double_exposure", fa="نوردهیِ دوگانه", en="Double Exposure", group="cinematic",
         font={"latin": "playfair-display", "fa": "markazi-text", "weight": 700, "lh": 1.3},
         bg={"kind": "doubleexp", "base": "bg", "a": "accent2", "b": "accent3", "opA": 0.55, "opB": 0.5, "veil": 0.45, "veilColor": "bg"},
         text={"fx": "plain", "color": "ink"},
         shape={"radius": 4, "border": 1, "bc": "muted", "shadow": "soft", "fill": "paper"},
         decor=[{"kind": "dust", "n": 24}],
         tex=[{"kind": "grain", "opacity": 0.12, "blend": "overlay", "rgb": [255, 255, 255]}, {"kind": "vignette", "opacity": 0.35}],
         motion={"enter": "blur"}, trans=("dip", 24),
         about="دو تصویر در هم: تپه‌ها و خورشید و تنهٔ درخت‌ها با خط‌هایِ ظریف؛ شاعرانه و آرام.",
         fits="برندِ سبک‌زندگی، عطر و لوازمِ دکوری، تبلیغِ احساسی.", tags=("شاعرانه", "سینمایی", "آرام")),

    dict(id="home-movie-8mm", src="super8_home_movie", fa="فیلمِ خانگیِ ۸ میلی‌متری", en="8mm Home Movie", group="cinematic",
         font={"latin": "lobster", "fa": "jomhuria", "weight": 400, "lh": 1.3},   # not lemonada (غ reads as ف); a condensed title-card face
         bg={"kind": "radial", "from": "bg2", "to": "bg", "at": "50% 45%"},
         text={"fx": "retro", "color": "ink", "c2": "accent2", "c3": "accent3", "c4": "muted", "depth": 4},
         shape={"radius": 4, "border": 8, "bc": "paper", "shadow": "soft", "fill": "paper", "tilt": 1.2},
         decor=[{"kind": "frame", "mode": "film"}],
         tex=[{"kind": "grain", "opacity": 0.2, "blend": "overlay", "rgb": [255, 255, 255]}, {"kind": "scratches", "opacity": 0.3}, {"kind": "flicker", "opacity": 0.09}, {"kind": "vignette", "opacity": 0.45}],
         motion={"enter": "fade", "stepFps": 18}, trans=("dip", 22),  # 18 poses a second like an 8mm camera (InstAI's table keeps the live camera smooth)
         fx={"grade": "sepia(0.28) contrast(1.05) saturate(1.1)"},
         about="دانهٔ فیلم، خراشِ نوار، قابِ سفید و رنگِ گرمِ کهنه؛ خاطره‌ای و صمیمی.",
         fits="کافه و نانوایی، برندِ قدیمی و خانوادگی، تبلیغِ خاطره‌انگیز.", tags=("نوستالژی", "فیلم", "صمیمی")),
]
