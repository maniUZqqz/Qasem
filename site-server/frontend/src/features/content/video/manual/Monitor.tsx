import { useEffect, useRef, useState } from "react";

import { api } from "../../../../api/client";
import Icon from "../../../../components/Icon";
import type { MediaItem } from "../api";
import { AnyClip, MediaClip, Project, TextClip, clipEnd, clipLength, timecode } from "./model";

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

/** تقریبِ پیش‌نمایشیِ افکت‌های یک قطعه با CSS (خروجیِ دقیق از ffmpeg روی سرور می‌آید) */
function cssFilter(effects: MediaClip["effects"]): string {
  const f: string[] = [];
  for (const e of effects) {
    const a = Number(e.params.amount ?? 0);
    if (e.tool === "brightness") f.push(`brightness(${1 + a * 1.4})`);
    else if (e.tool === "contrast") f.push(`contrast(${a || 1})`);
    else if (e.tool === "saturation") f.push(`saturate(${a || 1})`);
    else if (e.tool === "white_balance") {
      const t = Number(e.params.temperature ?? 0);
      f.push(t >= 0 ? `sepia(${Math.min(1, t * 2)}) saturate(1.1)` : `hue-rotate(${t * 60}deg) saturate(1.05)`);
    } else if (e.tool === "sharpen") f.push(`contrast(${1 + Number(e.params.amount ?? 0) * 0.08})`);
  }
  return f.join(" ") || "none";
}

function alphaAt(c: MediaClip, t: number): number {
  let a = c.opacity;
  const len = clipLength(c);
  if (c.fade_in > 0) a *= Math.min(1, Math.max(0, (t - c.at) / c.fade_in));
  if (c.fade_out > 0) a *= Math.min(1, Math.max(0, (clipEnd(c) - t) / c.fade_out));
  if (c.transition) {
    const d = c.transition.duration / (c.transition.kind === "crossfade" ? 1 : 2);
    a *= Math.min(1, Math.max(0, (t - c.at) / Math.min(d, len)));
  }
  return a;
}

function MediaLayer({
  clip, url, time, playing, rate, muted,
}: { clip: MediaClip; url: string | undefined; time: number; playing: boolean; rate: number; muted: boolean }) {
  const ref = useRef<HTMLVideoElement>(null);
  const end = clipEnd(clip);
  const active = time >= clip.at && time < end;
  useEffect(() => {
    const v = ref.current;
    if (!v || clip.kind === "image") return;
    const expected = clip.start + Math.max(0, time - clip.at) * clip.speed;
    v.muted = muted || !clip.audio_on || !active;
    v.volume = Math.max(0, Math.min(1, clip.volume));
    if (active) {
      v.playbackRate = Math.max(0.0625, Math.min(16, clip.speed * Math.abs(rate || 1)));
      if (playing && rate > 0) {
        if (v.paused) void v.play().catch(() => undefined);
        if (Math.abs(v.currentTime - expected) > 0.45) v.currentTime = expected;
      } else {
        if (!v.paused) v.pause();
        if (Math.abs(v.currentTime - expected) > 0.04) v.currentTime = expected;
      }
    } else {
      if (!v.paused) v.pause();
      if (Math.abs(v.currentTime - clip.start) > 0.2) v.currentTime = clip.start;
    }
  });
  const rotate = clip.effects.find((e) => e.tool === "rotate");
  const vignette = clip.effects.find((e) => e.tool === "vignette");
  const blurs = clip.effects.filter((e) => e.tool === "blur_region");
  const fit = clip.fit === "stretch" ? "fill" : clip.fit;
  return (
    <div
      className="vw-layer" data-clip={clip.id} data-active={active ? "1" : "0"}
      style={{
        left: `${clip.x * 100}%`, top: `${clip.y * 100}%`, width: `${clip.width * 100}%`, height: `${clip.height * 100}%`,
        opacity: active ? alphaAt(clip, time) : 0, pointerEvents: "none",
      }}
    >
      {clip.kind === "image" ? (
        url ? <img src={url} alt="" style={{ objectFit: fit, filter: cssFilter(clip.effects) }} /> : null
      ) : (
        url ? (
          <video
            ref={ref} src={url} preload="auto" playsInline
            style={{ objectFit: fit, filter: cssFilter(clip.effects), transform: rotate ? `rotate(${rotate.params.degrees}deg)` : undefined }}
          />
        ) : null
      )}
      {vignette && (
        <i style={{ position: "absolute", inset: 0, background: `radial-gradient(ellipse at center, transparent ${60 - Number(vignette.params.strength ?? 0.4) * 30}%, rgba(0,0,0,${0.35 + Number(vignette.params.strength ?? 0.4) * 0.6}) 100%)` }} />
      )}
      {blurs.map((b, i) => (
        <i key={i} style={{ position: "absolute", left: `${Number(b.params.x)}%`, top: `${Number(b.params.y)}%`, width: `${Number(b.params.width)}%`, height: `${Number(b.params.height)}%`, backdropFilter: `blur(${6 + Number(b.params.strength ?? 6) * 2}px)` }} />
      ))}
    </div>
  );
}

function AudioLayer({ clip, url, time, playing, rate, muted }: { clip: MediaClip; url: string | undefined; time: number; playing: boolean; rate: number; muted: boolean }) {
  const ref = useRef<HTMLMediaElement>(null);
  const active = time >= clip.at && time < clipEnd(clip);
  useEffect(() => {
    const v = ref.current;
    if (!v) return;
    const expected = clip.start + Math.max(0, time - clip.at) * clip.speed;
    v.muted = muted || !active;
    v.volume = Math.max(0, Math.min(1, clip.volume * clip.opacity));
    if (active && playing && rate > 0) {
      v.playbackRate = Math.max(0.0625, Math.min(16, clip.speed * rate));
      if (v.paused) void v.play().catch(() => undefined);
      if (Math.abs(v.currentTime - expected) > 0.45) v.currentTime = expected;
    } else if (!v.paused) v.pause();
  });
  return url ? <audio ref={ref} src={url} preload="auto" /> : null;
}

function TextLayer({ clip, time }: { clip: TextClip; time: number }) {
  if (time < clip.at || time >= clipEnd(clip)) return null;
  const pos = clip.position === "top" ? { top: "8%" } : clip.position === "middle" ? { top: "50%", transform: "translateY(-50%)" } : { bottom: "8%" };
  return (
    <div className="vw-text" data-text={clip.id} style={{ ...pos, fontSize: `${clip.size}cqh`, color: clip.color, opacity: clip.opacity }}>
      <span style={{ background: clip.box ? "rgba(0,0,0,.45)" : "transparent" }}>{clip.text}</span>
    </div>
  );
}

export default function Monitor({
  project, media, time, playing, rate, onSeek, onPlay, onStep, onRate, selectedProxyHint,
}: {
  project: Project;
  media: Record<string, MediaItem>;
  time: number;
  playing: boolean;
  rate: number;
  onSeek: (t: number) => void;
  onPlay: () => void;
  onStep: (frames: number) => void;
  onRate: (r: number) => void;
  selectedProxyHint?: React.ReactNode;
}) {
  const stage = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ w: 320, h: 400 });
  const [safe, setSafe] = useState(false);
  const refs = Array.from(new Set(project.tracks.flatMap((t) => t.clips.filter((c): c is MediaClip => c.type === "media").map((c) => c.ref))));
  const urls = useMediaUrls(media, refs);

  useEffect(() => {
    const el = stage.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setSize({ w: el.clientWidth - 16, h: el.clientHeight - 16 }));
    ro.observe(el);
    setSize({ w: el.clientWidth - 16, h: el.clientHeight - 16 });
    return () => ro.disconnect();
  }, []);

  const ar = project.format.width / project.format.height;
  const fw = Math.max(60, Math.min(size.w, size.h * ar));
  const fh = fw / ar;
  const fps = project.format.fps;
  const total = Math.max(0, ...project.tracks.flatMap((t) => t.clips.map(clipEnd)));

  // قطعه‌های نزدیک (فعال یا تا ۴ ثانیهٔ دیگر) برای پیش‌بارگذاری
  const near = (c: AnyClip) => time >= c.at - 4 && time < clipEnd(c) + 0.5;

  return (
    <div className="vw-monitor" data-testid="monitor">
      <div className="vw-stage" ref={stage}>
        <div className="vw-frame" style={{ width: fw, height: fh }} data-testid="program-frame">
          {project.tracks.map((t) => {
            if (t.kind === "video") {
              return t.clips.filter((c): c is MediaClip => c.type === "media" && near(c)).map((c) => (
                <MediaLayer key={c.id} clip={c} url={urls[c.ref]} time={time} playing={playing} rate={rate} muted={t.muted} />
              ));
            }
            if (t.kind === "audio") {
              return t.clips.filter((c): c is MediaClip => c.type === "media" && near(c)).map((c) => (
                <AudioLayer key={c.id} clip={c} url={urls[c.ref]} time={time} playing={playing} rate={rate} muted={t.muted} />
              ));
            }
            return t.clips.filter((c): c is TextClip => c.type === "text").map((c) => <TextLayer key={c.id} clip={c} time={time} />);
          })}
          {safe && (
            <>
              <i style={{ position: "absolute", inset: "5%", border: "1px dashed rgba(255,255,255,.55)", pointerEvents: "none" }} />
              <i style={{ position: "absolute", inset: "10%", border: "1px dashed rgba(255,255,255,.35)", pointerEvents: "none" }} />
            </>
          )}
          {total === 0 && (
            <div className="grid h-full w-full place-items-center px-4 text-center text-xs" style={{ color: "var(--text-3)" }}>
              ویدیو یا عکسی را از «رسانه‌ها» بکشید روی تایم‌لاین
            </div>
          )}
        </div>
      </div>
      <div className="vw-transport" dir="rtl">
        <button type="button" className="ws-btn" onClick={() => onSeek(0)} title="ابتدا (Home)" aria-label="ابتدا"><Icon name="back" size={14} /></button>
        <button type="button" className="ws-btn" onClick={() => onStep(-1)} title="یک فریم عقب (←)" data-testid="vw-prev-frame">−۱ فریم</button>
        <button type="button" className={`ws-btn primary`} onClick={onPlay} title="پخش / توقف (Space یا K)" data-testid="vw-play" aria-pressed={playing}>
          <Icon name="play" size={14} /> {playing ? "توقف" : "پخش"}
        </button>
        <button type="button" className="ws-btn" onClick={() => onStep(1)} title="یک فریم جلو (→)" data-testid="vw-next-frame">+۱ فریم</button>
        <button type="button" className="ws-btn" onClick={() => onSeek(total)} title="انتها (End)" aria-label="انتها"><Icon name="next" size={14} /></button>
        <button type="button" className="ws-btn" onClick={() => onRate(rate < 0 ? 1 : -1)} title="عقب‌رفتن (J)" data-testid="vw-rev">◀ J</button>
        <button type="button" className="ws-btn" onClick={() => onRate(rate >= 1 && rate < 4 ? rate * 2 : 1)} title="جلورفتنِ سریع‌تر (L)" data-testid="vw-fwd">L ▶</button>
        <span className="ws-muted" dir="ltr">{Math.abs(rate) !== 1 ? `${rate}×` : ""}</span>
        <span className="vw-time" data-testid="vw-time">{timecode(time, fps)} / {timecode(total, fps)}</span>
        <span className="ws-spacer" />
        <label className="ws-check"><input type="checkbox" checked={safe} onChange={(e) => setSafe(e.target.checked)} /> حاشیهٔ امن</label>
        {selectedProxyHint}
      </div>
    </div>
  );
}
