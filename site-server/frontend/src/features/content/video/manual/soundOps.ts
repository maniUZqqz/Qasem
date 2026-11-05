import { fa } from "../../../../components/ui";
import { ClipAudio, DEFAULT_DUCKING, MediaClip, Project, Track, isMedia } from "./model";

/**
 * عملیاتِ خالصِ «صداگذاریِ ساده» روی پروژه (بدونِ React و بدونِ سرور): بلندیِ گفتار/موسیقی، کم‌شدنِ خودکارِ موسیقی، صدای تمیز.
 * همهٔ آن‌ها پروژهٔ تازه برمی‌گردانند تا با تاریخچهٔ برگشت (edit.live/end/apply) بنشینند.
 */

/** بازهٔ لغزنده‌ها (دسی‌بل) */
export const SPEECH_DB = { min: -20, max: 10 } as const;
export const MUSIC_DB = { min: -40, max: 0 } as const;
/** مقدارِ «ملایم» و «قوی» برای کم‌شدنِ موسیقی زیرِ گفتار */
export const DUCK_SOFT_DB = 8;
export const DUCK_STRONG_DB = 14;
/** صدای موسیقیِ تازه زیرِ گفتار و بلندیِ استانداردِ شبکه‌های اجتماعی */
export const MUSIC_START_DB = -18;
export const LOUDNESS_TARGET = -14;
export const LOUDNESS_TP = -1;

export type DuckMode = "off" | "soft" | "strong" | "custom";

const hasVoiceVideo = (t: Track) => t.clips.some((c) => isMedia(c) && c.kind === "video" && c.has_audio && c.audio_on);

/** ترکِ گفتار: نقشِ «گفتار»، یا ترکِ تصویریِ بی‌نقش که ویدیوی صدادار دارد (آدمی که جلوی دوربین حرف می‌زند) */
export const isSpeechTrack = (t: Track): boolean => {
  if (t.kind === "text") return false;
  if (t.role === "speech") return true;
  return t.kind === "video" && !t.role && hasVoiceVideo(t);
};

export const isMusicTrack = (t: Track): boolean => t.kind !== "text" && t.role === "music";

export const speechTracks = (p: Project): Track[] => p.tracks.filter(isSpeechTrack);
export const musicTracks = (p: Project): Track[] => p.tracks.filter(isMusicTrack);
export const hasClips = (tracks: Track[]): boolean => tracks.some((t) => t.clips.length > 0);

/** میانگینِ بلندیِ ترک‌ها (اگر با هم فرق داشته باشند، لغزنده میانگین را نشان می‌دهد و با کشیدن همه یکی می‌شوند) */
export const meanGain = (tracks: Track[]): number => {
  if (!tracks.length) return 0;
  return tracks.reduce((s, t) => s + (t.gain_db ?? 0), 0) / tracks.length;
};

export const roundHalf = (x: number): number => Math.round(x * 2) / 2;

export function setGains(p: Project, pick: (t: Track) => boolean, db: number): Project {
  const v = roundHalf(db);
  return { ...p, tracks: p.tracks.map((t) => (pick(t) ? { ...t, gain_db: v } : t)) };
}

// ───────────── کم‌شدنِ خودکارِ موسیقی
export function duckMode(p: Project): DuckMode {
  const d = p.ducking;
  if (!d?.on) return "off";
  if (Math.abs(d.amount_db - DUCK_SOFT_DB) < 1.5) return "soft";
  if (Math.abs(d.amount_db - DUCK_STRONG_DB) < 1.5) return "strong";
  return "custom";
}

export function setDuckMode(p: Project, mode: "off" | "soft" | "strong"): Project {
  const base = p.ducking ?? DEFAULT_DUCKING;
  if (mode === "off") return { ...p, ducking: { ...base, on: false } };
  return { ...p, ducking: { ...base, on: true, amount_db: mode === "soft" ? DUCK_SOFT_DB : DUCK_STRONG_DB } };
}

// ───────────── صدای تمیز
/** قطعه‌هایی که «گفتار»اند: قطعه‌های ترکِ گفتار، و قطعه‌های ویدیوییِ صدادار (جز ترک‌های موسیقی و افکت) */
export function speechClips(p: Project): MediaClip[] {
  const out: MediaClip[] = [];
  for (const t of p.tracks) {
    if (t.kind === "text" || t.role === "music" || t.role === "sfx") continue;
    for (const c of t.clips) {
      if (!isMedia(c) || c.kind === "image") continue;
      if (t.kind === "audio" ? t.role === "speech" : c.kind === "video" && c.has_audio && c.audio_on) out.push(c);
    }
  }
  return out;
}

export type CleanState = "none" | "off" | "partial" | "on";

export function cleanState(p: Project): CleanState {
  const cs = speechClips(p);
  if (!cs.length) return "none";
  const on = cs.filter((c) => !!c.audio?.enhance && !!c.audio?.denoise).length;
  return on === cs.length ? "on" : on === 0 ? "off" : "partial";
}

const withClean = (a: ClipAudio | undefined, on: boolean): ClipAudio => {
  const next: ClipAudio = { ...(a ?? {}) };
  if (on) {
    next.enhance = true;
    next.denoise = true;
  } else {
    delete next.enhance;
    delete next.denoise;
  }
  return next;
};

export function setClean(p: Project, on: boolean): Project {
  const ids = new Set(speechClips(p).map((c) => c.id));
  if (!ids.size) return p;
  return { ...p, tracks: p.tracks.map((t) => ({ ...t, clips: t.clips.map((c) => (isMedia(c) && ids.has(c.id) ? { ...c, audio: withClean(c.audio, on) } : c)) })) };
}

// ───────────── نمایش
const faNum = (x: number): string => fa(String(x)).replace(".", "٫");

/** «+۳ dB» / «−۱۸٫۵ dB» / «۰ dB» */
export function dbText(v: number): string {
  const r = Math.round(v * 10) / 10;
  if (r === 0) return "۰ dB";
  return `${r < 0 ? "−" : "+"}${faNum(Math.abs(r))} dB`;
}

export { faNum };
