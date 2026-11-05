import { memo, useMemo, useRef, useState } from "react";

import { fa } from "../../../../components/ui";
import { Kf, removeKey, setKey, valueAt } from "./keyframes";
import {
  MediaClip, Project, VOL_MIN_DB, clipLength, findClip, isMedia, quantize, snapDb, timecode, updateClip, volDbToLin, volFracToDb, volLinToDb, volToFrac,
} from "./model";

/** کارهایی که قطعه‌های روی تایم‌لاین (خطِ بلندی، دستگیره‌های محو) برای ویرایش لازم دارند؛ یک شیءِ پایدار تا memo ِ قطعه‌ها نشکند */
export type ClipActs = {
  /** پروژهٔ همین لحظه (پایهٔ کشیدن) */
  base: () => Project;
  /** پیش‌نمایشِ زنده (در تاریخچه نمی‌رود) */
  live: (p: Project) => void;
  /** پایانِ ویرایش ⇒ یک گام در تاریخچه */
  commit: (label: string) => void;
  /** قطعه را انتخاب کن (اگر هنوز نیست) */
  pick: (id: string) => void;
};

const clamp = (x: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, x));
/** نیم‌ارتفاعِ نوارِ لمس‌پذیرِ دورِ خط (پیکسل): با انگشت کمی پهن‌تر */
const HIT = typeof window !== "undefined" && !!window.matchMedia && window.matchMedia("(pointer: coarse)").matches ? 9 : 6;
export const fmtDb = (db: number): string =>
  db <= VOL_MIN_DB + 0.01 ? "−∞" : `${db < 0 ? "−" : db > 0 ? "+" : ""}${fa(Math.abs(Math.round(db * 10) / 10)).replace(".", "٫")} dB`;

type Props = {
  clip: MediaClip;
  w: number;
  h: number;
  px: number;
  fps: number;
  /** قطعه انتخاب است (خط پررنگ) */
  strong: boolean;
  /** خط را می‌شود کشید (قطعه انتخاب است، ابزارِ «انتخاب» و ترک قفل نیست) */
  interactive: boolean;
  acts: ClipActs;
};

/**
 * خطِ بلندیِ روی موج (rubber band): بالای قطعه +۶ dB، ۰ dB حدودِ ۶۵٪ از پایین، پایین = بی‌صدا.
 * بدونِ کلیدفریم: کشیدنِ خط، بلندیِ ثابت را عوض می‌کند. با کلیدفریم (kf.volume): خط منحنی را دنبال می‌کند؛
 * دو بار زدن (یا Alt+کلیک) روی خط کلید می‌گذارد، نقطه‌ها کشیدنی‌اند و دو بار زدن روی نقطه آن را برمی‌دارد.
 * زمانِ کلیدها نسبت به شروعِ قطعه روی تایم‌لاین است (مثلِ keyframes.ts).
 */
const VolumeLine = memo(function VolumeLine({ clip, w, h, px, fps, strong, interactive, acts }: Props) {
  const svg = useRef<SVGSVGElement>(null);
  const tap = useRef<{ t: number; x: number; y: number; k: number } | null>(null);
  const [read, setRead] = useState<{ x: number; y: number; text: string } | null>(null);
  const keys = clip.kf?.volume;
  const keyed = !!keys && keys.length > 0;
  const len = clipLength(clip);
  const pe = interactive ? "all" : "none";

  // خط (برای کشیدن) و نوارِ لمس‌پذیرِ دورِ آن؛ نوار چندضلعیِ پُر است تا حتی روی خطِ صاف هم جعبهٔ غیرصفر داشته باشد
  const { points, band } = useMemo(() => {
    if (!keyed || !keys) return { points: "", band: "" };
    const xs = new Set<number>();
    const n = Math.max(2, Math.min(240, Math.ceil(w / 3)));
    for (let i = 0; i <= n; i++) xs.add((i / n) * w);
    for (const k of keys) if (k.t * px >= 0 && k.t * px <= w) xs.add(k.t * px);
    const pts = [...xs].sort((a, b) => a - b).map((x) => [x, clamp(h * volToFrac(valueAt(keys, x / px, clip.volume)), 0.5, h - 0.5)] as const);
    const f = (x: number, y: number) => `${x.toFixed(1)},${y.toFixed(1)}`;
    return {
      points: pts.map(([x, y]) => f(x, y)).join(" "),
      band: [...pts.map(([x, y]) => f(x, y - HIT)), ...[...pts].reverse().map(([x, y]) => f(x, y + HIT))].join(" "),
    };
  }, [keyed, keys, w, h, px, clip.volume]);

  const y0 = clamp(h * volToFrac(clip.volume), 1, h - 1);

  /** دو بار زدنِ پشت‌سرهم روی همان نقطه (ماوس و لمس) */
  const isDouble = (e: React.PointerEvent, k: number) => {
    const prev = tap.current;
    const hit = !!prev && prev.k === k && e.timeStamp - prev.t < 420 && Math.abs(e.clientX - prev.x) < 20 && Math.abs(e.clientY - prev.y) < 20;
    tap.current = hit ? null : { t: e.timeStamp, x: e.clientX, y: e.clientY, k };
    return hit;
  };

  const addKey = (localT: number) => {
    const orig = acts.base();
    const f = findClip(orig, clip.id);
    if (!f || !isMedia(f.clip)) return;
    const c = f.clip;
    const t = clamp(quantize(localT, fps), 0, clipLength(c));
    const v = valueAt(c.kf?.volume, t, c.volume);
    acts.live(updateClip(orig, c.id, { kf: { ...c.kf, volume: setKey(c.kf?.volume, t, v, "volume", "linear") } }));
    acts.commit("کلیدفریمِ بلندی");
  };

  const dropKey = (idx: number) => {
    const orig = acts.base();
    const f = findClip(orig, clip.id);
    if (!f || !isMedia(f.clip)) return;
    const c = f.clip;
    const list = c.kf?.volume ?? [];
    const k = list[idx];
    if (!k) return;
    const rest = removeKey(list, k.t);
    const kf: Kf = { ...c.kf };
    if (rest.length === 0) {
      delete kf.volume;
      acts.live(updateClip(orig, c.id, { kf, volume: k.v }));
    } else acts.live(updateClip(orig, c.id, { kf: { ...kf, volume: rest } }));
    acts.commit("حذفِ کلیدفریمِ بلندی");
  };

  const watch = (move: (e: PointerEvent) => void, end: () => void) => {
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      window.removeEventListener("pointercancel", up);
      end();
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    window.addEventListener("pointercancel", up);
  };

  const onLineDown = (e: React.PointerEvent) => {
    if (e.button !== 0 || !svg.current) return;
    const rect = svg.current.getBoundingClientRect();
    if (e.altKey || isDouble(e, -1)) {
      e.stopPropagation();
      addKey((e.clientX - rect.left) / px);
      return;
    }
    // با کلیدفریم: کشیدنِ خط خودِ قطعه را می‌برد (رویداد بالا می‌رود)؛ فقط دو بار زدن کلید می‌گذارد
    if (keyed) return;
    e.stopPropagation();
    acts.pick(clip.id);
    const orig = acts.base();
    const f0 = volToFrac(clip.volume);
    const sy = e.clientY;
    let moved = false;
    watch(
      (ev) => {
        if (!moved && Math.abs(ev.clientY - sy) < 2) return;
        moved = true;
        const fr = clamp(f0 + (ev.clientY - sy) / Math.max(1, rect.height), 0, 1);
        const db = snapDb(volFracToDb(fr));
        acts.live(updateClip(orig, clip.id, { volume: Math.round(volDbToLin(db) * 1000) / 1000 }));
        setRead({ x: ev.clientX - rect.left, y: h * fr, text: fmtDb(db) });
      },
      () => {
        setRead(null);
        if (moved) acts.commit("بلندیِ قطعه");
      },
    );
  };

  const onPointDown = (e: React.PointerEvent, idx: number) => {
    e.stopPropagation();
    if (e.button !== 0 || !svg.current) return;
    acts.pick(clip.id);
    if (isDouble(e, idx)) {
      dropKey(idx);
      return;
    }
    const rect = svg.current.getBoundingClientRect();
    const orig = acts.base();
    const f = findClip(orig, clip.id);
    if (!f || !isMedia(f.clip)) return;
    const c = f.clip;
    const list = c.kf?.volume ?? [];
    const k0 = list[idx];
    if (!k0) return;
    const sx = e.clientX;
    const sy = e.clientY;
    const fr0 = volToFrac(k0.v);
    const L = clipLength(c);
    let moved = false;
    watch(
      (ev) => {
        if (!moved && Math.abs(ev.clientX - sx) < 2 && Math.abs(ev.clientY - sy) < 2) return;
        moved = true;
        const lo = idx > 0 ? list[idx - 1].t + 0.03 : 0;
        const hi = idx < list.length - 1 ? list[idx + 1].t - 0.03 : L;
        const t = ev.shiftKey ? k0.t : clamp(quantize(k0.t + (ev.clientX - sx) / px, fps), lo, Math.max(lo, hi));
        const fr = clamp(fr0 + (ev.clientY - sy) / Math.max(1, rect.height), 0, 1);
        const db = snapDb(volFracToDb(fr));
        const nk = list.map((k, i) => (i === idx ? { ...k, t: Math.round(t * 1000) / 1000, v: Math.round(volDbToLin(db) * 10000) / 10000 } : k));
        acts.live(updateClip(orig, c.id, { kf: { ...c.kf, volume: nk } }));
        setRead({ x: t * px, y: h * fr, text: `${fmtDb(db)} · ${timecode(c.at + t, fps)}` });
      },
      () => {
        setRead(null);
        if (moved) acts.commit("جابه‌جاییِ کلیدفریمِ بلندی");
      },
    );
  };

  return (
    <>
      <svg ref={svg} className={`tl-vol ${strong ? "is-strong" : ""} ${keyed ? "is-keyed" : ""}`} width={w} height={h} aria-hidden="true">
        {keyed ? (
          <>
            <polyline className="vl-under" points={points} />
            <polyline className="vl-line" points={points} />
            <polygon className="vl-hit" points={band} data-testid="vol-line" style={{ pointerEvents: pe }} onPointerDown={onLineDown}>
              <title>خطِ بلندی — دو بار بزنید = کلیدِ تازه</title>
            </polygon>
          </>
        ) : (
          <>
            <line className="vl-under" x1={0} x2={w} y1={y0} y2={y0} />
            <line className="vl-line" x1={0} x2={w} y1={y0} y2={y0} />
            <rect className="vl-hit" x={0} y={y0 - HIT} width={w} height={HIT * 2} data-testid="vol-line" style={{ pointerEvents: pe }} onPointerDown={onLineDown}>
              <title>خطِ بلندی: بالا/پایین بکشید. دو بار زدن = کلیدفریم</title>
            </rect>
            {strong && w > 110 && (
              <text className="vl-db" x={26} y={y0 < 14 ? y0 + 11 : y0 - 3}>{fmtDb(volLinToDb(clip.volume))}</text>
            )}
          </>
        )}
        {keyed && keys && keys.map((k, i) => {
          const cx = k.t * px;
          if (cx < -1 || cx > w + 1) return null;
          const cy = clamp(h * volToFrac(k.v), 4, h - 4);
          return (
            <g key={i}>
              <circle className="vl-dot" cx={cx} cy={cy} r={4} />
              <circle className="vl-dot-hit" cx={cx} cy={cy} r={11} data-testid="vol-point" style={{ pointerEvents: interactive ? "all" : "none" }} onPointerDown={(e) => onPointDown(e, i)}>
                <title>{`${fmtDb(volLinToDb(k.v))} در ${timecode(clip.at + k.t, fps)} — بکشید؛ دو بار زدن = حذف`}</title>
              </circle>
            </g>
          );
        })}
      </svg>
      {read && (
        <span className="vl-read" style={{ left: clamp(read.x - 34, 2, Math.max(2, w - 110)), top: clamp(read.y - 26, 0, Math.max(0, h - 16)) }} data-testid="vol-readout">{read.text}</span>
      )}
    </>
  );
});

export default VolumeLine;
