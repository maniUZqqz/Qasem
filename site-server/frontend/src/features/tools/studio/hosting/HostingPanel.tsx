import { useCallback, useEffect, useRef, useState } from "react";

import { api, studioError } from "../api";
import "./hosting.css";

/**
 * انتشار روی اینترنت: وضعیت، پیشرفتِ کارِ پس‌زمینه، دامنه، پیام‌های فرم.
 * هم داخلِ ویرایشگر (پنجره) و هم به‌صورتِ صفحه در پروژه نشان داده می‌شود.
 */

type StepT = { label: string; state: "wait" | "run" | "done" | "fail" };
type JobT = {
  id: number;
  kind: string;
  state: "queued" | "running" | "ok" | "failed";
  steps: StepT[];
  message: string;
  technical: string;
  created_at: string;
  finished_at: string | null;
};
type RecordT = { type: string; name: string; host: string; value: string };
export type SiteT = {
  key: string;
  state: string;
  state_label: string;
  imported: boolean;
  address: string;
  port_address: string;
  admin_url: string;
  admin_user: string;
  admin_password: string;
  domain: string;
  domain_state: string;
  domain_error: string;
  domain_www: boolean;
  domain_staging: boolean;
  domain_records: RecordT[];
  domain_instruction: string[];
  cert_expires: string | null;
  cert_days_left: number | null;
  server_ip: string;
  last_publish_at: string | null;
  last_error: string;
  last_technical: string;
  can_rollback: boolean;
  unit: string;
  published: boolean;
  unread?: number;
  messages_total?: number;
  errors?: string[];
  memory_mb?: number | null;
  disk_mb?: number | null;
  pending?: string[];
  drafts?: string[];
  backups?: string[];
};
type CapacityT = { sites: number; max_sites: number; disk_free_mb: number; mem_available_mb: number; min_disk_mb: number; min_mem_mb: number };
type StatusResp = { site: SiteT; job: JobT | null; capacity: CapacityT | null };
type MessageT = { id: number; form_title: string; page: string; content: string; data: Record<string, string>; is_read: boolean; created_at: string };

const faDate = (iso: string | null) => {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("fa-IR", { dateStyle: "medium", timeStyle: "short" });
  } catch {
    return iso;
  }
};
const fa = (n: number | null | undefined) => (n ?? 0).toLocaleString("fa-IR");

function Copy({ text }: { text: string }) {
  const [done, setDone] = useState(false);
  return (
    <button
      type="button"
      className="nh-copy"
      onClick={() => {
        void navigator.clipboard?.writeText(text).then(() => {
          setDone(true);
          window.setTimeout(() => setDone(false), 1500);
        });
      }}
    >
      {done ? "کپی شد" : "کپی"}
    </button>
  );
}

function Tech({ text }: { text: string }) {
  if (!text) return null;
  return (
    <details className="nh-tech">
      <summary>جزئیات برای برنامه‌نویس</summary>
      <pre dir="ltr">{text}</pre>
    </details>
  );
}

export default function HostingPanel({ slug, autoJob, onLive }: { slug: string; autoJob?: JobT | null; onLive?: (address: string) => void }) {
  const [data, setData] = useState<StatusResp | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [job, setJob] = useState<JobT | null>(autoJob ?? null);
  const [tab, setTab] = useState<"status" | "domain" | "messages">("status");
  const timer = useRef<number>();
  const url = `/studio/projects/${slug}/hosting/`;

  const load = useCallback(async () => {
    const { data: d } = await api.get<StatusResp>(url);
    setData(d);
    return d;
  }, [url]);

  const poll = useCallback(() => {
    window.clearTimeout(timer.current);
    const tick = async () => {
      try {
        const { data: d } = await api.get<StatusResp>(`${url}?light=1`);
        setJob(d.job);
        if (d.job && (d.job.state === "queued" || d.job.state === "running")) {
          timer.current = window.setTimeout(() => void tick(), 1500);
        } else {
          const full = await load();
          if (d.job?.state === "ok" && full.site.address) onLive?.(full.site.address);
        }
      } catch (err) {
        setError(studioError(err));
      }
    };
    void tick();
  }, [url, load, onLive]);

  useEffect(() => {
    load()
      .then((d) => {
        const running = d.job && (d.job.state === "queued" || d.job.state === "running");
        if (running || autoJob) {
          setJob(d.job);
          poll();
        }
      })
      .catch((err) => setError(studioError(err)));
    return () => window.clearTimeout(timer.current);
  }, [load, poll, autoJob]);

  const act = useCallback(
    async (path: string, confirmText?: string, body?: object) => {
      if (confirmText && !window.confirm(confirmText)) return;
      setError(null);
      setNotice(null);
      try {
        const { data: d } = await api.post<{ job: JobT }>(`${url}${path}/`, body ?? {});
        setJob(d.job);
        poll();
      } catch (err) {
        setError(studioError(err));
      }
    },
    [url, poll],
  );

  if (!data) {
    return error ? <p className="nh-bad" role="alert">{error}</p> : <p className="nh-muted">در حالِ خواندنِ وضعیت…</p>;
  }
  const site = data.site;
  const busy = !!job && (job.state === "queued" || job.state === "running");
  const showJob = job && (busy || (job.finished_at && Date.now() - new Date(job.finished_at).getTime() < 15 * 60 * 1000));
  const tone = site.state === "live" ? "ok" : site.state === "failed" ? "bad" : site.state === "stopped" ? "warn" : "muted";

  return (
    <div className="nh" data-testid="hosting">
      {site.imported && <p className="nh-warn">پروژهٔ واردشده هنوز از این راه منتشر نمی‌شود، چون تنظیمات و دیتابیسِ خودش را دارد. می‌توانی ZIP را بگیری.</p>}
      {error && <p className="nh-bad" role="alert" data-testid="hosting-error">{error}</p>}
      {notice && <p className="nh-ok" role="status">{notice}</p>}

      {showJob && <JobBox job={job} />}

      <div className="nh-tabs" role="tablist">
        <button type="button" role="tab" aria-selected={tab === "status"} className={tab === "status" ? "on" : ""} onClick={() => setTab("status")}>وضعیتِ سایت</button>
        <button type="button" role="tab" aria-selected={tab === "domain"} className={tab === "domain" ? "on" : ""} onClick={() => setTab("domain")} data-testid="tab-domain">دامنه</button>
        <button type="button" role="tab" aria-selected={tab === "messages"} className={tab === "messages" ? "on" : ""} onClick={() => setTab("messages")} data-testid="tab-messages">
          پیام‌های فرم{site.unread ? <span className="nh-badge" data-testid="unread">{fa(site.unread)}</span> : null}
        </button>
      </div>

      {tab === "status" && (
        <section className="nh-card" data-testid="site-card">
          <div className="nh-row">
            <span className={`nh-dot ${tone}`} />
            <b data-testid="site-state">{site.state_label}</b>
            {site.published && site.unit && site.unit !== "active" && <span className="nh-muted">({site.unit})</span>}
          </div>

          {site.address ? (
            <div className="nh-address">
              <span className="nh-muted">نشانیِ سایت:</span>
              <a href={site.address} target="_blank" rel="noreferrer" dir="ltr" data-testid="site-address">{site.address}</a>
              <Copy text={site.address} />
            </div>
          ) : (
            <p className="nh-muted">با زدنِ «انتشار» سایتت یک نشانیِ ثابت می‌گیرد که همه می‌توانند بازش کنند. بعداً می‌توانی دامنهٔ خودت را هم وصل کنی.</p>
          )}

          {!busy && site.pending && site.pending.length > 0 && (
            <p className="nh-warn">این بخش‌ها بعد از آخرین انتشار عوض شده‌اند و هنوز روی اینترنت نیستند: {site.pending.join("، ")}</p>
          )}
          {site.drafts && site.drafts.length > 0 && (
            <p className="nh-note">پیش‌نویسِ ذخیره‌نشده در سایت: {site.drafts.join("، ")}. این‌ها تا وقتی در ویرایشگرِ خودشان «انتشار» را نزنی روی سایت نمی‌آیند.</p>
          )}

          {site.last_error && (
            <div className="nh-bad" role="alert" data-testid="site-last-error">
              <b>آخرین تلاش:</b> {site.last_error}
              <Tech text={site.last_technical} />
            </div>
          )}

          <dl className="nh-facts">
            <dt>آخرین انتشار</dt>
            <dd>{faDate(site.last_publish_at)}</dd>
            {site.domain && (
              <>
                <dt>دامنه</dt>
                <dd dir="ltr">{site.domain}</dd>
              </>
            )}
            {site.cert_days_left != null && (
              <>
                <dt>گواهیِ امنیت</dt>
                <dd>تا {faDate(site.cert_expires)} ({fa(site.cert_days_left)} روزِ دیگر؛ خودکار تمدید می‌شود)</dd>
              </>
            )}
            {site.memory_mb != null && (
              <>
                <dt>مصرفِ حافظه</dt>
                <dd>{fa(Math.round(site.memory_mb))} مگابایت</dd>
              </>
            )}
            {site.disk_mb != null && (
              <>
                <dt>فضای سایت</dt>
                <dd>{fa(site.disk_mb)} مگابایت</dd>
              </>
            )}
          </dl>

          <div className="nh-actions">
            {!site.imported && (
              <button type="button" className="nh-btn main" disabled={busy} data-testid="publish-live" onClick={() => void act("publish")}>
                {site.published ? "انتشارِ دوباره" : "انتشار"}
              </button>
            )}
            {site.published && site.state === "stopped" && (
              <button type="button" className="nh-btn" disabled={busy} data-testid="site-start" onClick={() => void act("start")}>روشن کردن</button>
            )}
            {site.published && site.state !== "stopped" && (
              <button type="button" className="nh-btn" disabled={busy} data-testid="site-stop" onClick={() => void act("stop", "سایت خاموش شود؟ تا وقتی روشنش نکنی کسی نمی‌تواند بازش کند.")}>خاموش کردن</button>
            )}
            {site.can_rollback && (
              <button type="button" className="nh-btn" disabled={busy} data-testid="site-rollback" onClick={() => void act("rollback", "سایت به نسخهٔ قبلی برگردد؟ داده‌ها و پیام‌ها می‌مانند.")}>بازگشت به نسخهٔ قبلی</button>
            )}
            {site.published && (
              <button type="button" className="nh-btn danger" disabled={busy} data-testid="site-unpublish" onClick={() => void act("unpublish", "سایت از اینترنت برداشته شود؟ نشانی‌اش از کار می‌افتد، ولی داده‌ها و پیام‌هایش نگه داشته می‌شوند.")}>برداشتن از اینترنت</button>
            )}
          </div>

          {site.admin_user && site.published && (
            <details className="nh-details" data-testid="site-admin">
              <summary>مدیریتِ سایت (ثبتِ محصول و داده)</summary>
              <p>نشانی: <a href={site.admin_url} target="_blank" rel="noreferrer" dir="ltr">{site.admin_url}</a></p>
              <p>نامِ کاربری: <code dir="ltr" data-testid="admin-user">{site.admin_user}</code> <Copy text={site.admin_user} /></p>
              <p>رمز: <code dir="ltr" data-testid="admin-password">{site.admin_password}</code> <Copy text={site.admin_password} /></p>
              <p className="nh-muted">این رمز با انتشارِ دوباره عوض نمی‌شود. اگر داخلِ مدیریتِ سایت عوضش کنی این‌جا هم قدیمی می‌ماند.</p>
              <button type="button" className="nh-btn" disabled={busy} onClick={() => void act("reset-admin", "رمزِ تازه ساخته شود؟ رمزِ فعلی دیگر کار نمی‌کند.")}>ساختنِ رمزِ تازه</button>
            </details>
          )}

          {site.errors && site.errors.length > 0 && (
            <details className="nh-details">
              <summary>خطاهای اخیرِ سایت ({fa(site.errors.length)})</summary>
              <pre className="nh-log" dir="ltr">{site.errors.join("\n")}</pre>
            </details>
          )}

          {data.capacity && (
            <p className="nh-muted nh-cap" data-testid="capacity">
              این سرور: {fa(data.capacity.sites)} از {fa(data.capacity.max_sites)} سایت · فضای خالی {fa(Math.round(data.capacity.disk_free_mb / 1024 * 10) / 10)} گیگابایت · حافظهٔ آزاد {fa(data.capacity.mem_available_mb)} مگابایت
            </p>
          )}
        </section>
      )}

      {tab === "domain" && <DomainPanel slug={slug} site={site} busy={busy} onJob={(j) => { setJob(j); poll(); setTab("status"); }} onChange={() => void load()} />}
      {tab === "messages" && <MessagesPanel slug={slug} onChange={() => void load()} />}
    </div>
  );
}

function JobBox({ job }: { job: JobT }) {
  const failed = job.state === "failed";
  return (
    <div className={`nh-job ${failed ? "bad" : job.state === "ok" ? "ok" : ""}`} data-testid="job" data-state={job.state}>
      <ol className="nh-steps">
        {job.steps.map((s, i) => (
          <li key={i} className={s.state}>
            <i aria-hidden="true">{s.state === "done" ? "✓" : s.state === "fail" ? "✕" : s.state === "run" ? "…" : ""}</i>
            {s.label}
          </li>
        ))}
        {!job.steps.length && <li className="run"><i aria-hidden="true">…</i>در صف…</li>}
      </ol>
      {job.message && (
        <p data-testid="job-message">
          {job.message.split(/(https?:\/\/\S+)/).map((part, i) =>
            i % 2 ? <a key={i} href={part} target="_blank" rel="noreferrer" dir="ltr" style={{ unicodeBidi: "isolate" }}>{part}</a> : part,
          )}
        </p>
      )}
      {failed && <Tech text={job.technical} />}
    </div>
  );
}

function DomainPanel({ slug, site, busy, onJob, onChange }: { slug: string; site: SiteT; busy: boolean; onJob: (j: JobT) => void; onChange: () => void }) {
  const url = `/studio/projects/${slug}/hosting/domain/`;
  const [name, setName] = useState(site.domain);
  const [error, setError] = useState<string | null>(null);
  const [problems, setProblems] = useState<string[]>([]);
  const [working, setWorking] = useState(false);

  async function save() {
    setWorking(true);
    setError(null);
    setProblems([]);
    try {
      await api.post(url, { domain: name });
      onChange();
    } catch (err) {
      setError(studioError(err));
    } finally {
      setWorking(false);
    }
  }
  async function check() {
    setWorking(true);
    setError(null);
    setProblems([]);
    try {
      const { data } = await api.post<{ ready: boolean; problems: string[]; job?: JobT }>(`${url}check/`, {});
      setProblems(data.problems || []);
      if (data.ready && data.job) onJob(data.job);
    } catch (err) {
      setError(studioError(err));
    } finally {
      setWorking(false);
    }
  }
  async function remove() {
    if (!window.confirm("دامنه از این سایت جدا شود؟ سایت از نشانیِ قبلی‌اش باز می‌شود.")) return;
    setWorking(true);
    setError(null);
    try {
      const { data } = await api.delete<{ job: JobT | null }>(url);
      if (data.job) onJob(data.job);
      else onChange();
    } catch (err) {
      setError(studioError(err));
    } finally {
      setWorking(false);
    }
  }

  if (!site.published) {
    return <section className="nh-card"><p className="nh-muted">اول سایت را منتشر کن، بعد می‌توانی دامنه‌ات را وصل کنی.</p></section>;
  }
  const connected = site.domain_state === "active";
  return (
    <section className="nh-card" data-testid="domain-panel">
      {connected ? (
        <>
          <p className="nh-ok" data-testid="domain-active">
            دامنه وصل است و قفلِ امن (https) روشن است: <a href={site.address} target="_blank" rel="noreferrer" dir="ltr">{site.address}</a>
          </p>
          {site.domain_staging && <p className="nh-warn">این گواهی آزمایشی است و مرورگر هشدار می‌دهد.</p>}
          {site.domain_error && <p className="nh-warn">{site.domain_error}</p>}
          {!site.domain_www && site.domain_records.length > 1 && (
            <p className="nh-note">نشانیِ www هنوز تنظیم نشده. رکوردِ A با نامِ www و مقدارِ {site.server_ip} را هم بگذار و دوباره «بررسی و وصل کردن» را بزن.</p>
          )}
          <div className="nh-actions">
            <button type="button" className="nh-btn" disabled={busy || working} onClick={() => void check()}>بررسی و وصل کردنِ دوباره</button>
            <button type="button" className="nh-btn danger" disabled={busy || working} data-testid="domain-remove" onClick={() => void remove()}>جدا کردنِ دامنه</button>
          </div>
        </>
      ) : (
        <>
          <label className="nh-label" htmlFor="nh-domain">نامِ دامنه‌ات</label>
          <div className="nh-domain-row">
            <input id="nh-domain" dir="ltr" className="nh-input" data-testid="domain-input" placeholder="example.ir" value={name} onChange={(e) => setName(e.target.value)} />
            <button type="button" className="nh-btn" disabled={working || !name.trim()} data-testid="domain-save" onClick={() => void save()}>ثبت</button>
          </div>
          {site.domain && (
            <div className="nh-dns" data-testid="dns-instruction">
              <p>{site.domain_instruction[0]}</p>
              <p>{site.domain_instruction[1]}</p>
              <table className="nh-table">
                <thead>
                  <tr><th>نوع</th><th>نام</th><th>مقدار</th></tr>
                </thead>
                <tbody>
                  {site.domain_records.map((r) => (
                    <tr key={r.host}>
                      <td dir="ltr">{r.type}</td>
                      <td dir="ltr">{r.name}</td>
                      <td dir="ltr">{r.value} <Copy text={r.value} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {site.domain_instruction.slice(2 + site.domain_records.length).map((line, i) => <p key={i} className="nh-muted">{line}</p>)}
              <div className="nh-actions">
                <button type="button" className="nh-btn main" disabled={busy || working} data-testid="domain-check" onClick={() => void check()}>
                  {working ? "در حالِ بررسی…" : "بررسی و وصل کردن"}
                </button>
                <button type="button" className="nh-btn" disabled={busy || working} onClick={() => void remove()}>حذف</button>
              </div>
            </div>
          )}
          {site.domain_error && <p className="nh-bad" role="alert" data-testid="domain-error">{site.domain_error}</p>}
        </>
      )}
      {error && <p className="nh-bad" role="alert" data-testid="domain-form-error">{error}</p>}
      {problems.map((p, i) => <p key={i} className="nh-warn" data-testid="dns-problem">{p}</p>)}
    </section>
  );
}

function MessagesPanel({ slug, onChange }: { slug: string; onChange: () => void }) {
  const url = `/studio/projects/${slug}/hosting/messages/`;
  const [rows, setRows] = useState<MessageT[] | null>(null);
  const [total, setTotal] = useState(0);
  const [unread, setUnread] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const PAGE = 30;

  const load = useCallback(async (offset = 0) => {
    try {
      const { data } = await api.get<{ rows: MessageT[]; total: number; unread: number }>(`${url}?limit=${PAGE}&offset=${offset}`);
      setRows((old) => (offset && old ? [...old, ...data.rows] : data.rows));
      setTotal(data.total);
      setUnread(data.unread);
    } catch (err) {
      setError(studioError(err));
    }
  }, [url]);

  useEffect(() => {
    void load();
  }, [load]);

  async function mark(body: object) {
    try {
      await api.post(url, body);
      await load();
      onChange();
    } catch (err) {
      setError(studioError(err));
    }
  }

  if (error) return <section className="nh-card"><p className="nh-bad" role="alert">{error}</p></section>;
  if (!rows) return <section className="nh-card"><p className="nh-muted">در حالِ خواندن…</p></section>;
  return (
    <section className="nh-card" data-testid="messages">
      <div className="nh-row">
        <b>{fa(total)} پیام</b>
        {unread > 0 && <span className="nh-badge">{fa(unread)} خوانده‌نشده</span>}
        {unread > 0 && <button type="button" className="nh-link" onClick={() => void mark({ all: true })}>همه خوانده شد</button>}
      </div>
      {!rows.length && <p className="nh-muted">هنوز پیامی نرسیده. وقتی کسی فرمِ سایتت را پر کند این‌جا می‌بینی.</p>}
      <ul className="nh-msgs">
        {rows.map((m) => (
          <li key={m.id} className={m.is_read ? "" : "new"} data-testid="message">
            <div className="nh-msg-head">
              <b>{m.form_title || "فرم"}</b>
              <span className="nh-muted">{faDate(m.created_at.replace(" ", "T") + (/[zZ]|\+/.test(m.created_at) ? "" : "Z"))}</span>
              {m.page && <span className="nh-muted" dir="ltr">{m.page}</span>}
              <button type="button" className="nh-link" onClick={() => void mark({ id: m.id, read: !m.is_read })}>{m.is_read ? "نخوانده" : "خواندم"}</button>
            </div>
            {Object.keys(m.data || {}).length ? (
              <dl className="nh-msg-data">
                {Object.entries(m.data).map(([k, v]) => (
                  <div key={k}>
                    <dt>{k}</dt>
                    <dd>{String(v)}</dd>
                  </div>
                ))}
              </dl>
            ) : (
              <p className="nh-msg-text">{m.content}</p>
            )}
          </li>
        ))}
      </ul>
      {rows.length < total && <button type="button" className="nh-btn" onClick={() => void load(rows.length)}>پیام‌های قدیمی‌تر</button>}
    </section>
  );
}
