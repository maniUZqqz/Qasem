import { useEffect, useRef, useState } from "react";

import { errorMessage } from "../../../../api/client";
import { Spinner, fa } from "../../../../components/ui";
import { Slider } from "./controls";
import type { MediaClip, Reframe } from "./model";
import { ENGINE_FA, REFRAME_TARGETS, ReframeResult, reframeApi } from "./reframeApi";

/**
 * «بازتنظیمِ خودکارِ قاب»: سرور سوژه (چهره/حرکت) را در بازهٔ استفاده‌شدهٔ همین قطعه پیدا می‌کند و پنجرهٔ برش را می‌سازد
 * که با کلیدها دنبالش برود. نتیجه با `onApply` ِ پدر (یک گامِ برگشت) روی قطعه می‌نشیند.
 * هم در بازرسِ قطعه و هم زیرِ مانیتور در حالتِ «برشِ قاب» استفاده می‌شود.
 */
export default function AutoReframe({
  storeId, clip, onApply, compact,
}: {
  storeId?: string;
  clip: MediaClip;
  onApply: (rf: Reframe) => void;
  compact?: boolean;
}) {
  const [target, setTarget] = useState<(typeof REFRAME_TARGETS)[number]["key"]>("9:16");
  const [zoom, setZoom] = useState(1);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [info, setInfo] = useState<ReframeResult | null>(null);
  const alive = useRef(true);
  useEffect(() => () => { alive.current = false; }, []);
  // قطعهٔ دیگری انتخاب شد ⇒ پیامِ نتیجهٔ قبلی دیگر به این قطعه ربط ندارد
  useEffect(() => { setInfo(null); setErr(null); }, [clip.id]);

  const title = REFRAME_TARGETS.find((t) => t.key === target)?.title ?? target;
  const image = clip.kind === "image";

  async function run() {
    if (!storeId || busy) return;
    setBusy(true);
    setErr(null);
    setInfo(null);
    try {
      const res = await reframeApi.run(storeId, {
        ref: clip.ref,
        start: image ? 0 : clip.start,
        end: image ? 1 : clip.end,
        aspect: target,
        follow: "auto",
        speed: clip.speed || 1,
        zoom,
      });
      if (!alive.current) return;
      if (!res.reframe) throw new Error("پاسخِ سرور ناقص بود.");
      onApply(res.reframe);
      setInfo(res);
    } catch (e) {
      if (alive.current) setErr(e instanceof Error && !("isAxiosError" in e) ? e.message : errorMessage(e));
    } finally {
      if (alive.current) setBusy(false);
    }
  }

  return (
    <div className={`cr-auto ${compact ? "is-compact" : ""}`} data-testid="auto-reframe-box">
      <div className="cr-auto-row">
        <label className="cr-auto-target">
          <span>نسبتِ مقصد</span>
          <select className="u-input" value={target} onChange={(e) => setTarget(e.target.value as typeof target)} data-testid="reframe-aspect" aria-label="نسبتِ مقصدِ بازتنظیمِ خودکار" disabled={busy}>
            {REFRAME_TARGETS.map((t) => <option key={t.key} value={t.key}>{t.title}</option>)}
          </select>
        </label>
        <button
          type="button" className="ws-btn primary" onClick={() => void run()} disabled={!storeId || busy} data-testid="auto-reframe"
          title="سوژه (چهره یا حرکت) را در بخشِ استفاده‌شدهٔ این قطعه پیدا می‌کند و قاب را طوری می‌برد که دنبالش برود"
        >
          {busy ? <><Spinner size={12} /> در حالِ تحلیل…</> : `${title} خودکار (دنبالِ سوژه)`}
        </button>
      </div>
      <Slider
        label="زوم" value={zoom} min={1} max={2} step={0.05} def={1} fmt={(v) => `${fa(v.toFixed(2))}×`}
        onLive={setZoom} onEnd={() => undefined}
      />
      {image && <p className="ws-hint">برای عکس، سوژه فقط یک‌بار پیدا می‌شود و قاب ثابت می‌ماند.</p>}
      {err && <p className="ws-hint" style={{ color: "var(--warn)" }} role="alert" data-testid="auto-reframe-error">{err}</p>}
      {info && (
        <div className="ws-hint" data-testid="auto-reframe-info">
          <b>سوژه: {ENGINE_FA[info.engine] ?? info.engine}</b>
          {info.notes?.length ? info.notes.map((n, i) => <div key={i}>{n}</div>) : null}
        </div>
      )}
    </div>
  );
}
