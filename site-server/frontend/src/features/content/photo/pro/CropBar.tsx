import { fa } from "../../../../components/ui";
import { ASPECTS, FULL } from "../manual/model";
import { resizeCrop } from "./cropMath";
import type { Hist } from "./panelTypes";
import type { ProState } from "./types";

type Props = {
  state: ProState;
  hist: Hist;
  /** اندازهٔ عکسِ چرخیده و صاف‌شده (پیکسل) — مبنای نسبتِ برش */
  Wt: number;
  Ht: number;
  aspectKey: string;
  aspectRatio: number | null;
  chooseAspect: (key: string) => void;
  flipAspect: boolean;
  setFlipAspect: (v: boolean) => void;
  storeFrameOn: boolean;
  toggleStoreFrame: () => void;
  rotate: (delta: number) => void;
  onAuto: () => void;
  autoMsg: string;
  onApply: () => void;
  onCancel: () => void;
};

/** نوارِ گزینه‌های ابزارِ برش: نسبت‌ها، اندازهٔ عددی، چرخش/قرینه/صاف‌کردن، تأیید و انصراف */
export default function CropBar(p: Props) {
  const { state, hist, Wt, Ht } = p;
  const cw = Math.round(state.crop.w * Wt);
  const ch = Math.round(state.crop.h * Ht);
  const locked = p.aspectKey !== "free" && !!p.aspectRatio;
  const setSize = (w: number | null, h: number | null) => {
    const next = resizeCrop(state.crop, Wt, Ht, w, h, locked ? p.aspectRatio : null);
    hist.apply("اندازهٔ برش", (s) => ({ ...s, crop: next }));
  };
  const num = (v: string) => (v.trim() === "" ? NaN : Number(v.replace(/[۰-۹]/g, (d) => String("۰۱۲۳۴۵۶۷۸۹".indexOf(d)))));
  const isFull = state.crop.x <= 0.0005 && state.crop.y <= 0.0005 && state.crop.w >= 0.9995 && state.crop.h >= 0.9995;
  return (
    <>
      <div className="crop-group" role="group" aria-label="نسبتِ برش" data-testid="crop-aspects">
        {ASPECTS.map((a) => (
          <button key={a.key} type="button" className={`ws-chip ${p.aspectKey === a.key ? "is-on" : ""}`} onClick={() => p.chooseAspect(a.key)} data-aspect={a.key} aria-pressed={p.aspectKey === a.key}>
            {a.title}
          </button>
        ))}
        <button type="button" className={`ws-chip ${p.storeFrameOn ? "is-on" : ""}`} onClick={p.toggleStoreFrame} aria-pressed={p.storeFrameOn} data-testid="crop-store-frame"
          title="خروجی مربعِ ۲۰۰۰ با کالا وسطِ قاب و زمینهٔ سفید (دیجی‌کالا، باسلام، ترب)؛ همان «قابِ فروشگاه» تنظیم‌ها">
          قابِ فروشگاه
        </button>
        <label className="ws-check" title="جای پهنا و ارتفاعِ نسبت را عوض می‌کند (عمودی ⇄ افقی)">
          <input type="checkbox" checked={p.flipAspect} onChange={(e) => p.setFlipAspect(e.target.checked)} />
          عمودی ⇄ افقی
        </label>
      </div>

      <div className="crop-group" role="group" aria-label="اندازه" data-testid="crop-size-group">
        <label className="crop-num">
          <span>پهنا</span>
          <input type="number" inputMode="numeric" min={8} max={Math.round(Wt)} value={cw} dir="ltr" aria-label="پهنای برش (پیکسل)" data-testid="crop-w"
            onChange={(e) => { const v = num(e.target.value); if (Number.isFinite(v) && v >= 8) setSize(v, null); }} />
        </label>
        <span aria-hidden="true">×</span>
        <label className="crop-num">
          <span>ارتفاع</span>
          <input type="number" inputMode="numeric" min={8} max={Math.round(Ht)} value={ch} dir="ltr" aria-label="ارتفاعِ برش (پیکسل)" data-testid="crop-h"
            onChange={(e) => { const v = num(e.target.value); if (Number.isFinite(v) && v >= 8) setSize(null, v); }} />
        </label>
        <span className="ws-muted" dir="ltr" data-testid="crop-size">{fa(cw)}×{fa(ch)} px</span>
        <button type="button" className="ws-link" disabled={isFull} onClick={() => hist.apply("بازنشانیِ برش", (s) => ({ ...s, crop: { ...FULL } }))} data-testid="crop-reset">بازنشانیِ برش</button>
      </div>

      <div className="crop-group" role="group" aria-label="چرخش و قرینه" data-testid="crop-rotate-group">
        <button type="button" className="ws-chip" onClick={() => p.rotate(90)} title="چرخشِ ۹۰ درجه پادساعتگرد" data-testid="crop-rot-l">↺ ۹۰°</button>
        <button type="button" className="ws-chip" onClick={() => p.rotate(-90)} title="چرخشِ ۹۰ درجه ساعتگرد" data-testid="crop-rot-r">↻ ۹۰°</button>
        <button type="button" className={`ws-chip ${state.flipH ? "is-on" : ""}`} aria-pressed={state.flipH} onClick={() => hist.apply("قرینهٔ افقی", (s) => ({ ...s, flipH: !s.flipH }))} data-testid="crop-flip-h">قرینهٔ افقی</button>
        <button type="button" className={`ws-chip ${state.flipV ? "is-on" : ""}`} aria-pressed={state.flipV} onClick={() => hist.apply("قرینهٔ عمودی", (s) => ({ ...s, flipV: !s.flipV }))} data-testid="crop-flip-v">قرینهٔ عمودی</button>
        <label className="pro-opt" title="کجیِ افق را اصلاح کنید؛ دوبار کلیک = صفر">
          <span>زاویه</span>
          <input type="range" min={-15} max={15} step={0.1} value={state.straighten} aria-label="زاویهٔ صاف‌کردن" data-testid="crop-angle"
            onChange={(e) => hist.live((s) => ({ ...s, straighten: Number(e.target.value) }))}
            onPointerUp={() => hist.end("صاف کردن")} onKeyUp={() => hist.end("صاف کردن")}
            onDoubleClick={() => hist.apply("صاف کردن", (s) => ({ ...s, straighten: 0 }))} />
          <b dir="ltr">{fa(state.straighten)}°</b>
        </label>
        <button type="button" className="ws-chip" onClick={p.onAuto} title="افق یا خطوطِ ساختمان را پیدا می‌کند و صاف می‌کند" data-testid="crop-auto">تشخیصِ خودکارِ افق</button>
        {p.autoMsg && <span className="ws-muted" role="status" data-testid="crop-auto-msg">{p.autoMsg}</span>}
      </div>

      <div className="crop-group crop-actions" role="group" aria-label="پایان">
        <button type="button" className="ws-btn primary" onClick={p.onApply} title="Enter" data-testid="crop-apply">✓ اعمال (Enter)</button>
        <button type="button" className="ws-btn" onClick={p.onCancel} title="Esc" data-testid="crop-cancel">✕ انصراف (Esc)</button>
        <span className="ws-muted crop-hint">بکشید تا قاب جابه‌جا شود؛ گوشه‌ها و لبه‌ها = اندازه؛ بیرونِ قاب بکشید = قابِ تازه</span>
      </div>
    </>
  );
}
