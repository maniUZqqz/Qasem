import { PointerEvent as ReactPointerEvent, useRef, useState } from "react";

import { fa, label } from "../api";
import type { Catalog, Issue, Item, SceneDoc, Track } from "../types";
import { type Sel, TRACKS, byId, docDuration, itemLabel } from "./model";

/**
 * خطِ زمانِ شش‌شیاره: خط‌کش (کلیک = زمانِ افزودن)، کشیدنِ قطعه (جابه‌جایی)، کشیدنِ لبهٔ راست (مدت)، بزرگ‌نمایی.
 *
 * حینِ کشیدن فقط قطعهٔ در حالِ حرکت از `drag` می‌خواند؛ سند در لحظهٔ رها کردن یک بار عوض می‌شود (یک پلهٔ undo).
 * بدنه `direction: ltr` است تا x همیشه با زمان هم‌جهت باشد؛ برچسب‌ها خودشان راست‌به‌چپ‌اند.
 */

type Drag = { track: Track; idx: number; start: number; duration: number };
type DragState = Drag & { x0: number; s0: number; d0: number; resize: boolean; moved: boolean };

export default function Timeline({
  cat,
  doc,
  issues,
  sel,
  zoom,
  playhead,
  onSelect,
  onPlayhead,
  onAdd,
  onMove,
  onZoom,
}: {
  cat: Catalog;
  doc: SceneDoc;
  issues: Issue[];
  sel: Sel;
  zoom: number;
  playhead: number;
  onSelect: (s: Sel) => void;
  onPlayhead: (t: number) => void;
  onAdd: (track: Track) => void;
  onMove: (track: Track, idx: number, start: number, duration: number) => void;
  onZoom: (factor: number) => void;
}) {
  const [drag, setDrag] = useState<Drag | null>(null);
  const dragRef = useRef<DragState | null>(null);

  const total = docDuration(doc);
  const w = Math.max(total * zoom, 400);
  const step = zoom > 90 ? 0.5 : zoom > 40 ? 1 : 2;
  const errs = new Set(issues.filter((i) => i.level === "error").map((i) => i.path));
  const ticks: number[] = [];
  for (let t = 0; t <= total + 0.001; t += step) ticks.push(Math.round(t * 10) / 10);

  const down = (track: Track, idx: number, it: Item) => (e: ReactPointerEvent<HTMLDivElement>) => {
    e.preventDefault();
    const resize = (e.target as HTMLElement).classList.contains("rs");
    onSelect({ track, idx });
    dragRef.current = {
      track,
      idx,
      x0: e.clientX,
      s0: it.start,
      d0: it.duration || 1,
      resize,
      moved: false,
      start: it.start,
      duration: it.duration || 1,
    };
    e.currentTarget.setPointerCapture(e.pointerId);
  };
  const move = (e: ReactPointerEvent<HTMLDivElement>) => {
    const d = dragRef.current;
    if (!d) return;
    const dx = e.clientX - d.x0;
    if (!d.moved && Math.abs(dx) > 3) d.moved = true;
    if (!d.moved) return;
    const dt = dx / zoom;
    if (d.resize) d.duration = Math.max(0.2, Math.round((d.d0 + dt) * 20) / 20);
    else d.start = Math.max(0, Math.min(total - 0.2, Math.round((d.s0 + dt) * 20) / 20));
    setDrag({ track: d.track, idx: d.idx, start: d.start, duration: d.duration });
  };
  const up = () => {
    const d = dragRef.current;
    dragRef.current = null;
    setDrag(null);
    if (d && d.moved) onMove(d.track, d.idx, d.start, d.duration);
  };

  const env = byId(cat, "environment", doc.environment.id);

  return (
    <div className="u-card u3d-tl p-3">
      <div className="mb-2 flex flex-wrap items-center gap-3">
        <b style={{ color: "var(--text)" }}>خطِ زمان</b>
        <span className="text-xs" style={{ color: "var(--text-3)" }}>
          {fa(total.toFixed(1))} ثانیه · {doc.output.aspect} · {fa(doc.output.fps)}fps · {label(env)}
        </span>
        <span className="ms-auto flex items-center gap-2 text-xs" style={{ color: "var(--text-2)" }}>
          <span>
            زمان: <b className="u3d-mono">{playhead.toFixed(2)}</b>ث
          </span>
          <button type="button" className="u-btn u-btn-ghost u-btn-sm" onClick={() => onZoom(1 / 1.3)} title="کوچک‌نمایی">
            −
          </button>
          <button type="button" className="u-btn u-btn-ghost u-btn-sm" onClick={() => onZoom(1.3)} title="بزرگ‌نمایی">
            +
          </button>
        </span>
      </div>
      <div className="u3d-tl-body">
        <div className="u3d-tl-inner" style={{ width: w + 110 }}>
          <div
            className="u3d-ruler"
            style={{ width: w }}
            onPointerDown={(e) => {
              const r = e.currentTarget.getBoundingClientRect();
              onPlayhead(Math.max(0, Math.min(total, (e.clientX - r.left) / zoom)));
            }}
          >
            {ticks.map((t) => (
              <i key={t} style={{ left: t * zoom }}>
                {t}
              </i>
            ))}
          </div>
          {TRACKS.map(({ id: tr, name }) => (
            <div key={tr} className={`u3d-track u3d-t-${tr}`}>
              <div className="u3d-track-lab">
                {name}
                <button type="button" className="u-btn u-btn-ghost u-btn-sm" onClick={() => onAdd(tr)} title="افزودن در زمانِ فعلی">
                  +
                </button>
              </div>
              <div className="u3d-lane" style={{ width: w }}>
                {doc[tr].map((it, i) => {
                  const dragging = drag && drag.track === tr && drag.idx === i;
                  const start = dragging ? drag.start : it.start;
                  const duration = dragging ? drag.duration : it.duration || 0.5;
                  const m = tr === "actions" ? byId(cat, "motion", it.motion) : undefined;
                  const cls = [
                    "u3d-blk",
                    sel && sel.track === tr && sel.idx === i ? "sel" : "",
                    errs.has(`${tr}[${i}]`) ? "err" : "",
                    m?.layer ? "layer" : "",
                  ].join(" ");
                  const text = itemLabel(cat, tr, it);
                  return (
                    <div
                      key={it.id || `${tr}-${i}`}
                      className={cls}
                      style={{ left: start * zoom, width: Math.max(6, duration * zoom) }}
                      title={text}
                      onPointerDown={down(tr, i, it)}
                      onPointerMove={move}
                      onPointerUp={up}
                      onPointerCancel={up}
                    >
                      {text}
                      <span className="rs" />
                    </div>
                  );
                })}
              </div>
            </div>
          ))}
          <div className="u3d-playhead" style={{ left: 104 + playhead * zoom }} />
        </div>
      </div>
      <p className="mt-1.5 text-xs" style={{ color: "var(--text-3)" }}>
        بکشید تا جابه‌جا شود · لبهٔ راستِ هر قطعه را بکشید تا کوتاه/بلند شود · روی خط‌کش بزنید تا زمانِ افزودن عوض شود ·{" "}
        <span className="u3d-kbd">Delete</span> حذف · <span className="u3d-kbd">Ctrl+Z</span> برگشت · <span className="u3d-kbd">Ctrl+S</span> ذخیره
      </p>
    </div>
  );
}
