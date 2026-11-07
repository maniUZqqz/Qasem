import { useEffect, useMemo, useRef, useState } from "react";

import { fa } from "../../../../../components/ui";
import { colorRangeMask, coverage } from "../selectionOps";
import "./effects.css";

/** پنجرهٔ کوچکِ «مقدار»: برای گسترش، انقباض، هموارسازی و حاشیهٔ انتخاب. */
export function AmountDialog({ title, hint, min, max, def, unit = "px", onApply, onClose }: { title: string; hint: string; min: number; max: number; def: number; unit?: string; onApply: (v: number) => void; onClose: () => void }) {
  const [v, setV] = useState(def);
  const root = useRef<HTMLDivElement>(null);
  useEffect(() => {
    root.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose();
      } else if (e.key === "Enter") {
        e.stopPropagation();
        onApply(v);
      }
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [v, onApply, onClose]);
  return (
    <div className="fx-overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()} data-testid="amount-dialog">
      <div className="fx-dialog" style={{ width: "min(420px, 100%)", maxHeight: "none" }} role="dialog" aria-modal="true" aria-label={title} tabIndex={-1} ref={root} dir="rtl">
        <div className="fx-head"><b>{title}</b><button type="button" className="fx-x" onClick={onClose} aria-label="بستن">✕</button></div>
        <div className="fx-form" style={{ padding: 14 }}>
          <p className="fx-note">{hint}</p>
          <label className="fx-row">
            <span>مقدار</span>
            <span className="fx-range"><input type="range" min={min} max={max} value={v} onChange={(e) => setV(Number(e.target.value))} data-testid="amount-range" /><b dir="ltr">{fa(v)} {unit}</b></span>
          </label>
        </div>
        <div className="fx-foot">
          <button type="button" className="ws-btn primary" onClick={() => onApply(v)} data-testid="amount-apply">اعمال</button>
          <button type="button" className="ws-btn" onClick={onClose}>انصراف</button>
        </div>
      </div>
    </div>
  );
}

/** «بازهٔ رنگ / عصای جادویی»: روی نمونهٔ تصویر کلیک کنید ⇒ همهٔ رنگ‌های مشابه (یا فقط ناحیهٔ پیوسته) انتخاب می‌شود. */
export function ColorRangeDialog({ getSource, onApply, onClose }: { getSource: () => Promise<HTMLCanvasElement>; onApply: (mask: HTMLCanvasElement, mode: "new" | "add" | "sub") => void; onClose: () => void }) {
  const [src, setSrc] = useState<HTMLCanvasElement | null>(null);
  const [seed, setSeed] = useState<[number, number] | null>(null);
  const [color, setColor] = useState<[number, number, number] | null>(null);
  const [tol, setTol] = useState(30);
  const [contig, setContig] = useState(false);
  const [feather, setFeather] = useState(1);
  const [mode, setMode] = useState<"new" | "add" | "sub">("new");
  const [err, setErr] = useState<string | null>(null);
  const view = useRef<HTMLCanvasElement>(null);
  const root = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let live = true;
    getSource()
      .then((c) => {
        if (!live) return;
        const k = Math.min(1, 640 / Math.max(c.width, c.height));
        const s = document.createElement("canvas");
        s.width = Math.max(8, Math.round(c.width * k));
        s.height = Math.max(8, Math.round(c.height * k));
        s.getContext("2d", { willReadFrequently: true })!.drawImage(c, 0, 0, s.width, s.height);
        setSrc(s);
      })
      .catch((e) => live && setErr(e instanceof Error ? e.message : "تصویر آماده نشد."));
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const mask = useMemo(() => (src && color ? colorRangeMask(src, { seed, color, tol, contiguous: contig, feather: Math.max(0, feather * (src.width / 640)) }) : null), [src, color, seed, tol, contig, feather]);
  const cov = useMemo(() => (mask ? coverage(mask) : 0), [mask]);

  // نمایش: تصویر + پوششِ قرمزِ ناحیهٔ انتخاب
  useEffect(() => {
    const cv = view.current;
    if (!cv || !src) return;
    cv.width = src.width;
    cv.height = src.height;
    const x = cv.getContext("2d")!;
    x.drawImage(src, 0, 0);
    if (mask) {
      const t = document.createElement("canvas");
      t.width = src.width;
      t.height = src.height;
      const tx = t.getContext("2d", { willReadFrequently: true })!;
      tx.drawImage(mask, 0, 0, t.width, t.height);
      const d = tx.getImageData(0, 0, t.width, t.height);
      for (let i = 0; i < d.data.length; i += 4) {
        const a = d.data[i] / 255;
        d.data[i] = 255;
        d.data[i + 1] = 40;
        d.data[i + 2] = 80;
        d.data[i + 3] = Math.round(a * 140);
      }
      tx.putImageData(d, 0, 0);
      x.drawImage(t, 0, 0);
    }
  }, [src, mask]);

  const pick = (e: React.MouseEvent<HTMLCanvasElement>) => {
    if (!src) return;
    const r = e.currentTarget.getBoundingClientRect();
    const px = Math.floor(((e.clientX - r.left) / r.width) * src.width);
    const py = Math.floor(((e.clientY - r.top) / r.height) * src.height);
    const d = src.getContext("2d", { willReadFrequently: true })!.getImageData(px, py, 1, 1).data;
    setSeed([px, py]);
    setColor([d[0], d[1], d[2]]);
  };

  useEffect(() => {
    root.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose();
      }
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [onClose]);

  return (
    <div className="fx-overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()} data-testid="color-range-dialog">
      <div className="fx-dialog" role="dialog" aria-modal="true" aria-label="بازهٔ رنگ" tabIndex={-1} ref={root} dir="rtl">
        <div className="fx-head"><b>بازهٔ رنگ / عصای جادویی</b><button type="button" className="fx-x" onClick={onClose} aria-label="بستن">✕</button></div>
        <div className="fx-body">
          <div className="fx-view" style={{ cursor: "crosshair" }}>
            {src ? <canvas ref={view} onClick={pick} style={{ maxWidth: "100%", maxHeight: "62vh" }} data-testid="cr-canvas" aria-label="روی رنگِ مورد نظر کلیک کنید" /> : <span className="fx-note">{err ?? "در حالِ آماده‌سازی…"}</span>}
          </div>
          <div className="fx-form">
            <p className="fx-note">روی بخشی از تصویر که می‌خواهید انتخاب شود کلیک کنید؛ لغزندهٔ «شباهت» را برای کم‌وزیادکردنِ دامنه بکشید.</p>
            <label className="fx-row"><span>شباهتِ رنگ</span><span className="fx-range"><input type="range" min={1} max={100} value={tol} onChange={(e) => setTol(Number(e.target.value))} data-testid="cr-tol" /><b dir="ltr">{fa(tol)}%</b></span></label>
            <label className="fx-row is-check"><span>فقط ناحیهٔ پیوسته (عصای جادویی)</span><input type="checkbox" checked={contig} onChange={(e) => setContig(e.target.checked)} data-testid="cr-contig" /></label>
            <label className="fx-row"><span>نرمیِ لبه</span><span className="fx-range"><input type="range" min={0} max={20} value={feather} onChange={(e) => setFeather(Number(e.target.value))} /><b dir="ltr">{fa(feather)} px</b></span></label>
            <label className="fx-row"><span>نسبت به انتخابِ قبلی</span>
              <select value={mode} onChange={(e) => setMode(e.target.value as "new" | "add" | "sub")}><option value="new">انتخابِ تازه</option><option value="add">افزودن به انتخاب</option><option value="sub">کم‌کردن از انتخاب</option></select>
            </label>
            {color && <p className="fx-note" data-testid="cr-info">{cov < 0.001 ? "چیزی با این شباهت پیدا نشد؛ شباهت را بیشتر کنید." : `${fa(Math.round(cov * 100))}٪ از تصویر انتخاب می‌شود.`}</p>}
          </div>
        </div>
        <div className="fx-foot">
          <button type="button" className="ws-btn primary" disabled={!mask || cov < 0.0005} onClick={() => mask && onApply(mask, mode)} data-testid="cr-apply">انتخاب</button>
          <button type="button" className="ws-btn" onClick={onClose}>انصراف</button>
        </div>
      </div>
    </div>
  );
}

/** فهرستِ انتخاب‌های ذخیره‌شده (برای «بارگذاری»). */
export function SavedSelDialog({ items, onLoad, onDelete, onClose }: { items: { id: string; name: string; thumb: string }[]; onLoad: (id: string) => void; onDelete: (id: string) => void; onClose: () => void }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose();
      }
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [onClose]);
  return (
    <div className="fx-overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()} data-testid="saved-sel-dialog">
      <div className="fx-dialog" style={{ width: "min(460px, 100%)", maxHeight: "none" }} role="dialog" aria-modal="true" aria-label="انتخاب‌های ذخیره‌شده" dir="rtl">
        <div className="fx-head"><b>انتخاب‌های ذخیره‌شده</b><button type="button" className="fx-x" onClick={onClose} aria-label="بستن">✕</button></div>
        <div className="fx-form" style={{ padding: 14 }}>
          {items.length === 0 && <p className="fx-note">هنوز انتخابی ذخیره نکرده‌اید (منوی انتخاب ‹ ذخیرهٔ انتخاب).</p>}
          {items.map((it) => (
            <div key={it.id} className="fx-row is-check" data-saved-sel={it.id}>
              <span style={{ display: "flex", alignItems: "center", gap: 8 }}><img src={it.thumb} alt="" width={48} height={32} style={{ borderRadius: 6, background: "#000", objectFit: "contain" }} />{it.name}</span>
              <span style={{ display: "flex", gap: 6 }}>
                <button type="button" className="ws-btn" onClick={() => onLoad(it.id)} data-testid={`load-sel-${it.id}`}>بارگذاری</button>
                <button type="button" className="ws-btn" onClick={() => onDelete(it.id)} aria-label="حذف">🗑</button>
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
