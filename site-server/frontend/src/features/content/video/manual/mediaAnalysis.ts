import { useEffect, useMemo, useState } from "react";

import type { Beats, Filmstrip, Waveform } from "../api";
import { videoApi } from "../api";
import { MediaClip, Project, Track, clipLength, clipSpeeds } from "./model";

/**
 * تحلیلِ رسانه برای تایم‌لاین و میکسر: موج‌صدا، نوارِ تصویر (filmstrip)، ضرب‌ها و بازه‌های گفتار.
 * همه‌چیز را سرور با ffmpeg می‌سازد و کش می‌کند؛ این‌جا فقط یک کشِ مرورگر است:
 *  • درخواستِ هم‌زمانِ یکسان یکی می‌شود (in-flight de-dup)
 *  • حداکثر ۲ درخواستِ هم‌زمان (سرورِ کوچک)
 *  • شکست ۶۰ ثانیه به خاطر سپرده می‌شود — هیچ‌وقت سرور را پشتِ‌هم نمی‌کوبیم.
 */

const MAX_CONCURRENT = 2;
const FAIL_MEMORY_MS = 60_000;

let running = 0;
const waiting: (() => void)[] = [];

function limited<T>(job: () => Promise<T>): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const start = () => {
      running += 1;
      job().then(resolve, reject).finally(() => {
        running -= 1;
        const next = waiting.shift();
        if (next) next();
      });
    };
    if (running < MAX_CONCURRENT) start();
    else waiting.push(start);
  });
}

type Entry<T> = { value?: T; error?: Error; failedAt?: number; promise?: Promise<T> };

/** یک کشِ ماژولی برای یک نوع تحلیل: کلیدش `${storeId}|${ref}` است */
function makeCache<T>(fetcher: (storeId: string, ref: string) => Promise<T>) {
  const entries = new Map<string, Entry<T>>();
  const listeners = new Map<string, Set<() => void>>();
  const keyOf = (storeId: string, ref: string) => `${storeId}|${ref}`;
  const notify = (key: string) => listeners.get(key)?.forEach((cb) => cb());

  function load(storeId: string, ref: string): Promise<T> {
    const key = keyOf(storeId, ref);
    const hit = entries.get(key);
    if (hit?.value !== undefined) return Promise.resolve(hit.value);
    if (hit?.promise) return hit.promise;
    if (hit?.error && hit.failedAt && Date.now() - hit.failedAt < FAIL_MEMORY_MS) return Promise.reject(hit.error);
    const promise = limited(() => fetcher(storeId, ref)).then(
      (value) => {
        entries.set(key, { value });
        notify(key);
        return value;
      },
      (err: unknown) => {
        const error = err instanceof Error ? err : new Error(String(err));
        entries.set(key, { error, failedAt: Date.now() });
        notify(key);
        throw error;
      },
    );
    entries.set(key, { promise });
    return promise;
  }

  const peek = (storeId: string, ref: string): T | null => entries.get(keyOf(storeId, ref))?.value ?? null;

  function subscribe(storeId: string, ref: string, cb: () => void): () => void {
    const key = keyOf(storeId, ref);
    const set = listeners.get(key) ?? new Set();
    set.add(cb);
    listeners.set(key, set);
    return () => {
      set.delete(cb);
    };
  }

  return { load, peek, subscribe };
}

const waveforms = makeCache<Waveform>((s, r) => videoApi.waveform(s, r));
const filmstrips = makeCache<Filmstrip>((s, r) => videoApi.filmstrip(s, r));
const beatCache = makeCache<Beats>((s, r) => videoApi.beats(s, r));
const speechCache = makeCache<[number, number][]>((s, r) => videoApi.speech(s, r));

/** هوکِ مشترکِ همهٔ تحلیل‌ها: مقدارِ کش‌شده یا null تا برسد (بدون خطا: شکست = null و ۶۰ ثانیه صبر) */
function useCached<T>(cache: ReturnType<typeof makeCache<T>>, storeId: string, ref: string | null | undefined, enabled: boolean): T | null {
  const [, bump] = useState(0);
  useEffect(() => {
    if (!enabled || !ref) return;
    let alive = true;
    const off = cache.subscribe(storeId, ref, () => alive && bump((n) => n + 1));
    cache.load(storeId, ref).catch(() => undefined);
    return () => {
      alive = false;
      off();
    };
  }, [cache, storeId, ref, enabled]);
  return enabled && ref ? cache.peek(storeId, ref) : null;
}

/** موجِ صدای یک رسانه (peaks 0..1، per_second نمونه در ثانیهٔ منبع) */
export function useWaveform(storeId: string, ref: string | null | undefined, enabled = true): Waveform | null {
  return useCached(waveforms, storeId, ref, enabled);
}

/** نوارِ تصاویرِ یک ویدیو (یک عکسِ افقی با `count` قاب هر `interval` ثانیه) */
export function useFilmstrip(storeId: string, ref: string | null | undefined, enabled = true): Filmstrip | null {
  return useCached(filmstrips, storeId, ref, enabled);
}

/** ضرب‌های یک موسیقی (ثانیه‌های منبع). خطا ⇒ promise رد می‌شود (پیامِ فارسیِ سرور در message). */
export function fetchBeats(storeId: string, ref: string): Promise<Beats> {
  return beatCache.load(storeId, ref);
}

/** بازه‌های گفتارِ یک رسانه (ثانیه‌های منبع) */
export function fetchSpeech(storeId: string, ref: string): Promise<[number, number][]> {
  return speechCache.load(storeId, ref);
}

// ───────────── بازه‌های گفتار روی تایم‌لاین (آینهٔ audiofx.duck_spans)
const MAX_DUCK_SPANS = 40;

/** آیا صدای این قطعه در خروجی هست (audiofx.carries + روشن‌بودنِ صدای قطعه) */
export function clipCarriesSound(track: Track, clip: MediaClip): boolean {
  if (track.kind === "audio") return true;
  return track.kind === "video" && clip.kind === "video" && clip.has_audio && clip.audio_on && !clip.freeze;
}

/** ثانیه‌ای از منبع کجای تایم‌لاین می‌افتد (سرعت، منحنی و وارونه را دنبال می‌کند) — audiofx.src_to_timeline */
export function srcToTimeline(clip: MediaClip, t: number): number {
  const speeds = clipSpeeds(clip);
  const forward = clipLength(clip);
  let cum = 0;
  let done = false;
  if (speeds.length === 1) {
    const [v] = speeds;
    if (t <= clip.end) {
      cum += Math.max(0, t - clip.start) / v;
      done = true;
    } else cum += (clip.end - clip.start) / v;
  } else {
    const step = (clip.end - clip.start) / speeds.length;
    for (let i = 0; i < speeds.length; i++) {
      const a = clip.start + i * step;
      const e = clip.start + (i + 1) * step;
      if (t <= e) {
        cum += Math.max(0, t - a) / speeds[i];
        done = true;
        break;
      }
      cum += (e - a) / speeds[i];
    }
  }
  if (!done) cum = forward;
  return clip.at + (clip.reverse ? forward - cum : cum);
}

function mergeSpans(spans: [number, number][], gap: number): [number, number][] {
  const out: [number, number][] = [];
  const sorted = [...spans].sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  for (const [s, e] of sorted) {
    const last = out[out.length - 1];
    if (last && s - last[1] <= gap) last[1] = Math.max(last[1], e);
    else out.push([s, e]);
  }
  return out;
}

/** ترک‌هایی که صدایشان به حسابِ «گفتار» می‌آید (نقشِ speech، بی‌صدا نشده، solo رعایت شده) */
function speechTracks(project: Project): Track[] {
  const soloing = project.tracks.some((t) => t.kind !== "text" && t.solo);
  return project.tracks.filter((t) => t.kind !== "text" && t.role === "speech" && !t.muted && !(soloing && !t.solo));
}

/** رفرِ رسانه‌هایی که روی ترک‌های «گفتار» صدا می‌دهند */
export function speechRefs(project: Project): string[] {
  const out = new Set<string>();
  for (const track of speechTracks(project)) {
    for (const c of track.clips) if (c.type === "media" && clipCarriesSound(track, c)) out.add(c.ref);
  }
  return [...out];
}

/** بازه‌های گفتارِ روی تایم‌لاین، برای کم‌کردنِ خودکارِ موسیقی — دقیقاً همان duck_spans سرور */
export function speechSpansForProject(project: Project, spansByRef: Record<string, [number, number][]>): [number, number][] {
  const found: [number, number][] = [];
  for (const track of speechTracks(project)) {
    for (const clip of track.clips) {
      if (clip.type !== "media" || !clipCarriesSound(track, clip)) continue;
      for (const [s0, e0] of spansByRef[clip.ref] ?? []) {
        const s = Math.max(s0, clip.start);
        const e = Math.min(e0, clip.end);
        if (e - s < 0.05) continue;
        const x = srcToTimeline(clip, s);
        const y = srcToTimeline(clip, e);
        found.push([Math.min(x, y), Math.max(x, y)]);
      }
    }
  }
  let gap = 0.6;
  let merged = mergeSpans(found, gap);
  while (merged.length > MAX_DUCK_SPANS && gap < 30) {
    gap *= 2;
    merged = mergeSpans(merged, gap);
  }
  return merged;
}

/**
 * بازه‌های گفتارِ تایم‌لاین. فقط وقتی «کم‌کردنِ خودکارِ موسیقی» روشن است (یا `enabled` صریح) از سرور می‌پرسد؛
 * با جابه‌جاییِ قطعه‌ها دوباره حساب می‌شود (بدون درخواستِ تازه — بازه‌های منبع کش‌اند).
 */
export function useDuckSpans(storeId: string, project: Project, enabled: boolean = !!project.ducking?.on): [number, number][] {
  const refsKey = enabled ? speechRefs(project).join(",") : "";
  const [byRef, setByRef] = useState<Record<string, [number, number][]>>({});
  useEffect(() => {
    if (!refsKey) return;
    let alive = true;
    for (const ref of refsKey.split(",")) {
      fetchSpeech(storeId, ref).then(
        (spans) => alive && setByRef((cur) => (cur[ref] === spans ? cur : { ...cur, [ref]: spans })),
        () => undefined,
      );
    }
    return () => {
      alive = false;
    };
  }, [storeId, refsKey]);
  return useMemo(() => (enabled ? speechSpansForProject(project, byRef) : []), [enabled, project, byRef]);
}
