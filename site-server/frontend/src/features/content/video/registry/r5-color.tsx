import { useEffect, useMemo, useRef, useState } from "react";

import { fa } from "../../../../components/ui";
import { frameStats, matchColor, patchToParams, HUE_BANDS, HUE_MODES, HueMode, hueCurve } from "../manual/colorTools";
import { grabFrame } from "../manual/frameGrab";
import { MediaClip, clipEnd, clipLength, srcTimeAt, timecode, updateClip } from "../manual/model";
import type { PanelProps } from "./types";

const clampN = (x: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, x));
const midOf = (c: MediaClip) => srcTimeAt(c, c.at + clipLength(c) / 2);
const explain = (p: { exposure: number; contrast: number; temperature: number; tint: number; saturation: number }) => {
  const sg = (v: number) => (v > 0 ? "+" : v < 0 ? "−" : "");
  return `نوردهی ${sg(p.exposure)}${fa(Math.abs(p.exposure))} · کنتراست ${sg(p.contrast)}${fa(Math.abs(p.contrast))} · دما ${sg(p.temperature)}${fa(Math.abs(p.temperature))} · تینت ${sg(p.tint)}${fa(Math.abs(p.tint))} · اشباع ${fa(p.saturation)}`;
};

/** تطبیقِ رنگِ قطعهٔ انتخاب‌شده با یک نمای دیگر: نوردهی، کنتراست، دما، تینت و اشباع طوری تنظیم می‌شود که به نمای مرجع نزدیک شود (قابل‌ویرایش و برگشت‌پذیر). */
export function ColorMatchPanel({ api }: PanelProps) {
  const target = api.selected && api.selected.clip.type === "media" && api.selected.clip.kind !== "audio" && api.selected.clip.ref !== "shape" ? (api.selected.clip as MediaClip) : null;
  const refs = useMemo(
    () => api.project.tracks.flatMap((t) => t.clips.filter((c): c is MediaClip => c.type === "media" && c.kind !== "audio" && c.ref !== "shape" && c.id !== target?.id && !!api.media[c.ref]).map((c) => ({ c, tr: t.id }))),
    [api.project, api.media, target?.id],
  );
  const [refId, setRefId] = useState("");
  const [strength, setStrength] = useState(100);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  useEffect(() => {
    if (!target || refs.length === 0) return;
    if (refs.some((r) => r.c.id === refId)) return;
    const before = refs.filter((r) => r.c.at <= target.at).sort((a, b) => b.c.at - a.c.at)[0] ?? refs[0];
    setRefId(before.c.id);
  }, [target, refs, refId]);
  if (!target) return <p className="ws-hint" data-testid="cm-empty">اول قطعهٔ ویدیو یا عکسی را که می‌خواهید رنگش اصلاح شود انتخاب کنید.</p>;
  if (refs.length === 0) return <p className="ws-hint" data-testid="cm-none">برای تطبیق، دست‌کم یک نمای دیگر (ویدیو یا عکس) روی تایم‌لاین لازم است.</p>;

  const go = async () => {
    const ref = refs.find((r) => r.c.id === refId)?.c;
    if (!ref) return;
    setBusy(true);
    setMsg(null);
    try {
      const [a, b] = await Promise.all([grabFrame(api.media[target.ref], midOf(target)), grabFrame(api.media[ref.ref], midOf(ref))]);
      const patch = matchColor(frameStats(a), frameStats(b), strength / 100);
      api.apply("تطبیقِ رنگ", (p) => updateClip(p, target.id, { color: patchToParams(target.color, patch) }));
      setMsg(`انجام شد: ${explain(patch)}. (برگشت: Ctrl+Z؛ ریزتنظیم: تبِ «رنگ»)`);
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "تطبیق ممکن نشد.");
    } finally {
      setBusy(false);
    }
  };
  return (
    <div data-testid="color-match-panel">
      <p className="ws-hint">رنگِ «{target.label}» را به نمای مرجع نزدیک می‌کند. بهترین نتیجه: دو نمایی که نورِ محیطشان یکی است.</p>
      <label className="ws-field">
        <span>نمای مرجع (می‌خواهم شبیهِ این شود)</span>
        <select className="u-input" value={refId} onChange={(e) => setRefId(e.target.value)} aria-label="نمای مرجع" data-testid="cm-ref">
          {refs.map(({ c }) => <option key={c.id} value={c.id}>{c.label} — {timecode(c.at).slice(0, 5)}</option>)}
        </select>
      </label>
      <label className="sq-slider sq-slider-sm">
        <span className="sq-slider-head"><span className="sq-slider-label">شدتِ تطبیق</span><span className="sq-slider-val">{fa(strength)}٪</span></span>
        <input type="range" min={0} max={100} step={5} value={strength} onChange={(e) => setStrength(Number(e.target.value))} aria-label="شدتِ تطبیق" data-testid="cm-strength" />
      </label>
      <button type="button" className="ws-btn primary" disabled={busy} onClick={() => void go()} data-testid="cm-go">{busy ? "در حالِ خواندنِ فریم‌ها…" : "تطبیق بده"}</button>
      {msg && <p className="ws-hint" role="status" data-testid="cm-msg">{msg}</p>}
      <p className="ws-hint">آمار از یک فریمِ وسطِ هر نما گرفته می‌شود. برای دقتِ بیشتر، نما را در جایی که نور و رنگش نمایندهٔ کلِ آن است نگه دارید.</p>
    </div>
  );
}

const W = 320, H = 150, PAD = 14;

/** منحنی‌های رنگ در برابرِ (Hue vs Sat / Hue / Lum): شش نقطه (قرمز…ارغوانی) روی چرخهٔ رنگ؛ هر نقطه را بالا/پایین بکشید. همان «HSLِ ثانویه» را می‌نویسد. */
export function HueVsPanel({ api }: PanelProps) {
  const clip = api.selected && api.selected.clip.type === "media" && api.selected.clip.kind !== "audio" ? (api.selected.clip as MediaClip) : null;
  const [mode, setMode] = useState<HueMode>("sat");
  const [drag, setDrag] = useState<number | null>(null);
  const svg = useRef<SVGSVGElement>(null);
  const spec = HUE_MODES.find((m) => m.key === mode)!;
  const values = HUE_BANDS.map((b) => clip?.color?.hsl?.[b.key]?.[spec.field] ?? 0);
  const X = (hue: number) => PAD + (hue / 360) * (W - 2 * PAD);
  const Y = (v: number) => PAD + (1 - (v - spec.min) / (spec.max - spec.min)) * (H - 2 * PAD);
  const vOf = (py: number) => Math.round(clampN(spec.min + (1 - (py - PAD) / (H - 2 * PAD)) * (spec.max - spec.min), spec.min, spec.max));
  const path = useMemo(() => {
    const pts: string[] = [];
    for (let h = 0; h <= 360; h += 6) pts.push(`${h ? "L" : "M"}${X(h).toFixed(1)},${Y(clampN(hueCurve(values, h), spec.min, spec.max)).toFixed(1)}`);
    return pts.join(" ");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [values.join(","), mode]);
  if (!clip) return <p className="ws-hint" data-testid="hv-empty">اول یک ویدیو یا عکس را روی تایم‌لاین انتخاب کنید.</p>;

  const setBand = (i: number, v: number, live: boolean) => {
    const key = HUE_BANDS[i].key;
    const cur = clip.color?.hsl?.[key] ?? { h: 0, s: 0, l: 0 };
    const color = { ...(clip.color ?? {}), hsl: { ...(clip.color?.hsl ?? {}), [key]: { ...cur, [spec.field]: v } } };
    if (live) api.live((p) => updateClip(p, clip.id, { color }));
    else api.apply("منحنیِ رنگ", (p) => updateClip(p, clip.id, { color }));
  };
  const local = (e: React.PointerEvent) => {
    const r = svg.current!.getBoundingClientRect();
    return ((e.clientY - r.top) / r.height) * H;
  };
  const reset = () => {
    const hsl = { ...(clip.color?.hsl ?? {}) } as NonNullable<MediaClip["color"]>["hsl"];
    for (const b of HUE_BANDS) if (hsl && hsl[b.key]) hsl[b.key] = { ...hsl[b.key]!, [spec.field]: 0 };
    api.apply("بازنشانیِ منحنیِ رنگ", (p) => updateClip(p, clip.id, { color: { ...(clip.color ?? {}), hsl } }));
  };
  return (
    <div data-testid="huevs-panel">
      <div className="hv-tabs" role="tablist">
        {HUE_MODES.map((m) => (
          <button key={m.key} type="button" role="tab" aria-selected={mode === m.key} className={`ws-chip ${mode === m.key ? "is-on" : ""}`} onClick={() => setMode(m.key)} data-testid={`hv-tab-${m.key}`}>{m.title}</button>
        ))}
      </div>
      <svg ref={svg} viewBox={`0 0 ${W} ${H}`} className="hv-svg" role="img" aria-label={spec.title} data-testid="hv-svg"
        onPointerMove={(e) => { if (drag !== null) setBand(drag, vOf(local(e)), true); }}
        onPointerUp={() => { if (drag !== null) { api.end("منحنیِ رنگ"); setDrag(null); } }} onPointerCancel={() => setDrag(null)}>
        <defs>
          <linearGradient id="hv-rainbow" x1="0" x2="1" y1="0" y2="0">
            {HUE_BANDS.concat(HUE_BANDS[0]).map((b, i) => <stop key={i} offset={`${(i / 6) * 100}%`} stopColor={b.css} />)}
          </linearGradient>
        </defs>
        <rect x={PAD} y={H - PAD + 2} width={W - 2 * PAD} height={6} fill="url(#hv-rainbow)" rx={3} />
        <line x1={PAD} x2={W - PAD} y1={Y(0)} y2={Y(0)} className="hv-zero" />
        <path d={path} className="hv-curve" fill="none" />
        {HUE_BANDS.map((b, i) => (
          <circle key={b.key} cx={X(b.hue)} cy={Y(values[i])} r={drag === i ? 8 : 6.5} fill={b.css} className="hv-dot" data-testid="hv-dot" data-band={b.key} tabIndex={0} role="slider"
            aria-label={`${b.title}: ${values[i]}`} aria-valuemin={spec.min} aria-valuemax={spec.max} aria-valuenow={values[i]}
            onPointerDown={(e) => { (e.currentTarget as Element).setPointerCapture(e.pointerId); setDrag(i); }}
            onDoubleClick={() => setBand(i, 0, false)}
            onKeyDown={(e) => {
              const step = e.shiftKey ? 10 : 2;
              if (e.key === "ArrowUp") { e.preventDefault(); setBand(i, clampN(values[i] + step, spec.min, spec.max), false); }
              if (e.key === "ArrowDown") { e.preventDefault(); setBand(i, clampN(values[i] - step, spec.min, spec.max), false); }
            }} />
        ))}
      </svg>
      <div className="hv-legend" aria-hidden>{HUE_BANDS.map((b) => <span key={b.key} style={{ color: b.css }}>{b.title}</span>)}</div>
      <p className="ws-hint">هر نقطه یکی از شش رنگ را بالا/پایین می‌برد (دوبار کلیک = صفر؛ با کیبورد: ↑ ↓). بینِ نقطه‌ها منحنی هموار است. این همان «HSL ثانویه» در تبِ رنگ است؛ نمودارش را این‌جا می‌بینید.</p>
      <button type="button" className="ws-btn" onClick={reset} data-testid="hv-reset">بازنشانیِ این منحنی</button>
    </div>
  );
}

export { clipEnd };
