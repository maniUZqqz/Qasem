import { useEffect, useRef, useState } from "react";

import { fa } from "../../../../../components/ui";
import { IDENTITY_XFORM, SelXform } from "../selxform";
import "../../designer/designer.css";

/** «تبدیلِ انتخاب» (دورِ ۸): بزرگ/کوچک (افقی و عمودی)، چرخش و جابه‌جاییِ خودِ ناحیهٔ انتخاب؛ پیش‌نمایشِ زنده روی همان انتخاب. */
export default function SelXformDialog({ w, h, onPreview, onApply, onCancel }: {
  w: number; h: number;
  onPreview: (t: SelXform) => void;
  onApply: (t: SelXform) => void;
  onCancel: () => void;
}) {
  const [t, setT] = useState<SelXform>(IDENTITY_XFORM);
  const [lock, setLock] = useState(true);
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
  const set = (p: Partial<SelXform>) => {
    const n = { ...t, ...p };
    if (lock && ("sx" in p || "sy" in p)) {
      n.sx = p.sx ?? p.sy ?? n.sx;
      n.sy = p.sy ?? p.sx ?? n.sy;
    }
    setT(n);
    onPreview(n);
  };
  const row = (label: string, k: keyof SelXform, min: number, max: number, step: number, shown: (v: number) => string, id: string) => (
    <label className="fx-row">
      <span>{label}</span>
      <span className="fx-range">
        <input type="range" min={min} max={max} step={step} value={t[k]} onChange={(e) => set({ [k]: Number(e.target.value) } as Partial<SelXform>)} data-testid={id} />
        <b dir="ltr">{shown(t[k])}</b>
      </span>
    </label>
  );
  return (
    <div className="fx-overlay" onMouseDown={(e) => e.target === e.currentTarget && onCancel()} data-testid="selxform-dialog">
      <div className="fx-dialog" role="dialog" aria-modal="true" aria-label="تبدیلِ انتخاب" tabIndex={-1} ref={root} dir="rtl" style={{ width: "min(480px, 100%)", maxHeight: "none" }}>
        <div className="fx-head"><b>تبدیلِ انتخاب</b><button type="button" className="fx-x" onClick={onCancel} aria-label="بستن">✕</button></div>
        <div className="fx-form" style={{ padding: 14 }}>
          {row("پهنا", "sx", 0.1, 3, 0.01, (v) => `${fa(Math.round(v * 100))}%`, "sx-pw")}
          {row("ارتفاع", "sy", 0.1, 3, 0.01, (v) => `${fa(Math.round(v * 100))}%`, "sx-ph")}
          <label className="fx-row"><span>قفلِ نسبت</span><input type="checkbox" checked={lock} onChange={(e) => setLock(e.target.checked)} data-testid="sx-lock" /></label>
          {row("چرخش", "rot", -180, 180, 1, (v) => `${fa(Math.round(v))}°`, "sx-rot")}
          {row("جابه‌جاییِ افقی", "dx", -w / 2, w / 2, 1, (v) => `${fa(Math.round(v))}px`, "sx-dx")}
          {row("جابه‌جاییِ عمودی", "dy", -h / 2, h / 2, 1, (v) => `${fa(Math.round(v))}px`, "sx-dy")}
        </div>
        <div className="fx-foot">
          <button type="button" className="ws-btn primary" onClick={() => onApply(t)} data-testid="sx-apply">اعمال</button>
          <button type="button" className="ws-btn" onClick={() => { setT(IDENTITY_XFORM); onPreview(IDENTITY_XFORM); }}>بازنشانی</button>
          <button type="button" className="ws-btn" onClick={onCancel}>انصراف</button>
        </div>
      </div>
    </div>
  );
}
