import { ReactNode, useEffect, useRef, useState } from "react";

import { errorMessage } from "../../api/client";
import { Input } from "../../components/ui";
import { Character, Option } from "./api";

export const hexOk = (v: string) => /^#[0-9a-f]{6}$/i.test(v);

export function ColourField({ label, value, disabled, swatches, onChange }: { label: string; value: string; disabled?: boolean; swatches?: string[]; onChange: (v: string) => void }) {
  return (
    <div className="bc-colour">
      <span className="bc-colour-label">{label}</span>
      <span className="bc-colour-row">
        <input type="color" value={hexOk(value) ? value : "#000000"} disabled={disabled} onChange={(e) => onChange(e.target.value)} aria-label={label} />
        <Input type="text" value={value} disabled={disabled} maxLength={7} onChange={(e) => onChange(e.target.value)} aria-label={`${label} (کد رنگ)`} />
      </span>
      {swatches && swatches.length ? (
        <span className="bc-swatches" role="group" aria-label="رنگ‌های برند">
          {swatches.map((s) => (
            <button key={s} type="button" disabled={disabled} className="bc-swatch" style={{ background: s }} title={s} aria-label={`رنگِ ${s}`} onClick={() => onChange(s)} />
          ))}
        </span>
      ) : null}
    </div>
  );
}

export function Chips({ options, value, disabled, onChange, label }: { options: Option[]; value: string; disabled?: boolean; onChange: (v: string) => void; label?: string }) {
  return (
    <div className="bc-chips" role="group" aria-label={label}>
      {options.map((o) => (
        <button key={o.key} type="button" className="bc-chip" aria-pressed={value === o.key} disabled={disabled} onClick={() => onChange(o.key)}>
          {o.fa}
        </button>
      ))}
    </div>
  );
}

export function ListEditor({ items, max, maxLen, placeholder, onChange, disabled }: { items: string[]; max: number; maxLen: number; placeholder: string; onChange: (v: string[]) => void; disabled?: boolean }) {
  const [text, setText] = useState("");
  const add = () => {
    const t = text.trim().slice(0, maxLen);
    if (!t || items.includes(t) || items.length >= max) return;
    onChange([...items, t]);
    setText("");
  };
  return (
    <div className="bc-list">
      <div className="bc-list-items">
        {items.map((it, i) => (
          <span key={`${it}-${i}`} className="bc-tag">
            {it}
            <button type="button" disabled={disabled} aria-label={`حذفِ ${it}`} onClick={() => onChange(items.filter((_, j) => j !== i))}>
              ×
            </button>
          </span>
        ))}
        {!items.length ? <span className="bc-muted">هنوز چیزی نیست</span> : null}
      </div>
      <div className="bc-list-add">
        <Input
          value={text}
          disabled={disabled || items.length >= max}
          maxLength={maxLen}
          placeholder={items.length >= max ? "به سقف رسیده‌اید" : placeholder}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              add();
            }
          }}
        />
        <button type="button" className="bc-chip" disabled={disabled || !text.trim() || items.length >= max} onClick={add}>
          افزودن
        </button>
      </div>
    </div>
  );
}

export function CharPicker({ chars, value, onChange, onAdd, addLabel = "شخصیتِ تازه", disabled }: { chars: Character[]; value: number | null; onChange: (id: number) => void; onAdd?: () => void; addLabel?: string; disabled?: boolean }) {
  return (
    <div className="bc-charlist" role="group" aria-label="شخصیت‌های برند">
      {chars.map((c) => (
        <button key={c.id} type="button" className="bc-char" aria-pressed={value === c.id} onClick={() => onChange(c.id)}>
          {c.cover ? <img src={c.cover} alt="" loading="lazy" /> : <span className="bc-char-ph">{c.style_fa}</span>}
          <b>{c.name}</b>
          <small>
            {c.style_fa}
            {c.is_primary ? " · اصلی" : ""}
            {c.locked ? ` · قفل v${c.version}` : ""}
          </small>
        </button>
      ))}
      {onAdd ? (
        <button type="button" className="bc-char bc-char-add" onClick={onAdd} disabled={disabled}>
          <span aria-hidden>＋</span>
          <b>{addLabel}</b>
        </button>
      ) : null}
    </div>
  );
}

export function Section({ title, hint, children, action, id }: { title: string; hint?: string; children: ReactNode; action?: ReactNode; id?: string }) {
  return (
    <section className="bc-card" id={id}>
      <header className="bc-card-head">
        <div>
          <h2>{title}</h2>
          {hint ? <p>{hint}</p> : null}
        </div>
        {action}
      </header>
      {children}
    </section>
  );
}

/** پیام‌های موقتِ «انجام شد» و خطا برای یک صفحه. */
export function useNotice() {
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const timer = useRef<number | null>(null);
  useEffect(() => () => {
    if (timer.current) window.clearTimeout(timer.current);
  }, []);
  const ok = (m: string) => {
    setError(null);
    setNotice(m);
    if (timer.current) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setNotice(null), 5000);
  };
  const fail = (e: unknown) => {
    setNotice(null);
    setError(errorMessage(e));
  };
  return { notice, error, ok, fail, clear: () => { setNotice(null); setError(null); } };
}

export const fmtDate = (s?: string | null) => {
  if (!s) return "";
  try {
    return new Date(s).toLocaleString("fa-IR", { dateStyle: "medium", timeStyle: "short" });
  } catch {
    return s;
  }
};
