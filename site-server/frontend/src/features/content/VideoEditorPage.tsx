import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { api, errorMessage } from "../../api/client";
import ModeSwitch, { useEditorMode } from "../../components/ModeSwitch";
import SubtitleSwitch from "../../components/SubtitleSwitch";
import { ToolInfo } from "./ToolPicker";
import { useJobRunner } from "../../hooks/useJobRunner";
import {
  Alert,
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorBox,
  PageHeader,
  SectionTitle,
  Spinner,
  fa,
} from "../../components/ui";
import type { EditableOp } from "./video/api";
import type { Video } from "./video/types";
import VideoWorkspace from "./video/manual/VideoWorkspace";
import { EditResult, VideoAutoBlock, VideoPromptBlock } from "./video/VideoModes";
import VideoDirector from "./video/director/VideoDirector";
import { UploadProgress, useVideoUpload } from "./video/useVideoUpload";

type UploadSubtitles = {
  url: string | null;
  possible: boolean;
  reason: string;
  /** null = follow the shop default. See SubtitleSwitch for why three states. */
  enabled: boolean | null;
  burned: boolean | null;
  effective_enabled: boolean;
  effective_burned: boolean;
  lines: number;
  /** Lines Whisper was unsure about. A shop can fix a word we got wrong; they
   *  cannot fix a line we quietly dropped. */
  uncertain: number;
};

const STATE: Record<string, { label: string; tone: "ok" | "warn" | "bad" | "info" }> = {
  UPLOADED: { label: "آپلود شد", tone: "info" },
  ANALYZING: { label: "در حال بررسی", tone: "info" },
  READY: { label: "آماده‌ی تدوین", tone: "ok" },
  EDITED: { label: "تدوین شد", tone: "ok" },
  FAILED: { label: "خطا", tone: "bad" },
};

/**
 * ادیتورِ ویدیو — سه حالت:
 *   خودکار     : یک کلیک؛ می‌سنجد ← تصمیم می‌گیرد ← اعمال می‌کند ← دوباره می‌سنجد و داوری می‌کند.
 *                «اول نشانم بده» = همان حالتِ پیشنهادی (SUGGEST) که قبلاً بود.
 *   نیمه‌خودکار : دستور (کارگردانی/DIRECTED)؛ اول Qwen روی سرورِ پردازش، بعد پشتیبان؛ مراحلش قابل‌ویرایش.
 *   دستی       : فضای کارِ پریمیرمانند (تایم‌لاین، سطلِ رسانه، مانیتور، پنلِ افکت‌ها، خروجی).
 *
 * یک قاعده‌ای که بک‌اند اجرا می‌کند و این صفحه نشانش می‌دهد: **دیدنِ طرح چیزی را عوض نمی‌کند.**
 * فقط «اعمال کن» یک فریم می‌نویسد.
 */
export default function VideoEditorPage() {
  const { id } = useParams<{ id: string }>();
  const [mode, setMode] = useEditorMode("nm.video.mode");
  const [videos, setVideos] = useState<Video[]>([]);
  const [habits, setHabits] = useState<string[]>([]);
  const [tools, setTools] = useState<ToolInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [subs, setSubs] = useState<Record<number, UploadSubtitles>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [manualStart, setManualStart] = useState<string | null>(null);
  /** پروژه‌ای که «کارگردان» ساخته و باید در فضای دستی باز شود */
  const [manualProject, setManualProject] = useState<number | null>(null);
  // ?project=<شناسه> (از صفحهٔ «چندزاویه» و مانندش): همان پروژه در فضای «دستی» باز می‌شود
  const [searchParams, setSearchParams] = useSearchParams();
  useEffect(() => {
    const wanted = Number(searchParams.get("project"));
    if (wanted > 0) {
      setManualProject(wanted);
      setMode("manual");
      setSearchParams({}, { replace: true });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const fileInput = useRef<HTMLInputElement>(null);
  const up = useVideoUpload<Video>(id!);

  const load = useCallback(async () => {
    try {
      const { data } = await api.get(`/stores/${id}/videos/`);
      setVideos(data.videos);
      setHabits(data.habits);
      setTools(data.tools ?? []);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }, [id]);

  // The runner reloads the list when a job finishes, which is the only place
  // the new measurements or the edited file can come from.
  const runner = useJobRunner(load);

  useEffect(() => {
    load();
  }, [load]);

  async function upload(file: File) {
    setError(null);
    setNotice(null);
    const res = await up.start(file);
    if (fileInput.current) fileInput.current.value = "";
    if (!res) return;
    setBusy(true);
    try {
      setNotice("ویدیو آپلود شد؛ در حال بررسی…");
      await load();
      const jobId = (res as { job_id?: number | null }).job_id;
      if (jobId) runner.track(jobId);
    } finally {
      setBusy(false);
    }
  }

  /** تدوین را شروع کن. operations = null ⇐ خودِ سرور تصمیم می‌گیرد (AUTO)؛ وگرنه فهرستِ تأییدشده (MANUAL). */
  const startEdit = useCallback(
    async (video: Video, editMode: string, operations: EditableOp[] | null) => {
      setBusy(true);
      setError(null);
      setNotice(null);
      try {
        const body: Record<string, unknown> = { mode: editMode };
        // Applying a reviewed plan is a manual edit, whatever produced it: the shop looked at each line and
        // decided. Sending the original mode would record the ones they removed as accepted.
        if (operations) body.operations = operations.filter((o) => o.on).map((o) => ({ tool: o.tool, params: o.params }));
        const { data } = await api.post(`/stores/${id}/videos/${video.id}/edit/`, body);
        runner.begin();
        runner.track(data.job_id);
        setNotice("تدوین شروع شد.");
      } catch (err) {
        setError(errorMessage(err));
      } finally {
        setBusy(false);
      }
    },
    [id, runner],
  );

  async function repurpose(video: Video) {
    setBusy(true);
    setError(null);
    try {
      const { data } = await api.post(`/stores/${id}/videos/${video.id}/repurpose/`);
      runner.track(data.job_id);
      setNotice("ساخت نسخه‌های مختلف شروع شد.");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function loadSubtitles(video: Video) {
    try {
      const { data } = await api.get(`/stores/${id}/videos/${video.id}/subtitles/`);
      setSubs((current) => ({ ...current, [video.id]: data }));
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  async function setSubtitleFlag(video: Video, key: "enabled" | "burned", next: boolean | null) {
    try {
      const { data } = await api.patch(`/stores/${id}/videos/${video.id}/subtitles/`, { [key]: next });
      setSubs((current) => ({ ...current, [video.id]: data }));
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  async function buildSubtitles(video: Video) {
    setBusy(true);
    setError(null);
    try {
      const { data } = await api.post(`/stores/${id}/videos/${video.id}/subtitles/`);
      runner.track(data.job_id);
      setNotice("زیرنویس در حال ساخت است — ویدیو گوش داده می‌شود.");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function remove(video: Video) {
    if (!window.confirm(`«${video.title}» حذف شود؟`)) return;
    try {
      await api.delete(`/stores/${id}/videos/${video.id}/`);
      await load();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  if (loading) return <Spinner />;
  const running = runner.running || busy;

  return (
    <>
      <PageHeader
        title="تدوین ویدیو"
        subtitle="ویدیوی خودتان را بدهید — خودکار، با یک دستور (کارگردان)، یا خودتان مثلِ پریمیر تدوینش کنید"
        actions={
          <>
            <Link to={`/stores/${id}/photo-editor`}>
              <Button variant="secondary">ادیتور عکس</Button>
            </Link>
            <Link to={`/stores/${id}`}>
              <Button variant="secondary">بازگشت</Button>
            </Link>
          </>
        }
      />

      <ErrorBox message={error} />
      {notice && (
        <div className="mb-4">
          <Alert tone="ok">{notice}</Alert>
        </div>
      )}

      <ModeSwitch
        mode={mode}
        onChange={setMode}
        hints={{
          auto: "می‌سنجد، خودش تدوین می‌کند و داوری می‌کند — یک کلیک",
          prompt: "بگویید چطور تدوین شود؛ هوش مصنوعی مرحله‌ها را می‌چیند",
          manual: "فضای کامل مثلِ پریمیر: تایم‌لاین، ترک‌ها، افکت‌ها",
        }}
      />

      {mode === "manual" && (
        <div className="mb-6">
          <VideoWorkspace storeId={id!} tools={tools} startRef={manualStart} onStartConsumed={() => setManualStart(null)} startProject={manualProject} onProjectOpened={() => setManualProject(null)} onGoDirector={() => setMode("prompt")} />
        </div>
      )}

      <Card>
        <SectionTitle>ویدیوی تازه</SectionTitle>
        <input
          ref={fileInput}
          type="file"
          accept="video/*"
          className="block w-full text-sm"
          disabled={busy || up.active}
          data-testid="video-upload"
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) upload(file);
          }}
        />
        <p className="mt-2 text-xs" style={{ color: "var(--text-3)" }}>
          فیلم موبایل هم مشکلی ندارد. حداکثر ۵۰۰ مگابایت. اگر اینترنت کند یا قطع شد، آپلود تکه‌تکه می‌رود و خودکار ادامه می‌دهد؛ اگر صفحه بسته شد همان فایل را دوباره انتخاب کنید تا از همان‌جا ادامه یابد.
        </p>
        <UploadProgress up={up as never} />
        {runner.running && (
          <div className="mt-3 flex items-center gap-2" data-testid="job-progress">
            <Spinner size={18} />
            <span className="text-sm" style={{ color: "var(--text-2)" }}>
              {runner.job?.current_step_label || "در حال کار…"}
            </span>
          </div>
        )}
        <ErrorBox message={runner.error} />
      </Card>

      {mode === "prompt" && (
        <div className="mt-4">
          <VideoDirector storeId={id!} onOpenProject={(pid) => { setManualProject(pid); setMode("manual"); window.scrollTo({ top: 0, behavior: "smooth" }); }} />
        </div>
      )}

      {habits.length > 0 && (
        <div className="mt-4">
          <Alert tone="brand" title="چیزهایی که از شما یاد گرفته‌ایم">
            <ul className="list-inside list-disc">
              {habits.map((habit) => (
                <li key={habit}>{habit}</li>
              ))}
            </ul>
          </Alert>
        </div>
      )}

      <div className="mt-6">
        <SectionTitle>ویدیوهای شما</SectionTitle>
        {videos.length === 0 ? (
          <Card>
            <EmptyState
              icon="film"
              title="هنوز ویدیویی آپلود نکرده‌اید"
              description="یک فیلم از محصولتان بگیرید و اینجا بگذارید تا تدوینش کنیم."
            />
          </Card>
        ) : (
          <div className="flex flex-col gap-3" data-testid="video-list">
            {videos.map((video) => {
              const state = STATE[video.state] ?? { label: video.state, tone: "info" as const };
              return (
                <Card key={video.id}>
                  <div data-video={video.id}>
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div className="min-w-0 flex-1">
                        <div className="mb-1 flex flex-wrap items-center gap-2">
                          <span className="font-bold" style={{ color: "var(--text)" }}>
                            {video.title}
                          </span>
                          <Badge tone={state.tone}>{state.label}</Badge>
                          {video.duration > 0 && <Badge tone="neutral">{fa(Math.round(video.duration))} ثانیه</Badge>}
                          {!video.has_audio && <Badge tone="warn">بدون صدا</Badge>}
                        </div>

                        {video.error && (
                          <p className="text-sm" style={{ color: "var(--bad)" }}>
                            {video.error}
                          </p>
                        )}

                        {video.findings.length > 0 ? (
                          <ul className="mt-1 flex flex-wrap gap-2 text-xs">
                            {video.findings.map((finding) => (
                              <li key={`${finding.what}-${finding.note}`}>
                                <Badge tone={finding.what === "no_speech" ? "bad" : "warn"}>{finding.note}</Badge>
                              </li>
                            ))}
                          </ul>
                        ) : (
                          video.state === "READY" && (
                            <p className="text-sm" style={{ color: "var(--text-3)" }}>
                              چیز خاصی برای اصلاح پیدا نشد.
                            </p>
                          )
                        )}
                      </div>

                      <div className="flex flex-wrap gap-2">
                        {video.edited_url && (
                          <a href={video.edited_url} target="_blank" rel="noreferrer">
                            <Button variant="secondary">دانلود نسخه‌ی تدوین‌شده</Button>
                          </a>
                        )}
                        <Button
                          variant="secondary"
                          disabled={video.state === "FAILED"}
                          onClick={() => {
                            setManualStart(`video:${video.id}`);
                            setMode("manual");
                            window.scrollTo({ top: 0, behavior: "smooth" });
                          }}
                          data-testid="open-manual"
                        >
                          ویرایشِ دستی
                        </Button>
                        <Button variant="secondary" onClick={() => repurpose(video)} disabled={busy || video.state === "FAILED"}>
                          ۵ قالب انتشار
                        </Button>
                        <Link to={`/stores/${id}/regen?src=upload:${video.id}${video.edited_url ? ":edited" : ""}`} className="u-btn u-btn-secondary">
                          بازسازیِ یک تکه
                        </Link>
                        <Button variant="secondary" onClick={() => loadSubtitles(video)} disabled={busy || video.state === "FAILED"}>
                          زیرنویس
                        </Button>
                        <Button variant="ghost" onClick={() => remove(video)}>
                          حذف
                        </Button>
                      </div>
                    </div>

                    {subs[video.id] && (
                      <div className="mt-3 flex flex-col gap-2 border-t pt-3" style={{ borderColor: "var(--line)" }}>
                        {!subs[video.id].possible ? (
                          <Alert tone="neutral">{subs[video.id].reason}</Alert>
                        ) : (
                          <>
                            <SubtitleSwitch
                              label="زیرنویس"
                              value={subs[video.id].enabled}
                              effective={subs[video.id].effective_enabled}
                              onChange={(next) => setSubtitleFlag(video, "enabled", next)}
                              disabled={busy}
                            />
                            <SubtitleSwitch
                              label="روی تصویر بسوزد"
                              value={subs[video.id].burned}
                              effective={subs[video.id].effective_burned}
                              onChange={(next) => setSubtitleFlag(video, "burned", next)}
                              disabled={busy}
                            />
                            <div className="flex flex-wrap items-center gap-2">
                              <Button onClick={() => buildSubtitles(video)} disabled={busy || !subs[video.id].effective_enabled}>
                                بساز
                              </Button>
                              {subs[video.id].url && (
                                <a href={subs[video.id].url!} download>
                                  <Button variant="secondary">دانلود SRT</Button>
                                </a>
                              )}
                              {subs[video.id].uncertain > 0 && (
                                <Badge tone="warn">{fa(subs[video.id].uncertain)} خط نامطمئن — نگاهشان کنید</Badge>
                              )}
                            </div>
                            <p className="text-xs" style={{ color: "var(--text-3)" }}>
                              این ویدیو را خودتان گرفته‌اید، پس برای زیرنویسش به آن گوش داده می‌شود. خط‌هایی که مطمئن نبودیم علامت می‌خورند.
                            </p>
                          </>
                        )}
                      </div>
                    )}

                    {mode === "auto" && (
                      <VideoAutoBlock storeId={id!} video={video} tools={tools} busy={running} start={startEdit} setError={setError} />
                    )}
                    {mode === "prompt" && (
                      <VideoPromptBlock storeId={id!} video={video} tools={tools} busy={running} start={startEdit} setError={setError} />
                    )}
                    {mode === "manual" && <EditResult video={video} tools={tools} busy={running} start={startEdit} />}
                  </div>
                </Card>
              );
            })}
          </div>
        )}
      </div>
    </>
  );
}
