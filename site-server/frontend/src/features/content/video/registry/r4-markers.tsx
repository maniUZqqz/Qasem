import { useEffect, useRef, useState } from "react";

import { fa } from "../../../../components/ui";
import { Marker, addMarker, clearMarkers, removeMarker, timecode } from "../manual/model";
import { parseTime } from "../manual/r4ops";
import type { PanelProps } from "./types";

const COLORS = ["#facc15", "#f87171", "#fb923c", "#34d399", "#38bdf8", "#a78bfa"];
const KIND_FA: Record<Marker["kind"], string> = { marker: "نشانگر", chapter: "فصل", beat: "ضرب" };

function Row({ m, onSeek, onChange, onDelete }: { m: Marker; onSeek: () => void; onChange: (patch: Partial<Marker>) => void; onDelete: () => void }) {
  const [label, setLabel] = useState(m.label);
  const [time, setTime] = useState<string | null>(null);
  useEffect(() => setLabel(m.label), [m.label]);
  const nextColor = COLORS[(COLORS.indexOf(m.color) + 1) % COLORS.length];
  return (
    <li className="mk-row" data-testid="marker-row" data-marker={m.id}>
      <button type="button" className="mk-dot" style={{ background: m.color }} onClick={() => onChange({ color: nextColor })} title="رنگ را عوض کن" aria-label="تغییرِ رنگِ نشانگر" data-testid="marker-color" />
      {time === null ? (
        <button type="button" className="mk-time" dir="ltr" onClick={onSeek} onDoubleClick={() => setTime(timecode(m.t))} title="کلیک = رفتن به این نشانگر؛ دوبار کلیک = ویرایشِ زمان" data-testid="marker-time">{timecode(m.t)}</button>
      ) : (
        <input className="u-input mk-time-in" dir="ltr" autoFocus value={time} onChange={(e) => setTime(e.target.value)} aria-label="زمانِ نشانگر"
          onBlur={() => { const v = parseTime(time); if (v !== null) onChange({ t: v }); setTime(null); }}
          onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); if (e.key === "Escape") setTime(null); }} />
      )}
      <input className="u-input mk-label" value={label} placeholder={KIND_FA[m.kind]} aria-label="نامِ نشانگر" data-testid="marker-label"
        onChange={(e) => setLabel(e.target.value)} onBlur={() => label !== m.label && onChange({ label: label.slice(0, 80) })}
        onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }} />
      <select className="u-input mk-kind" value={m.kind} onChange={(e) => onChange({ kind: e.target.value as Marker["kind"] })} aria-label="نوعِ نشانگر">
        {(Object.keys(KIND_FA) as Marker["kind"][]).map((k) => <option key={k} value={k}>{KIND_FA[k]}</option>)}
      </select>
      <button type="button" className="ws-btn" onClick={onDelete} aria-label="حذفِ نشانگر" title="حذف" data-testid="marker-delete">×</button>
    </li>
  );
}

/** فهرستِ نشانگرها: نام، رنگ، نوع و زمانِ هر کدام را ویرایش کنید؛ روی زمان بزنید تا سرِ پخش بپرد. */
export default function MarkersPanel({ api }: PanelProps) {
  const ms = [...(api.project.markers ?? [])].sort((a, b) => a.t - b.t);
  const patch = (id: string, p: Partial<Marker>) => api.apply("ویرایشِ نشانگر", (pr) => ({ ...pr, markers: (pr.markers ?? []).map((m) => (m.id === id ? { ...m, ...p, t: Math.max(0, p.t ?? m.t) } : m)).sort((a, b) => a.t - b.t) }));
  const box = useRef<HTMLUListElement>(null);
  return (
    <div data-testid="markers-panel">
      <div className="mk-top">
        <button type="button" className="ws-btn primary" onClick={() => api.apply("نشانگر", (p) => addMarker(p, api.time, ""))} data-testid="marker-add">+ نشانگر در سرِ پخش</button>
        <button type="button" className="ws-btn" onClick={() => api.apply("نشانگرِ فصل", (p) => addMarker(p, api.time, "فصل", "chapter"))}>+ فصل</button>
        <button type="button" className="ws-btn" disabled={ms.length === 0} onClick={() => window.confirm("همهٔ نشانگرها پاک شود؟") && api.apply("پاک‌کردنِ نشانگرها", (p) => clearMarkers(p))}>پاک‌کردنِ همه</button>
      </div>
      {ms.length === 0 ? (
        <p className="ws-hint" data-testid="markers-empty">هنوز نشانگری نیست. با کلیدِ M یا دکمهٔ بالا در سرِ پخش بگذارید؛ برش‌ها به نشانگرها می‌چسبند.</p>
      ) : (
        <>
          <p className="ws-hint">{fa(ms.length)} نشانگر. روی دایرهٔ رنگی بزنید تا رنگ عوض شود؛ روی زمان بزنید تا آن‌جا بپرید.</p>
          <ul className="mk-list" ref={box}>
            {ms.map((m) => <Row key={m.id} m={m} onSeek={() => api.seek(m.t)} onChange={(p) => patch(m.id, p)} onDelete={() => api.apply("حذفِ نشانگر", (pr) => removeMarker(pr, m.id))} />)}
          </ul>
        </>
      )}
    </div>
  );
}
