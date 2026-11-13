import { useEffect, useMemo, useRef, useState } from "react";

import { fa } from "../../../../components/ui";
import { countRender } from "../../../../hooks/perfCount";
import type { Catalogue } from "../api";
import { Section, Slider } from "./controls";
import {
  CURVE_KEYS, Curve, CurveKey, FullColor, HSL_KEYS, LookDef, SLIDERS, SliderKey, ZONES, Zone, applyColor, cleanColor, colorIsNeutral,
  compactColor, pchip, rgbToWheel, wheelToRgb,
} from "./color";
import type { ColorParams, HslKey, MediaClip, Rgb } from "./model";
import { usePlayheadStore } from "./playhead";
import "./color.css";

type Props = {
  clip: MediaClip;
  cat: Catalogue["color"];
  /** هنگامِ کشیدن (فقط پیش‌نمایش) */
  onLive(color: ColorParams): void;
  /** رها شدن ⇒ یک گام در تاریخچه */
  onEnd(label: string): void;
  /** کارِ یک‌باره؛ `undefined` = همهٔ رنگ پاک شود */
  onApply(label: string, color: ColorParams | undefined): void;
  /** نگه‌داشتنِ دکمهٔ «قبل/بعد»: true = رنگ موقتاً خاموش */
  onCompare?(on: boolean): void;
  /** بومِ فریمِ فعلی برای تصویرِ کوچکِ حالت‌ها */
  thumbSource?: () => HTMLCanvasElement | null;
};

const BASIC_LIGHT: SliderKey[] = ["exposure", "contrast", "highlights", "shadows", "whites", "blacks"];
const BASIC_COLOR: SliderKey[] = ["temperature", "tint", "saturation", "vibrance"];
const FX_KEYS: SliderKey[] = ["sharpen", "denoise", "blur", "vignette", "grain"];
const CURVE_COLOR: Record<CurveKey, string> = { m: "var(--text)", r: "#ef4444", g: "#22c55e", b: "#3b82f6" };
const nz = (...v: number[]) => v.some((x) => Math.abs(x) > 1e-6);

const Dot = () => <span className="ws-dot" aria-hidden />;

export default function ColorPanel({ clip, cat, onLive, onEnd, onApply, onCompare, thumbSource }: Props) {
  countRender("ColorPanel");
  const looks = useMemo<LookDef[]>(() => cat.looks.map((l) => ({ key: l.key, title: l.title, params: l.params as ColorParams })), [cat.looks]);
  const colorRef = useRef<ColorParams>({});
  colorRef.current = clip.color ?? {};
  const full = useMemo(() => cleanColor(clip.color), [clip.color]);
  const meta = useMemo(() => {
    const m: Record<string, { min: number; max: number; step: number; title: string }> = {};
    for (const s of cat.sliders) m[s.key] = { min: s.min, max: s.max, step: s.step, title: s.title };
    return m;
  }, [cat.sliders]);

  const emit = (next: ColorParams) => {
    colorRef.current = next;
    onLive(compactColor(next) ?? {});
  };
  const set = (patch: ColorParams) => emit({ ...colorRef.current, ...patch });
  const latest = () => cleanColor(colorRef.current);

  const slider = (key: SliderKey) => {
    const m = meta[key] ?? { min: SLIDERS[key][0], max: SLIDERS[key][1], step: key === "exposure" ? 0.05 : 1, title: key };
    return (
      <Slider
        key={key} label={m.title} value={full[key]} min={m.min} max={m.max} step={m.step} def={SLIDERS[key][2]} digits={key === "exposure" ? 2 : 0}
        onLive={(v) => set({ [key]: v } as ColorParams)} onEnd={() => onEnd(m.title)}
      />
    );
  };

  const neutral = colorIsNeutral(clip.color, looks);
  const basicDirty = [...BASIC_LIGHT, ...BASIC_COLOR].some((k) => Math.abs(full[k] - SLIDERS[k][2]) > 1e-6);
  const wheelsDirty = ZONES.some((z) => nz(...full.wheels[z]));
  const hslDirty = HSL_KEYS.some((k) => nz(full.hsl[k].h, full.hsl[k].s, full.hsl[k].l));
  const curvesDirty = CURVE_KEYS.some((k) => full.curves[k].some(([x, y]) => Math.abs(x - y) > 1e-4));
  const fxDirty = FX_KEYS.some((k) => Math.abs(full[k]) > 1e-6);

  return (
    <div className="cp-root" dir="rtl" data-testid="color-panel">
      <div className="cp-top">
        <button type="button" className="ws-btn" disabled={neutral} onClick={() => onApply("بازنشانیِ رنگ", undefined)} data-testid="color-reset-all">↺ بازنشانیِ همه</button>
        {onCompare && (
          <button
            type="button" className="ws-btn" title="نگه دارید تا تصویرِ بدونِ رنگ را ببینید" data-testid="color-compare"
            onPointerDown={() => onCompare(true)} onPointerUp={() => onCompare(false)} onPointerLeave={() => onCompare(false)} onPointerCancel={() => onCompare(false)}
            onKeyDown={(e) => { if (e.key === " " || e.key === "Enter") onCompare(true); }} onKeyUp={(e) => { if (e.key === " " || e.key === "Enter") onCompare(false); }}
          >
            قبل / بعد (نگه دارید)
          </button>
        )}
        <span className="ws-muted">{neutral ? "رنگی اعمال نشده" : "رنگ اعمال شده"}</span>
      </div>

      <Section title="پایه (نور و رنگ)" defaultOpen badge={basicDirty ? <Dot /> : null} testId="color-basic">
        <div className="cp-sub">نور</div>
        {BASIC_LIGHT.map(slider)}
        <div className="cp-sub">رنگ</div>
        {BASIC_COLOR.map(slider)}
      </Section>

      <Section title="حالت‌ها (Looks)" badge={full.look ? <Dot /> : null} testId="color-looks">
        <LookGrid
          looks={looks} current={full.look} thumbSource={thumbSource} clipId={clip.id}
          onPick={(key) => {
            const base = { ...colorRef.current };
            if (key) onApply(`حالت: ${looks.find((l) => l.key === key)?.title ?? key}`, compactColor({ ...base, look: key, look_amount: full.look_amount }));
            else {
              delete base.look;
              delete base.look_amount;
              onApply("حذفِ حالت", compactColor(base));
            }
          }}
        />
        {full.look && (
          <Slider
            label={`شدتِ حالت`} value={full.look_amount} min={cat.look_amount.min} max={cat.look_amount.max} step={1} def={cat.look_amount.default} digits={0} unit="٪"
            onLive={(v) => set({ look_amount: v })} onEnd={() => onEnd("شدتِ حالت")}
          />
        )}
      </Section>

      <Section title="منحنی‌ها" badge={curvesDirty ? <Dot /> : null} testId="color-curves">
        <CurveEditor
          curves={full.curves} titles={cat.curves}
          onLive={(curves) => set({ curves })} onEnd={() => onEnd("منحنی")}
          onReset={(ch) => {
            const c = { ...(colorRef.current.curves ?? {}) };
            delete c[ch];
            onApply("بازنشانیِ منحنی", compactColor({ ...colorRef.current, curves: c }));
          }}
        />
      </Section>

      <Section title="چرخ‌های رنگ" badge={wheelsDirty ? <Dot /> : null} testId="color-wheels">
        <div className="cp-wheels">
          {ZONES.map((z) => (
            <ColorWheel
              key={z} title={cat.wheels.find((w) => w.key === z)?.title ?? z} value={full.wheels[z]}
              onLive={(rgb) => set({ wheels: { ...latest().wheels, [z]: rgb } })} onEnd={() => onEnd("چرخِ رنگ")}
              onReset={() => onApply("بازنشانیِ چرخِ رنگ", compactColor({ ...colorRef.current, wheels: { ...latest().wheels, [z as Zone]: [0, 0, 0] } }))}
            />
          ))}
        </div>
        <p className="ws-hint">بکشید تا رنگِ آن بخشِ روشنایی (سایه / میانه / هایلایت) مایل شود؛ دوبار کلیک = بازنشانی.</p>
      </Section>

      <Section title="HSL (رنگ به رنگ)" badge={hslDirty ? <Dot /> : null} testId="color-hsl">
        <HslEditor
          full={full} swatches={cat.hsl}
          onLive={(key, v) => set({ hsl: { ...latest().hsl, [key]: v } })} onEnd={() => onEnd("HSL")}
        />
      </Section>

      <Section title="افکت‌های تصویر" badge={fxDirty ? <Dot /> : null} testId="color-fx">
        {FX_KEYS.map(slider)}
        <p className="ws-hint">محو و حذفِ نویز در پیش‌نمایش با تقریب دیده می‌شوند؛ خروجی دقیق است.</p>
      </Section>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════ حالت‌ها
function LookGrid({ looks, current, thumbSource, clipId, onPick }: {
  looks: LookDef[]; current: string; thumbSource?: () => HTMLCanvasElement | null; clipId: string; onPick: (key: string) => void;
}) {
  const [tick, setTick] = useState(0);
  const [hasThumb, setHasThumb] = useState(false);
  const refs = useRef<Record<string, HTMLCanvasElement | null>>({});
  // ۱۴۰۵/۰۸/۲۳: ساختنِ تصویرِ کوچکِ همهٔ حالت‌ها گران است و قبلاً با هر رندرِ فضای کار (۱۴ بار در ثانیه هنگامِ پخش، با هر پیکسلِ کشیدنِ لغزنده) تکرار می‌شد
  // چون thumbSource هر رندر تابعِ تازه‌ای بود. حالا فقط وقتی دوباره ساخته می‌شود که قطعه/فهرستِ حالت‌ها عوض شود، دکمهٔ «تازه‌سازی» زده شود، یا فریمِ مانیتور
  // واقعاً عوض شده و سرِ پخش ~۳۰۰ میلی‌ثانیه آرام گرفته باشد (هنگامِ پخش/کشیدنِ سرِ پخش نه).
  const ph = usePlayheadStore();
  const [frameTick, setFrameTick] = useState(0);
  useEffect(() => {
    let last = ph.get();
    let timer = 0;
    const off = ph.subscribe(() => {
      const t = ph.get();
      if (t === last) return;
      last = t;
      window.clearTimeout(timer);
      timer = window.setTimeout(() => setFrameTick((v) => v + 1), 300);
    });
    return () => {
      off();
      window.clearTimeout(timer);
    };
  }, [ph]);

  useEffect(() => {
    const src = thumbSource?.();
    if (!src || !src.width || !src.height) {
      setHasThumb(false);
      return;
    }
    setHasThumb(true);
    countRender("lookThumbBuild");
    const w = 72;
    const h = Math.max(24, Math.round((72 * src.height) / src.width));
    const tmp = document.createElement("canvas");
    tmp.width = w;
    tmp.height = h;
    const tctx = tmp.getContext("2d", { willReadFrequently: true });
    if (!tctx) return;
    tctx.drawImage(src, 0, 0, w, h);
    const base = tctx.getImageData(0, 0, w, h);
    for (const key of ["", ...looks.map((l) => l.key)]) {
      const cv = refs.current[key];
      const ctx = cv?.getContext("2d");
      if (!cv || !ctx) continue;
      cv.width = w;
      cv.height = h;
      const img = new ImageData(new Uint8ClampedArray(base.data), w, h);
      if (key) applyColor(img, { look: key, look_amount: 100 }, looks);
      ctx.putImageData(img, 0, 0);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tick, frameTick, clipId, looks, thumbSource]);

  const tile = (key: string, title: string) => (
    <button key={key || "none"} type="button" className={`cp-look ${current === key ? "is-on" : ""}`} aria-pressed={current === key} onClick={() => onPick(key)} data-look={key || "none"} title={title}>
      {hasThumb ? <canvas ref={(el) => { refs.current[key] = el; }} /> : <span className="cp-look-ph" aria-hidden />}
      <span className="cp-look-t">{title}</span>
    </button>
  );
  return (
    <div>
      <div className="cp-looks">
        {tile("", "بدونِ حالت")}
        {looks.map((l) => tile(l.key, l.title))}
      </div>
      <button type="button" className="ws-link" onClick={() => setTick((t) => t + 1)}>↻ تازه‌سازیِ تصویرِ کوچک‌ها از فریمِ فعلی</button>
      {!hasThumb && <p className="ws-hint">سرِ پخش را روی این قطعه بگذارید تا تصویرِ کوچکِ هر حالت دیده شود.</p>}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════ منحنی‌ها
const SZ = 200;
const PAD = 10;
const IN = SZ - 2 * PAD;
const cx = (x: number) => PAD + x * IN;
const cy = (y: number) => PAD + (1 - y) * IN;
const clamp01 = (v: number) => Math.max(0, Math.min(1, v));

function CurveEditor({ curves, titles, onLive, onEnd, onReset }: {
  curves: FullColor["curves"]; titles: { key: string; title: string }[];
  onLive: (c: NonNullable<ColorParams["curves"]>) => void; onEnd: () => void; onReset: (ch: CurveKey) => void;
}) {
  const [ch, setCh] = useState<CurveKey>("m");
  const [drag, setDrag] = useState<{ idx: number; pts: Curve; out: boolean } | null>(null);
  const svg = useRef<SVGSVGElement>(null);
  const pts: Curve = drag ? drag.pts : curves[ch];

  const emit = (p: Curve) => onLive({ ...curves, [ch]: p });
  const unit = (e: React.PointerEvent | React.MouseEvent): [number, number] => {
    const r = svg.current!.getBoundingClientRect();
    const sx = ((e.clientX - r.left) / r.width) * SZ;
    const sy = ((e.clientY - r.top) / r.height) * SZ;
    return [(sx - PAD) / IN, 1 - (sy - PAD) / IN];
  };
  const nearest = (ux: number, uy: number, list: Curve): number => {
    let best = -1;
    let bd = 13;
    list.forEach(([x, y], i) => {
      const d = Math.hypot(cx(x) - cx(ux), cy(y) - cy(uy));
      if (d < bd) { bd = d; best = i; }
    });
    return best;
  };

  const down = (e: React.PointerEvent) => {
    if (e.button !== 0) return;
    e.preventDefault();
    svg.current?.setPointerCapture(e.pointerId);
    const [ux, uy] = unit(e);
    let idx = nearest(ux, uy, pts);
    let next = pts.map((p) => [...p] as [number, number]);
    if (idx < 0) {
      if (next.length >= 8) return;
      const x = Math.max(0.03, Math.min(0.97, ux));
      let at = next.findIndex((p) => p[0] > x);
      if (at < 0) at = next.length - 1;
      if (x - next[at - 1][0] < 0.04 || next[at][0] - x < 0.04) return;
      next = [...next.slice(0, at), [x, clamp01(uy)], ...next.slice(at)];
      idx = at;
      emit(next);
    }
    setDrag({ idx, pts: next, out: false });
  };
  const move = (e: React.PointerEvent) => {
    if (!drag) return;
    const [ux, uy] = unit(e);
    const next = drag.pts.map((p) => [...p] as [number, number]);
    const last = next.length - 1;
    const interior = drag.idx > 0 && drag.idx < last;
    const x = interior ? Math.max(next[drag.idx - 1][0] + 0.02, Math.min(next[drag.idx + 1][0] - 0.02, ux)) : next[drag.idx][0];
    next[drag.idx] = [x, clamp01(uy)];
    const out = interior && (ux < -0.1 || ux > 1.1 || uy < -0.14 || uy > 1.14);
    setDrag({ idx: drag.idx, pts: next, out });
    emit(out ? next.filter((_, k) => k !== drag.idx) : next);
  };
  const up = () => {
    if (!drag) return;
    const final = drag.out ? drag.pts.filter((_, k) => k !== drag.idx) : drag.pts;
    setDrag(null);
    emit(final);
    onEnd();
  };
  const dbl = (e: React.MouseEvent) => {
    const [ux, uy] = unit(e);
    const i = nearest(ux, uy, pts);
    if (i > 0 && i < pts.length - 1) {
      emit(pts.filter((_, k) => k !== i));
      onEnd();
    }
  };

  const f = pchip(pts);
  const path = Array.from({ length: 65 }, (_, k) => {
    const x = k / 64;
    return `${k === 0 ? "M" : "L"}${cx(x).toFixed(1)},${cy(clamp01(f(x))).toFixed(1)}`;
  }).join(" ");
  const color = CURVE_COLOR[ch];
  const identity = curves[ch].length === 2 && curves[ch].every(([x, y]) => Math.abs(x - y) < 1e-4);

  return (
    <div className="cp-curve">
      <div className="flex flex-wrap gap-1 mb-2" role="tablist">
        {CURVE_KEYS.map((k) => (
          <button key={k} type="button" role="tab" aria-selected={ch === k} className={`ws-chip ${ch === k ? "is-on" : ""}`} onClick={() => setCh(k)} data-curve-tab={k}>
            <span className="cp-curve-dot" style={{ background: CURVE_COLOR[k] }} aria-hidden /> {titles.find((t) => t.key === k)?.title ?? k}
          </button>
        ))}
      </div>
      <svg
        ref={svg} viewBox={`0 0 ${SZ} ${SZ}`} className="cp-curve-svg" data-testid="curve-svg"
        onPointerDown={down} onPointerMove={move} onPointerUp={up} onPointerCancel={up} onDoubleClick={dbl}
      >
        <rect x={PAD} y={PAD} width={IN} height={IN} className="cp-curve-bg" />
        {[0.25, 0.5, 0.75].map((q) => (
          <g key={q} className="cp-curve-grid">
            <line x1={cx(q)} y1={PAD} x2={cx(q)} y2={PAD + IN} />
            <line x1={PAD} y1={cy(q)} x2={PAD + IN} y2={cy(q)} />
          </g>
        ))}
        <line x1={cx(0)} y1={cy(0)} x2={cx(1)} y2={cy(1)} className="cp-curve-diag" />
        <path d={path} fill="none" stroke={color} strokeWidth={2} />
        {pts.map(([x, y], i) => (
          <circle key={i} cx={cx(x)} cy={cy(y)} r={drag?.idx === i ? 6 : 5} fill={color} stroke="var(--surface-2)" strokeWidth={2} className="cp-curve-pt" data-pt={i} />
        ))}
      </svg>
      <div className="flex items-center justify-between">
        <span className="ws-hint">کلیک = نقطهٔ تازه · کشیدن = جابه‌جایی · دوبار کلیک یا کشیدن به بیرون = حذف</span>
        <button type="button" className="ws-btn" disabled={identity} onClick={() => onReset(ch)}>↺</button>
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════ چرخ‌های رنگ
const WHEEL_PX = 96;
let wheelBitmap: ImageData | null = null;

function hsv(h: number, s: number, v: number): [number, number, number] {
  const c = v * s;
  const hp = (((h % 360) + 360) % 360) / 60;
  const x = c * (1 - Math.abs((hp % 2) - 1));
  const [r, g, b] = hp < 1 ? [c, x, 0] : hp < 2 ? [x, c, 0] : hp < 3 ? [0, c, x] : hp < 4 ? [0, x, c] : hp < 5 ? [x, 0, c] : [c, 0, x];
  const m = v - c;
  return [(r + m) * 255, (g + m) * 255, (b + m) * 255];
}

function ColorWheel({ title, value, onLive, onEnd, onReset }: { title: string; value: Rgb; onLive: (v: Rgb) => void; onEnd: () => void; onReset: () => void }) {
  const cv = useRef<HTMLCanvasElement>(null);
  const pad = useRef<HTMLDivElement>(null);
  const dragging = useRef(false);

  useEffect(() => {
    const ctx = cv.current?.getContext("2d");
    if (!ctx) return;
    if (!wheelBitmap) {
      const img = new ImageData(WHEEL_PX, WHEEL_PX);
      for (let py = 0; py < WHEEL_PX; py++) {
        for (let px = 0; px < WHEEL_PX; px++) {
          const dx = (px + 0.5 - WHEEL_PX / 2) / (WHEEL_PX / 2);
          const dy = -(py + 0.5 - WHEEL_PX / 2) / (WHEEL_PX / 2);
          const rho = Math.hypot(dx, dy);
          const i = (py * WHEEL_PX + px) * 4;
          if (rho > 1) continue;
          const [r, g, b] = hsv((Math.atan2(dy, dx) * 180) / Math.PI, Math.min(1, rho) * 0.9, 0.95);
          img.data[i] = r;
          img.data[i + 1] = g;
          img.data[i + 2] = b;
          img.data[i + 3] = 255;
        }
      }
      wheelBitmap = img;
    }
    ctx.putImageData(wheelBitmap, 0, 0);
  }, []);

  const read = (e: React.PointerEvent): Rgb => {
    const r = pad.current!.getBoundingClientRect();
    let x = ((e.clientX - r.left) / r.width) * 2 - 1;
    let y = -(((e.clientY - r.top) / r.height) * 2 - 1);
    const m = Math.hypot(x, y);
    if (m > 1) { x /= m; y /= m; }
    return wheelToRgb(x, y);
  };
  const [wx, wy] = rgbToWheel(value);
  const m = Math.hypot(wx, wy);
  const sx = m > 1 ? wx / m : wx;
  const sy = m > 1 ? wy / m : wy;
  const active = nz(...value);

  return (
    <div className="cp-wheel" data-wheel={title}>
      <div
        ref={pad} className="cp-wheel-pad" role="slider" aria-label={title} aria-valuetext={active ? "تغییر داده شده" : "خنثی"} tabIndex={0}
        onPointerDown={(e) => { e.preventDefault(); dragging.current = true; pad.current?.setPointerCapture(e.pointerId); onLive(read(e)); }}
        onPointerMove={(e) => { if (dragging.current) onLive(read(e)); }}
        onPointerUp={() => { if (dragging.current) { dragging.current = false; onEnd(); } }}
        onPointerCancel={() => { dragging.current = false; }}
        onDoubleClick={onReset}
      >
        <canvas ref={cv} width={WHEEL_PX} height={WHEEL_PX} />
        <i className="cp-wheel-dot" style={{ left: `${(sx * 0.5 + 0.5) * 100}%`, top: `${(0.5 - sy * 0.5) * 100}%` }} />
      </div>
      <div className="cp-wheel-cap">
        <span>{title}</span>
        {active && <button type="button" className="pro-reset" aria-label={`بازنشانی ${title}`} onClick={onReset}>↺</button>}
      </div>
      <small className="ws-muted" dir="ltr">{active ? value.map((v) => (v >= 0 ? "+" : "") + fa(Math.round(v * 100) / 100)).join(" ") : ""}</small>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════ HSL
function HslEditor({ full, swatches, onLive, onEnd }: {
  full: FullColor; swatches: { key: string; title: string; color: string }[];
  onLive: (key: HslKey, v: { h: number; s: number; l: number }) => void; onEnd: () => void;
}) {
  const [sel, setSel] = useState<HslKey>("red");
  const v = full.hsl[sel];
  const title = swatches.find((s) => s.key === sel)?.title ?? sel;
  return (
    <div>
      <div className="cp-sws" role="tablist">
        {HSL_KEYS.map((k) => {
          const sw = swatches.find((s) => s.key === k);
          const on = nz(full.hsl[k].h, full.hsl[k].s, full.hsl[k].l);
          return (
            <button
              key={k} type="button" role="tab" aria-selected={sel === k} aria-label={sw?.title ?? k} title={sw?.title ?? k}
              className={`cp-sw ${sel === k ? "is-on" : ""} ${on ? "is-set" : ""}`} style={{ background: sw?.color ?? "#888" }} onClick={() => setSel(k)} data-hsl={k}
            />
          );
        })}
      </div>
      <div className="cp-sub">{title}</div>
      <Slider label="رنگمایه (Hue)" value={v.h} min={-180} max={180} step={1} def={0} unit="°" digits={0} onLive={(x) => onLive(sel, { ...v, h: x })} onEnd={onEnd} />
      <Slider label="اشباع" value={v.s} min={-100} max={100} step={1} def={0} digits={0} onLive={(x) => onLive(sel, { ...v, s: x })} onEnd={onEnd} />
      <Slider label="روشنایی" value={v.l} min={-100} max={100} step={1} def={0} digits={0} onLive={(x) => onLive(sel, { ...v, l: x })} onEnd={onEnd} />
    </div>
  );
}
