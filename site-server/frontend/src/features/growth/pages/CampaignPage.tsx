import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import Icon from "../../../components/Icon";
import { Alert, Badge, Button, Card, Meter, fa } from "../../../components/ui";
import { g, useGet } from "../api";
import { LoadState } from "../components/bits";
import { ConfirmDialog } from "../components/Modal";
import ItemsPanel from "../components/outreach/ItemsPanel";
import { ChannelBadge } from "../components/outreach/ChannelBits";
import ManualQueue from "../components/outreach/ManualQueue";
import { CampaignStateBadge, CapMeter, EmergencyStopButton, Flash, ModeBadge, SendingBanners } from "../components/outreach/shared";
import { faDateTime } from "../format";
import { useAction } from "../outreach/api";
import { COUNTER_ORDER, itemStatus, JOB_KIND_LABEL, MANUAL_QUEUE_STATUSES, templateName } from "../outreach/labels";
import type { CampaignStatusInfo, GrowthSettings, OutreachJobInfo } from "../outreach/types";

type Tab = "items" | "manual";

function JobCard({ job, onChanged }: { job: OutreachJobInfo; onChanged: () => void }) {
  const act = useAction();
  const running = job.status === "queued" || job.status === "running";
  const call = async (what: "cancel" | "resume") => {
    const done = await act.run(() => g.post(`/outreach/jobs/${job.id}/${what}/`));
    if (done !== undefined) onChanged();
  };
  const tone = job.status === "completed" ? "ok" : job.status === "failed" ? "bad" : job.status === "cancelled" ? "warn" : "brand";
  return (
    <div data-testid="job-card">
    <Card>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <b style={{ color: "var(--text)" }}>{JOB_KIND_LABEL[job.kind] ?? job.kind}</b>
          <Badge tone={tone}>{job.status_label || job.status}</Badge>
          <span className="u-num text-xs" style={{ color: "var(--text-3)" }}>
            {fa(job.processed_items)} از {fa(job.total_items)}
          </span>
        </div>
        <div className="flex gap-2">
          {running && (
            <Button size="sm" variant="secondary" onClick={() => call("cancel")} disabled={act.busy} data-testid="job-cancel">
              <Icon name="stop" size={14} /> توقفِ این کار
            </Button>
          )}
          {(job.can_resume || job.stalled) && (
            <Button size="sm" onClick={() => call("resume")} disabled={act.busy} data-testid="job-resume">
              <Icon name="play" size={14} /> ادامه
            </Button>
          )}
        </div>
      </div>
      <div className="mt-3">
        <div className="u-meter">
          <span style={{ width: `${Math.min(100, job.progress)}%`, background: "var(--brand)" }} />
        </div>
      </div>
      {job.stalled && (
        <p className="mt-2 text-xs" style={{ color: "var(--warn)" }}>
          این کار مدتی است جلو نرفته (شاید سرویس راه‌اندازی دوباره شده). «ادامه» را بزنید.
        </p>
      )}
      {job.error && (
        <p className="mt-2 text-sm" style={{ color: job.status === "failed" ? "var(--bad)" : "var(--text-2)" }}>
          {job.error}
        </p>
      )}
      {act.error && (
        <div className="mt-2">
          <Flash tone="bad">{act.error.message}</Flash>
        </div>
      )}
    </Card>
    </div>
  );
}

/**
 * One campaign: header and actions, what blocks sending, live counters, the running job, the items
 * (with review + dry run + batch approval) and the manual queue.
 */
export default function CampaignPage() {
  const { id } = useParams();
  const [fast, setFast] = useState(false);
  const status = useGet<CampaignStatusInfo>(`/outreach/campaigns/${id}/status/`, undefined, { poll: fast ? 3000 : 12000 });
  const settings = useGet<GrowthSettings>("/settings/", undefined, { poll: 15000 });
  const [tab, setTab] = useState<Tab | null>(null);
  const [filter, setFilter] = useState("all");
  const [askCancel, setAskCancel] = useState(false);
  const [notice, setNotice] = useState<{ tone: "ok" | "warn" | "bad"; text: string } | null>(null);
  const act = useAction();

  const info = status.data;
  const job = info?.job ?? null;
  const running = !!job && (job.status === "queued" || job.status === "running");
  useEffect(() => setFast(running), [running]);

  // an emergency stop flips on the server: refresh the settings view right away
  const stopped = info?.emergency_stop;
  const reloadSettings = settings.reload;
  useEffect(() => {
    reloadSettings();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stopped]);

  const reloadAll = () => {
    status.reload();
    settings.reload();
  };

  const post = async (path: string, okText?: string) => {
    const done = await act.run(() => g.post(`/outreach/campaigns/${id}/${path}/`));
    if (done !== undefined) {
      setNotice(okText ? { tone: "ok", text: okText } : null);
      reloadAll();
    }
    return done;
  };

  return (
    <LoadState loading={status.loading && !info} error={status.error} onRetry={status.reload}>
      {info && (
        <CampaignBody
          info={info}
          settings={settings.data}
          tab={tab ?? (info.campaign.mode === "manual" ? "manual" : "items")}
          onTab={setTab}
          filter={filter}
          onFilter={(f) => {
            setFilter(f);
            setTab("items");
          }}
          running={running}
          notice={notice}
          onNotice={setNotice}
          act={act}
          post={post}
          reloadAll={reloadAll}
          askCancel={askCancel}
          setAskCancel={setAskCancel}
        />
      )}
    </LoadState>
  );
}

function CampaignBody({
  info,
  settings,
  tab,
  onTab,
  filter,
  onFilter,
  running,
  notice,
  onNotice,
  act,
  post,
  reloadAll,
  askCancel,
  setAskCancel,
}: {
  info: CampaignStatusInfo;
  settings: GrowthSettings | null;
  tab: Tab;
  onTab: (t: Tab) => void;
  filter: string;
  onFilter: (f: string) => void;
  running: boolean;
  notice: { tone: "ok" | "warn" | "bad"; text: string } | null;
  onNotice: (n: { tone: "ok" | "warn" | "bad"; text: string } | null) => void;
  act: ReturnType<typeof useAction>;
  post: (path: string, okText?: string) => Promise<unknown>;
  reloadAll: () => void;
  askCancel: boolean;
  setAskCancel: (v: boolean) => void;
}) {
  const { campaign, counts, job } = info;
  const auto = campaign.mode === "auto";
  const finished = campaign.status === "completed" || campaign.status === "cancelled";
  const approved = counts.approved ?? 0;
  const pending = counts.pending ?? 0;
  const manualCount = MANUAL_QUEUE_STATUSES(campaign.mode).reduce((sum, s) => sum + (counts[s] ?? 0), 0);

  // what keeps «شروع» from working, said in plain words
  const own = campaign.channel ? info.channels?.[campaign.channel] : undefined;
  const blockers: string[] = [];
  if (auto && !finished) {
    if (info.emergency_stop) blockers.push("توقفِ اضطراری فعال است.");
    if (settings && !settings.sending_enabled) blockers.push("ارسالِ خودکار در «تنظیمات» خاموش است.");
    if (!info.readiness.ok) blockers.push(...info.readiness.problems);
    if (approved === 0) blockers.push("هنوز هیچ موردی تأیید نشده است.");
    if (info.cap_remaining <= 0) blockers.push("سقفِ ارسالِ امروز پر شده است؛ فردا ادامه دهید.");
    if (own && !own.enabled) blockers.push(`کانالِ «${own.label}» در صفحهٔ «کانال‌ها» خاموش است.`);
    if (own && own.enabled && !own.ready) blockers.push(own.not_ready_reason || `کانالِ «${own.label}» آماده نیست.`);
    if (own && own.cap_remaining === 0) blockers.push(`سقفِ روزانهٔ کانالِ «${own.label}» پر شده است.`);
  }
  const canStart = auto && !finished && blockers.length === 0 && !act.busy && !running;
  const startLabel = campaign.status === "active" ? "ادامهٔ ارسال" : campaign.status === "paused" ? "ادامهٔ ارسال" : "شروعِ ارسال";

  return (
    <div className="space-y-5" data-testid="campaign-page">
      <SendingBanners settings={settings ? { ...settings, emergency_stop: info.emergency_stop } : null} onChanged={reloadAll} />

      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <Link to="/growth/outreach" className="mb-1 inline-flex items-center gap-1 text-xs no-underline" style={{ color: "var(--text-3)" }}>
            <Icon name="back" size={12} /> همهٔ کمپین‌ها
          </Link>
          <h2 className="flex flex-wrap items-center gap-2 text-2xl font-extrabold" style={{ color: "var(--text)" }}>
            {campaign.name}
            <ModeBadge mode={campaign.mode} />
            <ChannelBadge channel={campaign.channel} label={campaign.channel_label} />
            <CampaignStateBadge status={campaign.status} label={campaign.status_label} />
          </h2>
          <p className="mt-1 text-sm" style={{ color: "var(--text-3)" }}>
            قالب: {templateName(campaign)}
            {campaign.started_at ? ` · شروع: ${faDateTime(campaign.started_at)}` : ""}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2" data-testid="campaign-actions">
          {auto && !finished && (
            <>
              <Button onClick={() => post("start", "ارسال شروع شد. هر پیام با فاصلهٔ زمانی می‌رود و از سقفِ روزانه بیشتر نمی‌شود.")} disabled={!canStart} data-testid="campaign-start">
                <Icon name="play" size={16} /> {startLabel}
              </Button>
              {campaign.status === "active" && (
                <Button variant="secondary" onClick={() => post("pause", "کمپین متوقف شد؛ پس از موردِ جاری هیچ پیامی نمی‌رود.")} disabled={act.busy} data-testid="campaign-pause">
                  <Icon name="pause" size={16} /> توقفِ موقتِ کمپین
                </Button>
              )}
              <Button variant="secondary" onClick={() => post("prepare", "آماده‌سازیِ فرم‌ها شروع شد.")} disabled={act.busy || running || finished} data-testid="campaign-prepare" title="گیرنده و کانالِ هر لید را می‌سنجد (فرم: صفحهٔ فرم خوانده می‌شود؛ ایمیل و پیامک: حساب و گوشی و اندازهٔ متن) و می‌گوید خودکار می‌شود فرستاد یا نه">
                <Icon name="search" size={16} /> {campaign.channel === "contact_form" || !campaign.channel ? "آماده‌سازیِ فرم‌ها" : "آماده‌سازی"}{pending > 0 ? ` (${fa(pending)})` : ""}
              </Button>
              <EmergencyStopButton stopped={info.emergency_stop} onChanged={reloadAll} compact />
            </>
          )}
          {!finished && (
            <Button variant="danger" size="sm" onClick={() => setAskCancel(true)} disabled={act.busy} data-testid="campaign-cancel">
              لغوِ کمپین
            </Button>
          )}
        </div>
      </div>

      {blockers.length > 0 && (
        <Alert tone="info" title="برای شروعِ ارسال این‌ها لازم است" action={<span className="flex gap-2"><Link to="/growth/settings" className="u-btn u-btn-secondary u-btn-sm no-underline">تنظیمات</Link><Link to="/growth/channels" className="u-btn u-btn-secondary u-btn-sm no-underline">کانال‌ها</Link></span>}>
          <ul className="list-disc ps-5" data-testid="start-blockers">
            {blockers.map((b) => (
              <li key={b}>{b}</li>
            ))}
          </ul>
        </Alert>
      )}
      {notice && (
        <Flash tone={notice.tone} onClose={() => onNotice(null)}>
          {notice.text}
        </Flash>
      )}
      {act.error && <Flash tone="bad">{act.error.message}</Flash>}

      {job && <JobCard job={job} onChanged={reloadAll} />}

      <div className="grid gap-4 lg:grid-cols-[minmax(0,3fr)_minmax(0,1fr)]">
        <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3 xl:grid-cols-4" data-testid="campaign-counters">
          {COUNTER_ORDER.filter((s) => (counts[s] ?? 0) > 0 || ["ready", "approved", "sent", "needs_manual"].includes(s)).map((s) => {
            const meta = itemStatus(s);
            return (
              <button
                key={s}
                type="button"
                onClick={() => onFilter(s)}
                className="u-card p-3 text-start"
                style={{ cursor: "pointer" }}
                data-testid={`counter-${s}`}
                title={meta.hint || undefined}
              >
                <div className="u-num text-2xl font-extrabold" style={{ color: `var(--${meta.tone === "neutral" ? "text" : meta.tone === "brand" ? "brand" : meta.tone})` }}>
                  {fa(counts[s] ?? 0)}
                </div>
                <div className="text-xs" style={{ color: "var(--text-2)" }}>
                  {meta.label}
                </div>
              </button>
            );
          })}
        </div>
        {auto && (
          <Card>
            <CapMeter sent={info.sent_today} cap={info.daily_cap} />
            <p className="mt-2 text-xs" style={{ color: "var(--text-3)" }}>
              سقفِ روزانه برای همهٔ کمپین‌ها با هم است. {fa(info.cap_remaining)} ارسالِ دیگر برای امروز مانده.
              {own && own.cap_remaining != null ? ` سقفِ کانالِ «${own.label}»: ${fa(own.cap_remaining)} ارسالِ دیگر.` : ""}
            </p>
            <div className="mt-3">
              <div className="mb-1 flex justify-between text-xs" style={{ color: "var(--text-3)" }}>
                <span>تأییدشده، منتظرِ ارسال</span>
                <span className="u-num">{fa(approved)}</span>
              </div>
              <Meter used={approved} total={Math.max(approved, info.cap_remaining, 1)} />
            </div>
          </Card>
        )}
      </div>

      <div className="u-tabs">
        <button type="button" className={`u-tab ${tab === "items" ? "active" : ""}`} onClick={() => onTab("items")} data-testid="tab-items">
          موردها
        </button>
        <button type="button" className={`u-tab ${tab === "manual" ? "active" : ""}`} onClick={() => onTab("manual")} data-testid="tab-manual">
          صفِ دستی ({fa(manualCount)})
        </button>
      </div>

      {tab === "items" ? (
        <ItemsPanel
          campaign={campaign}
          status={info}
          settings={settings}
          refreshKey={`${JSON.stringify(counts)}|${job?.id ?? ""}|${job?.processed_items ?? ""}`}
          filter={filter}
          onFilter={onFilter}
          onChanged={reloadAll}
        />
      ) : (
        <ManualQueue campaign={campaign} onChanged={reloadAll} />
      )}

      <ConfirmDialog
        open={askCancel}
        title="کمپین لغو شود؟"
        danger
        confirmLabel="بله، کمپین لغو شود"
        busy={act.busy}
        onConfirm={async () => {
          const done = await post("cancel", "کمپین لغو شد.");
          if (done !== undefined) setAskCancel(false);
        }}
        onClose={() => setAskCancel(false)}
        message="موردهای ارسال‌نشده (در انتظار، آماده، تأییدشده) لغو می‌شوند و دیگر ارسال نمی‌شوند. پیام‌هایی که تا حالا رفته‌اند سر جایشان می‌مانند. این کار برگشت‌پذیر نیست."
      />
    </div>
  );
}
