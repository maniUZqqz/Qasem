import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api, errorMessage } from "../../api/client";
import BeforeAfter, { Effect, Measurements } from "../../components/BeforeAfter";
import SubtitleSwitch from "../../components/SubtitleSwitch";
import ToolPicker, { ToolInfo } from "./ToolPicker";
import { useJobRunner } from "../../hooks/useJobRunner";
import {
  Alert,
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorBox,
  Input,
  PageHeader,
  SectionTitle,
  Spinner,
  fa,
} from "../../components/ui";

type Finding = { what: string; note: string; value: number };

type EditOutcome = {
  mode?: string;
  instruction?: string;
  kept?: boolean;
  improved?: boolean;
  note?: string;
  rounds?: number;
  summary?: string;
  operations?: Operation[];
  refusals?: string[];
  before?: Measurements;
  after?: Measurements;
  effects?: Effect[];
  /** Which noise remover ran, and what it measured. */
  denoise?: {
    engine: string;
    before: { snr_db?: number; noise_floor_db?: number };
    after: { snr_db?: number; noise_floor_db?: number };
    improvement_db: number | null;
    notes: string[];
  } | null;
};

type Video = {
  id: number;
  title: string;
  state: string;
  duration: number;
  has_audio: boolean;
  facts: Record<string, number | boolean | string>;
  findings: Finding[];
  video_url: string | null;
  edited_url: string | null;
  /** The last edit: plan, before/after measurements, per-tool verdicts. */
  edit_outcome?: EditOutcome | null;
  error: string;
};

type Operation = {
  tool: string;
  title: string;
  params: Record<string, number | string | boolean>;
  reason: string;
  notes: string[];
};

type Plan = {
  mode: string;
  operations: Operation[];
  refusals: string[];
  findings: Finding[];
  habits: string[];
};

type Mode = { key: string; title: string };

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
 * The editor. Ideas §8–§10.
 *
 * The screen is built around one distinction the backend enforces and the UI
 * has to make visible: **seeing the plan changes nothing.** «پیشنهادی» shows
 * what would happen and stops; only «اعمال کن» writes a frame. A button that
 * blurred those two would make the approval decorative.
 *
 * Every proposal is shown with the observation that produced it, because
 * «۱۲ سکوت طولانی پیدا شد، حذف شود؟» is a question a shop can answer and
 * «بهینه‌سازی خودکار؟» is not.
 */
export default function VideoEditorPage() {
  const { id } = useParams<{ id: string }>();
  const [videos, setVideos] = useState<Video[]>([]);
  const [modes, setModes] = useState<Mode[]>([]);
  const [habits, setHabits] = useState<string[]>([]);
  const [tools, setTools] = useState<ToolInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<Video | null>(null);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [mode, setMode] = useState("SUGGEST");
  const [instruction, setInstruction] = useState("");
  // Indexes into plan.operations, not tool names: a video with cuts can get
  // two brightness corrections (one per shot), and unticking one must not
  // untick both.
  const [dropped, setDropped] = useState<number[]>([]);
  const [subs, setSubs] = useState<Record<number, UploadSubtitles>>({});
  const [comparing, setComparing] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    try {
      const { data } = await api.get(`/stores/${id}/videos/`);
      setVideos(data.videos);
      setModes(data.modes);
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
    setBusy(true);
    setError(null);
    setNotice(null);
    const body = new FormData();
    body.append("video", file);
    body.append("title", file.name);
    try {
      const { data } = await api.post(`/stores/${id}/videos/`, body);
      setNotice("ویدیو آپلود شد؛ در حال بررسی…");
      await load();
      if (data.job_id) runner.track(data.job_id);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
      if (fileInput.current) fileInput.current.value = "";
    }
  }

  async function askForPlan(video: Video) {
    setSelected(video);
    setPlan(null);
    setDropped([]);
    setError(null);
    setBusy(true);
    try {
      const { data } = await api.post(`/stores/${id}/videos/${video.id}/plan/`, {
        mode,
        instruction,
      });
      setPlan(data);
      setHabits(data.habits);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  /** Add a tool by hand: re-plan as MANUAL with what is already on the list. */
  async function addOperation(
    video: Video,
    operation: { tool: string; params: Record<string, number | string | boolean> },
  ) {
    const kept = (plan?.operations ?? [])
      .filter((o, i) => !dropped.includes(i) && !(o.tool === operation.tool && sameWindow(o.params, operation.params)))
      .map((o) => ({ tool: o.tool, params: o.params }));
    setSelected(video);
    setError(null);
    setBusy(true);
    try {
      const { data } = await api.post(`/stores/${id}/videos/${video.id}/plan/`, {
        mode: "MANUAL",
        operations: [...kept, operation],
      });
      setPlan(data);
      setDropped([]);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function apply() {
    if (!selected || !plan) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      // Whatever the shop unticked is a refusal, and a refusal teaches the
      // editor more than an acceptance does — so it is sent before the edit,
      // not inferred from what is missing.
      if (dropped.length > 0) {
        await api.post(`/stores/${id}/videos/${selected.id}/reject/`, {
          tools: plan.operations
            .filter((_o, i) => dropped.includes(i))
            .map((o) => ({ tool: o.tool, params: o.params })),
        });
      }
      const kept = plan.operations.filter((_o, i) => !dropped.includes(i));
      const { data } = await api.post(`/stores/${id}/videos/${selected.id}/edit/`, {
        // Applying a reviewed plan is a manual edit, whatever produced it: the
        // shop looked at each line and decided. Sending the original mode would
        // record the ones they removed as accepted.
        mode: "MANUAL",
        operations: kept.map((o) => ({ tool: o.tool, params: o.params })),
      });
      runner.track(data.job_id);
      setNotice("تدوین شروع شد.");
      setPlan(null);
      setSelected(null);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

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
      const { data } = await api.get(
        `/stores/${id}/videos/${video.id}/subtitles/`,
      );
      setSubs((current) => ({ ...current, [video.id]: data }));
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  async function setSubtitleFlag(
    video: Video,
    key: "enabled" | "burned",
    next: boolean | null,
  ) {
    try {
      const { data } = await api.patch(
        `/stores/${id}/videos/${video.id}/subtitles/`,
        { [key]: next },
      );
      setSubs((current) => ({ ...current, [video.id]: data }));
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  async function buildSubtitles(video: Video) {
    setBusy(true);
    setError(null);
    try {
      const { data } = await api.post(
        `/stores/${id}/videos/${video.id}/subtitles/`,
      );
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
      if (selected?.id === video.id) {
        setSelected(null);
        setPlan(null);
      }
      await load();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  if (loading) return <Spinner />;

  return (
    <>
      <PageHeader
        title="تدوین ویدیو"
        subtitle="ویدیوی خودتان را بدهید — سکوت، نور، رنگ و لرزش را درست می‌کنیم"
        actions={
          <Link to={`/stores/${id}`}>
            <Button variant="secondary">بازگشت</Button>
          </Link>
        }
      />

      <ErrorBox message={error} />
      {notice && (
        <div className="mb-4">
          <Alert tone="ok">{notice}</Alert>
        </div>
      )}

      <Card>
        <SectionTitle>ویدیوی تازه</SectionTitle>
        <input
          ref={fileInput}
          type="file"
          accept="video/*"
          className="block w-full text-sm"
          disabled={busy}
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) upload(file);
          }}
        />
        <p className="mt-2 text-xs" style={{ color: "var(--text-3)" }}>
          فیلم موبایل هم مشکلی ندارد. حداکثر ۵۰۰ مگابایت.
        </p>
        {runner.running && (
          <div className="mt-3 flex items-center gap-2">
            <Spinner size={18} />
            <span className="text-sm" style={{ color: "var(--text-2)" }}>
              {runner.job?.current_step_label || "در حال کار…"}
            </span>
          </div>
        )}
        <ErrorBox message={runner.error} />
      </Card>

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
          <div className="flex flex-col gap-3">
            {videos.map((video) => {
              const state = STATE[video.state] ?? { label: video.state, tone: "info" as const };
              return (
                <Card key={video.id}>
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0 flex-1">
                      <div className="mb-1 flex flex-wrap items-center gap-2">
                        <span className="font-bold" style={{ color: "var(--text)" }}>
                          {video.title}
                        </span>
                        <Badge tone={state.tone}>{state.label}</Badge>
                        {video.duration > 0 && (
                          <Badge tone="neutral">{fa(Math.round(video.duration))} ثانیه</Badge>
                        )}
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
                              <Badge tone={finding.what === "no_speech" ? "bad" : "warn"}>
                                {finding.note}
                              </Badge>
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
                      {video.edited_url && video.video_url && (
                        <Button
                          variant={comparing === video.id ? "primary" : "secondary"}
                          onClick={() =>
                            setComparing((current) => (current === video.id ? null : video.id))
                          }
                        >
                          {comparing === video.id ? "بستن مقایسه" : "قبل و بعد"}
                        </Button>
                      )}
                      {video.edited_url && (
                        <a href={video.edited_url} target="_blank" rel="noreferrer">
                          <Button variant="secondary">دانلود نسخه‌ی تدوین‌شده</Button>
                        </a>
                      )}
                      <Button
                        onClick={() => askForPlan(video)}
                        disabled={busy || !video.facts || video.state === "FAILED"}
                      >
                        ببین چه کار می‌کند
                      </Button>
                      <Button
                        variant="secondary"
                        onClick={() => repurpose(video)}
                        disabled={busy || video.state === "FAILED"}
                      >
                        ۵ قالب انتشار
                      </Button>
                      <Link
                        to={`/stores/${id}/regen?src=upload:${video.id}${video.edited_url ? ":edited" : ""}`}
                        className="u-btn u-btn-secondary"
                      >
                        بازسازیِ یک تکه
                      </Link>
                      <Button
                        variant="secondary"
                        onClick={() => loadSubtitles(video)}
                        disabled={busy || video.state === "FAILED"}
                      >
                        زیرنویس
                      </Button>
                      <Button variant="ghost" onClick={() => remove(video)}>
                        حذف
                      </Button>
                    </div>
                  </div>

                  {comparing === video.id && video.edited_url && video.video_url && (
                    <div className="mt-3">
                      <BeforeAfter
                        beforeUrl={video.video_url}
                        afterUrl={video.edited_url}
                        before={video.edit_outcome?.before ?? (video.facts as Measurements)}
                        after={video.edit_outcome?.after}
                        effects={video.edit_outcome?.effects ?? []}
                        note={video.edit_outcome?.note}
                        improved={video.edit_outcome?.improved ?? null}
                        summary={video.edit_outcome?.summary}
                      />
                      {video.edit_outcome?.denoise && (
                        <p className="mt-2 text-xs" style={{ color: "var(--text-2)" }}>
                          🎧 حذف نویز با {video.edit_outcome.denoise.engine}
                          {typeof video.edit_outcome.denoise.before?.snr_db === "number" &&
                            typeof video.edit_outcome.denoise.after?.snr_db === "number" && (
                              <>
                                {" "}— فاصله‌ی صدا از نویز{" "}
                                {fa(Math.round(video.edit_outcome.denoise.before.snr_db))} ←{" "}
                                {fa(Math.round(video.edit_outcome.denoise.after.snr_db))} دسی‌بل
                              </>
                            )}
                          {video.edit_outcome.denoise.notes.map((note) => (
                            <span key={note} className="block" style={{ color: "var(--warn)" }}>
                              {note}
                            </span>
                          ))}
                        </p>
                      )}
                      {video.edit_outcome?.operations && video.edit_outcome.operations.length > 0 && (
                        <p className="mt-2 text-xs" style={{ color: "var(--text-3)" }}>
                          کارهایی که انجام شد:{" "}
                          {video.edit_outcome.operations.map((o) => o.title).join("، ")}
                          {video.edit_outcome.mode === "DIRECTED" && video.edit_outcome.instruction
                            ? ` — با دستور «${video.edit_outcome.instruction}»`
                            : ""}
                        </p>
                      )}
                    </div>
                  )}

                  {subs[video.id] && (
                    <div
                      className="mt-3 flex flex-col gap-2 border-t pt-3"
                      style={{ borderColor: "var(--line)" }}
                    >
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
                            <Button
                              onClick={() => buildSubtitles(video)}
                              disabled={busy || !subs[video.id].effective_enabled}
                            >
                              بساز
                            </Button>
                            {subs[video.id].url && (
                              <a href={subs[video.id].url!} download>
                                <Button variant="secondary">دانلود SRT</Button>
                              </a>
                            )}
                            {subs[video.id].uncertain > 0 && (
                              <Badge tone="warn">
                                {fa(subs[video.id].uncertain)} خط نامطمئن — نگاهشان کنید
                              </Badge>
                            )}
                          </div>
                          <p className="text-xs" style={{ color: "var(--text-3)" }}>
                            این ویدیو را خودتان گرفته‌اید، پس برای زیرنویسش به آن
                            گوش داده می‌شود. خط‌هایی که مطمئن نبودیم علامت می‌خورند.
                          </p>
                        </>
                      )}
                    </div>
                  )}

                  {selected?.id === video.id && (
                    <div
                      className="mt-4 border-t pt-4"
                      style={{ borderColor: "var(--line)" }}
                    >
                      <div className="mb-3 flex flex-wrap items-end gap-2">
                        {modes.map((m) => (
                          <Button
                            key={m.key}
                            variant={mode === m.key ? "primary" : "secondary"}
                            onClick={() => setMode(m.key)}
                          >
                            {m.title.split(" —")[0]}
                          </Button>
                        ))}
                      </div>

                      {mode === "DIRECTED" && (
                        <div className="mb-3 flex flex-wrap items-end gap-2">
                          <div className="min-w-[16rem] flex-1">
                            <Input
                              value={instruction}
                              onChange={(e) => setInstruction(e.target.value)}
                              placeholder="مثلاً: مثل یک یوتیوبر حرفه‌ای، ساده و بدون افکت زیاد"
                            />
                          </div>
                          <Button onClick={() => askForPlan(video)} disabled={busy}>
                            بپرس
                          </Button>
                        </div>
                      )}

                      {busy && !plan && <Spinner size={18} />}

                      {plan && (
                        <>
                          {plan.operations.length === 0 ? (
                            plan.mode === "MANUAL" ? (
                              <Alert tone="info">
                                هنوز کاری انتخاب نکرده‌اید — از پایین ابزار اضافه کنید.
                              </Alert>
                            ) : (
                              <Alert tone="ok">
                                چیزی برای اصلاح پیدا نشد — این ویدیو همین‌طوری خوب است.
                              </Alert>
                            )
                          ) : (
                            <>
                              <p className="mb-2 text-sm" style={{ color: "var(--text-2)" }}>
                                این کارها انجام می‌شود. هرکدام را نمی‌خواهید بردارید:
                              </p>
                              <div className="flex flex-col gap-2">
                                {plan.operations.map((operation, index) => {
                                  const off = dropped.includes(index);
                                  return (
                                    <label
                                      key={`${operation.tool}-${index}`}
                                      className="flex cursor-pointer items-start gap-3 rounded-xl p-3"
                                      style={{
                                        border: "1px solid var(--line)",
                                        opacity: off ? 0.5 : 1,
                                      }}
                                    >
                                      <input
                                        type="checkbox"
                                        checked={!off}
                                        className="mt-1"
                                        onChange={() =>
                                          setDropped((current) =>
                                            off
                                              ? current.filter((t) => t !== index)
                                              : [...current, index],
                                          )
                                        }
                                      />
                                      <div className="min-w-0 flex-1">
                                        <span
                                          className="font-bold"
                                          style={{ color: "var(--text)" }}
                                        >
                                          {operation.title}
                                        </span>
                                        <p
                                          className="text-sm"
                                          style={{ color: "var(--text-2)" }}
                                        >
                                          {operation.reason}
                                        </p>
                                        {operation.notes.map((note) => (
                                          <p
                                            key={note}
                                            className="text-xs"
                                            style={{ color: "var(--warn)" }}
                                          >
                                            {note}
                                          </p>
                                        ))}
                                      </div>
                                    </label>
                                  );
                                })}
                              </div>

                              <div className="mt-3 flex flex-wrap gap-2">
                                <Button
                                  onClick={apply}
                                  disabled={
                                    busy || plan.operations.length === dropped.length
                                  }
                                >
                                  اعمال کن
                                </Button>
                                <Button
                                  variant="ghost"
                                  onClick={() => {
                                    setPlan(null);
                                    setSelected(null);
                                  }}
                                >
                                  بی‌خیال
                                </Button>
                              </div>
                            </>
                          )}

                          {plan.refusals.length > 0 && (
                            <div className="mt-3">
                              <Alert tone="warn" title="این‌ها انجام نمی‌شود">
                                <ul className="list-inside list-disc">
                                  {plan.refusals.map((refusal) => (
                                    <li key={refusal}>{refusal}</li>
                                  ))}
                                </ul>
                              </Alert>
                            </div>
                          )}

                          {video.has_audio && (
                            <div className="mt-3 flex flex-wrap items-center gap-2">
                              {!plan.operations.some((o) => o.tool === "denoise_audio") && (
                                <Button
                                  size="sm"
                                  variant="secondary"
                                  disabled={busy}
                                  onClick={() =>
                                    void addOperation(video, {
                                      tool: "denoise_audio",
                                      params: { amount: denoiseAmount(video) },
                                    })
                                  }
                                >
                                  🎧 حذف نویز صدا
                                </Button>
                              )}
                              {!plan.operations.some((o) => o.tool === "normalize_audio") && (
                                <Button
                                  size="sm"
                                  variant="secondary"
                                  disabled={busy}
                                  onClick={() =>
                                    void addOperation(video, {
                                      tool: "normalize_audio",
                                      params: { target: -16 },
                                    })
                                  }
                                >
                                  🔊 یکسان‌کردن بلندی صدا
                                </Button>
                              )}
                              {typeof video.facts.snr_db === "number" && (
                                <span className="text-xs" style={{ color: "var(--text-3)" }}>
                                  صدای شما {fa(Math.round(video.facts.snr_db as number))} دسی‌بل از
                                  نویز پشتش بلندتر است
                                  {(video.facts.snr_db as number) >= 30 ? " — تمیز است." : "."}
                                </span>
                              )}
                            </div>
                          )}

                          {tools.length > 0 && (
                            <ToolPicker
                              tools={tools}
                              hasAudio={video.has_audio}
                              busy={busy}
                              onAdd={(operation) => void addOperation(video, operation)}
                            />
                          )}
                        </>
                      )}
                    </div>
                  )}
                </Card>
              );
            })}
          </div>
        )}
      </div>
    </>
  );
}

/** The editor agent's own choice of strength (services/editing/agent.py
 *  `suggest`), from how noisy the recording measured. */
function denoiseAmount(video: Video): number {
  const snr = Number(video.facts.snr_db);
  if (!Number.isFinite(snr) || snr >= 15) return 12;
  return snr >= 8 ? 16 : 20;
}

/** Same time window (or both whole-clip): a manual tool replaces only that. */
function sameWindow(
  a: Record<string, number | string | boolean>,
  b: Record<string, number | string | boolean>,
): boolean {
  const start = (p: Record<string, number | string | boolean>) => Number(p.from_s ?? -1);
  const end = (p: Record<string, number | string | boolean>) => Number(p.to_s ?? -1);
  return start(a) === start(b) && end(a) === end(b);
}
