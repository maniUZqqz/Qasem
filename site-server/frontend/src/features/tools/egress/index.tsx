import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { api, errorMessage } from "../../../api/client";
import Icon from "../../../components/Icon";
import { Alert, Badge, Button, Card, ErrorBox, Field, Input, PageHeader, Select, Spinner, Table, fa } from "../../../components/ui";
import {
  SCHEME_FA,
  SOURCE_FA,
  msText,
  routeText,
  stateText,
  stateTone,
  whenText,
  type Health,
  type Overview,
  type ProxyRow,
  type ServiceRow,
  type TestResult,
} from "./model";
import "./egress.css";

/**
 * «پراکسی و VPN» (فقط کارکنان، ۱۴۰۵/۰۸/۲۷): یک جا برای پراکسیِ سرویس‌های فیلترشده.
 *
 * فقط سرویس‌های همین جدول (تلگرام، اینستاگرام، واتساپ و Meta، موتورهای جست‌وجو، هوشِ مصنوعیِ خارجی، نقشه) می‌توانند از پراکسی بروند و
 * پیش‌فرضِ همه «مستقیم» است؛ سایت، سرویس‌های ایرانی (بله، ایتا، روبیکا، زرین‌پال، نوین‌هاب، متیس)، سرورِ پردازش و ابزارهای محلی همیشه
 * مستقیم‌اند. پراکسی هرگز متغیرِ محیطیِ کلِ سرور نمی‌شود. رمزِ پراکسی هیچ‌جا نمایش داده نمی‌شود.
 */

const POLL_MS = 30000;

type FormState = {
  id: number | null;
  name: string;
  url: string;
  username: string;
  password: string;
  clear_password: boolean;
  enabled: boolean;
  note: string;
  hasPassword: boolean;
};

const EMPTY_FORM: FormState = { id: null, name: "", url: "", username: "", password: "", clear_password: false, enabled: true, note: "", hasPassword: false };

function formOf(p: ProxyRow | null): FormState {
  if (!p) return { ...EMPTY_FORM };
  return { id: p.id, name: p.name, url: p.address, username: p.username, password: "", clear_password: false, enabled: p.enabled, note: p.note, hasPassword: p.has_password };
}

function bodyOf(f: FormState): Record<string, unknown> {
  const body: Record<string, unknown> = { name: f.name.trim(), url: f.url.trim(), username: f.username.trim(), enabled: f.enabled, note: f.note.trim() };
  if (f.password) body.password = f.password;
  if (f.clear_password) body.clear_password = true;
  return body;
}

function Ltr({ children }: { children: React.ReactNode }) {
  return <span dir="ltr" className="eg-ltr">{children}</span>;
}

function TestPanel({ title, result, testid = "test-result" }: { title: string; result: TestResult; testid?: string }) {
  const failed = !result.ok;
  return (
    <div className="eg-test" data-testid={testid}>
      <div className="eg-test-head">
        <strong>{title}</strong>
        <Badge tone={failed ? "bad" : "ok"}>{failed ? "ناموفق" : "موفق"}</Badge>
        <span className="eg-muted">{whenText(result.checked_at)}</span>
      </div>
      {result.proxy_error ? (
        <Alert tone="bad" title="پراکسی وصل نشد">{result.proxy_error}</Alert>
      ) : (
        <>
          <div className="eg-kv">
            <div><span>آدرسی که سرویس‌ها می‌بینند</span><b><Ltr>{result.ip || "—"}</Ltr></b></div>
            <div><span>کشور</span><b>{[result.country, result.country_code && `(${result.country_code})`].filter(Boolean).join(" ") || "—"}</b></div>
            <div><span>شهر</span><b>{result.city || "—"}</b></div>
            <div><span>اپراتور / سازمان</span><b><Ltr>{result.org || "—"}</Ltr></b></div>
            <div><span>تأخیر</span><b>{msText(result.latency_ms)}</b></div>
          </div>
          {result.summary && <p className="eg-muted" style={{ marginTop: 8 }}>{result.summary}</p>}
          {result.targets.length > 0 && (
            <Table>
              <thead>
                <tr><th>مقصد</th><th>نتیجه</th><th>پاسخ HTTP</th><th>زمان</th></tr>
              </thead>
              <tbody>
                {result.targets.map((t) => (
                  <tr key={`${t.service || ""}-${t.label}`}>
                    <td><Ltr>{t.label}</Ltr></td>
                    <td>{t.ok ? <Badge tone="ok">در دسترس</Badge> : <span className="eg-bad">{t.error || "در دسترس نیست"}</span>}</td>
                    <td>{t.status ?? "—"}</td>
                    <td>{msText(t.ms)}</td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
        </>
      )}
    </div>
  );
}

function HealthBadge({ s }: { s: ServiceRow }) {
  const h: Health = s.health;
  if (s.effective === "direct") {
    if (!h || h.state === "unknown" || h.stale) return <Badge tone="neutral">مستقیم</Badge>;
    return <Badge tone={stateTone(h.state)}>مستقیم · {stateText(h.state)}</Badge>;
  }
  if (!h || h.state === "unknown") return <Badge tone="neutral">از پراکسی · آزمایش نشده</Badge>;
  if (h.stale) return <Badge tone="neutral">از پراکسی · نتیجهٔ قدیمی</Badge>;
  return <Badge tone={stateTone(h.state)}>از پراکسی · {stateText(h.state)}</Badge>;
}

function ProxyForm({
  form,
  setForm,
  busy,
  onSave,
  onTest,
  onCancel,
  error,
  test,
}: {
  form: FormState;
  setForm: (f: FormState) => void;
  busy: string | null;
  onSave: () => void;
  onTest: () => void;
  onCancel: () => void;
  error: string | null;
  test: TestResult | null;
}) {
  const set = (patch: Partial<FormState>) => setForm({ ...form, ...patch });
  return (
    <Card>
      <div data-testid="proxy-form">
        <h3 className="text-base font-extrabold" style={{ color: "var(--text)", marginBottom: 12 }}>
          {form.id ? "ویرایشِ پراکسی" : "پراکسیِ تازه"}
        </h3>
        <div className="eg-form">
          <Field label="نام" hint="هر نامی که خودتان بشناسید؛ مثلاً «VPN دفتر».">
            <Input value={form.name} onChange={(e) => set({ name: e.target.value })} placeholder="VPN دفتر" data-testid="proxy-name" />
          </Field>
          <Field
            label="نشانیِ پراکسی"
            hint="نوع://نشانی:پورت. نمونه‌ها: socks5h://127.0.0.1:10808 (کلاینتِ V2Ray / Xray روی همین سرور) یا http://host:8080 یا user:pass@host:port."
          >
            <Input dir="ltr" value={form.url} onChange={(e) => set({ url: e.target.value })} placeholder="socks5h://127.0.0.1:10808" data-testid="proxy-url" />
          </Field>
          <Field label="نامِ کاربری (اگر لازم است)">
            <Input dir="ltr" value={form.username} onChange={(e) => set({ username: e.target.value, clear_password: false })} autoComplete="off" data-testid="proxy-user" />
          </Field>
          <Field label="رمز (اگر لازم است)" hint={form.hasPassword ? "رمزِ قبلی ذخیره است و نمایش داده نمی‌شود؛ خالی بگذارید تا همان بماند." : undefined}>
            <Input
              dir="ltr"
              type="password"
              value={form.password}
              onChange={(e) => set({ password: e.target.value, clear_password: false })}
              autoComplete="new-password"
              placeholder={form.hasPassword ? "•••••• (ذخیره‌شده)" : ""}
              data-testid="proxy-password"
            />
          </Field>
          <Field label="یادداشت">
            <Input value={form.note} onChange={(e) => set({ note: e.target.value })} data-testid="proxy-note" />
          </Field>
        </div>
        <div className="eg-row" style={{ marginTop: 10 }}>
          <label className="eg-check">
            <input type="checkbox" checked={form.enabled} onChange={(e) => set({ enabled: e.target.checked })} data-testid="proxy-enabled" />
            <span>روشن (اگر خاموش باشد، سرویس‌هایش فعلاً مستقیم می‌روند)</span>
          </label>
          {form.id !== null && form.hasPassword && (
            <label className="eg-check">
              <input type="checkbox" checked={form.clear_password} onChange={(e) => set({ clear_password: e.target.checked, password: "" })} />
              <span>رمزِ ذخیره‌شده پاک شود</span>
            </label>
          )}
        </div>
        <ErrorBox message={error} />
        <div className="eg-row" style={{ marginTop: 12 }}>
          <Button onClick={onSave} disabled={busy !== null} data-testid="proxy-save">
            {busy === "save" ? "در حالِ ذخیره…" : "ذخیره"}
          </Button>
          <Button variant="secondary" onClick={onTest} disabled={busy !== null || !form.url.trim()} data-testid="proxy-test">
            {busy === "test" ? "در حالِ آزمایش…" : "آزمایش (بدونِ ذخیره)"}
          </Button>
          <Button variant="ghost" onClick={onCancel} disabled={busy !== null}>انصراف</Button>
        </div>
        {test && <div style={{ marginTop: 12 }}><TestPanel title="نتیجهٔ آزمایش" result={test} testid="form-test-result" /></div>}
      </div>
    </Card>
  );
}

function ProxyCard({
  p,
  busy,
  test,
  onEdit,
  onTest,
  onDelete,
  onToggle,
  onRouteAll,
}: {
  p: ProxyRow;
  busy: string | null;
  test: TestResult | null;
  onEdit: () => void;
  onTest: () => void;
  onDelete: () => void;
  onToggle: () => void;
  onRouteAll: () => void;
}) {
  const shown = test ?? (p.last_test && "ok" in p.last_test && p.last_test.checked_at ? (p.last_test as TestResult) : null);
  return (
    <Card>
      <div data-testid={`proxy-${p.id}`}>
        <div className="eg-row" style={{ justifyContent: "space-between" }}>
          <div style={{ minWidth: 0 }}>
            <div className="eg-row">
              <h3 className="text-base font-extrabold" style={{ color: "var(--text)" }}>{p.name}</h3>
              <Badge tone={p.enabled ? "ok" : "neutral"}>{p.enabled ? "روشن" : "خاموش"}</Badge>
              {p.is_local && <Badge tone="info">روی همین سرور</Badge>}
              {p.has_password && <Badge tone="neutral">رمز ذخیره است</Badge>}
            </div>
            <div className="eg-muted"><Ltr>{p.address}</Ltr>{p.username ? <> · کاربر: <Ltr>{p.username}</Ltr></> : null}</div>
            {p.note && <div className="eg-muted">{p.note}</div>}
            <div className="eg-muted">
              سرویس‌هایی که از آن می‌روند: {p.services.length ? p.services.join("، ") : "هیچ‌کدام"}
            </div>
          </div>
          <div className="eg-row">
            <Button size="sm" onClick={onTest} disabled={busy !== null} data-testid={`proxy-${p.id}-test`}>
              {busy === `test:${p.id}` ? "در حالِ آزمایش…" : "آزمایش"}
            </Button>
            <Button size="sm" variant="secondary" onClick={onEdit} disabled={busy !== null}>ویرایش</Button>
            <Button size="sm" variant="secondary" onClick={onToggle} disabled={busy !== null}>{p.enabled ? "خاموش کن" : "روشن کن"}</Button>
            <Button size="sm" variant="danger" onClick={onDelete} disabled={busy !== null}>حذف</Button>
          </div>
        </div>
        <div className="eg-row" style={{ marginTop: 8 }}>
          <Button size="sm" variant="secondary" onClick={onRouteAll} disabled={busy !== null} data-testid={`proxy-${p.id}-all`}>
            همهٔ سرویس‌های جدول از این پراکسی بروند
          </Button>
        </div>
        {shown && <div style={{ marginTop: 12 }}><TestPanel title={test ? "نتیجهٔ آزمایش" : "آخرین آزمایش"} result={shown} testid={`proxy-${p.id}-result`} /></div>}
      </div>
    </Card>
  );
}

export default function EgressPage() {
  const [params] = useSearchParams();
  const focus = params.get("service") || "";
  const [data, setData] = useState<Overview | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [form, setForm] = useState<FormState | null>(null);
  const [formErr, setFormErr] = useState<string | null>(null);
  const [formTest, setFormTest] = useState<TestResult | null>(null);
  const [tests, setTests] = useState<Record<number, TestResult>>({});
  const [direct, setDirect] = useState<TestResult | null>(null);
  const alive = useRef(true);
  const scrolled = useRef(false);

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  const load = useCallback(async () => {
    try {
      const { data: d } = await api.get<Overview>("/egress/overview/");
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

  useEffect(() => {
    const t = window.setInterval(() => {
      if (document.visibilityState === "visible" && busy === null) void load();
    }, POLL_MS);
    return () => window.clearInterval(t);
  }, [load, busy]);

  useEffect(() => {
    if (!data || !focus || scrolled.current) return;
    const el = document.querySelector(`[data-service="${CSS.escape(focus)}"]`);
    if (el) {
      scrolled.current = true;
      el.scrollIntoView({ block: "center" });
    }
  }, [data, focus]);

  const run = async (key: string, fn: () => Promise<void>) => {
    setBusy(key);
    setErr(null);
    setNotice(null);
    try {
      await fn();
    } catch (e) {
      if (alive.current) setErr(errorMessage(e));
    } finally {
      if (alive.current) setBusy(null);
    }
  };

  const saveForm = async () => {
    if (!form) return;
    setBusy("save");
    setFormErr(null);
    setNotice(null);
    try {
      if (form.id) await api.patch(`/egress/proxies/${form.id}/`, bodyOf(form));
      else await api.post("/egress/proxies/", bodyOf(form));
      await load();
      setNotice(form.id ? "پراکسی ذخیره شد." : "پراکسی افزوده شد؛ حالا در جدولِ پایین مسیرِ سرویس‌ها را به آن بدهید.");
      setForm(null);
      setFormTest(null);
    } catch (e) {
      setFormErr(errorMessage(e));
    } finally {
      setBusy(null);
    }
  };

  const testForm = async () => {
    if (!form) return;
    setBusy("test");
    setFormErr(null);
    setFormTest(null);
    setNotice(null);
    try {
      const body = bodyOf(form);
      if (form.id) body.id = form.id;
      const { data: r } = await api.post<TestResult>("/egress/proxies/test/", body);
      setFormTest(r);
    } catch (e) {
      setFormErr(errorMessage(e));
    } finally {
      setBusy(null);
    }
  };

  const testSaved = (p: ProxyRow) =>
    run(`test:${p.id}`, async () => {
      const { data: r } = await api.post<TestResult>(`/egress/proxies/${p.id}/test/`, {});
      setTests((cur) => ({ ...cur, [p.id]: r }));
      await load();
    });

  const removeProxy = (p: ProxyRow) => {
    if (!window.confirm(`پراکسیِ «${p.name}» پاک شود؟ سرویس‌هایی که از آن می‌روند دوباره مستقیم می‌شوند.`)) return;
    void run(`del:${p.id}`, async () => {
      await api.delete(`/egress/proxies/${p.id}/`);
      await load();
      setNotice(`پراکسیِ «${p.name}» پاک شد؛ سرویس‌هایش مستقیم شدند.`);
    });
  };

  const toggleProxy = (p: ProxyRow) =>
    run(`toggle:${p.id}`, async () => {
      await api.patch(`/egress/proxies/${p.id}/`, { enabled: !p.enabled });
      await load();
      setNotice(p.enabled ? `«${p.name}» خاموش شد؛ سرویس‌هایش فعلاً مستقیم می‌روند.` : `«${p.name}» روشن شد.`);
    });

  const setRoutes = (routes: Record<string, number | null>, message: string) =>
    run("routes", async () => {
      await api.put("/egress/routes/", { routes });
      await load();
      setNotice(message);
    });

  const routeAll = (p: ProxyRow) => {
    if (!data) return;
    const routes: Record<string, number | null> = {};
    data.services.forEach((s) => (routes[s.key] = p.id));
    void setRoutes(routes, `همهٔ سرویس‌های جدول از پراکسیِ «${p.name}» می‌روند. حالا «آزمایشِ همه» را بزنید.`);
  };

  const allDirect = () => {
    if (!data) return;
    const routes: Record<string, number | null> = {};
    data.services.forEach((s) => (routes[s.key] = null));
    void setRoutes(routes, "همهٔ سرویس‌ها مستقیم شدند.");
  };

  const setMaster = (enabled: boolean) =>
    run("master", async () => {
      await api.put("/egress/switch/", { enabled });
      await load();
      setNotice(enabled ? "پراکسی روشن شد؛ مسیرهای ذخیره‌شده دوباره کار می‌کنند." : "پراکسی خاموش شد؛ همهٔ سرویس‌ها مستقیم می‌روند (جدولِ مسیرها نگه داشته شد).");
    });

  const testService = (s: ServiceRow) =>
    run(`svc:${s.key}`, async () => {
      await api.post(`/egress/services/${s.key}/test/`, {});
      await load();
      setNotice(`«${s.title}» آزمایش شد.`);
    });

  const testAllRouted = () =>
    run("all", async () => {
      await api.post("/egress/check-routed/", {});
      await load();
      setNotice("سرویس‌هایی که از پراکسی می‌روند آزمایش شدند.");
    });

  const testDirect = () =>
    run("direct", async () => {
      const { data: r } = await api.post<TestResult>("/egress/test-direct/", {});
      setDirect(r);
    });

  if (!data) {
    return (
      <div className="eg-page" data-testid="egress-page">
        <PageHeader title="پراکسی و VPN" />
        {err ? <ErrorBox message={err} /> : <div style={{ padding: 40, textAlign: "center" }}><Spinner /></div>}
      </div>
    );
  }

  const routed = data.services.filter((s) => s.effective === "proxy");
  const enabledProxies = data.proxies.filter((p) => p.enabled);

  return (
    <div className="eg-page" data-testid="egress-page">
      <PageHeader
        title="پراکسی و VPN"
        subtitle="فقط سرویس‌هایی که از ایران فیلتر یا بسته‌اند (تلگرام، اینستاگرام، واتساپ و …) از پراکسی می‌روند؛ همهٔ بقیه همیشه مستقیم‌اند."
        actions={
          <>
            <Button variant="secondary" size="sm" onClick={() => void load()} disabled={busy !== null}>
              <Icon name="refresh" size={14} /> تازه‌سازی
            </Button>
          </>
        }
      />

      <div className="eg-stack">
        <Card>
          <div className="eg-row" style={{ justifyContent: "space-between" }} data-testid="master-switch">
            <div style={{ minWidth: 0 }}>
              <div className="eg-row">
                <strong style={{ color: "var(--text)" }}>کلیدِ کلیِ پراکسی</strong>
                <Badge tone={data.enabled ? "ok" : "bad"}>{data.enabled ? "روشن" : "خاموش — همه مستقیم"}</Badge>
              </div>
              <p className="eg-muted">
                {data.enabled
                  ? "اگر VPN مشکل ساخت، این کلید را خاموش کنید: همهٔ سرویس‌ها فوراً مستقیم می‌شوند و مسیرهایی که چیده‌اید نگه داشته می‌شود."
                  : "الان هیچ سرویسی از پراکسی نمی‌رود، حتی اگر در جدولِ پایین مسیرِ پراکسی داشته باشد. روشن کنید تا مسیرها برگردند."}
              </p>
            </div>
            <Button variant={data.enabled ? "secondary" : "primary"} size="sm" onClick={() => void setMaster(!data.enabled)} disabled={busy !== null} data-testid="master-toggle">
              {data.enabled ? "خاموش کن" : "روشن کن"}
            </Button>
          </div>
        </Card>
        {data.all_direct && !data.enabled ? (
          <Alert tone="warn" title="کلیدِ کلیِ پراکسی خاموش است">
            همهٔ سرویس‌ها مستقیم می‌روند. با «روشن کن» مسیرهای ذخیره‌شده دوباره کار می‌کنند.
          </Alert>
        ) : data.all_direct ? (
          <Alert tone="info" title="الان همهٔ سرویس‌ها مستقیم می‌روند">
            هنوز هیچ سرویسی از پراکسی نمی‌رود. وقتی VPN یا پراکسی دارید: پایین «پراکسیِ تازه» را اضافه کنید، آزمایشش کنید و در جدولِ «مسیرِ هر سرویس» تلگرام و بقیه را روی آن بگذارید. سایت، سرویس‌های ایرانی و سرورِ پردازش در هر حال مستقیم می‌مانند.
          </Alert>
        ) : (
          <Alert tone="ok" title={`${fa(routed.length)} سرویس از پراکسی می‌رود`}>
            {routed.map((s) => `${s.title} ← «${s.proxy_name}»`).join("؛ ")}. هر چیزِ دیگر مستقیم است.
          </Alert>
        )}
        {notice && <Alert tone="ok" title={notice} />}
        <ErrorBox message={err} />

        {/* ───────── پراکسی‌ها */}
        <section data-testid="proxies-section">
          <div className="eg-head">
            <h2 className="text-lg font-bold" style={{ color: "var(--text)" }}>پراکسی‌ها</h2>
            {form === null && (
              <Button size="sm" onClick={() => { setForm(formOf(null)); setFormErr(null); setFormTest(null); }} data-testid="proxy-add">
                <Icon name="plus" size={14} /> پراکسیِ تازه
              </Button>
            )}
          </div>
          <p className="eg-muted" style={{ marginBottom: 10 }}>
            هر پراکسی یک نشانی است: HTTP، HTTPS یا SOCKS5. اگر کلاینتِ V2Ray / Xray را روی همین سرور اجرا کنید، فقط به پورتِ محلیِ آن اشاره کنید (مثلاً <Ltr>socks5h://127.0.0.1:10808</Ltr>). رمزها فقط در پایگاه‌دادهٔ سرور می‌مانند و هیچ‌جا نمایش داده نمی‌شوند.
          </p>
          <div className="eg-stack">
            {form !== null && (
              <ProxyForm
                form={form}
                setForm={setForm}
                busy={busy}
                onSave={() => void saveForm()}
                onTest={() => void testForm()}
                onCancel={() => { setForm(null); setFormErr(null); setFormTest(null); }}
                error={formErr}
                test={formTest}
              />
            )}
            {data.proxies.length === 0 && form === null && (
              <Card><p className="eg-muted">هنوز پراکسی‌ای نیست. «پراکسیِ تازه» را بزنید.</p></Card>
            )}
            {data.proxies.map((p) => (
              <ProxyCard
                key={p.id}
                p={p}
                busy={busy}
                test={tests[p.id] ?? null}
                onEdit={() => { setForm(formOf(p)); setFormErr(null); setFormTest(null); }}
                onTest={() => void testSaved(p)}
                onDelete={() => removeProxy(p)}
                onToggle={() => void toggleProxy(p)}
                onRouteAll={() => routeAll(p)}
              />
            ))}
          </div>
        </section>

        {/* ───────── جدولِ مسیرها */}
        <section data-testid="routes-section">
          <div className="eg-head">
            <h2 className="text-lg font-bold" style={{ color: "var(--text)" }}>مسیرِ هر سرویس</h2>
            <div className="eg-row">
              <Button size="sm" variant="secondary" onClick={() => void testAllRouted()} disabled={busy !== null || routed.length === 0} data-testid="routes-test-all">
                {busy === "all" ? "در حالِ آزمایش…" : "آزمایشِ همهٔ سرویس‌هایی که از پراکسی می‌روند"}
              </Button>
              <Button size="sm" variant="secondary" onClick={allDirect} disabled={busy !== null || routed.length === 0}>همه مستقیم</Button>
            </div>
          </div>
          {enabledProxies.length === 0 && (
            <p className="eg-muted" style={{ marginBottom: 10 }}>تا یک پراکسیِ روشن نداشته باشید، همهٔ سرویس‌ها فقط «مستقیم» هستند.</p>
          )}
          {data.groups.map((g) => {
            const rows = data.services.filter((s) => s.group === g.key);
            if (!rows.length) return null;
            return (
              <div key={g.key} style={{ marginBottom: 16 }}>
                <h3 className="eg-group">{g.title}</h3>
                <div className="eg-stack">
                  {rows.map((s) => (
                    <div key={s.key} className={`eg-svc${focus === s.key ? " eg-focus" : ""}`} data-service={s.key} data-testid={`svc-${s.key}`}>
                      <div style={{ minWidth: 0 }}>
                        <div className="eg-row">
                          <strong style={{ color: "var(--text)" }}>{s.title}</strong>
                          <HealthBadge s={s} />
                          {s.node && <Badge tone="info">به سرورِ پردازش هم داده می‌شود</Badge>}
                        </div>
                        <p className="eg-muted">{s.summary}</p>
                        <p className="eg-muted">کجا استفاده می‌شود: {s.used_by.join("، ")}</p>
                        {s.note && <p className="eg-bad">{s.note}</p>}
                        {s.health.detail && s.effective === "proxy" && !s.health.stale && s.health.state !== "unknown" && (
                          <details className="eg-details">
                            <summary>جزئیاتِ آخرین آزمایش ({whenText(s.health.checked_at)})</summary>
                            <p className="eg-muted">{s.health.detail}</p>
                          </details>
                        )}
                      </div>
                      <div>
                        <Select
                          aria-label={`مسیرِ ${s.title}`}
                          value={s.proxy_id === null ? "direct" : String(s.proxy_id)}
                          onChange={(e) => {
                            const v = e.target.value;
                            const pid = v === "direct" ? null : Number(v);
                            const pname = data.proxies.find((p) => p.id === pid)?.name;
                            void setRoutes({ [s.key]: pid }, pid === null ? `«${s.title}» مستقیم شد.` : `«${s.title}» حالا از پراکسیِ «${pname}» می‌رود.`);
                          }}
                          disabled={busy !== null}
                          data-testid={`route-${s.key}`}
                        >
                          <option value="direct">مستقیم</option>
                          {data.proxies.map((p) => (
                            <option key={p.id} value={p.id}>{`از راهِ پراکسیِ «${p.name}»${p.enabled ? "" : " (خاموش)"}`}</option>
                          ))}
                        </Select>
                        <div className="eg-muted" style={{ marginTop: 4 }}>الان: {routeText(s)}</div>
                      </div>
                      <div>
                        <Button size="sm" variant="secondary" onClick={() => void testService(s)} disabled={busy !== null} data-testid={`svc-test-${s.key}`}>
                          {busy === `svc:${s.key}` ? "در حالِ آزمایش…" : "آزمایش"}
                        </Button>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            );
          })}
          <p className="eg-muted">
            هر چیزی که در این جدول نیست همیشه مستقیم می‌رود: خودِ سایت، بله، ایتا، روبیکا، زرین‌پال، نوین‌هاب، متیس، سرورِ پردازشِ GPU، PyPI/npm و سرویس‌های محلی.
          </p>
        </section>

        {/* ───────── آزمایشِ مستقیم */}
        <section data-testid="direct-section">
          <div className="eg-head">
            <h2 className="text-lg font-bold" style={{ color: "var(--text)" }}>بدونِ پراکسی چه می‌شود؟</h2>
            <Button size="sm" variant="secondary" onClick={() => void testDirect()} disabled={busy !== null} data-testid="direct-test">
              {busy === "direct" ? "در حالِ آزمایش…" : "آزمایشِ مستقیم از این سرور"}
            </Button>
          </div>
          <p className="eg-muted" style={{ marginBottom: 10 }}>
            همهٔ مقصدهای جدول را مستقیم، بی‌پراکسی، می‌آزماید؛ هر چه «در دسترس نیست» است برایش پراکسی لازم دارید.
          </p>
          {direct && <TestPanel title="آزمایشِ مستقیم" result={direct} testid="direct-result" />}
        </section>

        {/* ───────── سرورِ پردازش */}
        <section data-testid="node-section">
          <h2 className="text-lg font-bold" style={{ color: "var(--text)", marginBottom: 8 }}>سرورِ پردازشِ GPU</h2>
          <Card>
            <p className="eg-muted">
              آباگرام (خواندنِ اینستاگرام) روی سرورِ پردازش اجرا می‌شود. اگر برای «اینستاگرام» پراکسی بگذارید و آن پراکسی از بیرونِ این سرور هم در دسترس باشد
              (نه 127.0.0.1 و نه نشانیِ شبکهٔ داخلی)، سرورِ پردازش آن را فقط وقتی استفاده می‌کند که خودش پراکسی ندارد
              (متغیرِ NM_ABAGRAM_PROXY، فایلِ proxy.txt، پراکسیِ ویندوز یا تنظیماتِ خودِ آباگرام). برای SOCKS با نام‌کاربری و رمز، Chromium پشتیبانی ندارد و داده نمی‌شود. بقیهٔ کارهای سرورِ پردازش مستقیم‌اند.
            </p>
            {data.nodes.length === 0 ? (
              <p className="eg-muted" style={{ marginTop: 8 }}>هنوز هیچ سرورِ پردازشی آباگرام را گزارش نکرده است.</p>
            ) : (
              <Table>
                <thead>
                  <tr><th>سرور</th><th>وضعیت</th><th>پراکسیِ آباگرام</th><th>از کجا</th><th>ورود به اینستاگرام</th></tr>
                </thead>
                <tbody>
                  {data.nodes.map((n) => (
                    <tr key={n.name}>
                      <td>{n.name}</td>
                      <td><Badge tone={n.online ? "ok" : "neutral"}>{n.online ? "روشن" : "خاموش"}</Badge></td>
                      <td>{n.has_proxy ? <Ltr>{n.proxy}</Ltr> : "ندارد"}</td>
                      <td>{n.proxy_source ? SOURCE_FA[n.proxy_source] || n.proxy_source : "—"}</td>
                      <td>{n.signed_in ? "وارد شده" : "هنوز نه"}</td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            )}
          </Card>
        </section>

        <p className="eg-muted">
          انواعِ پراکسی: {Object.values(SCHEME_FA).join(" · ")}. آخرین تازه‌سازی: {whenText(data.generated_at)}.
        </p>
      </div>
    </div>
  );
}
