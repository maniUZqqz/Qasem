import { useCallback, useEffect, useRef, useState } from "react";

import { fa } from "../../../../components/ui";
import type { Catalogue } from "../api";
import { Chips, ColorField, Num, Section, Slider, Toggle } from "./controls";
import type { TextClip, TextWord } from "./model";
import { FONT_CSS, drawText, onTextFontsReady, resolveText, styleOf, templatePatch } from "./textRender";
import "./text.css";

type Titles = Catalogue["titles"];

type Props = {
  clip: TextClip;
  cat: Titles;
  playhead: number;
  onLive: (patch: Partial<TextClip>) => void;
  onEnd: (label: string) => void;
  onApply: (label: string, patch: Partial<TextClip>) => void;
  /** چند قطعهٔ زیرنویس (caption) در پروژه هست — برای «اعمال روی همه» */
  captionCount?: number;
  onApplyToCaptions?: (patch: Partial<TextClip>) => void;
};

const POS_Y = { top: 0.12, middle: 0.5, bottom: 0.86 } as const;
const POS_TITLE = { top: "بالا", middle: "وسط", bottom: "پایین" } as const;

/** یک نمونهٔ کوچک از هر قالب، با همان drawText ِ مانیتور */
function TemplateThumb({ template, title, active, onPick }: { template: string; title: string; active: boolean; onPick: () => void }) {
  const ref = useRef<HTMLCanvasElement>(null);
  const paint = useCallback(() => {
    const cv = ref.current;
    const ctx = cv?.getContext("2d");
    if (!cv || !ctx) return;
    const W = cv.width;
    const H = cv.height;
    const g = ctx.createLinearGradient(0, 0, W, H);
    g.addColorStop(0, "#2b3a67");
    g.addColorStop(1, "#6b4a8a");
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, W, H);
    const two = template !== "plain" && template !== "sticker" && template !== "bubble";
    const base: TextClip = { id: "thumb", type: "text", text: "عنوان نمونه", at: 0, duration: 4, position: "bottom", size: 6, color: "#ffffff", box: true, opacity: 1, label: "" };
    const clip: TextClip = { ...base, text2: two ? "زیرعنوان" : "", ...templatePatch(template, base), anim_in: "none", anim_out: "none", y: 0.5 };
    drawText(ctx, clip, 2, W, H);
  }, [template]);
  useEffect(() => {
    paint();
    return onTextFontsReady(paint);
  }, [paint]);
  return (
    <button type="button" className={`tx-tpl ${active ? "is-on" : ""}`} aria-pressed={active} onClick={onPick} data-template={template} title={title}>
      <canvas ref={ref} width={150} height={96} aria-hidden />
      <span>{title}</span>
    </button>
  );
}

/** عددِ زمان که هنگامِ تایپ زنده است و با خروج از فیلد یک گامِ تاریخچه می‌شود */
function LiveNum({ value, onLive, onEnd, label, step = 0.05 }: { value: number; onLive: (v: number) => void; onEnd: () => void; label: string; step?: number }) {
  return (
    <input
      className="u-input tx-num" type="number" step={step} min={0} value={Math.round(value * 1000) / 1000} aria-label={label} dir="ltr"
      onChange={(e) => onLive(Math.max(0, Number(e.target.value) || 0))} onBlur={onEnd}
    />
  );
}

export default function TextPanel({ clip, cat, playhead, onLive, onEnd, onApply, captionCount = 0, onApplyToCaptions }: Props) {
  const r = resolveText(clip);
  const font = FONT_CSS[r.font];
  const timer = useRef<number | undefined>(undefined);
  useEffect(() => () => window.clearTimeout(timer.current), []);
  /** رنگ‌گیرها پیوسته می‌فرستند؛ ۳۵۰ میلی‌ثانیه پس از آخرین تغییر یک گامِ تاریخچه می‌شود */
  const liveColor = (patch: Partial<TextClip>, label: string) => {
    onLive(patch);
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => onEnd(label), 350);
  };
  const live = (patch: Partial<TextClip>) => onLive(patch);
  const sl = (label: string, key: keyof TextClip, value: number, min: number, max: number, def: number, step = 0.01, unit = "", digits = 2) => (
    <Slider label={label} value={value} min={min} max={max} step={step} def={def} unit={unit} digits={digits}
      onLive={(v) => live({ [key]: v } as Partial<TextClip>)} onEnd={() => onEnd(label)} />
  );
  const words: TextWord[] = clip.words ?? [];
  const setWords = (next: TextWord[]) => live({ words: next });
  const tpl = cat.templates;
  const showText2 = !!(clip.text2 && clip.text2.length) || (clip.template && clip.template !== "plain");

  const makeWords = () => {
    const toks = clip.text.trim().split(/\s+/).filter(Boolean);
    if (!toks.length) return;
    const slot = (clip.duration * 0.92) / toks.length;
    onApply("زمان‌بندیِ کلمه‌ها", { words: toks.map((w, i) => ({ w, s: Math.round(i * slot * 1000) / 1000, e: Math.round((i + 1) * slot * 1000) / 1000 })) });
  };

  const nowLocal = Math.max(0, Math.min(clip.duration, playhead - clip.at));

  return (
    <div className="tx-panel" dir="rtl" data-testid="text-panel">
      <div className="ws-card-title">عنوان / زیرنویس</div>
      <label className="ws-field">
        <span>متن</span>
        <textarea
          className="u-input" rows={3} value={clip.text} aria-label="متن" data-testid="text-input" dir="auto"
          onChange={(e) => live({ text: e.target.value, label: e.target.value.replace(/\s+/g, " ").slice(0, 20) })} onBlur={() => onEnd("متن")}
        />
      </label>
      {showText2 && (
        <label className="ws-field">
          <span>زیرعنوان (خطِ دوم)</span>
          <input className="u-input" value={clip.text2 ?? ""} aria-label="زیرعنوان" dir="auto" onChange={(e) => live({ text2: e.target.value })} onBlur={() => onEnd("زیرعنوان")} />
        </label>
      )}

      <Section title="قالب‌ها (عنوانِ آماده)" defaultOpen testId="tx-templates">
        <div className="tx-tpl-grid">
          {tpl.map((t) => (
            <TemplateThumb key={t.key} template={t.key} title={t.title} active={(clip.template ?? "plain") === t.key}
              onPick={() => onApply(`قالبِ ${t.title}`, templatePatch(t.key, clip))} />
          ))}
        </div>
        <p className="ws-hint">{String(tpl.find((t) => t.key === (clip.template ?? "plain"))?.hint ?? "")}</p>
        <button type="button" className="ws-link" onClick={() => onApply("بازنشانی به قالب", templatePatch(clip.template ?? "plain", clip))}>بازنشانی ظاهر به پیش‌فرضِ قالب</button>
      </Section>

      <Section title="ظاهر" defaultOpen testId="tx-look">
        <div className="tx-fonts" role="radiogroup" aria-label="فونت">
          {cat.fonts.map((f) => (
            <button key={f.key} type="button" role="radio" aria-checked={r.font === f.key} className={`ws-chip ${r.font === f.key ? "is-on" : ""}`}
              style={{ fontFamily: String(f.css ?? ""), fontWeight: Number(f.weight ?? 400) }} onClick={() => onApply("فونت", { font: f.key })} data-font={f.key}>
              {f.title} <span className="tx-font-sample">Aa آب</span>
            </button>
          ))}
        </div>
        {sl("اندازه (٪ ارتفاعِ قاب)", "size", r.size, 1, 30, 6, 0.5, "", 1)}
        <div className="flex flex-wrap items-center gap-3">
          {font.bold && <Toggle label="درشت" checked={r.bold} onChange={(v) => onApply("درشت", { bold: v })} />}
          <Toggle label="مورب" checked={r.italic} onChange={(v) => onApply("مورب", { italic: v })} />
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <ColorField label="رنگ" value={r.color} onChange={(v) => liveColor({ color: v }, "رنگِ متن")} />
          <ColorField label="رنگِ تاکیدی (نوار/کادر)" value={r.accent} onChange={(v) => liveColor({ accent: v }, "رنگِ تاکیدی")} />
        </div>
        {sl("شفافیت", "opacity", r.opacity, 0.05, 1, 1)}
        <div className="tx-sub">لبه (Stroke)</div>
        <div className="flex items-center gap-3">
          <ColorField label="رنگِ لبه" value={r.stroke_color} onChange={(v) => liveColor({ stroke_color: v }, "رنگِ لبه")} />
          <div className="flex-1">{sl("ضخامت", "stroke", r.stroke, 0, 100, 0, 1, "", 0)}</div>
        </div>
        <div className="tx-sub">سایه</div>
        <div className="flex items-center gap-3">
          <ColorField label="رنگِ سایه" value={r.shadow_color} onChange={(v) => liveColor({ shadow_color: v }, "رنگِ سایه")} />
          <div className="flex-1">{sl("شدت", "shadow", r.shadow, 0, 100, 0, 1, "", 0)}</div>
        </div>
        <div className="tx-sub">زمینه</div>
        <Toggle label="زمینهٔ پشتِ متن" checked={r.box} onChange={(v) => onApply("زمینهٔ متن", { box: v })} />
        {r.box && (
          <>
            <div className="flex items-center gap-3">
              <ColorField label="رنگِ زمینه" value={r.box_color} onChange={(v) => liveColor({ box_color: v }, "رنگِ زمینه")} />
              <div className="flex-1">{sl("شفافیتِ زمینه", "box_opacity", r.box_opacity, 0, 1, 0.45)}</div>
            </div>
            {sl("فاصلهٔ زمینه از متن", "box_pad", r.box_pad, 0, 100, 20, 1, "", 0)}
          </>
        )}
      </Section>

      <Section title="چیدمان" testId="tx-layout">
        <div className="tx-sub">تراز</div>
        <Chips value={r.align} options={cat.aligns.map((a) => ({ key: a.key as TextClip["align"] & string, title: a.title }))} onPick={(k) => onApply("تراز", { align: k })} />
        <div className="tx-sub">جا</div>
        <div className="flex flex-wrap gap-1">
          {(Object.keys(POS_Y) as (keyof typeof POS_Y)[]).map((p) => (
            <button key={p} type="button" className={`ws-chip ${clip.position === p && Math.abs(r.y - POS_Y[p]) < 0.005 ? "is-on" : ""}`}
              onClick={() => onApply("جای متن", { position: p, y: POS_Y[p] })} data-position={p}>{POS_TITLE[p]}</button>
          ))}
        </div>
        {sl("جای افقی (مرکز)", "x", r.x, 0, 1, 0.5)}
        <Slider label="جای عمودی (مرکز)" value={r.y} min={0} max={1} step={0.01} def={0.86}
          onLive={(v) => live({ y: v, position: v < 0.3 ? "top" : v < 0.65 ? "middle" : "bottom" })} onEnd={() => onEnd("جای عمودی")} />
        {sl("چرخش (درجه)", "rotation", r.rotation, -180, 180, 0, 1, "°", 0)}
        {sl("بزرگ‌نمایی", "scale", r.scale, 0.1, 4, 1)}
      </Section>

      <Section title="انیمیشن" testId="tx-anim">
        <label className="ws-field"><span>ورود</span>
          <select className="u-input" value={r.anim_in} aria-label="انیمیشنِ ورود" onChange={(e) => onApply("انیمیشنِ ورود", { anim_in: e.target.value as TextClip["anim_in"] })}>
            {cat.animations_in.map((a) => <option key={a.key} value={a.key}>{a.title}</option>)}
          </select>
        </label>
        <label className="ws-field"><span>خروج</span>
          <select className="u-input" value={r.anim_out} aria-label="انیمیشنِ خروج" onChange={(e) => onApply("انیمیشنِ خروج", { anim_out: e.target.value as TextClip["anim_out"] })}>
            {cat.animations_out.map((a) => <option key={a.key} value={a.key}>{a.title}</option>)}
          </select>
        </label>
        {sl("مدتِ انیمیشن (ثانیه)", "anim_dur", r.anim_dur, 0.1, 2, 0.4, 0.05, "", 2)}
      </Section>

      <Section title="هایلایتِ کلمه‌به‌کلمه (کارائوکه)" badge={words.length ? <span className="ws-dot" /> : undefined} testId="tx-karaoke">
        {words.length === 0 ? (
          <>
            <p className="ws-hint">با زمان‌بندیِ هر کلمه، کلمه‌ای که الان گفته می‌شود رنگ/اندازه می‌گیرد (مثل CapCut). زیرنویسِ خودکار این را خودش می‌سازد؛ برای متنِ دستی می‌توانید کلمه‌ها را مساوی پخش کنید و بعد دقیق‌تر کنید.</p>
            <button type="button" className="ws-btn" onClick={makeWords} disabled={!clip.text.trim()} data-testid="tx-make-words">ساختنِ زمان‌بندی از متن</button>
          </>
        ) : (
          <>
            <div className="tx-sub">شکلِ هایلایت</div>
            <Chips value={r.hl_mode as "color" | "scale" | "box"} options={cat.hl_modes.map((m) => ({ key: m.key as "color" | "scale" | "box", title: m.title }))} onPick={(k) => onApply("شکلِ هایلایت", { hl_mode: k })} />
            <ColorField label="رنگِ هایلایت" value={r.hl_color} onChange={(v) => liveColor({ hl_color: v }, "رنگِ هایلایت")} />
            <div className="tx-words" data-testid="tx-words">
              <div className="tx-word tx-word-head"><span>کلمه</span><span>شروع</span><span>پایان</span><span /></div>
              {words.slice(0, 80).map((w, i) => (
                <div key={i} className={`tx-word ${nowLocal >= w.s && nowLocal < w.e ? "is-now" : ""}`}>
                  <input className="u-input" value={w.w} aria-label={`کلمهٔ ${fa(i + 1)}`} dir="auto"
                    onChange={(e) => setWords(words.map((x, j) => (j === i ? { ...x, w: e.target.value } : x)))} onBlur={() => onEnd("ویرایشِ کلمه")} />
                  <LiveNum value={w.s} label={`شروعِ کلمهٔ ${fa(i + 1)}`} onLive={(v) => setWords(words.map((x, j) => (j === i ? { ...x, s: Math.min(v, x.e) } : x)))} onEnd={() => onEnd("زمانِ کلمه")} />
                  <LiveNum value={w.e} label={`پایانِ کلمهٔ ${fa(i + 1)}`} onLive={(v) => setWords(words.map((x, j) => (j === i ? { ...x, e: Math.max(v, x.s) } : x)))} onEnd={() => onEnd("زمانِ کلمه")} />
                  <button type="button" className="ws-btn" aria-label="حذفِ کلمه" title="حذفِ کلمه" onClick={() => onApply("حذفِ کلمه", { words: words.filter((_, j) => j !== i) })}>×</button>
                </div>
              ))}
            </div>
            <div className="flex flex-wrap gap-2 mt-2">
              <button type="button" className="ws-btn" onClick={makeWords}>پخشِ مساویِ کلمه‌ها</button>
              <button type="button" className="ws-btn" onClick={() => onApply("حذفِ زمان‌بندیِ کلمه‌ها", { words: [] })}>حذفِ هایلایت</button>
            </div>
          </>
        )}
      </Section>

      <Section title="زمان" testId="tx-time">
        <div className="grid grid-cols-2 gap-2">
          <Num label="شروع (ثانیه)" value={clip.at} step={0.1} onChange={(v) => onApply("زمانِ متن", { at: Math.max(0, v) })} />
          <Num label="مدت (ثانیه)" value={clip.duration} step={0.1} min={0.1} onChange={(v) => onApply("مدتِ متن", { duration: Math.max(0.1, v) })} />
        </div>
      </Section>

      {clip.caption && captionCount > 0 && onApplyToCaptions && (
        <div className="tx-all">
          <button type="button" className="ws-btn primary w-full justify-center" data-testid="tx-apply-all" onClick={() => onApplyToCaptions(styleOf(clip))}>
            اعمالِ این سبک روی همهٔ {fa(captionCount)} زیرنویس
          </button>
        </div>
      )}
    </div>
  );
}
