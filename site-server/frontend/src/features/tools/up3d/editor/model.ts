import { label } from "../api";
import type { Catalog, Item, Motion, SceneDoc, Shot, Track } from "../types";

/**
 * مدلِ ویرایشگر: شیارها، برچسب‌های فارسی، ساختِ قطعهٔ تازه و تولیدِ کد از سند.
 * (همان منطقِ editor.js ِ قدیمی، بی‌DOM.)
 */

export const TRACKS: { id: Track; name: string }[] = [
  { id: "shots", name: "دوربین" },
  { id: "actions", name: "حرکت" },
  { id: "speech", name: "گفتار" },
  { id: "expressions", name: "چهره" },
  { id: "gaze", name: "نگاه" },
  { id: "overlays", name: "نوشته" },
];

export const EXPRS: Record<string, string> = {
  neutral: "خنثی",
  smile: "لبخند",
  big_smile: "لبخندِ بزرگ",
  warm: "گرم",
  surprised: "شگفت‌زده",
  thinking: "فکر",
  confident: "مطمئن",
  wink: "چشمک",
};

export const OVT: Record<string, string> = {
  title: "عنوان",
  subtitle: "زیرنویس",
  cta: "دعوت به خرید",
  price: "قیمت",
  badge: "نشان",
};

export const MOVES_FA: Record<string, string> = {
  static: "ثابت",
  push_in: "نزدیک‌شدن",
  pull_out: "دورشدن",
  orbit_left: "چرخش به چپ",
  orbit_right: "چرخش به راست",
  crane_up: "بالا رفتن",
  crane_down: "پایین آمدن",
  handheld: "روی دست",
  rack_focus: "تغییرِ فوکوس",
  slide_left: "سُرخوردن به چپ",
  slide_right: "سُرخوردن به راست",
};

export const CAT_FA: Record<string, string> = { base: "پایه", gesture: "ژست", interaction: "تعامل با محصول", face: "سر و چهره (لایه)" };

export type Sel = { track: Track; idx: number } | null;

export function byId<K extends keyof Catalog>(cat: Catalog, kind: K, id: string | undefined | null): Catalog[K][number] | undefined {
  if (!id) return undefined;
  return (cat[kind] as Catalog[K][number][]).find((a) => a.id === id);
}

export function trackName(t: Track): string {
  return TRACKS.find((x) => x.id === t)?.name ?? t;
}

/** عنوانِ قطعه روی خطِ زمان */
export function itemLabel(cat: Catalog, track: Track, it: Item): string {
  if (track === "actions") {
    const m = byId(cat, "motion", it.motion);
    const prod = it.params && typeof it.params.product === "string" ? ` · ${it.params.product}` : "";
    return (m ? label(m) : it.motion || "") + prod;
  }
  if (track === "speech") return `🗣 ${it.text || ""}`;
  if (track === "shots") {
    const s = byId(cat, "shot", it.shot);
    return `🎥 ${s ? label(s) : it.shot || ""} · ${MOVES_FA[it.move || ""] || it.move || ""} · ${it.subject || ""}`;
  }
  if (track === "expressions") return EXPRS[it.expression || ""] || it.expression || "";
  if (track === "gaze") return `👁 ${it.target === "camera" ? "دوربین" : it.target || ""}`;
  if (track === "overlays") return `${OVT[it.type || ""] || it.type || ""}: ${it.text || ""}`;
  return it.id || "";
}

export function speechSeconds(text: string): number {
  return Math.max(1, text.length / 13 + 0.4);
}

export function docDuration(doc: SceneDoc): number {
  return Number(doc.output.duration) || 10;
}

/** قطعهٔ تازه در زمانِ `t` (برای دکمهٔ + ِ هر شیار) */
export function newItem(cat: Catalog, doc: SceneDoc, track: Track, t: number): Item {
  const actor = doc.actors[0]?.id ?? null;
  const prod = doc.products[0]?.id ?? null;
  const defaultVoice = doc.speech[0]?.voice || (cat.voice.find((v) => v.default) || cat.voice[0])?.id;
  switch (track) {
    case "actions":
      return { actor, motion: "talk", start: t, duration: 2.0, params: {} };
    case "speech":
      return { actor, text: "متنِ تازه", start: t, duration: speechSeconds("متنِ تازه"), voice: defaultVoice };
    case "shots":
      return { shot: "medium", start: t, duration: 2.5, subject: actor || prod || undefined, move: "static", params: {} };
    case "expressions":
      return { actor, expression: "smile", start: t, duration: 2.0, intensity: 0.7 };
    case "gaze":
      return { actor, target: prod ? `product:${prod}` : "camera", start: t, duration: 1.5 };
    case "overlays":
    default:
      return { type: "title", text: "نوشتهٔ تازه", start: t, duration: 2.5 };
  }
}

export function sortTrack(items: Item[]) {
  items.sort((a, b) => a.start - b.start);
}

/** مسیرِ ایراد مثل `actions[3]` ⇐ انتخاب */
export function selFromPath(path: string): Sel {
  const m = /^(\w+)\[(\d+)\]$/.exec(path);
  if (!m) return null;
  const track = m[1] as Track;
  if (!TRACKS.some((t) => t.id === track)) return null;
  return { track, idx: Number(m[2]) };
}

export function motionOf(cat: Catalog, it: Item): Motion | undefined {
  return byId(cat, "motion", it.motion);
}

export function shotOf(cat: Catalog, it: Item): Shot | undefined {
  return byId(cat, "shot", it.shot);
}

// ───────────────────────── تولیدِ کد

const q = (s: unknown) => JSON.stringify(s ?? "");

export function pythonCode(doc: SceneDoc, origin: string): string {
  let py = `# python -m pip install -e <UP3D_ROOT>  (یا PYTHONPATH=<UP3D_ROOT>)\nfrom up3d.sdk import Scene\n\n`;
  py += `s = (Scene(${q(doc.meta?.title || "")}, duration=${doc.output.duration}, aspect=${q(doc.output.aspect)})\n`;
  py += `     .environment(${q(doc.environment.id)}).lighting(${q(doc.lighting.id)})\n`;
  doc.actors.forEach((a) => {
    py += `     .actor(${q(a.id)}, ${q(a.character)}, mark=${q(a.mark)})\n`;
  });
  doc.products.forEach((p) => {
    py += `     .product(${q(p.id)}, ${q(p.asset)}, name=${q(p.name || "")}, surface=${q(p.surface)})\n`;
  });
  doc.actions.forEach((a) => {
    const ps = Object.entries(a.params || {})
      .map(([k, v]) => `, ${k}=${q(v)}`)
      .join("");
    py += `     .do(${q(a.actor)}, ${q(a.motion)}, start=${a.start}, duration=${a.duration}${ps})\n`;
  });
  doc.speech.forEach((s) => {
    py += `     .say(${q(s.actor)}, ${q(s.text)}, start=${s.start}, voice=${q(s.voice)})\n`;
  });
  doc.shots.forEach((s) => {
    py += `     .shot(${q(s.shot)}, ${s.start}, ${s.duration}, subject=${q(s.subject)}, move=${q(s.move)})\n`;
  });
  doc.overlays.forEach((o) => {
    py += `     .overlay(${q(o.type)}, ${q(o.text)}, ${o.start}, ${o.duration})\n`;
  });
  py += `)\nprint(s.validate())\n# روی پنل رندر کن:\n# s.render('preview', server='${origin}', token='<توکنِ API از صفحهٔ «توکن»>')\n`;
  return py;
}

export function curlCode(pid: number | string, origin: string): string {
  const base = `${origin}/api/v1/up3d`;
  const H = `-H "Authorization: Token $TOKEN"`;
  const J = `-H "Content-Type: application/json"`;
  return (
    `# توکن: صفحهٔ «توکنِ API»\nTOKEN=...\n\n` +
    `# وضعیتِ پروژه\ncurl ${H} ${base}/video-projects/${pid}/\n\n` +
    `# پیش‌نمایش\ncurl -X POST ${H} ${J} -d '{"profile":"preview"}' ${base}/video-projects/${pid}/preview/\n\n` +
    `# رندرِ نهایی روی کارگرِ GPU\ncurl -X POST ${H} ${J} -d '{"profile":"high"}' ${base}/video-projects/${pid}/render/\n\n` +
    `# نتیجه\ncurl ${H} ${base}/video-projects/${pid}/result/\n\n` +
    `# ویرایش با زبانِ طبیعی\ncurl -X POST ${H} ${J} -d '{"instruction":"شاتِ آخر نزدیک‌تر باشد"}' ${base}/video-projects/${pid}/edit/`
  );
}
