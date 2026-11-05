import { FORMATS } from "./model";

/** وقتی پروژه خالی است: چند کارِ روشن به‌جای یک صفحهٔ خالی. */
export default function QuickStart({ onFormat, formatKey, onDirector, onAdd }: {
  onFormat: (key: string) => void;
  formatKey: string;
  onDirector?: () => void;
  onAdd: () => void;
}) {
  return (
    <div className="qs-box" dir="rtl" data-testid="quick-start">
      <b>از کجا شروع کنیم؟</b>
      <div className="qs-row">
        <button type="button" className="ws-btn primary" onClick={onAdd} data-testid="qs-add" title="ویدیو یا عکس را از «رسانه‌ها» بکشید روی تایم‌لاین، یا دوبار روی آن کلیک کنید">① ویدیو یا عکس بیاورید</button>
        {onDirector && <button type="button" className="ws-btn" onClick={onDirector} data-testid="qs-director" title="دستور بدهید تا کارگردان خودش تدوین کند و نتیجه همین‌جا قابل‌ویرایش بماند">✨ یا به کارگردان بسپارید</button>}
      </div>
      <div className="qs-row">
        <span className="ws-hint">قابِ ویدیو:</span>
        {FORMATS.slice(0, 4).map((f) => (
          <button key={f.key} type="button" className={`ws-chip ${formatKey === f.key ? "is-on" : ""}`} onClick={() => onFormat(f.key)} data-testid={`qs-format-${f.key}`}>{f.title}</button>
        ))}
      </div>
      <p className="ws-hint">بعد: تقسیم با S، حذف با Delete، موسیقی و گویندگی از تبِ «صدا»، متن با T. برای دیدنِ همهٔ میان‌برها «؟» را بزنید.</p>
    </div>
  );
}
