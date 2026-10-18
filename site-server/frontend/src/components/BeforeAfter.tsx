import { useEffect, useRef, useState } from "react";

import { Badge, Button, fa } from "./ui";

/**
 * The original and the edited cut, side by side, with the numbers that changed.
 *
 * An editor that only shows the result asks the shop to remember what the
 * footage looked like before — and asks us to trust our own filters. Both
 * videos play together from one button, and under them sits every measurement
 * the "second look" took before and after, so a brightness lift is a number
 * (94 → 167) and not an impression. `effects` are the agent's own verdicts per
 * tool: what each edit was meant to change, and whether it did.
 *
 * Used for a shop's uploaded video (original vs edited) and for a generated
 * segment (the raw render vs the code-repaired one).
 */

export type Effect = {
  tool: string;
  title: string;
  verdict: "better" | "worse" | "neutral" | "applied" | string;
  detail: string;
};

export type Measurements = Record<string, number | boolean | string | null | undefined>;

type Props = {
  beforeUrl: string;
  afterUrl: string;
  beforeLabel?: string;
  afterLabel?: string;
  before?: Measurements | null;
  after?: Measurements | null;
  effects?: Effect[];
  note?: string;
  improved?: boolean | null;
  summary?: string;
  compact?: boolean;
};

type Row = {
  key: string;
  label: string;
  /** How to print the value. */
  format: (value: number) => string;
  /** Which direction is an improvement, when there is one. */
  better: "lower" | "higher" | "band" | "none";
};

const ROWS: Row[] = [
  { key: "duration", label: "مدت (ثانیه)", format: (v) => fa(Math.round(v * 10) / 10), better: "none" },
  { key: "p95", label: "روشن‌ترین بخش‌ها (۰–۲۵۵)", format: (v) => fa(Math.round(v)), better: "band" },
  { key: "p50", label: "روشنایی میانه", format: (v) => fa(Math.round(v)), better: "band" },
  { key: "p5", label: "تیره‌ترین بخش‌ها", format: (v) => fa(Math.round(v)), better: "none" },
  { key: "clip_hi", label: "پیکسل‌های سوخته (٪)", format: (v) => fa(Math.round(v * 100)), better: "lower" },
  { key: "cast_rb", label: "رنگ‌زدگی روی خنثی‌ها", format: (v) => fa(Math.round(v)), better: "lower" },
  { key: "flicker", label: "پرش نور بین فریم‌ها", format: (v) => fa(Math.round(v)), better: "lower" },
  { key: "shake", label: "لرزش دست (٪ عرض)", format: (v) => fa(Math.round(v * 1000) / 10), better: "lower" },
  { key: "snr_db", label: "فاصله‌ی صدا از نویز (دسی‌بل)", format: (v) => fa(Math.round(v)), better: "higher" },
  { key: "noise_floor_db", label: "بلندی نویز زمینه (دسی‌بل)", format: (v) => fa(Math.round(v)), better: "lower" },
  { key: "silence_count", label: "تعداد سکوت‌ها", format: (v) => fa(Math.round(v)), better: "lower" },
  { key: "silence_seconds", label: "سکوت (ثانیه)", format: (v) => fa(Math.round(v)), better: "lower" },
  { key: "faces", label: "چهره‌ها", format: (v) => fa(Math.round(v)), better: "none" },
];

const VERDICT_TONE: Record<string, "ok" | "bad" | "neutral" | "info"> = {
  better: "ok",
  worse: "bad",
  neutral: "neutral",
  applied: "info",
};

const VERDICT_LABEL: Record<string, string> = {
  better: "بهتر شد",
  worse: "بدتر شد",
  neutral: "تغییری نکرد",
  applied: "اعمال شد",
};

function asNumber(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  return null;
}

/** Whether the change in one metric reads as an improvement, a regression, or
 *  nothing worth colouring. */
function direction(row: Row, before: number, after: number): "ok" | "bad" | "neutral" {
  if (row.better === "none") return "neutral";
  const size = Math.abs(after - before);
  const scale = row.key === "clip_hi" ? 0.02 : row.key === "shake" ? 0.001 : 2;
  if (size < scale) return "neutral";
  if (row.key === "noise_floor_db") return after < before ? "ok" : "bad";
  if (row.better === "lower") return Math.abs(after) < Math.abs(before) ? "ok" : "bad";
  if (row.better === "higher") return after > before ? "ok" : "bad";
  // band: closer to a healthy exposure band is better
  const distance = (v: number) => (v < 100 ? 100 - v : v > 200 ? v - 200 : 0);
  const d0 = distance(before);
  const d1 = distance(after);
  if (d0 === d1) return "neutral";
  return d1 < d0 ? "ok" : "bad";
}

export default function BeforeAfter({
  beforeUrl,
  afterUrl,
  beforeLabel = "ویدیوی اصلی",
  afterLabel = "بعد از تدوین",
  before,
  after,
  effects = [],
  note,
  improved,
  summary,
  compact = false,
}: Props) {
  const left = useRef<HTMLVideoElement>(null);
  const right = useRef<HTMLVideoElement>(null);
  const [playing, setPlaying] = useState(false);
  const [position, setPosition] = useState(0);

  // One clock for two players. The edited cut is often shorter (silences
  // removed), so the slider is a fraction of each video's own length rather
  // than a shared timestamp — both reach their end together.
  useEffect(() => {
    const video = left.current;
    if (!video) return;
    const onTime = () => {
      if (video.duration) setPosition(video.currentTime / video.duration);
    };
    const onEnd = () => setPlaying(false);
    video.addEventListener("timeupdate", onTime);
    video.addEventListener("ended", onEnd);
    return () => {
      video.removeEventListener("timeupdate", onTime);
      video.removeEventListener("ended", onEnd);
    };
  }, []);

  function both(action: (v: HTMLVideoElement) => void) {
    [left.current, right.current].forEach((v) => v && action(v));
  }

  function toggle() {
    if (playing) {
      both((v) => v.pause());
      setPlaying(false);
    } else {
      both((v) => {
        void v.play().catch(() => undefined);
      });
      setPlaying(true);
    }
  }

  function seek(fraction: number) {
    both((v) => {
      if (v.duration) v.currentTime = fraction * v.duration;
    });
    setPosition(fraction);
  }

  function restart() {
    seek(0);
    if (!playing) toggle();
  }

  const rows = ROWS.map((row) => {
    const b = asNumber(before?.[row.key]);
    const a = asNumber(after?.[row.key]);
    if (b === null && a === null) return null;
    const tone = b !== null && a !== null ? direction(row, b, a) : "neutral";
    return { row, b, a, tone };
  }).filter(Boolean) as { row: Row; b: number | null; a: number | null; tone: "ok" | "bad" | "neutral" }[];

  return (
    <div
      className="flex flex-col gap-3 rounded-xl p-3"
      style={{ border: "1px solid var(--line)", background: "var(--surface-2, transparent)" }}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm font-bold" style={{ color: "var(--text)" }}>
            قبل و بعد
          </span>
          {improved === true && <Badge tone="ok">بهتر شد</Badge>}
          {improved === false && <Badge tone="warn">بعضی سنجه‌ها بدتر شد</Badge>}
          {summary && (
            <span className="text-xs" style={{ color: "var(--text-3)" }}>
              {summary}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <Button variant="secondary" onClick={toggle}>
            {playing ? "⏸ توقف" : "▶ پخش هر دو"}
          </Button>
          <Button variant="ghost" onClick={restart}>
            از اول
          </Button>
        </div>
      </div>

      <div className={`grid gap-3 ${compact ? "sm:grid-cols-2" : "md:grid-cols-2"}`}>
        {[
          { ref: left, url: beforeUrl, label: beforeLabel, tone: "neutral" as const },
          { ref: right, url: afterUrl, label: afterLabel, tone: "ok" as const },
        ].map((side) => (
          <div key={side.label} className="flex flex-col gap-1">
            <Badge tone={side.tone}>{side.label}</Badge>
            <video
              ref={side.ref}
              src={side.url}
              playsInline
              preload="metadata"
              controls={false}
              onClick={toggle}
              className="w-full rounded-lg"
              style={{ maxHeight: compact ? 240 : 360, background: "#000", cursor: "pointer" }}
            />
          </div>
        ))}
      </div>

      <input
        type="range"
        min={0}
        max={1000}
        value={Math.round(position * 1000)}
        onChange={(e) => seek(Number(e.target.value) / 1000)}
        className="w-full"
        aria-label="جای پخش"
      />

      {note && (
        <p className="text-sm leading-7" style={{ color: "var(--text-2)" }}>
          {note}
        </p>
      )}

      {effects.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {effects.map((effect) => (
            <span
              key={`${effect.tool}-${effect.detail}`}
              className="rounded-lg px-2 py-1 text-xs"
              style={{
                background:
                  VERDICT_TONE[effect.verdict] === "ok"
                    ? "var(--ok-soft, #dcfce7)"
                    : VERDICT_TONE[effect.verdict] === "bad"
                      ? "var(--bad-soft, #fee2e2)"
                      : "var(--surface-2, #f1f5f9)",
                color: "var(--text)",
              }}
            >
              <b>{effect.title}</b> · {VERDICT_LABEL[effect.verdict] ?? effect.verdict}
              {effect.detail ? ` — ${effect.detail}` : ""}
            </span>
          ))}
        </div>
      )}

      {rows.length > 0 && (
        <table className="w-full text-xs" style={{ color: "var(--text-2)" }}>
          <thead>
            <tr style={{ color: "var(--text-3)" }}>
              <th className="py-1 text-start font-normal">سنجه</th>
              <th className="py-1 text-start font-normal">قبل</th>
              <th className="py-1 text-start font-normal">بعد</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(({ row, b, a, tone }) => (
              <tr key={row.key} style={{ borderTop: "1px solid var(--line)" }}>
                <td className="py-1">{row.label}</td>
                <td className="py-1" dir="ltr">
                  {b === null ? "—" : row.format(b)}
                </td>
                <td
                  className="py-1 font-bold"
                  dir="ltr"
                  style={{
                    color:
                      tone === "ok" ? "var(--ok)" : tone === "bad" ? "var(--bad)" : "var(--text)",
                  }}
                >
                  {a === null ? "—" : row.format(a)}
                  {tone === "ok" ? " ✓" : tone === "bad" ? " ✗" : ""}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
