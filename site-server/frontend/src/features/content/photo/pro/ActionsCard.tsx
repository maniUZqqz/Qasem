import { useState } from "react";

import { Spinner, fa } from "../../../../components/ui";
import type { Preset } from "../api";
import { ActionStep, describeStep, parseAction } from "./actions";

export type RecState = { steps: ActionStep[]; skipped: number };

type Props = {
  /** ضبط روشن است */
  rec: RecState | null;
  /** ضبط تمام شد و منتظرِ نام است */
  pending: RecState | null;
  saved: Preset[] | null;
  err: string;
  busy: boolean;
  onStart: () => void;
  onStop: () => void;
  onDiscard: () => void;
  onSave: (name: string) => void;
  onPlay: (p: Preset) => void;
  onRemove: (p: Preset) => void;
};

/** کارتِ «اکشن‌ها» در زبانهٔ تاریخچه: ضبطِ کارهای تکراری و اجرای یک‌کلیکیِ آن‌ها روی هر عکس (نوبت ۶) */
export default function ActionsCard(p: Props) {
  const [name, setName] = useState("");
  const live = p.rec ?? p.pending;
  return (
    <div className="ws-card" data-testid="actions-card">
      <div className="ws-card-title">اکشن‌ها (ضبطِ کارهای تکراری)</div>
      <p className="ws-hint">یک بار کارها را انجام دهید (نور و رنگ، برش، متن، لوگو…) و ضبط کنید؛ بعد روی هر عکسِ دیگر با یک کلیک اجرا می‌شود. نقاشی و ترمیمِ همان عکس ضبط نمی‌شود.</p>
      {!p.rec && !p.pending && (
        <button type="button" className="ws-btn primary" onClick={p.onStart} data-testid="action-start">شروعِ ضبط</button>
      )}
      {p.rec && (
        <div className="pw-rec" data-testid="action-recording" role="status">
          <b className="pw-rec-dot">● در حالِ ضبط</b> — {fa(p.rec.steps.length)} گام
          <button type="button" className="ws-btn primary" onClick={p.onStop} data-testid="action-stop">پایان و ذخیره</button>
          <button type="button" className="ws-btn" onClick={p.onDiscard} data-testid="action-discard">دور بریز</button>
        </div>
      )}
      {live && live.steps.length > 0 && (
        <ol className="pw-act-steps" data-testid="action-steps">
          {live.steps.map((s, i) => (
            <li key={i}><span>{fa(i + 1)}.</span> {describeStep(s)}</li>
          ))}
        </ol>
      )}
      {live && live.skipped > 0 && <p className="ws-hint" data-testid="action-skipped">{fa(live.skipped)} کارِ وابسته به پیکسلِ همین عکس (نقاشی، ترمیم، عکسِ دیگر…) ضبط نشد.</p>}
      {p.pending && !p.rec && (
        <div className="flex gap-1" data-testid="action-save-row">
          <input className="u-input" value={name} maxLength={80} placeholder="نامِ اکشن (مثلاً «لوگو و روشن‌تر»)" onChange={(e) => setName(e.target.value)} aria-label="نامِ اکشن" data-testid="action-name"
            onKeyDown={(e) => e.key === "Enter" && name.trim() && (p.onSave(name.trim()), setName(""))} />
          <button type="button" className="ws-btn primary" disabled={!name.trim() || p.busy} onClick={() => { p.onSave(name.trim()); setName(""); }} data-testid="action-save">ذخیره</button>
          <button type="button" className="ws-btn" onClick={p.onDiscard}>دور بریز</button>
        </div>
      )}
      {p.err && <p className="ws-hint" role="alert">{p.err}</p>}
      <div className="ws-card-title" style={{ marginTop: 10 }}>اکشن‌های ذخیره‌شده</div>
      {p.saved === null && !p.err && <div className="pn-muted"><Spinner size={14} /> در حالِ بارگذاری…</div>}
      <ul className="pw-snaps" data-testid="actions-list">
        {(p.saved ?? []).map((a) => {
          const n = parseAction(a.data)?.steps.length ?? 0;
          return (
            <li key={a.id} data-action={a.id}>
              <b>{a.name}</b>
              <span className="ws-muted">{fa(n)} گام</span>
              <span className="pw-snap-btns">
                <button type="button" className="ws-btn primary" disabled={p.busy || n === 0} onClick={() => p.onPlay(a)} data-testid={`action-play-${a.id}`} title="روی عکسِ باز اجرا می‌شود؛ با Ctrl+Z یک‌جا برمی‌گردد">اجرا</button>
                <button type="button" className="ws-btn" aria-label="حذفِ اکشن" disabled={p.busy} onClick={() => p.onRemove(a)} data-testid={`action-del-${a.id}`}>🗑</button>
              </span>
            </li>
          );
        })}
        {p.saved && !p.saved.length && <li className="ws-muted">هنوز اکشنی ذخیره نکرده‌اید.</li>}
      </ul>
    </div>
  );
}
