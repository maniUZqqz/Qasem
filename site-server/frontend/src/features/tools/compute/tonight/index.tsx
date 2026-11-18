import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { api, errorMessage } from "../../../../api/client";
import Icon from "../../../../components/Icon";
import { Alert, Badge, Button, Card, ErrorBox, PageHeader, Spinner, fa } from "../../../../components/ui";
import "../selftest/selftest.css";
import "./tonight.css";

/**
 * «امشب: روشن کردنِ سرورِ پردازش» (فقط کارکنان، ۱۴۰۵/۰۸/۲۸).
 *
 * پیش از روشن شدنِ گره: چک‌لیستِ «چه می‌شود» و فهرستِ نصب‌ها. بعد از روشن شدن: پیشرفتِ زنده‌ی
 * به‌روزرسانی ⇒ نصب ⇒ آزمون ⇒ کارهای منتظر ⇒ درخواست‌های هوش مصنوعیِ صف‌دار، با خطای فارسی و دکمهٔ «دوباره».
 * هیچ‌چیز کلیک نمی‌خواهد؛ دکمه‌ها فقط برای وقتی است که چیزی قرمز شد. داده از GET /compute/tonight/ می‌آید (backend/apps/compute/tonight.py).
 */

type StepState = "todo" | "waiting" | "doing" | "done" | "warn" | "fail" | "skip";
type Row = {
  key: string;
  title: string;
  state: StepState;
  detail: string;
  action?: string;
  progress?: number | null;
  feature?: string;
  kind?: string;
  items?: { id: string; title: string; state: StepState; progress?: number | null; detail: string; error: string; tries: number }[];
  results?: { key: string; label: string; state: string }[];
  bytes?: number;
  queued?: number;
  running?: number;
  done?: number;
  failed?: number;
  kinds?: { kind: string; label: string; model: string; installed: boolean; substitute: string; reason: string }[] | string[];
  models?: string[];
  comfyui?: boolean;
};
type Report = {
  at: string;
  phase: "off" | "update" | "installs" | "tests" | "jobs" | "attention" | "done";
  phase_text: string;
  node: { id: number; name: string; online: boolean; agent: string; last_seen: string } | null;
  latest_agent: string;
  steps: Row[];
  installs: Row[];
  tests: Row[];
  queue: Row[];
  checklist: { n: string; title: string; detail: string }[];
  owner: { key: string; title: string; state: string; detail: string; how: string }[];
  auto: { auto_update: boolean; auto_selftest: boolean; requeue_after_pass: boolean };
  counts: Record<string, number>;
};

const TONE: Record<StepState, "ok" | "bad" | "warn" | "neutral" | "info" | "brand"> = { done: "ok", fail: "bad", warn: "warn", doing: "brand", waiting: "info", todo: "neutral", skip: "neutral" };
const TEXT: Record<StepState, string> = { done: "انجام شد", fail: "قرمز", warn: "نیازِ توجه", doing: "در جریان", waiting: "منتظرِ روشن شدنِ سرور", todo: "هنوز نه", skip: "برای این سیستم نیست" };
const ACTION_TEXT: Record<string, string> = { update: "به‌روزرسانیِ دوباره", bootstrap: "نصبِ دوباره", selftest: "آزمونِ دوباره", requeue: "کارهای ناموفق را دوباره بفرست" };
const PHASE_TONE: Record<Report["phase"], "ok" | "bad" | "warn" | "neutral" | "info" | "brand"> = { off: "warn", update: "brand", installs: "brand", tests: "brand", jobs: "brand", attention: "bad", done: "ok" };
const POLL_FAST = 5000;
const POLL_SLOW = 20000;

function pct(p: number | null | undefined): number {
  return Math.max(0, Math.min(100, Math.round((p ?? 0) * 100)));
}

function Bar({ value }: { value: number | null | undefined }) {
  if (value === null || value === undefined) return null;
  return (
    <div className="nmt-bar" role="progressbar" aria-valuenow={pct(value)} aria-valuemin={0} aria-valuemax={100}>
      <span style={{ width: `${pct(value)}%` }} />
    </div>
  );
}

function mb(bytes?: number): string {
  if (!bytes) return "";
  return bytes >= 1e9 ? `${fa((bytes / 1e9).toFixed(1).replace(".", "٫"))} گیگابایت` : `${fa(Math.round(bytes / 1e6))} مگابایت`;
}

export default function TonightPage() {
  const [data, setData] = useState<Report | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ tone: "ok" | "bad"; text: string } | null>(null);
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const alive = useRef(true);

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  const load = useCallback(async () => {
    try {
      const { data: d } = await api.get<Report>("/compute/tonight/");
      if (!alive.current) return;
      setData(d);
      setErr(null);
    } catch (e) {
      if (alive.current) setErr(errorMessage(e));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const fast = !!data && ["update", "installs", "tests", "jobs"].includes(data.phase);
  useEffect(() => {
    const t = window.setInterval(() => {
      if (document.visibilityState === "visible") void load();
    }, fast ? POLL_FAST : POLL_SLOW);
    return () => window.clearInterval(t);
  }, [load, fast]);

  async function retry(what: string) {
    setBusy(what);
    setNotice(null);
    try {
      const { data: r } = await api.post<{ ok: boolean; message: string }>("/compute/tonight/retry/", { what, node: data?.node?.id });
      setNotice({ tone: r.ok ? "ok" : "bad", text: r.message });
    } catch (e) {
      setNotice({ tone: "bad", text: errorMessage(e) });
    } finally {
      setBusy(null);
      void load();
    }
  }

  const node = data?.node;
  const bad = data?.steps.filter((s) => s.state === "fail").length ?? 0;

  function detailRows(step: Row): Row[] {
    if (step.key === "installs") return data?.installs ?? [];
    if (step.key === "selftests") return data?.tests ?? [];
    if (step.key === "queue") return data?.queue ?? [];
    return [];
  }

  return (
    <div className="nmt nmtn" data-testid="tonight" data-phase={data?.phase}>
      <PageHeader
        title="امشب: روشن کردنِ سرورِ پردازش"
        subtitle="کامپیوترِ گرافیکی را روشن کنید؛ به‌روزرسانی، نصبِ نیازمندی‌ها، آزمونِ هر ویژگی و اجرای کارهای منتظر خودشان انجام می‌شود. این‌جا همه‌چیز زنده دیده می‌شود."
        actions={
          <>
            <Link to="/tools/compute/selftest" className="u-btn u-btn-secondary u-btn-sm no-underline">
              <Icon name="check" size={13} /> آزمونِ خودکار
            </Link>
            <Link to="/tools/compute/queue" className="u-btn u-btn-secondary u-btn-sm no-underline">
              <Icon name="clock" size={13} /> صفِ پردازش
            </Link>
            <Button size="sm" variant="secondary" onClick={() => void load()}>
              <Icon name="refresh" size={13} /> تازه‌سازی
            </Button>
          </>
        }
      />
      <ErrorBox message={err} />
      {notice && <Alert tone={notice.tone === "ok" ? "ok" : "bad"}>{notice.text}</Alert>}
      {!data && !err && <Spinner size={18} />}

      {data && (
        <>
          <Card padded={false}>
            <div className="nmt-sec" data-testid="tonight-status">
              <div className="nmt-head">
                <span className={`nmt-dot ${node?.online ? "online" : "offline"}`} />
                <span className="nmt-name">{node ? node.name : "سرورِ پردازشی ثبت نیست"}</span>
                <Badge tone={PHASE_TONE[data.phase]}>{data.phase_text}</Badge>
                <span className="nmt-head-end">
                  {node?.online && (
                    <Button size="sm" variant="secondary" disabled={busy !== null} onClick={() => void retry("kick")}>
                      <Icon name="rocket" size={13} /> {busy === "kick" ? "…" : "همین حالا بررسی کن"}
                    </Button>
                  )}
                </span>
              </div>
              <div className="nmt-chips">
                {node?.agent && <span className="nmt-chip ltr">نرم‌افزارِ گره {node.agent}</span>}
                {data.latest_agent && <span className="nmt-chip ltr">نسخهٔ سایت {data.latest_agent}</span>}
                <span className={`nmt-chip ${data.auto.auto_update ? "ok" : "warn"}`}>به‌روزرسانیِ خودکار {data.auto.auto_update ? "روشن" : "خاموش"}</span>
                <span className={`nmt-chip ${data.auto.auto_selftest ? "ok" : "warn"}`}>آزمونِ خودکار {data.auto.auto_selftest ? "روشن" : "خاموش"}</span>
                <span className={`nmt-chip ${data.auto.requeue_after_pass ? "ok" : "warn"}`}>اجرای دوبارهٔ کارهای ناموفق {data.auto.requeue_after_pass ? "روشن" : "خاموش"}</span>
              </div>
              {bad > 0 && <Alert tone="bad">{fa(bad)} بخش قرمز است؛ دلیل و دکمهٔ «دوباره» زیرِ همان بخش هست.</Alert>}
            </div>
          </Card>

          {data.checklist.length > 0 && (
            <Card padded={false}>
              <div className="nmt-sec" data-testid="tonight-checklist">
                <div className="nmt-sec-title">
                  <h2>وقتی روشنش کنید این‌ها خودشان اتفاق می‌افتد</h2>
                  <span>کارِ دیگری از شما لازم نیست</span>
                </div>
                <ol className="nmtn-check">
                  {data.checklist.map((c) => (
                    <li key={c.n}>
                      <b className="nmt-wrap">{c.title}</b>
                      <p className="nmt-detail">{c.detail}</p>
                    </li>
                  ))}
                </ol>
              </div>
            </Card>
          )}

          <Card padded={false}>
            <div className="nmt-sec" data-testid="tonight-steps">
              <div className="nmt-sec-title">
                <h2>پیشرفت</h2>
                <span>{data.node?.online ? "هر ۵ ثانیه تازه می‌شود" : "با روشن شدنِ گره زنده می‌شود"}</span>
              </div>
              <div className="nmt-list">
                {data.steps.map((s, i) => {
                  const rows = detailRows(s);
                  const isOpen = open[s.key] ?? (s.state === "fail" || s.state === "doing");
                  return (
                    <div key={s.key} className="nmt-test" data-step={s.key} data-state={s.state}>
                      <div className="nmt-test-row">
                        <span className="nmtn-n">{fa(i + 1)}</span>
                        <Badge tone={TONE[s.state]}>{TEXT[s.state]}</Badge>
                        <b className="nmt-test-title">{s.title}</b>
                        <span className="nmt-test-end">
                          {s.action && ACTION_TEXT[s.action] && (s.state === "fail" || s.state === "warn" || (s.action === "update" && s.state === "doing")) && (
                            <Button size="sm" variant="secondary" disabled={busy !== null} onClick={() => void retry(s.action!)}>
                              <Icon name="refresh" size={13} /> {busy === s.action ? "…" : ACTION_TEXT[s.action]}
                            </Button>
                          )}
                          {rows.length > 0 && (
                            <Button size="sm" variant="secondary" onClick={() => setOpen({ ...open, [s.key]: !isOpen })}>
                              {isOpen ? "بستن" : `جزئیات (${fa(rows.length)})`}
                            </Button>
                          )}
                        </span>
                      </div>
                      <p className="nmt-detail">{s.detail}</p>
                      {s.key === "models" && Array.isArray(s.kinds) && (s.kinds as { kind: string; label: string; model: string; installed: boolean; substitute: string; reason: string }[]).length > 0 && (
                        <div className="nmt-chips">
                          {(s.kinds as { kind: string; label: string; model: string; installed: boolean; substitute: string; reason: string }[]).map((k) => (
                            <span key={k.kind} className={`nmt-chip ${k.installed ? "ok" : "bad"}`} title={k.reason}>
                              {k.label}: <span className="nmt-chip ltr">{k.model || "—"}</span>
                              {k.substitute ? " (جایگزین)" : ""}
                            </span>
                          ))}
                        </div>
                      )}
                      {isOpen && rows.length > 0 && (
                        <div className="nmtn-rows">
                          {rows.map((r) => (
                            <div key={r.key} className="nmt-feat" data-row={r.key} data-state={r.state}>
                              <div className="nmt-feat-head">
                                <Badge tone={TONE[r.state]}>{TEXT[r.state]}</Badge>
                                <span className="nmt-feat-title">{r.title}</span>
                                {r.bytes ? <span className="nmt-small">حدود {mb(r.bytes)}</span> : null}
                              </div>
                              {r.detail && <p className="nmt-detail">{r.detail}</p>}
                              <Bar value={r.progress} />
                              {r.items?.some((it) => it.state === "fail" || it.state === "doing") && (
                                <div>
                                  {r.items
                                    .filter((it) => it.state === "fail" || it.state === "doing")
                                    .map((it) => (
                                      <div key={it.id} className="nmt-item">
                                        <div className="nmt-item-row">
                                          <Badge tone={TONE[it.state]}>{TEXT[it.state]}</Badge>
                                          <span>{it.title}</span>
                                          {it.tries > 1 && <span className="nmt-small">تلاشِ {fa(it.tries)}</span>}
                                        </div>
                                        <Bar value={it.progress} />
                                        {(it.error || it.detail) && <p className="nmt-detail nmtn-ltr">{it.error || it.detail}</p>}
                                      </div>
                                    ))}
                                </div>
                              )}
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          </Card>

          {data.owner.length > 0 && (
            <Card padded={false}>
              <div className="nmt-sec" data-testid="tonight-owner">
                <div className="nmt-sec-title">
                  <h2>کارهایی که فقط خودِ شما می‌توانید بکنید</h2>
                  <span>
                    {fa(data.owner.length)} مورد · <Link to="/tools/compute/selftest">همهٔ جزئیات</Link>
                  </span>
                </div>
                <p className="nmt-small">همهٔ چیزهای دیگر خودکار است؛ این‌ها به حساب، اعتبار، مجوز یا تأییدِ شما بسته‌اند (و انتشار و ارسال هم همیشه به تأییدِ شماست).</p>
                <div className="nmt-list">
                  {data.owner.map((o) => (
                    <div key={o.key} className="nmt-test" data-owner={o.key}>
                      <div className="nmt-test-row">
                        <Badge tone={o.state === "todo" ? "bad" : "warn"}>{o.state === "todo" ? "مانده" : "منتظرِ تأییدِ شما"}</Badge>
                        <b className="nmt-wrap">{o.title}</b>
                      </div>
                      <p className="nmt-detail">{o.detail}</p>
                      <p className="nmt-small nmt-wrap">
                        <b>چه کنید: </b>
                        {o.how}
                      </p>
                    </div>
                  ))}
                </div>
              </div>
            </Card>
          )}
        </>
      )}
    </div>
  );
}
