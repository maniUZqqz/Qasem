import { useRef, useState } from "react";

import { fa } from "../../../../../components/ui";
import { MAX_STOPS, Stop, addStop, cssGradient, normStops, removeStop } from "../gradients";

/**
 * ویرایشگرِ توقف‌های شیب (دورِ ۸): نوارِ شیب با دستگیره‌های کشیدنی؛ کلیک روی نوار = توقفِ تازه؛ انتخابِ یک توقف ⇒ رنگ، جایگاه و حذف.
 * جهتِ نوار همیشه چپ ⇒ راست است (مستقل از RTL).
 */
export default function GradientStopsEditor({ stops, onChange, testId = "stops" }: { stops: Stop[]; onChange: (s: Stop[]) => void; testId?: string }) {
  const s = normStops(stops);
  const [sel, setSel] = useState(0);
  const bar = useRef<HTMLDivElement>(null);
  const cur = Math.min(sel, s.length - 1);

  const posOf = (clientX: number) => {
    const r = bar.current!.getBoundingClientRect();
    return Math.min(1, Math.max(0, (clientX - r.left) / Math.max(1, r.width)));
  };
  const setAt = (i: number, patch: Partial<{ pos: number; color: string }>) => {
    const next = s.map((x, k) => (k === i ? ([patch.pos ?? x[0], patch.color ?? x[1]] as Stop) : x));
    const moved = next[i];
    next.sort((a, b) => a[0] - b[0]);
    setSel(next.indexOf(moved));
    onChange(next);
  };
  const startDrag = (e: React.PointerEvent, i: number) => {
    e.preventDefault();
    e.stopPropagation();
    setSel(i);
    const el = e.currentTarget as HTMLElement;
    el.setPointerCapture(e.pointerId);
    let idx = i;
    const move = (ev: PointerEvent) => {
      const p = Math.round(posOf(ev.clientX) * 1000) / 1000;
      const next = s.map((x, k) => (k === idx ? ([p, x[1]] as Stop) : x));
      const moved = next[idx];
      next.sort((a, b) => a[0] - b[0]);
      idx = next.indexOf(moved);
      s.splice(0, s.length, ...next);
      setSel(idx);
      onChange(next);
    };
    const up = () => {
      el.removeEventListener("pointermove", move);
      el.removeEventListener("pointerup", up);
    };
    el.addEventListener("pointermove", move);
    el.addEventListener("pointerup", up);
  };
  return (
    <div data-testid={testId} style={{ display: "flex", flexDirection: "column", gap: 8, width: "100%" }} dir="ltr">
      <div
        ref={bar} role="group" aria-label="نوارِ شیب؛ برای افزودنِ توقف کلیک کنید" data-testid={`${testId}-bar`}
        onClick={(e) => {
          if (s.length >= MAX_STOPS) return;
          const next = addStop(s, posOf(e.clientX));
          setSel(next.findIndex((x) => Math.abs(x[0] - posOf(e.clientX)) < 0.002));
          onChange(next);
        }}
        style={{ position: "relative", height: 26, borderRadius: 6, border: "1px solid var(--border, #d4d4d8)", background: cssGradient(s), cursor: "copy", margin: "6px 8px 14px" }}
      >
        {s.map(([p, c], i) => (
          <button
            key={i} type="button" aria-label={`توقفِ ${fa(i + 1)}`} data-testid={`${testId}-handle-${i}`} data-stop={i} aria-pressed={i === cur}
            onPointerDown={(e) => startDrag(e, i)} onClick={(e) => { e.stopPropagation(); setSel(i); }}
            style={{ position: "absolute", left: `${p * 100}%`, top: 14, transform: "translateX(-50%)", width: 16, height: 18, background: c, border: i === cur ? "2px solid #111827" : "2px solid #fff", borderRadius: "3px 3px 8px 8px", boxShadow: "0 1px 4px rgba(0,0,0,.45)", cursor: "ew-resize", padding: 0, touchAction: "none" }}
          />
        ))}
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <input type="color" value={s[cur][1]} onChange={(e) => setAt(cur, { color: e.target.value })} aria-label="رنگِ توقف" data-testid={`${testId}-color`} />
        <label style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 12 }}>
          <span>جایگاه</span>
          <input type="number" min={0} max={100} step={1} value={Math.round(s[cur][0] * 100)} onChange={(e) => setAt(cur, { pos: Math.min(1, Math.max(0, Number(e.target.value) / 100)) })} style={{ width: 64 }} aria-label="جایگاهِ توقف (درصد)" data-testid={`${testId}-pos`} />٪
        </label>
        <button type="button" className="ws-btn" disabled={s.length <= 2} onClick={() => { const n = removeStop(s, cur); setSel(Math.max(0, cur - 1)); onChange(n); }} data-testid={`${testId}-remove`}>حذفِ این توقف</button>
        <button type="button" className="ws-btn" onClick={() => onChange(s.map(([p, c]) => [1 - p, c] as Stop).sort((a, b) => a[0] - b[0]))} data-testid={`${testId}-flip`} title="جهتِ شیب را برعکس می‌کند">برعکس</button>
        <span className="ws-muted" style={{ fontSize: 11 }}>{fa(s.length)} توقف (تا {fa(MAX_STOPS)})</span>
      </div>
    </div>
  );
}
