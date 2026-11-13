import { ReactNode, useEffect, useMemo, useRef, useState } from "react";

import { Spinner } from "../../../../components/ui";
import type { Bin as BinData, MediaItem } from "../api";
import MusicPicker, { ChooseOutcome, MusicChoice } from "./MusicPicker";
import { AnyClip, Project, Track, projectLength, toApi } from "./model";
import {
  LOUDNESS_TARGET, LOUDNESS_TP, MUSIC_DB, MUSIC_START_DB, SPEECH_DB, cleanState, dbText, duckMode, faNum, hasClips, isMusicTrack, isSpeechTrack,
  meanGain, musicTracks, setClean, setDuckMode, setGains, speechTracks, DUCK_SOFT_DB, DUCK_STRONG_DB,
} from "./soundOps";
import { DirectorResult, DirectorStep, directorApply, soundError } from "./soundApi";
import VoiceOverDialog from "./VoiceOverDialog";
import "./sound.css";
import { usePlayheadStore } from "./playhead";

type Edit = {
  live: (fn: (p: Project) => Project) => void;
  end: (label: string) => void;
  apply: (label: string, fn: (p: Project) => Project) => void;
};

/** آنچه VideoWorkspace به بازرس می‌دهد تا «صدا — ساده» بتواند روی کلِ پروژه کار کند */
export type SoundWiring = {
  /** ریشهٔ پروژه (نه نمای توالیِ بازشده): ابزارهای سرور روی همین اعمال می‌شوند */
  root: Project;
  /** ویرایش در سطحِ ریشه با یک گامِ برگشت (مستر، کم‌شدنِ خودکار، جایگزینیِ پروژه با نتیجهٔ سرور) */
  applyRoot: (label: string, fn: (p: Project) => Project) => void;
  /** یک توالیِ تودرتو باز است ⇒ کارهای یک‌کلیکیِ سرور غیرفعال‌اند */
  nested: boolean;
  bin: BinData | null;
  /** سطلِ رسانه را دوباره بخوان (صدای تازه ساخته شد) */
  onBinChanged: () => void;
  /** پیامِ کوتاهِ بالای فضای کار (وقتی کارِ سرور تمام شد و کارت دیگر روی صفحه نبود) */
  onNotice: (m: string) => void;
};

export type SoundQuickProps = {
  storeId: string;
  project: Project;
  selected: { track: Track; clip: AnyClip } | null;
  edit: Edit;
  media: Record<string, MediaItem>;
  sound: SoundWiring;
  /** «علامت‌گذاریِ ضرب‌ها» — همان تابعِ تبِ صدا */
  onBeats?: () => void;
  beatsBusy?: boolean;
};

type Busy = "music" | "silence" | "fillers" | "loud" | "voice" | "mix" | null;
type ResultChip = { ok: boolean; lines: { ok: boolean; text: string }[]; notes: string[] };

const HINT_MUSIC = "ترکِ موسیقی ندارید — دکمهٔ «موسیقیِ پس‌زمینه» را بزنید";
const HINT_SPEECH = "ترکِ گفتار ندارید — «گویندگی از متن» را بزنید یا در تبِ میکسر نقشِ یک ترک را «گفتار» کنید";

/** لغزندهٔ بزرگِ لمس‌پذیر با مقدارِ زنده (دسی‌بل). `onLive` هنگامِ کشیدن، `onEnd` هنگامِ رها شدن (گامِ برگشت) */
function BigSlider({
  label, value, min, max, testId, onLive, onEnd, hint,
}: { label: string; value: number; min: number; max: number; testId: string; onLive: (v: number) => void; onEnd: () => void; hint?: ReactNode }) {
  const v = Math.max(min, Math.min(max, value));
  return (
    <div className="sq-slider">
      <div className="sq-slider-head">
        <span className="sq-slider-label">{label}</span>
        <span className="sq-slider-tools">
          {Math.abs(v) > 0.01 && (
            <button type="button" className="sq-reset" title="برگشت به حالتِ اول (۰ دسی‌بل)" aria-label={`بازنشانیِ ${label}`} onClick={() => { onLive(0); onEnd(); }}>↺</button>
          )}
          <span className="sq-slider-val" dir="ltr">{dbText(v)}</span>
        </span>
      </div>
      <input
        type="range" min={min} max={max} step={0.5} value={v} aria-label={label} aria-valuetext={dbText(v)} data-testid={testId}
        onChange={(e) => onLive(Number(e.target.value))} onPointerUp={onEnd} onKeyUp={onEnd} onBlur={onEnd}
        onDoubleClick={() => { onLive(0); onEnd(); }}
      />
      {hint && <p className="ws-hint sq-slider-hint">{hint}</p>}
    </div>
  );
}

/**
 * «صدا — ساده»: چهار کنترلِ بزرگ برای کلِ پروژه (گفتار، موسیقی، کم‌شدنِ موسیقی زیرِ گفتار، صدای تمیز) و ردیفِ کارهای یک‌کلیکی
 * (موسیقیِ پس‌زمینه، حذفِ سکوت‌ها، بلندیِ استاندارد، گویندگی از متن، تنظیمِ خودکارِ میکس، ضرب‌ها). همهٔ کنترل‌های قبلیِ تبِ «صدا» و «میکسر»
 * همان‌جا زیرِ «پیشرفته» مانده‌اند. کارهای سمتِ سرور از راهِ editor/director/apply/ می‌روند و یک گامِ برگشت می‌شوند.
 */
export default function SoundQuick({ storeId, project, selected, edit, media, sound, onBeats, beatsBusy }: SoundQuickProps) {
  const phStore = usePlayheadStore();
  const { root, applyRoot, nested, bin, onBinChanged, onNotice } = sound;
  const speech = useMemo(() => speechTracks(project), [project]);
  const music = useMemo(() => musicTracks(project), [project]);
  const speechDb = meanGain(speech);
  const musicDb = meanGain(music);
  const duck = duckMode(root);
  const clean = cleanState(project);
  const loudOn = !!root.master?.loudness?.on;

  const [dialog, setDialog] = useState<"music" | "voice" | null>(null);
  const [busy, setBusy] = useState<Busy>(null);
  const busyRef = useRef<Busy>(null);
  const [result, setResult] = useState<ResultChip | null>(null);
  const rootRef = useRef(root);
  rootRef.current = root;
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  // ───────────── اجرای ابزارهای سرور (یک گامِ برگشت)
  const run = async (label: string, steps: DirectorStep[], key: Exclude<Busy, null>): Promise<ChooseOutcome> => {
    if (busyRef.current) return { ok: false, message: "کارِ دیگری در حالِ انجام است؛ کمی صبر کنید." };
    busyRef.current = key;
    setBusy(key);
    setResult(null);
    const sent = rootRef.current;
    const sentKey = JSON.stringify(toApi(sent));
    try {
      const res = await directorApply(storeId, sent, steps);
      const lines = res.results.map((r: DirectorResult) => ({ ok: r.ok, text: r.message || (r.ok ? "انجام شد." : "انجام نشد.") }));
      if (!lines.length) lines.push({ ok: false, text: "سرور نتیجه‌ای برنگرداند؛ چیزی تغییر نکرد." });
      const anyOk = res.results.some((r) => r.ok);
      if (anyOk && !res.project) {
        const message = "پاسخِ سرور پروژهٔ معتبری نداشت؛ چیزی تغییر نکرد.";
        if (alive.current) setResult({ ok: false, lines: [{ ok: false, text: message }], notes: [] });
        return { ok: false, message };
      }
      if (anyOk && res.project) {
        // اگر در این فاصله پروژه را ویرایش کرده‌اید، نتیجهٔ سرور را روی آن نمی‌ریزیم تا ویرایش‌های شما گم نشود
        if (rootRef.current !== sent && JSON.stringify(toApi(rootRef.current)) !== sentKey) {
          const message = "پروژه هم‌زمان با انجامِ کار تغییر کرد؛ برای این‌که ویرایش‌های شما گم نشود نتیجه اعمال نشد. دوباره بزنید.";
          if (alive.current) setResult({ ok: false, lines: [{ ok: false, text: message }], notes: [] });
          return { ok: false, message };
        }
        const next = res.project;
        applyRoot(label, () => next);
      }
      if (alive.current) setResult({ ok: res.results.length > 0 && res.results.every((r) => r.ok), lines, notes: res.notes });
      else onNotice(lines.map((l) => l.text).join(" · "));
      const failed = lines.filter((l) => !l.ok).map((l) => l.text);
      return { ok: anyOk, message: failed.join(" — ") || (anyOk ? "" : "انجام نشد.") };
    } catch (err) {
      const message = soundError(err);
      if (alive.current) setResult({ ok: false, lines: [{ ok: false, text: message }], notes: [] });
      return { ok: false, message };
    } finally {
      busyRef.current = null;
      if (alive.current) setBusy(null);
    }
  };

  const chooseMusic = async (c: MusicChoice): Promise<ChooseOutcome> => {
    const ref = c.ref ? { ref: c.ref } : { query: c.query };
    const r = await run("موسیقیِ پس‌زمینه", [{ tool: "add_music", params: { ...ref, volume_db: MUSIC_START_DB, duck: true } }], "music");
    if (r.ok && alive.current) setDialog(null);
    return r;
  };
  const addVoice = async (ref: string, title: string): Promise<ChooseOutcome> => {
    const r = await run(`گویندگی «${title}»`, [{ tool: "add_voiceover", params: { ref, at: Math.round(phStore.get() * 100) / 100 } }], "voice");
    if (r.ok && alive.current) setDialog(null);
    return r;
  };

  const sel = selected && selected.clip.type === "media" && selected.clip.kind !== "image" && (selected.clip.kind === "audio" || selected.clip.has_audio) ? selected.clip : null;
  const canBeats = !!sel && !!onBeats;
  const locked = nested || busy !== null;

  const duckChip = (mode: "off" | "soft" | "strong", title: string, tip: string) => (
    <button
      key={mode} type="button" className={`ws-chip sq-chip ${duck === mode ? "is-on" : ""}`} aria-pressed={duck === mode} title={tip}
      onClick={() => applyRoot("کم‌شدنِ خودکارِ موسیقی", (r) => setDuckMode(r, mode))} data-testid={`sq-duck-${mode}`}
    >
      {title}
    </button>
  );

  const act = (testId: string, emoji: string, label: string, tip: string, onClick: () => void, opts: { disabled?: boolean; on?: boolean; sub?: string; running?: boolean } = {}) => (
    <button
      type="button" className={`ws-btn sq-act ${opts.on ? "is-on" : ""}`} title={tip} disabled={opts.disabled} onClick={onClick} data-testid={testId}
      aria-pressed={opts.on === undefined ? undefined : opts.on}
    >
      <span className="sq-emo" aria-hidden>{opts.running ? <Spinner size={14} /> : emoji}</span>
      <span className="sq-act-txt">{label}{opts.sub && <small>{opts.sub}</small>}</span>
    </button>
  );

  return (
    <>
      <div className="ws-card sq-card" data-testid="sound-quick" dir="rtl">
        <div className="ws-card-title">🎚 صدا — ساده</div>
        {nested && <p className="ws-hint" data-testid="sq-nested">یک توالیِ تودرتو باز است؛ بلندی‌ها فقط برای همین توالی‌اند و کارهای یک‌کلیکیِ پایین تا برگشت به پروژهٔ اصلی خاموش‌اند.</p>}

        {speech.length > 0 ? (
          <BigSlider
            label="بلندیِ صدای گفتار" value={speechDb} min={SPEECH_DB.min} max={SPEECH_DB.max} testId="sq-speech"
            onLive={(v) => edit.live((p) => setGains(p, isSpeechTrack, v))} onEnd={() => edit.end("بلندیِ گفتار")}
            hint={hasClips(speech) ? undefined : "هنوز گفتاری روی این ترک نیست."}
          />
        ) : (
          <p className="ws-hint sq-need" data-testid="sq-speech-hint">{HINT_SPEECH}</p>
        )}

        {music.length > 0 ? (
          <BigSlider
            label="بلندیِ موسیقی" value={musicDb} min={MUSIC_DB.min} max={MUSIC_DB.max} testId="sq-music"
            onLive={(v) => edit.live((p) => setGains(p, isMusicTrack, v))} onEnd={() => edit.end("بلندیِ موسیقی")}
            hint={hasClips(music) ? undefined : HINT_MUSIC}
          />
        ) : (
          <p className="ws-hint sq-need" data-testid="sq-music-hint">{HINT_MUSIC}</p>
        )}

        <div className="sq-row" data-testid="sq-duck">
          <div className="sq-row-label">موسیقی زیرِ گفتار کم شود</div>
          <div className="sq-chips" role="group" aria-label="کم‌شدنِ موسیقی زیرِ گفتار">
            {duckChip("off", "خاموش", "موسیقی زیرِ صدای گوینده کم نمی‌شود")}
            {duckChip("soft", "ملایم", `هنگامِ حرف‌زدن موسیقی حدودِ ${faNum(DUCK_SOFT_DB)} دسی‌بل کم می‌شود`)}
            {duckChip("strong", "قوی", `هنگامِ حرف‌زدن موسیقی حدودِ ${faNum(DUCK_STRONG_DB)} دسی‌بل کم می‌شود`)}
          </div>
          {duck === "custom" && <p className="ws-hint">مقدارِ دلخواه ({faNum(root.ducking?.amount_db ?? 0)} دسی‌بل) از تبِ میکسر تنظیم شده؛ با یکی از دکمه‌های بالا جایگزین می‌شود.</p>}
          {duck !== "off" && music.length === 0 && <p className="ws-hint">{HINT_MUSIC}</p>}
          {duck !== "off" && music.length > 0 && speech.length === 0 && <p className="ws-hint">{HINT_SPEECH}</p>}
        </div>

        <button
          type="button" role="switch" aria-checked={clean === "partial" ? "mixed" : clean === "on"} disabled={clean === "none"}
          className={`sq-switch ${clean === "on" ? "is-on" : clean === "partial" ? "is-part" : ""}`}
          title="نویزِ پس‌زمینه را کم و صدای گوینده را واضح‌تر می‌کند (روی همهٔ گفتارها)"
          onClick={() => edit.apply("صدای تمیز", (p) => setClean(p, clean !== "on"))} data-testid="sq-clean"
        >
          <span className="sq-switch-txt">
            <b>صدای تمیز</b>
            <small>{clean === "none" ? "گفتاری روی تایم‌لاین نیست" : clean === "partial" ? "فقط روی بعضی از گفتارها روشن است؛ بزنید تا روی همه روشن شود" : "نویز کم می‌شود و صدای گوینده واضح‌تر"}</small>
          </span>
          <span className="sq-knob" aria-hidden />
        </button>
        <p className="ws-hint">تأثیرِ «صدای تمیز» در پخشِ فوری شنیده نمی‌شود؛ در خروجی و «پیش‌نمایشِ دقیق» اعمال می‌شود.</p>
      </div>

      <div className="ws-card sq-card" data-testid="sq-actions">
        <div className="ws-card-title">کارهای یک‌کلیکی</div>
        <div className="sq-actions">
          {act("sq-add-music", "🎵", "موسیقیِ پس‌زمینه", "موسیقی انتخاب کنید یا با هوش مصنوعی بسازید؛ خودکار زیرِ ویدیو می‌نشیند", () => setDialog("music"), { disabled: locked, running: busy === "music" })}
          {act("sq-remove-silence", "✂", "حذفِ سکوت‌ها", "مکث‌های بی‌صدا را می‌برد و گفتار را فشرده می‌کند. اگر قطعه‌ای انتخاب شده باشد فقط همان، وگرنه همهٔ گفتارها",
            () => void run("حذفِ سکوت‌ها", [{ tool: "remove_silence", params: { clip: sel ? sel.id : "all" } }], "silence"),
            { disabled: locked, running: busy === "silence", sub: sel ? "فقط قطعهٔ انتخاب‌شده" : "همهٔ گفتارها" })}
          {act("sq-remove-fillers", "🤫", "حذفِ «اِم و اوم»", "صداهای مکث‌دار (اِم، اوم) را با کمک تشخیصِ گفتار می‌برد؛ به سرورِ پردازش نیاز دارد. اگر قطعه‌ای انتخاب شده باشد فقط همان",
            () => void run("حذفِ اِم و اوم", [{ tool: "remove_fillers", params: { clip: sel ? sel.id : "all" } }], "fillers"),
            { disabled: locked, running: busy === "fillers", sub: sel ? "فقط قطعهٔ انتخاب‌شده" : "همهٔ گفتارها" })}
          {act("sq-loudness", "🔊", "بلندیِ استاندارد برای شبکه‌ها (−۱۴)", "بلندیِ نهاییِ ویدیو را در حدِ استاندارد (حدودِ −۱۴ LUFS) یکسان می‌کند تا اینستاگرام و تیک‌تاک صدایش را پایین نیاورند. دوباره بزنید تا خاموش شود",
            () => void run(loudOn ? "خاموش‌کردنِ بلندیِ استاندارد" : "بلندیِ استاندارد برای شبکه‌ها", [{ tool: "set_loudness", params: { on: !loudOn, target: LOUDNESS_TARGET, tp: LOUDNESS_TP } }], "loud"),
            { disabled: locked, running: busy === "loud", on: loudOn, sub: loudOn ? "روشن ✓ (دوباره بزنید تا خاموش شود)" : "خاموش" })}
          {act("sq-voiceover", "🎙", "گویندگی از متن", "متن را بنویسید تا صدایش ساخته و روی تایم‌لاین گذاشته شود", () => setDialog("voice"), { disabled: locked, running: busy === "voice" })}
          {act("sq-automix", "⚡", "تنظیمِ خودکارِ میکس", "بلندیِ ترک‌ها را طوری تنظیم می‌کند که گفتار از موسیقی بلندتر و واضح باشد",
            () => void run("تنظیمِ خودکارِ میکس", [{ tool: "auto_mix", params: {} }], "mix"), { disabled: locked, running: busy === "mix" })}
          {onBeats && act("sq-beats", "🥁", "ضرب‌ها", canBeats ? "ضربِ موسیقیِ قطعهٔ انتخاب‌شده را روی تایم‌لاین علامت می‌زند تا برش‌ها را روی ضرب بچینید" : "اول یک قطعهٔ موسیقی یا صدادار را روی تایم‌لاین انتخاب کنید",
            () => onBeats(), { disabled: !canBeats || !!beatsBusy, running: !!beatsBusy, sub: beatsBusy ? "در حالِ تحلیل…" : undefined })}
        </div>
        {onBeats && !canBeats && !nested && <p className="ws-hint">برای «ضرب‌ها» اول یک قطعهٔ موسیقی یا صدادار را روی تایم‌لاین انتخاب کنید.</p>}
        {busy && <p className="sq-busy" role="status"><Spinner size={14} /> در حالِ انجام… (چند ثانیه تا چند دقیقه؛ پروژه را تا پایانش دست نزنید)</p>}
        {result && (
          <div className={`sq-result ${result.ok ? "is-ok" : "is-warn"}`} role="status" data-testid="sq-result">
            <div className="sq-result-body">
              {result.lines.map((l, i) => <div key={i} className={l.ok ? "is-ok" : "is-warn"}>{l.ok ? "✓" : "!"} {l.text}</div>)}
              {result.notes.map((n, i) => <div key={`n${i}`} className="sq-result-note">{n}</div>)}
            </div>
            <button type="button" className="ws-btn sq-x" onClick={() => setResult(null)} aria-label="بستنِ پیام" title="بستن">×</button>
          </div>
        )}
      </div>

      {dialog === "music" && (
        <MusicPicker storeId={storeId} bin={bin} media={media} programSeconds={projectLength(root)} busy={busy === "music"} onChoose={chooseMusic} onBinChanged={onBinChanged} onClose={() => setDialog(null)} />
      )}
      {dialog === "voice" && (
        <VoiceOverDialog storeId={storeId} busy={busy === "voice"} onAdd={addVoice} onBinChanged={onBinChanged} onClose={() => setDialog(null)} />
      )}
    </>
  );
}
