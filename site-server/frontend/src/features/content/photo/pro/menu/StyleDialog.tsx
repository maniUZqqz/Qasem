import { useEffect, useRef, useState } from "react";

import { Preset, proApi } from "../../api";
import type { Layer } from "../types";
import { BUILTIN_STYLES, StyleData, captureStyle, styleToPatch } from "../styleLib";
import "../../designer/designer.css";

const TARGET_FA: Record<string, string> = { text: "متن", shape: "شکل", image: "تصویر", any: "همهٔ لایه‌ها" };

/**
 * «سبک‌ها» (دورِ ۸): سبکِ لایه + سبکِ حرف/پاراگراف. سبکِ لایهٔ فعال را با یک نام ذخیره کنید (در همهٔ عکس‌های فروشگاه می‌ماند) یا
 * یکی از سبک‌های آماده/ذخیره‌شده را روی لایهٔ فعال بگذارید.
 */
export default function StyleDialog({ storeId, layer, onApply, onClose, onNotice }: {
  storeId: string; layer: Layer | null;
  onApply: (patch: Partial<Layer>, label: string) => void;
  onClose: () => void;
  onNotice: (text: string, tone?: "info" | "bad") => void;
}) {
  const [saved, setSaved] = useState<Preset[] | null>(null);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const cap = captureStyle(layer);

  useEffect(() => {
    root.current?.focus();
    let live = true;
    proApi.presets(storeId).then((l) => live && setSaved(l.filter((p) => p.kind === "style"))).catch(() => live && setSaved([]));
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose();
      }
    };
    window.addEventListener("keydown", onKey, true);
    return () => {
      live = false;
      window.removeEventListener("keydown", onKey, true);
    };
  }, [storeId, onClose]);

  const apply = (s: StyleData, title: string) => {
    const patch = styleToPatch(layer, s);
    if (!patch) return onNotice(`سبکِ «${title}» به این لایه نمی‌خورد (نوعِ لایه: ${layer ? TARGET_FA[layer.type] ?? layer.type : "—"}؛ سبک برای ${TARGET_FA[s.target]}).`, "info");
    onApply(patch, `سبکِ «${title}»`);
    onClose();
  };

  const save = async () => {
    const nm = name.trim();
    if (!nm || !cap || busy) return;
    setBusy(true);
    try {
      const p = await proApi.createPreset(storeId, nm, cap as unknown as Record<string, unknown>, "style");
      setSaved((l) => [...(l ?? []), p]);
      setName("");
      onNotice(`سبکِ «${nm}» ذخیره شد و در همهٔ عکس‌های فروشگاه هست.`);
    } catch (e) {
      onNotice(e instanceof Error ? e.message : "سبک ذخیره نشد.", "bad");
    } finally {
      setBusy(false);
    }
  };

  const remove = async (p: Preset) => {
    try {
      await proApi.removePreset(storeId, p.id);
      setSaved((l) => (l ?? []).filter((x) => x.id !== p.id));
    } catch (e) {
      onNotice(e instanceof Error ? e.message : "حذف نشد.", "bad");
    }
  };

  return (
    <div className="fx-overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()} data-testid="style-dialog">
      <div className="fx-dialog" role="dialog" aria-modal="true" aria-label="سبک‌ها" tabIndex={-1} ref={root} dir="rtl" style={{ width: "min(560px, 100%)", maxHeight: "none" }}>
        <div className="fx-head"><b>سبک‌ها (لایه، حرف و پاراگراف)</b><button type="button" className="fx-x" onClick={onClose} aria-label="بستن">✕</button></div>
        <div style={{ padding: 14, display: "grid", gap: 12 }}>
          <p className="ws-muted" style={{ fontSize: 12, margin: 0 }}>
            {layer ? `لایهٔ فعال: «${layer.name}» (${TARGET_FA[layer.type] ?? layer.type}). سبک فقط ویژگی‌های مجازِ همین نوعِ لایه را عوض می‌کند.` : "اول یک لایه را انتخاب کنید."}
          </p>
          <section aria-label="سبک‌های آماده">
            <b style={{ fontSize: 13 }}>آماده</b>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 6 }}>
              {BUILTIN_STYLES.map((s) => (
                <button key={s.id} type="button" className="ws-chip" title={`${s.hint} — برای ${TARGET_FA[s.style.target]}`} disabled={!layer} onClick={() => apply(s.style, s.title)} data-testid={`style-${s.id}`}>{s.title}</button>
              ))}
            </div>
          </section>
          <section aria-label="سبک‌های من">
            <b style={{ fontSize: 13 }}>سبک‌های من</b>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 6 }}>
              {saved === null && <span className="ws-muted" style={{ fontSize: 12 }}>در حالِ بارگذاری…</span>}
              {saved?.length === 0 && <span className="ws-muted" style={{ fontSize: 12 }}>هنوز سبکی ذخیره نکرده‌اید.</span>}
              {(saved ?? []).map((p) => {
                const d = p.data as unknown as StyleData;
                return (
                  <span key={p.id} style={{ display: "inline-flex", gap: 2 }}>
                    <button type="button" className="ws-chip" title={`برای ${TARGET_FA[d?.target] ?? "—"}`} disabled={!layer || !d?.props} onClick={() => apply(d, p.name)} data-testid="style-saved">{p.name}</button>
                    <button type="button" className="ws-chip" aria-label={`حذفِ «${p.name}»`} onClick={() => void remove(p)} data-testid="style-del">✕</button>
                  </span>
                );
              })}
            </div>
          </section>
          <section aria-label="ذخیرهٔ سبک">
            <b style={{ fontSize: 13 }}>ذخیرهٔ سبکِ لایهٔ فعال</b>
            <div style={{ display: "flex", gap: 6, marginTop: 6 }}>
              <input className="u-input" value={name} maxLength={60} placeholder="نامِ سبک" aria-label="نامِ سبک" onChange={(e) => setName(e.target.value)} onKeyDown={(e) => e.key === "Enter" && void save()} data-testid="style-name" style={{ flex: 1 }} />
              <button type="button" className="ws-btn primary" disabled={!cap || !name.trim() || busy} onClick={() => void save()} data-testid="style-save">ذخیره</button>
            </div>
            {!cap && <p className="ws-muted" style={{ fontSize: 12 }}>از لایه‌ای که متن، شکل یا تصویر نیست سبک گرفته نمی‌شود.</p>}
          </section>
        </div>
        <div className="fx-foot"><button type="button" className="ws-btn" onClick={onClose}>بستن</button></div>
      </div>
    </div>
  );
}
