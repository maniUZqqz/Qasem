import { useEffect, useRef, useState } from "react";

import { errorMessage } from "../../../../api/client";
import { Alert, Badge, Button, ErrorBox, Spinner, fa } from "../../../../components/ui";
import { fetchLookPreview, type LookPreview } from "./api";
import { momentLabel, quickMoments } from "./logic";

/**
 * «قبل / بعد» نور و رنگِ خودکار — یک عکس از همان لحظه، یک بار همان‌طور که گرفته شده و یک بار با اصلاحی که تدوینِ خودکار می‌زند.
 * اسلایدرِ بالا لحظهٔ ویدیو را عوض می‌کند (هر نما اصلاحِ خودش را دارد: چهرهٔ گوینده یک چیز، ضبطِ صفحهٔ برنامه چیز دیگر)؛
 * اسلایدرِ پایین خطِ جداکننده را می‌برد. بدونِ لحظه، خودش فریمی را که گوینده در آن دیده می‌شود انتخاب می‌کند. هیچ چیز ذخیره نمی‌شود.
 */
export default function LookCompare({ storeId, refId, at }: { storeId: string; refId: string; at?: number }) {
  const [data, setData] = useState<LookPreview | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [split, setSplit] = useState(50);
  const [moment, setMoment] = useState<number | null>(null);
  const timer = useRef<number | null>(null);
  const seq = useRef(0);

  async function load(t?: number) {
    const mine = ++seq.current;
    setBusy(true);
    setError(null);
    try {
      const res = await fetchLookPreview(storeId, refId, t ?? at);
      if (mine !== seq.current) return;
      setData(res);
      setMoment(res.t);
      setSplit(50);
    } catch (e) {
      if (mine === seq.current) setError(errorMessage(e));
    } finally {
      if (mine === seq.current) setBusy(false);
    }
  }

  useEffect(() => () => { if (timer.current) window.clearTimeout(timer.current); }, []);

  /** لحظه عوض شد: کمی صبر می‌کنیم تا انگشت/ماوس ایستاد، بعد یک عکسِ تازه می‌گیریم */
  function pick(t: number, now = false) {
    setMoment(t);
    if (timer.current) window.clearTimeout(timer.current);
    if (now) void load(t);
    else timer.current = window.setTimeout(() => void load(t), 450);
  }

  const moments = data?.duration ? quickMoments(data.duration) : [];

  return (
    <div data-testid="look-compare">
      <Button variant="secondary" onClick={() => void load()} disabled={busy} data-testid="look-compare-run">
        {busy && !data ? <Spinner size={16} /> : "☀️ قبل / بعدِ نور و رنگ"}
      </Button>
      {error && <div className="mt-2"><ErrorBox message={error} /></div>}
      {data && (
        <div className="mt-3">
          <div className="mb-2 flex flex-wrap items-center gap-2 text-xs">
            <Badge tone={data.changed ? "ok" : "neutral"}>{data.changed ? "اصلاح می‌شود" : "درست است"}</Badge>
            <span style={{ color: "var(--text-2)" }}>{data.note}</span>
            {busy && <Spinner size={14} />}
          </div>
          {data.duration && data.duration > 1 ? (
            <div className="mb-2" data-testid="look-compare-time">
              <div className="mb-1 flex flex-wrap items-center gap-2 text-xs" style={{ color: "var(--text-2)" }}>
                <span>لحظهٔ ویدیو:</span>
                <b dir="ltr" data-testid="look-compare-time-label">{momentLabel(moment ?? data.t)}</b>
                <span dir="ltr" style={{ color: "var(--text-3)" }}>/ {momentLabel(data.duration)}</span>
                {moments.map((m) => (
                  <button key={m.label} type="button" className="ws-chip" onClick={() => pick(m.t, true)} data-testid={`look-compare-at-${m.label}`}>{m.label}</button>
                ))}
              </div>
              <input type="range" min={0} max={Math.max(1, Math.floor(data.duration * 2) / 2)} step={0.5} value={moment ?? data.t} dir="ltr"
                onChange={(e) => pick(Number(e.target.value))} className="w-full" aria-label={`لحظهٔ ویدیو (از ${fa(0)} تا ${fa(Math.round(data.duration))} ثانیه)`} data-testid="look-compare-time-slider" />
            </div>
          ) : null}
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
              <Alert tone="info" title="نیازی به اصلاح نبود">نور و رنگِ این نما در محدودهٔ درست است؛ تدوینِ خودکار آن را دست نمی‌زند. لحظهٔ دیگری از ویدیو را (بالا) امتحان کنید.</Alert>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
