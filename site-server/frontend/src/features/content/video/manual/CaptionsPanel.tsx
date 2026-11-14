import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { api, errorMessage } from "../../../../api/client";
import { Alert, Badge, Spinner, fa } from "../../../../components/ui";
import { useJobRunner } from "../../../../hooks/useJobRunner";
import type { Job } from "../../../../types";
import { videoApi } from "../api";
import type { CaptionsStatus } from "../api";
import SpeechLanguagePicker, { type SpeechLang } from "../autoedit/SpeechLanguage";
import { MediaClip, Project, TextClip, clipLength, isMedia, timecode } from "./model";
import { drawText, onTextFontsReady } from "./textRender";
import "./text.css";

type Props = {
  storeId: string;
  project: Project;
  selectionIds: string[];
  /** کلیپ‌های زیرنویسِ ساخته‌شده؛ برنامه آن‌ها را روی ترکِ زیرنویس می‌گذارد */
  onInsert: (clips: Partial<TextClip>[]) => void;
  onNotice: (msg: string) => void;
  onImportSrt?: () => void;
  hasSrtSource: boolean;
};

/** سبک‌های آمادهٔ زیرنویس — فقط کلیدهایی که titles.clean می‌شناسد؛ روی هر قطعهٔ ساخته‌شده ادغام می‌شوند */
export const CAPTION_PRESETS: { key: string; title: string; hint: string; style: Partial<TextClip> }[] = [
  {
    key: "classic", title: "کلاسیک", hint: "سفید با لبهٔ مشکی، پایینِ قاب",
    style: { font: "vazir", bold: true, size: 6, color: "#ffffff", stroke_color: "#000000", stroke: 12, shadow: 0, box: false, position: "bottom", y: 0.84,
      hl_color: "#ffd400", hl_mode: "color", anim_in: "none", anim_out: "none", align: "center", rotation: 0, scale: 1 },
  },
  {
    key: "karaoke", title: "کارائوکهٔ زرد", hint: "کلمهٔ در حالِ گفتن زرد می‌شود",
    style: { font: "vazir", bold: true, size: 6.5, color: "#ffffff", stroke_color: "#000000", stroke: 14, shadow: 10, box: false, position: "bottom", y: 0.8,
      hl_color: "#ffd400", hl_mode: "color", anim_in: "none", anim_out: "none", align: "center", rotation: 0, scale: 1 },
  },
  {
    key: "boxed", title: "کادرِ تیره", hint: "متن روی زمینهٔ نیمه‌شفاف",
    style: { font: "vazir", bold: true, size: 5.6, color: "#ffffff", stroke_color: "#000000", stroke: 0, shadow: 0, box: true, box_color: "#000000", box_opacity: 0.6, box_pad: 22,
      position: "bottom", y: 0.84, hl_color: "#ffd400", hl_mode: "color", anim_in: "fade", anim_out: "none", anim_dur: 0.2, align: "center", rotation: 0, scale: 1 },
  },
  {
    key: "capcut", title: "درشتِ وسط (CapCut)", hint: "درشت، وسطِ قاب، کلمه بزرگ و سبز می‌شود",
    style: { font: "vazir_black", bold: false, size: 9.5, color: "#ffffff", stroke_color: "#000000", stroke: 18, shadow: 20, box: false, position: "middle", y: 0.55,
      hl_color: "#39ff14", hl_mode: "scale", anim_in: "pop", anim_out: "none", anim_dur: 0.25, align: "center", rotation: 0, scale: 1 },
  },
  {
    key: "marker", title: "ماژیکی", hint: "کلمهٔ فعال با هایلایتِ زرد",
    style: { font: "vazir", bold: true, size: 6.2, color: "#ffffff", stroke_color: "#000000", stroke: 10, shadow: 8, box: false, position: "bottom", y: 0.8,
      hl_color: "#ffd400", hl_mode: "box", anim_in: "none", anim_out: "none", align: "center", rotation: 0, scale: 1 },
  },
];

function PresetThumb({ preset, active, onPick }: { preset: (typeof CAPTION_PRESETS)[number]; active: boolean; onPick: () => void }) {
  const ref = useRef<HTMLCanvasElement>(null);
  const paint = useCallback(() => {
    const cv = ref.current;
    const ctx = cv?.getContext("2d");
    if (!cv || !ctx) return;
    const W = cv.width;
    const H = cv.height;
    const g = ctx.createLinearGradient(0, 0, W, H);
    g.addColorStop(0, "#25324f");
    g.addColorStop(1, "#5a3f73");
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, W, H);
    const clip: TextClip = {
      id: "cap-thumb", type: "text", text: "سلام به همه", at: 0, duration: 3, position: "bottom", size: 6, color: "#ffffff", box: false, opacity: 1, label: "",
      words: [{ w: "سلام", s: 0, e: 0.9 }, { w: "به", s: 0.9, e: 1.6 }, { w: "همه", s: 1.6, e: 3 }], caption: true, ...preset.style, anim_in: "none", anim_out: "none", y: 0.5,
    };
    drawText(ctx, clip, 1.2, W, H);
  }, [preset]);
  useEffect(() => {
    paint();
    return onTextFontsReady(paint);
  }, [paint]);
  return (
    <button type="button" className={`tx-tpl ${active ? "is-on" : ""}`} aria-pressed={active} onClick={onPick} data-preset={preset.key} title={preset.hint}>
      <canvas ref={ref} width={150} height={84} aria-hidden />
      <span>{preset.title}</span>
    </button>
  );
}

type Source = { clip: MediaClip; trackName: string };

/** قطعه‌ای که صدای قابلِ شنیدن دارد */
const carriesSound = (c: MediaClip): boolean => !c.freeze && c.kind !== "image" && (c.kind === "audio" || (c.kind === "video" && c.has_audio && c.audio_on !== false));

export default function CaptionsPanel({ storeId, project, selectionIds, onInsert, onNotice, onImportSrt, hasSrtSource }: Props) {
  const [status, setStatus] = useState<CaptionsStatus | null>(null);
  const [checking, setChecking] = useState(false);
  const [mode, setMode] = useState<"selected" | "speech">("selected");
  const [presetKey, setPresetKey] = useState("karaoke");
  const [working, setWorking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [progress, setProgress] = useState<{ idx: number; total: number } | null>(null);
  const queue = useRef<Source[]>([]);
  const index = useRef(0);
  const found = useRef<Partial<TextClip>[]>([]);
  const jobId = useRef<number | null>(null);
  const cancelled = useRef(false);
  const presetRef = useRef(presetKey);
  presetRef.current = presetKey;

  const checkStatus = useCallback(async () => {
    setChecking(true);
    try {
      setStatus(await videoApi.captionsStatus(storeId));
    } catch (err) {
      setStatus({ node: false, local: false, ok: false, message: errorMessage(err) });
    } finally {
      setChecking(false);
    }
  }, [storeId]);
  useEffect(() => {
    void checkStatus();
  }, [checkStatus]);

  const sources = useMemo(() => {
    const all: Source[] = [];
    for (const t of project.tracks) for (const c of t.clips) if (isMedia(c) && carriesSound(c)) all.push({ clip: c, trackName: t.name });
    const speechTracks = new Set(project.tracks.filter((t) => t.role === "speech").map((t) => t.id));
    const bySelection = all.filter((s) => selectionIds.includes(s.clip.id));
    const bySpeech = all.filter((s) => project.tracks.some((t) => speechTracks.has(t.id) && t.clips.includes(s.clip)));
    const pool = mode === "selected" ? bySelection : bySpeech.length ? bySpeech : all;
    const seen = new Set<string>();
    return pool.filter((s) => {
      const k = `${s.clip.ref}|${s.clip.start}|${s.clip.end}|${s.clip.at}`;
      if (seen.has(k)) return false;
      seen.add(k);
      return true;
    });
  }, [project, selectionIds, mode]);

  const finish = useCallback(() => {
    const preset = CAPTION_PRESETS.find((p) => p.key === presetRef.current) ?? CAPTION_PRESETS[0];
    const clips = found.current.map((c) => ({ ...c, ...preset.style, caption: true }));
    setWorking(false);
    setProgress(null);
    if (clips.length === 0) {
      setError("حرفی در این بخش‌ها شنیده نشد.");
      return;
    }
    onInsert(clips);
    onNotice(`${fa(clips.length)} خط زیرنویس روی ترکِ زیرنویس آمد (با زمان‌بندیِ کلمه‌به‌کلمه).`);
  }, [onInsert, onNotice]);

  const [lang, setLang] = useState<SpeechLang>("fa");
  const langRef = useRef<SpeechLang>("fa");
  langRef.current = lang;
  const runNext = useRef<() => Promise<void>>(async () => undefined);
  const onDone = useCallback(async () => {
    const id = jobId.current;
    if (id !== null) {
      try {
        const { data } = await api.get<Job>(`/jobs/${id}/`);
        const clips = (data.result as { clips?: Partial<TextClip>[] } | undefined)?.clips;
        if (Array.isArray(clips)) found.current.push(...clips);
      } catch (err) {
        setError(errorMessage(err));
      }
    }
    index.current += 1;
    await runNext.current();
  }, []);
  const runner = useJobRunner(onDone);

  runNext.current = async () => {
    if (cancelled.current) return;
    const item = queue.current[index.current];
    if (!item) {
      finish();
      return;
    }
    setProgress({ idx: index.current, total: queue.current.length });
    const c = item.clip;
    const speed = Math.max(0.25, Math.min(4, (c.end - c.start) / Math.max(0.1, clipLength(c))));
    try {
      runner.begin();
      const r = await videoApi.captions(storeId, { ref: c.ref, start: c.start, end: c.end, at: c.at, speed, language: langRef.current });
      jobId.current = r.job_id;
      runner.track(r.job_id);
    } catch (err) {
      runner.fail(errorMessage(err));
      setError(errorMessage(err));
      setWorking(false);
      setProgress(null);
    }
  };

  // شکستِ یک job (نه لغو) صف را می‌بندد
  useEffect(() => {
    if (runner.error && working) {
      setWorking(false);
      setProgress(null);
    }
  }, [runner.error, working]);

  const start = () => {
    setError(null);
    cancelled.current = false;
    const usable = sources.filter((s) => !s.clip.reverse);
    if (usable.length === 0) {
      setError(sources.length ? "قطعه‌های وارونه زیرنویس نمی‌شوند." : mode === "selected" ? "اول قطعه‌ای (ویدیو یا صدا) را انتخاب کنید." : "قطعه‌ای با صدا پیدا نشد.");
      return;
    }
    queue.current = usable;
    index.current = 0;
    found.current = [];
    setWorking(true);
    void runNext.current();
  };

  const stop = () => {
    cancelled.current = true;
    void runner.cancel();
    setWorking(false);
    setProgress(null);
  };

  const total = sources.reduce((s, x) => s + (x.clip.end - x.clip.start) / (x.clip.speed || 1), 0);
  const jobFrac = runner.job && runner.job.total_steps ? runner.job.progress_step / runner.job.total_steps : 0;
  const overall = progress ? Math.min(1, (progress.idx + jobFrac) / Math.max(1, progress.total)) : 0;
  const ok = !!status?.ok || !!status?.waiting;          // «در انتظارِ سرور» هم یعنی می‌شود درخواست داد

  return (
    <div className="cap-panel" dir="rtl" data-testid="captions-panel">
      <div className="ws-card-title">زیرنویسِ خودکار</div>
      <p className="ws-hint">گفتارِ ویدیو یا صدا تشخیص داده می‌شود و به خط‌های کوتاه با زمان‌بندیِ هر کلمه تبدیل می‌شود؛ بعد می‌توانید متن و سبک را ویرایش کنید.</p>

      <div className="cap-status" data-testid="captions-status">
        {status === null ? (
          <span className="ws-muted"><Spinner size={12} /> در حالِ بررسیِ سرورِ پردازش…</span>
        ) : ok ? (
          status.waiting
            ? <Badge tone="warn"><span data-testid="captions-waiting">{status.message}</span></Badge>
            : <Badge tone="ok">{status.node ? "سرورِ پردازش (گفتارخوان) آنلاین است" : "مدلِ محلی آماده است"}</Badge>
        ) : (
          <Alert tone="warn" title="الان نمی‌شود گفتار را تشخیص داد">
            <span data-testid="captions-offline">{status.message || "سرورِ پردازش خاموش است."}</span>
            <div className="mt-2 flex flex-wrap gap-2">
              <button type="button" className="ws-btn" disabled={checking} onClick={() => void checkStatus()}>{checking ? "در حالِ بررسی…" : "بررسیِ دوباره"}</button>
              {hasSrtSource && onImportSrt && <button type="button" className="ws-btn" onClick={onImportSrt}>ورودِ زیرنویسِ آمادهٔ این ویدیو</button>}
            </div>
          </Alert>
        )}
      </div>

      <div className="tx-sub">از کجا زیرنویس بسازم؟</div>
      <div className="flex flex-wrap gap-1">
        <button type="button" className={`ws-chip ${mode === "selected" ? "is-on" : ""}`} aria-pressed={mode === "selected"} onClick={() => setMode("selected")} data-cap-mode="selected">قطعهٔ انتخاب‌شده</button>
        <button type="button" className={`ws-chip ${mode === "speech" ? "is-on" : ""}`} aria-pressed={mode === "speech"} onClick={() => setMode("speech")} data-cap-mode="speech">همهٔ گفتار (ترک‌های گفتار)</button>
      </div>
      <p className="ws-hint" data-testid="captions-sources">
        {sources.length === 0
          ? mode === "selected" ? "قطعه‌ای با صدا انتخاب نشده است." : "قطعه‌ای با صدا در پروژه نیست."
          : `${fa(sources.length)} قطعه — حدودِ ${timecode(total).slice(0, 5)} صدا`}
      </p>

      <div className="tx-sub">زبانِ گفتار</div>
      <SpeechLanguagePicker value={lang} onChange={setLang} testId="captions-speech-language" />

      <div className="tx-sub">سبکِ زیرنویس</div>
      <div className="tx-tpl-grid">
        {CAPTION_PRESETS.map((p) => <PresetThumb key={p.key} preset={p} active={presetKey === p.key} onPick={() => setPresetKey(p.key)} />)}
      </div>

      {!working ? (
        <button type="button" className="ws-btn primary w-full justify-center mt-2" disabled={!ok || sources.length === 0} onClick={start} data-testid="captions-run">
          ساختنِ زیرنویس
        </button>
      ) : (
        <div className="cap-run" data-testid="captions-running">
          <div className="xp-bar" role="progressbar" aria-valuenow={Math.round(overall * 100)} aria-valuemin={0} aria-valuemax={100}><i style={{ width: `${Math.round(overall * 100)}%` }} /></div>
          <div className="ws-muted"><Spinner size={12} /> {runner.job?.current_step_label || "در حالِ تشخیصِ گفتار…"} {progress ? `(${fa(progress.idx + 1)} از ${fa(progress.total)})` : ""}</div>
          <button type="button" className="ws-btn mt-1" onClick={stop}>لغو</button>
        </div>
      )}
      {(error || runner.error) && !working && <div className="mt-2"><Alert tone="bad" title="زیرنویس ساخته نشد">{error || runner.error}</Alert></div>}
      <p className="ws-hint mt-2">
        هر خط یک قطعهٔ متن است (روی ترکِ «زیرنویس»)؛ با انتخابش در تبِ «متن» می‌توانید کلمه‌ها، زمان‌ها، رنگ و هایلایت را عوض کنید و سبک را روی همهٔ خط‌ها اعمال کنید.
      </p>
    </div>
  );
}
