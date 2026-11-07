import { useState } from "react";

import { fa } from "../../../../components/ui";
import { MediaClip } from "../manual/model";
import { ANCHOR_PRESETS, DEFAULT_LUMA, DEFAULT_MATTE, anchorIsCentre, lensIsFlat, matteSourceFor, setAnchor, setLens, setLuma, setTrackMatte } from "../manual/r5fx";
import type { PanelProps } from "./types";

type Section = "luma" | "lens" | "anchor" | "matte";

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
  const tab = (k: Section, t: string) => (
    <button key={k} type="button" role="tab" aria-selected={open === k} className={`ws-chip ${open === k ? "is-on" : ""}`} onClick={() => setOpen(k)} data-testid={`fx-tab-${k}`}>{t}</button>
  );
  return (
    <div data-testid="clipfx-panel">
      <div className="hv-tabs" role="tablist">{tab("luma", "کلیدِ روشنایی")}{tab("lens", "اصلاحِ لنز")}{tab("anchor", "نقطهٔ لنگر")}{tab("matte", "ماتِ ترک")}</div>
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
