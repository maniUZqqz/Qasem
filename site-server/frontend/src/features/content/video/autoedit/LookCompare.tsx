import { useState } from "react";

import { errorMessage } from "../../../../api/client";
import { Alert, Badge, Button, ErrorBox, Spinner } from "../../../../components/ui";
import { fetchLookPreview, type LookPreview } from "./api";

/**
 * «قبل / بعد» نور و رنگِ خودکار — یک عکس از همان لحظه، یک بار همان‌طور که گرفته شده و یک بار با اصلاحی که تدوینِ خودکار می‌زند.
 * اسلایدر خطِ جداکننده را می‌برد؛ هیچ چیز ذخیره نمی‌شود. اگر نما درست باشد همین را می‌گوید و دست نمی‌زند.
 */
export default function LookCompare({ storeId, refId, at }: { storeId: string; refId: string; at?: number }) {
  const [data, setData] = useState<LookPreview | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [split, setSplit] = useState(50);

  async function load() {
    setBusy(true);
    setError(null);
    try {
      setData(await fetchLookPreview(storeId, refId, at));
      setSplit(50);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div data-testid="look-compare">
      <Button variant="secondary" onClick={() => void load()} disabled={busy} data-testid="look-compare-run">
        {busy ? <Spinner size={16} /> : "☀️ قبل / بعدِ نور و رنگ"}
      </Button>
      {error && <div className="mt-2"><ErrorBox message={error} /></div>}
      {data && (
        <div className="mt-3">
          <div className="mb-2 flex flex-wrap items-center gap-2 text-xs">
            <Badge tone={data.changed ? "ok" : "neutral"}>{data.changed ? "اصلاح می‌شود" : "درست است"}</Badge>
            <span style={{ color: "var(--text-2)" }}>{data.note}</span>
          </div>
          <div className="relative overflow-hidden rounded-xl" style={{ border: "1px solid var(--line)", direction: "ltr" }} dir="ltr">
            <img src={data.after} alt="بعد" className="block w-full" />
            <div className="absolute inset-y-0 left-0 overflow-hidden" style={{ width: `${split}%` }}>
              <img src={data.before} alt="قبل" className="block h-full max-w-none" style={{ width: `${10000 / Math.max(split, 1)}%` }} />
            </div>
            <div className="absolute inset-y-0 w-0.5" style={{ left: `${split}%`, background: "#fff", boxShadow: "0 0 4px rgba(0,0,0,.6)" }} />
            <span className="absolute left-2 top-2 rounded px-1.5 py-0.5 text-xs" style={{ background: "rgba(0,0,0,.55)", color: "#fff" }}>قبل</span>
            <span className="absolute right-2 top-2 rounded px-1.5 py-0.5 text-xs" style={{ background: "rgba(0,0,0,.55)", color: "#fff" }}>بعد</span>
          </div>
          <input type="range" min={0} max={100} value={split} onChange={(e) => setSplit(Number(e.target.value))} className="mt-2 w-full" aria-label="جداکنندهٔ قبل و بعد" data-testid="look-compare-split" />
          {!data.changed && (
            <div className="mt-2">
              <Alert tone="info" title="نیازی به اصلاح نبود">نور و رنگِ این نما در محدودهٔ درست است؛ تدوینِ خودکار آن را دست نمی‌زند.</Alert>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
