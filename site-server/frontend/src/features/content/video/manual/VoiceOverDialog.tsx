import { useEffect, useMemo, useRef, useState } from "react";

import { Spinner, fa } from "../../../../components/ui";
import { AudioOverview, VoiceOption, loadOverview } from "../../../audio/api";
import { Recorder, micErrorText, micSupport, startRecording } from "./micRecorder";
import { timecode } from "./model";
import SoundDialog from "./SoundDialog";
import { makeAsset, soundError, uploadAudio } from "./soundApi";
import type { ChooseOutcome } from "./MusicPicker";
import "./sound.css";
import { usePlayhead } from "./playhead";

/** آیا سرور مسیری برای آپلودِ صدای ضبط‌شده به کتابخانهٔ صدا دارد؟ (فعلاً نه: فقط ساختن از متن) — با ساخته‌شدنِ مسیر `true` شود */
export const AUDIO_UPLOAD_READY = true;

const MAX_CHARS = 600;
const clamp = (x: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, x));

/**
 * «گویندگی از متن»: متن + گوینده + سرعت ⇒ ساختِ گفتار (سرورِ پردازش یا موتورِ سایت) ⇒ ذخیره در کتابخانه ⇒ ابزارِ add_voiceover
 * که صدا را از سرِ پخش روی ترکِ گفتار می‌گذارد. ضبط با میکروفون فقط روی نشانیِ امن (https) کار می‌کند؛ تا آن موقع دکمه خاموش است و دلیلش روی صفحه نوشته شده.
 */
export default function VoiceOverDialog({
  storeId, busy, onAdd, onBinChanged, onClose,
}: {
  storeId: string;
  /** ابزارِ add_voiceover در حالِ اجراست */
  busy: boolean;
  onAdd: (ref: string, title: string) => Promise<ChooseOutcome>;
  onBinChanged: () => void;
  onClose: () => void;
}) {
  const playhead = usePlayhead();   // لحظه‌ای که گویندگی از آن‌جا شروع می‌شود (فقط همین پنجره با زمان رندر می‌شود)
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  const [overview, setOverview] = useState<AudioOverview | null>(null);
  const [ovError, setOvError] = useState<string | null>(null);
  useEffect(() => {
    let on = true;
    loadOverview(storeId).then(
      (o) => on && setOverview(o),
      (e) => on && setOvError(soundError(e)),
    );
    return () => {
      on = false;
    };
  }, [storeId]);

  const voices = overview?.voices ?? [];
  const ready = useMemo(() => voices.filter((v) => v.available), [voices]);
  const groups = useMemo(() => {
    const m = new Map<string, VoiceOption[]>();
    for (const v of ready) m.set(v.group || "سایر", [...(m.get(v.group || "سایر") ?? []), v]);
    return [...m.entries()];
  }, [ready]);
  const whys = useMemo(() => [...new Set(voices.filter((v) => !v.available && v.why).map((v) => v.why))].slice(0, 2), [voices]);

  const [text, setText] = useState("");
  const [voice, setVoice] = useState("");
  const chosen = ready.find((v) => v.id === voice) ?? ready[0];
  const sp = overview?.limits.speed ?? [0.8, 1.3];
  const lo = Math.max(0.8, sp[0]);
  const hi = Math.min(1.3, sp[1]);
  const [sMin, sMax] = lo <= hi ? [lo, hi] : [0.8, 1.3];
  const [speedRaw, setSpeed] = useState(1);
  const speed = clamp(speedRaw, sMin, sMax);
  const maxChars = Math.min(MAX_CHARS, overview?.limits.speech_chars || MAX_CHARS);

  const [genBusy, setGenBusy] = useState(false);
  const [genText, setGenText] = useState("");
  const [error, setError] = useState<string | null>(null);

  const fileInput = useRef<HTMLInputElement>(null);
  const captureInput = useRef<HTMLInputElement>(null);
  // ---- ضبط با میکروفون (فقط روی https/localhost)
  const mic = useMemo(() => micSupport(), []);
  const recorder = useRef<Recorder | null>(null);
  const [recording, setRecording] = useState(false);
  const [recSec, setRecSec] = useState(0);
  const [micError, setMicError] = useState<string | null>(null);
  useEffect(() => () => recorder.current?.cancel(), []);
  const upload = async (file: File) => {
    setGenBusy(true);
    setError(null);
    setGenText("در حالِ فرستادنِ صدا…");
    try {
      const a = await uploadAudio(storeId, file, "speech");
      onBinChanged();
      if (!alive.current) return;
      setGenText("در حالِ گذاشتنِ صدا روی تایم‌لاین…");
      const r = await onAdd(`audio:${a.id}`, a.title || "صدای ضبط‌شده");
      if (alive.current && !r.ok) setError(r.message);
    } catch (err) {
      if (alive.current) setError(soundError(err));
    } finally {
      if (alive.current) {
        setGenBusy(false);
        setGenText("");
        if (fileInput.current) fileInput.current.value = "";
      }
    }
  };

  const toggleRecord = async () => {
    if (recording) {
      recorder.current?.stop();
      return;
    }
    setMicError(null);
    setRecSec(0);
    try {
      recorder.current = await startRecording((file) => {
        recorder.current = null;
        if (!alive.current) return;
        setRecording(false);
        if (file) void upload(file);
        else setMicError("چیزی ضبط نشد.");
      }, (sec) => alive.current && setRecSec(sec));
      setRecording(true);
    } catch (err) {
      setMicError(micErrorText(err));
    }
  };

  const go = async () => {
    if (!chosen || !text.trim()) return;
    setGenBusy(true);
    setError(null);
    try {
      const title = `گویندگی: ${text.trim().slice(0, 30)}`;
      const a = await makeAsset(storeId, { kind: "speech", text: text.trim(), voice: chosen.id, speed, title }, (t) => alive.current && setGenText(t));
      onBinChanged();
      if (!alive.current) return;
      setGenText("در حالِ گذاشتنِ گویندگی روی تایم‌لاین…");
      const r = await onAdd(`audio:${a.id}`, a.title || title);
      if (alive.current && !r.ok) setError(r.message);
    } catch (err) {
      if (alive.current) setError(soundError(err));
    } finally {
      if (alive.current) {
        setGenBusy(false);
        setGenText("");
      }
    }
  };

  const working = genBusy || busy;
  const noVoice = !!overview && ready.length === 0;

  return (
    <SoundDialog title="گویندگی از متن" testId="voiceover-dialog" onClose={onClose}>
      <p className="ws-hint">متن را بنویسید؛ صدایش ساخته می‌شود و از لحظهٔ سرِ پخش ({fa(timecode(playhead).slice(0, 5))}) روی ترکِ گفتار می‌نشیند. با «برگشت» (Ctrl+Z) برمی‌گردد.</p>

      {ovError && <p className="sq-note is-warn" data-testid="vo-overview-error">{ovError}</p>}
      {!overview && !ovError && <p className="sq-busy"><Spinner size={14} /> در حالِ بارگیری…</p>}

      <label className="ws-field">
        <span>متنِ گویندگی <small className="ws-muted">({fa(text.length)} از {fa(maxChars)} نویسه)</small></span>
        <textarea className="u-input sq-text" rows={5} maxLength={maxChars} value={text} onChange={(e) => setText(e.target.value)} disabled={working}
          placeholder="مثلاً: کفش‌های تابستانی رسید؛ تا جمعه با ارسالِ رایگان." data-testid="vo-text" />
      </label>

      {noVoice ? (
        <div className="sq-note is-warn" data-testid="vo-unavailable">
          <b>الان هیچ گوینده‌ای آماده نیست.</b>
          {whys.map((w) => <div key={w}>{w}</div>)}
        </div>
      ) : (
        overview && (
          <>
            <label className="ws-field">
              <span>گوینده</span>
              <select className="u-input" value={chosen?.id ?? ""} onChange={(e) => setVoice(e.target.value)} disabled={working} aria-label="گوینده" data-testid="vo-voice">
                {groups.map(([g, rows]) => (
                  <optgroup key={g} label={g}>
                    {rows.map((v) => (
                      <option key={v.id} value={v.id}>
                        {v.name}{v.gender === "female" ? " (زن)" : v.gender === "male" ? " (مرد)" : ""}{v.commercial ? "" : " — غیرتجاری"}
                      </option>
                    ))}
                  </optgroup>
                ))}
              </select>
            </label>
            {chosen && !chosen.commercial && <p className="sq-note is-warn">این صدا مجوزِ استفادهٔ تجاری ندارد ({chosen.license}).</p>}
            {whys.length > 0 && <p className="ws-hint" data-testid="vo-why">بعضی گوینده‌ها الان آماده نیستند: {whys.join(" — ")}</p>}
            <label className="sq-slider sq-slider-sm">
              <span className="sq-slider-head"><span className="sq-slider-label">سرعتِ گفتار</span><span className="sq-slider-val" dir="ltr">{fa(speed.toFixed(2).replace(/0$/, "")).replace(".", "٫")}×</span></span>
              <input type="range" min={sMin} max={sMax} step={0.05} value={speed} onChange={(e) => setSpeed(Number(e.target.value))} disabled={working} aria-label="سرعتِ گفتار" data-testid="vo-speed" />
            </label>
          </>
        )
      )}

      <button type="button" className="ws-btn primary sq-wide" disabled={working || !text.trim() || !chosen} onClick={() => void go()} data-testid="vo-make">
        {working ? "در حالِ کار…" : "🎙 بساز و بگذار روی تایم‌لاین"}
      </button>
      {working && <p className="sq-busy" role="status" data-testid="vo-progress"><Spinner size={14} /> {genText || "در حالِ گذاشتنِ گویندگی روی تایم‌لاین…"}</p>}
      {genBusy && <p className="ws-hint">اگر پنجره را ببندید، صدا ساخته و در بخشِ «صدا»ی رسانه‌ها ذخیره می‌شود ولی خودکار روی تایم‌لاین نمی‌نشیند.</p>}
      {error && <p className="sq-note is-warn" data-testid="vo-error">{error}</p>}

      <div className="sq-sub">یا صدای خودتان</div>
      <div className="sq-actions">
        {mic.ok ? (
          <button type="button" className={`ws-btn sq-act ${recording ? "is-on" : ""}`} disabled={working && !recording} onClick={() => void toggleRecord()} aria-pressed={recording}
            title={recording ? "ایستادن و گذاشتنِ صدا روی تایم‌لاین" : "با میکروفونِ همین دستگاه ضبط کنید؛ بعد از ایستادن، صدا از سرِ پخش روی تایم‌لاین می‌نشیند"} data-testid="vo-record">
            {recording ? `⏹ ایست و گذاشتن (${fa(Math.floor(recSec / 60))}:${fa(String(recSec % 60).padStart(2, "0"))})` : "⏺ ضبط با میکروفون"}
          </button>
        ) : (
          <>
            <button type="button" className="ws-btn sq-act" disabled title={mic.reason} data-testid="vo-record-disabled">⏺ ضبط با میکروفون</button>
            {/* روی نشانیِ ناامن (http) مرورگر میکروفون نمی‌دهد؛ ولی «گرفتنِ فایل با ضبطِ خودِ گوشی» همه‌جا کار می‌کند */}
            <input ref={captureInput} type="file" accept="audio/*" capture hidden data-testid="vo-capture-input" onChange={(e) => { const f = e.target.files?.[0]; if (f) void upload(f); e.target.value = ""; }} />
            <button type="button" className="ws-btn sq-act" disabled={working} onClick={() => captureInput.current?.click()} data-testid="vo-phone-record"
              title="برنامهٔ ضبطِ صدای خودِ گوشی باز می‌شود؛ بعد از ضبط، صدا خودکار روی تایم‌لاین می‌نشیند (روی کامپیوتر پنجرهٔ انتخابِ فایل باز می‌شود)">⏺ ضبط با برنامهٔ ضبطِ گوشی</button>
          </>
        )}
        <input ref={fileInput} type="file" accept="audio/*,video/mp4,.m4a,.aac,.amr,.3gp,.opus,.webm" hidden data-testid="vo-upload-input"
          onChange={(e) => { const f = e.target.files?.[0]; if (f) void upload(f); }} />
        <button type="button" className="ws-btn sq-act" disabled={working} onClick={() => fileInput.current?.click()} title="صدایی که با گوشی ضبط کرده‌اید (m4a، mp3، wav…) را بیاورید؛ روی تایم‌لاین از سرِ پخش می‌نشیند" data-testid="vo-upload">⬆ آپلودِ صدای ضبط‌شده</button>
      </div>
      {mic.ok
        ? <p className="ws-hint" data-testid="vo-record-why">ضبط را بزنید و حرف بزنید؛ با «ایست» صدا ذخیره و روی تایم‌لاین گذاشته می‌شود (حداکثر ۵ دقیقه). اولین بار مرورگر اجازهٔ میکروفون را می‌پرسد.</p>
        : <p className="ws-hint" data-testid="vo-record-why">{mic.reason} روی گوشی دکمهٔ «ضبط با برنامهٔ ضبطِ گوشی» ضبطِ خودِ گوشی را باز می‌کند و صدا همان‌جا روی تایم‌لاین می‌نشیند.</p>}
      {micError && <p className="sq-note is-warn" role="alert" data-testid="vo-mic-error">{micError}</p>}
    </SoundDialog>
  );
}
