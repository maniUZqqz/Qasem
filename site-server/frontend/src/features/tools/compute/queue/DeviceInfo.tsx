import { Badge, fa } from "../../../../components/ui";
import { DEVICE_FA, deviceTone, mbText } from "../selftest/model";
import type { GpuSummary, QueueJob } from "./model";

/**
 * «روی چه دستگاهی اجرا شد؟» (عامل ۲٫۱۱، خواستهٔ مالک: «چرا همه‌چیز با پردازندهٔ ضعیف انجام می‌شود و کارتِ قوی نه؟»)
 * هر کارِ تمام‌شده نوشته می‌شود کارت (CUDA / DirectML / NVENC) بود یا پردازنده و علتش؛ اگر کاری که باید روی کارت می‌بود روی
 * پردازنده رفت، هشدارِ زرد با علت می‌آید. نمودارِ کوچک: درصدِ استفادهٔ کارت در طولِ کار (نمونه‌های nvidia-smi).
 */

export function hasDevice(job: QueueJob): boolean {
  return Boolean(job.device && DEVICE_FA[job.device]) || Boolean(job.device_warning);
}

/** نشانِ کوچک کنارِ نامِ سرور در ردیف */
export function DeviceChip({ job }: { job: QueueJob }) {
  if (!job.device || !DEVICE_FA[job.device]) return null;
  return (
    <span title={job.device_warning || job.device_note || undefined}>
      <Badge tone={deviceTone(job.device)}>{DEVICE_FA[job.device]}</Badge>
    </span>
  );
}

function Spark({ series }: { series: NonNullable<GpuSummary["series"]> }) {
  const pts = series.filter((p) => p[1] !== null && p[1] !== undefined);
  if (pts.length < 2) return null;
  const w = 160;
  const h = 34;
  const maxT = Math.max(1, pts[pts.length - 1][0]);
  const d = pts.map((p, i) => `${i ? "L" : "M"}${((p[0] / maxT) * w).toFixed(1)} ${(h - ((p[1] as number) / 100) * (h - 2) - 1).toFixed(1)}`).join(" ");
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} role="img" aria-label="استفادهٔ کارت گرافیک در طولِ کار" style={{ direction: "ltr" }}>
      <rect x="0" y="0" width={w} height={h} rx="6" fill="var(--surface-2)" stroke="var(--line)" />
      <path d={d} fill="none" stroke="var(--brand)" strokeWidth="1.6" />
    </svg>
  );
}

/** بلوکِ جزئیاتِ یک کار */
export default function DeviceInfo({ job }: { job: QueueJob }) {
  if (!hasDevice(job)) return null;
  const g = job.gpu;
  return (
    <div>
      <div className="nmq-detail-head">
        <b>دستگاهِ اجرا</b>
        {job.device && DEVICE_FA[job.device] ? <Badge tone={deviceTone(job.device)}>{DEVICE_FA[job.device]}</Badge> : null}
      </div>
      {job.device_note && <p className="nmq-note">{job.device_note}</p>}
      {job.device_warning && (
        <p className="nmq-note" style={{ color: "var(--warn)" }}>
          هشدار: {job.device_warning}
        </p>
      )}
      {g && (g.util_max !== undefined || g.vram_max_mb !== undefined) && (
        <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: "6px 16px" }}>
          {g.series && <Spark series={g.series} />}
          <span className="nmq-small">
            {g.name ? <span dir="ltr">{g.name}</span> : "کارت"}
            {g.util_max !== undefined ? ` — استفاده: میانگین ${fa(Math.round(g.util_avg ?? 0))}٪، بیشینه ${fa(g.util_max)}٪` : ""}
            {g.vram_max_mb !== undefined ? ` — حافظه: تا ${mbText(g.vram_max_mb)} از ${mbText(g.vram_total_mb)}` : ""}
            {g.temp_max_c !== undefined ? ` — دما: تا ${fa(g.temp_max_c)}°` : ""}
            {g.samples ? ` (${fa(g.samples)} نمونه)` : ""}
          </span>
        </div>
      )}
    </div>
  );
}
