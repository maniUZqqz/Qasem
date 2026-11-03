import { useRef, useState } from "react";

import { Curve, Pt, curveLut } from "./engine";

const CHANNELS: { key: keyof Curve; title: string; color: string }[] = [
  { key: "rgb", title: "همه", color: "#e5e7eb" },
  { key: "red", title: "قرمز", color: "#f87171" },
  { key: "green", title: "سبز", color: "#4ade80" },
  { key: "blue", title: "آبی", color: "#60a5fa" },
];

const SIZE = 224;
const PAD = 8;
const span = SIZE - 2 * PAD;

const toX = (v: number) => PAD + (v / 255) * span;
const toY = (v: number) => SIZE - PAD - (v / 255) * span;
const fromX = (px: number) => Math.round(Math.max(0, Math.min(255, ((px - PAD) / span) * 255)));
const fromY = (py: number) => Math.round(Math.max(0, Math.min(255, ((SIZE - PAD - py) / span) * 255)));

const IDENTITY: Pt[] = [
  [0, 0],
  [255, 255],
];

/**
 * منحنیِ تُن (Curves): نقطه را بکشید، روی خالی کلیک کنید تا نقطه اضافه شود، دوبار کلیک روی نقطه ⇐ برداشتن.
 * همان قراردادِ کیت: { rgb|red|green|blue: [[ورودی، خروجی], …] } بینِ ۰ و ۲۵۵.
 */
export default function CurveEditor({
  value,
  onChange,
}: {
  value: Curve;
  /** commit=false هنگامِ کشیدن (پیش‌نمایش)، true وقتی رها شد (ثبت در تاریخچه) */
  onChange: (next: Curve, commit: boolean) => void;
}) {
  const [channel, setChannel] = useState<keyof Curve>("rgb");
  const [drag, setDrag] = useState<number | null>(null);
  const svg = useRef<SVGSVGElement>(null);
  const info = CHANNELS.find((c) => c.key === channel)!;
  const pts: Pt[] = value[channel] && value[channel]!.length >= 2 ? value[channel]! : IDENTITY;

  const set = (next: Pt[], commit: boolean) => {
    const sorted = [...next].sort((a, b) => a[0] - b[0]);
    const identity = sorted.length < 2 || sorted.every((p) => p[0] === p[1]);
    const out: Curve = { ...value };
    if (identity) delete out[channel];
    else out[channel] = sorted;
    onChange(out, commit);
  };

  const local = (e: React.PointerEvent) => {
    const box = svg.current!.getBoundingClientRect();
    const k = SIZE / box.width;
    return [(e.clientX - box.left) * k, (e.clientY - box.top) * k] as const;
  };

  const lut = curveLut(pts);
  const path = lut
    ? Array.from({ length: 64 }, (_, i) => {
        const x = Math.round((i / 63) * 255);
        return `${i ? "L" : "M"}${toX(x).toFixed(1)} ${toY(lut[x]).toFixed(1)}`;
      }).join(" ")
    : `M${toX(0)} ${toY(0)} L${toX(255)} ${toY(255)}`;

  return (
    <div data-testid="curve-editor">
      <div className="mb-2 flex gap-1">
        {CHANNELS.map((c) => (
          <button
            key={c.key}
            type="button"
            className={`ws-chip ${channel === c.key ? "is-on" : ""}`}
            style={channel === c.key ? { borderColor: c.color } : undefined}
            onClick={() => setChannel(c.key)}
          >
            {c.title}
            {value[c.key] ? " •" : ""}
          </button>
        ))}
        <button type="button" className="ws-chip ms-auto" onClick={() => onChange({}, true)} title="بازگشتِ همهٔ منحنی‌ها به خط راست">
          بازنشانی
        </button>
      </div>
      <svg
        ref={svg}
        viewBox={`0 0 ${SIZE} ${SIZE}`}
        className="curve-svg"
        style={{ direction: "ltr" }}
        onPointerDown={(e) => {
          const [px, py] = local(e);
          const near = pts.findIndex((p) => Math.hypot(toX(p[0]) - px, toY(p[1]) - py) < 11);
          if (near >= 0) {
            setDrag(near);
          } else {
            const next: Pt[] = [...pts, [fromX(px), fromY(py)]];
            set(next, false);
            setDrag(next.length - 1);
          }
          (e.target as Element).setPointerCapture?.(e.pointerId);
        }}
        onPointerMove={(e) => {
          if (drag === null) return;
          const [px, py] = local(e);
          const next = pts.map((p, i) => (i === drag ? ([fromX(px), fromY(py)] as Pt) : p));
          // نقطه‌ها روی هم نیفتند و ترتیبِ ورودی حفظ شود
          const x = next[drag][0];
          if (next.some((p, i) => i !== drag && p[0] === x)) return;
          set(next, false);
        }}
        onPointerUp={() => {
          if (drag !== null) set(pts, true);
          setDrag(null);
        }}
        onDoubleClick={(e) => {
          const box = svg.current!.getBoundingClientRect();
          const k = SIZE / box.width;
          const px = (e.clientX - box.left) * k;
          const py = (e.clientY - box.top) * k;
          const near = pts.findIndex((p) => Math.hypot(toX(p[0]) - px, toY(p[1]) - py) < 11);
          if (near >= 0 && pts.length > 2 && near !== 0 && near !== pts.length - 1) set(pts.filter((_, i) => i !== near), true);
        }}
      >
        <rect x={PAD} y={PAD} width={span} height={span} fill="rgba(0,0,0,.35)" stroke="var(--line-strong)" />
        {[1, 2, 3].map((i) => (
          <g key={i} stroke="var(--line)">
            <line x1={PAD + (span * i) / 4} y1={PAD} x2={PAD + (span * i) / 4} y2={SIZE - PAD} />
            <line x1={PAD} y1={PAD + (span * i) / 4} x2={SIZE - PAD} y2={PAD + (span * i) / 4} />
          </g>
        ))}
        <line x1={toX(0)} y1={toY(0)} x2={toX(255)} y2={toY(255)} stroke="var(--line-strong)" strokeDasharray="3 3" />
        <path d={path} fill="none" stroke={info.color} strokeWidth={2} />
        {pts.map((p, i) => (
          <circle key={i} cx={toX(p[0])} cy={toY(p[1])} r={5} fill={info.color} stroke="#000" strokeWidth={1} data-point={i} />
        ))}
      </svg>
      <p className="mt-1 text-xs" style={{ color: "var(--text-3)" }}>
        کلیک ⇐ نقطهٔ تازه · دوبار کلیک روی نقطه ⇐ برداشتن · {pts.length} نقطه
      </p>
    </div>
  );
}
