import { useEffect, useRef, useState, type ReactNode } from "react";

import Icon from "../../../../components/Icon";
import { Table } from "../../../../components/ui";
import {
  TEXT,
  axisLabel,
  buildLinePaths,
  chartValue,
  gapLimit,
  niceMax,
  runDuration,
  segmentBars,
  seriesStats,
  thinPoints,
  toFa,
  type JobStat,
  type Point,
} from "./model";

/** رونوشتِ متن. روی نشانیِ بدونِ https (مثل این پنل) `navigator.clipboard` نیست، پس روشِ قدیمی هم دارد. */
export function CopyButton({ text }: { text: string }) {
  const [done, setDone] = useState(false);
  const timer = useRef<number | null>(null);
  useEffect(
    () => () => {
      if (timer.current) window.clearTimeout(timer.current);
    },
    [],
  );
  const copy = async () => {
    let ok = false;
    try {
      await navigator.clipboard.writeText(text);
      ok = true;
    } catch {
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.setAttribute("readonly", "");
      ta.style.cssText = "position:fixed;opacity:0;top:0;left:0";
      document.body.appendChild(ta);
      ta.select();
      try {
        ok = document.execCommand("copy");
      } catch {
        ok = false;
      }
      ta.remove();
    }
    if (ok) {
      setDone(true);
      if (timer.current) window.clearTimeout(timer.current);
      timer.current = window.setTimeout(() => setDone(false), 2000);
    }
  };
  return (
    <button type="button" className="nmr-copy" onClick={() => void copy()}>
      <Icon name={done ? "check" : "copy"} size={13} />
      {done ? TEXT.copied : TEXT.copy}
    </button>
  );
}

/** نوارِ روشن/خاموش: هر بازهٔ سبز یک نوبتِ وصل‌بودن؛ جای قرمزِ کم‌رنگ = خاموش. زمان از چپ (قدیمی) به راست (اکنون). */
export function TimelineBar({ segments, lo, hi }: { segments: [number, number][]; lo: number; hi: number }) {
  const bars = segmentBars(segments, lo, hi);
  const span = hi - lo;
  return (
    <div>
      <div className="nmr-timeline" role="img" aria-label={TEXT.timeline}>
        {bars.map((b, i) => (
          <i key={i} style={{ left: `${b.left}%`, width: `${b.width}%` }} />
        ))}
      </div>
      <div className="nmr-axis" aria-hidden="true">
        <span>{axisLabel(lo, span)}</span>
        <span>{axisLabel(lo + span / 2, span)}</span>
        <span>{TEXT.now}</span>
      </div>
    </div>
  );
}

const W = 300;
const H = 76;

/** نمودارِ خطیِ سبک (SVG، بدونِ کتابخانه). وقفه‌ها (سرورِ خاموش) خط را می‌شکنند. */
export function LineChart({
  title,
  points,
  lo,
  hi,
  tone,
  unit,
  max,
}: {
  title: string;
  points: Point[];
  lo: number;
  hi: number;
  tone: "brand" | "info" | "ok" | "warn" | "bad";
  unit: "pct" | "gb" | "c";
  max?: number;
}) {
  const pts = thinPoints(points, 240);
  const st = seriesStats(pts);
  const yMax = niceMax(pts.map((p) => p[1]), max);
  const paths = buildLinePaths(pts, lo, hi, W, H, yMax, gapLimit(hi - lo));
  return (
    <div className={`nmr-chart c-${tone}`}>
      <div className="nmr-chart-head">
        <span>{title}</span>
        <span className="nmr-chart-now">{st ? chartValue(unit, st.last) : "—"}</span>
      </div>
      {st ? (
        <>
          <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" role="img" aria-label={title}>
            <line className="grid" x1="0" y1={H} x2={W} y2={H} />
            <line className="grid" x1="0" y1={H / 2} x2={W} y2={H / 2} strokeDasharray="3 4" />
            {paths.areas.map((d, i) => (
              <path key={`a${i}`} className="area" d={d} />
            ))}
            {paths.lines.map((d, i) => (
              <path key={`l${i}`} className="line" d={d} />
            ))}
            {paths.dots.map(([x, y], i) => (
              <circle key={`d${i}`} className="dot" cx={x} cy={y} r="2.2" />
            ))}
          </svg>
          <div className="nmr-chart-foot">
            <span>کمترین: {chartValue(unit, st.min)}</span>
            <span>میانگین: {chartValue(unit, st.avg)}</span>
            <span>بیشترین: {chartValue(unit, st.max)}</span>
          </div>
        </>
      ) : (
        <div className="nmr-chart-empty">{TEXT.noSeries}</div>
      )}
    </div>
  );
}

export type StatRow = { key: string; label: ReactNode; stat: JobStat };

/** جدولِ آمارِ کارها (نوع یا سرور): تعداد، موفق، ناموفق، لغو، میانگینِ اجرا و انتظار. */
export function StatTable({ rows, total, firstColumn }: { rows: StatRow[]; total?: JobStat; firstColumn: string }) {
  return (
    <div className="nmr-tablewrap">
      <Table>
        <thead>
          <tr>
            <th className="wrap">{firstColumn}</th>
            <th className="num">تعداد</th>
            <th className="num">موفق</th>
            <th className="num">ناموفق</th>
            <th className="num">لغو</th>
            <th className="num">میانگینِ اجرا</th>
            <th className="num">میانگینِ انتظار در صف</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.key}>
              <td className="wrap">{r.label}</td>
              <StatCells stat={r.stat} />
            </tr>
          ))}
        </tbody>
        {total && (
          <tfoot>
            <tr>
              <td className="wrap">جمع</td>
              <StatCells stat={total} />
            </tr>
          </tfoot>
        )}
      </Table>
    </div>
  );
}

function StatCells({ stat }: { stat: JobStat }) {
  const open = stat.running + stat.waiting;
  return (
    <>
      <td className="num">
        {toFa(stat.count)}
        {open > 0 && <span className="nmr-small"> ({toFa(open)} در جریان)</span>}
      </td>
      <td className="num" style={stat.success ? { color: "var(--ok)" } : undefined}>
        {toFa(stat.success)}
      </td>
      <td className="num" style={stat.failed ? { color: "var(--bad)", fontWeight: 700 } : undefined}>
        {toFa(stat.failed)}
      </td>
      <td className="num">{toFa(stat.cancelled)}</td>
      <td className="num">{runDuration(stat.avg_run_s)}</td>
      <td className="num">{runDuration(stat.avg_wait_s)}</td>
    </>
  );
}
