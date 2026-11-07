import { useCallback, useEffect, useState } from "react";

import { errorMessage } from "../../../../api/client";
import { Spinner, fa } from "../../../../components/ui";
import { EditorSettings, directorApi } from "./api";

const DAY_CHOICES = [1, 3, 7, 14, 30];

/**
 * تنظیماتِ ویرایشگرِ ویدیو برای همین فروشگاه:
 *  - «کمکِ هوش مصنوعی» به‌طورِ پیش‌فرض روشن باشد یا خاموش (تیکِ کارگردان از همین حالت شروع می‌شود؛ هر بار هم می‌شود عوضش کرد) و هزینه‌اش چیست؛
 *  - پیش‌نویس‌های بازنشدهٔ کارگردان چند روز بمانند.
 * هم در صفحهٔ کارگردان و هم در منوی کامل (پرونده › تنظیمات ویرایشگر) و جستجوی ابزار هست.
 */
export default function EditorSettingsCard({ storeId, onChange }: { storeId: string; onChange?: (s: EditorSettings) => void }) {
  const [s, setS] = useState<EditorSettings | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);

  useEffect(() => {
    let stop = false;
    void directorApi.settings(storeId).then((v) => !stop && setS(v)).catch((e) => !stop && setError(errorMessage(e)));
    return () => {
      stop = true;
    };
  }, [storeId]);

  const save = useCallback(async (body: Partial<Pick<EditorSettings, "ai_default" | "draft_days" | "max_drafts">>, say: string) => {
    setError(null);
    const before = s;
    setS((cur) => (cur ? { ...cur, ...body } : cur));                // فوراً نشان بده؛ اگر ذخیره نشد برمی‌گردد
    try {
      const v = await directorApi.saveSettings(storeId, body);
      setS(v);
      setSaved(say);
      onChange?.(v);
    } catch (e) {
      setS(before);
      setError(errorMessage(e));
    }
  }, [storeId, onChange, s]);

  if (!s) return error ? <p className="ws-hint" role="alert">{error}</p> : <p className="ws-hint"><Spinner size={14} /> در حالِ بارگیری…</p>;
  return (
    <div className="es-card" data-testid="editor-settings">
      <label className="dr-check es-row">
        <input type="checkbox" checked={s.ai_default} onChange={(e) => void save({ ai_default: e.target.checked }, e.target.checked ? "کمکِ هوش مصنوعی از این به بعد روشن شروع می‌شود." : "کمکِ هوش مصنوعی از این به بعد خاموش شروع می‌شود.")} data-testid="es-ai-default" />
        <span><b>پیش‌فرضِ «هوش مصنوعی کمک کند»: {s.ai_default ? "روشن" : "خاموش"}</b></span>
      </label>
      <p className="ws-hint" data-testid="es-cost">{s.cost_note}</p>
      <p className="ws-hint">این فقط حالتِ شروعِ تیکِ «هوش مصنوعی کمک کند» در کارگردان است؛ هر بار که ویدیو می‌سازید می‌توانید همان‌جا عوضش کنید.</p>

      <label className="ws-field es-row">
        <span>پیش‌نویس‌های بازنشده چند روز بمانند؟</span>
        <select className="u-input" value={s.draft_days} onChange={(e) => void save({ draft_days: Number(e.target.value) }, `پیش‌نویس‌ها ${fa(Number(e.target.value))} روز می‌مانند.`)} data-testid="es-draft-days" aria-label="مدتِ نگهداریِ پیش‌نویس">
          {Array.from(new Set([...DAY_CHOICES, s.draft_days])).sort((a, b) => a - b).filter((d) => d >= s.min_days && d <= s.max_days).map((d) => (
            <option key={d} value={d}>{fa(d)} روز</option>
          ))}
        </select>
      </label>
      <p className="ws-hint" data-testid="es-draft-note">
        هر «بساز» سه نسخه را فقط به‌صورتِ پیش‌نویسِ سبک نگه می‌دارد (فیلم‌ها کپی نمی‌شوند). پیش‌نویسی که در {fa(s.draft_days)} روز باز نشود خودکار پاک می‌شود (حداکثر {fa(s.max_drafts)} پیش‌نویس).
        پروژه‌ای که یک بار در تدوینِ دستی باز کرده یا ذخیره کرده باشید <b>هرگز</b> خودکار پاک نمی‌شود.
      </p>
      <label className="ws-field es-row">
        <span>حداکثر چند پیش‌نویسِ بازنشده نگه داشته شود؟</span>
        <input type="number" className="u-input" min={s.min_drafts} max={s.max_drafts_limit} step={5} value={s.max_drafts} data-testid="es-max-drafts"
          onChange={(e) => setS((cur) => (cur ? { ...cur, max_drafts: Number(e.target.value) } : cur))}
          onBlur={(e) => { const v = Math.max(s.min_drafts, Math.min(s.max_drafts_limit, Math.round(Number(e.target.value)) || s.max_drafts)); void save({ max_drafts: v }, `حداکثر ${fa(v)} پیش‌نویس نگه داشته می‌شود (قدیمی‌ترها زودتر پاک می‌شوند).`); }} />
      </label>
      <p className="ws-hint" data-testid="es-cap-note">بینِ {fa(s.min_drafts)} تا {fa(s.max_drafts_limit)}. فقط پیش‌نویس‌های بازنشده شمرده می‌شوند؛ پروژه‌ای که باز کرده‌اید هرگز پاک نمی‌شود.</p>
      {saved && <p className="ws-hint" role="status" data-testid="es-saved">{saved}</p>}
      {error && <p className="ws-hint" role="alert">{error}</p>}
    </div>
  );
}
