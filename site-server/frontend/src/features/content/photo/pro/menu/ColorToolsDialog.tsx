import { useEffect, useRef, useState } from "react";

import { errorMessage } from "../../../../../api/client";
import { fa } from "../../../../../components/ui";
import type { Asset } from "../../api";
import { proApi } from "../../api";
import "../../designer/designer.css";

/**
 * «رنگ از فایل / از عکسِ دیگر» (دورِ ۸): LUT (فایلِ .cube) یا «تطبیقِ رنگ» با یک عکسِ مرجع. هر دو یک عکسِ تازه در کتابخانه می‌سازند
 * (اصلِ عکس دست‌نخورده می‌ماند) و آن را باز می‌کنند.
 */
export type ColorMode = "lut" | "match";

export default function ColorToolsDialog({ storeId, mode, asset, assets, onClose, onOpenAsset, onNotice }: {
  storeId: string; mode: ColorMode; asset: { id: number; title: string }; assets: Asset[];
  onClose: () => void; onOpenAsset: (a: Asset) => void; onNotice: (text: string, tone?: "info" | "bad") => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [ref, setRef] = useState<number>(0);
  const [strength, setStrength] = useState(100);
  const [keepLuma, setKeepLuma] = useState(0);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const root = useRef<HTMLDivElement>(null);
  useEffect(() => {
    root.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !busy) {
        e.stopPropagation();
        onClose();
      }
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [onClose, busy]);

  const others = assets.filter((a) => a.id !== asset.id).slice(0, 200);
  const ready = !busy && (mode === "lut" ? !!file : ref > 0);
  const run = async () => {
    if (!ready) return;
    setBusy(true);
    setErr("");
    try {
      const a = mode === "lut" ? await proApi.lutApply(storeId, asset.id, file as File, strength / 100) : await proApi.matchColor(storeId, asset.id, ref, strength / 100, keepLuma / 100);
      onNotice(`«${a.title}» ساخته شد و باز می‌شود؛ عکسِ اصل دست‌نخورده است.`);
      onOpenAsset(a);
      onClose();
    } catch (e) {
      setErr(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };
  const title = mode === "lut" ? "LUT رنگی (فایلِ .cube)" : "تطبیقِ رنگ با عکسِ دیگر";
  return (
    <div className="fx-overlay" onMouseDown={(e) => e.target === e.currentTarget && !busy && onClose()} data-testid="color-dialog" data-mode={mode}>
      <div className="fx-dialog" role="dialog" aria-modal="true" aria-label={title} tabIndex={-1} ref={root} dir="rtl" style={{ width: "min(600px, 100%)", maxHeight: "92vh", overflow: "auto" }}>
        <div className="fx-head"><b>{title}</b><button type="button" className="fx-x" onClick={onClose} disabled={busy} aria-label="بستن">✕</button></div>
        <div style={{ padding: 14, display: "grid", gap: 12 }}>
          <p className="ws-muted" style={{ fontSize: 12, margin: 0 }}>
            {mode === "lut"
              ? `فایلِ LUT (فرمتِ .cube؛ سه‌بعدی یا یک‌بعدی، تا ۶ مگابایت) را روی «${asset.title}» اعمال می‌کند؛ مثلِ فیلترهای رنگیِ فیلم و عکس.`
              : `رنگ و روشناییِ کلیِ یک عکسِ مرجع (مثلاً بهترین عکسِ فروشگاه) را روی «${asset.title}» می‌آورد تا عکس‌ها هم‌رنگ شوند.`}
          </p>
          {mode === "lut" ? (
            <label className="fx-row">
              <span>فایلِ LUT</span>
              <input type="file" accept=".cube,text/plain" onChange={(e) => setFile(e.target.files?.[0] ?? null)} data-testid="lut-file" />
            </label>
          ) : (
            <div>
              <b style={{ fontSize: 13 }}>عکسِ مرجع</b>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(86px, 1fr))", gap: 6, maxHeight: 220, overflow: "auto", padding: 2, marginTop: 6 }} role="listbox" aria-label="عکسِ مرجع">
                {others.length === 0 && <span className="ws-muted" style={{ fontSize: 12 }}>عکسِ دیگری در کتابخانه نیست.</span>}
                {others.map((a) => (
                  <button key={a.id} type="button" role="option" aria-selected={ref === a.id} onClick={() => setRef(a.id)} title={a.title} data-testid="match-ref" data-on={ref === a.id ? "1" : "0"}
                    style={{ padding: 0, border: ref === a.id ? "2px solid var(--accent, #6366f1)" : "2px solid transparent", borderRadius: 8, overflow: "hidden", background: "var(--bg-2, #f3f4f6)", cursor: "pointer", aspectRatio: "1 / 1" }}>
                    <img src={a.thumb} alt="" loading="lazy" style={{ width: "100%", height: "100%", objectFit: "cover", display: "block" }} />
                  </button>
                ))}
              </div>
            </div>
          )}
          <label className="fx-row"><span>شدت</span><span className="fx-range"><input type="range" min={0} max={100} value={strength} onChange={(e) => setStrength(Number(e.target.value))} data-testid="color-strength" /><b dir="ltr">{fa(strength)}%</b></span></label>
          {mode === "match" && <label className="fx-row"><span>حفظِ روشناییِ خودِ عکس</span><span className="fx-range"><input type="range" min={0} max={100} value={keepLuma} onChange={(e) => setKeepLuma(Number(e.target.value))} /><b dir="ltr">{fa(keepLuma)}%</b></span></label>}
          {err && <p role="alert" style={{ color: "var(--danger, #b91c1c)", margin: 0, fontSize: 13 }} data-testid="color-error">{err}</p>}
          {busy && <p className="ws-muted" style={{ margin: 0, fontSize: 13 }}>در حالِ ساختنِ عکسِ تازه…</p>}
        </div>
        <div className="fx-foot">
          <button type="button" className="ws-btn primary" disabled={!ready} onClick={() => void run()} data-testid="color-run">اعمال (عکسِ تازه)</button>
          <button type="button" className="ws-btn" onClick={onClose} disabled={busy}>انصراف</button>
        </div>
      </div>
    </div>
  );
}
