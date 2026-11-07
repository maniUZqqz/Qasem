import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { fa } from "../../../../components/ui";
import type { MediaItem } from "../api";
import FadeHandles from "./FadeHandles";
import { KF_TITLE, KfChannel } from "./keyframes";
import { useFilmstrip, useWaveform } from "./mediaAnalysis";
import {
  AnyClip, MediaClip, Project, Track, cloneInPlace, clipEnd, clipLength, findClip, framesBetween, moveClips, projectLength, quantize, rateStretch, rollEdit, rippleTrim,
  slideClip, slipClip, snap, snapPoints, srcTimeAt, tidyFrame, timecode, touchingPair, trimEnd, trimStart, withLinked, isMedia,
} from "./model";
import TrimPreview, { FrameAt } from "./TrimPreview";
import VolumeLine, { ClipActs } from "./VolumeLine";
import "./timeline.css";

export type Tool = "select" | "razor" | "ripple" | "roll" | "slip" | "slide" | "rate" | "trackfwd";

export const ROW = 52;
const LANE = 22;
const STEPS = [0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600];

type Drag =
  | { kind: "move"; ids: string[]; primary: string; sx: number; sy: number; orig: Project; at0: number; end0: number; moved: boolean; trackId: string }
  | { kind: "edge"; side: "l" | "r"; id: string; sx: number; orig: Project; at0: number; end0: number; moved: boolean; tool: Tool; solo: boolean }
  | { kind: "tool"; tool: "slip" | "slide"; id: string; sx: number; orig: Project; moved: boolean }
  | { kind: "trans"; id: string; sx: number; orig: Project; moved: boolean; cut: number }
  | { kind: "key"; id: string; ch: KfChannel; idx: number; sx: number; orig: Project; moved: boolean }
  | { kind: "marker"; id: string; sx: number; orig: Project; moved: boolean; t0: number }
  | { kind: "band"; sx: number; sy: number; x: number; y: number; additive: boolean; base: string[] };

const lanesOf = (c: MediaClip | undefined): { ch: KfChannel; keys: { t: number; v: number; e: string }[] }[] =>
  c ? (Object.keys(c.kf ?? {}) as KfChannel[]).filter((ch) => (c.kf?.[ch]?.length ?? 0) > 0).map((ch) => ({ ch, keys: c.kf![ch]! })) : [];

/** مشخصاتِ اشاره‌گر (و کلیدهای تغییردهنده) برای کشیدن؛ هم از pointermove می‌آید هم از تغییرِ Ctrl/Shift/Alt وسطِ کشیدن */
type Ptr = { clientX: number; clientY: number; ctrlKey: boolean; metaKey: boolean; shiftKey: boolean; altKey: boolean };
const ptrOf = (e: PointerEvent): Ptr => ({ clientX: e.clientX, clientY: e.clientY, ctrlKey: e.ctrlKey, metaKey: e.metaKey, shiftKey: e.shiftKey, altKey: e.altKey });

/** چیزی که هنگامِ کشیدنِ لبه/قطعه نزدیکِ اشاره‌گر نشان داده می‌شود: متنِ راهنما + دو فریمِ پیش‌نمایشِ برش */
type TrimUi = { x: number; y: number; top: number; text: string; out: FrameAt | null; inn: FrameAt | null };

const signedFrames = (n: number): string => (n === 0 ? "۰ فریم" : `${n > 0 ? "+" : "−"}${fa(Math.abs(n))} فریم`);

/** فریم‌هایی که دو سوی برش دیده می‌شوند: آخرین فریمِ سمتِ چپ و اولین فریمِ سمتِ راست؛ همسایه فقط اگر به لبه چسبیده باشد */
function previewFrames(p: Project, id: string, side: "l" | "r", fps: number): { out: FrameAt | null; inn: FrameAt | null } {
  const f = findClip(p, id);
  if (!f) return { out: null, inn: null };
  const cands = [id, ...withLinked(p, [id]).filter((x) => x !== id)].map((x) => findClip(p, x)).filter((x): x is NonNullable<typeof x> => !!x);
  const subj = cands.find((x) => isMedia(x.clip) && x.clip.kind !== "audio" && x.track.kind !== "audio");
  if (!subj || !isMedia(subj.clip)) return { out: null, inn: null };
  const s = subj.clip;
  const eps = 1 / (fps > 0 ? fps : 30);
  const lastOf = (c: MediaClip): FrameAt => ({ ref: c.ref, t: srcTimeAt(c, Math.max(c.at, clipEnd(c) - eps)) });
  const firstOf = (c: MediaClip): FrameAt => ({ ref: c.ref, t: srcTimeAt(c, c.at) });
  const others = subj.track.clips.filter((x): x is MediaClip => x.id !== s.id && isMedia(x) && x.kind !== "audio");
  if (side === "l") {
    const prev = others.find((x) => Math.abs(clipEnd(x) - s.at) < 0.06);
    return { out: prev ? lastOf(prev) : null, inn: firstOf(s) };
  }
  const nxt = others.find((x) => Math.abs(x.at - clipEnd(s)) < 0.06);
  return { out: lastOf(s), inn: nxt ? firstOf(nxt) : null };
}

// ─────────────────────────────────────────────────────────── موج و نوارِ تصویر
function Wave({ peaks, perSecond, clip, px, width, height }: { peaks: number[]; perSecond: number; clip: MediaClip; px: number; width: number; height: number }) {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const cv = ref.current;
    if (!cv || peaks.length === 0) return;
    const W = Math.max(2, Math.min(3000, Math.round(width)));
    cv.width = W;
    cv.height = height;
    const x = cv.getContext("2d")!;
    x.clearRect(0, 0, W, height);
    x.fillStyle = "rgba(255,255,255,.75)";
    const mid = height / 2;
    const k = W / Math.max(1, width);
    for (let i = 0; i < W; i++) {
      const tl = clip.at + (i / k) / px;
      const a = srcTimeAt(clip, tl);
      const b = srcTimeAt(clip, clip.at + ((i + 1) / k) / px);
      const lo = Math.floor(Math.min(a, b) * perSecond);
      const hi = Math.max(lo, Math.ceil(Math.max(a, b) * perSecond));
      let m = 0;
      for (let j = lo; j <= hi && j < peaks.length; j++) m = Math.max(m, peaks[j] ?? 0);
      const h = Math.max(1, Math.min(1, m * Math.min(3, clip.volume)) * (height - 4));
      x.fillRect(i, mid - h / 2, 1, h);
    }
  }, [peaks, perSecond, clip.at, clip.start, clip.end, clip.speed, clip.volume, clip.ramp, clip.reverse, px, width, height]);
  return <canvas ref={ref} className="tl-wave" style={{ width, height }} />;
}

function Film({ sprite, clip, px, width, height }: { sprite: { url: string; count: number; interval: number; w: number; h: number }; clip: MediaClip; px: number; width: number; height: number }) {
  const tileW = Math.max(24, Math.round((sprite.w / sprite.h) * height));
  const n = Math.min(80, Math.ceil(width / tileW));
  const sizeW = tileW * sprite.count;
  const tiles = [];
  for (let i = 0; i < n; i++) {
    const t = srcTimeAt(clip, clip.at + ((i + 0.5) * tileW) / px);
    const idx = Math.max(0, Math.min(sprite.count - 1, Math.floor(t / sprite.interval)));
    tiles.push(<i key={i} style={{ left: i * tileW, width: tileW, backgroundImage: `url(${sprite.url})`, backgroundSize: `${sizeW}px ${height}px`, backgroundPosition: `-${idx * tileW}px 0` }} />);
  }
  return <div className="tl-film" style={{ height }}>{tiles}</div>;
}

// ─────────────────────────────────────────────────────────── یک قطعه
type ClipProps = {
  clip: AnyClip;
  track: Track;
  selected: boolean;
  primary: boolean;
  px: number;
  tool: Tool;
  storeId: string;
  item: MediaItem | undefined;
  visible: boolean;
  dragging: boolean;
  linked: boolean;
  /** لبه‌ای از این قطعه که همین الان بریده می‌شود */
  trim: "l" | "r" | null;
  fps: number;
  /** «خط بلندی» برای قطعه‌های انتخاب‌نشده هم نشان داده شود */
  volLine: boolean;
  acts: ClipActs;
  onDown: (e: React.PointerEvent, c: AnyClip, t: Track, mode: "move" | "l" | "r") => void;
};

const ClipView = memo(function ClipView({ clip: c, track: t, selected, primary, px, tool, storeId, item, visible, dragging, linked, trim, fps, volLine, acts, onDown }: ClipProps) {
  const w = Math.max(6, (clipEnd(c) - c.at) * px);
  const isAudio = c.type === "media" && (c.kind === "audio" || t.kind === "audio");
  const hasSound = c.type === "media" && (isAudio || (c.has_audio && c.audio_on));
  const wide = w > 28 && visible;
  // شکل‌ها و توالی‌های تودرتو فایلِ تحلیل‌پذیر ندارند
  const analyzable = c.type === "media" && c.ref !== "shape" && !c.ref.startsWith("seq:");
  const wave = useWaveform(storeId, analyzable && hasSound && wide ? c.ref : null);
  const film = useFilmstrip(storeId, analyzable && c.type === "media" && c.kind === "video" && !isAudio && wide && w > 60 ? c.ref : null);
  const kindClass = c.type === "text" ? ((c as { caption?: boolean }).caption ? "kind-caption" : "kind-text") : isAudio ? "kind-audio" : c.kind === "image" ? "kind-image" : "";
  const label = c.type === "text" ? c.text : c.label;
  const inner = ROW - 8;
  // خطِ بلندی و محو فقط روی قطعه‌های رسانه‌ای؛ کشیدنشان فقط وقتی قطعه انتخاب است و ابزار «انتخاب» و ترک قفل نیست
  const media = c.type === "media" ? c : null;
  const canEdit = selected && tool === "select" && !t.locked;
  // انتخاب‌شده ⇒ همیشه؛ وگرنه با کلیدِ «خط بلندی»: روی ترکِ صدا همیشه، روی قطعهٔ تصویر فقط اگر بلندی‌اش دست خورده (تا نوارِ تصویر شلوغ نشود)
  const volEdited = !!media && (media.volume !== 1 || (media.kf?.volume?.length ?? 0) > 0);
  const showVol = !!media && hasSound && (selected || (volLine && (isAudio || volEdited)));
  return (
    <div
      className={`tl-clip ${kindClass} ${selected ? "is-sel" : ""} ${primary ? "is-primary" : ""} ${dragging ? "is-drag" : ""} ${trim ? "is-trim" : ""} tool-${tool}`}
      data-clip={c.id} data-clip-kind={c.type === "text" ? "text" : c.kind} data-trim={trim ?? undefined}
      style={{ left: c.at * px, width: w, opacity: t.muted ? 0.5 : 1 }}
      title={c.type === "text" ? c.text : `${c.label} — ${timecode(c.at, fps)}`}
      onPointerDown={(e) => onDown(e, c, t, "move")}
    >
      {film && c.type === "media" && <Film sprite={film} clip={c} px={px} width={w} height={inner} />}
      {wave && wave.peaks.length > 0 && c.type === "media" && <Wave peaks={wave.peaks} perSecond={wave.per_second} clip={c} px={px} width={w} height={inner} />}
      {media && wide && <FadeHandles clip={media} w={w} h={inner} px={px} handles={canEdit && w > 48} acts={acts} />}
      {media && wide && showVol && (
        <VolumeLine clip={media} w={w} h={inner} px={px} fps={fps} strong={selected} interactive={canEdit && w > 24} acts={acts} />
      )}
      <i className="grip l" onPointerDown={(e) => onDown(e, c, t, "l")} data-grip="l" />
      <span className="tl-label">
        {linked && <b className="tl-link" title="صدا و تصویر پیوسته‌اند">⛓</b>}
        {c.type === "media" && c.ref.startsWith("seq:") ? "▣ " : c.type === "media" && c.shape ? "◇ " : ""}
        {label}
        {c.type === "media" && (c.ramp?.length ?? 0) >= 2 ? " ⏱" : ""}
        {c.type === "media" && c.speed !== 1 && !(c.ramp?.length) ? ` ×${fa(c.speed)}` : ""}
        {c.type === "media" && c.reverse ? " ⇄" : ""}
        {c.type === "media" && c.freeze ? " ❄" : ""}
      </span>
      {c.type === "media" && c.kf && Object.values(c.kf).some((k) => k && k.length) && <b className="tl-kfmark" title="کلیدفریم دارد">◆</b>}
      <i className="grip r" onPointerDown={(e) => onDown(e, c, t, "r")} data-grip="r" />
    </div>
  );
});

// ─────────────────────────────────────────────────────────── تایم‌لاین
type Props = {
  project: Project;
  selection: string[];
  playhead: number;
  px: number;
  snapOn: boolean;
  tool: Tool;
  storeId: string;
  media: Record<string, MediaItem>;
  fps: number;
  /** `base` = پروژهٔ پیش از شروعِ کشیدن؛ برای ریپلِ خودکار هنگامِ تغییرِ سرعت با ابزارِ «سرعت» (نتیجه از همان پایه ساخته می‌شود) */
  onProject: (p: Project, live: boolean, base?: Project) => void;
  onCommit: (label: string) => void;
  onSelect: (ids: string[]) => void;
  onSeek: (t: number) => void;
  onDropRef: (trackId: string, ref: string, at: number) => void;
  onTrack: (id: string, patch: Partial<Track>) => void;
  onRemoveTrack: (id: string) => void;
  onRazor: (id: string, t: number) => void;
  onTrackForward: (t: number) => void;
  onMarkerClick: (id: string, alt: boolean) => void;
  onInOut: (a: number, b: number) => void;
  onKeyPick: (id: string, ch: KfChannel, t: number) => void;
  /** «خط بلندی» برای قطعه‌های انتخاب‌نشده هم نشان داده شود (پیش‌فرض: بله) */
  volLine?: boolean;
};

export default function TimelineView(props: Props) {
  const { project, selection, playhead, px, snapOn, tool, storeId, media, onProject, onCommit, onSelect, onSeek, onDropRef, onTrack, onRemoveTrack } = props;
  const scroller = useRef<HTMLDivElement>(null);
  const rows = useRef<HTMLDivElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const [drag, setDrag] = useState<Drag | null>(null);
  const [dropTrack, setDropTrack] = useState<string | null>(null);
  const [snapAt, setSnapAt] = useState<number | null>(null);
  const [view, setView] = useState({ lo: 0, hi: 40 });
  const [hint, setHint] = useState<string | null>(null);
  const [trimUi, setTrimUi] = useState<TrimUi | null>(null);
  const lastPtr = useRef<Ptr | null>(null);
  const fps = props.fps || 30;
  const volLine = props.volLine ?? true;
  const length = Math.max(30, projectLength(project) + 12);
  const width = length * px;
  const projRef = useRef(project);
  projRef.current = project;
  const selSet = useMemo(() => new Set(selection), [selection]);
  const primaryId = selection[selection.length - 1] ?? null;
  // کارهای پایدارِ قطعه‌ها (خطِ بلندی/محو): همیشه آخرین props را می‌بینند ولی هویتشان عوض نمی‌شود تا memo ِ قطعه‌ها بماند
  const latest = useRef({ selection, onProject, onCommit, onSelect });
  latest.current = { selection, onProject, onCommit, onSelect };
  const acts = useMemo<ClipActs>(() => ({
    base: () => projRef.current,
    live: (p) => latest.current.onProject(p, true),
    commit: (l) => latest.current.onCommit(l),
    pick: (id) => { if (!latest.current.selection.includes(id)) latest.current.onSelect([id]); },
  }), []);

  // ترتیبِ نمایش: لایه‌های بالاتر بالاتر (تصویر/متن وارونه)، بعد صداها
  const display = useMemo(() => [...project.tracks.filter((t) => t.kind !== "audio").reverse(), ...project.tracks.filter((t) => t.kind === "audio")], [project.tracks]);
  const primary = useMemo(() => {
    for (const t of project.tracks) for (const c of t.clips) if (c.id === primaryId && isMedia(c)) return c;
    return undefined;
  }, [project.tracks, primaryId]);
  const lanes = useMemo(() => lanesOf(primary), [primary]);

  const step = STEPS.find((s) => s * px >= 74) ?? 600;
  const ticks = useMemo(() => {
    const out: { t: number; major: boolean }[] = [];
    for (let t = 0; t <= length; t += step / 2) out.push({ t, major: Math.abs(t / step - Math.round(t / step)) < 1e-6 });
    return out;
  }, [length, step]);

  const updateView = () => {
    const el = scroller.current;
    if (!el) return;
    const lo = Math.floor(el.scrollLeft / px - 2);
    const hi = Math.ceil((el.scrollLeft + el.clientWidth) / px + 2);
    setView((v) => (Math.abs(v.lo - lo) >= 1 || Math.abs(v.hi - hi) >= 1 ? { lo, hi } : v));
  };
  useEffect(() => {
    updateView();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [px, project.tracks.length]);

  // سرِ پخش از قابِ دیدنی بیرون رفت ⇒ اسکرول
  useEffect(() => {
    const el = scroller.current;
    if (!el) return;
    const x = playhead * px;
    if (x > el.scrollLeft + el.clientWidth - 30) el.scrollLeft = x - 60;
    else if (x < el.scrollLeft) el.scrollLeft = Math.max(0, x - 60);
  }, [playhead, px]);

  const timeAt = (clientX: number) => {
    const el = scroller.current!;
    const rect = el.getBoundingClientRect();
    return Math.max(0, (clientX - rect.left + el.scrollLeft) / px);
  };
  const displayRowAt = (clientY: number) => {
    const rect = rows.current?.getBoundingClientRect();
    if (!rect) return -1;
    return Math.floor((clientY - rect.top) / ROW);
  };

  // ───────────── کشیدن
  useEffect(() => {
    if (!drag) return;
    const threshold = 9 / px;
    const fpsStep = 1 / fps;
    const onMove = (e: Ptr) => {
      if (drag.kind === "band") {
        const el = scroller.current!;
        const rect = el.getBoundingClientRect();
        const x = e.clientX - rect.left + el.scrollLeft;
        const y = e.clientY - (rows.current?.getBoundingClientRect().top ?? 0);
        setDrag({ ...drag, x, y });
        const x0 = Math.min(drag.sx, x) / px, x1 = Math.max(drag.sx, x) / px;
        const r0 = Math.floor(Math.min(drag.sy, y) / ROW), r1 = Math.floor(Math.max(drag.sy, y) / ROW);
        const picked: string[] = [];
        display.forEach((t, i) => {
          if (i < r0 || i > r1) return;
          for (const c of t.clips) if (clipEnd(c) > x0 && c.at < x1) picked.push(c.id);
        });
        onSelect(drag.additive ? Array.from(new Set([...drag.base, ...picked])) : picked);
        return;
      }
      const dtRaw = (e.clientX - ("sx" in drag ? drag.sx : 0)) / px;
      if ("moved" in drag && !drag.moved && Math.abs(e.clientX - drag.sx) < 3 && (drag.kind !== "move" || Math.abs(e.clientY - drag.sy) < 4)) return;
      if ("moved" in drag) drag.moved = true;
      // سرِ پخش هنگامِ پخش روی فریم نیست؛ هدفِ چسبیدن همیشه فریم‌دار باشد
      const pts = snapOn ? snapPoints("orig" in drag ? drag.orig : projRef.current, quantize(playhead, fps), "ids" in drag ? new Set(drag.ids) : "id" in drag ? drag.id : undefined) : [];
      if (drag.kind === "move") {
        const len = drag.end0 - drag.at0;
        const raw = Math.max(0, drag.at0 + dtRaw);
        // روی شبکهٔ فریم می‌نشیند؛ چسبیدن (snap) اگر در آستانه باشد بر آن می‌چربد
        let at = quantize(raw, fps);
        let line: number | null = null;
        if (snapOn) {
          const a = snap(raw, pts, threshold);
          const b = snap(raw + len, pts, threshold) - len;
          const aS = a !== raw, bS = b !== raw;
          if (aS && (!bS || Math.abs(a - raw) <= Math.abs(b - raw))) { at = Math.max(0, tidyFrame(a, fps)); line = at; }
          else if (bS) { at = Math.max(0, tidyFrame(b + len, fps) - len); line = at + len; }
        }
        setSnapAt(line);
        // ترکِ مقصد (هم‌نوع)
        const idx = Math.max(0, Math.min(display.length - 1, displayRowAt(e.clientY)));
        const target = display[idx];
        const origTrack = drag.orig.tracks.find((t) => t.clips.some((c) => c.id === drag.primary))!;
        let rowsDelta = 0;
        if (target && target.kind === origTrack.kind && !target.locked) {
          const same = drag.orig.tracks.filter((t) => t.kind === origTrack.kind);
          rowsDelta = same.findIndex((t) => t.id === target.id) - same.findIndex((t) => t.id === origTrack.id);
        }
        onProject(moveClips(drag.orig, drag.ids, at - drag.at0, rowsDelta), true);
        setTrimUi({ x: e.clientX, y: e.clientY, top: wrapRef.current?.getBoundingClientRect().top ?? 0, text: `جابه‌جایی · ${timecode(at, fps)} · ${signedFrames(framesBetween(drag.at0, at, fps))}`, out: null, inn: null });
      } else if (drag.kind === "edge") {
        const base = drag.side === "l" ? drag.at0 : drag.end0;
        const raw = base + dtRaw;
        // لبه روی فریم می‌نشیند؛ چسبیدن (snap) اگر در آستانه باشد بر آن می‌چربد
        let t = quantize(raw, fps);
        let hit = false;
        if (snapOn) {
          const sp = snap(raw, pts, threshold);
          if (sp !== raw) { t = tidyFrame(sp, fps); hit = true; }
        }
        setSnapAt(hit ? t : null);
        // نوعِ برش از ابزار یا کلیدِ تغییردهنده: Ctrl/⌘ = ریپل، Shift = رول (اگر همسایهٔ چسبیده هست)، Alt = فقط همین قطعه
        let mode: "normal" | "ripple" | "roll" | "rate" = "normal";
        if (drag.tool === "rate") mode = "rate";
        else if (drag.tool === "ripple") mode = "ripple";
        else if (drag.tool === "roll") mode = "roll";
        else if (e.ctrlKey || e.metaKey) mode = "ripple";
        else if (e.shiftKey) mode = "roll";
        if (mode === "roll" && !touchingPair(drag.orig, drag.id, drag.side)) mode = "normal";
        const solo = drag.solo || e.altKey;
        let next = drag.orig;
        const partners = solo ? [drag.id] : withLinked(drag.orig, [drag.id]);
        for (const id of partners) {
          if (mode === "rate") {
            const c = next.tracks.flatMap((x) => x.clips).find((x) => x.id === id);
            if (c) next = rateStretch(next, id, drag.side === "r" ? t - c.at : clipEnd(c) - t);
          } else if (mode === "ripple") next = rippleTrim(next, id, drag.side, t);
          else if (mode === "roll") {
            const pr = touchingPair(drag.orig, id, drag.side);
            next = pr ? rollEdit(next, pr.l, pr.r, t) : drag.side === "l" ? trimStart(next, id, t) : trimEnd(next, id, t);
          } else next = drag.side === "l" ? trimStart(next, id, t) : trimEnd(next, id, t);
        }
        onProject(next, true, drag.orig);
        const was = findClip(drag.orig, drag.id)?.clip;
        const now = findClip(next, drag.id)?.clip;
        if (was && now) {
          const label = mode === "ripple" ? "ریپل" : mode === "roll" ? "رول" : mode === "rate" ? "تغییرِ سرعت" : solo ? "فقط این قطعه" : "معمولی";
          const extra = solo && (mode === "ripple" || mode === "roll") ? " · فقط این قطعه" : "";
          const fr = previewFrames(next, drag.id, drag.side, fps);
          setTrimUi({
            x: e.clientX, y: e.clientY, top: wrapRef.current?.getBoundingClientRect().top ?? 0,
            text: `${label}${extra} · ${timecode(drag.side === "l" ? now.at : clipEnd(now), fps)} · ${signedFrames(framesBetween(clipLength(was), clipLength(now), fps))}`,
            out: fr.out, inn: fr.inn,
          });
        }
      } else if (drag.kind === "tool") {
        const d = Math.round(dtRaw / fpsStep) * fpsStep;
        const c = drag.orig.tracks.flatMap((x) => x.clips).find((x) => x.id === drag.id) as MediaClip | undefined;
        if (!c) return;
        const next = drag.tool === "slip" ? slipClip(drag.orig, drag.id, -d * (c.speed || 1)) : slideClip(drag.orig, drag.id, d);
        onProject(next, true);
        setHint(drag.tool === "slip" ? `جابه‌جاییِ منبع ${d >= 0 ? "+" : ""}${(-d * (c.speed || 1)).toFixed(2)} ث` : `لغزش ${d >= 0 ? "+" : ""}${d.toFixed(2)} ث`);
      } else if (drag.kind === "trans") {
        const t = timeAt(e.clientX);
        const d = Math.max(0.1, Math.min(2, 2 * Math.abs(t - drag.cut)));
        onProject({ ...drag.orig, tracks: drag.orig.tracks.map((tr) => ({ ...tr, clips: tr.clips.map((c) => (c.id === drag.id && isMedia(c) && c.transition ? { ...c, transition: { ...c.transition, duration: Math.round(d * 100) / 100 } } : c)) })) }, true);
        setHint(`طولِ گذار ${d.toFixed(2)} ث`);
      } else if (drag.kind === "key") {
        const c = drag.orig.tracks.flatMap((x) => x.clips).find((x) => x.id === drag.id) as MediaClip | undefined;
        if (!c?.kf?.[drag.ch]) return;
        const keys = c.kf[drag.ch]!;
        const k = keys[drag.idx];
        const t0 = Math.max(0, Math.min(clipLength(c), k.t + dtRaw));
        const nk = keys.map((kk, i) => (i === drag.idx ? { ...kk, t: Math.round(t0 * 1000) / 1000 } : kk)).sort((a, b) => a.t - b.t);
        onProject({ ...drag.orig, tracks: drag.orig.tracks.map((tr) => ({ ...tr, clips: tr.clips.map((x) => (x.id === drag.id && isMedia(x) ? { ...x, kf: { ...x.kf, [drag.ch]: nk } } : x)) })) }, true);
      } else if (drag.kind === "marker") {
        const t = Math.max(0, drag.t0 + dtRaw);
        onProject({ ...drag.orig, markers: (drag.orig.markers ?? []).map((m) => (m.id === drag.id ? { ...m, t } : m)) }, true);
      }
    };
    const onUp = () => {
      if (drag.kind === "band") {
        setDrag(null);
        return;
      }
      if ("moved" in drag && drag.moved) {
        const label = drag.kind === "move" ? "جابه‌جایی" : drag.kind === "edge" ? (drag.tool === "rate" ? "تغییرِ سرعت" : drag.tool === "ripple" ? "برشِ ریپل" : drag.tool === "roll" ? "رول" : "برشِ لبه")
          : drag.kind === "tool" ? (drag.tool === "slip" ? "اسلیپ" : "اسلاید") : drag.kind === "trans" ? "طولِ گذار" : drag.kind === "key" ? "جابه‌جاییِ کلیدفریم" : "جابه‌جاییِ نشانگر";
        onCommit(label);
      }
      setDrag(null);
      setSnapAt(null);
      setHint(null);
      setTrimUi(null);
      lastPtr.current = null;
    };
    const onPtr = (e: PointerEvent) => {
      lastPtr.current = ptrOf(e);
      onMove(lastPtr.current);
    };
    // Ctrl/Shift/Alt وسطِ کشیدن عوض شد ⇒ بدونِ حرکتِ ماوس هم نتیجه و راهنما تازه شود
    const onKey = (ev: KeyboardEvent) => {
      const l = lastPtr.current;
      if (!l || !["Control", "Shift", "Alt", "Meta"].includes(ev.key)) return;
      lastPtr.current = { ...l, ctrlKey: ev.ctrlKey, metaKey: ev.metaKey, shiftKey: ev.shiftKey, altKey: ev.altKey };
      onMove(lastPtr.current);
    };
    window.addEventListener("pointermove", onPtr);
    window.addEventListener("pointerup", onUp);
    window.addEventListener("pointercancel", onUp);
    window.addEventListener("keydown", onKey);
    window.addEventListener("keyup", onKey);
    return () => {
      window.removeEventListener("pointermove", onPtr);
      window.removeEventListener("pointerup", onUp);
      window.removeEventListener("pointercancel", onUp);
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("keyup", onKey);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [drag, px, snapOn, playhead, display]);

  const down = (e: React.PointerEvent, c: AnyClip, tr: Track, mode: "move" | "l" | "r") => {
    e.stopPropagation();
    if (e.button !== 0) return;
    // روی لبه‌ها Shift/Ctrl/Alt نوعِ برش را تعیین می‌کنند (رول/ریپل/فقط این قطعه)، نه افزودن به انتخاب
    const additive = mode === "move" && (e.shiftKey || e.ctrlKey || e.metaKey);
    if (tool === "razor") {
      onSelect([c.id]);
      props.onRazor(c.id, timeAt(e.clientX));
      return;
    }
    if (tool === "trackfwd") {
      props.onTrackForward(timeAt(e.clientX));
      return;
    }
    let ids = selSet.has(c.id) ? selection : additive ? [...selection, c.id] : [c.id];
    if (additive && selSet.has(c.id) && mode === "move") ids = selection.filter((x) => x !== c.id);
    onSelect(ids);
    if (tr.locked || (additive && mode === "move")) return;
    if (mode === "move") {
      if (tool === "slip" || tool === "slide") {
        if (c.type === "media") setDrag({ kind: "tool", tool, id: c.id, sx: e.clientX, orig: project, moved: false });
        return;
      }
      let orig = project;
      let moveIds = withLinked(project, ids);
      if (e.altKey) {
        // Alt+کشیدن: نسخه‌ای بساز و همان را بکش
        const made: string[] = [];
        for (const id of moveIds) {
          const r = cloneInPlace(orig, id);
          if (r) { orig = r.project; made.push(r.newId); }
        }
        if (made.length) {
          moveIds = made;
          onProject(orig, true);
          onSelect(made);
        }
      }
      const first = orig.tracks.flatMap((t) => t.clips).find((x) => x.id === (moveIds[moveIds.length - 1] ?? c.id)) ?? c;
      setDrag({ kind: "move", ids: moveIds, primary: first.id, sx: e.clientX, sy: e.clientY, orig, at0: first.at, end0: clipEnd(first), moved: false, trackId: tr.id });
    } else {
      // رول (ابزارِ N یا Shift) هم از همین مسیر می‌گذرد: لبه با قطعهٔ چسبیده با هم می‌رود (touchingPair)
      const eff: Tool = tool === "ripple" || tool === "roll" || tool === "rate" ? tool : "select";
      setDrag({ kind: "edge", side: mode, id: c.id, sx: e.clientX, orig: project, at0: c.at, end0: clipEnd(c), moved: false, tool: eff, solo: e.altKey });
    }
  };

  // کلیکِ روی خطِ زمان سرِ پخش را روی فریم می‌گذارد
  const seekFrom = (clientX: number) => onSeek(quantize(timeAt(clientX), fps));
  // تابعِ پایدار برای ClipView (down هر بار نو می‌شود) تا memo ِ قطعه‌ها واقعاً کار کند
  const downRef = useRef(down);
  downRef.current = down;
  const onDownStable = useCallback((e: React.PointerEvent, c: AnyClip, t: Track, mode: "move" | "l" | "r") => downRef.current(e, c, t, mode), []);

  const gaps = useMemo(() => {
    const base = project.tracks.find((t) => t.kind === "video");
    if (!base) return [] as { a: number; b: number }[];
    const sorted = [...base.clips].sort((x, y) => x.at - y.at);
    const out: { a: number; b: number }[] = [];
    let cur = 0;
    for (const c of sorted) {
      if (c.at > cur + 0.05) out.push({ a: cur, b: c.at });
      cur = Math.max(cur, clipEnd(c));
    }
    return out;
  }, [project]);
  const baseId = project.tracks.find((t) => t.kind === "video")?.id;

  const transitions = useMemo(() => {
    const out: { id: string; cut: number; d: number; kind: string; trackId: string }[] = [];
    for (const t of project.tracks) {
      if (t.kind !== "video") continue;
      const sorted = [...t.clips].filter(isMedia).sort((a, b) => a.at - b.at);
      for (let i = 1; i < sorted.length; i++) {
        const a = sorted[i - 1], b = sorted[i];
        if (b.transition && Math.abs(b.at - clipEnd(a)) < 0.15) out.push({ id: b.id, cut: b.at, d: Math.max(0.1, Math.min(2, b.transition.duration)), kind: b.transition.kind, trackId: t.id });
      }
    }
    return out;
  }, [project.tracks]);

  const linkedSet = useMemo(() => {
    const counts = new Map<string, number>();
    for (const t of project.tracks) for (const c of t.clips) if (isMedia(c) && c.link) counts.set(c.link, (counts.get(c.link) ?? 0) + 1);
    return counts;
  }, [project.tracks]);

  const markers = project.markers ?? [];
  const io = project.inout;
  const bandRect = drag?.kind === "band" ? { x: Math.min(drag.sx, drag.x), y: Math.min(drag.sy, drag.y), w: Math.abs(drag.x - drag.sx), h: Math.abs(drag.y - drag.sy) } : null;

  return (
    <div className="tl-wrap" ref={wrapRef} data-testid="timeline" data-tool={tool}>
      <div className="tl-heads" dir="rtl">
        <div className="tl-ruler-spacer" />
        {display.map((t) => (
          <div key={t.id} className={`tl-head kind-${t.kind}`} data-track-head={t.id}>
            <span className="name" title={t.name}>{t.kind === "video" ? "🎞 " : t.kind === "audio" ? "🔊 " : "T "}{t.name}{t.role ? <small className="role">{t.role === "speech" ? " گفتار" : t.role === "music" ? " موسیقی" : " افکت"}</small> : null}</span>
            {t.kind === "video" && (
              <button type="button" className={t.hidden ? "is-on" : ""} title={t.hidden ? "نمایشِ تصویرِ این ترک" : "پنهان‌کردنِ تصویرِ این ترک (چشم)"} onClick={() => onTrack(t.id, { hidden: !t.hidden })} data-hide={t.id}>👁</button>
            )}
            {t.kind !== "text" && <button type="button" className={t.muted ? "is-on" : ""} title={t.muted ? "صدای این ترک روشن شود" : "بی‌صدا (M)"} onClick={() => onTrack(t.id, { muted: !t.muted })} data-mute={t.id}>M</button>}
            {t.kind !== "text" && <button type="button" className={t.solo ? "is-on solo" : ""} title="تک‌صدا (Solo)" onClick={() => onTrack(t.id, { solo: !t.solo })} data-solo={t.id}>S</button>}
            <button type="button" className={t.locked ? "is-on" : ""} title="قفل (قطعه‌ها جابه‌جا نمی‌شوند)" onClick={() => onTrack(t.id, { locked: !t.locked })} data-lock={t.id}>L</button>
            {t.kind !== "text" && <button type="button" className={t.target ? "is-on" : ""} title="هدف: درج و رویه‌گذاری از مانیتورِ منبع روی این ترک می‌نشینند" onClick={() => onTrack(t.id, { target: !t.target })} data-target={t.id}>◎</button>}
            <button type="button" title="حذفِ ترک" onClick={() => onRemoveTrack(t.id)}>×</button>
          </div>
        ))}
        {lanes.map((l) => (
          <div key={l.ch} className="tl-head lane" style={{ height: LANE }}><span className="name">◆ {KF_TITLE[l.ch]}</span></div>
        ))}
      </div>
      <div className="tl-scroll" ref={scroller} data-testid="timeline-scroll" onScroll={updateView}
        onWheel={(e) => { if (e.ctrlKey) e.preventDefault(); }}>
        <div style={{ width, position: "relative" }}>
          <div
            className="tl-ruler" data-testid="ruler"
            onPointerDown={(e) => {
              if (e.shiftKey) {
                const a = timeAt(e.clientX);
                const move = (ev: PointerEvent) => props.onInOut(Math.min(a, timeAt(ev.clientX)), Math.max(a, timeAt(ev.clientX)));
                const up = () => { window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up); };
                window.addEventListener("pointermove", move);
                window.addEventListener("pointerup", up);
                return;
              }
              seekFrom(e.clientX);
              const move = (ev: PointerEvent) => seekFrom(ev.clientX);
              const up = () => { window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up); };
              window.addEventListener("pointermove", move);
              window.addEventListener("pointerup", up);
            }}
          >
            {io && <i className="tl-io" style={{ left: io.in * px, width: Math.max(2, (io.out - io.in) * px) }} data-testid="inout-range" />}
            {ticks.map((k) => (
              <span key={k.t} className={`tl-tick ${k.major ? "" : "minor"}`} style={{ left: k.t * px }}>{k.major ? timecode(k.t).slice(0, 5) : ""}</span>
            ))}
            {markers.map((m) => (
              <b key={m.id} className={`tl-marker kind-${m.kind}`} style={{ left: m.t * px, color: m.color }} title={`${m.label || "نشانگر"} — ${timecode(m.t)} (Alt+کلیک = حذف)`} data-marker={m.id}
                onPointerDown={(e) => {
                  e.stopPropagation();
                  if (e.altKey) { props.onMarkerClick(m.id, true); return; }
                  props.onMarkerClick(m.id, false);
                  setDrag({ kind: "marker", id: m.id, sx: e.clientX, orig: project, moved: false, t0: m.t });
                }}>
                <i />{m.label && px > 18 ? <span>{m.label}</span> : null}
              </b>
            ))}
          </div>
          <div ref={rows} className="tl-rows">
            {display.map((t) => (
              <div
                key={t.id}
                className={`tl-track kind-${t.kind} ${t.locked ? "is-locked" : ""} ${dropTrack === t.id ? "is-drop" : ""}`}
                style={{ height: ROW }}
                data-track={t.id} data-kind={t.kind}
                onPointerDown={(e) => {
                  if (e.target !== e.currentTarget) return;
                  if (tool === "trackfwd") { props.onTrackForward(timeAt(e.clientX)); return; }
                  const el = scroller.current!;
                  const rect = el.getBoundingClientRect();
                  const x = e.clientX - rect.left + el.scrollLeft;
                  const y = e.clientY - (rows.current?.getBoundingClientRect().top ?? 0);
                  const additive = e.shiftKey || e.ctrlKey;
                  if (!additive) onSelect([]);
                  seekFrom(e.clientX);
                  if (e.pointerType === "mouse" && tool === "select") setDrag({ kind: "band", sx: x, sy: y, x, y, additive, base: selection });
                }}
                onDragOver={(e) => { if (t.locked) return; e.preventDefault(); setDropTrack(t.id); }}
                onDragLeave={() => setDropTrack(null)}
                onDrop={(e) => {
                  e.preventDefault();
                  setDropTrack(null);
                  const ref = e.dataTransfer.getData("text/nm-ref");
                  if (!ref || t.locked) return;
                  const rect = e.currentTarget.getBoundingClientRect();
                  onDropRef(t.id, ref, Math.max(0, (e.clientX - rect.left) / px));
                }}
              >
                {t.id === baseId && gaps.map((g, i) => <i key={i} className="tl-gap" title="فاصلهٔ خالی (سیاه)" style={{ left: g.a * px, width: (g.b - g.a) * px }} />)}
                {t.clips.map((c) => (
                  <ClipView
                    key={c.id} clip={c} track={t} selected={selSet.has(c.id)} primary={c.id === primaryId} px={px} tool={tool} storeId={storeId}
                    item={c.type === "media" ? media[c.ref] : undefined} visible={clipEnd(c) > view.lo && c.at < view.hi}
                    dragging={!!drag && "ids" in drag && drag.ids.includes(c.id)}
                    trim={drag?.kind === "edge" && drag.id === c.id ? drag.side : null}
                    linked={c.type === "media" && !!c.link && (linkedSet.get(c.link) ?? 0) > 1}
                    fps={fps} volLine={volLine} acts={acts} onDown={onDownStable}
                  />
                ))}
                {transitions.filter((x) => x.trackId === t.id).map((x) => (
                  <div key={x.id} className="tl-trans" data-transition={x.id} title={`گذار: ${x.kind} — ${x.d.toFixed(2)} ث (لبه‌ها را بکشید)`}
                    style={{ left: (x.cut - x.d / 2) * px, width: Math.max(10, x.d * px) }}
                    onPointerDown={(e) => { e.stopPropagation(); onSelect([x.id]); }}>
                    <i className="g l" onPointerDown={(e) => { e.stopPropagation(); onSelect([x.id]); setDrag({ kind: "trans", id: x.id, sx: e.clientX, orig: project, moved: false, cut: x.cut }); }} />
                    <span>⋈</span>
                    <i className="g r" onPointerDown={(e) => { e.stopPropagation(); onSelect([x.id]); setDrag({ kind: "trans", id: x.id, sx: e.clientX, orig: project, moved: false, cut: x.cut }); }} />
                  </div>
                ))}
              </div>
            ))}
            {lanes.map((l) => (
              <div key={l.ch} className="tl-lane" style={{ height: LANE }} data-lane={l.ch}>
                {primary && <i className="tl-lane-span" style={{ left: primary.at * px, width: (clipEnd(primary) - primary.at) * px }} />}
                {primary && l.keys.map((k, i) => (
                  <b key={i} className={`tl-key e-${k.e}`} data-key={`${l.ch}:${i}`} title={`${KF_TITLE[l.ch]}: ${Math.round(k.v * 1000) / 1000} — ${k.e}`}
                    style={{ left: (primary.at + k.t) * px }}
                    onPointerDown={(e) => {
                      e.stopPropagation();
                      props.onKeyPick(primary.id, l.ch, k.t);
                      setDrag({ kind: "key", id: primary.id, ch: l.ch, idx: i, sx: e.clientX, orig: project, moved: false });
                    }} />
                ))}
              </div>
            ))}
            {bandRect && <i className="tl-band" style={{ left: bandRect.x, top: bandRect.y, width: bandRect.w, height: bandRect.h }} />}
          </div>
          {snapAt !== null && <i className="tl-snap" style={{ left: snapAt * px }} />}
          {markers.map((m) => <i key={m.id} className="tl-marker-line" style={{ left: m.t * px, borderColor: m.color }} />)}
          <i className="tl-playhead" style={{ left: playhead * px }} data-testid="playhead" />
          {hint && <div className="tl-hint">{hint}</div>}
        </div>
      </div>
      {trimUi && typeof document !== "undefined" && createPortal(
        <>
          <TrimPreview out={trimUi.out} inn={trimUi.inn} media={media} x={trimUi.x} top={trimUi.top} />
          <div className="tl-chip" data-testid="trim-hint" dir="rtl"
            style={{ left: Math.max(90, Math.min((typeof window === "undefined" ? 800 : window.innerWidth) - 90, trimUi.x)), top: Math.max(8, trimUi.y - 48) }}>
            {trimUi.text}
          </div>
        </>,
        document.body,
      )}
    </div>
  );
}
