"""SOURCE: ported from InstAI:instai/styles/aliases.py @ 2f8aa90, adapted for store advertising (NMarketing).
تغییر: فقط سربرگ. این فایل «فقط برای جست‌وجو» است؛ هرگز وارد دستور یا برچسبِ سبک نمی‌شود (آزمون).

Search-only names for the art/animation styles: what people TYPE to find a look ("ghibli", "lego", "ps2", "پیکسار" ...).

Why a separate file: the project rule is that no studio, franchise, brand, artist or creator name may appear in a style's name, description or prompt
(licence risk: the output must never be mistaken for a rights-holder's work; tests/test_styles.py scans the style data for such names). People still
search by those names, so the library matches them here and shows the generic look. Nothing in this file is ever sent to a model or shown as a label.
Terms are lower-case; a Persian and an English spelling are both useful. Words already in a style's own name or tags need not be repeated.
"""
from __future__ import annotations

ALIASES: dict[str, list[str]] = {
    # the owner's list, by the names he uses
    "pixel_art_16bit": ["pixel art", "8-bit", "16 bit", "retro game", "پیکسل آرت", "پیکسل", "بازی قدیمی"],
    "chalkboard_classroom": ["chalkboard", "chalk board", "blackboard", "تخته سیاه", "تخته گچی", "گچ"],
    "glow_sketch": ["glow sketch", "neon sketch", "light painting", "اسکچ نئون", "اسکچ درخشان"],
    "early_console_3d": ["ps2", "ps2 style", "playstation", "playstation 2", "ps1", "low poly game", "پی اس ۲", "پلی استیشن", "بازی قدیمی سه بعدی"],
    "comic_ink": ["comic art", "comics", "comic book", "کمیک", "کمیک آرت", "کمیک بوک"],
    "flat_vector_motion": ["flat vector", "vector", "flat design", "وکتور", "فلت"],
    "minimal_bw_essay": ["dan koe", "dankoe", "essay video", "minimalist", "black and white", "دن کو", "مینیمال", "سیاه سفید", "ویدیو مقاله"],
    "cgi_motion_graphics": ["cgi motion", "cgi", "3d motion graphics", "سی جی آی", "موشن سه بعدی"],
    "toy_brick_3d": ["lego", "lego style", "lego-like bricks", "bricks", "brick film", "لگو", "آجر اسباب بازی", "بلوک"],
    "fast_3d_explainer": ["zackd", "zack d", "zackd films", "zack d films", "3d explainer", "زک دی", "توضیح سه بعدی"],
    "modern_tv_anime": ["anime", "انیمه"],
    "painterly_pastoral": ["ghibli", "studio ghibli", "miyazaki style", "ژیبلی", "استودیو ژیبلی", "میازاکی"],
    "fairytale_feature_2d": ["disney", "disney style", "classic disney", "princess", "دیزنی", "پرنسس", "افسانه"],
    "cg_family_3d": ["pixar", "pixar style", "disney 3d", "dreamworks", "3d animation", "پیکسار", "دریم ورکس", "انیمیشن سه بعدی"],
    "bold_angular_tv_toon": ["cartoon network", "cn style", "adventure time", "کارتون نتورک", "کارتون شبکه"],
    "western_2d_tv": ["simpsons", "family guy", "tv cartoon", "سیمپسونز"],
    "watercolour_storybook": ["watercolor", "watercolour", "آبرنگ"],
    "cel_shading_render": ["cel shading", "cel-shading", "toon shader", "cell shading", "سلی شیدینگ", "سل شیدینگ"],
    "line_art_mono": ["line art", "lineart", "monoline", "لاین آرت", "خط"],
    "silhouette_cutout": ["silhouette", "shadow figure", "سیلوئت", "سایه نما", "سایه"],
    "claymation_stopmotion": ["claymation", "clay animation", "plasticine", "wallace", "کلی میشن", "خمیر بازی", "پلاستیسین"],
    "stop_motion_puppet": ["stop motion", "stopmotion", "puppet animation", "استاپ موشن"],
    "low_poly_3d": ["low poly", "lowpoly", "لو پلی", "کم چند ضلعی"],
    "voxel_art": ["voxel", "minecraft", "minecraft style", "blocky", "ووکسل", "ماین کرفت", "ماینکرفت"],
    "papercraft_layers": ["papercraft", "paper craft", "shadow box", "کاردستی کاغذی", "پیپر کرفت"],
    "origami_fold": ["origami", "paper folding", "اوریگامی", "کاغذ تا شده"],
    "isometric_diorama": ["isometric", "iso", "diorama", "ایزومتریک", "دیوراما"],
    "photoreal_cgi": ["photorealistic cgi", "photoreal", "vfx", "hyperreal", "سی جی آی واقعی", "فوق واقعی"],
    "layered_parallax_25d": ["2.5d", "2.5d parallax", "parallax", "depth layers", "پارالاکس", "دو و نیم بعدی", "۲٫۵ بعدی"],
    "vaporwave_synth": ["synthwave", "outrun", "retrowave", "80s neon", "سینت ویو", "سینث ویو"],
    "noir_bw": ["film noir", "noir", "نوآر", "فیلم نوآر"],
    "cyberpunk_neon": ["cyberpunk", "blade runner", "سایبرپانک"],
    "steampunk_brass": ["steampunk", "استیم پانک"],
    "pop_art_halftone": ["pop art", "warhol", "lichtenstein", "پاپ آرت"],
    "stained_glass": ["stained glass", "vitrail", "ویتراژ", "شیشه رنگی"],
    "graffiti_street": ["graffiti", "street art", "spray paint", "گرافیتی", "اسپری"],
    "blueprint_technical": ["blueprint", "technical drawing", "schematic", "بلوپرینت", "نقشه فنی"],
    "glitch_datamosh": ["glitch", "glitch art", "datamosh", "گلیچ"],
    "whiteboard_explainer": ["whiteboard", "doodle video", "white board", "وایت برد", "تخته سفید"],
    "kinetic_typography": ["kinetic type", "text animation", "lyric video", "typography", "تایپوگرافی", "تایپوگرافی متحرک", "متن متحرک"],
    "infographic_data": ["infographic", "chart", "data viz", "اینفوگرافیک", "نمودار"],
    "corporate_flat_people": ["corporate memphis", "alegria", "flat people", "corporate flat", "ممفیس شرکتی"],
    "stickman_doodle": ["stickman", "stick figure", "stick man", "استیک من", "آدم چوبی"],
    "flat_2d_character": ["flat 2d", "2d flat", "flat character", "دوبعدی تخت"],
    "clay_3d_render": ["3d claymation", "clay render", "claymation 3d", "کلی میشن سه بعدی"],
    "glassmorphism_ui": ["glassmorphism", "glass ui", "frosted glass", "گلس مورفیسم", "شیشه مات"],
    "chrome_metal_type": ["chrome 22k", "chrome", "liquid metal", "metallic type", "کروم", "فلز مایع"],
    "cineview_widescreen": ["cineview", "cinematic", "anamorphic", "teal orange", "سینه ویو", "سینمایی"],
    "risograph_print": ["risograph", "riso", "ریزوگراف"],
    "paper_collage": ["paper collage", "collage", "کولاژ"],
    "particle_field": ["particles", "particle", "ذرات"],
    "neo_brutalism": ["neo brutalism", "neobrutalism", "neo-brutalism", "brutalist", "نئوبروتالیسم", "نئو بروتالیسم"],
    "bauhaus_geometric": ["bauhaus", "باهاوس"],
    "memphis_80s": ["memphis", "memphis design", "ممفیس"],
    "vaporwave_dream": ["vaporwave", "vapor wave", "ویپورویو", "ویپورموج"],
    "anime_90s_cel": ["90s anime", "cel anime", "انیمه نود", "انیمه دهه ۹۰"],
    "shonen_action": ["shonen", "naruto style", "dragon ball style", "one piece style", "شونن"],
    "anime_chibi": ["chibi", "super deformed", "چیبی"],
    "persian_miniature": ["miniature painting", "persian painting", "نگارگری", "مینیاتور", "مینیاتور ایرانی"],
    "ukiyoe_woodblock": ["ukiyo-e", "ukiyoe", "hokusai style", "japanese print", "اوکیوئه"],
    "kids_crayon_doodle": ["crayon", "children drawing", "نقاشی کودکانه", "مداد شمعی"],
    "cinematic_realistic": ["cinematic", "film look", "realistic", "movie", "سینمایی", "واقع گرا"],
    "documentary_real": ["documentary", "مستند"],
    "retro_rubberhose": ["rubber hose", "1930s cartoon", "vintage cartoon", "کارتون قدیمی"],
    "midcentury_modern_2d": ["mid-century", "mid century modern"],
    "toon_shaded_3d": ["toon shading", "anime 3d", "تون شیدینگ"],
    "super8_home_movie": ["super 8", "super8", "8mm", "home video", "old film", "فیلم قدیمی", "سوپر ۸"],
    "vhs_analog": ["vhs", "camcorder", "analog", "ویدیو قدیمی", "وی اچ اس"],
    "ink_wash_sumi": ["sumi-e", "sumi e", "ink painting", "chinese ink", "نقاشی جوهری"],
    "impressionist_oil": ["impressionism", "monet style", "oil painting", "امپرسیونیسم", "رنگ روغن"],
    "art_deco_gilded": ["art deco", "gatsby", "آرت دکو"],
    "art_nouveau_botanical": ["art nouveau", "mucha style", "آرنوو", "آر نوو"],
    "calligraphy_ink_art": ["calligraphy", "nastaliq", "persian calligraphy", "خوشنویسی", "نقاشی خط"],
    "dark_fantasy_painting": ["dark fantasy", "gothic", "فانتزی تاریک"],
    "vinyl_toy_figure": ["designer toy", "art toy", "funko style", "vinyl figure", "اسباب بازی کلکسیونی"],
    "y2k_bubble_chrome": ["y2k", "2000s", "frutiger aero", "وای تو کی"],
    "wireframe_hud": ["wireframe", "hud", "hologram", "sci-fi interface", "هولوگرام", "وایرفریم"],
    "terminal_ascii": ["ascii", "terminal", "hacker", "matrix", "code", "کد", "هکر"],
    "tilt_shift_miniature": ["tilt shift", "tiltshift", "miniature", "تیلت شیفت"],
    "double_exposure": ["double exposure", "نوردهی دوگانه"],
    "manga_bw_ink": ["manga", "black and white manga", "مانگا"],
    "duotone_gradient": ["duotone", "two colour", "دوتون"],
    "die_cut_sticker": ["sticker", "stickers", "telegram sticker", "استیکر"],
    "constructivist_poster": ["constructivism", "propaganda poster", "ساختن گرا"],
    "groovy_70s": ["70s", "seventies", "retro 70s", "دهه هفتاد میلادی"],
    "lowfi_cozy_pixel": ["lofi", "lo-fi", "cozy room", "لو فای"],
}


# The name the OWNER uses for a look, shown as a small "inspired by" caption next to the generic look that stands in for it (so he can see at a glance that
# every look on his list is in the library). It is display-only: never part of a style's data, never in a prompt (tests/test_style_library.py checks both).
# Only looks whose own name does not already say it are listed here.
KNOWN_AS: dict[str, str] = {
    "early_console_3d": "PS2 style",
    "comic_ink": "Comic Art",
    "minimal_bw_essay": "Dan Koe style",
    "toy_brick_3d": "Lego-like bricks",
    "fast_3d_explainer": "ZackD Films style",
    "modern_tv_anime": "Anime",
    "painterly_pastoral": "Studio Ghibli",
    "fairytale_feature_2d": "Disney",
    "bold_angular_tv_toon": "Cartoon Network",
    "corporate_flat_people": "Corporate Memphis",
    "clay_3d_render": "3D Claymation",
    "chrome_metal_type": "Chrome 22K",
}


def known_as(key: str) -> str:
    return KNOWN_AS.get(key, "")


def terms_for(key: str) -> list[str]:
    return ALIASES.get(key, [])
