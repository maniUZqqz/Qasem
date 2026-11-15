"""SOURCE: ported from InstAI:instai/styles/style_meta.py @ 2f8aa90, adapted for store advertising (NMarketing).
تغییر: فقط سربرگ.

Browse group, suitability, generation hints and preview motif of the 44 first-release styles (the newer ones carry theirs inside `styles_more.py`).

`apply_meta` only fills a style that has no group yet, so it can be called again safely and never overrides a style that sets its own.
"""
from __future__ import annotations

from .schema import normalize_style
from .style_base import gen, suit

# key -> (group, suitability letters, motif, gen preset or (preset, overrides))
META: dict[str, tuple] = {
    "cinematic_realistic": ("cinematic", "ivc", "film", "flux_sharp"),
    "documentary_real": ("cinematic", "iv", "photo", "flux"),
    "noir_bw": ("cinematic", "ivc", "noir", "flux_sharp"),
    "painterly_semi_real": ("hand_drawn", "ivc", "paint", "flux_soft"),
    "rotoscope_look": ("hand_drawn", "iv", "wobble", "flux_lora"),
    "comic_ink": ("hand_drawn", "ic", "halftone", ("flux_lora", {"aspect": "4:5"})),
    "cyberpunk_neon": ("retro_digital", "ivc", "neoncity", "flux_sharp"),
    "anime_realistic_drama": ("anime_toon", "ivc", "anime", "anime"),
    "anime_film_cinematic": ("anime_toon", "ivc", "anime", ("anime", {"aspect": "16:9"})),
    "anime_dark_fantasy": ("anime_toon", "ivc", "anime", "anime"),
    "anime_noir_thriller": ("anime_toon", "ivc", "noir", "anime"),
    "modern_tv_anime": ("anime_toon", "ivc", "anime", "sdxl_anime"),
    "anime_90s_cel": ("anime_toon", "ivc", "anime", "sdxl_anime"),
    "anime_80s_ova": ("anime_toon", "ivc", "synth", "sdxl_anime"),
    "shonen_action": ("anime_toon", "ivc", "anime", "sdxl_anime"),
    "shojo_romance": ("anime_toon", "ivc", "kawaii", "sdxl_anime"),
    "painterly_pastoral": ("anime_toon", "ivc", "watercolor", "anime"),
    "anime_slice_of_life": ("anime_toon", "ivc", "anime", "sdxl_anime"),
    "anime_chibi": ("anime_toon", "ic", "kawaii", "sdxl_anime"),
    "anime_mecha_scifi": ("anime_toon", "ivc", "neoncity", "anime"),
    "anime_isekai_fantasy": ("anime_toon", "ivc", "anime", "anime"),
    "anime_horror_gothic": ("anime_toon", "ivc", "noir", "anime"),
    "anime_lofi_night": ("anime_toon", "iv", "neoncity", "anime"),
    "western_2d_tv": ("anime_toon", "ivc", "flat", "flux_lora"),
    "retro_rubberhose": ("anime_toon", "ivc", "wobble", "flux_lora"),
    "midcentury_modern_2d": ("anime_toon", "iv", "geometric", "flux_lora"),
    "kids_crayon_doodle": ("hand_drawn", "ic", "crayon", "flux_lora"),
    "flat_vector_motion": ("graphic_design", "iv", "flat", ("flux_lora", {"aspect": "16:9"})),
    "whiteboard_explainer": ("motion_type", "iv", "whiteboard", ("flux_lora", {"aspect": "16:9"})),
    "chalkboard_classroom": ("motion_type", "iv", "chalk", ("flux_lora", {"aspect": "16:9"})),
    "pixel_art_16bit": ("retro_digital", "ivc", "pixel", ("flux_lora", {"steps": 28, "lora": ["a pixel-art style LoRA for FLUX (check its licence)"]})),
    "kawaii_pastel": ("anime_toon", "ic", "kawaii", "flux_soft"),
    "paper_cutout": ("craft", "iv", "paper", "flux_lora"),
    "watercolour_storybook": ("hand_drawn", "ivc", "watercolor", "flux_soft"),
    "ukiyoe_woodblock": ("hand_drawn", "ic", "woodblock", "flux_lora"),
    "persian_miniature": ("hand_drawn", "ic", "miniature", "flux_lora"),
    "islamic_geometric_graphic": ("graphic_design", "iv", "geometric", "flux_lora"),
    "cg_family_3d": ("cg_3d", "ivc", "cg", "flux_sharp"),
    "toon_shaded_3d": ("cg_3d", "ivc", "cg", "flux_sharp"),
    "claymation_stopmotion": ("craft", "ivc", "clay", "flux_soft"),
    "felt_plush_stopmotion": ("craft", "ivc", "felt", "flux_soft"),
    "low_poly_3d": ("cg_3d", "iv", "lowpoly", "flux_sharp"),
    "isometric_diorama": ("cg_3d", "iv", "iso", ("flux_sharp", {"aspect": "1:1"})),
    "vaporwave_synth": ("retro_digital", "iv", "synth", "flux_lora"),
}


def apply_meta(styles: dict[str, dict]) -> None:
    for key, st in styles.items():
        m = META.get(key)
        if not m or st.get("group"):
            continue
        group, letters, motif, g = m
        preset, over = (g, {}) if isinstance(g, str) else g
        styles[key] = normalize_style({**st, "group": group, "suitability": suit(letters), "motif": motif, "gen": gen(preset, **over)})
