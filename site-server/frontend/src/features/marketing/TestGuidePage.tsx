import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { errorMessage } from "../../api/client";
import { faDateTime } from "../../components/fmt";
import { Alert, Badge, Button, Card, EmptyState, ErrorBox, PageHeader, SectionTitle, Spinner, fa } from "../../components/ui";
import { useAuth } from "../auth/AuthContext";
import { type BugReport, type GuideResponse, type GuideSection, loadBugs, loadGuide, openBugReport, setBugState } from "./api";
import "./marketing.css";

const KEY = (id: string) => `nm-guide-tested-${id}`;

function readTested(id: string): Set<string> {
  try {
    const raw = localStorage.getItem(KEY(id));
    return new Set(raw ? (JSON.parse(raw) as string[]) : []);
  } catch {
    return new Set(); // حالتِ خصوصی یا ذخیره‌سازیِ بسته
  }
}

function writeTested(id: string, s: Set<string>) {
  try {
    localStorage.setItem(KEY(id), JSON.stringify(Array.from(s)));
  } catch {
    /* فقط راحتیِ همین مرورگر است */
  }
}

function SectionCard({
  s,
  open,
  tested,
  onToggle,
  onTested,
}: {
  s: GuideSection;
  open: boolean;
  tested: boolean;
  onToggle: () => void;
  onTested: (v: boolean) => void;
}) {
  return (
    <article className={`tg-card ${tested ? "is-tested" : ""}`} data-testid={`guide-${s.key}`}>
      <button type="button" className="tg-head" onClick={onToggle} aria-expanded={open}>
        <span className="tg-title">
          {tested ? "✓ " : ""}
          {s.title}
        </span>
        <span className="tg-chips">
          <Badge tone="neutral">حدود {fa(s.minutes)} دقیقه</Badge>
          {s.staff && <Badge tone="info">کارکنان</Badge>}
          {s.node && <Badge tone="warn">سرورِ پردازش</Badge>}
          {s.plan.total > 0 && s.plan.waiting_node > 0 && <Badge tone="warn">{fa(s.plan.waiting_node)} کار منتظرِ سرور</Badge>}
          {s.plan.total > 0 && s.plan.waiting_node === 0 && s.plan.ready > 0 && <Badge tone="ok">{fa(s.plan.ready)} کارِ آماده</Badge>}
          {s.plan.needs_you > 0 && <Badge tone="warn">{fa(s.plan.needs_you)} نیازمندِ شما</Badge>}
          {s.open_bugs > 0 && <Badge tone="bad">{fa(s.open_bugs)} ایرادِ باز</Badge>}
        </span>
      </button>
      {open && (
        <div className="tg-body">
          <div className="tg-row">
            {s.url ? (
              <Link to={s.url} className="u-btn u-btn-primary u-btn-sm">
                باز کردنِ این بخش
              </Link>
            ) : null}
            <span className="mp-muted">صفحه‌ها: {s.pages.map((p) => p.title).join("، ")}</span>
          </div>
          <div>
            <h4>چه کار کنید</h4>
            <ol>
              {s.steps.map((x) => (
                <li key={x}>{x}</li>
              ))}
            </ol>
          </div>
          <div>
            <h4>چه باید ببینید</h4>
            <ul>
              {s.expect.map((x) => (
                <li key={x}>{x}</li>
              ))}
            </ul>
          </div>
          {s.node && (
            <div className="tg-node">
              <strong>منتظرِ سرورِ پردازش: </strong>
              {s.node}
            </div>
          )}
          <div className="tg-row">
            <label className="tg-check">
              <input type="checkbox" checked={tested} onChange={(e) => onTested(e.target.checked)} /> این بخش را آزمودم
            </label>
            <Button size="sm" variant="secondary" onClick={() => openBugReport({ section: s.key })}>
              گزارشِ ایراد برای این بخش
            </Button>
          </div>
        </div>
      )}
    </article>
  );
}

export default function TestGuidePage() {
  const { id = "" } = useParams<{ id: string }>();
  const { user } = useAuth();
  const [data, setData] = useState<GuideResponse | null>(null);
  const [bugs, setBugs] = useState<BugReport[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [tested, setTested] = useState<Set<string>>(() => readTested(id));
  const [open, setOpen] = useState<Set<string>>(new Set());
  const [onlyTodo, setOnlyTodo] = useState(false);
  const [phase, setPhase] = useState<number | null>(null);

  const load = useCallback(async () => {
    try {
      setData(await loadGuide(id));
      setBugs(await loadBugs(id).catch(() => []));
      setError(null);
    } catch (e) {
      setError(errorMessage(e));
    }
  }, [id]);

  useEffect(() => {
    setTested(readTested(id));
    void load();
  }, [id, load]);

  const mark = (key: string, v: boolean) =>
    setTested((s) => {
      const n = new Set(s);
      if (v) n.add(key);
      else n.delete(key);
      writeTested(id, n);
      return n;
    });
  const toggle = (key: string) =>
    setOpen((s) => {
      const n = new Set(s);
      if (n.has(key)) n.delete(key);
      else n.add(key);
      return n;
    });

  const sections = useMemo(() => data?.sections ?? [], [data]);
  const phases = useMemo(() => Array.from(new Set(sections.map((s) => s.phase))).sort((a, b) => a - b), [sections]);
  const shown = useMemo(() => sections.filter((s) => (phase === null || s.phase === phase) && (!onlyTodo || !tested.has(s.key))), [sections, phase, onlyTodo, tested]);
  const doneCount = sections.filter((s) => tested.has(s.key)).length;
  const pct = sections.length ? Math.round((doneCount / sections.length) * 100) : 0;

  if (!data && !error) {
    return (
      <div className="mp-center">
        <Spinner />
      </div>
    );
  }

  let lastPhase = -1;
  return (
    <div className="tg-root">
      <PageHeader
        title="راهنمای آزمونِ بخش‌ها"
        subtitle="برای هر بخشِ پنل، به بهترین ترتیب: کجاست، چه چیزی را بزنید، چه باید ببینید و چه چیزی منتظرِ سرورِ پردازش است. ایرادی دیدید «گزارشِ ایراد» را بزنید."
        actions={
          <Link to={`/stores/${id}/marketing-plan`} className="u-btn u-btn-secondary u-btn-sm">
            برنامهٔ بازاریابی
          </Link>
        }
      />
      <ErrorBox message={error} />
      {data && (
        <>
          <Card>
            <div className="tg-row">
              <strong>
                {fa(doneCount)} از {fa(sections.length)} بخش آزموده شد
              </strong>
              <span className="mp-muted">(تیک‌ها فقط در همین مرورگر می‌ماند)</span>
            </div>
            <div className="tg-progress" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
              <span style={{ width: `${pct}%` }} />
            </div>
            {data.node.online ? (
              <Alert tone="ok" title="سرورِ پردازش روشن است">
                {data.node.name}: همهٔ بخش‌هایی که «منتظرِ سرور» نوشته‌اند الان اجرا می‌شوند؛ وضعیتشان را در «برنامهٔ بازاریابی» ببینید.
              </Alert>
            ) : (
              <Alert tone="warn" title="سرورِ پردازش خاموش است">
                بخش‌های دارای نشانِ «سرورِ پردازش» تا روشن‌شدنِ سرور کار را در صف نگه می‌دارند و بعد خودشان اجرا می‌شوند؛ آزمونشان را بعد از روشن‌شدن انجام دهید.
              </Alert>
            )}
            {!data.has_plan && (
              <Alert tone="info" title="برنامهٔ بازاریابی هنوز ساخته نشده">
                برای دیدنِ کارهای آماده در هر بخش اول <Link to={`/stores/${id}/marketing-plan`}>برنامه را بسازید و اجرا کنید</Link>.
              </Alert>
            )}
            <div className="mp-chips" style={{ marginTop: 8 }}>
              <button type="button" className="mp-chip" aria-pressed={phase === null} onClick={() => setPhase(null)}>
                همهٔ مرحله‌ها
              </button>
              {phases.map((p) => (
                <button key={p} type="button" className="mp-chip" aria-pressed={phase === p} onClick={() => setPhase(p)}>
                  {data.phases[String(p)] ?? p}
                </button>
              ))}
              <button type="button" className="mp-chip" aria-pressed={onlyTodo} onClick={() => setOnlyTodo((v) => !v)}>
                فقط آزموده‌نشده‌ها
              </button>
            </div>
          </Card>

          {shown.length === 0 && <EmptyState title="همه آزموده شد">فیلتر را عوض کنید.</EmptyState>}
          {shown.map((s) => {
            const head = s.phase !== lastPhase;
            lastPhase = s.phase;
            return (
              <div key={s.key}>
                {head && <h3 className="tg-phase">{s.phase_title}</h3>}
                <SectionCard s={s} open={open.has(s.key)} tested={tested.has(s.key)} onToggle={() => toggle(s.key)} onTested={(v) => mark(s.key, v)} />
              </div>
            );
          })}

          <Card>
            <SectionTitle>گزارش‌هایی که فرستاده‌اید</SectionTitle>
            {bugs.length === 0 ? (
              <p className="mp-muted">هنوز گزارشی نیست. هر ایرادی دیدید دکمهٔ «ایراد؟» (کنارِ نسخه، پایینِ صفحه) را بزنید.</p>
            ) : (
              <div className="tg-bugs">
                {bugs.slice(0, 30).map((b) => (
                  <div key={b.id} className="tg-bug">
                    <div className="tg-row">
                      <strong>
                        #{fa(b.id)} · {b.section_title || b.section}
                      </strong>
                      <Badge tone={b.state === "fixed" ? "ok" : b.state === "wontfix" ? "neutral" : "warn"}>{b.state_label}</Badge>
                      <span className="mp-muted">{faDateTime(b.created_at)}</span>
                      {user?.is_staff && (
                        <select
                          className="u-input"
                          style={{ width: "auto" }}
                          value={b.state}
                          onChange={async (e) => {
                            const r = await setBugState(b.id, e.target.value as BugReport["state"]);
                            setBugs((arr) => arr.map((x) => (x.id === r.id ? r : x)));
                          }}
                        >
                          <option value="new">جدید</option>
                          <option value="seen">دیده شد</option>
                          <option value="fixed">رفع شد</option>
                          <option value="wontfix">رفع نمی‌شود</option>
                        </select>
                      )}
                    </div>
                    <div>{b.note}</div>
                    {b.page_url && <div className="mp-muted">{b.page_url}</div>}
                    {b.screenshot && <img src={b.screenshot} alt="عکسِ گزارش" />}
                    {b.response && <div className="mp-muted">پاسخ: {b.response}</div>}
                  </div>
                ))}
              </div>
            )}
          </Card>
        </>
      )}
    </div>
  );
}
