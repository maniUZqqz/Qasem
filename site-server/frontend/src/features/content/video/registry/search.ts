import { MENUS, type FeatureDef } from "./types";

/**
 * جستجوی ابزار: فارسی و انگلیسی و مترادف، بدونِ حساسیت به «ی/ي»، «ک/ك»، نیم‌فاصله، اعرابِ فارسی و رقم‌های فارسی/عربی.
 * هر کلمهٔ جستجو باید جایی پیدا شود (AND)؛ امتیاز: عنوان > نامِ انگلیسی > مترادف > گروه/منو.
 */

const DIGITS: Record<string, string> = {};
"۰۱۲۳۴۵۶۷۸۹".split("").forEach((d, i) => (DIGITS[d] = String(i)));
"٠١٢٣٤٥٦٧٨٩".split("").forEach((d, i) => (DIGITS[d] = String(i)));

export function norm(s: string): string {
  let out = "";
  for (const ch of String(s ?? "").toLowerCase()) {
    if (DIGITS[ch]) out += DIGITS[ch];
    else if (ch === "ي" || ch === "ى" || ch === "ئ") out += "ی";
    else if (ch === "ك") out += "ک";
    else if (ch === "ة") out += "ه";
    else if (ch === "أ" || ch === "إ" || ch === "ٱ") out += "ا";
    else if (ch === "ؤ") out += "و";
    else if (ch === "‌" || ch === "‏" || ch === "‎" || ch === "-" || ch === "_" || ch === "/") out += " ";
    else if (ch === "ـ" || (ch >= "ً" && ch <= "ٟ") || ch === "ٰ") continue;
    else out += ch;
  }
  return out.replace(/\s+/g, " ").trim();
}

const menuTitle = (id: string) => MENUS.find((m) => m.id === id)?.title ?? "";

export type Hit = { feature: FeatureDef; score: number };

function tokenScore(token: string, f: FeatureDef): number {
  const title = norm(f.title);
  const en = norm(f.en ?? "");
  let best = 0;
  if (title === token) best = 120;
  else if (title.startsWith(token)) best = 100;
  else if (title.split(" ").some((w) => w.startsWith(token))) best = 85;
  else if (title.includes(token)) best = 65;
  if (en) {
    if (en === token) best = Math.max(best, 110);
    else if (en.startsWith(token)) best = Math.max(best, 90);
    else if (en.split(" ").some((w) => w.startsWith(token))) best = Math.max(best, 75);
    else if (en.includes(token)) best = Math.max(best, 55);
  }
  for (const w of f.words ?? []) {
    const n = norm(w);
    if (!n) continue;
    if (n === token) best = Math.max(best, 80);
    else if (n.startsWith(token)) best = Math.max(best, 62);
    else if (n.includes(token)) best = Math.max(best, 45);
  }
  if (best === 0) {
    const other = `${norm(f.group)} ${norm(menuTitle(f.menu))} ${norm(f.tip)}`;
    if (other.includes(token)) best = 20;
  }
  if (best === 0 && token.length >= 4) {
    // غلطِ تایپیِ ملایم: همهٔ حرف‌های کلمه به ترتیب در عنوان/نامِ انگلیسی بیایند
    const hay = `${title} ${en}`;
    let i = 0;
    for (const ch of hay) if (ch === token[i]) i++;
    if (i === token.length) best = 12;
  }
  return best;
}

/** امتیازِ یک ویژگی برای یک جستجو؛ 0 = نامربوط */
export function scoreFeature(query: string, f: FeatureDef): number {
  const tokens = norm(query).split(" ").filter(Boolean);
  if (!tokens.length) return 0;
  let total = 0;
  for (const t of tokens) {
    const s = tokenScore(t, f);
    if (s === 0) return 0;
    total += s;
  }
  return total - Math.min(10, norm(f.title).length / 10);
}

export function searchFeatures(query: string, features: FeatureDef[], limit = 30): Hit[] {
  return features
    .map((feature) => ({ feature, score: scoreFeature(query, feature) }))
    .filter((h) => h.score > 0)
    .sort((a, b) => b.score - a.score || a.feature.title.length - b.feature.title.length)
    .slice(0, limit);
}

// ───────── «اخیراً»
const RECENT = "nm.video.recent";
export function loadRecent(): string[] {
  try {
    const v = JSON.parse(localStorage.getItem(RECENT) || "[]");
    return Array.isArray(v) ? v.filter((x) => typeof x === "string").slice(0, 8) : [];
  } catch {
    return [];
  }
}
export function pushRecent(id: string): void {
  try {
    const next = [id, ...loadRecent().filter((x) => x !== id)].slice(0, 8);
    localStorage.setItem(RECENT, JSON.stringify(next));
  } catch {
    /* حافظهٔ مرورگر بسته است */
  }
}
