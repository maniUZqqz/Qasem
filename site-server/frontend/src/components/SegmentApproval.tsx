import { useState } from "react";

import { api, errorMessage } from "../api/client";
import { Job } from "../types";
import BeforeAfter from "./BeforeAfter";
import { Alert, Badge, Button } from "./ui";

/**
 * The five seconds the owner is asked to look at, and the answers.
 *
 * The backend stops a video render after each segment and waits here. Until
 * this component existed that pause was invisible: the job sat in
 * WAITING_APPROVAL, the panel showed a spinner forever, and the one feature
 * that keeps forty seconds of GPU from being wasted did nothing for anyone.
 *
 * Three different answers, three different words. **Approve** continues.
 * **Regenerate** says this one piece is wrong — make it again, with the prompt
 * steered around what went wrong, and leave the finished pieces alone; the
 * rejected render is refunded and counted against the quality guarantee.
 * **Stop** says the whole video is wrong. Before regenerate existed the only
 * way to reject one clip was to cancel everything, or to approve a clip whose
 * last frame then anchored every clip after it.
 *
 * What quality control found sits next to the clip, because «قابل بررسی · ۷۴»
 * is a number and «کلیپ ۱.۶ ثانیه بی‌حرکت می‌ماند» is a reason.
 */

const CAUSES: { key: string; label: string }[] = [
  { key: "OBJECT", label: "محصول عوض شده" },
  { key: "CHARACTER", label: "چهره یا آدم عوض شده" },
  { key: "ANATOMY", label: "دست یا اندام خراب است" },
  { key: "ARTIFACTS", label: "خرابی تصویری" },
  { key: "MOTION", label: "حرکت یا پرش بد" },
  { key: "TALKING", label: "آدم لب می‌زند (صدا گوینده است)" },
  { key: "OTHER", label: "چیز دیگر" },
];

const VERDICT_LABEL: Record<string, { label: string; tone: "ok" | "warn" | "bad" }> = {
  EXCELLENT: { label: "عالی", tone: "ok" },
  GOOD: { label: "خوب", tone: "ok" },
  REVIEW: { label: "قابل بررسی", tone: "warn" },
  REGENERATE: { label: "ضعیف", tone: "bad" },
};

export default function SegmentApproval({
  job,
  onResumed,
  onStopped,
}: {
  job: Job;
  onResumed: (job: Job) => void;
  onStopped: () => void;
}) {
  const [busy, setBusy] = useState<"approve" | "reject" | "auto" | "regenerate" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refunded, setRefunded] = useState<number | null>(null);
  const [causes, setCauses] = useState<string[]>([]);
  const [askingWhy, setAskingWhy] = useState(false);
  const [compare, setCompare] = useState(false);

  const preview = job.preview ?? {};
  const quality = preview.quality;
  const done = preview.segments_done ?? preview.segment_index ?? 1;
  const total = preview.segments_total ?? 0;
  const remaining = Math.max(0, total - done);
  const verdict = quality?.verdict ? VERDICT_LABEL[quality.verdict] : null;

  async function approve() {
    setBusy("approve");
    setError(null);
    try {
      const { data } = await api.post<Job>(`/jobs/${job.id}/approve/`);
      onResumed(data);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(null);
    }
  }

  async function continueWithoutAsking() {
    setBusy("auto");
    setError(null);
    try {
      await api.patch(`/jobs/${job.id}/mode/`, { mode: "AUTO" });
      const { data } = await api.post<Job>(`/jobs/${job.id}/approve/`);
      onResumed(data);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(null);
    }
  }

  async function regenerate() {
    setBusy("regenerate");
    setError(null);
    try {
      const { data } = await api.post<{ job: Job; message: string }>(
        `/jobs/${job.id}/regenerate/`,
        {
          reason: causes.length
            ? CAUSES.filter((c) => causes.includes(c.key)).map((c) => c.label).join("، ")
            : "فروشگاه‌دار قطعه را نپسندید",
          causes,
        },
      );
      setAskingWhy(false);
      onResumed(data.job);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(null);
    }
  }

  async function reject() {
    setBusy("reject");
    setError(null);
    try {
      const { data } = await api.post<{ refunded: number }>(`/jobs/${job.id}/reject/`, {
        reason: "فروشگاه‌دار قطعه را نپسندید",
      });
      setRefunded(data.refunded ?? 0);
      onStopped();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(null);
    }
  }

  if (refunded !== null) {
    return (
      <Alert tone="ok" title="ساخت ویدیو متوقف شد">
        {refunded > 0
          ? `${refunded} ثانیه اعتبار برگشت. می‌توانید با سناریوی دیگری دوباره شروع کنید.`
          : "اعتباری مصرف نشده بود. می‌توانید با سناریوی دیگری دوباره شروع کنید."}
      </Alert>
    );
  }

  return (
    <div
      className="mb-4 flex flex-col gap-3 rounded-xl p-4"
      style={{
        background: "var(--warn-soft, var(--surface-2))",
        border: "1px solid color-mix(in srgb, var(--warn) 35%, transparent)",
      }}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="text-sm font-bold" style={{ color: "var(--text)" }}>
          {job.current_step_label || `قطعه‌ی ${done} آماده است — نگاهی بیندازید`}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {verdict && quality?.overall != null && (
            <Badge tone={verdict.tone}>
              کیفیت: {verdict.label} · {Math.round(quality.overall)}
            </Badge>
          )}
          <Badge tone="warn">{total ? `${done} از ${total}` : `قطعه ${done}`}</Badge>
        </div>
      </div>

      {compare && quality?.original_video && preview.video ? (
        <BeforeAfter
          beforeUrl={quality.original_video}
          afterUrl={preview.video}
          beforeLabel="رندر خام"
          afterLabel="بعد از اصلاح با کد"
          compact
        />
      ) : preview.video ? (
        <video
          src={preview.video}
          controls
          playsInline
          className="w-full rounded-lg"
          style={{ maxHeight: 360, background: "#000" }}
        />
      ) : (
        <p className="text-sm" style={{ color: "var(--text-2)" }}>
          فایل پیش‌نمایش در دسترس نیست، ولی قطعه ساخته شده است.
        </p>
      )}

      {quality && (
        <div className="flex flex-col gap-1 text-xs" style={{ color: "var(--text-2)" }}>
          {(quality.problems ?? []).map((axis) => (
            <div key={axis.name}>
              ⚠ {axis.note || `${axis.name}: ${Math.round(axis.score)}`}
            </div>
          ))}
          {quality.repaired && quality.repaired.length > 0 && (
            <div className="flex flex-wrap items-center gap-2">
              <span>🔧 {quality.repaired.length} مشکل با کد اصلاح شد — بدون مصرف GPU.</span>
              {quality.original_video && (
                <Button variant="ghost" onClick={() => setCompare((c) => !c)}>
                  {compare ? "فقط نسخه‌ی نهایی" : "قبل و بعد را ببین"}
                </Button>
              )}
            </div>
          )}
          {quality.attempts && quality.attempts > 1 && (
            <div>🔁 این قطعه {quality.attempts} بار ساخته شد و بهترین نسخه نگه داشته شده است.</div>
          )}
          {quality.vision_checked === false && (
            <div style={{ color: "var(--text-3)" }}>
              فقط بررسی کد انجام شد — مدل بینایی در دسترس نبود
              {quality.vision_reason ? ` (${quality.vision_reason})` : ""}. محصول و چهره را خودتان چک کنید.
            </div>
          )}
        </div>
      )}

      <p className="text-sm leading-7" style={{ color: "var(--text-2)" }}>
        {remaining > 0 ? (
          <>
            تا اینجا فقط همین {done} قطعه رندر شده و بابت همین حساب شده‌اید.{" "}
            <b style={{ color: "var(--text)" }}>{remaining} قطعه‌ی بعدی هنوز GPU مصرف نکرده.</b>{" "}
            اگر این یکی درست نیست، دوباره بسازیدش یا متوقفش کنید.
          </>
        ) : (
          <>این آخرین قطعه است. با تأیید، ویدیوی نهایی چسبانده می‌شود.</>
        )}
      </p>

      {error && <Alert tone="bad">{error}</Alert>}

      {askingWhy ? (
        <div className="flex flex-col gap-2">
          <p className="text-sm" style={{ color: "var(--text)" }}>
            چه چیزی خراب است؟ (اختیاری — به مدل می‌گوییم دفعه‌ی بعد از آن پرهیز کند)
          </p>
          <div className="flex flex-wrap gap-2">
            {CAUSES.map((cause) => {
              const on = causes.includes(cause.key);
              return (
                <Button
                  key={cause.key}
                  variant={on ? "primary" : "secondary"}
                  onClick={() =>
                    setCauses((current) =>
                      on ? current.filter((k) => k !== cause.key) : [...current, cause.key],
                    )
                  }
                >
                  {cause.label}
                </Button>
              );
            })}
          </div>
          <div className="flex flex-wrap gap-2">
            <Button onClick={regenerate} disabled={busy !== null}>
              {busy === "regenerate" ? "…" : "دوباره بساز"}
            </Button>
            <Button variant="ghost" onClick={() => setAskingWhy(false)} disabled={busy !== null}>
              برگرد
            </Button>
          </div>
        </div>
      ) : (
        <div className="flex flex-wrap gap-2">
          <Button onClick={approve} disabled={busy !== null}>
            {busy === "approve" ? "…" : "خوب است، ادامه بده"}
          </Button>
          {remaining > 1 && (
            <Button variant="secondary" onClick={continueWithoutAsking} disabled={busy !== null}>
              {busy === "auto" ? "…" : "تا آخر برو و دیگر نپرس"}
            </Button>
          )}
          <Button variant="secondary" onClick={() => setAskingWhy(true)} disabled={busy !== null}>
            خوب نیست، دوباره بساز
          </Button>
          <Button variant="danger" onClick={reject} disabled={busy !== null}>
            {busy === "reject" ? "…" : "متوقف کن"}
          </Button>
        </div>
      )}

      <p className="text-xs leading-6" style={{ color: "var(--text-3)" }}>
        «دوباره بساز» فقط همین قطعه را دوباره می‌سازد، اعتبار همین قطعه برمی‌گردد و قطعه‌های
        آماده دست‌نخورده می‌مانند. اگر سه بار پشت‌سرهم به نتیجه نرسید، تولید بعدی رایگان می‌شود.
      </p>
    </div>
  );
}
