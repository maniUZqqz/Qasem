import { InputHTMLAttributes, ReactNode, TextareaHTMLAttributes, useEffect, useRef, useState } from "react";

import { Input, TextArea } from "../../../../components/ui";

/**
 * ورودی‌های «پیش‌نویسی»: مقدار را محلی نگه می‌دارند و فقط هنگامِ ترکِ فیلد (یا Enter) به سند می‌نویسند.
 * دلیلش undo است: هر تغییرِ سند یک پلهٔ تاریخچه است، و پلهٔ تاریخچه به‌ازای هر حرفِ تایپ‌شده بی‌معناست.
 * (ویرایشگرِ قدیمی هم روی رویدادِ change کار می‌کرد، نه input.)
 */

type InputRest = Omit<InputHTMLAttributes<HTMLInputElement>, "value" | "onChange" | "onBlur" | "onKeyDown" | "type">;

export function DraftInput({ value, onCommit, ...rest }: { value: string; onCommit: (v: string) => void } & InputRest) {
  const [draft, setDraft] = useState(value);
  useEffect(() => setDraft(value), [value]);
  const commit = () => {
    if (draft !== value) onCommit(draft);
  };
  return (
    <Input
      {...rest}
      type="text"
      value={draft}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === "Enter") (e.target as HTMLInputElement).blur();
      }}
    />
  );
}

export function DraftNumber({
  value,
  onCommit,
  ...rest
}: { value: number | null | undefined; onCommit: (v: number | null) => void } & InputRest) {
  const text = value == null ? "" : String(value);
  const [draft, setDraft] = useState(text);
  useEffect(() => setDraft(text), [text]);
  const commit = () => {
    if (draft === text) return;
    if (draft.trim() === "") onCommit(null);
    else {
      const n = Number(draft);
      if (Number.isFinite(n)) onCommit(n);
      else setDraft(text);
    }
  };
  return (
    <Input
      {...rest}
      type="number"
      dir="ltr"
      value={draft}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === "Enter") (e.target as HTMLInputElement).blur();
      }}
    />
  );
}

type AreaRest = Omit<TextareaHTMLAttributes<HTMLTextAreaElement>, "value" | "onChange" | "onBlur">;

export function DraftTextArea({ value, onCommit, ...rest }: { value: string; onCommit: (v: string) => void } & AreaRest) {
  const [draft, setDraft] = useState(value);
  useEffect(() => setDraft(value), [value]);
  return (
    <TextArea
      {...rest}
      value={draft}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={() => {
        if (draft !== value) onCommit(draft);
      }}
    />
  );
}

/** اسلایدر: هنگامِ کشیدن فقط پیش‌نویس، هنگامِ رها کردن نوشتن. */
export function DraftRange({
  value,
  min,
  max,
  step,
  onCommit,
}: {
  value: number;
  min: number;
  max: number;
  step: number;
  onCommit: (v: number) => void;
}) {
  const [draft, setDraft] = useState(value);
  useEffect(() => setDraft(value), [value]);
  const commit = () => {
    if (draft !== value) onCommit(draft);
  };
  return (
    <input
      type="range"
      className="w-full"
      min={min}
      max={max}
      step={step}
      value={draft}
      onChange={(e) => setDraft(Number(e.target.value))}
      onPointerUp={commit}
      onKeyUp={commit}
      onBlur={commit}
    />
  );
}

/** رنگ: رویدادِ input ِ مرورگر هنگامِ کشیدن در پالت پشتِ سرِ هم می‌آید؛ فقط رویدادِ change (بستنِ پالت) نوشته می‌شود. */
export function ColorInput({ value, onCommit }: { value: string; onCommit: (v: string) => void }) {
  const ref = useRef<HTMLInputElement>(null);
  const [draft, setDraft] = useState(value || "#ffffff");
  useEffect(() => setDraft(value || "#ffffff"), [value]);
  const latest = useRef(onCommit);
  latest.current = onCommit;
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const h = () => latest.current(el.value);
    el.addEventListener("change", h);
    return () => el.removeEventListener("change", h);
  }, []);
  return (
    <input
      ref={ref}
      type="color"
      className="u-input"
      style={{ width: 64, height: 38, padding: 2 }}
      value={draft}
      onChange={(e) => setDraft(e.target.value)}
    />
  );
}

export function Details({ summary, children, open }: { summary: string; children: ReactNode; open?: boolean }) {
  return (
    <details open={open} className="mt-1">
      <summary className="cursor-pointer text-xs" style={{ color: "var(--text-3)" }}>
        {summary}
      </summary>
      <div className="mt-2 space-y-2">{children}</div>
    </details>
  );
}

export function SubCard({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="space-y-2 rounded-xl p-3" style={{ background: "var(--surface-2)", border: "1px solid var(--line)" }}>
      <b className="block text-sm" style={{ color: "var(--text)" }}>
        {title}
      </b>
      {children}
    </div>
  );
}

export function Grid2({ children }: { children: ReactNode }) {
  return <div className="grid grid-cols-2 gap-2">{children}</div>;
}

export function Hr() {
  return <hr className="my-3" style={{ border: 0, borderTop: "1px solid var(--line)" }} />;
}

export function H3({ children }: { children: ReactNode }) {
  return (
    <h3 className="font-bold" style={{ color: "var(--text)" }}>
      {children}
    </h3>
  );
}
