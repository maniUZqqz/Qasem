import { useMemo, useRef, useState } from "react";

import { fa } from "../../../../components/ui";
import { EASINGS, Easing, KF_RANGE, KF_TITLE, Key, KfChannel, MAX_KEYS, removeKey, setKey, valueAt } from "../manual/keyframes";
import { MediaClip, clipLength, propAt, updateClip } from "../manual/model";
import type { PanelProps } from "./types";

const W = 400;
const H = 190;
const PAD = { l: 38, r: 10, t: 10, b: 20 };
const CHANNELS = Object.keys(KF_TITLE) as KfChannel[];

/** کلیدهای کپی‌شده (در حافظهٔ همین صفحه): کانال + کلیدها با زمانِ نسبت به شروعِ قطعه */
let copied: { ch: KfChannel; keys: Key[] } | null = null;

const r3 = (x: number) => Math.round(x * 1000) / 1000;
const r4 = (x: number) => Math.round(x * 10000) / 10000;

/**
 * گرافِ کلیدفریم: برای هر ویژگیِ قطعه (جا، اندازه، چرخش، شفافیت، بلندی، برش) منحنیِ مقدار بر حسبِ زمان را ببینید.
 * نقطه‌ها را بکشید (بالا/پایین = مقدار، چپ/راست = زمان)، دوبار کلیک روی نمودار = کلیدِ تازه، نوعِ شیبِ هر کلید را عوض کنید.
 */
export default function KeyframeGraph({ api }: PanelProps) {
  const clip = api.selected && api.selected.clip.type === "media" ? (api.selected.clip as MediaClip) : null;
  const [ch, setCh] = useState<KfChannel>("opacity");
  const [sel, setSel] = useState<number | null>(null);
  const svg = useRef<SVGSVGElement>(null);
  const drag = useRef<number | null>(null);

  const len = clip ? Math.max(0.1, clipLength(clip)) : 1;
  const keys: Key[] = useMemo(() => clip?.kf?.[ch] ?? [], [clip, ch]);
  const dflt = clip ? propAt(clip, ch, 0) : 0;
  const [lo0, hi0] = KF_RANGE[ch];

  // محورِ مقدار: به اندازهٔ داده‌ها (نه کلِ بازهٔ مجاز) تا منحنی دیده شود
  const [vmin, vmax] = useMemo(() => {
    const vs = keys.length ? keys.map((k) => k.v) : [dflt];
    let a = Math.min(...vs, dflt);
    let b = Math.max(...vs, dflt);
    if (b - a < (hi0 - lo0) * 0.05) { const c = (a + b) / 2; a = c - (hi0 - lo0) * 0.05; b = c + (hi0 - lo0) * 0.05; }
    const pad = (b - a) * 0.15;
    return [Math.max(lo0, a - pad), Math.min(hi0, b + pad)];
  }, [keys, dflt, lo0, hi0]);

  const X = (t: number) => PAD.l + (t / len) * (W - PAD.l - PAD.r);
  const Y = (v: number) => PAD.t + (1 - (v - vmin) / Math.max(1e-9, vmax - vmin)) * (H - PAD.t - PAD.b);
  const tOf = (px: number) => Math.max(0, Math.min(len, ((px - PAD.l) / (W - PAD.l - PAD.r)) * len));
  const vOf = (py: number) => Math.max(lo0, Math.min(hi0, vmin + (1 - (py - PAD.t) / (H - PAD.t - PAD.b)) * (vmax - vmin)));

  const curve = useMemo(() => {
    if (!keys.length) return `M${X(0)},${Y(dflt)} L${X(len)},${Y(dflt)}`;
    const pts: string[] = [];
    for (let i = 0; i <= 120; i++) {
      const t = (len * i) / 120;
      pts.push(`${i ? "L" : "M"}${X(t).toFixed(1)},${Y(valueAt(keys, t, dflt)).toFixed(1)}`);
    }
    return pts.join(" ");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [keys, len, vmin, vmax, dflt]);

  if (!clip) return <p className="ws-hint" data-testid="graph-empty">اول یک ویدیو یا عکس را روی تایم‌لاین انتخاب کنید تا منحنیِ کلیدفریم‌هایش دیده شود.</p>;

  const write = (next: Key[], live: boolean, label = "ویرایشِ کلیدفریم") => {
    const kf = { ...(clip.kf ?? {}) };
    if (next.length) kf[ch] = next;
    else delete kf[ch];
    const patch = { kf: Object.keys(kf).length ? kf : undefined };
    if (live) api.live((p) => updateClip(p, clip.id, patch));
    else api.apply(label, (p) => updateClip(p, clip.id, patch));
  };

  const local = (e: React.PointerEvent | React.MouseEvent) => {
    const r = svg.current!.getBoundingClientRect();
    return { x: ((e.clientX - r.left) / r.width) * W, y: ((e.clientY - r.top) / r.height) * H };
  };

  const onDown = (i: number) => (e: React.PointerEvent) => {
    e.stopPropagation();
    (e.currentTarget as Element).setPointerCapture(e.pointerId);
    drag.current = i;
    setSel(i);
  };
  const onMove = (e: React.PointerEvent) => {
    const i = drag.current;
    if (i === null) return;
    const { x, y } = local(e);
    const old = keys[i];
    const moved: Key = { ...old, t: r3(tOf(x)), v: r4(vOf(y)) };
    const rest = keys.filter((_, j) => j !== i);
    const next = [...rest.filter((k) => Math.abs(k.t - moved.t) > 0.02), moved].sort((a, b) => a.t - b.t);
    write(next, true);
    setSel(next.indexOf(moved));
  };
  const onUp = () => {
    if (drag.current !== null) api.end("حرکتِ کلیدفریم");
    drag.current = null;
  };
  const addAt = (t: number, v?: number) => {
    const val = v ?? valueAt(keys, t, dflt);
    if (keys.length >= MAX_KEYS) { api.notice("به سقفِ کلیدها رسیدید."); return; }
    const next = setKey(keys, t, val, ch);
    write(next, false, "کلیدفریمِ تازه");
    setSel(next.findIndex((k) => Math.abs(k.t - t) < 0.03));
  };
  const cur = Math.max(0, Math.min(len, api.time - clip.at));
  const s = sel !== null ? keys[sel] : undefined;
  const edit = (patch: Partial<Key>) => {
    if (sel === null || !s) return;
    const moved: Key = { ...s, ...patch };
    const [a, b] = KF_RANGE[ch];
    moved.v = r4(Math.max(a, Math.min(b, moved.v)));
    moved.t = r3(Math.max(0, Math.min(len, moved.t)));
    const next = [...keys.filter((_, j) => j !== sel).filter((k) => Math.abs(k.t - moved.t) > 0.02), moved].sort((x, y) => x.t - y.t);
    write(next, false);
    setSel(next.indexOf(moved));
  };

  return (
    <div data-testid="graph-panel">
      <label className="ws-field">
        <span>کدام ویژگی؟</span>
        <select className="u-input" value={ch} onChange={(e) => { setCh(e.target.value as KfChannel); setSel(null); }} aria-label="ویژگیِ کلیدفریم" data-testid="graph-channel">
          {CHANNELS.map((c) => <option key={c} value={c}>{KF_TITLE[c]}{clip.kf?.[c]?.length ? ` (${fa(clip.kf[c]!.length)} کلید)` : ""}</option>)}
        </select>
      </label>
      <svg ref={svg} viewBox={`0 0 ${W} ${H}`} className="kg-svg" role="img" aria-label={`منحنیِ ${KF_TITLE[ch]}`} data-testid="graph-svg"
        onPointerMove={onMove} onPointerUp={onUp} onPointerCancel={onUp}
        onDoubleClick={(e) => { const { x, y } = local(e); addAt(r3(tOf(x)), r4(vOf(y))); }}
        onClick={() => setSel(null)}>
        <rect x={PAD.l} y={PAD.t} width={W - PAD.l - PAD.r} height={H - PAD.t - PAD.b} className="kg-plot" />
        {[0, 0.5, 1].map((f) => <line key={f} x1={PAD.l} x2={W - PAD.r} y1={PAD.t + f * (H - PAD.t - PAD.b)} y2={PAD.t + f * (H - PAD.t - PAD.b)} className="kg-grid" />)}
        <text x={PAD.l - 4} y={PAD.t + 4} className="kg-axis" textAnchor="end">{r3(vmax)}</text>
        <text x={PAD.l - 4} y={H - PAD.b} className="kg-axis" textAnchor="end">{r3(vmin)}</text>
        <text x={PAD.l} y={H - 5} className="kg-axis">۰</text>
        <text x={W - PAD.r} y={H - 5} className="kg-axis" textAnchor="end">{r3(len)}s</text>
        <line x1={X(cur)} x2={X(cur)} y1={PAD.t} y2={H - PAD.b} className="kg-now" />
        <path d={curve} className="kg-curve" fill="none" />
        {keys.map((k, i) => (
          <circle key={`${i}-${k.t}`} cx={X(k.t)} cy={Y(k.v)} r={sel === i ? 7 : 5.5} className={`kg-key ${sel === i ? "is-sel" : ""}`} data-testid="graph-key"
            onPointerDown={onDown(i)} onClick={(e) => { e.stopPropagation(); setSel(i); }} tabIndex={0} role="button" aria-label={`کلید در ${k.t} ثانیه`}
            onKeyDown={(e) => { if (e.key === "Delete" || e.key === "Backspace") { e.preventDefault(); write(removeKey(keys, k.t), false, "حذفِ کلید"); setSel(null); } }} />
        ))}
      </svg>
      <p className="ws-hint">دوبار کلیک روی نمودار = کلیدِ تازه · نقطه را بکشید · روی نقطه بزنید و Delete = حذف. خطِ قرمز جای سرِ پخش است.</p>
      <div className="kg-row">
        <button type="button" className="ws-btn" onClick={() => addAt(r3(cur))} data-testid="graph-add" title="یک کلید در جای سرِ پخش با مقدارِ همان لحظه">+ کلید در سرِ پخش</button>
        <button type="button" className="ws-btn" disabled={!keys.length} onClick={() => { copied = { ch, keys: keys.map((k) => ({ ...k })) }; api.notice(`${fa(keys.length)} کلیدِ «${KF_TITLE[ch]}» کپی شد؛ قطعهٔ دیگری را انتخاب و «چسباندن» را بزنید.`); }} data-testid="graph-copy">کپیِ کلیدها</button>
        <button type="button" className="ws-btn" disabled={!copied || copied.ch !== ch} onClick={() => copied && write(copied.keys.filter((k) => k.t <= len + 0.02).map((k) => ({ ...k, t: r3(Math.min(len, k.t)) })), false, "چسباندنِ کلیدها")} data-testid="graph-paste" title={copied ? `کلیدهای «${KF_TITLE[copied.ch]}» را روی این قطعه می‌گذارد` : "اول کلیدها را کپی کنید"}>چسباندنِ کلیدها</button>
        <button type="button" className="ws-btn" disabled={!keys.length} onClick={() => { write([], false, "پاک‌کردنِ کلیدها"); setSel(null); }} data-testid="graph-clear">پاک‌کردنِ همهٔ کلیدها</button>
      </div>
      {s ? (
        <div className="kg-key-edit" data-testid="graph-key-edit">
          <label className="ws-field"><span>زمان (ثانیه)</span><input className="u-input" type="number" dir="ltr" step={0.05} value={s.t} onChange={(e) => edit({ t: Number(e.target.value) })} data-testid="graph-key-t" /></label>
          <label className="ws-field"><span>مقدار</span><input className="u-input" type="number" dir="ltr" step={0.05} value={s.v} onChange={(e) => edit({ v: Number(e.target.value) })} data-testid="graph-key-v" /></label>
          <label className="ws-field"><span>شیب تا کلیدِ بعدی</span>
            <select className="u-input" value={s.e} onChange={(e) => edit({ e: e.target.value as Easing })} data-testid="graph-key-e">
              {EASINGS.map((x) => <option key={x.key} value={x.key}>{x.title}</option>)}
            </select>
          </label>
          <button type="button" className="ws-btn" onClick={() => { write(removeKey(keys, s.t), false, "حذفِ کلید"); setSel(null); }} data-testid="graph-key-delete">حذفِ این کلید</button>
        </div>
      ) : (
        <p className="ws-hint">{keys.length ? "روی یک نقطه بزنید تا زمان، مقدار و نوعِ شیبش را بنویسید." : `هنوز کلیدی روی «${KF_TITLE[ch]}» نیست؛ مقدارِ ثابتِ ${r3(dflt)} است. یک کلید بگذارید تا انیمیشن بسازید.`}</p>
      )}
    </div>
  );
}
