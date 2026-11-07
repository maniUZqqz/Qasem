import { fa } from "../../../../components/ui";
import { Section, Slider, Toggle } from "./controls";
import type { ClipAudio, MediaClip } from "./model";

type Band = NonNullable<ClipAudio["bands"]>[number];
const MAX_BANDS = 5;
const SUGGEST: Band[] = [{ f: 120, g: 3, q: 1 }, { f: 400, g: -3, q: 1 }, { f: 1500, g: 3, q: 1 }, { f: 4000, g: 3, q: 1 }, { f: 9000, g: 3, q: 1 }];
const DEF_COMP = { on: true, thr: -18, ratio: 3, attack: 20, release: 250, makeup: 0 };
const DEF_ECHO = { on: true, delay: 250, decay: 0.4 };
const sign = (v: number) => (v < 0 ? "−" : v > 0 ? "+" : "");

/**
 * «صدای پیشرفته»: EQ پارامتریک (تا ۵ باند)، کمپرسورِ دقیق (آستانه، نسبت، حمله، رهایی، جبرانِ بلندی)، زیر و بمی (نیم‌پرده) و پژواک.
 * همه در خروجی و «پیش‌نمایشِ دقیق» اعمال می‌شوند؛ پخشِ فوریِ مرورگر آن‌ها را نمی‌شنود. (سرور: backend/services/editing/audiofx.py)
 */
export default function AudioAdvanced({
  clip, onLive, onEnd, onApply,
}: {
  clip: MediaClip;
  onLive: (patch: Partial<MediaClip>) => void;
  onEnd: (label: string) => void;
  onApply: (label: string, patch: Partial<MediaClip>) => void;
}) {
  const audio: ClipAudio = clip.audio ?? {};
  const bands = audio.bands ?? [];
  const cd = audio.cdetail;
  const echo = audio.echo;
  const set = (patch: Partial<ClipAudio>): Partial<MediaClip> => {
    const next: ClipAudio = { ...audio, ...patch };
    for (const k of Object.keys(next) as (keyof ClipAudio)[]) if (next[k] === undefined) delete next[k];
    return { audio: next };
  };
  const setBands = (b: Band[]) => set({ bands: b.length ? b : undefined });
  const upd = (i: number, p: Partial<Band>) => bands.map((x, j) => (j === i ? { ...x, ...p } : x));
  const used = bands.length + (cd?.on ? 1 : 0) + (audio.pitch ? 1 : 0) + (echo?.on ? 1 : 0);

  return (
    <Section title="صدای پیشرفته: EQ پارامتریک، کمپرسورِ دقیق، زیر و بمی، پژواک" testId="ap-adv" badge={used ? <span className="ws-dot" /> : undefined}>
      <div className="ws-group-title">EQ پارامتریک <small className="ws-muted">(تا {fa(MAX_BANDS)} باند)</small></div>
      {bands.length === 0 && <p className="ws-hint">هر باند یک فرکانس را بالا یا پایین می‌برد؛ مثلاً ۳۰۰ هرتز با ‑۴ dB صدای «تو دماغی» را کم می‌کند.</p>}
      {bands.map((b, i) => (
        <div className="aa-band" key={i} data-testid="aa-band">
          <Slider label={`باند ${fa(i + 1)}: فرکانس`} value={Math.log10(b.f)} min={Math.log10(20)} max={Math.log10(20000)} step={0.01} def={undefined}
            fmt={() => `${fa(Math.round(b.f))} Hz`} onLive={(v) => onLive(setBands(upd(i, { f: Math.round(10 ** v) })))} onEnd={() => onEnd("فرکانسِ باند")} />
          <Slider label="بهره" value={b.g} min={-18} max={18} step={0.5} def={0} fmt={(v) => `${sign(v)}${fa(Math.abs(Math.round(v * 10) / 10))} dB`}
            onLive={(v) => onLive(setBands(upd(i, { g: v })))} onEnd={() => onEnd("بهرهٔ باند")} />
          <Slider label="پهنا (Q)" value={b.q} min={0.2} max={10} step={0.1} def={1} fmt={(v) => fa(Math.round(v * 10) / 10)}
            onLive={(v) => onLive(setBands(upd(i, { q: v })))} onEnd={() => onEnd("پهنای باند")} />
          <button type="button" className="ws-btn" onClick={() => onApply("حذفِ باند", setBands(bands.filter((_, j) => j !== i)))} aria-label={`حذفِ باند ${fa(i + 1)}`} data-testid="aa-band-delete">× حذفِ این باند</button>
        </div>
      ))}
      <button type="button" className="ws-btn" disabled={bands.length >= MAX_BANDS} onClick={() => onApply("باندِ EQ", setBands([...bands, SUGGEST[bands.length % SUGGEST.length]]))} data-testid="aa-band-add">+ باندِ تازه</button>

      <div className="ws-group-title">کمپرسورِ دقیق</div>
      <Toggle label="روشن" checked={!!cd?.on} onChange={(v) => onApply("کمپرسورِ دقیق", set({ cdetail: v ? { ...DEF_COMP, ...(cd ?? {}), on: true } : undefined }))} />
      {cd?.on && (
        <>
          <Slider label="آستانه" value={cd.thr} min={-40} max={0} step={1} def={-18} fmt={(v) => `${fa(v)} dB`} onLive={(v) => onLive(set({ cdetail: { ...cd, thr: v } }))} onEnd={() => onEnd("آستانهٔ کمپرسور")} />
          <Slider label="نسبت" value={cd.ratio} min={1} max={20} step={0.5} def={3} fmt={(v) => `${fa(v)} : ۱`} onLive={(v) => onLive(set({ cdetail: { ...cd, ratio: v } }))} onEnd={() => onEnd("نسبتِ کمپرسور")} />
          <Slider label="حمله" value={cd.attack} min={1} max={200} step={1} def={20} fmt={(v) => `${fa(v)} ms`} onLive={(v) => onLive(set({ cdetail: { ...cd, attack: v } }))} onEnd={() => onEnd("حملهٔ کمپرسور")} />
          <Slider label="رهایی" value={cd.release} min={10} max={2000} step={10} def={250} fmt={(v) => `${fa(v)} ms`} onLive={(v) => onLive(set({ cdetail: { ...cd, release: v } }))} onEnd={() => onEnd("رهاییِ کمپرسور")} />
          <Slider label="جبرانِ بلندی" value={cd.makeup} min={0} max={24} step={0.5} def={0} fmt={(v) => `+${fa(v)} dB`} onLive={(v) => onLive(set({ cdetail: { ...cd, makeup: v } }))} onEnd={() => onEnd("جبرانِ بلندی")} />
        </>
      )}

      <div className="ws-group-title">زیر و بمی (Pitch)</div>
      <Slider label="نیم‌پرده" value={audio.pitch ?? 0} min={-12} max={12} step={1} def={0}
        fmt={(v) => (Math.abs(v) < 0.05 ? "بدونِ تغییر" : `${sign(v)}${fa(Math.abs(v))} نیم‌پرده`)}
        onLive={(v) => onLive(set({ pitch: Math.abs(v) < 0.05 ? undefined : v }))} onEnd={() => onEnd("زیر و بمی")} />

      <div className="ws-group-title">پژواک (Echo)</div>
      <Toggle label="روشن" checked={!!echo?.on} onChange={(v) => onApply("پژواک", set({ echo: v ? { ...DEF_ECHO, ...(echo ?? {}), on: true } : undefined }))} />
      {echo?.on && (
        <>
          <Slider label="فاصلهٔ تکرار" value={echo.delay} min={20} max={1000} step={10} def={250} fmt={(v) => `${fa(v)} ms`} onLive={(v) => onLive(set({ echo: { ...echo, delay: v } }))} onEnd={() => onEnd("فاصلهٔ پژواک")} />
          <Slider label="شدتِ تکرار" value={echo.decay} min={0.05} max={0.9} step={0.05} def={0.4} fmt={(v) => `${fa(Math.round(v * 100))}٪`} onLive={(v) => onLive(set({ echo: { ...echo, decay: v } }))} onEnd={() => onEnd("شدتِ پژواک")} />
        </>
      )}
      <p className="ws-hint">این‌ها در خروجی و در «پیش‌نمایشِ دقیق» شنیده می‌شوند؛ پخشِ فوریِ مرورگر نشانشان نمی‌دهد. بعد از تنظیم، «پیش‌نمایشِ دقیقِ این بازه» را بزنید و بشنوید.</p>
    </Section>
  );
}
