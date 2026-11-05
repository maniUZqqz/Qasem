import { useEffect, useRef } from "react";

type Row = { keys: string; text: string };

const GENERAL: Row[] = [
  { keys: "Ctrl + Z", text: "برگشت" },
  { keys: "Ctrl + Shift + Z  یا  Ctrl + Y", text: "جلو" },
  { keys: "Ctrl + J", text: "رونوشتِ لایهٔ فعال" },
  { keys: "Ctrl + E", text: "تلفیقِ لایه با لایهٔ زیرین" },
  { keys: "Ctrl + G  /  Ctrl + Shift + G", text: "گروه کردن / بازکردنِ گروه" },
  { keys: "Ctrl + D", text: "برداشتنِ انتخاب" },
  { keys: "Ctrl + Shift + I", text: "معکوسِ انتخاب" },
  { keys: "Delete", text: "حذفِ لایهٔ فعال" },
  { keys: "کلیدهای جهت (Shift = ده برابر)", text: "جابه‌جاییِ دقیقِ لایه" },
  { keys: "0  /  1  /  +  /  −", text: "جا شدن / ۱۰۰٪ / بزرگ‌نمایی / کوچک‌نمایی" },
  { keys: "Space (نگه‌داشتن)", text: "موقتاً دست (جابه‌جاییِ نما)" },
  { keys: "\\", text: "نمایشِ «قبل»" },
  { keys: "[  /  ]", text: "کوچک/بزرگ‌کردنِ قلم (Shift = سختی)" },
  { keys: "X", text: "جابه‌جاییِ رنگ‌کن ⇄ پاک‌کن" },
  { keys: "؟  یا  ?", text: "همین راهنما" },
];

const CROP: Row[] = [
  { keys: "C", text: "ابزارِ برش" },
  { keys: "Enter", text: "اعمالِ برش" },
  { keys: "Esc", text: "انصرافِ برش (به حالتِ پیش از ورود برمی‌گردد)" },
  { keys: "بکشید", text: "داخلِ قاب = جابه‌جایی؛ گوشه/لبه = اندازه؛ بیرونِ قاب = قابِ تازه" },
];

export type ToolRow = { key: string; title: string };

export default function Shortcuts({ tools, onClose }: { tools: ToolRow[]; onClose: () => void }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    ref.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" || e.key === "?" || e.key === "؟") {
        e.preventDefault();
        e.stopImmediatePropagation(); // تمام‌صفحه با همین Esc بسته نشود
        onClose();
      }
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [onClose]);
  const table = (title: string, rows: Row[]) => (
    <section className="sc-sec">
      <h3>{title}</h3>
      <dl>
        {rows.map((r) => (
          <div key={r.keys + r.text} className="sc-row">
            <dt dir="ltr">{r.keys}</dt>
            <dd>{r.text}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
  return (
    <div className="sc-backdrop" onClick={onClose} role="presentation" data-testid="shortcuts">
      <div className="sc-box" role="dialog" aria-modal="true" aria-label="راهنمای کلیدهای میان‌بر" tabIndex={-1} ref={ref} onClick={(e) => e.stopPropagation()} dir="rtl">
        <div className="sc-head">
          <b>راهنمای کلیدهای میان‌بر</b>
          <button type="button" className="ws-btn" onClick={onClose} data-testid="shortcuts-close">بستن (Esc)</button>
        </div>
        <div className="sc-grid">
          {table("ابزارها (فقط حرفِ لاتین، با زبانِ انگلیسیِ صفحه‌کلید)", tools.map((t) => ({ keys: t.key, text: t.title })))}
          {table("برش", CROP)}
          {table("کارهای همه‌جا", GENERAL)}
        </div>
        <p className="sc-foot">روی هر دکمه نگه دارید تا توضیحِ فارسی‌اش دیده شود. اگر ابزاری در نوار نیست «⋯ بیشتر» را بزنید؛ کلیدش هم کار می‌کند.</p>
      </div>
    </div>
  );
}
