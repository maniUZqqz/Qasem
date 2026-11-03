import { Select, fa } from "../../../../components/ui";
import type { Params, Tool } from "../api";
import { CF_DEFAULT, CropFormat, FrameSpec, cropFormatOpParams, normalizeCropFormat } from "./frame";
import type { Hist } from "./panelTypes";
import type { ProState } from "./types";

/** «قابِ مربعِ فروشگاه (سفید)» — جای kit_square ِ قدیمی: مربعِ ۲۰۰۰، جا دادنِ کلِ کالا، زمینهٔ سفید، حاشیهٔ ۶٪ */
export const STORE_FRAME: Params = cropFormatOpParams(normalizeCropFormat({ format: "custom", size: 2000, fit: "contain", focus: "center", fill: "white", padding: 6 }));

const FALLBACK_FORMATS: [string, string][] = [
  ["square", "مربع ۱:۱ (پستِ اینستاگرام)"], ["portrait", "عمودی ۴:۵ (پستِ عمودی)"], ["story", "۹:۱۶ (استوری، ریلز، شورتز)"],
  ["landscape", "افقی ۱٫۹۱:۱ (بنرِ سایت، تلگرام، لینک)"], ["wide", "افقی ۱۶:۹ (یوتیوب، اسلاید)"], ["store", "مربعِ ۲۰۰۰ (دیجی‌کالا، باسلام، ترب)"],
  ["custom", "مربعِ دلخواه (ضلع به پیکسل)"],
];
const FOCUS: [string, string][] = [["smart", "خودکار"], ["center", "وسط"], ["top", "بالا"], ["bottom", "پایین"], ["left", "چپ"], ["right", "راست"]];
const FILL: [string, string][] = [["blur", "محوِ خودِ عکس"], ["white", "سفید"], ["black", "سیاه"], ["color", "رنگِ دلخواه"], ["transparent", "شفاف"]];

const chip = (on: boolean) => `ws-chip ${on ? "is-on" : ""}`;

type Props = {
  state: ProState;
  hist: Hist;
  /** ابزارِ crop_format از فهرستِ سرور (برچسبِ قالب‌ها)؛ نبود ⇒ فهرستِ داخلی */
  tool?: Tool;
  /** قابِ فعلی (اندازهٔ بومِ نهایی) */
  spec: FrameSpec;
  photoSize: [number, number];
};

/**
 * کارتِ «قاب (اندازهٔ خروجی)»: اول قاب را می‌چینید (قالبِ شبکه، مربعِ فروشگاه، اندازهٔ دلخواه)، بعد لایه‌ها را روی همان قاب می‌گذارید.
 * همه‌چیز در `state.tools.crop_format` می‌نشیند (همان کارِ crop_format ِ سرور؛ پیش‌نمایشِ مرورگر هندسه‌اش را عیناً بازتولید می‌کند).
 */
export default function FrameCard({ state, hist, tool, spec, photoSize }: Props) {
  const raw = state.tools.crop_format;
  const cf: CropFormat | null = raw ? normalizeCropFormat(raw) : null;
  const formats: [string, string][] = tool?.params.find((p) => p.key === "format")?.options?.map((o) => [o.value, o.label] as [string, string]) ?? FALLBACK_FORMATS;

  const make = (patch: Partial<CropFormat>): Params => cropFormatOpParams(normalizeCropFormat({ ...(cf ?? CF_DEFAULT), ...patch, window: [] }));
  const setTools = (label: string, params: Params | null, extra?: (s: ProState) => ProState) =>
    hist.apply(label, (s) => {
      const t = { ...s.tools };
      delete t.kit_square;
      if (params) t.crop_format = params;
      else delete t.crop_format;
      return extra ? extra({ ...s, tools: t }) : { ...s, tools: t };
    });
  const live = (params: Params) => hist.live((s) => ({ ...s, tools: { ...s.tools, crop_format: params } }));

  const pickFormat = (v: string) => (v === "none" ? setTools("بدونِ قاب", null) : setTools("قاب: " + (formats.find((f) => f[0] === v)?.[1] ?? v), make({ format: v })));
  const pickFill = (v: string) =>
    setTools("پرکردنِ قاب", make({ fill: v as CropFormat["fill"] }), v === "transparent" ? (s) => (s.out.format === "jpeg" ? { ...s, out: { ...s.out, format: "png" } } : s) : undefined);

  return (
    <div className="ws-card" data-testid="frame-card">
      <div className="ws-card-title">قاب (اندازهٔ خروجی)</div>
      <p className="ws-hint">اول قاب را انتخاب کنید؛ متن و لوگو روی همین قاب چیده می‌شوند و جایشان در پیش‌نمایش و خروجی یکی است.</p>

      <label className="ws-field">
        <span>اندازهٔ قاب</span>
        <Select value={cf ? cf.format : "none"} onChange={(e) => pickFormat(e.target.value)} aria-label="اندازهٔ قاب" data-testid="frame-format">
          <option value="none">بدونِ قاب (اندازهٔ خودِ عکس)</option>
          {formats.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </Select>
      </label>

      {cf && cf.format === "custom" && (
        <label className="ws-field">
          <span>ضلعِ قابِ دلخواه (پیکسل)</span>
          <div className="flex items-center gap-2">
            <input type="range" min={200} max={4000} step={10} value={cf.size} aria-label="ضلعِ قاب" data-testid="frame-size"
              onChange={(e) => live(make({ size: Number(e.target.value) }))} onPointerUp={() => hist.end("اندازهٔ قاب")} onKeyUp={() => hist.end("اندازهٔ قاب")} />
            <b dir="ltr" className="ws-muted" style={{ minWidth: 48 }}>{fa(cf.size)}</b>
          </div>
        </label>
      )}

      {cf && (
        <>
          <div className="ws-field">
            <span>روش</span>
            <div className="flex flex-wrap gap-1">
              <button type="button" className={chip(cf.fit === "cover")} onClick={() => setTools("قاب: پر کردن", make({ fit: "cover" }))} data-testid="frame-fit-cover">پر کردن (برش)</button>
              <button type="button" className={chip(cf.fit === "contain")} onClick={() => setTools("قاب: جا دادن", make({ fit: "contain" }))} data-testid="frame-fit-contain">جا دادن (بی‌برش)</button>
            </div>
          </div>

          {cf.fit === "cover" ? (
            <label className="ws-field">
              <span>سوژه کجاست</span>
              <Select value={cf.focus} onChange={(e) => setTools("قاب: جای سوژه", make({ focus: e.target.value as CropFormat["focus"] }))} aria-label="سوژه کجاست" data-testid="frame-focus">
                {FOCUS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </Select>
            </label>
          ) : (
            <>
              <label className="ws-field">
                <span>پرکردنِ دورِ عکس</span>
                <Select value={cf.fill} onChange={(e) => pickFill(e.target.value)} aria-label="پرکردنِ دور" data-testid="frame-fill">
                  {FILL.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                </Select>
              </label>
              {cf.fill === "color" && (
                <label className="ws-field">
                  <span>رنگِ زمینه</span>
                  <input type="color" value={cf.fill_color} aria-label="رنگِ زمینه" data-testid="frame-fill-color" className="h-9 w-16 cursor-pointer rounded"
                    onChange={(e) => live(make({ fill_color: e.target.value }))} onPointerUp={() => hist.end("رنگِ قاب")} onBlur={() => hist.end("رنگِ قاب")} />
                </label>
              )}
              {cf.fill === "transparent" && <p className="ws-hint">زمینهٔ شفاف فقط در خروجیِ PNG یا WebP می‌ماند (JPEG روی سفید می‌نشیند).</p>}
              <label className="ws-field">
                <span>حاشیه (٪ از قاب)</span>
                <div className="flex items-center gap-2">
                  <input type="range" min={0} max={40} step={1} value={cf.padding} aria-label="حاشیه" data-testid="frame-padding"
                    onChange={(e) => live(make({ padding: Number(e.target.value) }))} onPointerUp={() => hist.end("حاشیهٔ قاب")} onKeyUp={() => hist.end("حاشیهٔ قاب")} />
                  <b dir="ltr" className="ws-muted" style={{ minWidth: 30 }}>{fa(cf.padding)}%</b>
                </div>
              </label>
            </>
          )}
        </>
      )}

      <div className="flex flex-wrap items-center gap-1">
        <button type="button" className={chip(!!cf && cf.format === "custom" && cf.fit === "contain" && cf.fill === "white")} onClick={() => setTools("قابِ مربعِ فروشگاه", STORE_FRAME)} data-testid="frame-store-preset">
          قابِ مربعِ فروشگاه (سفید)
        </button>
        {cf && <button type="button" className="ws-link" onClick={() => setTools("بدونِ قاب", null)} data-testid="frame-clear">برداشتنِ قاب</button>}
      </div>

      <p className="ws-hint" data-testid="frame-size-info" dir="rtl">
        بومِ نهایی: <b dir="ltr">{fa(spec.Wf)}×{fa(spec.Hf)}</b> پیکسل
        {" "}(عکسِ اصل <span dir="ltr">{fa(photoSize[0])}×{fa(photoSize[1])}</span>)
        {cf && cf.fit === "cover" && cf.focus === "smart" ? " — جای سوژه را مرورگر پیدا می‌کند و همان در خروجی می‌آید" : ""}
      </p>
    </div>
  );
}
