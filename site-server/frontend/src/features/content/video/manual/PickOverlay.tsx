import { useRef, useState } from "react";

import { flatten, insertPoint, removePoint, togglePointSmooth } from "./bezier";
import { boxToFrame, frameToBox, placement } from "./geom";
import { BezierPt, MediaClip, Project } from "./model";
import "./pick.css";

/**
 * لایهٔ تعاملیِ روی تصویرِ مانیتور: ویرایشِ ماسکِ آزاد (نقطه‌ها و دستگیره‌ها) و کشیدنِ ناحیهٔ ردیابی.
 * مختصاتِ نشان‌داده‌شده «کسری از قاب»‌اند و با هندسهٔ قطعه (جا، اندازه، چرخش) به/از جعبهٔ قطعه برمی‌گردند.
 */
type FrameBox = { x: number; y: number; w: number; h: number };

function useFramePointer(host: React.RefObject<HTMLDivElement>) {
  return (e: { clientX: number; clientY: number }): [number, number] => {
    const r = host.current!.getBoundingClientRect();
    return [(e.clientX - r.left) / r.width, (e.clientY - r.top) / r.height];
  };
}

export function BezierOverlay({
  project, clip, time, onLive, onEnd,
}: {
  project: Project;
  clip: MediaClip;
  time: number;
  onLive: (points: BezierPt[]) => void;
  onEnd: (label: string) => void;
}) {
  const host = useRef<HTMLDivElement>(null);
  const at = useFramePointer(host);
  const fa = project.format.width / project.format.height;
  const pl = placement(clip, time);
  const pts = clip.mask?.points ?? [];
  const drag = useRef<null | { i: number; part: "a" | "in" | "out"; moved: boolean }>(null);
  const [sel, setSel] = useState<number | null>(null);
  const toFrame = (u: number, v: number) => boxToFrame(pl, u, v, fa);
  const toBox = (X: number, Y: number) => frameToBox(pl, X, Y, fa);
  const pct = (n: number) => `${(n * 100).toFixed(2)}%`;

  const poly = flatten(pts).map(([u, v]) => toFrame(u, v));
  const d = poly.map(([X, Y], i) => `${i ? "L" : "M"}${(X * 1000).toFixed(1)},${(Y * 1000).toFixed(1)}`).join(" ") + " Z";

  const move = (e: React.PointerEvent) => {
    const st = drag.current;
    if (!st) return;
    st.moved = true;
    const [X, Y] = at(e);
    const [u, v] = toBox(X, Y);
    onLive(pts.map((p, k) => {
      if (k !== st.i) return p;
      if (st.part === "a") return { ...p, x: u, y: v };
      if (st.part === "in") return { ...p, ix: u - p.x, iy: v - p.y };
      return { ...p, ox: u - p.x, oy: v - p.y };
    }));
  };
  const up = () => {
    const st = drag.current;
    drag.current = null;
    if (st?.moved) onEnd("ویرایشِ ماسکِ آزاد");
  };
  const begin = (e: React.PointerEvent, i: number, part: "a" | "in" | "out") => {
    e.stopPropagation();
    if (part === "a" && e.altKey) {
      onLive(removePoint(pts, i));
      onEnd("حذفِ نقطهٔ ماسک");
      return;
    }
    setSel(i);
    drag.current = { i, part, moved: false };
    (e.currentTarget as Element).setPointerCapture(e.pointerId);
  };

  return (
    <div ref={host} className="pk-layer" data-testid="bezier-overlay" onPointerMove={move} onPointerUp={up}
      onDoubleClick={(e) => {
        const [X, Y] = at(e);
        const [u, v] = toBox(X, Y);
        onLive(insertPoint(pts, u, v));
        onEnd("نقطهٔ تازهٔ ماسک");
      }}>
      <svg viewBox="0 0 1000 1000" preserveAspectRatio="none" className="pk-svg">
        <path d={d} className="pk-path" vectorEffect="non-scaling-stroke" />
      </svg>
      {pts.map((p, i) => {
        const [ax, ay] = toFrame(p.x, p.y);
        const [ix, iy] = toFrame(p.x + p.ix, p.y + p.iy);
        const [ox, oy] = toFrame(p.x + p.ox, p.y + p.oy);
        const smooth = p.ix !== 0 || p.iy !== 0 || p.ox !== 0 || p.oy !== 0;
        return (
          <div key={i}>
            {smooth && sel === i && (
              <svg viewBox="0 0 1000 1000" preserveAspectRatio="none" className="pk-svg">
                <line x1={ix * 1000} y1={iy * 1000} x2={ax * 1000} y2={ay * 1000} className="pk-handle-line" vectorEffect="non-scaling-stroke" />
                <line x1={ox * 1000} y1={oy * 1000} x2={ax * 1000} y2={ay * 1000} className="pk-handle-line" vectorEffect="non-scaling-stroke" />
              </svg>
            )}
            {smooth && sel === i && <i className="pk-h" style={{ left: pct(ix), top: pct(iy) }} onPointerDown={(e) => begin(e, i, "in")} data-bez-handle={`${i}:in`} />}
            {smooth && sel === i && <i className="pk-h" style={{ left: pct(ox), top: pct(oy) }} onPointerDown={(e) => begin(e, i, "out")} data-bez-handle={`${i}:out`} />}
            <i className={`pk-pt ${sel === i ? "is-sel" : ""} ${smooth ? "" : "sharp"}`} style={{ left: pct(ax), top: pct(ay) }} data-bez-point={i}
              title="بکشید؛ دوبار کلیک روی نقطه = نرم/تیز؛ Alt+کلیک = حذف"
              onPointerDown={(e) => begin(e, i, "a")}
              onDoubleClick={(e) => { e.stopPropagation(); onLive(togglePointSmooth(pts, i)); onEnd("نرم/تیزِ نقطه"); }} />
          </div>
        );
      })}
      <div className="pk-hint">ماسکِ آزاد — نقطه‌ها را بکشید · دوبار کلیک روی خط = نقطهٔ تازه · دوبار کلیک روی نقطه = نرم/تیز · Alt+کلیک = حذف</div>
    </div>
  );
}

/** ناحیه (یا نقطه با یک کلیک) را روی تصویر می‌کشد؛ خروجی «کسری از قاب» */
export function RegionOverlay({ rect, onRect }: { rect: FrameBox | null; onRect: (r: FrameBox) => void }) {
  const host = useRef<HTMLDivElement>(null);
  const at = useFramePointer(host);
  const start = useRef<[number, number] | null>(null);
  const pct = (n: number) => `${(n * 100).toFixed(2)}%`;
  return (
    <div ref={host} className="pk-layer pk-region" data-testid="region-overlay"
      onPointerDown={(e) => {
        (e.currentTarget as Element).setPointerCapture(e.pointerId);
        start.current = at(e);
        const [x, y] = start.current;
        onRect({ x: x - 0.04, y: y - 0.04, w: 0.08, h: 0.08 });
      }}
      onPointerMove={(e) => {
        if (!start.current) return;
        const [x0, y0] = start.current;
        const [x1, y1] = at(e);
        if (Math.abs(x1 - x0) < 0.012 && Math.abs(y1 - y0) < 0.012) return;
        onRect({ x: Math.min(x0, x1), y: Math.min(y0, y1), w: Math.abs(x1 - x0), h: Math.abs(y1 - y0) });
      }}
      onPointerUp={() => { start.current = null; }}>
      {rect && <i className="pk-rect" style={{ left: pct(rect.x), top: pct(rect.y), width: pct(rect.w), height: pct(rect.h) }} data-testid="region-rect" />}
      <div className="pk-hint">روی تصویر بکشید تا ناحیهٔ ردیابی را بکشید؛ یک کلیک = یک نقطه</div>
    </div>
  );
}
