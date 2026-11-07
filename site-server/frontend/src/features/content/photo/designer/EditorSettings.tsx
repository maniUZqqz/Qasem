import { useEffect, useRef, useState } from "react";

import { errorMessage } from "../../../../api/client";
import { Alert, Button, Spinner, fa } from "../../../../components/ui";
import type { Asset } from "../api";
import { designerApi, type DesignerInfo } from "./api";
import BrandForm from "./BrandForm";
import { Brand, StoreSettings, emptyBrand, settingsApi } from "./brandApi";
import "./designer.css";

type Tab = "ai" | "brand";

/** «تنظیماتِ ادیتور عکس»: پیش‌فرضِ کمکِ هوش مصنوعی + سبکِ برند (رنگ، فونت، لوگو، لحن). برای هر فروشگاه یک بار ذخیره می‌شود. */
export default function EditorSettings({ storeId, assets, initialTab = "ai", onClose, onSaved }: { storeId: string; assets: Asset[]; initialTab?: Tab; onClose: () => void; onSaved?: (s: StoreSettings) => void }) {
  const [tab, setTab] = useState<Tab>(initialTab);
  const [info, setInfo] = useState<DesignerInfo | null>(null);
  const [st, setSt] = useState<StoreSettings | null>(null);
  const [ai, setAi] = useState(true);
  const [brand, setBrand] = useState<Brand>(emptyBrand());
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const root = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let live = true;
    Promise.all([designerApi.info(storeId), settingsApi.get(storeId)])
      .then(([i, s]) => {
        if (!live) return;
        setInfo(i);
        setSt(s);
        setAi(s.ai_assist);
        setBrand(s.brand);
      })
      .catch((e) => live && setErr(errorMessage(e)));
    return () => {
      live = false;
    };
  }, [storeId]);

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

  async function save() {
    setBusy(true);
    setErr(null);
    setSaved(false);
    try {
      const s = await settingsApi.put(storeId, { ai_assist: ai, brand });
      setSt(s);
      setSaved(true);
      onSaved?.(s);
    } catch (e) {
      setErr(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  const cost = st?.ai_cost;
  return (
    <div className="es-overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()} data-testid="editor-settings">
      <div className="es-dialog" role="dialog" aria-modal="true" aria-label="تنظیماتِ ادیتور عکس" tabIndex={-1} ref={root}>
        <div className="es-head">
          <b>تنظیماتِ ادیتور عکس</b>
          <button type="button" className="dz-link" onClick={onClose} aria-label="بستن" data-testid="settings-close">✕ بستن</button>
        </div>
        <div className="dz-tabs" role="tablist" aria-label="بخش‌های تنظیمات">
          <button type="button" role="tab" className="dz-tab" aria-selected={tab === "ai"} onClick={() => setTab("ai")} data-stab="ai">کمکِ هوش مصنوعی</button>
          <button type="button" role="tab" className="dz-tab" aria-selected={tab === "brand"} onClick={() => setTab("brand")} data-stab="brand">سبکِ برند</button>
        </div>
        {!st && !err && <div className="p-6 text-center"><Spinner /></div>}
        {err && <Alert tone="bad">{err}</Alert>}
        {st && tab === "ai" && (
          <div data-testid="settings-ai">
            <label className="es-switch">
              <input type="checkbox" checked={ai} onChange={(e) => setAi(e.target.checked)} data-testid="settings-ai-toggle" />
              <span>پیش‌فرضِ کمکِ هوش مصنوعی: <b data-testid="settings-ai-state">{ai ? "روشن" : "خاموش"}</b></span>
            </label>
            <p className="dz-muted">
              این فقط مقدارِ اولِ تیکِ «از هوش مصنوعی هم کمک بگیر» در طراحِ خودکار و طراحیِ گروهی است؛ هر بار که بخواهید می‌توانید همان‌جا عوضش کنید.
              وقتی خاموش است هیچ‌وقت از هوش مصنوعی نمی‌پرسیم و طراحی با الگوها و قاعده‌های آماده انجام می‌شود (فوری، بدونِ هزینه؛ فقط انتخابِ الگو و نوشتنِ متن ساده‌تر است).
            </p>
            {cost && (
              <Alert tone="info" title="هزینه چقدر است؟">
                هر بار هوش مصنوعی «می‌پرسد» یعنی یک فراخوانیِ بینا (عکس + متن). در طراحِ خودکار: دقتِ «سریع» {fa(cost.fast)} فراخوانی، «معمولی» تا {fa(cost.normal)} فراخوانی
                ({fa(1)} برنامه‌ریز + {fa(cost.variants)} نقد) و «دقیق» تا {fa(cost.best)} فراخوانی. در طراحیِ گروهی: {fa(cost.batch_per_photo)} فراخوانی برای هر عکس و
                هیچ نقدی در کار نیست. اگر هوش مصنوعی جواب ندهد طراحی بی‌آن ادامه می‌یابد و چیزی حساب نمی‌شود.
              </Alert>
            )}
          </div>
        )}
        {st && info && tab === "brand" && (
          <div data-testid="settings-brand">
            <p className="dz-muted">یک بار ذخیره کنید؛ طراحِ خودکار و طراحیِ گروهی پیش‌فرض از آن استفاده می‌کنند (و برای هر طراحی می‌توانید عوضش کنید). خالی‌گذاشتنِ هر بخش = خودکار.</p>
            <BrandForm value={brand} onChange={setBrand} fonts={info.fonts} assets={assets} hasStoreLogo={info.has_logo} positions={st.positions} tid="brand" />
          </div>
        )}
        <div className="es-foot">
          <Button onClick={() => void save()} disabled={busy || !st} data-testid="settings-save">{busy ? <Spinner size={16} /> : "ذخیره"}</Button>
          {saved && <span className="text-sm" style={{ color: "var(--ok)" }} data-testid="settings-saved">ذخیره شد</span>}
        </div>
      </div>
    </div>
  );
}
