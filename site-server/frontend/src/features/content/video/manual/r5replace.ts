/**
 * «رندر و جایگزینی» (Render and replace): قطعه‌های انتخاب‌شده (با تصویر، صدا، افکت و رنگشان) روی سرور یک فایلِ ویدیو می‌شوند و
 * همان فایل جای آن‌ها روی تایم‌لاین می‌نشیند؛ برای بخش‌های سنگین که پیش‌نمایششان کند است.
 * منطقِ خالص؛ آزمون: tests/video-r5-replace.test.ts. سرور: `export.replace` + `inout` در apps/content/tasks_editing.py.
 */
import { AnyClip, MediaClip, Project, Track, addTrack, clipEnd, clipLength, uid, withLinked } from "./model";

export type ReplaceSpec = { ok: true; ids: string[]; at: number; end: number; data: Project; trackId: string } | { ok: false; error: string };
export type Rendered = { ref: string; seconds: number; has_audio: boolean; title?: string };

const bakeable = (c: AnyClip): c is MediaClip => c.type === "media";

/** از انتخاب: شناسه‌های واقعی (با قطعه‌های پیوندی)، بازهٔ زمانی، و پروژه‌ای که فقط همین قطعه‌ها را دارد (برای رندر) */
export function replaceSpec(p: Project, selection: string[]): ReplaceSpec {
  const ids = withLinked(p, selection);
  const picked = p.tracks.flatMap((t) => t.clips.filter((c) => ids.includes(c.id) && bakeable(c)).map((c) => ({ t, c: c as MediaClip })));
  if (picked.length === 0) return { ok: false, error: "اول یک یا چند ویدیو، عکس یا صدا را روی تایم‌لاین انتخاب کنید (متن و زیرنویس پخته نمی‌شود)." };
  if (picked.some(({ c }) => c.adjust)) return { ok: false, error: "لایهٔ تنظیم را نمی‌شود پخت؛ آن را از انتخاب بیرون بیاورید (روی بقیه اثر می‌کند)." };
  if (picked.some(({ c }) => c.ref.startsWith("seq:"))) return { ok: false, error: "توالیِ تودرتو را اول باز کنید یا همان را «رندر» بگیرید؛ در این روش پخته نمی‌شود." };
  const at = Math.min(...picked.map(({ c }) => c.at));
  const end = Math.max(...picked.map(({ c }) => clipEnd(c)));
  if (end - at < 0.3) return { ok: false, error: "این بازه خیلی کوتاه است." };
  const keep = new Set(picked.map(({ c }) => c.id));
  const tracks = p.tracks
    .map((t) => ({ ...t, clips: t.clips.filter((c) => keep.has(c.id)) }))
    .filter((t) => t.clips.length > 0);
  const firstVideo = p.tracks.find((t) => t.kind === "video" && t.clips.some((c) => keep.has(c.id)));
  const trackId = (firstVideo ?? picked[0].t).id;
  const data: Project = { ...p, tracks, markers: [], inout: { in: at, out: end }, export: { ...(p.export ?? {}) } };
  return { ok: true, ids: [...keep], at, end, data, trackId };
}

/** فایلِ رندرشده را جای قطعه‌های اصلی می‌گذارد؛ اگر جا نبود روی ترکِ تصویرِ تازه */
export function applyReplace(p: Project, spec: Extract<ReplaceSpec, { ok: true }>, r: Rendered): Project | null {
  const present = new Set(p.tracks.flatMap((t) => t.clips.map((c) => c.id)));
  if (!spec.ids.every((id) => present.has(id))) return null;              // در این فاصله قطعه‌ها عوض یا پاک شده‌اند
  const gone = new Set(spec.ids);
  let q: Project = { ...p, tracks: p.tracks.map((t) => ({ ...t, clips: t.clips.filter((c) => !gone.has(c.id)) })) };
  const len = Math.max(0.3, r.seconds || spec.end - spec.at);
  let track: Track | undefined = q.tracks.find((t) => t.id === spec.trackId && t.kind === "video");
  const free = (t: Track) => !t.locked && !t.clips.some((c) => spec.at < clipEnd(c) - 0.001 && spec.at + len > c.at + 0.001);
  if (!track || !free(track)) {
    q = addTrack(q, "video");
    track = q.tracks.filter((t) => t.kind === "video").slice(-1)[0];
  }
  const clip: MediaClip = {
    id: uid(), type: "media", ref: r.ref, label: "رندرِ جایگزین", kind: "video", at: spec.at, start: 0, end: len, src: len, opacity: 1, x: 0, y: 0, width: 1, height: 1,
    volume: 1, speed: 1, fit: "cover", fade_in: 0, fade_out: 0, audio_on: true, has_audio: r.has_audio, effects: [], transition: null,
  };
  const tid = track.id;
  return { ...q, tracks: q.tracks.map((t) => (t.id === tid ? { ...t, clips: [...t.clips, clip].sort((a, b) => a.at - b.at) } : t)) };
}

export const replacedLength = (p: Project, ids: string[]): number => p.tracks.flatMap((t) => t.clips.filter((c) => ids.includes(c.id))).reduce((m, c) => Math.max(m, clipLength(c)), 0);

export type JobView = { id: number; state: string; error: string; label: string; percent: number; active: boolean };

/** وضعیتِ یک کارِ رندر از فهرستِ `renders` سرور */
export function pollJob(jobs: JobView[], replaced: Record<string, Rendered>, jobId: number):
  { phase: "wait"; percent: number; label: string } | { phase: "done"; rendered: Rendered } | { phase: "failed"; message: string } {
  const j = jobs.find((x) => x.id === jobId);
  if (!j) return { phase: "wait", percent: 0, label: "" };
  if (j.state === "FAILED") return { phase: "failed", message: j.error || "رندر شکست خورد." };
  if (j.state === "CANCELLED") return { phase: "failed", message: "رندر لغو شد." };
  if (j.state === "COMPLETED") {
    const r = replaced[String(jobId)];
    return r ? { phase: "done", rendered: r } : { phase: "failed", message: "رندر تمام شد ولی فایلِ جایگزین ساخته نشد." };
  }
  return { phase: "wait", percent: j.percent, label: j.label };
}
