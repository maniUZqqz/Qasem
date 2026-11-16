// Brand colours on top of a style's palette. PURE (only util.ts, which needs `remotion` for its seeded random; a plain-node test stubs that).
import type { Brand, Pal } from "./types";
import { bestText, contrast, lum, rgba, shade } from "./util";

/** nudge `c` (towards white or black, whichever helps) until it reads on `bg` with ratio >= need; the hue stays */
export function fitOn(c: string, bg: string, need: number): string {
  if (contrast(c, bg) >= need) return c;
  const up = lum(bg) <= 0.18;                      // lighten on a dark background; the WCAG crossover (0.179) decides which of black / white reads better, so a mid-tone background (tan, sky blue, coral) is darkened - at 0.4 it was lightened towards a white that can never reach the ratio
  for (let k = 1; k <= 18; k++) {
    const t = shade(c, (up ? 1 : -1) * k * 0.05);
    if (contrast(t, bg) >= need) return t;
  }
  return up ? "#ffffff" : "#111111";
}

/** brand colours on top of the style palette. A brand colour that is almost white or almost black is no ACCENT (it would be a pale / black slab behind the
 *  style's light or dark text: the sun of «synthwave», the cards of «vaporwave»): the style keeps its own accent in that slot. The accent text colour is
 *  made readable on the style's background (>= 4.5 for the small kicker lines, >= 3 for the second and third accent) without changing its hue. */
export function brandPalette(pal: Pal, brand?: Brand): Pal {
  if (!brand || brand.use_brand_colors === false) return pal;
  const cols = (brand.colors || []).filter((c) => /^#?[0-9a-fA-F]{6}$/.test((c || "").trim())).map((c) => (c.startsWith("#") ? c : "#" + c));
  const usable = cols.filter((c) => lum(c) >= 0.03 && lum(c) <= 0.72);
  if (!usable.length) return pal;
  const out = { ...pal };
  out.accent = fitOn(usable[0], pal.bg, 4.5);
  if (usable[1]) out.accent2 = fitOn(usable[1], pal.bg, 3.0);
  if (usable[2]) out.accent3 = fitOn(usable[2], pal.bg, 3.0);
  return out;
}

/** a plain small text (kicker, author ...) on the style's background: when its colour would nearly vanish, darken/lighten it, else fall back to the best of ink / white / black.
 *  The direction is the WCAG crossover (0.179): on a mid-tone background (tan, sky blue, coral) only the dark side can reach the ratio. */
export function readableOn(c: string, bg: string, ink: string, need = 3): string {
  if (!/^#|^rgb/.test(c) || contrast(c, bg) >= need) return c;
  const d = shade(c, lum(bg) > 0.18 ? -0.55 : 0.55);
  return contrast(d, bg) >= need ? d : bestText(bg, [ink, "#ffffff", "#111111"]);
}

/** the small label lines (kicker, eyebrow, caption) are read at arm's length on a phone: anti-aliasing of thin strokes costs about a point of contrast, so the palette-level bar is 4.5 */
export const LABEL_CONTRAST = 4.5;

/** A soft halo in the style's own background colour around SMALL text (kicker, caption, body line, an accent suffix such as the «+» of a number).
 *  The text colour is chosen to read on the palette background; the picture behind it (a spotlight cone, a busy tile, a sun, a cloud) can still be
 *  far from that colour. The halo repaints the pixels right around the letters in the palette background colour, so the letters read on ANY picture
 *  without a plate or a layout change (display titles have their own effects and are left alone). */
export function haloCss(bg: string, size: number): string {
  return `0 0 ${(0.07 * size).toFixed(1)}px ${rgba(bg, 0.95)}, 0 0 ${(0.16 * size).toFixed(1)}px ${rgba(bg, 0.85)}, 0 0 ${(0.34 * size).toFixed(1)}px ${rgba(bg, 0.6)}`;
}
