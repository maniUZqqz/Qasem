import { useEffect, useMemo, useRef, useState } from "react";

import { SHAPES, buildShape } from "../shapesLib";
import { fa } from "../../../../../components/ui";
import "../../designer/designer.css";

/**
 * «شکل‌های آماده» (دورِ ۸): چندضلعی (تعدادِ ضلع)، ستاره (تعدادِ پر و گودی) و شکل‌های پُرکاربردِ فروشگاه. هر شکل یک لایهٔ شکلِ مسیر می‌شود
 * (قابلِ رنگ، خطِ دور، تبدیل و ویرایشِ نقطه‌ها).
 */
export default function ShapeDialog({ onPick, onClose }: { onPick: (id: string, opts: { sides: number; inner: number }) => void; onClose: () => void }) {
  const [id, setId] = useState("star");
  const [sides, setSides] = useState(5);
  const [inner, setInner] = useState(0.45);
  const root = useRef<HTMLDivElement>(null);
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

  const previews = useMemo(
    () =>
      SHAPES.map((s) => {
        const b = buildShape(s.id, { sides: s.id === "polygon" ? 6 : 5, inner: 0.45 });
        const d = b ? b.path.pts.map((p, i) => `${i ? "L" : "M"}${(p.x * 40 + 4).toFixed(1)} ${(p.y * 40 + 4).toFixed(1)}`).join(" ") + "Z" : "";
        return { id: s.id, title: s.title, d };
      }),
    [],
  );
  const cur = SHAPES.find((s) => s.id === id);
  const live = useMemo(() => {
    const b = buildShape(id, { sides, inner });
    return b ? b.path.pts.map((p, i) => `${i ? "L" : "M"}${(p.x * 70 + 5).toFixed(1)} ${(p.y * 70 + 5).toFixed(1)}`).join(" ") + "Z" : "";
  }, [id, sides, inner]);

  return (
    <div className="fx-overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()} data-testid="shape-dialog">
      <div className="fx-dialog" role="dialog" aria-modal="true" aria-label="شکل‌های آماده" tabIndex={-1} ref={root} dir="rtl" style={{ width: "min(560px, 100%)", maxHeight: "none" }}>
        <div className="fx-head"><b>شکل‌های آماده</b><button type="button" className="fx-x" onClick={onClose} aria-label="بستن">✕</button></div>
        <div style={{ padding: 14, display: "grid", gap: 12 }}>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(64px, 1fr))", gap: 8 }} role="listbox" aria-label="فهرستِ شکل‌ها">
            {previews.map((p) => (
              <button
                key={p.id}
                type="button"
                role="option"
                aria-selected={id === p.id}
                className={`ws-chip${id === p.id ? " is-on" : ""}`}
                style={{ display: "grid", justifyItems: "center", gap: 4, padding: 6 }}
                onClick={() => setId(p.id)}
                onDoubleClick={() => onPick(p.id, { sides, inner })}
                data-testid={`shape-${p.id}`}
              >
                <svg width="48" height="48" viewBox="0 0 48 48" aria-hidden="true"><path d={p.d} fill="currentColor" opacity="0.85" /></svg>
                <span style={{ fontSize: 11 }}>{p.title}</span>
              </button>
            ))}
          </div>
          <div style={{ display: "flex", gap: 14, alignItems: "center", flexWrap: "wrap" }}>
            <svg width="80" height="80" viewBox="0 0 80 80" aria-label="پیش‌نمایش" data-testid="shape-preview"><path d={live} fill="var(--accent, #6366f1)" /></svg>
            {(id === "polygon" || id === "star") && (
              <label className="fx-row" style={{ flex: 1, minWidth: 180 }}>
                <span>{id === "polygon" ? "تعدادِ ضلع" : "تعدادِ پر"}</span>
                <span className="fx-range">
                  <input type="range" min={3} max={id === "polygon" ? 16 : 12} step={1} value={sides} onChange={(e) => setSides(Number(e.target.value))} data-testid="shape-sides" />
                  <b dir="ltr">{fa(sides)}</b>
                </span>
              </label>
            )}
            {id === "star" && (
              <label className="fx-row" style={{ flex: 1, minWidth: 180 }}>
                <span>گودیِ پرها</span>
                <span className="fx-range">
                  <input type="range" min={0.15} max={0.85} step={0.05} value={inner} onChange={(e) => setInner(Number(e.target.value))} data-testid="shape-inner" />
                  <b dir="ltr">{fa(Math.round(inner * 100))}%</b>
                </span>
              </label>
            )}
          </div>
          <p className="ws-muted" style={{ fontSize: 12, margin: 0 }}>{cur ? `«${cur.title}» به‌صورتِ یک لایهٔ شکل روی عکس می‌نشیند؛ رنگ، خطِ دور و اندازه را از زبانهٔ «لایه‌ها» عوض کنید.` : ""}</p>
        </div>
        <div className="fx-foot">
          <button type="button" className="ws-btn primary" onClick={() => onPick(id, { sides, inner })} data-testid="shape-add">افزودن به عکس</button>
          <button type="button" className="ws-btn" onClick={onClose}>انصراف</button>
        </div>
      </div>
    </div>
  );
}
