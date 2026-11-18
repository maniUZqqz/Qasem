import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { errorMessage } from "../../api/client";
import Icon from "../../components/Icon";
import { Alert, Badge, Button, Card, EmptyState, ErrorBox, PageHeader, SectionTitle, Spinner, Stat, TextArea, fa } from "../../components/ui";
import {
  type Decision,
  type Plan,
  type PlanItem,
  type PlanRef,
  type PlanResponse,
  loadPlan,
  openBugReport,
  patchItem,
  planAction,
  runItem,
} from "./api";
import "./marketing.css";

type Tone = "neutral" | "brand" | "ok" | "warn" | "bad" | "info";

const STATUS_TONE: Record<string, Tone> = {
  PLANNED: "neutral",
  DRAFTED: "info",
  WAITING_NODE: "warn",
  RUNNING: "brand",
  READY: "ok",
  NEEDS_YOU: "warn",
  FAILED: "bad",
};

const REF_STATE: Record<string, { label: string; tone: Tone }> = {
  ready: { label: "آماده", tone: "ok" },
  done: { label: "انجام شد", tone: "ok" },
  draft: { label: "پیش‌نویس", tone: "info" },
  waiting: { label: "منتظرِ سرور", tone: "warn" },
  running: { label: "در حالِ ساخت", tone: "brand" },
  failed: { label: "ناموفق", tone: "bad" },
  cancelled: { label: "لغو شد", tone: "neutral" },
  missing: { label: "پاک شده", tone: "neutral" },
};

const WEEKS: { key: 0 | 1 | 2; label: string }[] = [
  { key: 0, label: "هر دو هفته" },
  { key: 1, label: "هفتهٔ ۱" },
  { key: 2, label: "هفتهٔ ۲" },
];

function RefRow({ r }: { r: PlanRef }) {
  const st = REF_STATE[r.state] ?? { label: r.state || "—", tone: "neutral" as Tone };
  const inner = <span className="mp-ref-label">{r.label || r.type}</span>;
  return (
    <li className="mp-ref">
      {r.url ? (
        <Link to={r.url} className="mp-ref-link">
          {inner}
        </Link>
      ) : (
        inner
      )}
      <Badge tone={st.tone}>{st.label}</Badge>
      {r.note && <span className="mp-muted">{r.note}</span>}
    </li>
  );
}

function ItemCard({
  item,
  storeId,
  open,
  onToggle,
  onChanged,
}: {
  item: PlanItem;
  storeId: string;
  open: boolean;
  onToggle: () => void;
  onChanged: (i: PlanItem) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(item.draft);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!editing) setText(item.draft);
  }, [item.draft, editing]);

  const act = async (fn: () => Promise<PlanItem>) => {
    setBusy(true);
    setErr(null);
    try {
      onChanged(await fn());
    } catch (e) {
      setErr(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };
  const decide = (d: Decision) => act(() => patchItem(storeId, item.id, { decision: d }));
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(item.draft);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      setErr("کپی نشد؛ متن را با ماوس انتخاب کنید.");
    }
  };

  const tone = STATUS_TONE[item.status] ?? "neutral";
  const decided = item.decision !== "";
  return (
    <article className={`mp-item ${open ? "is-open" : ""} ${decided ? "is-decided" : ""}`} data-status={item.status} data-testid={`plan-item-${item.key}`}>
      <button type="button" className="mp-item-head" onClick={onToggle} aria-expanded={open}>
        <span className="mp-kind">{item.kind_label}</span>
        <strong className="mp-title">{item.title}</strong>
        <span className="mp-badges">
          {item.needs_node && (
            <span className="mp-gpu" title="این کار روی سرورِ پردازش (کارتِ گرافیک) ساخته می‌شود">
              GPU
            </span>
          )}
          <Badge tone={tone}>{item.status_label}</Badge>
          {decided && <Badge tone={item.decision === "skipped" ? "neutral" : "ok"}>{item.decision_label}</Badge>}
        </span>
      </button>
      {item.message && <p className="mp-msg">{item.message}</p>}
      {open && (
        <div className="mp-body">
          {item.brief && <p className="mp-brief">{item.brief}</p>}
          {item.needs_you && <Alert tone="warn" title="نیازمندِ شما">{item.needs_you}</Alert>}
          {item.error && <ErrorBox message={item.error} />}
          {item.checks.length > 0 && (
            <Alert tone="warn" title="پیش از انتشار بازبینی کنید">
              <ul className="mp-list">
                {item.checks.map((c) => (
                  <li key={c}>{c}</li>
                ))}
              </ul>
            </Alert>
          )}
          {item.refs.length > 0 && (
            <div>
              <div className="mp-sub">ساخته‌شده و وصل‌شده</div>
              <ul className="mp-refs">
                {item.refs.map((r) => (
                  <RefRow key={`${r.type}-${r.id}`} r={r} />
                ))}
              </ul>
            </div>
          )}
          {(item.draft || editing) && (
            <div>
              <div className="mp-sub">
                پیش‌نویس
                {item.polished && <span className="mp-muted"> · با هوش مصنوعی بازنویسی شد</span>}
                {item.ai_wait && <span className="mp-muted"> · بازنویسیِ هوشمند منتظرِ سرورِ پردازش/متیس است</span>}
              </div>
              {editing ? (
                <TextArea rows={10} value={text} onChange={(e) => setText(e.target.value)} className="mp-edit" />
              ) : (
                <pre className="mp-draft">{item.draft}</pre>
              )}
            </div>
          )}
          <div className="mp-meta">
            {item.when_fa && <span className="mp-muted">زمانِ پیشنهادی: {item.when_fa}</span>}
          </div>
          <ErrorBox message={err} />
          <div className="mp-actions">
            {item.url && (
              <Link to={item.url} className="u-btn u-btn-secondary u-btn-sm">
                باز کردن در بخشِ مربوط
              </Link>
            )}
            {item.draft && !editing && (
              <Button size="sm" variant="secondary" onClick={copy}>
                {copied ? "کپی شد ✓" : "کپیِ متن"}
              </Button>
            )}
            {!editing ? (
              item.draft && (
                <Button size="sm" variant="secondary" onClick={() => setEditing(true)}>
                  ویرایشِ متن
                </Button>
              )
            ) : (
              <>
                <Button
                  size="sm"
                  disabled={busy}
                  onClick={() =>
                    act(async () => {
                      const saved = await patchItem(storeId, item.id, { draft: text });
                      setEditing(false);
                      return saved;
                    })
                  }
                >
                  ذخیرهٔ متن
                </Button>
                <Button size="sm" variant="ghost" onClick={() => setEditing(false)}>
                  انصراف
                </Button>
              </>
            )}
            {!decided ? (
              <>
                <Button size="sm" disabled={busy} onClick={() => decide("approved")}>
                  تأیید
                </Button>
                <Button size="sm" variant="secondary" disabled={busy} onClick={() => decide("done")}>
                  منتشر / انجام شد
                </Button>
                <Button size="sm" variant="ghost" disabled={busy} onClick={() => decide("skipped")}>
                  رد
                </Button>
              </>
            ) : (
              <Button size="sm" variant="secondary" disabled={busy} onClick={() => decide("")}>
                برگرداندنِ تصمیم
              </Button>
            )}
            {!decided && (
              <Button size="sm" variant="ghost" disabled={busy} onClick={() => act(() => runItem(storeId, item.id))}>
                ساخت / به‌روزرسانیِ همین کار
              </Button>
            )}
            <Button size="sm" variant="ghost" onClick={() => openBugReport({ section: "plan", note: `کار «${item.title}» (${item.key}): ` })}>
              گزارشِ ایراد
            </Button>
          </div>
        </div>
      )}
    </article>
  );
}

function Counters({ plan }: { plan: Plan }) {
  const c = plan.counts;
  return (
    <div className="mp-stats">
      <Stat value={fa(c.total)} label="کار در برنامه" />
      <Stat value={fa(c.ready)} label="پیش‌نویس یا آماده برای تأیید" tone="ok" />
      <Stat value={fa(c.waiting_node)} label="منتظرِ سرورِ پردازش" tone={c.waiting_node ? "warn" : undefined} />
      <Stat value={fa(c.needs_you)} label="نیازمندِ شما" tone={c.needs_you ? "warn" : undefined} />
      <Stat value={fa(c.decided)} label="تصمیم گرفته‌اید" />
      {c.failed > 0 && <Stat value={fa(c.failed)} label="ناموفق" tone="bad" />}
    </div>
  );
}

export default function MarketingPlanPage() {
  const { id = "" } = useParams<{ id: string }>();
  const [data, setData] = useState<PlanResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [week, setWeek] = useState<0 | 1 | 2>(0);
  const [group, setGroup] = useState<string>("");
  const [status, setStatus] = useState<string>("");
  const [openKeys, setOpenKeys] = useState<Set<string>>(new Set());
  const alive = useRef(true);

  const load = useCallback(async () => {
    try {
      const r = await loadPlan(id);
      if (alive.current) {
        setData(r);
        setError(null);
      }
    } catch (e) {
      if (alive.current) setError(errorMessage(e));
    }
  }, [id]);

  useEffect(() => {
    alive.current = true;
    void load();
    return () => {
      alive.current = false;
    };
  }, [load]);

  const plan = data && data.plan ? data.plan : null;
  const active = !!plan && (plan.running || plan.counts.waiting_node > 0 || (plan.counts.by_status.RUNNING ?? 0) > 0);
  useEffect(() => {
    const t = window.setInterval(() => {
      if (!document.hidden) void load();
    }, active ? 15000 : 60000);
    return () => window.clearInterval(t);
  }, [active, load]);

  const act = async (action: "create" | "run" | "create_run" | "restart" | "refresh", note?: string) => {
    setBusy(true);
    setError(null);
    try {
      const r = await planAction(id, action);
      setData({ plan: r.plan });
      setNotice(note ?? null);
      if (action !== "refresh" && action !== "create") window.setTimeout(() => void load(), 4000);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  const replaceItem = (item: PlanItem) =>
    setData((d) => (d && d.plan ? { plan: { ...d.plan, items: d.plan.items.map((x) => (x.id === item.id ? item : x)) } } : d));

  const groups = useMemo(() => (plan ? Array.from(new Set(plan.items.map((i) => i.group))) : []), [plan]);
  const visible = useMemo(() => {
    if (!plan) return [];
    return plan.items.filter((i) => (week === 0 || i.week === week) && (!group || i.group === group) && (!status || i.status === status));
  }, [plan, week, group, status]);
  const days = useMemo(() => {
    const by = new Map<number, PlanItem[]>();
    for (const i of visible) by.set(i.day, [...(by.get(i.day) ?? []), i]);
    return Array.from(by.entries()).sort((a, b) => a[0] - b[0]);
  }, [visible]);

  const toggle = (k: string) =>
    setOpenKeys((s) => {
      const n = new Set(s);
      if (n.has(k)) n.delete(k);
      else n.add(k);
      return n;
    });

  if (!data && !error) {
    return (
      <div className="mp-center">
        <Spinner />
      </div>
    );
  }

  return (
    <div className="mp-root">
      <PageHeader
        title="برنامهٔ بازاریابی"
        subtitle="برنامهٔ دو‌هفته‌ایِ آماده: برای هر روز، کارِ مشخص، پیش‌نویسِ واقعی و لینک به بخشی که می‌سازدش. هیچ‌چیز خودکار منتشر یا فرستاده نمی‌شود."
        actions={
          plan ? (
            <>
              <Button variant="secondary" size="sm" disabled={busy} onClick={() => act("refresh")}>
                <Icon name="refresh" size={14} /> تازه‌سازیِ وضعیت
              </Button>
              <Button size="sm" disabled={busy || plan.running} onClick={() => act("run", "اجرا شروع شد؛ چند ثانیه بعد وضعیت‌ها تازه می‌شود.")}>
                <Icon name="play" size={14} /> ساخت و اجرای دوباره
              </Button>
            </>
          ) : undefined
        }
      />
      <ErrorBox message={error} />
      {notice && <Alert tone="ok">{notice}</Alert>}

      {!plan && data && !data.plan && (
        <Card>
          <SectionTitle>برنامه‌ای هنوز ساخته نشده</SectionTitle>
          <p className="mp-muted">
            برنامه از واقعیت‌هایی که خودتان در NM ثبت کرده‌اید ساخته می‌شود: نام و توضیح، مخاطب، لحن، شخصیتِ گفتار و محصول‌ها. چیزی از خودش نمی‌سازد (قیمت، آمار یا نظرِ مشتری).
            شروع از فردا ({data.default_start_fa}) است.
          </p>
          <ul className="mp-list">
            <li>
              <strong>{data.facts.name || "فروشگاه"}</strong>
              {data.facts.business ? ` — ${data.facts.business}` : ""}
            </li>
            {data.facts.audience && <li>مخاطب: {data.facts.audience}</li>}
            {data.facts.products.length > 0 && <li>محصول‌ها: {data.facts.products.slice(0, 5).join("، ")}</li>}
          </ul>
          {data.facts.gaps.length > 0 && (
            <Alert tone="warn" title="چیزهایی که خالی است (برنامه با [ ] جایشان را نگه می‌دارد)">
              <ul className="mp-list">
                {data.facts.gaps.map((g) => (
                  <li key={g}>{g}</li>
                ))}
              </ul>
            </Alert>
          )}
          <div className="mp-actions">
            <Button disabled={busy} onClick={() => act("create_run", "برنامه ساخته شد و اجرا شروع شد.")}>
              {busy ? <Spinner size={14} /> : <Icon name="rocket" size={14} />} ساخت و اجرا
            </Button>
            <Button variant="secondary" disabled={busy} onClick={() => act("create")}>
              فقط ساختنِ برنامه (بدونِ اجرا)
            </Button>
          </div>
        </Card>
      )}

      {plan && (
        <>
          <Card>
            <h2 className="mp-plan-name">{plan.name}</h2>
            <p className="mp-muted">{plan.goal}</p>
            <p className="mp-muted">
              شروع: {plan.start_fa} · {fa(plan.days)} روز
              {plan.last_run_at ? ` · آخرین اجرا: ${new Date(plan.last_run_at).toLocaleString("fa-IR")}` : ""}
              {plan.running ? " · در حالِ اجرا…" : ""}
            </p>
            <Counters plan={plan} />
            {plan.node.online ? (
              <Alert tone="ok" title="سرورِ پردازش روشن است">
                {plan.node.name} · کارهای GPU (تصویر FLUX، موشن، گوینده، موسیقی، ویدیو) در صف اجرا می‌شوند و وضعیتشان خودکار تازه می‌شود.
              </Alert>
            ) : (
              <Alert tone="warn" title="سرورِ پردازش خاموش است">
                کارهای GPU در صفِ ماندگار گذاشته شده‌اند و بی‌هیچ کلیک با روشن‌شدنِ سرور اجرا می‌شوند؛ اینجا خودکار «آماده» می‌شوند.
              </Alert>
            )}
            {!plan.ai.ok && (
              <Alert tone="info" title="هوش مصنوعیِ متن الان در دسترس نیست">
                {plan.ai.why || "پیش‌نویس‌ها قاعده‌محورند."} با برگشتنِ سرورِ پردازش (اول لوکال، بعد متیس) خودکار با لحنِ شخصیتِ برند بازنویسی می‌شوند.
              </Alert>
            )}
            {plan.summary.facts && plan.summary.facts.gaps.length > 0 && (
              <Alert tone="info" title="برای دقیق‌تر شدنِ برنامه">
                <ul className="mp-list">
                  {plan.summary.facts.gaps.map((g) => (
                    <li key={g}>{g}</li>
                  ))}
                </ul>
              </Alert>
            )}
          </Card>

          <div className="mp-filters" role="toolbar" aria-label="فیلتر">
            <div className="mp-chips">
              {WEEKS.map((w) => (
                <button key={w.key} type="button" className="mp-chip" aria-pressed={week === w.key} onClick={() => setWeek(w.key)}>
                  {w.label}
                </button>
              ))}
            </div>
            <div className="mp-chips">
              <button type="button" className="mp-chip" aria-pressed={group === ""} onClick={() => setGroup("")}>
                همهٔ بخش‌ها
              </button>
              {groups.map((g) => (
                <button key={g} type="button" className="mp-chip" aria-pressed={group === g} onClick={() => setGroup(g)}>
                  {plan.groups[g] ?? g}
                </button>
              ))}
            </div>
            <div className="mp-chips">
              <button type="button" className="mp-chip" aria-pressed={status === ""} onClick={() => setStatus("")}>
                همهٔ وضعیت‌ها
              </button>
              {Object.entries(plan.status_labels).map(([k, v]) => (
                <button key={k} type="button" className="mp-chip" aria-pressed={status === k} onClick={() => setStatus(k)}>
                  {v} ({fa(plan.counts.by_status[k] ?? 0)})
                </button>
              ))}
            </div>
          </div>

          {days.length === 0 && (
            <EmptyState title="کاری با این فیلتر نیست">فیلتر را عوض کنید.</EmptyState>
          )}
          {days.map(([day, items]) => (
            <section key={day} className="mp-day">
              <h3 className="mp-day-head">
                روز {fa(day)} — {items[0].weekday} {items[0].date_fa}
              </h3>
              <div className="mp-items">
                {items.map((i) => (
                  <ItemCard key={i.id} item={i} storeId={id} open={openKeys.has(i.key)} onToggle={() => toggle(i.key)} onChanged={replaceItem} />
                ))}
              </div>
            </section>
          ))}

          <Card>
            <SectionTitle>گزارشِ آخرین اجرا</SectionTitle>
            {plan.last_run && "log" in plan.last_run && plan.last_run.log && plan.last_run.log.length > 0 ? (
              <pre className="mp-draft mp-log">{plan.last_run.log.join("\n")}</pre>
            ) : (
              <p className="mp-muted">هنوز اجرایی ثبت نشده.</p>
            )}
            <p className="mp-muted">
              هر ۱۰ دقیقه یک تیکِ پس‌زمینه وضعیت‌ها را از چیزهای ساخته‌شده تازه می‌کند و کارهای منتظرِ هوش مصنوعی یا سرورِ پردازش را پیش می‌برد.
              راهنمای آزمونِ بخش‌ها: <Link to={`/stores/${id}/test-guide`}>محتوا ⇐ راهنمای آزمون</Link>.
            </p>
          </Card>
        </>
      )}
    </div>
  );
}
