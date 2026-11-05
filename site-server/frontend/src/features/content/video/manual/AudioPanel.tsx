import { fa } from "../../../../components/ui";
import { Chips, Section, Slider, Toggle } from "./controls";
import { keyNear, removeKey, setKey } from "./keyframes";
import { Kf, MediaClip, clipLength, propAt } from "./model";
import "./audio.css";

const EQ_OPTIONS = [
  { key: "flat", title: "بدون تغییر" },
  { key: "voice", title: "گفتار (واضح)" },
  { key: "bright", title: "روشن" },
  { key: "warm", title: "گرم" },
  { key: "phone", title: "تلفنی" },
  { key: "bass_cut", title: "حذفِ بم" },
  { key: "bass_boost", title: "بم‌دار" },
  { key: "deess", title: "کاهش «س»" },
] as const;

const MIN_DB = -60;
const MAX_DB = 9.5; // ≈ ۳ برابر (سقفِ سرور)

const clamp = (x: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, x));
const linToDb = (lin: number) => (lin <= 0.001 ? MIN_DB : clamp(20 * Math.log10(lin), MIN_DB, MAX_DB));
const dbToLin = (db: number) => (db <= MIN_DB + 0.5 ? 0 : clamp(Math.pow(10, db / 20), 0, 3));
const fmtDb = (db: number) => (db <= MIN_DB + 0.01 ? "−∞" : `${db < 0 ? "−" : db > 0 ? "+" : ""}${fa(Math.abs(Math.round(db * 10) / 10))} dB`);

/** تب «صدا» برای یک قطعه: بلندی (dB + کلیدفریم)، پن، محوشدن، EQ، کمپرسور، تقویتِ گفتار، حذفِ نویز، یکسان‌سازی، جداکردنِ صدا و ضرب‌ها */
export default function AudioPanel({
  clip, trackKind, playhead, onLive, onEnd, onApply, onExtractAudio, onBeats, beatsBusy,
}: {
  clip: MediaClip;
  trackKind: "video" | "audio";
  playhead: number;
  onLive: (patch: Partial<MediaClip>) => void;
  onEnd: (label: string) => void;
  onApply: (label: string, patch: Partial<MediaClip>) => void;
  onExtractAudio?: () => void;
  onBeats?: () => void;
  beatsBusy?: boolean;
}) {
  const audio = clip.audio ?? {};
  const keys = clip.kf?.volume;
  const local = playhead - clip.at;
  const here = keyNear(keys, local);
  const db = linToDb(propAt(clip, "volume", playhead));
  const len = clipLength(clip);

  const setVolume = (v: number) => {
    const lin = dbToLin(v);
    if (keys && keys.length > 0) onLive({ kf: { ...clip.kf, volume: setKey(keys, local, lin, "volume") } });
    else onLive({ volume: lin });
  };
  const toggleKey = () => {
    const lin = dbToLin(db);
    if (here) {
      const rest = removeKey(keys, here.t);
      const kf: Kf = { ...clip.kf };
      if (rest.length === 0) {
        delete kf.volume;
        onApply("حذفِ کلیدفریمِ بلندی", { kf, volume: lin });
      } else onApply("حذفِ کلیدفریمِ بلندی", { kf: { ...kf, volume: rest } });
    } else {
      onApply("کلیدفریمِ بلندی", { kf: { ...clip.kf, volume: setKey(keys, local, lin, "volume") } });
    }
  };
  const setAudio = (patch: Partial<NonNullable<MediaClip["audio"]>>) => ({ audio: { ...audio, ...patch } });

  const pan = audio.pan ?? 0;
  const carries = trackKind === "audio" || (clip.kind === "video" && clip.has_audio);
  if (!carries) {
    return <p className="ws-hint" data-testid="audio-none">این قطعه صدا ندارد.</p>;
  }

  return (
    <div className="ap-root" data-testid="audio-panel">
      {trackKind === "video" && clip.kind === "video" && (
        <Toggle label="پخشِ صدای خودِ این قطعه" checked={clip.audio_on} onChange={(on) => onApply("صدای قطعه", { audio_on: on })} />
      )}
      <Slider
        label="بلندیِ قطعه" value={db} min={MIN_DB} max={MAX_DB} step={0.5} def={0} fmt={fmtDb}
        onLive={setVolume} onEnd={() => onEnd("بلندیِ قطعه")}
        kf={{ has: !!keys && keys.length > 0, here: !!here, onToggle: toggleKey }}
      />
      {keys && keys.length > 0 && (
        <p className="ws-hint">
          بلندی انیمیشن دارد ({fa(keys.length)} کلید). لغزنده مقدارِ کلیدِ سرِ پخش را عوض می‌کند؛ برای کلیدِ تازه سرِ پخش را جابه‌جا کنید.
        </p>
      )}
      <Slider
        label="پن (چپ ↔ راست)" value={pan} min={-1} max={1} step={0.05} def={0}
        fmt={(v) => (Math.abs(v) < 0.03 ? "وسط" : `${v < 0 ? "چپ" : "راست"} ${fa(Math.round(Math.abs(v) * 100))}٪`)}
        onLive={(v) => onLive(setAudio({ pan: v }))} onEnd={() => onEnd("پنِ قطعه")}
      />
      <Slider label="محوِ ابتدا (ثانیه)" value={clip.fade_in} min={0} max={Math.max(0.1, Math.min(10, len))} step={0.05} def={0}
        onLive={(v) => onLive({ fade_in: v })} onEnd={() => onEnd("محوِ ابتدای صدا")} />
      <Slider label="محوِ انتها (ثانیه)" value={clip.fade_out} min={0} max={Math.max(0.1, Math.min(10, len))} step={0.05} def={0}
        onLive={(v) => onLive({ fade_out: v })} onEnd={() => onEnd("محوِ انتهای صدا")} />

      <Section title="EQ و بهبودِ صدا" defaultOpen testId="ap-eq" badge={audio.eq && audio.eq !== "flat" ? <span className="ws-dot" /> : undefined}>
        <div className="ws-group-title">پیش‌تنظیمِ EQ</div>
        <Chips value={(audio.eq ?? "flat") as (typeof EQ_OPTIONS)[number]["key"]} options={[...EQ_OPTIONS]}
          onPick={(k) => onApply("EQ", { audio: { ...audio, eq: k === "flat" ? undefined : k } })} />
        <Slider
          label="کمپرسور (فشرده‌سازیِ دامنه)" value={audio.comp ?? 0} min={0} max={1} step={0.05} def={0}
          fmt={(v) => (v < 0.01 ? "خاموش" : `${fa(Math.round(v * 100))}٪`)}
          onLive={(v) => onLive(setAudio({ comp: v }))} onEnd={() => onEnd("کمپرسور")}
        />
        <Toggle label="تقویتِ صدای گفتار (فیلتر، نویزگیر، EQ و کمپرسور)" checked={!!audio.enhance} onChange={(v) => onApply("تقویتِ گفتار", setAudio({ enhance: v }))} />
        <Toggle label="حذفِ نویزِ پس‌زمینه" checked={!!audio.denoise} onChange={(v) => onApply("حذفِ نویز", setAudio({ denoise: v }))} />
        <Toggle label="یکسان‌سازیِ بلندی (حدودِ −۱۶ LUFS)" checked={!!audio.normalize} onChange={(v) => onApply("یکسان‌سازیِ بلندی", setAudio({ normalize: v }))} />
        <p className="ws-hint">
          حذفِ نویز و یکسان‌سازیِ بلندی در پخشِ فوری شنیده نمی‌شوند؛ در خروجی و «پیش‌نمایشِ دقیق» اعمال می‌شوند. EQ و کمپرسور در پیش‌نمایش نزدیک‌اند نه یکسان.
        </p>
      </Section>

      {onExtractAudio && trackKind === "video" && clip.kind === "video" && clip.audio_on && (
        <div className="ap-extract">
          <button type="button" className="ws-btn w-full justify-center" onClick={onExtractAudio} data-testid="audio-extract">جدا کردنِ صدا از تصویر</button>
          <p className="ws-hint">صدا روی ترکِ صدا می‌رود و به تصویر «پیوند» می‌ماند؛ بعد می‌توانید آن را زودتر یا دیرتر از تصویر شروع کنید (J-cut / L-cut).</p>
        </div>
      )}
      {onBeats && (clip.kind === "audio" || clip.has_audio) && (
        <div className="ap-beats">
          <button type="button" className="ws-btn w-full justify-center" disabled={beatsBusy} onClick={onBeats} data-testid="audio-beats">
            {beatsBusy ? "در حالِ تحلیلِ ضرب‌ها…" : "علامت‌گذاریِ ضرب‌ها روی تایم‌لاین"}
          </button>
          <p className="ws-hint">ضرب‌های موسیقی به‌صورت نشانگر می‌آیند تا برش‌ها را روی ضرب بچینید (مثل CapCut).</p>
        </div>
      )}
    </div>
  );
}
