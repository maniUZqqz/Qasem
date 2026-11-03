import { useEffect, useMemo, useRef, useState } from "react";

import { fa } from "../../../../components/ui";
import {
  AnyClip, Project, Track, clipEnd, moveClip, projectLength, snap, snapPoints, timecode, trimEnd, trimStart,
} from "./model";

const ROW = 46;
const STEPS = [0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600];

type Drag = {
  id: string;
  mode: "move" | "l" | "r";
  sx: number;
  orig: Project;
  at: number;
  end: number;
  moved: boolean;
};

/** تایم‌لاینِ چندترکه: کشیدنِ قطعه، برشِ لبه‌ها، چسبیدن (snap)، خط‌کشِ زوم‌پذیر، سرِ پخش، قفل و بی‌صدا. */
export default function TimelineView({
  project, selection, playhead, px, snapOn, onProject, onCommit, onSelect, onSeek, onDropRef, onTrack, onRemoveTrack,
}: {
  project: Project;
  selection: string | null;
  playhead: number;
  /** پیکسل بر ثانیه */
  px: number;
  snapOn: boolean;
  /** live=true هنگامِ کشیدن؛ false = گامِ نهایی */
  onProject: (p: Project, live: boolean) => void;
  onCommit: (label: string) => void;
  onSelect: (id: string | null) => void;
  onSeek: (t: number) => void;
  onDropRef: (trackId: string, ref: string, at: number) => void;
  onTrack: (id: string, patch: Partial<Track>) => void;
  onRemoveTrack: (id: string) => void;
}) {
  const scroller = useRef<HTMLDivElement>(null);
  const rows = useRef<HTMLDivElement>(null);
  const [drag, setDrag] = useState<Drag | null>(null);
  const [dropTrack, setDropTrack] = useState<string | null>(null);
  const [snapAt, setSnapAt] = useState<number | null>(null);
  const length = Math.max(30, projectLength(project) + 12);
  const width = length * px;
  const projRef = useRef(project);
  projRef.current = project;

  const step = STEPS.find((s) => s * px >= 74) ?? 600;
  const ticks = useMemo(() => {
    const out: { t: number; major: boolean }[] = [];
    for (let t = 0; t <= length; t += step / 2) out.push({ t, major: Math.abs(t / step - Math.round(t / step)) < 1e-6 });
    return out;
  }, [length, step]);

  // سرِ پخش از قابِ دیدنی بیرون رفت ⇒ اسکرول
  useEffect(() => {
    const el = scroller.current;
    if (!el) return;
    const x = playhead * px;
    if (x > el.scrollLeft + el.clientWidth - 30) el.scrollLeft = x - 60;
    else if (x < el.scrollLeft) el.scrollLeft = Math.max(0, x - 60);
  }, [playhead, px]);

  // ───────────── کشیدنِ قطعه / لبه
  useEffect(() => {
    if (!drag) return;
    const threshold = 9 / px;
    const onMove = (e: PointerEvent) => {
      const dt = (e.clientX - drag.sx) / px;
      const pts = snapOn ? snapPoints(drag.orig, playhead, drag.id) : [];
      let next = drag.orig;
      if (drag.mode === "move") {
        const len = drag.end - drag.at;
        const raw = Math.max(0, drag.at + dt);
        let at = raw;
        let line: number | null = null;
        if (snapOn) {
          const a = snap(raw, pts, threshold);
          const b = snap(raw + len, pts, threshold) - len;
          const aS = a !== raw;
          const bS = b !== raw;
          if (aS && (!bS || Math.abs(a - raw) <= Math.abs(b - raw))) {
            at = a;
            line = a;
          } else if (bS) {
            at = b;
            line = b + len;
          }
        }
        setSnapAt(line);
        const rect = rows.current?.getBoundingClientRect();
        let targetId: string | undefined;
        if (rect) {
          const idx = Math.floor((e.clientY - rect.top) / ROW);
          targetId = projRef.current.tracks[Math.max(0, Math.min(projRef.current.tracks.length - 1, idx))]?.id;
        }
        next = moveClip(drag.orig, drag.id, at, targetId);
      } else if (drag.mode === "l") {
        const t = snapOn ? snap(drag.at + dt, pts, threshold) : drag.at + dt;
        setSnapAt(snapOn && t !== drag.at + dt ? t : null);
        next = trimStart(drag.orig, drag.id, t);
      } else {
        const t = snapOn ? snap(drag.end + dt, pts, threshold) : drag.end + dt;
        setSnapAt(snapOn && t !== drag.end + dt ? t : null);
        next = trimEnd(drag.orig, drag.id, t);
      }
      if (!drag.moved && Math.abs(e.clientX - drag.sx) < 3) return;
      drag.moved = true;
      onProject(next, true);
    };
    const onUp = () => {
      if (drag.moved) onCommit(drag.mode === "move" ? "جابه‌جایی" : "برشِ لبه");
      setDrag(null);
      setSnapAt(null);
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    return () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [drag, px, snapOn, playhead]);

  const begin = (e: React.PointerEvent, c: AnyClip, tr: Track, mode: Drag["mode"]) => {
    e.stopPropagation();
    onSelect(c.id);
    if (tr.locked || e.button !== 0) return;
    setDrag({ id: c.id, mode, sx: e.clientX, orig: project, at: c.at, end: clipEnd(c), moved: false });
  };

  const seekFrom = (e: React.PointerEvent) => {
    const el = scroller.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    const t = Math.max(0, (e.clientX - rect.left + el.scrollLeft) / px);
    onSeek(t);
  };

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

  const kindClass = (c: AnyClip, tr: Track) => (c.type === "text" ? "kind-text" : tr.kind === "audio" ? "kind-audio" : c.kind === "image" ? "kind-image" : "");

  return (
    <div className="tl-wrap" data-testid="timeline">
      <div className="tl-heads" dir="rtl">
        <div className="tl-ruler-spacer" />
        {project.tracks.map((t) => (
          <div key={t.id} className="tl-head" data-track-head={t.id}>
            <span className="name" title={t.name}>{t.kind === "video" ? "🎞 " : t.kind === "audio" ? "🔊 " : "T "}{t.name}</span>
            <button type="button" className={t.muted ? "is-on" : ""} title={t.muted ? "صدا/تصویرِ این ترک روشن شود" : "بی‌صدا / پنهان (M)"} onClick={() => onTrack(t.id, { muted: !t.muted })} data-mute={t.id}>M</button>
            <button type="button" className={t.locked ? "is-on" : ""} title="قفل (قطعه‌ها جابه‌جا نمی‌شوند)" onClick={() => onTrack(t.id, { locked: !t.locked })} data-lock={t.id}>L</button>
            <button type="button" title="حذفِ ترک" onClick={() => onRemoveTrack(t.id)}>×</button>
          </div>
        ))}
      </div>
      <div className="tl-scroll" ref={scroller} data-testid="timeline-scroll">
        <div style={{ width, position: "relative" }}>
          <div
            className="tl-ruler" data-testid="ruler"
            onPointerDown={(e) => {
              seekFrom(e);
              const move = (ev: PointerEvent) => seekFrom(ev as unknown as React.PointerEvent);
              const up = () => {
                window.removeEventListener("pointermove", move);
                window.removeEventListener("pointerup", up);
              };
              window.addEventListener("pointermove", move);
              window.addEventListener("pointerup", up);
            }}
          >
            {ticks.map((k) => (
              <span key={k.t} className={`tl-tick ${k.major ? "" : "minor"}`} style={{ left: k.t * px }}>
                {k.major ? timecode(k.t).slice(0, 5) : ""}
              </span>
            ))}
          </div>
          <div ref={rows}>
            {project.tracks.map((t) => (
              <div
                key={t.id}
                className={`tl-track ${t.locked ? "is-locked" : ""} ${dropTrack === t.id ? "is-drop" : ""}`}
                data-track={t.id} data-kind={t.kind}
                onPointerDown={(e) => {
                  if (e.target === e.currentTarget) {
                    onSelect(null);
                    seekFrom(e);
                  }
                }}
                onDragOver={(e) => {
                  if (t.locked) return;
                  e.preventDefault();
                  setDropTrack(t.id);
                }}
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
                {t.kind === "video" && t.id === project.tracks.find((x) => x.kind === "video")?.id &&
                  gaps.map((g, i) => <i key={i} className="tl-gap" title="فاصلهٔ خالی (سیاه)" style={{ left: g.a * px, width: (g.b - g.a) * px }} />)}
                {t.clips.map((c) => {
                  const live = drag?.id === c.id;
                  return (
                    <div
                      key={c.id}
                      className={`tl-clip ${kindClass(c, t)} ${selection === c.id ? "is-sel" : ""}`}
                      data-clip={c.id} data-clip-kind={c.type === "text" ? "text" : c.kind}
                      style={{ left: c.at * px, width: Math.max(6, (clipEnd(c) - c.at) * px), opacity: t.muted ? 0.45 : live ? 0.9 : 1 }}
                      title={c.type === "text" ? c.text : `${c.label} — ${timecode(c.at)}`}
                      onPointerDown={(e) => begin(e, c, t, "move")}
                    >
                      {c.type === "media" && c.transition && <i className="tr" title={c.transition.kind === "crossfade" ? "محوشدنِ تدریجی" : "محو به سیاه"} />}
                      <i className="grip l" onPointerDown={(e) => begin(e, c, t, "l")} data-grip="l" />
                      <span className="truncate" style={{ maxWidth: "100%" }}>
                        {c.type === "text" ? c.text : c.label}
                        {c.type === "media" && c.speed !== 1 ? ` ×${fa(c.speed)}` : ""}
                      </span>
                      <i className="grip r" onPointerDown={(e) => begin(e, c, t, "r")} data-grip="r" />
                    </div>
                  );
                })}
              </div>
            ))}
          </div>
          {snapAt !== null && <i className="tl-snap" style={{ left: snapAt * px }} />}
          <i className="tl-playhead" style={{ left: playhead * px }} data-testid="playhead" />
        </div>
      </div>
    </div>
  );
}
