/**
 * ترجمهٔ زیرنویس (تابع‌های خالص): خط‌های زیرنویسِ تایم‌لاین → فهرستِ {id, text} برای سرور → ترجمه روی یک ترکِ تازه یا جای متنِ قبلی.
 * سرور: POST editor/captions/translate/ (services/editing/translate.py). آزمون: tests/video-r5-translate.test.ts.
 */
import { AnyClip, Project, TextClip, addTrack, updateClip, updateTrack, uid } from "./model";

export const TRANSLATE_LANGS: { key: string; title: string; rtl: boolean }[] = [
  { key: "en", title: "انگلیسی", rtl: false }, { key: "fa", title: "فارسی", rtl: true }, { key: "ar", title: "عربی", rtl: true }, { key: "tr", title: "ترکی استانبولی", rtl: false },
  { key: "ru", title: "روسی", rtl: false }, { key: "de", title: "آلمانی", rtl: false }, { key: "fr", title: "فرانسوی", rtl: false }, { key: "es", title: "اسپانیایی", rtl: false },
  { key: "it", title: "ایتالیایی", rtl: false }, { key: "zh", title: "چینی", rtl: false }, { key: "hi", title: "هندی", rtl: false }, { key: "ur", title: "اردو", rtl: true },
];
export type Line = { id: string; text: string };
export type Translated = { id: string; text: string };
export const MAX_LINES = 300;

const isText = (c: AnyClip): c is TextClip => c.type === "text";

/** خط‌های زیرنویس: ترک‌های «زیرنویس»، و اگر نبود همهٔ متن‌ها؛ به ترتیبِ زمان */
export function captionLines(p: Project): Line[] {
  const caps = p.tracks.filter((t) => t.kind === "text" && t.caption);
  const pool = (caps.some((t) => t.clips.length) ? caps : p.tracks.filter((t) => t.kind === "text")).flatMap((t) => t.clips.filter(isText));
  return pool.filter((c) => c.text.trim()).sort((a, b) => a.at - b.at).map((c) => ({ id: c.id, text: c.text }));
}

export const langTitle = (key: string) => TRANSLATE_LANGS.find((l) => l.key === key)?.title ?? key;

/** ترجمه را به پروژه می‌آورد. "new" = ترکِ تازه (اصل می‌ماند)، "replace" = متنِ همان قطعه‌ها عوض می‌شود. */
export function applyTranslation(p: Project, items: Translated[], lang: string, mode: "new" | "replace"): Project {
  const byId = new Map(items.map((i) => [i.id, i.text]));
  const rtl = TRANSLATE_LANGS.find((l) => l.key === lang)?.rtl ?? false;
  if (mode === "replace") {
    let q = p;
    for (const [id, text] of byId) q = updateClip(q, id, { text, words: undefined, ...(rtl ? {} : { align: "center" as const }) } as Partial<TextClip>);
    return q;
  }
  const sources = p.tracks.flatMap((t) => t.clips.filter(isText)).filter((c) => byId.has(c.id));
  if (sources.length === 0) return p;
  let q = addTrack(p, "text");
  const made = q.tracks.filter((t) => t.kind === "text").slice(-1)[0];
  q = updateTrack(q, made.id, { name: `ترجمه (${langTitle(lang)})`, caption: false });
  const clips: TextClip[] = sources.map((c) => ({ ...c, id: uid(), text: byId.get(c.id) as string, words: undefined, ...(rtl ? {} : { align: "center" as const }) }));
  return { ...q, tracks: q.tracks.map((t) => (t.id === made.id ? { ...t, clips: clips.sort((a, b) => a.at - b.at) } : t)) };
}

/** نتیجهٔ job → فهرستِ ترجمه‌ها (یا null اگر شکلش درست نبود) */
export function resultItems(result: unknown): Translated[] | null {
  const items = (result as { items?: unknown } | undefined)?.items;
  if (!Array.isArray(items)) return null;
  const out = items.filter((i): i is Translated => !!i && typeof (i as Translated).id === "string" && typeof (i as Translated).text === "string");
  return out.length === items.length && out.length > 0 ? out : null;
}
