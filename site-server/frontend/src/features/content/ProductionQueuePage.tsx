import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api, errorMessage, fetchAllPages } from "../../api/client";
import Icon, { type IconName } from "../../components/Icon";
import { StatRow, StatTile } from "../../components/charts";
import {
  Alert,
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorBox,
  Spinner,
  fa,
} from "../../components/ui";
import { Job, JobState } from "../../types";

/**
 * صف تولید — همه‌ی کارهای AI فروشگاه، در یک جا.
 *
 * تا حالا پیشرفت هر کار فقط داخل همان پنلی دیده می‌شد که شروعش کرده
 * بود: ویدیو در استودیوی ویدیو، پوستر در استودیوی تصویر. یعنی برای
 * فهمیدن اینکه «الان چه چیزی روی GPU است»، باید پنج تب را باز می‌کردی —
 * و کاری که در تبِ بسته شکست خورده بود، تا روزها دیده نمی‌شد.
 *
 * GPU در این محصول منبع کمیاب است و همزمان یک کار سنگین بیشتر اجرا
 * نمی‌شود. صفی که دیده نشود یعنی کاربر نمی‌داند چرا کارش شروع نشده، و
 * جواب «معلوم نیست» همان است که آدم را به پشتیبانی می‌فرستد.
 */

const TYPE_LABEL: Record<string, { label: string; icon: IconName }> = {
  product_analysis: { label: "تحلیل محصول", icon: "sparkle" },
  market_analysis: { label: "تحلیل بازار", icon: "swords" },
  caption_generation: { label: "کپشن", icon: "subtitles" },
  image_generation: { label: "تصویر", icon: "image" },
  video_generation: { label: "ویدیو", icon: "film" },
  video_script_generation: { label: "سناریو", icon: "subtitles" },
  video_segment_generation: { label: "قطعه‌ی ویدیو", icon: "film" },
  video_concatenation: { label: "اتصال ویدیو", icon: "film" },
  voice_generation: { label: "صداگذاری", icon: "mic" },
  publishing: { label: "انتشار", icon: "upload" },
  embedding_build: { label: "بردارسازی", icon: "cpu" },
  video_analysis: { label: "تحلیل ویدیو", icon: "play" },
  video_edit: { label: "تدوین", icon: "settings" },
};

const describe = (type: string) => TYPE_LABEL[type] ?? { label: type, icon: "cpu" as IconName };

const TONE: Record<JobState, "info" | "ok" | "bad" | "warn" | "brand" | "neutral"> = {
  QUEUED: "neutral",
  PROCESSING: "brand",
  RUNNING: "brand",
  PREVIEW: "warn",
  WAITING_APPROVAL: "warn",
  APPROVED: "info",
  RENDERING: "brand",
  QC: "info",
  COMPLETED: "ok",
  FAILED: "bad",
  CANCELLED: "neutral",
};

/** همان فهرستی که `apps/jobs/staleness.ACTIVE_STATES` در سرور دارد.
 *  اگر این دو از هم جدا بیفتند، صفحه کاری را «تمام‌شده» نشان می‌دهد که
 *  هنوز روی GPU است. */
const ACTIVE: JobState[] = [
  "QUEUED", "RUNNING", "PROCESSING", "PREVIEW", "WAITING_APPROVAL",
  "APPROVED", "RENDERING", "QC",
];

/** حالت‌هایی که تا کسی جواب ندهد هیچ اتفاقی نمی‌افتد. */
const AWAITING_HUMAN: JobState[] = ["PREVIEW", "WAITING_APPROVAL"];

const when = (iso: string) =>
  new Date(iso).toLocaleString("fa-IR", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });

export default function ProductionQueuePage() {
  const { id: storeId } = useParams<{ id: string }>();
  const [jobs, setJobs] = useState<Job[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);

  const load = useCallback(async () => {
    try {
      setJobs(await fetchAllPages<Job>(`/jobs/?store=${storeId}`));
      setError(null);
    } catch (err) {
      setError(errorMessage(err));
    }
  }, [storeId]);

  useEffect(() => {
    void load();
  }, [load]);

  // کارِ در جریان خودش جلو می‌رود؛ صفحه هم باید برود. وقتی هیچ کار
  // فعالی نیست، نظرسنجی متوقف می‌شود — یک صفحه‌ی باز و بی‌کار نباید هر
  // پنج ثانیه سرور را بزند.
  const active = (jobs ?? []).filter((j) => ACTIVE.includes(j.state));
  useEffect(() => {
    if (active.length === 0) return;
    const timer = setInterval(() => void load(), 5000);
    return () => clearInterval(timer);
  }, [active.length, load]);

  const cancel = async (jobId: number) => {
    setBusyId(jobId);
    try {
      await api.post(`/jobs/${jobId}/cancel/`);
      await load();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusyId(null);
    }
  };

  if (!jobs) {
    return (
      <div className="py-10 text-center">
        {error ? <ErrorBox message={error} /> : <Spinner />}
      </div>
    );
  }

  const waiting = jobs.filter((j) => AWAITING_HUMAN.includes(j.state));
  const failed = jobs.filter((j) => j.state === "FAILED");
  const done = jobs.filter((j) => j.state === "COMPLETED");
  const history = jobs
    .filter((j) => !ACTIVE.includes(j.state))
    .sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime())
    .slice(0, 40);

  const row = (job: Job) => {
    const { label, icon } = describe(job.type);
    const pct =
      job.total_steps > 0 ? Math.round((job.progress_step / job.total_steps) * 100) : null;
    return (
      <Card key={job.id}>
        <div className="flex flex-wrap items-center gap-2">
          <span style={{ color: "var(--text-3)" }}>
            <Icon name={icon} size={17} />
          </span>
          <span className="font-bold" style={{ color: "var(--text)" }}>
            {label}
          </span>
          <Badge tone={TONE[job.state] ?? "neutral"}>{job.state_label ?? job.state}</Badge>
          {!!job.retry_count && <Badge tone="warn">تلاش {fa(job.retry_count + 1)}</Badge>}
          <span className="mr-auto text-xs" style={{ color: "var(--text-3)" }}>
            {when(job.updated_at)}
          </span>
        </div>

        {job.current_step_label && (
          <p className="mt-1.5 text-sm" style={{ color: "var(--text-2)" }}>
            {job.current_step_label}
            {pct !== null && <span className="u-num"> — ٪{fa(pct)}</span>}
          </p>
        )}

        {pct !== null && ACTIVE.includes(job.state) && (
          <div className="u-meter mt-2">
            <span style={{ width: `${pct}%`, background: "var(--brand)" }} />
          </div>
        )}

        {job.error && (
          <p className="mt-2 text-sm" style={{ color: "var(--bad)" }}>
            {job.error}
          </p>
        )}

        {ACTIVE.includes(job.state) && !job.cancel_requested && (
          <div className="mt-3">
            <Button
              variant="secondary"
              size="sm"
              onClick={() => void cancel(job.id)}
              disabled={busyId === job.id}
            >
              <Icon name="x" size={14} />
              لغو کار
            </Button>
          </div>
        )}
        {job.cancel_requested && (
          <p className="mt-2 text-xs" style={{ color: "var(--text-3)" }}>
            لغو درخواست شد — تا پایان مرحله‌ی جاری صبر می‌کند، بعد فایل نیمه‌کاره را پاک
            می‌کند و اعتبار را برمی‌گرداند.
          </p>
        )}
      </Card>
    );
  };

  return (
    <div className="u-rise space-y-5">
      <div>
        <Link
          to={`/stores/${storeId}`}
          className="u-back"
        >
          <Icon name="back" size={15} />
          بازگشت به فروشگاه
        </Link>
        <h1 className="mt-1 text-2xl font-extrabold" style={{ color: "var(--text)" }}>
          صف تولید
        </h1>
        <p className="text-xs" style={{ color: "var(--text-3)" }}>
          هر کاری که AI برای این فروشگاه انجام می‌دهد — در جریان، منتظر تأیید، یا شکست‌خورده.
        </p>
      </div>

      <ErrorBox message={error} />

      <StatRow>
        <StatTile label="در جریان" value={fa(active.length)} />
        <StatTile label="منتظر تأیید شما" value={fa(waiting.length)} />
        <StatTile label="شکست‌خورده" value={fa(failed.length)} />
        <StatTile label="تمام‌شده" value={fa(done.length)} />
      </StatRow>

      {active.length > 1 && (
        <Alert tone="info" title="کارها یکی‌یکی روی GPU می‌روند">
          کارت گرافیک همزمان یک کار سنگین بیشتر برنمی‌دارد، پس بقیه در صف می‌مانند.
          این کندی نیست؛ جلوگیری از پر شدن حافظه‌ی کارت است.
        </Alert>
      )}

      <section>
        <h2 className="mb-2 text-sm font-bold" style={{ color: "var(--text-2)" }}>
          در جریان
        </h2>
        {active.length === 0 ? (
          <Card>
            <EmptyState icon="ok" title="صف خالی است">
              هیچ کاری روی GPU نیست. تولید محتوا از صفحه‌ی محصول شروع می‌شود.
            </EmptyState>
          </Card>
        ) : (
          <div className="space-y-3">{active.map(row)}</div>
        )}
      </section>

      {history.length > 0 && (
        <section>
          <h2 className="mb-2 text-sm font-bold" style={{ color: "var(--text-2)" }}>
            تاریخچه
          </h2>
          <div className="space-y-3">{history.map(row)}</div>
        </section>
      )}
    </div>
  );
}
