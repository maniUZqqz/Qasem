import { useCallback, useEffect, useState } from "react";

import { errorMessage } from "../../../../api/client";
import { Badge, Button, Spinner, fa } from "../../../../components/ui";
import { DraftRow, directorApi } from "./api";

/** پیش‌نویس‌های قبلیِ کارگردان که هنوز بازشان نکرده‌اید؛ هر کدام چند روز مانده تا پاک شود. باز کردن = ساختنِ پروژهٔ واقعی. */
export default function DraftsList({ storeId, refreshKey, onOpen }: { storeId: string; refreshKey: number; onOpen: (projectId: number) => void }) {
  const [rows, setRows] = useState<DraftRow[] | null>(null);
  const [days, setDays] = useState(7);
  const [busy, setBusy] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const r = await directorApi.drafts(storeId);
      setRows(r.drafts);
      setDays(r.draft_days);
    } catch (e) {
      setError(errorMessage(e));
    }
  }, [storeId]);
  useEffect(() => {
    void load();
  }, [load, refreshKey]);

  async function open(d: DraftRow) {
    setBusy(d.id);
    setError(null);
    try {
      const r = await directorApi.openDraft(storeId, d.id);
      onOpen(r.project_id);
    } catch (e) {
      setError(errorMessage(e));
      setBusy(null);
    }
  }
  async function drop(d: DraftRow) {
    if (!window.confirm("این پیش‌نویس پاک شود؟")) return;
    setBusy(d.id);
    try {
      await directorApi.deleteDraft(storeId, d.id);
      await load();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(null);
    }
  }

  if (rows === null) return error ? <p className="ws-hint" role="alert">{error}</p> : <Spinner size={16} />;
  if (rows.length === 0) return <p className="dr-hint" data-testid="dr-drafts-empty">پیش‌نویسِ بازنشده‌ای نیست. هر چه با «بساز» درست کنید این‌جا می‌ماند تا بازش کنید.</p>;
  return (
    <div data-testid="dr-drafts">
      <p className="dr-hint">
        این‌ها نتیجه‌های «بساز»ِ قبلی‌اند که هنوز بازشان نکرده‌اید؛ سبک نگه داشته می‌شوند و هر کدام {fa(days)} روز بعد از ساخته‌شدن، اگر باز نشود، خودکار پاک می‌شود.
        با «باز کردن در تدوینِ دستی» پروژهٔ واقعی می‌شود و دیگر هیچ‌وقت خودکار پاک نمی‌شود.
      </p>
      <ul className="dr-draft-list">
        {rows.map((d) => (
          <li key={d.id} className="dr-draft" data-testid="dr-draft" data-draft={d.id}>
            <div className="dr-draft-main">
              <b>{d.title || "ویدیو"}</b>
              <small>{d.prompt ? `«${d.prompt}»` : ""} {fa(Math.round(d.length))} ثانیه</small>
            </div>
            <Badge tone={d.score >= 80 ? "ok" : d.score >= 60 ? "warn" : "bad"}>{fa(d.score)}</Badge>
            <Badge tone={(d.days_left ?? 0) <= 1 ? "warn" : "neutral"}>{d.days_left === 0 ? "امروز پاک می‌شود" : `${fa(d.days_left ?? 0)} روز مانده`}</Badge>
            <Button onClick={() => void open(d)} disabled={busy === d.id} data-testid="dr-draft-open">باز کردن در تدوینِ دستی</Button>
            <Button variant="secondary" onClick={() => void drop(d)} disabled={busy === d.id} data-testid="dr-draft-delete" aria-label="پاک کردنِ پیش‌نویس">پاک</Button>
          </li>
        ))}
      </ul>
      {error && <p className="ws-hint" role="alert">{error}</p>}
    </div>
  );
}
