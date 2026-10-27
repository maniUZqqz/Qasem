import { useState } from "react";

/**
 * قبل/بعد با لغزنده: «بعد» زیر، «قبل» رویش تا جایی که دسته است.
 *
 * وقتی قالب عوض شده (مثلاً عکسِ افقی ⇐ استوریِ ۹:۱۶) روی هم گذاشتن دروغ می‌گوید — آن‌وقت دو عکس کنارِ هم.
 */
export default function CompareSlider({
  before,
  after,
  beforeSize,
  afterSize,
}: {
  before: string;
  after: string;
  beforeSize?: [number, number] | null;
  afterSize?: [number, number] | null;
}) {
  const [pos, setPos] = useState(50);
  const sameShape =
    !beforeSize ||
    !afterSize ||
    Math.abs(beforeSize[0] / beforeSize[1] - afterSize[0] / afterSize[1]) < 0.02;

  if (!sameShape) {
    return (
      <div className="grid gap-3 sm:grid-cols-2" data-testid="compare-side">
        {[
          { url: before, label: "قبل" },
          { url: after, label: "بعد" },
        ].map((x) => (
          <figure key={x.label} className="m-0">
            <img
              src={x.url}
              alt={x.label}
              className="max-h-[70vh] w-full rounded-xl object-contain"
              style={{ background: "var(--surface-2)" }}
            />
            <figcaption className="mt-1 text-center text-xs" style={{ color: "var(--text-3)" }}>
              {x.label}
            </figcaption>
          </figure>
        ))}
      </div>
    );
  }

  // عکسِ بلند (مربع، عمودی) تمامِ صفحه را نگیرد: بلندی حداکثر ۷۰٪ ِ صفحه
  const aspect = afterSize ? afterSize[0] / afterSize[1] : beforeSize ? beforeSize[0] / beforeSize[1] : 1.5;
  return (
    <div
      className="relative mx-auto w-full select-none overflow-hidden rounded-xl"
      style={{ background: "var(--surface-2)", maxWidth: `min(900px, calc(70vh * ${aspect.toFixed(4)}))` }}
      data-testid="compare-slider"
      dir="ltr"
    >
      <img src={after} alt="بعد" className="block h-auto w-full" draggable={false} />
      <img
        src={before}
        alt="قبل"
        className="absolute inset-0 block h-full w-full"
        style={{ clipPath: `inset(0 ${100 - pos}% 0 0)`, objectFit: "fill" }}
        draggable={false}
      />
      <div
        className="pointer-events-none absolute inset-y-0"
        style={{ left: `${pos}%`, width: 2, marginLeft: -1, background: "white", boxShadow: "0 0 6px rgba(0,0,0,.5)" }}
      />
      <span
        className="pointer-events-none absolute top-2 rounded-full px-2 py-0.5 text-xs"
        style={{ left: 8, background: "rgba(0,0,0,.55)", color: "white" }}
      >
        قبل
      </span>
      <span
        className="pointer-events-none absolute top-2 rounded-full px-2 py-0.5 text-xs"
        style={{ right: 8, background: "rgba(0,0,0,.55)", color: "white" }}
      >
        بعد
      </span>
      <input
        type="range"
        min={0}
        max={100}
        step={0.5}
        value={pos}
        onChange={(e) => setPos(Number(e.target.value))}
        aria-label="مرزِ قبل و بعد"
        className="absolute inset-0 h-full w-full cursor-ew-resize opacity-0"
      />
    </div>
  );
}
