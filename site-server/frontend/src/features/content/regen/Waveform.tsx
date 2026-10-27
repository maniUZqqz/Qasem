import { useRef } from "react";

/**
 * شکلِ موجِ صدا (ستون‌های متقارن) زیرِ خطِ زمانی، همیشه چپ‌به‌راست. بازهٔ انتخاب‌شده رنگی است، بیرونش کم‌رنگ؛
 * خطِ سفید جای پخش است و کلیک جای پخش را عوض می‌کند. from/to ثانیه‌اند (کلِ ویدیو یا نزدیک‌نمای بازه).
 */
export default function Waveform({
  peaks,
  from,
  to,
  selStart,
  selEnd,
  playhead,
  height = 44,
  onSeek,
  testid,
  empty = "این ویدیو صدا ندارد",
}: {
  peaks: number[] | null;
  from: number;
  to: number;
  selStart: number;
  selEnd: number;
  playhead?: number;
  height?: number;
  onSeek?: (seconds: number) => void;
  testid?: string;
  empty?: string;
}) {
  const box = useRef<HTMLDivElement>(null);
  const span = Math.max(1e-6, to - from);
  const pct = (t: number) => `${Math.max(0, Math.min(100, ((t - from) / span) * 100))}%`;
  const n = peaks?.length ?? 0;
  return (
    <div
      ref={box}
      dir="ltr"
      data-testid={testid}
      className="relative w-full overflow-hidden rounded-lg"
      style={{ height, background: "var(--surface-2)", border: "1px solid var(--line)", cursor: onSeek ? "pointer" : "default" }}
      onPointerDown={(e) => {
        const r = box.current?.getBoundingClientRect();
        if (!r || !onSeek) return;
        onSeek(from + ((e.clientX - r.left) / r.width) * span);
      }}
    >
      {peaks && n > 0 ? (
        <svg viewBox={`0 0 ${n} 100`} preserveAspectRatio="none" className="absolute inset-0 h-full w-full">
          {peaks.map((p, i) => {
            const t = from + ((i + 0.5) / n) * span;
            const inside = t >= selStart && t <= selEnd;
            const h = Math.max(1.5, p * 96);
            return (
              <rect
                key={i}
                x={i + 0.1}
                width={0.8}
                y={50 - h / 2}
                height={h}
                fill={inside ? "var(--brand)" : "var(--text-3)"}
                opacity={inside ? 0.95 : 0.55}
              />
            );
          })}
        </svg>
      ) : (
        <div className="flex h-full items-center justify-center text-xs" style={{ color: "var(--text-3)" }}>
          {peaks === null ? "…" : empty}
        </div>
      )}
      <div
        className="pointer-events-none absolute inset-y-0"
        style={{ left: pct(selStart), width: `calc(${pct(selEnd)} - ${pct(selStart)})`, border: "1px solid var(--brand)", background: "rgb(139 123 255 / .10)" }}
      />
      {playhead !== undefined && playhead >= from && playhead <= to && (
        <div className="pointer-events-none absolute inset-y-0 w-0.5" style={{ left: pct(playhead), background: "#fff", boxShadow: "0 0 3px #000" }} />
      )}
    </div>
  );
}
