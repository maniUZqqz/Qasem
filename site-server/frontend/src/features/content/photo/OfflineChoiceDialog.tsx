import { useEffect, useRef, useState } from "react";

import { Button } from "../../../components/ui";
import "./designer/designer.css";

/**
 * «سرورِ پردازش الان خاموش است» — هر بار که «ویرایش با دستور» خواسته می‌شود و سرور خاموش است از کاربر می‌پرسیم (تصمیمِ مالک):
 * با هوشِ سادهٔ سایت همین حالا، یا در صفِ ماندگار بماند تا سرور روشن شود. «به‌خاطر بسپار» در تنظیماتِ ادیتورِ عکس ذخیره می‌شود و آن‌جا عوض می‌شود.
 */
export default function OfflineChoiceDialog({ onChoose, onCancel }: { onChoose: (choice: "site" | "queue", remember: boolean) => void; onCancel: () => void }) {
  const [remember, setRemember] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  useEffect(() => {
    root.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        onCancel();
      }
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [onCancel]);
  return (
    <div className="es-overlay" onMouseDown={(e) => e.target === e.currentTarget && onCancel()} data-testid="offline-choice">
      <div className="es-dialog" role="dialog" aria-modal="true" aria-label="سرورِ پردازش خاموش است" tabIndex={-1} ref={root} style={{ maxWidth: 520 }}>
        <div className="es-head"><b>سرورِ پردازش الان خاموش است</b></div>
        <p className="mb-3 text-sm" style={{ color: "var(--text-2)" }}>
          «ویرایش با دستور» به یک هوشِ مصنوعیِ بینا نیاز دارد که کاملش روی سرورِ پردازش است. چطور ادامه بدهیم؟
        </p>
        <div className="flex flex-col gap-2">
          <button type="button" className="dz-link" style={{ textAlign: "start", border: "1px solid var(--border, #e5e7eb)", borderRadius: 10, padding: 10 }} onClick={() => onChoose("site", remember)} data-testid="choice-site">
            <b>همین حالا با هوشِ سادهٔ سایت</b>
            <br /><span className="ws-muted" style={{ fontSize: 12 }}>نتیجه فوری است ولی ساده‌تر: هوشِ مصنوعیِ سایت (اگر جواب داد) یا فقط نور و رنگِ خودکارِ سبک.</span>
          </button>
          <button type="button" className="dz-link" style={{ textAlign: "start", border: "1px solid var(--border, #e5e7eb)", borderRadius: 10, padding: 10 }} onClick={() => onChoose("queue", remember)} data-testid="choice-queue">
            <b>منتظرِ سرورِ پردازش بماند (در صف)</b>
            <br /><span className="ws-muted" style={{ fontSize: 12 }}>کار گم نمی‌شود؛ هر وقت سرور روشن شد با هوشِ کامل خودکار انجام می‌شود (ممکن است ساعت‌ها طول بکشد).</span>
          </button>
        </div>
        <label className="mt-3 flex items-center gap-2 text-sm" style={{ cursor: "pointer" }}>
          <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} data-testid="choice-remember" />
          انتخابِ من را به‌خاطر بسپار (بعداً در «تنظیمات ‹ کمکِ هوش مصنوعی» عوض می‌شود)
        </label>
        <div className="mt-3"><Button variant="secondary" onClick={onCancel} data-testid="choice-cancel">انصراف</Button></div>
      </div>
    </div>
  );
}
