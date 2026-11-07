import { useState } from "react";

import { fa } from "../../../../components/ui";
import { MediaClip } from "../manual/model";
import { INTERPRET_FPS, clearInterpretFps, interpretFps, isSlowed, setDenoise, setFrames, setInterpret } from "../manual/r6ops";
import { ANCHOR_PRESETS, DEFAULT_LUMA, DEFAULT_MATTE, anchorIsCentre, lensIsFlat, matteSourceFor, setAnchor, setLens, setLuma, setTrackMatte } from "../manual/r5fx";
import type { PanelProps } from "./types";

type Section = "luma" | "lens" | "anchor" | "matte" | "denoise" | "frames" | "interpret";

function Slider({ label, value, min, max, step, onLive, onCommit, testId, hint }: {
  label: string; value: number; min: number; max: number; step: number; onLive: (v: number) => void; onCommit: (v: number) => void; testId: string; hint?: string;
}) {
  return (
    <label className="fx-row" title={hint}>
      <span className="fx-label">{label}</span>
      <input type="range" min={min} max={max} step={step} value={value} data-testid={testId}
        onChange={(e) => onLive(Number(e.target.value))}
        onPointerUp={(e) => onCommit(Number((e.target as HTMLInputElement).value))}
        onKeyUp={(e) => onCommit(Number((e.target as HTMLInputElement).value))} />
      <span className="fx-val">{fa(Math.round(value * 100) / 100)}</span>
    </label>
  );
}

/** ابزارهای قطعه: کلیدِ روشنایی (Luma key)، اصلاحِ لنز، نقطهٔ لنگر؛ هر سه روی قطعهٔ انتخاب‌شده، با گامِ برگشت */
export function ClipFxPanel({ api, props }: PanelProps) {
  const clip = api.selected && api.selected.clip.type === "media" && api.selected.track.kind === "video" && !(api.selected.clip as MediaClip).adjust ? (api.selected.clip as MediaClip) : null;
  const [open, setOpen] = useState<Section>(((props?.section as Section) ?? "luma"));
  if (!clip) return <p className="ws-hint" data-testid="fx-empty">اول یک ویدیو یا عکس را روی تایم‌لاین انتخاب کنید.</p>;
  const luma = clip.luma ?? { ...DEFAULT_LUMA, on: false };
  const lens = clip.lens ?? { k1: 0, k2: 0 };
  const anchor = clip.anchor ?? { x: 0, y: 0 };
  const matte = clip.track_matte ?? DEFAULT_MATTE;
  const matteSrc = matteSourceFor(api.project, clip.id);
  const native = api.media[clip.ref]?.fps ?? 0;
  const interp = clip.interpret ?? {};
  const slowed = isSlowed(clip);
  const tab = (k: Section, t: string) => (
    <button key={k} type="button" role="tab" aria-selected={open === k} className={`ws-chip ${open === k ? "is-on" : ""}`} onClick={() => setOpen(k)} data-testid={`fx-tab-${k}`}>{t}</button>
  );
  return (
    <div data-testid="clipfx-panel">
      <div className="hv-tabs" role="tablist">{tab("luma", "کلیدِ روشنایی")}{tab("lens", "اصلاحِ لنز")}{tab("anchor", "نقطهٔ لنگر")}{tab("matte", "ماتِ ترک")}{tab("denoise", "نویزگیر")}{tab("frames", "ترکیبِ فریم")}{tab("interpret", "تفسیرِ فیلم")}</div>
      {open === "luma" && (
        <div data-testid="fx-luma">
          <label className="fx-check">
            <input type="checkbox" checked={!!clip.luma?.on} data-testid="luma-on" onChange={(e) => api.apply("کلیدِ روشنایی", (p) => (e.target.checked ? setLuma(p, clip.id, { on: true }) : setLuma(p, clip.id, null)))} />
            <span>کلیدِ روشنایی روشن باشد</span>
          </label>
          <div className="mk-top">
            <button type="button" className={`ws-chip ${luma.mode === "dark" ? "is-on" : ""}`} data-testid="luma-dark" disabled={!clip.luma?.on} onClick={() => api.apply("کلیدِ روشنایی", (p) => setLuma(p, clip.id, { mode: "dark" }))}>تاریک‌ها شفاف شوند</button>
            <button type="button" className={`ws-chip ${luma.mode === "bright" ? "is-on" : ""}`} data-testid="luma-bright" disabled={!clip.luma?.on} onClick={() => api.apply("کلیدِ روشنایی", (p) => setLuma(p, clip.id, { mode: "bright" }))}>روشن‌ها شفاف شوند</button>
          </div>
          <Slider label="دامنه" value={luma.tolerance} min={0} max={1} step={0.01} testId="luma-tol" hint="هرچه بیشتر، بخشِ بیشتری از تاریک (یا روشن) شفاف می‌شود"
            onLive={(v) => api.live((p) => setLuma(p, clip.id, { tolerance: v }))} onCommit={() => api.end("کلیدِ روشنایی")} />
          <Slider label="نرمیِ لبه" value={luma.softness} min={0} max={1} step={0.01} testId="luma-soft" hint="لبهٔ بینِ شفاف و دیده‌شده چقدر نرم باشد"
            onLive={(v) => api.live((p) => setLuma(p, clip.id, { softness: v }))} onCommit={() => api.end("کلیدِ روشنایی")} />
          <p className="ws-hint">مناسبِ افکت‌های نور، دود و آتش روی پس‌زمینهٔ سیاه (تاریک‌ها شفاف) یا متنِ سیاه روی سفید (روشن‌ها شفاف). قطعه را روی ترکِ بالاتر از تصویرِ اصلی بگذارید.</p>
        </div>
      )}
      {open === "lens" && (
        <div data-testid="fx-lens">
          <Slider label="بشکه‌ای ⇄ بالشتکی" value={lens.k1} min={-1} max={1} step={0.01} testId="lens-k1" hint="منفی: اعوجاجِ بشکه‌ای (لنزِ واید و اکشن‌کم) را صاف می‌کند؛ مثبت: بالشتکی را"
            onLive={(v) => api.live((p) => setLens(p, clip.id, { k1: v }))} onCommit={() => api.end("اصلاحِ لنز")} />
          <Slider label="اصلاحِ ظریف (لبه‌ها)" value={lens.k2} min={-1} max={1} step={0.01} testId="lens-k2" hint="روی لبه‌های قاب بیشتر اثر دارد"
            onLive={(v) => api.live((p) => setLens(p, clip.id, { k2: v }))} onCommit={() => api.end("اصلاحِ لنز")} />
          <button type="button" className="ws-btn" disabled={lensIsFlat(clip.lens)} data-testid="lens-reset" onClick={() => api.apply("بازنشانیِ لنز", (p) => setLens(p, clip.id, null))}>بازنشانی</button>
          <p className="ws-hint">اثر هم در پیش‌نمایش دیده می‌شود هم در خروجی. برای فیلمِ لنزِ واید، منفیِ کوچک (حدودِ ‎−۰٫۲‎) خط‌های خمیده را صاف می‌کند.</p>
        </div>
      )}
      {open === "matte" && (
        <div data-testid="fx-matte">
          <label className="fx-check">
            <input type="checkbox" checked={!!clip.track_matte} data-testid="matte-on" onChange={(e) => api.apply("ماتِ ترک", (p) => setTrackMatte(p, clip.id, e.target.checked ? {} : null))} />
            <span>این قطعه از پشتِ قطعهٔ ترکِ بالاتر دیده شود</span>
          </label>
          <div className="mk-top">
            <button type="button" className={`ws-chip ${matte.mode === "luma" ? "is-on" : ""}`} data-testid="matte-luma" disabled={!clip.track_matte} onClick={() => api.apply("ماتِ ترک", (p) => setTrackMatte(p, clip.id, { mode: "luma" }))}>روشنیِ مات (سفید = دیده)</button>
            <button type="button" className={`ws-chip ${matte.mode === "alpha" ? "is-on" : ""}`} data-testid="matte-alpha" disabled={!clip.track_matte} onClick={() => api.apply("ماتِ ترک", (p) => setTrackMatte(p, clip.id, { mode: "alpha" }))}>شفافیتِ مات (پررنگ = دیده)</button>
          </div>
          <label className="fx-check">
            <input type="checkbox" checked={matte.invert} disabled={!clip.track_matte} data-testid="matte-invert" onChange={(e) => api.apply("ماتِ ترک", (p) => setTrackMatte(p, clip.id, { invert: e.target.checked }))} />
            <span>برعکس (جایی که مات پررنگ است پنهان شود)</span>
          </label>
          {clip.track_matte && (matteSrc
            ? <p className="ws-hint" data-testid="matte-source">ماتِ این قطعه: «{matteSrc.label}» روی ترکِ بالاتر؛ خودش نمایش داده نمی‌شود.</p>
            : <p className="ws-hint" data-testid="matte-missing">هنوز مات پیدا نشد: روی ترکِ تصویرِ بالاتر باید قطعه‌ای هم‌زمان با این قطعه باشد (متن یا شکل و عکس هم می‌شود، فقط روی ترکِ تصویر).</p>)}
          <p className="ws-hint">مثلاً یک شکل یا عنوانِ سفید روی ترکِ بالا بگذارید و ویدیو را زیرش؛ ویدیو فقط داخلِ آن شکل دیده می‌شود. روشنایی: سفید دیده، سیاه پنهان. اگر مات یک عکسِ شفاف (استیکر) است «شفافیتِ مات» را بزنید.</p>
        </div>
      )}
      {open === "denoise" && (
        <div data-testid="fx-denoise">
          <Slider label="شدتِ نویزگیر" value={clip.denoise?.amount ?? 0} min={0} max={1} step={0.05} testId="dn-amount" hint="۰ = خاموش؛ بالاتر = تمیزتر ولی نرم‌تر"
            onLive={(v) => api.live((p) => setDenoise(p, clip.id, { amount: v }))} onCommit={() => api.end("نویزگیرِ تصویر")} />
          <div className="mk-top">
            <button type="button" className={`ws-chip ${(clip.denoise?.mode ?? "fast") === "fast" ? "is-on" : ""}`} data-testid="dn-fast" disabled={!clip.denoise}
              onClick={() => api.apply("نویزگیرِ سریع", (p) => setDenoise(p, clip.id, { mode: "fast" }))}>سریع (hqdn3d)</button>
            <button type="button" className={`ws-chip ${clip.denoise?.mode === "strong" ? "is-on" : ""}`} data-testid="dn-strong" disabled={!clip.denoise}
              onClick={() => api.apply("نویزگیرِ قوی", (p) => setDenoise(p, clip.id, { mode: "strong" }))}>قوی (nlmeans، کندتر)</button>
            <button type="button" className="ws-btn" disabled={!clip.denoise} data-testid="dn-off" onClick={() => api.apply("خاموش‌کردنِ نویزگیر", (p) => setDenoise(p, clip.id, null))}>خاموش</button>
          </div>
          <p className="ws-hint">برای فیلم‌هایی که شب یا با گوشیِ قدیمی گرفته شده و دانه‌دانه است. پیش‌نمایش فقط کمی نرم می‌شود؛ تمیزی‌اش را در خروجی می‌بینید. «قوی» روی سرورِ پردازش (در خروجیِ نهایی) خیلی بهتر و سریع‌تر است.</p>
        </div>
      )}
      {open === "frames" && (
        <div data-testid="fx-frames">
          <div className="mk-top">
            {([[undefined, "هیچ (تکرارِ فریم)"], ["blend", "ترکیبِ فریم‌ها (Blend)"], ["flow", "فریمِ میانیِ اپتیکال‌فلو"]] as const).map(([k, t]) => (
              <button key={String(k)} type="button" className={`ws-chip ${clip.frames === k ? "is-on" : ""}`} data-testid={`fr-${k ?? "none"}`}
                onClick={() => api.apply("ترکیبِ فریم‌ها", (p) => setFrames(p, clip.id, k ?? null))}>{t}</button>
            ))}
          </div>
          {!slowed && <p className="ws-hint" data-testid="fr-not-slowed">این قطعه کند نشده؛ ترکیبِ فریم‌ها فقط وقتی اثر دارد که سرعتِ قطعه کمتر از ۱ باشد (یا منحنیِ سرعت جایی کند شود).</p>}
          <p className="ws-hint">وقتی قطعه را کند می‌کنید فریم‌ها تکرار می‌شوند و تصویر «پله‌پله» می‌شود. «ترکیبِ فریم‌ها» فریم‌های کنارِ هم را قاطی می‌کند (سریع)؛ «اپتیکال‌فلو» فریم‌های تازه با حرکتِ درست می‌سازد (کندتر و بهتر). اپتیکال‌فلو فقط در خروجیِ نهایی روی سرورِ پردازش ساخته می‌شود و در پیش‌نویسِ سریعِ روی سایت اجرا نمی‌شود (مگر خودتان خروجی را دستی روی سایت بسازید). پیش‌نمایشِ مرورگر هیچ‌کدام را نشان نمی‌دهد.</p>
        </div>
      )}
      {open === "interpret" && (
        <div data-testid="fx-interpret">
          <p className="ws-hint">{native ? `فریم‌بر‌ثانیهٔ واقعیِ این فیلم: ${fa(Math.round(native * 100) / 100)}` : "فریم‌بر‌ثانیهٔ این فیلم معلوم نیست."}{interp.fps ? ` — الان مثلِ ${fa(interp.fps.to)} خوانده می‌شود (سرعتِ ${fa(Math.round((clip.speed || 1) * 100) / 100)} برابر).` : ""}</p>
          <div className="mk-top">
            {INTERPRET_FPS.map((f) => (
              <button key={f} type="button" className={`ws-chip ${interp.fps?.to === f ? "is-on" : ""}`} data-testid={`ip-fps-${f}`} disabled={!native}
                onClick={() => { const r = interpretFps(api.project, clip.id, native, f); if ("error" in r) { api.notice(r.error); return; } api.apply(`تفسیرِ فیلم مثلِ ${f} فریم`, () => r.project); if (r.clamped) api.notice("سرعت از بازهٔ ۰٫۲۵ تا ۴ برابر بیرون می‌زد و محدود شد."); }}>{fa(f)}</button>
            ))}
            <button type="button" className="ws-btn" disabled={!interp.fps} data-testid="ip-fps-reset" onClick={() => api.apply("برگشتِ تفسیرِ فریم", (p) => clearInterpretFps(p, clip.id))}>برگشت</button>
          </div>
          <p className="ws-hint">مثلاً فیلمِ ۶۰ فریمی را «مثلِ ۳۰ فریم» بخوانید تا نیمه‌سرعت (اسلوموشن) شود؛ قطعه‌های بعدی به‌اندازهٔ کش‌آمدن جلو می‌روند. با «برگشت» به سرعتِ قبلی برمی‌گردد.</p>
          <Slider label="نسبتِ پیکسل" value={interp.par ?? 1} min={0.5} max={2} step={0.01} testId="ip-par" hint="۱ = پیکسلِ مربع؛ ۱٫۳۳ = فیلمِ آنامورفیکِ قدیمی (۴:۳ خوانده‌شده ۱۶:۹)"
            onLive={(v) => api.live((p) => setInterpret(p, clip.id, { par: v }))} onCommit={() => api.end("نسبتِ پیکسل")} />
          <label className="fx-check">
            <input type="checkbox" checked={!!interp.deinterlace} data-testid="ip-deint" onChange={(e) => api.apply("حذفِ خط‌های درهم", (p) => setInterpret(p, clip.id, { deinterlace: e.target.checked }))} />
            <span>خط‌های درهم (Interlace) را به فریمِ کامل تبدیل کن (yadif)</span>
          </label>
          <p className="ws-hint">نسبتِ پیکسل در پیش‌نمایش و خروجی هر دو دیده می‌شود؛ حذفِ خط‌های درهم فقط در خروجی اعمال می‌شود. فیلمِ گوشی و دوربین‌های امروزی معمولاً به هیچ‌کدام نیاز ندارد.</p>
        </div>
      )}
      {open === "anchor" && (
        <div data-testid="fx-anchor">
          <div className="fx-anchor-grid" role="group" aria-label="نقطهٔ لنگر">
            {ANCHOR_PRESETS.map((a) => {
              const on = Math.abs(anchor.x - a.x) < 0.01 && Math.abs(anchor.y - a.y) < 0.01;
              return (
                <button key={a.key} type="button" className={`fx-anchor ${on ? "is-on" : ""}`} title={a.title} aria-label={a.title} aria-pressed={on} data-testid={`anchor-${a.key}`}
                  onClick={() => api.apply("نقطهٔ لنگر", (p) => setAnchor(p, clip.id, { x: a.x, y: a.y }))} />
              );
            })}
          </div>
          <Slider label="افقی" value={anchor.x} min={-1} max={1} step={0.01} testId="anchor-x" onLive={(v) => api.live((p) => setAnchor(p, clip.id, { x: v, y: anchor.y }))} onCommit={() => api.end("نقطهٔ لنگر")} />
          <Slider label="عمودی" value={anchor.y} min={-1} max={1} step={0.01} testId="anchor-y" onLive={(v) => api.live((p) => setAnchor(p, clip.id, { x: anchor.x, y: v }))} onCommit={() => api.end("نقطهٔ لنگر")} />
          <button type="button" className="ws-btn" disabled={anchorIsCentre(clip.anchor)} data-testid="anchor-reset" onClick={() => api.apply("لنگر به مرکز", (p) => setAnchor(p, clip.id, null))}>برگشت به مرکز</button>
          <p className="ws-hint">چرخش و بزرگ‌نمایی دورِ این نقطه انجام می‌شود (مثلاً درِ باز شونده از لبه). اثرش را وقتی «چرخش» یا «اندازه» را در بخشِ حرکت عوض می‌کنید می‌بینید.</p>
        </div>
      )}
    </div>
  );
}
