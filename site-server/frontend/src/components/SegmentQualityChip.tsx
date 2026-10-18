import { useState } from "react";

import { SegmentQuality, VideoSegmentInfo } from "../types";
import BeforeAfter from "./BeforeAfter";

const SEGMENT_STATE: Record<string, string> = {
  PENDING: "در انتظار",
  GENERATING: "در حال تولید",
  DONE: "آماده",
  FAILED: "ناموفق",
};

const VERDICT: Record<SegmentQuality["verdict"], { label: string; tone: string }> = {
  EXCELLENT: { label: "عالی", tone: "ok" },
  GOOD: { label: "خوب", tone: "ok" },
  REVIEW: { label: "قابل بررسی", tone: "warn" },
  REGENERATE: { label: "ضعیف", tone: "bad" },
};

const TONE_STYLE: Record<string, { bg: string; fg: string }> = {
  ok: { bg: "var(--ok-soft, #dcfce7)", fg: "var(--ok, #166534)" },
  warn: { bg: "var(--warn-soft, #fef3c7)", fg: "var(--warn, #92400e)" },
  bad: { bg: "var(--bad-soft, #fee2e2)", fg: "var(--bad, #991b1b)" },
  neutral: { bg: "var(--surface-2, #f1f5f9)", fg: "var(--text-3, #64748b)" },
};

/**
 * One segment, with what quality control found in it.
 *
 * The score alone would be decoration. What makes it useful is the reason
 * underneath — "the clip freezes for about a second" tells a shop owner what to
 * do; "Motion Quality: 61" tells them nothing — and the note about what was
 * already repaired with code, so they can see that a dark clip was corrected
 * rather than wonder why it looks different from the preview. When the raw
 * render was kept, «قبل و بعد» puts the two side by side.
 */
export default function SegmentQualityChip({ segment }: { segment: VideoSegmentInfo }) {
  const quality = segment.quality;
  const [compare, setCompare] = useState(false);
  const statusTone =
    segment.status === "DONE"
      ? "ok"
      : segment.status === "FAILED"
        ? "bad"
        : segment.status === "GENERATING"
          ? "warn"
          : "neutral";

  const tone = quality ? VERDICT[quality.verdict].tone : statusTone;
  const style = TONE_STYLE[tone] ?? TONE_STYLE.neutral;
  const repaired = Boolean(quality?.repaired && quality.repaired.length > 0);
  const canCompare = repaired && Boolean(quality?.original_video) && Boolean(segment.video);

  return (
    <div
      className="flex flex-col gap-1 rounded-xl px-3 py-2 text-xs"
      style={{
        background: style.bg,
        color: style.fg,
        minWidth: "11rem",
        flexBasis: compare ? "100%" : undefined,
      }}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="font-bold">قطعه {segment.index}</span>
        <span>
          {quality
            ? `${VERDICT[quality.verdict].label} · ${Math.round(quality.overall)}`
            : SEGMENT_STATE[segment.status]}
        </span>
      </div>

      {repaired && (
        <div style={{ opacity: 0.85 }}>
          🔧 با کد اصلاح شد — بدون مصرف GPU
          {quality?.overall_before_repair != null
            ? ` (${Math.round(quality.overall_before_repair)} → ${Math.round(quality.overall)})`
            : ""}
        </div>
      )}

      {quality?.attempts && quality.attempts > 1 && (
        <div style={{ opacity: 0.85 }}>🔁 {quality.attempts} بار ساخته شد؛ بهترین نسخه مانده</div>
      )}

      {quality?.problems.map((axis) => (
        <div key={axis.name} style={{ opacity: 0.9 }}>
          {axis.note || `${axis.name}: ${Math.round(axis.score)}`}
        </div>
      ))}

      {quality && !quality.vision_checked && (
        <div style={{ opacity: 0.7 }}>
          فقط بررسی کد — مدل بینایی در دسترس نبود
          {quality.vision_reason ? ` (${quality.vision_reason})` : ""}
        </div>
      )}

      {canCompare && (
        <button
          type="button"
          className="self-start underline"
          style={{ color: "inherit" }}
          onClick={() => setCompare((c) => !c)}
        >
          {compare ? "بستن مقایسه" : "قبل و بعد را ببین"}
        </button>
      )}

      {compare && canCompare && quality?.original_video && segment.video && (
        <div className="mt-1" style={{ color: "var(--text)" }}>
          <BeforeAfter
            beforeUrl={quality.original_video}
            afterUrl={segment.video}
            beforeLabel="رندر خام"
            afterLabel="بعد از اصلاح با کد"
            compact
          />
        </div>
      )}

      {!quality && segment.error && <div style={{ opacity: 0.9 }}>{segment.error}</div>}
    </div>
  );
}
