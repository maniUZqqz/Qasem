import { useEffect, useMemo, useRef, useState } from "react";

import { fa } from "../../../../components/ui";
import { KF_RANGE, valueAt } from "../manual/keyframes";
import { MediaClip, timecode, updateClip } from "../manual/model";
import { deleteWordRange, motionPoints, pausesBetween, removeMotionPoint, setMotionPoint, spokenWords, wordsRange } from "../manual/r5ops";
import { liftRange } from "../manual/model";
import type { PanelProps } from "./types";

/** ویرایش با متنِ گفتار: کلمه‌ها را انتخاب کنید و «حذف» بزنید؛ همان بخش از ویدیو و صدا (و زیرنویسش) بریده می‌شود و جا بسته می‌شود. */
export function TranscriptPanel({ api }: PanelProps) {
  const words = useMemo(() => spokenWords(api.project), [api.project]);
  const [a, setA] = useState<number | null>(null);
  const [b, setB] = useState<number | null>(null);
  useEffect(() => { setA(null); setB(null); }, [words.length]);
  const range = a !== null && b !== null ? wordsRange(words, a, b) : null;
  const pauses = useMemo(() => pausesBetween(words), [words]);
  if (words.length === 0) {
    return (
      <div data-testid="tb-empty">
        <p className="ws-hint">برای ویرایش با متن، اول باید زیرنویسِ گفتار روی تایم‌لاین باشد. «زیرنویسِ خودکار» گفتار را می‌شنود و متنش را با زمانِ هر کلمه می‌سازد (به سرورِ پردازش یا هوش مصنوعی نیاز دارد؛ اگر آماده نباشد در صف می‌ماند).</p>
        <button type="button" className="ws-btn primary" onClick={() => api.setTab("captions")} data-testid="tb-make-captions">رفتن به ساختنِ زیرنویس</button>
      </div>
    );
  }
  const pick = (i: number, shift: boolean) => {
    if (shift && a !== null) setB(i);
    else { setA(i); setB(i); }
  };
  const cut = () => {
    if (a === null || b === null) return;
    const r = deleteWordRange(api.project, words, a, b, true);
    if (!r) { api.notice("این بازه برای بریدن خیلی کوتاه است."); return; }
    api.apply("حذف با متنِ گفتار", () => r.project);
    api.notice(`${fa(Math.round(r.seconds * 10) / 10)} ثانیه از ویدیو بریده شد و جا بسته شد (برگشت: Ctrl+Z).`);
    setA(null); setB(null);
  };
  const cutPauses = () => {
    if (!pauses.length) return;
    api.apply("حذفِ مکث‌های بین کلمه‌ها", (p) => [...pauses].sort((x, y) => y.a - x.a).reduce((q, r) => liftRange(q, r.a, r.b, true), p));
    api.notice(`${fa(pauses.length)} مکثِ طولانی بریده شد.`);
  };
  const lo = a !== null && b !== null ? Math.min(a, b) : -1;
  const hi = a !== null && b !== null ? Math.max(a, b) : -2;
  return (
    <div data-testid="transcript-panel">
      <p className="ws-hint">روی یک کلمه بزنید؛ Shift + کلیک روی کلمهٔ دیگر بازه را بزرگ می‌کند. «پرش» سرِ پخش را به آن‌جا می‌برد.</p>
      <div className="tb-words" dir="rtl" role="listbox" aria-label="کلمه‌های گفتار" aria-multiselectable>
        {words.map((w, i) => (
          <button key={w.id} type="button" role="option" aria-selected={i >= lo && i <= hi} className={`tb-w ${i >= lo && i <= hi ? "is-sel" : ""}`} data-testid="tb-word"
            onClick={(e) => pick(i, e.shiftKey)} onDoubleClick={() => api.seek(w.start)} title={timecode(w.start).slice(0, 8)}>
            {w.text}
          </button>
        ))}
      </div>
      <div className="mk-top">
        <button type="button" className="ws-btn primary" disabled={!range} onClick={cut} data-testid="tb-cut">حذفِ انتخاب از ویدیو{range ? ` (${fa(Math.round((range.b - range.a) * 10) / 10)} ثانیه)` : ""}</button>
        <button type="button" className="ws-btn" disabled={!range} onClick={() => range && api.seek(range.a)} data-testid="tb-seek">پرش به آن‌جا</button>
        <button type="button" className="ws-btn" disabled={!pauses.length} onClick={cutPauses} data-testid="tb-pauses" title="مکث‌های بیش از ۰٫۸ ثانیه بینِ دو کلمه">حذفِ مکث‌های طولانی ({fa(pauses.length)})</button>
      </div>
    </div>
  );
}

const SZ = 220;

/** مسیرِ حرکتِ قطعه: جای مرکزِ قطعه در طولِ زمان؛ نقطه‌ها را بکشید، دوبار کلیک روی صفحه = نقطهٔ تازه در سرِ پخش، کلیک روی نقطه + Delete = حذف. */
export function MotionPathPanel({ api }: PanelProps) {
  const c = api.selected && api.selected.clip.type === "media" && api.selected.track.kind === "video" ? (api.selected.clip as MediaClip) : null;
  const fmt = api.project.format;
  const ar = fmt.width / fmt.height;
  const W = ar >= 1 ? SZ : Math.round(SZ * ar);
  const H = ar >= 1 ? Math.round(SZ / ar) : SZ;
  const box = useRef<SVGSVGElement>(null);
  const [drag, setDrag] = useState<number | null>(null);
  const [sel, setSel] = useState<number | null>(null);
  if (!c) return <p className="ws-hint" data-testid="mp-empty">اول یک ویدیو یا عکس را روی تایم‌لاین انتخاب کنید.</p>;
  const pts = motionPoints(c);
  const cx = c.x + c.width / 2, cy = c.y + c.height / 2;
  const X = (px: number) => (cx + px) * W;
  const Y = (py: number) => (cy + py) * H;
  const local = (e: React.PointerEvent | React.MouseEvent) => {
    const r = box.current!.getBoundingClientRect();
    return { u: (e.clientX - r.left) / r.width, v: (e.clientY - r.top) / r.height };
  };
  const rangePx = KF_RANGE.px, rangePy = KF_RANGE.py;
  const clampPx = (v: number) => Math.max(rangePx[0], Math.min(rangePx[1], v));
  const clampPy = (v: number) => Math.max(rangePy[0], Math.min(rangePy[1], v));
  const rel = Math.max(0, api.time - c.at);
  const write = (kf: MediaClip["kf"], live: boolean, label = "مسیرِ حرکت") => {
    if (live) api.live((p) => updateClip(p, c.id, { kf }));
    else api.apply(label, (p) => updateClip(p, c.id, { kf }));
  };
  const d = pts.length > 1 ? (() => {
    const out: string[] = [];
    const t0 = pts[0].t, t1 = pts[pts.length - 1].t;
    for (let i = 0; i <= 60; i++) {
      const t = t0 + ((t1 - t0) * i) / 60;
      out.push(`${i ? "L" : "M"}${X(valueAt(c.kf?.px, t, c.px ?? 0)).toFixed(1)},${Y(valueAt(c.kf?.py, t, c.py ?? 0)).toFixed(1)}`);
    }
    return out.join(" ");
  })() : "";
  const here = { px: valueAt(c.kf?.px, rel, c.px ?? 0), py: valueAt(c.kf?.py, rel, c.py ?? 0) };
  return (
    <div data-testid="motion-panel">
      <p className="ws-hint">مسیرِ مرکزِ قطعه روی قاب. هر نقطه یک کلیدِ جابه‌جایی در همان لحظه است؛ قطعه از میانِ نقطه‌ها عبور می‌کند.</p>
      <svg ref={box} viewBox={`0 0 ${W} ${H}`} width="100%" style={{ maxWidth: W * 1.6, background: "color-mix(in srgb, var(--void) 70%, transparent)", border: "1px solid var(--line)", borderRadius: 8, touchAction: "none" }}
        data-testid="mp-svg" role="img" aria-label="مسیرِ حرکت"
        onPointerMove={(e) => { if (drag === null) return; const { u, v } = local(e); write(setMotionPoint(c, pts[drag].t, clampPx(u - cx), clampPy(v - cy)), true); }}
        onPointerUp={() => { if (drag !== null) { api.end("مسیرِ حرکت"); setDrag(null); } }}
        onDoubleClick={(e) => { const { u, v } = local(e); write(setMotionPoint(c, Math.round(rel * 100) / 100, clampPx(u - cx), clampPy(v - cy)), false, "نقطهٔ مسیر"); }}>
        <rect x={0} y={0} width={W} height={H} fill="none" stroke="var(--line-strong)" strokeDasharray="4 4" />
        <line x1={W / 2} x2={W / 2} y1={0} y2={H} stroke="var(--line)" /><line y1={H / 2} y2={H / 2} x1={0} x2={W} stroke="var(--line)" />
        {d && <path d={d} fill="none" stroke="var(--brand)" strokeWidth={2} data-testid="mp-path" />}
        <circle cx={X(here.px)} cy={Y(here.py)} r={4} fill="#ef4444" data-testid="mp-now"><title>جای فعلیِ قطعه (سرِ پخش)</title></circle>
        {pts.map((p, i) => (
          <circle key={`${i}-${p.t}`} cx={X(p.px)} cy={Y(p.py)} r={sel === i ? 8 : 6} fill={sel === i ? "var(--brand)" : "var(--surface-2)"} stroke="var(--brand)" strokeWidth={2} data-testid="mp-point" tabIndex={0} role="button"
            aria-label={`نقطه در ثانیهٔ ${p.t}`} style={{ cursor: "grab" }}
            onPointerDown={(e) => { e.stopPropagation(); (e.currentTarget as Element).setPointerCapture(e.pointerId); setDrag(i); setSel(i); }}
            onKeyDown={(e) => { if (e.key === "Delete" || e.key === "Backspace") { e.preventDefault(); write(removeMotionPoint(c, p.t), false, "حذفِ نقطهٔ مسیر"); setSel(null); } }}>
            <title>{`ثانیهٔ ${p.t}`}</title>
          </circle>
        ))}
      </svg>
      <div className="mk-top">
        <button type="button" className="ws-btn" onClick={() => write(setMotionPoint(c, Math.round(rel * 100) / 100, here.px, here.py), false, "نقطهٔ مسیر")} data-testid="mp-add">+ نقطه در سرِ پخش</button>
        <button type="button" className="ws-btn" disabled={sel === null} onClick={() => { if (sel !== null) { write(removeMotionPoint(c, pts[sel].t), false, "حذفِ نقطهٔ مسیر"); setSel(null); } }} data-testid="mp-del">حذفِ نقطهٔ انتخاب‌شده</button>
        <button type="button" className="ws-btn" disabled={!pts.length} onClick={() => { const kf = { ...(c.kf ?? {}) }; delete kf.px; delete kf.py; write(Object.keys(kf).length ? kf : undefined, false, "پاک‌کردنِ مسیر"); setSel(null); }} data-testid="mp-clear">پاک‌کردنِ مسیر</button>
      </div>
      <p className="ws-hint">{pts.length ? `${fa(pts.length)} نقطه` : "هنوز مسیری نیست؛ دوبار کلیک روی قاب یا «+ نقطه»."} شیبِ هر بخش را در «گرافِ کلیدفریم» (کانالِ جابه‌جایی) عوض کنید.</p>
    </div>
  );
}
