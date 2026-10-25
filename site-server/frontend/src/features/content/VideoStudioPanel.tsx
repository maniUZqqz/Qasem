import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api, errorMessage } from "../../api/client";
import JobProgress from "../../components/JobProgress";
import SegmentApproval from "../../components/SegmentApproval";
import SegmentQualityChip from "../../components/SegmentQualityChip";
import SoundDesignCard from "../../components/SoundDesignCard";
import {
  Button,
  Card,
  Chip,
  ErrorBox,
  Field,
  Input,
  SectionTitle,
} from "../../components/ui";
import { useJobRunner } from "../../hooks/useJobRunner";
import { Job, SoundOption, StoreVoice, VideoSceneInfo, VideoScriptInfo } from "../../types";
import CutsPanel from "./CutsPanel";
import RealPhotoPanel from "./RealPhotoPanel";
import SceneSoundCell from "./SceneSoundCell";
import SubtitleMusicPanel from "./SubtitleMusicPanel";
import VideoSoundPanel, { NarratorPicker } from "../audio/VideoSoundPanel";

const TRANSITION_LABEL: Record<string, string> = {
  NEW_SCENE: "صحنه جدید",
  CONTINUE: "ادامه از فریم آخر",
  TRANSITION: "گذار نرم",
};

export default function VideoStudioPanel({
  productId,
  storeId,
}: {
  productId: number;
  /** Subtitles and music hang off the store, so the panel needs it too. */
  storeId?: string | number;
}) {
  const [script, setScript] = useState<VideoScriptInfo | null>(null);
  const [duration, setDuration] = useState("15");
  const [objective, setObjective] = useState("");
  const [language, setLanguage] = useState<"fa" | "en">("fa");
  const [showScenes, setShowScenes] = useState(false);
  // Ambience (rain, street, café…) and moment effects (a lamp click, heels)
  // under the narration. On by default; the admin's mix settings decide
  // whether they exist at all.
  const [ambience, setAmbience] = useState(true);
  const [effects, setEffects] = useState(true);
  // Every sound the mixer can place — loaded when the scene table opens.
  const [catalogue, setCatalogue] = useState<SoundOption[]>([]);
  // Set once a scene's sound was changed after the last voicing.
  const [soundChanged, setSoundChanged] = useState(false);
  // Who will read the narration, from the store's voice settings.
  const [voice, setVoice] = useState<StoreVoice | null>(null);

  const load = useCallback(async () => {
    try {
      // the backend returns 200 + null when no script exists yet
      const { data } = await api.get<VideoScriptInfo | null>(
        `/products/${productId}/video-script/`,
      );
      setScript(data ?? null);
    } catch {
      setScript(null);
    }
  }, [productId]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!showScenes || catalogue.length > 0) return;
    api
      .get<{ sounds: SoundOption[] }>("/audio/sounds/")
      .then(({ data }) => setCatalogue(data.sounds))
      .catch(() => setCatalogue([]));
  }, [showScenes, catalogue.length]);

  const hasFinal = Boolean(script?.final_video);
  useEffect(() => {
    if (!storeId || !hasFinal) return;
    api
      .get<StoreVoice>(`/stores/${storeId}/voice/`)
      .then(({ data }) => setVoice(data))
      .catch(() => setVoice(null));
  }, [storeId, hasFinal]);

  const setOnCamera = async (scene: VideoSceneInfo, enabled: boolean) => {
    if (!script) return;
    try {
      const { data } = await api.patch<VideoSceneInfo>(
        `/video-scripts/${script.id}/scenes/${scene.index}/on-camera/`,
        { enabled },
      );
      sceneSaved(data);
    } catch (err) {
      voiceRunner.fail(errorMessage(err));
    }
  };

  const sceneSaved = (updated: VideoSceneInfo) => {
    setScript((current) =>
      current
        ? {
            ...current,
            scenes: current.scenes.map((s) => (s.index === updated.index ? updated : s)),
          }
        : current,
    );
    setSoundChanged(true);
  };

  const scriptRunner = useJobRunner(load);
  const videoRunner = useJobRunner(load);
  const voiceRunner = useJobRunner(load);

  // re-attach to in-flight jobs after refresh/navigation (beter.md #2)
  const resumeScript = scriptRunner.resume;
  const resumeVideo = videoRunner.resume;
  const resumeVoice = voiceRunner.resume;
  useEffect(() => {
    void resumeScript({ type: "video_script_generation", productId });
  }, [resumeScript, productId]);
  useEffect(() => {
    if (!script?.id) return;
    void resumeVideo({ type: "video_generation", scriptId: script.id });
  }, [resumeVideo, script?.id]);
  // The video job starts the voice job itself when it finishes, so the voice
  // runner re-attaches every time the script reloads (updated_at moves when
  // the render completes) — the owner sees «صداگذاری» running without a click.
  useEffect(() => {
    if (!script?.id) return;
    void resumeVoice({ type: "voice_generation", scriptId: script.id });
  }, [resumeVoice, script?.id, script?.updated_at]);

  const generateScript = async () => {
    scriptRunner.begin();
    try {
      const { data } = await api.post<{ job_id: number; job: Job }>(
        `/products/${productId}/video-script/`,
        { duration: Number(duration) || 15, objective, language },
      );
      scriptRunner.track(data.job_id, data.job);
    } catch (err) {
      scriptRunner.fail(errorMessage(err));
    }
  };

  const generateVideo = async () => {
    if (!script) return;
    videoRunner.begin();
    try {
      const { data } = await api.post<{ job_id: number; job: Job }>(
        `/video-scripts/${script.id}/generate/`,
      );
      videoRunner.track(data.job_id, data.job);
    } catch (err) {
      videoRunner.fail(errorMessage(err));
    }
  };

  const generateVoice = async () => {
    if (!script) return;
    voiceRunner.begin();
    try {
      const { data } = await api.post<{ job_id: number; job: Job }>(
        `/video-scripts/${script.id}/voice/`,
        { ambience, effects },
      );
      voiceRunner.track(data.job_id, data.job);
      setSoundChanged(false);
    } catch (err) {
      voiceRunner.fail(errorMessage(err));
    }
  };

  const anyRunning = scriptRunner.running || videoRunner.running || voiceRunner.running;
  const activeRunner = [voiceRunner, videoRunner, scriptRunner].find((r) => r.running) ?? null;
  const activeJob = activeRunner?.job ?? null;

  // A render that stopped after a segment and is waiting for a look. Only the
  // video runner can park; the other two produce one thing and finish.
  const parkedJob = videoRunner.waiting ? videoRunner.job : null;
  // A parked job is not "running", so the generate buttons would unlock and let
  // the owner start a second render on top of the one already half-done.
  const anyBusy = anyRunning || parkedJob !== null;

  return (
    <Card>
      <SectionTitle>🎬 استودیوی ویدیو</SectionTitle>
      <ErrorBox message={scriptRunner.error} />
      <ErrorBox message={videoRunner.error} />
      <ErrorBox message={voiceRunner.error} />

      <div className="mb-4 flex flex-wrap items-end gap-3">
        <div className="w-32">
          <Field label="مدت (ثانیه)">
            <Input
              type="number"
              min="5"
              max="60"
              step="5"
              value={duration}
              onChange={(e) => setDuration(e.target.value)}
            />
          </Field>
        </div>
        <div className="w-64">
          <Field label="هدف (اختیاری)">
            <Input
              value={objective}
              onChange={(e) => setObjective(e.target.value)}
              placeholder="مثلاً معرفی محصول جدید"
            />
          </Field>
        </div>
        <div className="w-40">
          <Field label="زبان نریشن و صدا">
            <select
              value={language}
              onChange={(e) => setLanguage(e.target.value as "fa" | "en")}
              className="u-input"
            >
              <option value="fa">🇮🇷 فارسی</option>
              <option value="en">🇬🇧 English</option>
            </select>
          </Field>
        </div>
        <Button onClick={generateScript} disabled={anyBusy}>
          {scriptRunner.running ? "در حال نوشتن سناریو…" : script ? "سناریوی جدید" : "تولید سناریو"}
        </Button>
        {script && (
          <Button onClick={generateVideo} disabled={anyBusy} variant="secondary">
            {videoRunner.running ? "در حال تولید ویدیو…" : "🎥 تولید ویدیو (Wan 2.2)"}
          </Button>
        )}
        {script?.final_video && (
          <div className="flex flex-wrap items-center gap-3">
            <Button onClick={generateVoice} disabled={anyBusy} variant="secondary">
              {voiceRunner.running
                ? "در حال صداگذاری…"
                : script.final_video_voiced
                  ? "🔊 صداگذاری دوباره"
                  : "🔊 صداگذاری"}
            </Button>
            <label className="flex items-center gap-1 text-sm" style={{ color: "var(--text-2)" }}>
              <input
                type="checkbox"
                checked={ambience}
                onChange={(e) => setAmbience(e.target.checked)}
                disabled={anyBusy}
              />
              صدای محیط
            </label>
            <label className="flex items-center gap-1 text-sm" style={{ color: "var(--text-2)" }}>
              <input
                type="checkbox"
                checked={effects}
                onChange={(e) => setEffects(e.target.checked)}
                disabled={anyBusy}
              />
              افکت‌ها
            </label>
          </div>
        )}
      </div>

      {/* گوینده — صداهای MOSS، صدای کلون‌شدهٔ فروشگاه یا مرد/زن؛ با «صداگذاریِ دوباره» */}
      {script?.final_video && voice && storeId && (
        <NarratorPicker
          storeId={storeId}
          voice={voice}
          language={script.narration_language}
          onChanged={setVoice}
          onRegenerate={() => void generateVoice()}
          busy={anyBusy}
          voiced={Boolean(script.final_video_voiced)}
        />
      )}
      {script?.final_video && voice && !storeId && (
        <NarratorLine voice={voice} language={script.narration_language} storeId={storeId} />
      )}

      {anyRunning && (
        <JobProgress
          job={activeJob}
          startedAt={activeRunner?.startedAt ?? null}
          onCancel={() => void activeRunner?.cancel()}
          fallbackLabel="در حال شروع پردازش ویدیو…"
        />
      )}

      {parkedJob && (
        <SegmentApproval
          job={parkedJob}
          onResumed={(job) => videoRunner.track(job.id, job)}
          onStopped={() => {
            videoRunner.setJob(null);
            void load();
          }}
        />
      )}

      {!script && !anyRunning && (
        <p className="text-sm text-slate-400">
          هنوز سناریویی ساخته نشده. اول سناریو تولید کنید؛ بعد ویدیو قطعه‌قطعه با Wan 2.2 ساخته
          می‌شود (نیازمند ComfyUI روی سیستم اصلی + حداقل یک عکس محصول).
        </p>
      )}

      {script && (
        <div className="space-y-4">
          {script.concept && (
            <p className="rounded-lg bg-slate-50 p-3 text-sm leading-6 text-slate-700">
              <span className="font-bold">کانسپت: </span>
              {script.concept}
            </p>
          )}
          {script.cta && (
            <p className="text-sm text-violet-700">
              <span className="font-bold">CTA: </span>
              {script.cta}
            </p>
          )}

          <div className="flex items-center gap-3 text-sm">
            <Chip>{script.total_duration} ثانیه</Chip>
            <Chip>{script.scenes.length} صحنه</Chip>
            <Chip>{script.narration_language === "en" ? "🇬🇧 نریشن انگلیسی" : "🇮🇷 نریشن فارسی"}</Chip>
            <button
              onClick={() => setShowScenes((v) => !v)}
              className="text-violet-600 hover:underline"
            >
              {showScenes ? "بستن صحنه‌ها" : "نمایش صحنه‌ها"}
            </button>
          </div>

          {showScenes && (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[600px] text-right text-sm">
                <thead>
                  <tr className="border-b border-slate-200 text-xs text-slate-500">
                    <th className="py-2">#</th>
                    <th>مدت</th>
                    <th>ترنزیشن</th>
                    <th>نریشن</th>
                    <th>پرامپت بصری (EN)</th>
                    <th>صدای محیط و افکت</th>
                    <th title="یک آدم رو به دوربین در این صحنه ساخته می‌شود و خودش نریشن را می‌گوید. برای داشتنِ صدا لازم نیست — صدا خودکار اضافه می‌شود.">
                      آدمِ گوینده در تصویر
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {script.scenes.map((scene) => (
                    <tr key={scene.index} className="border-b border-slate-100 align-top">
                      <td className="py-2 font-bold">{scene.index}</td>
                      <td>{scene.duration}s</td>
                      <td className="text-xs">{TRANSITION_LABEL[scene.transition]}</td>
                      <td className="max-w-[200px]">{scene.narration}</td>
                      <td className="max-w-[260px] text-xs text-slate-500" dir="ltr">
                        {scene.visual_prompt}
                      </td>
                      <td className="py-2">
                        <SceneSoundCell
                          key={JSON.stringify(scene.sound ?? {})}
                          scriptId={script.id}
                          scene={scene}
                          catalogue={catalogue}
                          onSaved={sceneSaved}
                        />
                      </td>
                      <td className="py-2 text-xs">
                        <label className="flex items-center gap-1" style={{ color: "var(--text-2)" }}>
                          <input
                            type="checkbox"
                            checked={Boolean(scene.speaker_on_camera)}
                            disabled={anyBusy}
                            onChange={(e) => void setOnCamera(scene, e.target.checked)}
                          />
                          آدم بیاید
                        </label>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="mt-2 text-xs" style={{ color: "var(--text-3)" }}>
                صحنه‌ها به‌طور پیش‌فرض فقط محصول را نشان می‌دهند و فقط دوربین حرکت می‌کند؛ آدم
                و دست فقط برای محصولِ پوشیدنی (لباس، کفش، کیف، زیورآلات، آرایشی) ساخته می‌شود.
                صدای گوینده و صدای محیط بعد از ساختِ ویدیو خودکار اضافه می‌شود.
              </p>
              {script.scenes.some((s) => s.speaker_on_camera) && (
                <p className="mt-2 text-xs" style={{ color: "var(--warn)" }}>
                  در صحنه‌های «آدم بیاید» یک آدم رو به دوربین ساخته می‌شود که خودش نریشن را
                  می‌گوید و لب‌هایش با صدای گوینده هماهنگ می‌شود (نیازمند ComfyUI و مدل LatentSync
                  روی سیستم اصلی). اگر آدم نمی‌خواهید، این تیک را بردارید — برای داشتنِ صدا لازم
                  نیست.
                </p>
              )}
              {soundChanged && script.final_video && (
                <p className="mt-2 text-xs" style={{ color: "var(--warn)" }}>
                  صدای صحنه‌ها عوض شد — برای شنیدنش در ویدیو، دوباره «صداگذاری» کنید.
                </p>
              )}
            </div>
          )}

          {script.segments.length > 0 && (
            <div className="flex flex-wrap gap-2">
              {script.segments.map((segment) => (
                <SegmentQualityChip key={segment.index} segment={segment} />
              ))}
            </div>
          )}

          {script.final_video && (
            <>
              <FinalVideo script={script} voicing={voiceRunner.running} />
              {storeId && (
                <Link
                  to={`/stores/${storeId}/regen?src=script:${script.id}`}
                  className="u-btn u-btn-secondary u-btn-sm inline-flex"
                >
                  بازسازیِ یک تکه از این ویدیو
                </Link>
              )}
            </>
          )}
        </div>
      )}

      {/* Subtitles cost nothing (we wrote the narration); music is the shop's
          own file, because the licence lands on their account. */}
      {script?.id && storeId && script.final_video && (
        <div className="mt-4 space-y-4">
          {/* صدای پس‌زمینه از کتابخانهٔ «صدا»: موسیقی و صدای محیط زیرِ گوینده */}
          <VideoSoundPanel storeId={storeId} scriptId={script.id} />
          <SubtitleMusicPanel storeId={storeId} scriptId={script.id} />
          {/* بند ۲۶ — اندپوینتش ساخته بود و دکمه‌ای نداشت */}
          <RealPhotoPanel storeId={storeId} scriptId={script.id} />
          {/* بند ۱۰ — برش‌های پلتفرمی همین ویدیو، بدون رندر دوباره */}
          <CutsPanel scriptId={script.id} />
        </div>
      )}
    </Card>
  );
}

function shapeText(shape?: { width: number; height: number; fps: number }): string {
  if (!shape) return "";
  return `${shape.width}×${shape.height} · ${Math.round(shape.fps)}fps`;
}

/**
 * The finished video, sound first: the cut with music, else the voiced one,
 * else the silent picture (while the automatic voicing is still running, it
 * says so). The silent version stays one click away, not side by side —
 * the owner of script 1 watched the silent player and reported "no sound".
 */
function FinalVideo({ script, voicing }: { script: VideoScriptInfo; voicing: boolean }) {
  const best = script.final_video_music || script.final_video_voiced || script.final_video;
  const label = script.final_video_music
    ? "🎉 ویدیوی نهایی — با صدای گوینده، صدای محیط و موسیقی"
    : script.final_video_voiced
      ? "🎉 ویدیوی نهایی — با صدای گوینده و صدای محیط"
      : "🎉 ویدیوی نهایی";
  const enhance = script.finishing?.enhance;
  const silentOnly = !script.final_video_voiced && !script.final_video_music;
  return (
    <div className="space-y-2">
      <h4 className="text-sm font-bold text-slate-700">{label}</h4>
      <video
        key={best ?? ""}
        controls
        src={best ?? undefined}
        className="w-full max-w-xl rounded-lg border border-violet-300"
      />
      {enhance?.ok && enhance.before && enhance.after && (
        <p className="text-xs" style={{ color: "var(--text-2)" }}>
          کیفیت بهتر شد: {shapeText(enhance.before)} ← {shapeText(enhance.after)} (نرم‌تر،
          واضح‌تر){enhance.source_url && (
            <>
              {" — "}
              <a href={enhance.source_url} target="_blank" rel="noreferrer" className="text-violet-600 hover:underline">
                نسخه‌ی خام
              </a>
            </>
          )}
        </p>
      )}
      {silentOnly && (
        <p className="text-xs" style={{ color: "var(--warn)" }}>
          {voicing
            ? "صدای گوینده و صدای محیط در حال اضافه شدن است؛ چند دقیقه‌ی دیگر همین‌جا نسخه‌ی با صدا پخش می‌شود."
            : "این نسخه هنوز صدا ندارد — «🔊 صداگذاری» را بزنید."}
        </p>
      )}
      {script.sound_design?.voice && !silentOnly && (
        <div className="max-w-xl">
          <SoundDesignCard design={script.sound_design} />
        </div>
      )}
      {!silentOnly && (
        <details className="text-xs" style={{ color: "var(--text-2)" }}>
          <summary className="cursor-pointer">نسخه‌ی بی‌صدا</summary>
          <video
            controls
            src={script.final_video ?? undefined}
            className="mt-2 w-full max-w-md rounded-lg border border-slate-200"
          />
        </details>
      )}
    </div>
  );
}

/** One line above the player: who will read, and where to change it. */
function NarratorLine({
  voice,
  language,
  storeId,
}: {
  voice: StoreVoice;
  language: string;
  storeId?: string | number;
}) {
  const lang = language === "en" ? "en" : "fa";
  const first = voice.speakers[lang].speakers[0];
  return (
    <div
      className="mb-4 flex flex-wrap items-center gap-2 text-sm"
      style={{ color: "var(--text-2)" }}
    >
      <span>گوینده:</span>
      <b style={{ color: "var(--text)" }}>{voice.description}</b>
      {first ? (
        <span className={`u-badge u-badge-${first.local ? "ok" : "info"}`}>
          {first.processor}
        </span>
      ) : (
        <span className="u-badge u-badge-warn">
          {voice.speakers[lang].error || "گوینده‌ای آماده نیست"}
        </span>
      )}
      {storeId && (
        <Link to={`/stores/${storeId}/voice`} className="text-violet-600 hover:underline">
          تغییر صدا و تلفظ‌ها
        </Link>
      )}
    </div>
  );
}
