import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";

import Icon from "../../../components/Icon";
import { Alert, Badge, Button, Card, ErrorBox, SectionTitle, Spinner } from "../../../components/ui";
import { P, dur, errMsg, fa, up3d, when } from "./api";
import { qualitySummary } from "./editor/QualityPanel";
import { Bar, JobSteps, Muted, StateBadge, WaitingAlert, usePoll, useToast } from "./shared";
import type { Job } from "./types";

/**
 * جزئیاتِ یک کار: مراحل، وضعیت و پیشرفت (با کارگری که کار را گرفته)، هشدارِ «منتظرِ کارگر» با راهِ حل،
 * خروجی‌ها (ویدئو/پوستر/فریم‌ها/GLB)، کنترلِ کیفیت، گزارشِ لحظه‌به‌لحظه، اندازه‌گیری‌های موتور و خطا.
 * تا پایانِ کار هر ۳ ثانیه به‌روز می‌شود.
 */
export default function JobPage() {
  const { id } = useParams<{ id: string }>();
  const toast = useToast();
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<string | null>(null);
  const logRef = useRef<HTMLPreElement>(null);
  const stickRef = useRef(true);

  usePoll(
    async () => {
      try {
        const j = await up3d.job(id!);
        setJob(j);
        setError(null);
        return j.final;
      } catch (e) {
        setError(errMsg(e));
      }
    },
    3000,
    [id],
  );

  // گزارش به انتها می‌چسبد مگر کاربر خودش بالا رفته باشد
  useEffect(() => {
    const el = logRef.current;
    if (el && stickRef.current) el.scrollTop = el.scrollHeight;
  }, [job?.log]);

  const cancel = async () => {
    if (!job || !window.confirm("این کار لغو شود؟")) return;
    try {
      await up3d.cancelJob(job.id);
      toast("درخواستِ لغو رفت");
      setJob(await up3d.job(job.id));
    } catch (e) {
      toast(errMsg(e), true);
    }
  };
  const allowCpu = async () => {
    if (!job) return;
    try {
      const j = await up3d.allowCpu(job.id);
      setJob(j);
      toast(j.waiting && j.waiting.eligible.length ? `کارگرِ ${j.waiting.eligible.join("، ")} به‌زودی کار را می‌گیرد` : "اجازهٔ CPU داده شد؛ تا کارگری آنلاین شود");
    } catch (e) {
      toast(errMsg(e), true);
    }
  };

  if (!job) {
    return (
      <div className="py-10 text-center">
        {error ? <ErrorBox message={error} /> : <Spinner />}
      </div>
    );
  }

  const pct = Math.round(job.progress * 100);
  const f = job.files || {};
  const images = Object.entries(f).filter(([k]) => /\.(png|jpg)$/.test(k) && k !== "poster.jpg");
  const exports = Object.entries(f).filter(([k]) => k.startsWith("scene."));
  const hasGlb = exports.some(([k]) => k.endsWith(".glb"));
  const qcIcon = { pass: <Badge tone="ok">قبول</Badge>, warn: <Badge tone="warn">هشدار</Badge>, fail: <Badge tone="bad">رد</Badge> };
  const engine = job.report?.engine;
  const ffmpegHint = job.state === "FAILED" && /ffmpeg/i.test(job.error || "");

  return (
    <div className="space-y-4">
      <ErrorBox message={error} />
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <Link to={P.jobs()} className="u-back">
            <Icon name="back" size={15} />
            همهٔ کارها
          </Link>
          <h1 className="flex flex-wrap items-center gap-2 text-xl font-extrabold" style={{ color: "var(--text)" }}>
            {job.kind_label} #{fa(job.id)}
            {job.project && (
              <Link to={P.project(job.project)} className="text-sm font-medium" style={{ color: "var(--brand-strong)" }}>
                ({job.project_title || `پروژهٔ ${fa(job.project)}`})
              </Link>
            )}
            <StateBadge job={job} />
            {job.worker ? (
              <Badge tone="info">
                <Icon name="cpu" size={12} /> کارگر: {job.worker}
              </Badge>
            ) : job.waiting ? (
              <Badge tone={job.waiting.eligible.length ? "info" : "warn"}>{job.waiting.eligible.length ? "در انتظارِ گرفتنِ کار" : "منتظرِ کارگر — کسی مناسب نیست"}</Badge>
            ) : null}
          </h1>
        </div>
        {!job.final && (
          <Button variant="danger" onClick={() => void cancel()}>
            لغوِ کار
          </Button>
        )}
      </div>

      <JobSteps job={job} />

      {job.waiting && <WaitingAlert job={job} onAllowCpu={() => void allowCpu()} onCancel={() => void cancel()} />}

      {ffmpegHint && (
        <Alert tone="bad" title="کار در گامِ ساختِ ویدئو (ffmpeg) خراب شد">
          رندر انجام شده بود ولی تبدیلِ فریم‌ها به ویدئو خطا داد. اگر ffmpeg ِ کارگر تازه عوض شده، کارگر باید دوباره راه بیفتد
          (نسخهٔ تازهٔ موتور گزینهٔ سازگار را خودش انتخاب می‌کند). کار را دوباره از صفحهٔ پروژه شروع کنید.
        </Alert>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <div className="space-y-4">
          <Card>
            <div className="flex items-center justify-between">
              <SectionTitle>وضعیت</SectionTitle>
              <StateBadge job={job} />
            </div>
            <p className="text-sm" style={{ color: "var(--text-2)" }}>
              {job.message || ""}
            </p>
            {!job.final && (
              <div className="mt-2">
                <Bar value={job.progress} />
                <Muted className="mt-1">
                  {fa(pct)}٪{job.frames_total ? ` · فریم ${fa(job.frames_done)} از ${fa(job.frames_total)}` : ""}
                  {job.sec_per_frame ? ` · ${fa(job.sec_per_frame)} ثانیه برای هر فریم` : ""}
                  {job.eta_seconds ? ` · مانده ~${dur(job.eta_seconds)}` : job.estimate_seconds ? ` · تخمینِ کل ~${dur(job.estimate_seconds)}` : ""}
                </Muted>
              </div>
            )}
            <table className="u3d-kv mt-3 w-full">
              <tbody>
                <tr>
                  <td>پروفایل</td>
                  <td>
                    <span className="u3d-mono">{job.profile || "—"}</span>
                    {job.quality && <span> · تنظیمِ دستی: {qualitySummary(job.quality)}</span>}
                  </td>
                </tr>
                <tr>
                  <td>کارگر</td>
                  <td>{job.worker || (job.final ? "—" : "هنوز کارگری نگرفته")}</td>
                </tr>
                <tr>
                  <td>نسخهٔ صحنه</td>
                  <td>{job.version ? fa(job.version) : "—"}</td>
                </tr>
                <tr>
                  <td>ثبت / شروع / پایان</td>
                  <td>
                    {when(job.created)} / {when(job.started)} / {when(job.finished)}
                  </td>
                </tr>
              </tbody>
            </table>
          </Card>

          <Card>
            <SectionTitle>خروجی‌ها</SectionTitle>
            {f["final.mp4"] && (
              <>
                <video className="u3d-video" controls playsInline src={f["final.mp4"]} poster={f["poster.jpg"] || undefined} />
                <div className="mt-2 flex flex-wrap gap-2">
                  <a className="u-btn u-btn-primary u-btn-sm" href={f["final.mp4"]} download>
                    <Icon name="download" size={14} />
                    دانلودِ ویدئو
                  </a>
                  {f["render.mp4"] && (
                    <a className="u-btn u-btn-secondary u-btn-sm" href={f["render.mp4"]} download>
                      ویدئوی خام (بی‌صدا)
                    </a>
                  )}
                </div>
              </>
            )}
            {images.length > 0 && (
              <div className="u3d-thumbs mt-2">
                {images.map(([k, v]) => (
                  <a key={k} href={v} target="_blank" rel="noreferrer">
                    <img src={v} alt={k} title={k} />
                  </a>
                ))}
              </div>
            )}
            {exports.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-2">
                {exports.map(([k, v]) => (
                  <a key={k} className="u-btn u-btn-secondary u-btn-sm" href={v} download>
                    {k}
                  </a>
                ))}
                {hasGlb && (
                  <Link className="u-btn u-btn-primary u-btn-sm" to={P.viewer(job.id)}>
                    نمایشگرِ سه‌بعدی
                  </Link>
                )}
              </div>
            )}
            {f["engine.log"] && (
              <p className="mt-2 text-sm">
                <a href={f["engine.log"]} target="_blank" rel="noreferrer" style={{ color: "var(--brand-strong)" }}>
                  گزارشِ کاملِ موتور (engine.log)
                </a>
              </p>
            )}
            {!f["final.mp4"] && images.length === 0 && exports.length === 0 && !f["engine.log"] && (
              <Muted>{job.final ? "خروجی‌ای نماند." : "هنوز خروجی‌ای نیست؛ با پایانِ کار همین‌جا می‌آید."}</Muted>
            )}
          </Card>

          <Card>
            <SectionTitle>کنترلِ کیفیت</SectionTitle>
            {job.qc?.checks ? (
              <>
                <p className="text-sm" style={{ color: "var(--text-2)" }}>
                  نتیجهٔ کلی: {job.qc.result ? qcIcon[job.qc.result] : "—"}
                </p>
                <table className="u3d-kv mt-2 w-full">
                  <tbody>
                    {job.qc.checks.map((c, i) => (
                      <tr key={i}>
                        <td>{qcIcon[c.level]}</td>
                        <td>{c.message}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </>
            ) : (
              <Muted>بعد از رندر پر می‌شود.</Muted>
            )}
          </Card>
        </div>

        <div className="space-y-4">
          <Card>
            <SectionTitle>گزارشِ لحظه‌به‌لحظه</SectionTitle>
            <pre
              ref={logRef}
              className="u3d-pre rtl"
              style={{ maxHeight: 420 }}
              onScroll={(e) => {
                const el = e.currentTarget;
                stickRef.current = el.scrollTop + el.clientHeight >= el.scrollHeight - 20;
              }}
            >
              {job.log || ""}
            </pre>
          </Card>
          {engine && (
            <Card>
              <SectionTitle>اندازه‌گیری‌های موتور</SectionTitle>
              <pre className="u3d-pre">{JSON.stringify(engine, null, 1)}</pre>
            </Card>
          )}
          {job.error && (
            <Card>
              <h2 className="mb-2 text-lg font-bold" style={{ color: "var(--bad)" }}>
                خطا
              </h2>
              <pre className="u3d-pre">{job.error}</pre>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
