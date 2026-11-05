import { forwardRef, ReactNode, useCallback, useEffect, useImperativeHandle, useMemo, useRef, useState } from "react";

import { createPortal } from "react-dom";

import { api } from "../../../../api/client";
import Icon from "../../../../components/Icon";
import type { MediaItem } from "../api";
import type { AudioEngine } from "./AudioEngine";
import type { LookDef } from "./color";
import { Compositor, Source, planTransitions, sourceTimeFor } from "./Compositor";
import { CropOverlay, CropPanel, CropSource, OnReframe, sourceSize } from "./CropOverlay";
import { setKey } from "./keyframes";
import type { Lut } from "./lut";
import {
  AnyClip, MediaClip, Project, TextClip, clipEnd, clipLength, findClip, isMedia, projectLength, propAt, speedAt, timecode,
} from "./model";
import { flattenForMedia } from "./ops";
import { AspectKey, detectAspect } from "./reframe";
import SafeZoneLayer from "./SafeZoneLayer";
import { SAFE_GENERAL, SAFE_OFF, SafeZone, readSafeZone, safeZonesOf, writeSafeZone, zoneByKey } from "./SafeZones";
import { onTextFontsReady } from "./textRender";
import "./monitor.css";

/** آدرسِ قابلِ پخش: نسخهٔ سبک (پروکسی) اگر هست؛ صداهای کتابخانه نیاز به توکن دارند ⇐ blob */
export function useMediaUrls(media: Record<string, MediaItem>, refs: string[]): Record<string, string> {
  const [urls, setUrls] = useState<Record<string, string>>({});
  const made = useRef<Record<string, string>>({});
  useEffect(() => {
    let stop = false;
    for (const ref of refs) {
      const item = media[ref];
      if (!item) continue;
      if (!item.auth) {
        const u = item.proxy === "ready" && item.proxy_url ? item.proxy_url : item.url;
        setUrls((cur) => (cur[ref] === u ? cur : { ...cur, [ref]: u }));
      } else if (!made.current[ref]) {
        made.current[ref] = "pending";
        api.get<Blob>(item.url.replace("/api/v1", ""), { responseType: "blob" })
          .then((r) => {
            if (stop) return;
            const u = URL.createObjectURL(r.data);
            made.current[ref] = u;
            setUrls((cur) => ({ ...cur, [ref]: u }));
          })
          .catch(() => {
            made.current[ref] = "";
          });
      }
    }
    return () => {
      stop = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [media, refs.join(",")]);
  useEffect(
    () => () => {
      Object.values(made.current).forEach((u) => u.startsWith("blob:") && URL.revokeObjectURL(u));
    },
    [],
  );
  return urls;
}

export type MonitorHandle = {
  getFrame: () => ImageData | null;
  getCanvas: () => HTMLCanvasElement | null;
  invalidate: () => void;
};

type Props = {
  project: Project;
  media: Record<string, MediaItem>;
  time: number;
  playing: boolean;
  rate: number;
  selection: string[];
  looks: LookDef[];
  compare: string | null;
  engine: AudioEngine | null;
  duckSpans: [number, number][];
  /** LUT های خوانده‌شده و ماتِ حذفِ پس‌زمینه (کلید ⇒ نشانی و ثانیهٔ شروع) برای پیش‌نمایش */
  luts?: Record<string, Lut>;
  matteMeta?: Record<string, { url: string; s0: number }>;
  /** لایهٔ تعاملیِ روی تصویر (ویرایشِ ماسکِ آزاد، انتخابِ ناحیهٔ ردیابی) */
  pickOverlay?: ReactNode;
  /** پخش: زمانِ فعلی را به‌صورتِ ملایم خبر می‌دهد */
  onTime: (t: number) => void;
  onEnded: () => void;
  onSeek: (t: number) => void;
  onPlay: () => void;
  onStep: (frames: number) => void;
  onRate: (r: number) => void;
  /** جابه‌جایی/اندازه/چرخش با دستگیره‌های روی تصویر */
  onGizmo: (id: string, patch: Partial<MediaClip> | Partial<TextClip>, final: boolean) => void;
  /** «برشِ قاب»: پنجرهٔ برشِ منبعِ قطعه (undefined = بدونِ برش)؛ final=false هنگامِ کشیدن، true هنگامِ رها شدن (یک گامِ برگشت) */
  onReframe?: OnReframe;
  /** حالتِ «برشِ قاب» از بیرون هم کنترل می‌شود (دکمهٔ بازرسِ قطعه)؛ اگر نیامد خودِ مانیتور نگه می‌دارد */
  cropMode?: boolean;
  onCropMode?: (on: boolean) => void;
  /** برای «بازتنظیمِ خودکار» (فراخوانیِ سرور) */
  storeId?: string;
  /** ناحیه‌های امنِ کاتالوگ (catalogue.safe_zones)؛ نبودنش = جایگزینِ داخلی */
  safeZones?: SafeZone[];
  onFrame?: () => void;
  selectedProxyHint?: ReactNode;
  overlay?: ReactNode;
  extraTransport?: ReactNode;
  badge?: ReactNode;
  footer?: ReactNode;
};

const NEAR_BEFORE = 3;
const NEAR_AFTER = 1.5;

const Monitor = forwardRef<MonitorHandle, Props>(function Monitor(props, ref) {
  const {
    project, media, time, playing, rate, selection, looks, compare, engine, duckSpans, onTime, onEnded, onPlay, onStep, onRate, onSeek, onGizmo,
  } = props;
  const stage = useRef<HTMLDivElement>(null);
  const holder = useRef<HTMLDivElement>(null);
  const compositor = useRef<Compositor | null>(null);
  const elements = useRef(new Map<string, { el: HTMLVideoElement | HTMLAudioElement | HTMLImageElement; ref: string; routed: boolean }>());
  const [size, setSize] = useState({ w: 320, h: 400 });
  const [safeKey, setSafeKey] = useState<string>(() => readSafeZone());
  const zones = useMemo(() => safeZonesOf(props.safeZones), [props.safeZones]);
  const safeShown = safeKey === SAFE_OFF || safeKey === SAFE_GENERAL || zoneByKey(zones, safeKey) ? safeKey : SAFE_OFF;
  const pickZone = (k: string) => {
    setSafeKey(k);
    writeSafeZone(k);
  };
  const rafRender = useRef(0);
  // توالی‌های تودرتو: برگ‌هایشان روی خطِ زمانِ ریشه هم‌گام می‌شوند (مونتاژگر خودش تودرتو می‌کشد)
  const flat = useMemo(() => flattenForMedia(project), [project]);
  const luts = props.luts;
  const matteMeta = props.matteMeta;
  const latest = useRef({ project, flat, time, playing, rate, looks, compare, engine, duckSpans, luts, matteMeta });
  latest.current = { project, flat, time, playing, rate, looks, compare, engine, duckSpans, luts, matteMeta };
  const matteEls = useRef(new Map<string, { el: HTMLVideoElement; url: string }>());
  const matteNow = useRef(new Map<string, Source>());
  const timeRef = useRef(time);
  const [frameVersion, setFrameVersion] = useState(0);

  const mediaClips = useMemo(() => flat.tracks.flatMap((t) => t.clips.filter(isMedia).map((c) => ({ c, t }))), [flat]);
  const refs = useMemo(() => Array.from(new Set(mediaClips.map((x) => x.c.ref))), [mediaClips]);
  const urls = useMediaUrls(media, refs);
  const urlsRef = useRef(urls);
  urlsRef.current = urls;

  const ar = project.format.width / project.format.height;
  const fw = Math.max(60, Math.min(size.w, size.h * ar));
  const fh = fw / ar;
  const total = projectLength(project);

  // ───────── اندازهٔ قاب
  useEffect(() => {
    const el = stage.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setSize({ w: el.clientWidth - 16, h: el.clientHeight - 16 }));
    ro.observe(el);
    setSize({ w: el.clientWidth - 16, h: el.clientHeight - 16 });
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    if (!compositor.current) compositor.current = new Compositor();
    const cv = compositor.current.canvas;
    cv.className = "vw-canvas";
    cv.setAttribute("data-testid", "program-canvas");
    const host = holder.current;
    if (host && cv.parentElement !== host) host.prepend(cv);
    const dpr = Math.min(window.devicePixelRatio || 1, 1.5);
    let w = fw * dpr;
    let h = fh * dpr;
    const k = Math.min(1, 900 / Math.max(w, h));
    w *= k;
    h *= k;
    compositor.current.setSize(w, h);
    requestRender();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fw, fh]);

  // ───────── منبع‌ها (element ِ هر کلیپ)
  const releaseElement = useCallback((id: string) => {
    const e = elements.current.get(id);
    if (!e) return;
    latest.current.engine?.unregister(id);
    if (e.el instanceof HTMLMediaElement) {
      e.el.pause();
      e.el.removeAttribute("src");
      e.el.load();
    }
    elements.current.delete(id);
  }, []);

  const ensureElement = useCallback((clip: MediaClip, track: { muted: boolean }): HTMLVideoElement | HTMLAudioElement | HTMLImageElement | null => {
    const url = urlsRef.current[clip.ref];
    if (!url) return null;
    const cur = elements.current.get(clip.id);
    if (cur && cur.ref === clip.ref) return cur.el;
    if (cur) releaseElement(clip.id);
    let el: HTMLVideoElement | HTMLAudioElement | HTMLImageElement;
    if (clip.kind === "image") {
      el = new Image();
      el.addEventListener("load", () => requestRender());
      el.src = url;
    } else {
      el = document.createElement(clip.kind === "audio" ? "audio" : "video");
      el.preload = "auto";
      if (el instanceof HTMLVideoElement) el.playsInline = true;
      el.muted = true;
      for (const ev of ["seeked", "loadeddata", "canplay"]) el.addEventListener(ev, () => requestRender());
      el.src = url;
    }
    let routed = false;
    if (el instanceof HTMLMediaElement && latest.current.engine && (clip.kind === "audio" || (clip.has_audio && clip.audio_on))) {
      routed = latest.current.engine.register(clip.id, el);
    }
    elements.current.set(clip.id, { el, ref: clip.ref, routed });
    void track;
    return el;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [releaseElement]);

  /** element ها را با زمان هماهنگ می‌کند (پخش/توقف/جست‌وجو) و فهرستِ منبعِ آمادهٔ رسم را برمی‌گرداند */
  const syncMedia = useCallback((t: number, isPlaying: boolean, r: number): Map<string, Source> => {
    const pr = latest.current.flat;
    const sources = new Map<string, Source>();
    const keep = new Set<string>();
    const mattes = new Map<string, Source>();
    const keepMatte = new Set<string>();
    for (const tr of pr.tracks) {
      if (tr.kind === "text") continue;
      const pairs = tr.kind === "video" ? planTransitions(tr) : [];
      for (const c of tr.clips) {
        if (!isMedia(c)) continue;
        let lo = c.at - NEAR_BEFORE;
        let hi = clipEnd(c) + NEAR_AFTER;
        for (const p of pairs) {
          if (p.a === c) hi = Math.max(hi, p.cut + p.d / 2 + 0.2);
          if (p.b === c) lo = Math.min(lo, p.cut - p.d / 2 - 0.2);
        }
        if (t < lo || t > hi) continue;
        keep.add(c.id);
        const el = ensureElement(c, tr);
        if (!el) continue;
        const inWindow = t >= c.at - 0.001 && t < clipEnd(c);
        const nearTransition = pairs.some((p) => (p.a === c || p.b === c) && t >= p.cut - p.d / 2 - 0.05 && t < p.cut + p.d / 2 + 0.05);
        const active = inWindow || nearTransition;
        if (el instanceof HTMLImageElement) {
          sources.set(c.id, el);
          continue;
        }
        const entry = elements.current.get(c.id);
        const routed = !!entry?.routed;
        const carries = c.kind === "audio" || (c.has_audio && c.audio_on);
        if (!routed) {
          el.muted = !carries || tr.muted || !active;
          el.volume = Math.max(0, Math.min(1, propAt(c, "volume", t) * (c.kind === "audio" ? c.opacity : 1)));
        }
        const want = sourceTimeFor(c, t);
        const forward = isPlaying && r > 0 && !c.reverse && !c.freeze && inWindow;
        if (forward) {
          const speed = Math.max(0.0625, Math.min(16, speedAt(c, t) * r));
          if (Math.abs(el.playbackRate - speed) > 0.01) el.playbackRate = speed;
          if (el.paused) void el.play().catch(() => undefined);
          if (Math.abs(el.currentTime - want) > 0.35) el.currentTime = want;
        } else {
          if (!el.paused) el.pause();
          if (el.readyState >= 1 && Math.abs(el.currentTime - want) > (isPlaying ? 0.06 : 0.02)) el.currentTime = want;
        }
        if (el instanceof HTMLVideoElement && el.videoWidth > 0 && el.readyState >= 1) sources.set(c.id, el);
        // ماتِ حذفِ پس‌زمینه: یک ویدیوی خاکستریِ هم‌گام (ثانیهٔ منبع − شروعِ مات)
        const meta = c.matte ? latest.current.matteMeta?.[c.matte.key] : undefined;
        if (meta && c.kind === "video") {
          keepMatte.add(c.id);
          let me = matteEls.current.get(c.id);
          if (!me || me.url !== meta.url) {
            if (me) { me.el.removeAttribute("src"); me.el.load(); }
            const mel = document.createElement("video");
            mel.preload = "auto";
            mel.muted = true;
            mel.playsInline = true;
            for (const ev of ["seeked", "loadeddata"]) mel.addEventListener(ev, () => requestRender());
            mel.src = meta.url;
            me = { el: mel, url: meta.url };
            matteEls.current.set(c.id, me);
          }
          const mt = Math.max(0, want - meta.s0);
          if (me.el.readyState >= 1 && Math.abs(me.el.currentTime - mt) > 0.05) me.el.currentTime = mt;
          if (me.el.readyState >= 2 && me.el.videoWidth > 0) mattes.set(c.id, me.el);
        }
      }
    }
    for (const id of [...elements.current.keys()]) if (!keep.has(id)) releaseElement(id);
    for (const [id, m] of [...matteEls.current]) {
      if (!keepMatte.has(id)) { m.el.removeAttribute("src"); m.el.load(); matteEls.current.delete(id); }
    }
    matteNow.current = mattes;
    return sources;
  }, [ensureElement, releaseElement]);

  const draw = useCallback((t: number, isPlaying: boolean, r: number) => {
    const comp = compositor.current;
    if (!comp) return;
    const sources = syncMedia(t, isPlaying, r);
    const L = latest.current;
    comp.render({ project: L.project, time: t, sources, looks: L.looks, compare: L.compare, luts: L.luts, mattes: matteNow.current });
    L.engine?.sync(L.flat, t, isPlaying, L.duckSpans);
    props.onFrame?.();
  }, [props, syncMedia]);

  const requestRender = useCallback(() => {
    if (latest.current.playing || rafRender.current) return;
    rafRender.current = requestAnimationFrame(() => {
      rafRender.current = 0;
      draw(timeRef.current, false, 1);
      setFrameVersion((v) => v + 1);
    });
  }, [draw]);

  useImperativeHandle(ref, () => ({
    getFrame: () => compositor.current?.getImageData() ?? null,
    getCanvas: () => compositor.current?.canvas ?? null,
    invalidate: () => requestRender(),
  }), [requestRender]);

  // ───────── وقتی ایستاده‌ایم: با هر تغییرِ زمان/پروژه/آدرس دوباره بکش
  useEffect(() => {
    if (playing) return;
    timeRef.current = time;
    draw(time, false, 1);
    setFrameVersion((v) => v + 1);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [time, playing, project, urls, looks, compare, fw, fh, duckSpans, luts, matteMeta]);

  useEffect(() => onTextFontsReady(() => requestRender()), [requestRender]);

  // برای آزمونِ مرورگر و عیب‌یابی: وضعیتِ element های پخش
  useEffect(() => {
    Object.assign(window, {
      __nmVideoDebug: () => [...elements.current].map(([id, e]) => (e.el instanceof HTMLMediaElement
        ? { id, routed: e.routed, paused: e.el.paused, t: Math.round(e.el.currentTime * 100) / 100, muted: e.el.muted, vol: e.el.volume, ready: e.el.readyState, rate: e.el.playbackRate }
        : { id, image: true })),
    });
  }, []);

  // ───────── حلقهٔ پخش
  useEffect(() => {
    if (!playing) {
      for (const [, e] of elements.current) if (e.el instanceof HTMLMediaElement && !e.el.paused) e.el.pause();
      return;
    }
    let raf = 0;
    let last = performance.now();
    let sent = 0;
    let t = timeRef.current;
    const tick = (now: number) => {
      const dt = Math.min(0.25, (now - last) / 1000);
      last = now;
      const rr = latest.current.rate;
      t += dt * rr;
      const end = projectLength(latest.current.project);
      if ((rr > 0 && t >= end) || (rr < 0 && t <= 0)) {
        t = rr > 0 ? end : 0;
        timeRef.current = t;
        draw(t, false, 1);
        onTime(t);
        onEnded();
        return;
      }
      timeRef.current = t;
      draw(t, true, rr);
      if (now - sent > 70) {
        sent = now;
        onTime(t);
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [playing]);

  useEffect(
    () => () => {
      for (const id of [...elements.current.keys()]) releaseElement(id);
      if (rafRender.current) cancelAnimationFrame(rafRender.current);
    },
    [releaseElement],
  );

  // ───────── دستگیره‌های روی تصویر
  const sel = selection.length ? findClip(project, selection[selection.length - 1]) : null;
  const gizmo = useMemo(() => {
    if (!sel) return null;
    const c = sel.clip;
    if (c.type === "text") {
      if (time < c.at || time >= clipEnd(c)) return null;
      return { kind: "text" as const, clip: c, cx: (c.x ?? 0.5) * fw, cy: (c.y ?? (c.position === "top" ? 0.12 : c.position === "middle" ? 0.5 : 0.86)) * fh, w: fw * 0.6, h: fh * 0.08, rot: c.rotation ?? 0 };
    }
    if (sel.track.kind !== "video" || c.kind === "audio") return null;
    if (time < c.at || time >= clipEnd(c)) return null;
    const px = propAt(c, "px", time), py = propAt(c, "py", time), sc = propAt(c, "scale", time), rot = propAt(c, "rot", time);
    return { kind: "media" as const, clip: c, cx: (c.x + c.width / 2 + px) * fw, cy: (c.y + c.height / 2 + py) * fh, w: c.width * fw * sc, h: c.height * fh * sc, rot };
  }, [sel, time, fw, fh, frameVersion]);

  // ───────── «برشِ قاب»: فقط وقتی روشن است کاری می‌کند؛ حلقهٔ رسمِ برنامه دست‌نخورده می‌ماند
  const onReframe = props.onReframe;
  const selClip = sel && sel.clip.type === "media" && sel.track.kind === "video" ? sel.clip : null;
  const cropClip: MediaClip | null = selClip && selClip.kind !== "audio" && !selClip.shape && !selClip.ref.startsWith("seq:") ? selClip : null;
  const cropOk = !!onReframe && !!cropClip;
  const [cropLocal, setCropLocal] = useState(false);
  const wantCrop = props.cropMode ?? cropLocal;
  const crop = wantCrop && cropOk;
  const setCrop = useCallback((on: boolean) => {
    if (props.onCropMode) props.onCropMode(on);
    else setCropLocal(on);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [props.onCropMode]);
  const [aspect, setAspect] = useState<AspectKey>("free");
  const cropEntry = crop && cropClip ? elements.current.get(cropClip.id) : undefined;
  const cropEl: CropSource | null = cropEntry && (cropEntry.el instanceof HTMLVideoElement || cropEntry.el instanceof HTMLImageElement) ? cropEntry.el : null;
  const cropDims = crop && cropClip ? sourceSize(media[cropClip.ref], cropEl) : null;
  // قطعهٔ برش‌پذیر نیست (انتخاب عوض شد/پاک شد) ⇒ حالتِ برش بسته شود
  useEffect(() => {
    if (wantCrop && !cropOk) setCrop(false);
  }, [wantCrop, cropOk, setCrop]);
  // ورود: پخش بایستد و سرِ پخش روی خودِ قطعه باشد (منبعِ آن همان‌جا بارگیری و هم‌گام می‌شود)
  useEffect(() => {
    if (!crop || !cropClip) return;
    if (latest.current.playing) onPlay();
    const t = latest.current.time;
    if (t < cropClip.at || t >= clipEnd(cropClip)) onSeek(cropClip.at);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [crop, cropClip?.id]);
  // نسبتِ پیش‌فرضِ چیپ‌ها از روی برشِ موجودِ قطعه
  useEffect(() => {
    if (!crop || !cropClip) return;
    setAspect(detectAspect(cropClip.reframe, cropDims ? cropDims[0] / cropDims[1] : 0, ar));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [crop, cropClip?.id, !!cropDims]);

  const drag = useRef<null | { mode: "move" | "scale" | "rot"; sx: number; sy: number; c0: AnyClip; cx: number; cy: number; d0: number; a0: number }>(null);

  const patchFor = (c: AnyClip, mode: "move" | "scale" | "rot", x: number, y: number, st: NonNullable<typeof drag.current>): Partial<MediaClip> | Partial<TextClip> => {
    const rel = time - c.at;
    if (c.type === "text") {
      if (mode === "move" && c.follow) {
        const f0 = (st.c0 as TextClip).follow ?? c.follow;
        return { follow: { ...f0, bx: f0.bx + (x - st.sx) / fw, by: f0.by + (y - st.sy) / fh } };
      }
      if (mode === "move") return { x: Math.max(0, Math.min(1, (st.cx + x - st.sx) / fw)), y: Math.max(0, Math.min(1, (st.cy + y - st.sy) / fh)) };
      if (mode === "scale") return { scale: Math.max(0.1, Math.min(4, (c.scale ?? 1) * 1)) };
      return { rotation: Math.round(Math.atan2(y - st.cy, x - st.cx) * (180 / Math.PI) + 90) };
    }
    const m = c as MediaClip;
    const kf = m.kf ?? {};
    if (mode === "move" && m.follow) {
      const f0 = (st.c0 as MediaClip).follow ?? m.follow;
      return { follow: { ...f0, bx: f0.bx + (x - st.sx) / fw, by: f0.by + (y - st.sy) / fh } };
    }
    if (mode === "move") {
      const dx = (x - st.sx) / fw, dy = (y - st.sy) / fh;
      const bx = propAt(st.c0 as MediaClip, "px", time) + dx, by = propAt(st.c0 as MediaClip, "py", time) + dy;
      const hasX = !!kf.px?.length, hasY = !!kf.py?.length;
      return {
        ...(hasX || hasY ? { kf: { ...kf, px: hasX ? setKey(kf.px, rel, bx, "px") : kf.px, py: hasY ? setKey(kf.py, rel, by, "py") : kf.py } } : {}),
        ...(hasX ? {} : { px: bx }), ...(hasY ? {} : { py: by }),
      };
    }
    if (mode === "scale") {
      const d = Math.hypot(x - st.cx, y - st.cy);
      const s = Math.max(0.05, Math.min(8, propAt(st.c0 as MediaClip, "scale", time) * (d / Math.max(4, st.d0))));
      return kf.scale?.length ? { kf: { ...kf, scale: setKey(kf.scale, rel, s, "scale") } } : { scale: Math.round(s * 1000) / 1000 };
    }
    const a = Math.round(Math.atan2(y - st.cy, x - st.cx) * (180 / Math.PI) + 90);
    return kf.rot?.length ? { kf: { ...kf, rot: setKey(kf.rot, rel, a, "rot") } } : { rot: a };
  };

  const begin = (e: React.PointerEvent, mode: "move" | "scale" | "rot") => {
    if (!gizmo) return;
    e.stopPropagation();
    e.preventDefault();
    const box = holder.current!.getBoundingClientRect();
    const x = e.clientX - box.left, y = e.clientY - box.top;
    drag.current = { mode, sx: x, sy: y, c0: gizmo.clip, cx: gizmo.cx, cy: gizmo.cy, d0: Math.hypot(x - gizmo.cx, y - gizmo.cy), a0: 0 };
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
  };
  const move = (e: React.PointerEvent) => {
    const st = drag.current;
    if (!st) return;
    const box = holder.current!.getBoundingClientRect();
    onGizmo(st.c0.id, patchFor(st.c0, st.mode, e.clientX - box.left, e.clientY - box.top, st), false);
  };
  const end = (e: React.PointerEvent) => {
    const st = drag.current;
    if (!st) return;
    drag.current = null;
    const box = holder.current!.getBoundingClientRect();
    onGizmo(st.c0.id, patchFor(st.c0, st.mode, e.clientX - box.left, e.clientY - box.top, st), true);
  };

  return (
    <div className="vw-monitor" data-testid="monitor">
      <div className="vw-stage" ref={stage}>
        <div className="vw-frame" ref={holder} style={{ width: fw, height: fh }} data-testid="program-frame">
          {safeShown !== SAFE_OFF && !crop && <SafeZoneLayer zoneKey={safeShown} zone={zoneByKey(zones, safeShown)} />}
          {total === 0 && (
            <div className="grid h-full w-full place-items-center px-4 text-center text-xs" style={{ color: "var(--text-3)", position: "absolute", inset: 0 }}>
              ویدیو یا عکسی را از «رسانه‌ها» بکشید روی تایم‌لاین
            </div>
          )}
          {gizmo && !playing && !props.overlay && !crop && (
            <div
              className="vw-gizmo" data-testid="gizmo"
              style={{ left: gizmo.cx - gizmo.w / 2, top: gizmo.cy - gizmo.h / 2, width: gizmo.w, height: gizmo.h, transform: `rotate(${gizmo.rot}deg)` }}
              onPointerDown={(e) => begin(e, "move")} onPointerMove={move} onPointerUp={end}
            >
              {gizmo.kind === "media" && (
                <>
                  <i className="h tl" data-handle="scale" onPointerDown={(e) => begin(e, "scale")} onPointerMove={move} onPointerUp={end} />
                  <i className="h tr" data-handle="scale" onPointerDown={(e) => begin(e, "scale")} onPointerMove={move} onPointerUp={end} />
                  <i className="h bl" data-handle="scale" onPointerDown={(e) => begin(e, "scale")} onPointerMove={move} onPointerUp={end} />
                  <i className="h br" data-handle="scale" onPointerDown={(e) => begin(e, "scale")} onPointerMove={move} onPointerUp={end} />
                </>
              )}
              <i className="h rot" data-handle="rot" onPointerDown={(e) => begin(e, "rot")} onPointerMove={move} onPointerUp={end} />
            </div>
          )}
          {props.pickOverlay}
          {crop && cropClip && onReframe && (
            <CropOverlay
              clip={cropClip} time={time} playing={playing} frameW={fw} frameH={fh} dims={cropDims} el={cropEl} version={frameVersion}
              aspect={aspect} frameAspect={ar} onReframe={onReframe} onSeekClip={() => onSeek(cropClip.at)} onClose={() => setCrop(false)}
            />
          )}
          {props.overlay}
        </div>
      </div>
      {crop && cropClip && onReframe && (() => {
        const panel = (
          <CropPanel
            storeId={props.storeId} clip={cropClip} time={time} dims={cropDims} aspect={aspect} frameAspect={ar}
            onAspect={setAspect} onReframe={onReframe} onClose={() => setCrop(false)}
          />
        );
        // صفحهٔ پهن: پنل در ستونِ بازرس (جای کافی دارد)؛ صفحهٔ باریک: زیرِ مانیتور
        const host = typeof window !== "undefined" && window.matchMedia("(min-width: 1001px)").matches ? document.getElementById("vw-crop-host") : null;
        return host ? createPortal(panel, host) : panel;
      })()}
      <div className="vw-transport" dir="rtl">
        <button type="button" className="ws-btn" onClick={() => onSeek(0)} title="ابتدا (Home)" aria-label="ابتدا"><Icon name="back" size={14} /></button>
        <button type="button" className="ws-btn" onClick={() => onStep(-1)} title="یک فریم عقب (←)" data-testid="vw-prev-frame">−۱ فریم</button>
        <button type="button" className="ws-btn primary" onClick={onPlay} title="پخش / توقف (Space یا K)" data-testid="vw-play" aria-pressed={playing}>
          <Icon name="play" size={14} /> {playing ? "توقف" : "پخش"}
        </button>
        <button type="button" className="ws-btn" onClick={() => onStep(1)} title="یک فریم جلو (→)" data-testid="vw-next-frame">+۱ فریم</button>
        <button type="button" className="ws-btn" onClick={() => onSeek(total)} title="انتها (End)" aria-label="انتها"><Icon name="next" size={14} /></button>
        <button type="button" className="ws-btn" onClick={() => onRate(rate < 0 ? 1 : -1)} title="عقب‌رفتن (J)" data-testid="vw-rev">◀ J</button>
        <button type="button" className="ws-btn" onClick={() => onRate(rate >= 1 && rate < 4 ? rate * 2 : 1)} title="جلورفتنِ سریع‌تر (L)" data-testid="vw-fwd">L ▶</button>
        <span className="ws-muted" dir="ltr">{Math.abs(rate) !== 1 ? `${rate}×` : ""}</span>
        <span className="vw-time" data-testid="vw-time">{timecode(time, project.format.fps)} / {timecode(total, project.format.fps)}</span>
        <span className="ws-spacer" />
        {props.badge}
        <button
          type="button" className={`ws-btn ${crop ? "is-on" : ""}`} onClick={() => setCrop(!crop)} disabled={!cropOk} aria-pressed={crop} data-testid="crop-toggle"
          title={cropOk ? "برشِ قاب: روی خودِ تصویر انتخاب کنید کدام بخشِ آن دیده شود (کیفیت از فایلِ اصلی می‌آید)" : "برای برشِ قاب یک قطعهٔ تصویر یا عکس را روی ترکِ تصویر انتخاب کنید"}
        >
          برشِ قاب
        </button>
        <label className="vw-safe-wrap" title="ناحیه‌ای از قاب که رابطِ برنامه (نام، دکمه‌ها، توضیح) می‌پوشاند؛ زیرنویس و لوگو را بیرونِ نوارهای قرمز بگذارید">
          <span>حاشیهٔ امن</span>
          <select className="u-input vw-safe" value={safeShown} onChange={(e) => pickZone(e.target.value)} data-testid="safezone-select" aria-label="حاشیهٔ امن">
            <option value={SAFE_OFF}>خاموش</option>
            <option value={SAFE_GENERAL}>عمومی</option>
            {zones.map((z) => <option key={z.key} value={z.key}>{z.title}</option>)}
          </select>
        </label>
        {props.extraTransport}
        {props.selectedProxyHint}
      </div>
      {props.footer}
    </div>
  );
});

export default Monitor;
export { clipLength };
