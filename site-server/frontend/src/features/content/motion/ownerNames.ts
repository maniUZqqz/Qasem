/**
 * نام‌هایی که مالک در فهرستِ سبک‌های موشن نوشته (انگلیسی و فارسی) ⇒ شناسهٔ سبک. جست‌وجو با همین نام‌ها هم سبک را پیدا می‌کند؛
 * برای «Disney»، «Cartoon Network»، «Photorealistic CGI»، «Lego Style»، «Dan Koe Style» و … که نامِ کارتِ سبک چیزِ دیگری است.
 */
import type { StyleDef } from "./api";

export const OWNER_NAMES: Record<string, string[]> = {
  "pixel-art": ["Pixel Art", "پیکسل‌آرت"],
  chalkboard: ["ChalkBoard Style", "Chalkboard", "تخته"],
  "glow-sketch": ["Glow Sketch"],
  "ps2-style": ["PS2 Style"],
  "comic-art": ["Comic Art"],
  "flat-vector": ["Flat Vector", "فلت"],
  "dan-koe-style": ["Dan Koe Style", "Dan Koe"],
  "cgi-motion": ["CGI Motion"],
  "lego-bricks": ["Lego Style", "Lego", "لگو"],
  "zackd-inspired": ["ZackD Films", "ZackD"],
  "anime-inspired": ["Anime", "انیمه"],
  "ghibli-inspired": ["Studio Ghibli", "Ghibli", "جیبلی"],
  "disney-inspired": ["Disney", "دیزنی"],
  "cartoon-network-inspired": ["Cartoon Network", "کارتون نتورک"],
  watercolor: ["Watercolor"],
  "cel-shading": ["Cel Shading"],
  "line-art": ["Line Art", "لاین‌آرت"],
  silhouette: ["Silhouette"],
  claymation: ["Claymation"],
  "stop-motion": ["Stop Motion"],
  "low-poly": ["Low Poly", "لوپولی", "لو پلی"],
  "voxel-art": ["Voxel Art"],
  papercraft: ["Papercraft"],
  origami: ["Origami"],
  isometric: ["Isometric", "ایزومتریک"],
  "photoreal-cgi": ["Photorealistic CGI", "Photoreal"],
  "parallax-2-5d": ["2.5D Parallax", "Parallax"],
  synthwave: ["Synthwave", "سونسیس", "سینتویو"],
  "film-noir": ["Film Noir"],
  cyberpunk: ["Cyberpunk"],
  steampunk: ["Steampunk"],
  "pop-art": ["Pop Art", "پاپ‌آرت"],
  "stained-glass": ["Stained Glass"],
  graffiti: ["Graffiti"],
  blueprint: ["Blueprint"],
  "glitch-art": ["Glitch Art", "Glitch", "گلیچ"],
  whiteboard: ["Whiteboard"],
  "kinetic-typography": ["Kinetic Typography", "تایپوگرافی جنبشی"],
  infographic: ["Infographic"],
  "corporate-memphis": ["Corporate Memphis"],
  stickman: ["stickman"],
  "flat-2d": ["Flat 2D", "فلت دوبعدی", "فلت"],
  "claymation-3d": ["3D Claymation", "خمیری سه‌بعدی", "خمیری"],
  glassmorphism: ["Glassmorphism", "گلس‌مورفیسم"],
  "chrome-22k": ["Chrome 22K", "کروم"],
  cineview: ["Cineview", "سینت‌ویو"],
  risograph: ["Risograph", "ریسوگراف"],
  "paper-collage": ["Paper Collage", "کلاژ کاغذی"],
  particles: ["Particles", "ذرات"],
  "neo-brutalism": ["Neo-brutalism", "نئوبروتالیسم"],
  bauhaus: ["Bauhaus", "باهوس"],
  memphis: ["Memphis", "ممفیس"],
  vaporwave: ["Vaporwave", "وپرویو"],
};

const norm = (s: string) => s.toLowerCase().replace(/[‌\-_\s]+/g, "");

/** نامِ مالک برای یک سبک (اگر در نامِ انگلیسیِ کارت نیست) تا کنارِ نامِ کارت نشان داده شود. */
export function ownerLabel(s: Pick<StyleDef, "id" | "name_en">): string {
  const first = (OWNER_NAMES[s.id] || []).find((n) => /[A-Za-z]/.test(n));
  return first && !norm(s.name_en).includes(norm(first)) ? first : "";
}

/** آیا عبارتِ جست‌وجو این سبک را پیدا می‌کند؟ (نامِ فارسی، نامِ انگلیسی، برچسب‌ها، «الهام از»، و نام‌های فهرستِ مالک؛ بی‌توجه به حروفِ بزرگ و فاصله). */
export function styleMatches(s: StyleDef, q: string): boolean {
  const needle = norm(q);
  if (!needle) return true;
  const hay = [s.name_fa, s.name_en, s.inspired || "", ...s.tags, ...(OWNER_NAMES[s.id] || [])];
  return hay.some((h) => norm(h).includes(needle));
}
