import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { errorMessage } from "../../../../api/client";
import { Alert, Button, ErrorBox, Spinner, fa } from "../../../../components/ui";
import { fetchSizes, makeSizes, type SizeInfo, type SizeJob } from "./api";
import CaptionModePicker, { type CaptionMode } from "./CaptionMode";
import { toggleKey } from "./logic";
import { RenderLine } from "./PolishStatus";

/**
 * «چند سایز با یک کلیک» — همین پروژه برای هر شبکه: ریلز/استوری/پست/یوتیوب/شورتس/تیک‌تاک/تلگرام/آپارات.
 * هر سایز پروژهٔ جدا (قابل ویرایش) و رندرِ جدا می‌شود؛ قاب دنبالِ چهره می‌رود (چهره روی خطِ یک‌سوم، با فضای سر) و زیرنویس‌ها از دکمه‌های همان شبکه دور می‌ماند.
 */
/** انتخابِ اندازه‌ها (ریلز، استوری، پست، یوتیوب، شورتس، تیک‌تاک، تلگرام، آپارات) — هم برای «چند سایز» و هم برای تدوینِ حرفه‌ای */
export function SizeChips({ sizes, picked, onToggle }: { sizes: SizeInfo[]; picked: string[]; onToggle: (key: string) => void }) {
  const networks = Array.from(new Set(sizes.map((s) => s.network)));
  return (
    <>
      {networks.map((net) => (
        <div key={net} className="mb-2">
          <div className="mb-1 text-xs" style={{ color: "var(--text-3)" }}>{net}</div>
          <div className="flex flex-wrap gap-2">
            {sizes.filter((s) => s.network === net).map((s) => {
              const on = picked.includes(s.key);
              return (
                <button
                  key={s.key}
                  type="button"
                  aria-pressed={on}
                  onClick={() => onToggle(s.key)}
                  data-testid={`size-${s.key}`}
                  className="rounded-lg px-3 py-1 text-sm"
                  style={{ border: `1px solid ${on ? "var(--brand)" : "var(--line)"}`, background: on ? "var(--brand-soft)" : "transparent", color: "var(--text)" }}
                >
                  {s.title} <span dir="ltr" className="text-xs" style={{ color: "var(--text-3)" }}>{fa(s.width)}×{fa(s.height)}</span>
                </button>
              );
            })}
          </div>
        </div>
      ))}
    </>
  );
}

export default function SizesPanel({ storeId, projectId }: { storeId: string; projectId: number }) {
  const [sizes, setSizes] = useState<SizeInfo[] | null>(null);
  const [picked, setPicked] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [captions, setCaptions] = useState<CaptionMode>("burn");
  const [error, setError] = useState<string | null>(null);
  const [made, setMade] = useState<SizeJob[]>([]);
  const [skipped, setSkipped] = useState<{ title: string; reason: string }[]>([]);

  useEffect(() => {
    fetchSizes(storeId)
      .then((d) => {
        setSizes(d.sizes);
        setPicked(d.default);
      })
      .catch((e) => setError(errorMessage(e)));
  }, [storeId]);

  async function go() {
    setBusy(true);
    setError(null);
    try {
      const out = await makeSizes(storeId, projectId, picked, captions);
      setMade(out.jobs);
      setSkipped(out.skipped);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  if (error && !sizes) return <ErrorBox message={error} />;
  if (!sizes) return <Spinner size={16} />;

  return (
    <div className="rounded-xl p-3" style={{ border: "1px solid var(--line)" }} data-testid="sizes-panel">
      <div className="mb-2 text-sm font-bold" style={{ color: "var(--text)" }}>همین ویدیو برای چند شبکه</div>
      <SizeChips sizes={sizes} picked={picked} onToggle={(k) => setPicked((p) => toggleKey(p, k))} />
      <div className="mt-2"><CaptionModePicker value={captions} onChange={setCaptions} testId="sizes-caption-mode" /></div>
      {error && <ErrorBox message={error} />}
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <Button type="button" onClick={() => void go()} disabled={busy || picked.length === 0} data-testid="sizes-go">
          {busy ? <Spinner size={16} /> : `ساختِ ${fa(picked.length)} سایز`}
        </Button>
        <span className="text-xs" style={{ color: "var(--text-3)" }}>پروژهٔ اصلی دست نمی‌خورد؛ هر سایز پروژهٔ تازه‌ای است.</span>
      </div>
      {made.length > 0 && (
        <div className="mt-3">
          <Alert tone="ok" title={`${fa(made.length)} رندر در صف رفت`}>
            <ul className="mt-1 flex flex-col gap-2">
              {made.map((m) => (
                <li key={m.job_id}>
                  <RenderLine render={{ size: m.size, title: m.title, project_id: m.project_id, job_id: m.job_id }} />
                  {m.notes.length > 0 && <div className="mt-1 text-xs" style={{ color: "var(--warn)" }}>{m.notes.join(" · ")}</div>}
                </li>
              ))}
            </ul>
            <div className="mt-2 text-sm"><Link to={`/stores/${storeId}/queue`} className="text-violet-600 hover:underline">پیگیری در «صف تولید»</Link></div>
          </Alert>
        </div>
      )}
      {skipped.length > 0 && (
        <div className="mt-2"><Alert tone="warn" title="این‌ها ساخته نشد">{skipped.map((s) => `${s.title}: ${s.reason}`).join(" · ")}</Alert></div>
      )}
    </div>
  );
}
