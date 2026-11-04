import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { api, errorMessage } from "../../api/client";
import {
  Alert,
  Badge,
  Button,
  Card,
  ErrorBox,
  Field,
  Input,
  PageHeader,
  SectionTitle,
  Select,
  Spinner,
  Stat,
  Table,
  TextArea,
  fa,
} from "../../components/ui";

/**
 * «دستگاه‌های موبایل» — پنلِ برنامهٔ NM-Mobile (اندروید).
 *
 * گوشی‌های جفت‌شده، صفِ پیامک (با فهرستِ «لغو» و تأییدِ کمپین)، تماس‌ها (رضایت، متن، یادداشتِ هوش مصنوعی)،
 * قیمتِ پایینِ محصول، شناساییِ تماس‌گیرنده از پیام‌رسان‌ها و تنظیمات. بک‌اند: apps/mobile.
 * هر عددی که ثبت نشده باشد «ثبت نشده» نوشته می‌شود، نه صفر.
 */

const M = "/mobile";

type Tab = "devices" | "sms" | "calls" | "prices" | "lookup" | "settings";
const TABS: { key: Tab; label: string }[] = [
  { key: "devices", label: "گوشی‌ها" },
  { key: "sms", label: "صفِ پیامک" },
  { key: "calls", label: "تماس‌ها" },
  { key: "prices", label: "قیمت‌ها" },
  { key: "lookup", label: "شناساییِ تماس‌گیرنده" },
  { key: "settings", label: "تنظیمات و گزارشِ اقدام‌ها" },
];

type Dict = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any

function when(iso?: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString("fa-IR", { dateStyle: "short", timeStyle: "short" });
}

function num(v: unknown): string {
  return v === null || v === undefined || v === "" ? "ثبت نشده" : fa(Number(v).toLocaleString("en-US")).replace(/,/g, "٬");
}

function useLoad<T = Dict>(path: string, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const r = await api.get<T>(path);
      setData(r.data);
      setError(null);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, ...deps]);
  useEffect(() => {
    void reload();
  }, [reload]);
  return { data, error, loading, reload, setData };
}

function useAction() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const run = useCallback(async (fn: () => Promise<unknown>, ok = "انجام شد.") => {
    setBusy(true);
    setError(null);
    setDone(null);
    try {
      const r = await fn();
      setDone(ok);
      return r;
    } catch (e) {
      setError(errorMessage(e));
      return undefined;
    } finally {
      setBusy(false);
    }
  }, []);
  return { busy, error, done, run };
}

export default function MobilePage() {
  const [tab, setTab] = useState<Tab>("devices");
  return (
    <div dir="rtl">
      <PageHeader
        title="دستگاه‌های موبایل"
        subtitle="گوشی‌های کارمندان که به NM وصل‌اند: وضعیت، پیامک، تماس، قیمتِ پایین و شناساییِ تماس‌گیرنده"
      />
      <div className="mb-5 flex flex-wrap gap-2" role="tablist">
        {TABS.map((t) => (
          <button
            key={t.key}
            role="tab"
            aria-selected={tab === t.key}
            onClick={() => setTab(t.key)}
            className={`u-btn ${tab === t.key ? "u-btn-primary" : "u-btn-secondary"} u-btn-sm`}
          >
            {t.label}
          </button>
        ))}
      </div>
      {tab === "devices" && <DevicesTab />}
      {tab === "sms" && <SmsTab />}
      {tab === "calls" && <CallsTab />}
      {tab === "prices" && <PricesTab />}
      {tab === "lookup" && <LookupTab />}
      {tab === "settings" && <SettingsTab />}
    </div>
  );
}

/* ------------------------------------------------------------------ devices */

function DevicesTab() {
  const overview = useLoad("/mobile/admin/overview/");
  const devices = useLoad<{ results: Dict[] }>(`${M}/admin/devices/`);
  const act = useAction();

  useEffect(() => {
    const t = setInterval(() => void devices.reload(), 20000);
    return () => clearInterval(t);
  }, [devices]);

  const o = overview.data;
  return (
    <div className="grid gap-5">
      <ErrorBox message={overview.error || devices.error || act.error} />
      <Card>
        <SectionTitle>اتصالِ یک گوشی</SectionTitle>
        {o ? (
          <div className="grid gap-3 text-sm leading-7">
            <div>
              آدرسِ سرور برای نوشتن در برنامه:{" "}
              <code dir="ltr" className="rounded bg-[var(--surface-2)] px-2 py-1">
                {o.server_url}
              </code>
            </div>
            <ol className="list-decimal pr-5">
              {(o.pairing_steps as string[]).map((s) => (
                <li key={s}>{s}</li>
              ))}
            </ol>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <Stat value={fa(o.counts.devices)} label="گوشیِ فعال" />
              <Stat value={fa(o.counts.devices_online)} label="آنلاین" />
              <Stat value={fa(o.counts.sms_queued)} label="پیامکِ در صف" />
              <Stat value={fa(o.counts.calls)} label="تماسِ ثبت‌شده" />
            </div>
            <Alert tone="warn" title="امنیتِ اتصال">
              آدرسِ فعلی http است؛ توکنِ گوشی و ضبط‌ها بدونِ رمزنگاری می‌روند. برای استفادهٔ روزمره بهتر است سرور با https (دامنه + گواهی) بالا بیاید.
            </Alert>
          </div>
        ) : (
          <Spinner />
        )}
      </Card>

      <Card>
        <SectionTitle>گوشی‌های جفت‌شده</SectionTitle>
        {devices.loading && !devices.data ? (
          <Spinner />
        ) : !devices.data?.results.length ? (
          <p className="text-sm" style={{ color: "var(--text-3)" }}>
            هنوز گوشی‌ای وصل نشده است.
          </p>
        ) : (
          <Table>
            <thead>
              <tr>
                <th>نام</th>
                <th>کارمند</th>
                <th>مدل</th>
                <th>آخرین تماس</th>
                <th>وضعیت</th>
                <th>باتری</th>
                <th>پیامکِ امروز</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {devices.data.results.map((d) => (
                <tr key={d.uid}>
                  <td>{d.name}</td>
                  <td>{d.user?.username}</td>
                  <td>
                    {d.model || "—"} {d.android_version ? `· اندروید ${fa(d.android_version)}` : ""}
                    <div className="text-xs" style={{ color: "var(--text-3)" }}>
                      برنامه {d.app_version || "—"} · {d.token_prefix}…
                    </div>
                  </td>
                  <td>{when(d.last_seen_at)}</td>
                  <td>
                    {d.revoked_at ? <Badge tone="bad">لغو شده</Badge> : d.online ? <Badge tone="ok">آنلاین</Badge> : <Badge>آفلاین</Badge>}{" "}
                    {!d.revoked_at && !d.sms_enabled && <Badge tone="warn">پیامک خاموش</Badge>}
                  </td>
                  <td>{d.battery_percent === null || d.battery_percent === undefined ? "نامعلوم" : `${fa(d.battery_percent)}٪`}</td>
                  <td>{fa(d.sms_sent_today ?? 0)}</td>
                  <td className="whitespace-nowrap">
                    {!d.revoked_at && (
                      <>
                        <Button
                          size="sm"
                          variant="secondary"
                          disabled={act.busy}
                          onClick={() =>
                            act.run(async () => {
                              await api.patch(`${M}/admin/devices/${d.uid}/`, { sms_enabled: !d.sms_enabled });
                              await devices.reload();
                            })
                          }
                        >
                          {d.sms_enabled ? "قطعِ پیامک" : "وصلِ پیامک"}
                        </Button>{" "}
                        <Button
                          size="sm"
                          variant="danger"
                          disabled={act.busy}
                          onClick={() => {
                            if (!window.confirm(`دسترسیِ «${d.name}» لغو شود؟ گوشی باید دوباره با رمز وصل شود.`)) return;
                            void act.run(async () => {
                              await api.post(`${M}/admin/devices/${d.uid}/revoke/`);
                              await devices.reload();
                            });
                          }}
                        >
                          لغوِ دسترسی
                        </Button>
                      </>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
    </div>
  );
}

/* ------------------------------------------------------------------ sms */

const STATE_TONE: Record<string, "ok" | "warn" | "bad" | "info" | "neutral"> = {
  QUEUED: "info",
  CLAIMED: "info",
  SENT: "ok",
  DELIVERED: "ok",
  FAILED: "bad",
  CANCELLED: "neutral",
  BLOCKED: "warn",
};

function SmsTab() {
  const [state, setState] = useState("");
  const list = useLoad<{ count: number; results: Dict[] }>(`${M}/sms/queue/?limit=40${state ? `&state=${state}` : ""}`, [state]);
  const optouts = useLoad<{ count: number; results: Dict[] }>(`${M}/admin/optouts/?limit=50`);
  const approvals = useLoad<{ results: Dict[] }>(`${M}/admin/approvals/`);
  const send = useAction();
  const other = useAction();
  const [form, setForm] = useState({ to: "", body: "", kind: "transactional", campaign_ref: "" });
  const [stop, setStop] = useState("");
  const [appr, setAppr] = useState({ ref: "", title: "", max_messages: "" });

  return (
    <div className="grid gap-5">
      <Alert tone="info" title="قاعده‌ها">
        شماره‌ای که «لغو» یا «stop» جواب بدهد برای همیشه در فهرستِ لغو می‌رود و هیچ پیامی نمی‌گیرد. پیامِ تبلیغاتی فقط از کمپینی ساخته می‌شود که یک نفر در
        «تأییدِ کمپین» تأییدش کرده باشد، و بینِ ساعتِ ۲۱ تا ۸ فرستاده نمی‌شود.
      </Alert>
      <ErrorBox message={list.error || send.error || other.error} />

      <Card>
        <SectionTitle>ارسالِ یک پیامک (آزمایشی / تکی)</SectionTitle>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="شمارهٔ گیرنده">
            <Input dir="ltr" value={form.to} onChange={(e) => setForm({ ...form, to: e.target.value })} placeholder="09121234567" />
          </Field>
          <Field label="نوع">
            <Select value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value })}>
              <option value="transactional">اطلاع‌رسانی</option>
              <option value="otp">کدِ تأیید</option>
              <option value="marketing">تبلیغاتی (نیازمندِ کمپینِ تأییدشده)</option>
            </Select>
          </Field>
          {form.kind === "marketing" && (
            <Field label="شناسهٔ کمپینِ تأییدشده">
              <Input dir="ltr" value={form.campaign_ref} onChange={(e) => setForm({ ...form, campaign_ref: e.target.value })} />
            </Field>
          )}
          <div className="sm:col-span-2">
            <Field label="متن">
              <TextArea rows={3} value={form.body} onChange={(e) => setForm({ ...form, body: e.target.value })} />
            </Field>
          </div>
        </div>
        <div className="mt-3 flex items-center gap-3">
          <Button
            disabled={send.busy || !form.to || !form.body}
            onClick={() =>
              send.run(async () => {
                await api.post(`${M}/sms/queue/`, { ...form, idempotency_key: `panel-${Date.now()}-${Math.random().toString(36).slice(2, 8)}` });
                await list.reload();
              }, "در صف گذاشته شد؛ گوشی خودش می‌فرستد.")
            }
          >
            {send.busy ? <Spinner size={16} /> : "گذاشتن در صف"}
          </Button>
          {send.done && <span className="text-sm" style={{ color: "var(--ok)" }}>{send.done}</span>}
        </div>
      </Card>

      <Card>
        <SectionTitle>صفِ پیامک {list.data ? `(${fa(list.data.count)})` : ""}</SectionTitle>
        <div className="mb-3 flex flex-wrap gap-2">
          <Select value={state} onChange={(e) => setState(e.target.value)} style={{ width: "auto" }}>
            <option value="">همهٔ وضعیت‌ها</option>
            {Object.keys(STATE_TONE).map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </Select>
        </div>
        {list.loading && !list.data ? (
          <Spinner />
        ) : !list.data?.results.length ? (
          <p className="text-sm" style={{ color: "var(--text-3)" }}>
            پیامکی نیست.
          </p>
        ) : (
          <Table>
            <thead>
              <tr>
                <th>گیرنده</th>
                <th>نوع</th>
                <th>وضعیت</th>
                <th>گوشی</th>
                <th>زمان</th>
                <th>خطا</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {list.data.results.map((m) => (
                <tr key={m.uid}>
                  <td dir="ltr">{m.to}</td>
                  <td>{m.kind}</td>
                  <td>
                    <Badge tone={STATE_TONE[m.state] ?? "neutral"}>{m.state_label}</Badge>
                  </td>
                  <td>{m.device || "—"}</td>
                  <td>{when(m.sent_at || m.created_at)}</td>
                  <td className="max-w-[16rem] truncate" title={m.error}>
                    {m.error || ""}
                  </td>
                  <td>
                    {m.state === "QUEUED" && (
                      <Button
                        size="sm"
                        variant="secondary"
                        onClick={() => other.run(async () => { await api.post(`${M}/sms/${m.uid}/cancel/`); await list.reload(); })}
                      >
                        لغو
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>

      <div className="grid gap-5 lg:grid-cols-2">
        <Card>
          <SectionTitle>فهرستِ «پیامک نفرست» ({fa(optouts.data?.count ?? 0)})</SectionTitle>
          <div className="mb-3 flex gap-2">
            <Input dir="ltr" value={stop} onChange={(e) => setStop(e.target.value)} placeholder="شماره" />
            <Button
              disabled={!stop || other.busy}
              onClick={() => other.run(async () => { await api.post(`${M}/admin/optouts/`, { number: stop }); setStop(""); await optouts.reload(); })}
            >
              افزودن
            </Button>
          </div>
          {optouts.data?.results.map((o) => (
            <div key={o.id} className="flex items-center justify-between border-b py-2 text-sm" style={{ borderColor: "var(--line)" }}>
              <span dir="ltr">{o.number}</span>
              <span style={{ color: "var(--text-3)" }}>{o.reason_label}</span>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => {
                  if (!window.confirm("از فهرستِ لغو برداشته شود؟ فقط اگر خودِ شخص خواسته باشد.")) return;
                  void other.run(async () => { await api.delete(`${M}/admin/optouts/${o.id}/`); await optouts.reload(); });
                }}
              >
                برداشتن
              </Button>
            </div>
          ))}
        </Card>

        <Card>
          <SectionTitle>تأییدِ کمپینِ پیامکی</SectionTitle>
          <p className="mb-3 text-sm" style={{ color: "var(--text-3)" }}>
            «جذبِ مشتری» یا هر بخشِ دیگر بعد از تأییدِ یک انسان، همین شناسه را ثبت می‌کند. اینجا هم می‌توانید دستی تأیید کنید.
          </p>
          <div className="mb-3 grid gap-2 sm:grid-cols-3">
            <Input dir="ltr" placeholder="شناسه مثل ge:42" value={appr.ref} onChange={(e) => setAppr({ ...appr, ref: e.target.value })} />
            <Input placeholder="عنوان" value={appr.title} onChange={(e) => setAppr({ ...appr, title: e.target.value })} />
            <Input dir="ltr" placeholder="سقفِ تعداد (اختیاری)" value={appr.max_messages} onChange={(e) => setAppr({ ...appr, max_messages: e.target.value })} />
          </div>
          <Button
            disabled={!appr.ref || !appr.title || other.busy}
            onClick={() =>
              other.run(async () => {
                await api.post(`${M}/admin/approvals/`, appr);
                setAppr({ ref: "", title: "", max_messages: "" });
                await approvals.reload();
              })
            }
          >
            تأییدِ این کمپین
          </Button>
          <div className="mt-3">
            {approvals.data?.results.map((a) => (
              <div key={a.id} className="flex items-center justify-between border-b py-2 text-sm" style={{ borderColor: "var(--line)" }}>
                <span>
                  <b dir="ltr">{a.ref}</b> — {a.title} <span style={{ color: "var(--text-3)" }}>({fa(a.sent_count)}{a.max_messages ? ` / ${fa(a.max_messages)}` : ""})</span>
                </span>
                {a.active ? (
                  <Button
                    size="sm"
                    variant="danger"
                    onClick={() => other.run(async () => { await api.post(`${M}/admin/approvals/${a.id}/revoke/`); await approvals.reload(); })}
                  >
                    پس‌گرفتن
                  </Button>
                ) : (
                  <Badge tone="neutral">غیرفعال</Badge>
                )}
              </div>
            ))}
          </div>
        </Card>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ calls */

const CALL_STATUS: Record<string, { label: string; tone: "ok" | "warn" | "bad" | "info" | "neutral" }> = {
  LOGGED: { label: "ثبت شد", tone: "neutral" },
  NO_CONSENT: { label: "رضایت ثبت نشده", tone: "warn" },
  UPLOADED: { label: "ضبط رسید", tone: "info" },
  TRANSCRIBING: { label: "در حال تبدیل به متن", tone: "info" },
  TRANSCRIBED: { label: "متن آماده", tone: "ok" },
  ANALYSED: { label: "تحلیل شد", tone: "ok" },
  FAILED: { label: "خطا", tone: "bad" },
};
const DIRECTION: Record<string, string> = { in: "ورودی", out: "خروجی", missed: "بی‌پاسخ", rejected: "ردشده" };

function CallsTab() {
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const list = useLoad<{ count: number; results: Dict[] }>(`${M}/calls/?limit=40${status ? `&status=${status}` : ""}${q ? `&number=${encodeURIComponent(q)}` : ""}`, [q, status]);
  const [open, setOpen] = useState<string | null>(null);
  const consents = useLoad<{ results: Dict[] }>(`${M}/admin/consents/`);
  return (
    <div className="grid gap-5">
      <Alert tone="info" title="قاعدهٔ ضبط">
        بدون ثبتِ رضایتِ طرفِ مقابل، هیچ ضبطی ذخیره نمی‌شود (همان قاعدهٔ «بازاریابی تلفنی»). فایل‌ها بیرون از پوشه‌های عمومیِ سایت نگه‌داری می‌شوند و فقط
        کارمندان می‌شنوند. متنِ تماس با روشِ «اول لوکال / اول متیس» ساخته می‌شود و اگر سیاستِ دادهٔ فروشگاه اجازه ندهد صدا به متیس نمی‌رود.
      </Alert>
      <ErrorBox message={list.error} />
      <Card>
        <SectionTitle>تماس‌ها {list.data ? `(${fa(list.data.count)})` : ""}</SectionTitle>
        <div className="mb-3 flex flex-wrap gap-2">
          <Input dir="ltr" placeholder="شماره" value={q} onChange={(e) => setQ(e.target.value)} style={{ width: 150 }} />
          <Select value={status} onChange={(e) => setStatus(e.target.value)} style={{ width: "auto" }}>
            <option value="">همه</option>
            {Object.entries(CALL_STATUS).map(([k, v]) => (
              <option key={k} value={k}>
                {v.label}
              </option>
            ))}
          </Select>
        </div>
        {list.loading && !list.data ? (
          <Spinner />
        ) : !list.data?.results.length ? (
          <p className="text-sm" style={{ color: "var(--text-3)" }}>
            تماسی ثبت نشده است.
          </p>
        ) : (
          <Table>
            <thead>
              <tr>
                <th>شماره</th>
                <th>کیست</th>
                <th>جهت</th>
                <th>زمان</th>
                <th>مدت</th>
                <th>وضعیت</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {list.data.results.map((c) => (
                <tr key={c.uid}>
                  <td dir="ltr">{c.number}</td>
                  <td>{c.caller?.display || c.contact_name || "ناشناس"}</td>
                  <td>{DIRECTION[c.direction] ?? c.direction}</td>
                  <td>{when(c.started_at)}</td>
                  <td>{c.duration_s ? `${fa(Math.floor(c.duration_s / 60))}:${fa(String(c.duration_s % 60).padStart(2, "0"))}` : "—"}</td>
                  <td>
                    <Badge tone={CALL_STATUS[c.status]?.tone ?? "neutral"}>{CALL_STATUS[c.status]?.label ?? c.status}</Badge>
                  </td>
                  <td>
                    <Button size="sm" variant="secondary" onClick={() => setOpen(open === c.uid ? null : c.uid)}>
                      {open === c.uid ? "بستن" : "جزئیات"}
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
      {open && <CallDetail uid={open} onChanged={() => void list.reload()} />}
      <Card>
        <SectionTitle>رضایت‌های ثبت‌شده برای ضبط</SectionTitle>
        {!consents.data?.results.length ? (
          <p className="text-sm" style={{ color: "var(--text-3)" }}>
            هنوز رضایتی ثبت نشده است.
          </p>
        ) : (
          <Table>
            <thead>
              <tr>
                <th>شماره</th>
                <th>وضعیت</th>
                <th>چطور گرفته شد</th>
                <th>زمان</th>
                <th>ثبت‌کننده</th>
              </tr>
            </thead>
            <tbody>
              {consents.data.results.map((c) => (
                <tr key={c.normalized}>
                  <td dir="ltr">{c.number}</td>
                  <td>{c.active ? <Badge tone="ok">فعال</Badge> : <Badge tone="neutral">پس گرفته شد</Badge>}</td>
                  <td>{c.obtained_how}</td>
                  <td>{when(c.obtained_at)}</td>
                  <td>{c.by || "—"}</td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
    </div>
  );
}

function CallDetail({ uid, onChanged }: { uid: string; onChanged: () => void }) {
  const d = useLoad(`${M}/calls/${uid}/`, [uid]);
  const act = useAction();
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const urlRef = useRef<string | null>(null);
  useEffect(
    () => () => {
      if (urlRef.current) URL.revokeObjectURL(urlRef.current);
    },
    [],
  );
  const c = d.data;
  useEffect(() => {
    if (!c || !["UPLOADED", "TRANSCRIBING"].includes(c.status)) return;
    const t = setTimeout(() => void d.reload(), 4000);
    return () => clearTimeout(t);
  }, [c, d]);
  const loadAudio = () =>
    act.run(async () => {
      const r = await api.get(`${M}/calls/${uid}/audio/`, { responseType: "blob" });
      const url = URL.createObjectURL(r.data as Blob);
      if (urlRef.current) URL.revokeObjectURL(urlRef.current);
      urlRef.current = url;
      setAudioUrl(url);
    }, "");
  if (d.loading && !c) return <Card><Spinner /></Card>;
  if (!c) return <ErrorBox message={d.error} />;
  const list = (title: string, items?: string[]) =>
    items && items.length ? (
      <div>
        <div className="text-sm font-bold">{title}</div>
        <ul className="list-disc pr-5 text-sm leading-7">
          {items.map((x) => (
            <li key={x}>{x}</li>
          ))}
        </ul>
      </div>
    ) : null;
  return (
    <Card>
      <SectionTitle
        action={
          <div className="flex gap-2">
            {c.has_audio && (
              <>
                <Button size="sm" variant="secondary" onClick={() => void loadAudio()} disabled={act.busy}>
                  شنیدنِ ضبط
                </Button>
                <Button
                  size="sm"
                  variant="secondary"
                  disabled={act.busy}
                  onClick={() => act.run(async () => { await api.post(`${M}/calls/${uid}/reprocess/`); await d.reload(); onChanged(); }, "دوباره پردازش شد.")}
                >
                  پردازشِ دوباره
                </Button>
              </>
            )}
          </div>
        }
      >
        تماس با <span dir="ltr">{c.number}</span> {c.caller?.display ? `— ${c.caller.display}` : ""}
      </SectionTitle>
      <ErrorBox message={act.error} />
      {audioUrl && <audio controls src={audioUrl} className="mb-3 w-full" />}
      <div className="mb-3 flex flex-wrap gap-2 text-sm">
        <Badge tone={CALL_STATUS[c.status]?.tone ?? "neutral"}>{CALL_STATUS[c.status]?.label ?? c.status}</Badge>
        {c.asr_engine && <Badge tone="info">متن: {c.asr_engine === "metis" ? "متیس" : c.asr_engine === "node" ? "سرورِ پردازش" : "لوکال"}</Badge>}
        {c.sentiment && <Badge tone={c.sentiment === "POSITIVE" ? "ok" : c.sentiment === "NEGATIVE" ? "bad" : "neutral"}>{c.sentiment === "POSITIVE" ? "مثبت" : c.sentiment === "NEGATIVE" ? "منفی" : "خنثی"}</Badge>}
        {c.consent?.granted ? <Badge tone="ok">رضایتِ ضبط ثبت است</Badge> : <Badge tone="warn">رضایتِ ضبط ثبت نیست</Badge>}
      </div>
      {c.error && <Alert tone={c.status === "FAILED" ? "bad" : "warn"}>{c.error}</Alert>}
      {c.summary && (
        <div className="my-3">
          <div className="text-sm font-bold">خلاصه (هوش مصنوعی — پیشنهاد است، تصمیم با شماست)</div>
          <p className="text-sm leading-7">{c.summary}</p>
        </div>
      )}
      <div className="grid gap-3 sm:grid-cols-3">
        {list("مخالفت‌ها / نگرانی‌ها", c.objections)}
        {list("قول‌ها", c.commitments)}
        {list("قدم‌های بعدی", c.next_steps)}
      </div>
      {c.transcript && (
        <div className="mt-3">
          <div className="text-sm font-bold">متنِ تماس</div>
          <p className="whitespace-pre-wrap text-sm leading-7">{c.transcript}</p>
        </div>
      )}
      {c.profiles?.length > 0 && (
        <div className="mt-4">
          <div className="text-sm font-bold">پروفایل‌ها در پیام‌رسان‌ها</div>
          <ProfileList rows={c.profiles} />
        </div>
      )}
    </Card>
  );
}

function ProfileList({ rows }: { rows: Dict[] }) {
  return (
    <div className="grid gap-2">
      {rows.map((p) => (
        <div key={p.uid} className="flex items-start gap-3 rounded-xl p-3" style={{ background: "var(--surface-2)" }}>
          <div className="min-w-0 flex-1 text-sm leading-7">
            <b>{p.label}</b>{" "}
            {p.status === "found" ? <Badge tone="ok">هست</Badge> : p.status === "not_found" ? <Badge>نیست</Badge> : <Badge tone="warn">{p.status}</Badge>}
            {p.display_name && <div>نام: {p.display_name} <small style={{ color: "var(--text-3)" }}>({p.field_sources?.display_name || "—"})</small></div>}
            {p.username && <div dir="ltr" className="text-right">@{p.username}</div>}
            {p.bio && <div>بیو: {p.bio}</div>}
            <div className="text-xs" style={{ color: "var(--text-3)" }}>
              {when(p.looked_up_at)} · {p.method === "server" ? "از سرور" : "از گوشی"} · {fa(p.age_days)} روز پیش{p.stale ? " (قدیمی)" : ""}
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

/* ------------------------------------------------------------------ prices */

function PricesTab() {
  const [q, setQ] = useState("");
  const [term, setTerm] = useState("");
  const list = useLoad<{ results: Dict[] }>(`${M}/admin/products/?limit=40${term ? `&q=${encodeURIComponent(term)}` : ""}`, [term]);
  return (
    <div className="grid gap-5">
      <Alert tone="info" title="کفِ قیمت چطور حساب می‌شود؟">
        کفِ قیمت = (بهای تمام‌شده + هزینهٔ اضافهٔ هر عدد) × (۱ + حداقل سود٪). اگر «کفِ دستی» را بنویسید همان می‌شود. اگر بهای تمام‌شده ثبت نشده باشد، کف و
        «بیشینهٔ تخفیف» <b>ثبت نشده</b> می‌ماند و عددی از خودمان نمی‌سازیم. بهای تمام‌شده و سود فقط به گوشی‌های کارمندان می‌رسد.
      </Alert>
      <Card>
        <div className="mb-4 flex gap-2">
          <Input placeholder="جستجوی محصول (نام، کد، برند)" value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === "Enter" && setTerm(q)} />
          <Button onClick={() => setTerm(q)}>جستجو</Button>
        </div>
        <ErrorBox message={list.error} />
        {list.loading && !list.data ? <Spinner /> : !list.data?.results.length ? <p className="text-sm" style={{ color: "var(--text-3)" }}>محصولی پیدا نشد.</p> : list.data.results.map((p) => <PriceRow key={p.id} p={p} onSaved={() => void list.reload()} />)}
      </Card>
    </div>
  );
}

function PriceRow({ p, onSaved }: { p: Dict; onSaved: () => void }) {
  const init = useMemo(
    () => ({
      cost_price: p.cost ?? "",
      stock_quantity: p.stock?.on_hand ?? "",
      extra_unit_cost: p.pricing?.extra_unit_cost ?? "",
      min_margin_percent: p.pricing?.min_margin_percent ?? "",
      floor_price_override: p.pricing?.floor_price_override ?? "",
    }),
    [p],
  );
  const [f, setF] = useState<Dict>(init);
  const act = useAction();
  useEffect(() => setF(init), [init]);
  const field = (key: string, label: string) => (
    <Field label={label}>
      <Input dir="ltr" inputMode="decimal" value={f[key] ?? ""} onChange={(e) => setF({ ...f, [key]: e.target.value })} placeholder="ثبت نشده" />
    </Field>
  );
  return (
    <div className="mb-4 rounded-xl border p-4" style={{ borderColor: "var(--line)" }}>
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <div>
          <b>{p.name}</b> <span className="text-xs" style={{ color: "var(--text-3)" }}>{p.sku} · {p.store?.name}</span>
        </div>
        <div className="flex flex-wrap gap-2 text-sm">
          <Badge>قیمت {num(p.price)}</Badge>
          <Badge tone={p.stock?.available > 0 ? "ok" : "warn"}>موجودیِ آزاد {fa(p.stock?.available ?? 0)}</Badge>
          <Badge tone={p.floor_price === null ? "warn" : "info"}>کفِ قیمت {num(p.floor_price)}</Badge>
          <Badge>بیشینهٔ تخفیف {p.max_discount_percent === null ? "ثبت نشده" : `${fa(p.max_discount_percent)}٪`}</Badge>
          <Badge>سودِ هر عدد {num(p.unit_profit)}</Badge>
        </div>
      </div>
      <div className="grid gap-3 sm:grid-cols-5">
        {field("cost_price", "بهای تمام‌شده")}
        {field("stock_quantity", "موجودی (انبار)")}
        {field("extra_unit_cost", "هزینهٔ اضافهٔ هر عدد")}
        {field("min_margin_percent", "حداقل سود ٪")}
        {field("floor_price_override", "کفِ دستی")}
      </div>
      <div className="mt-3 flex items-center gap-3">
        <Button
          size="sm"
          disabled={act.busy}
          onClick={() =>
            act.run(async () => {
              await api.patch(`${M}/admin/products/${p.id}/pricing/`, f);
              onSaved();
            }, "ذخیره شد.")
          }
        >
          {act.busy ? <Spinner size={14} /> : "ذخیره"}
        </Button>
        {act.done && <span className="text-sm" style={{ color: "var(--ok)" }}>{act.done}</span>}
        <ErrorBox message={act.error} />
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ lookup */

function LookupTab() {
  const s = useLoad("/mobile/admin/settings/");
  const tg = useLoad("/mobile/admin/lookups/telegram/");
  const recent = useLoad<{ results: Dict[] }>(`${M}/admin/lookups/`);
  const act = useAction();
  const [tgForm, setTgForm] = useState({ api_id: "", api_hash: "", phone: "", code: "", password: "" });
  const platforms: Record<string, boolean> = s.data?.lookup_platforms ?? {};
  const labels: Record<string, string> = s.data?.lookup_labels ?? {};
  const methods: Record<string, string> = s.data?.lookup_methods ?? {};
  const tgCall = (action: string, extra: Dict = {}) =>
    act.run(async () => {
      await api.post(`${M}/admin/lookups/telegram/`, { action, ...extra });
      await tg.reload();
      await s.reload();
    });
  const t = tg.data;
  return (
    <div className="grid gap-5">
      <Alert tone="warn" title="این بخش فقط برای شناساییِ تماس‌گیرنده است">
        {s.data?.lookup_rules}
      </Alert>
      <ErrorBox message={s.error || tg.error || act.error} />
      <Card>
        <SectionTitle>پیام‌رسان‌ها (هرکدام جدا روشن/خاموش؛ پیش‌فرض خاموش)</SectionTitle>
        {!s.data ? (
          <Spinner />
        ) : (
          <div className="grid gap-3">
            {Object.keys(platforms).map((k) => (
              <div key={k} className="flex flex-wrap items-center justify-between gap-3 rounded-xl p-3" style={{ background: "var(--surface-2)" }}>
                <div className="min-w-0 flex-1">
                  <b>{labels[k]}</b>{" "}
                  <Badge tone={methods[k] === "server" ? "info" : "neutral"}>{methods[k] === "server" ? "از سرور (راهِ رسمی)" : "از روی گوشی"}</Badge>
                  <div className="text-xs leading-6" style={{ color: "var(--text-3)" }}>
                    {methods[k] === "server"
                      ? "با حسابی که خودتان در پایین وصل می‌کنید؛ تلگرام ممکن است در صورتِ جستجوی زیاد محدودیتِ موقت بگذارد."
                      : s.data?.lookup_warning}
                  </div>
                </div>
                <label className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={!!platforms[k]}
                    disabled={act.busy}
                    onChange={(e) => {
                      if (e.target.checked && methods[k] !== "server" && !window.confirm(`«${labels[k]}» از راهِ غیررسمی انجام می‌شود و ممکن است حسابش محدود یا مسدود شود. روشن شود؟`)) return;
                      void act.run(async () => {
                        await api.patch(`${M}/admin/settings/`, { lookup_platforms: { [k]: e.target.checked } });
                        await s.reload();
                      });
                    }}
                  />
                  {platforms[k] ? "روشن" : "خاموش"}
                </label>
              </div>
            ))}
          </div>
        )}
      </Card>

      <Card>
        <SectionTitle>اتصالِ حسابِ تلگرامِ خودتان</SectionTitle>
        {!t ? (
          <Spinner />
        ) : (
          <div className="grid gap-3 text-sm leading-7">
            {t.linked ? (
              <Alert tone="ok" title={`وصل است: ${t.account?.name || ""} ${t.account?.username ? `(@${t.account.username})` : ""}`}>
                نشست روی سرور و در پوشهٔ داده‌ها (با دسترسیِ محدود) نگه داشته می‌شود، نه در مخزنِ کد.
                <div className="mt-2">
                  <Button size="sm" variant="danger" disabled={act.busy} onClick={() => window.confirm("اتصالِ تلگرام قطع و نشست پاک شود؟") && void tgCall("unlink")}>
                    قطعِ اتصال
                  </Button>
                </div>
              </Alert>
            ) : (
              <>
                {!t.installed && <Alert tone="bad">کتابخانهٔ Telethon روی سرور نصب نیست؛ اول باید نصب شود.</Alert>}
                <ol className="list-decimal pr-5">
                  <li>در سایتِ my.telegram.org با شمارهٔ خودتان وارد شوید ← API development tools ← یک برنامه بسازید ← «api_id» و «api_hash» را اینجا بنویسید.</li>
                  <li>شمارهٔ تلگرامِ خودتان را با کدِ کشور بنویسید (مثل 989121234567) تا کد به تلگرامتان بیاید.</li>
                  <li>کد را وارد کنید؛ اگر رمزِ دومرحله‌ای دارید رمز را هم بنویسید.</li>
                </ol>
                <div className="grid gap-2 sm:grid-cols-3">
                  <Input dir="ltr" placeholder="api_id" value={tgForm.api_id} onChange={(e) => setTgForm({ ...tgForm, api_id: e.target.value })} />
                  <Input dir="ltr" type="password" placeholder={t.api_configured ? "api_hash (ثبت شده)" : "api_hash"} value={tgForm.api_hash} onChange={(e) => setTgForm({ ...tgForm, api_hash: e.target.value })} autoComplete="off" />
                  <Button disabled={act.busy || !tgForm.api_id || !tgForm.api_hash} onClick={() => { void tgCall("save_api", { api_id: tgForm.api_id, api_hash: tgForm.api_hash }); setTgForm({ ...tgForm, api_hash: "" }); }}>
                    ذخیرهٔ api
                  </Button>
                </div>
                <div className="grid gap-2 sm:grid-cols-3">
                  <Input dir="ltr" placeholder="989121234567" value={tgForm.phone} onChange={(e) => setTgForm({ ...tgForm, phone: e.target.value })} />
                  <Button disabled={act.busy || !t.api_configured || !tgForm.phone} onClick={() => void tgCall("send_code", { phone: tgForm.phone })}>
                    فرستادنِ کد
                  </Button>
                </div>
                {t.pending === "code" && (
                  <div className="grid gap-2 sm:grid-cols-3">
                    <Input dir="ltr" placeholder={`کد (به ${t.pending_phone} رفت)`} value={tgForm.code} onChange={(e) => setTgForm({ ...tgForm, code: e.target.value })} autoComplete="off" />
                    <Button disabled={act.busy || !tgForm.code} onClick={() => { void tgCall("code", { code: tgForm.code }); setTgForm({ ...tgForm, code: "" }); }}>
                      تأییدِ کد
                    </Button>
                  </div>
                )}
                {t.pending === "password" && (
                  <div className="grid gap-2 sm:grid-cols-3">
                    <Input dir="ltr" type="password" placeholder="رمزِ دومرحله‌ای" value={tgForm.password} onChange={(e) => setTgForm({ ...tgForm, password: e.target.value })} autoComplete="off" />
                    <Button disabled={act.busy || !tgForm.password} onClick={() => { void tgCall("password", { password: tgForm.password }); setTgForm({ ...tgForm, password: "" }); }}>
                      تأییدِ رمز
                    </Button>
                  </div>
                )}
              </>
            )}
          </div>
        )}
      </Card>

      <Card>
        <SectionTitle>آخرین نتیجه‌های جستجو</SectionTitle>
        {!recent.data?.results.length ? (
          <p className="text-sm" style={{ color: "var(--text-3)" }}>
            هنوز جستجویی انجام نشده است.
          </p>
        ) : (
          <Table>
            <thead>
              <tr>
                <th>شماره</th>
                <th>پیام‌رسان</th>
                <th>نتیجه</th>
                <th>نام</th>
                <th>نام‌کاربری</th>
                <th>زمان</th>
                <th>چرا</th>
              </tr>
            </thead>
            <tbody>
              {recent.data.results.map((p) => (
                <tr key={p.uid}>
                  <td dir="ltr">{p.number}</td>
                  <td>{p.label}</td>
                  <td>{p.status === "found" ? "هست" : p.status === "not_found" ? "نیست" : p.status}</td>
                  <td>{p.display_name || "—"}</td>
                  <td dir="ltr">{p.username ? `@${p.username}` : "—"}</td>
                  <td>{when(p.looked_up_at)}</td>
                  <td>{p.trigger === "call" ? "تماسِ واقعی" : "جستجوی دستی"}</td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
    </div>
  );
}

/* ------------------------------------------------------------------ settings */

const SWITCHES: [string, string][] = [
  ["sms_enabled", "صفِ پیامک روشن است (خاموش = توقفِ کلیِ ارسال)"],
  ["forward_incoming_sms", "پیامک‌های دریافتی به NM فرستاده شود (خاموش: فقط «لغو/stop»)"],
  ["calls_upload_enabled", "بارگذاریِ ضبطِ تماس"],
  ["asr_enabled", "تبدیلِ تماس به متن"],
  ["otp_ignores_opt_out", "کدِ تأیید (OTP) به فهرستِ «لغو» توجه نکند (پیشنهاد نمی‌شود)"],
];
const NUMBERS: [string, string][] = [
  ["max_sms_per_hour", "سقفِ پیامک در ساعت (هر گوشی)"],
  ["max_sms_per_day", "سقفِ پیامک در روز (هر گوشی)"],
  ["max_marketing_per_hour", "سقفِ پیامکِ تبلیغاتی در ساعت (هر گوشی)"],
  ["claim_batch", "حداکثر پیامک در هر نوبت"],
  ["quiet_start_hour", "شروعِ ساعتِ سکوتِ تبلیغاتی (۰–۲۳)"],
  ["quiet_end_hour", "پایانِ ساعتِ سکوت (۰–۲۳)"],
  ["max_audio_mb", "بیشینهٔ حجمِ ضبط (مگابایت)"],
  ["lookup_cache_days", "نگهداریِ نتیجهٔ پیام‌رسان (روز)"],
  ["lookup_per_device_hour", "جستجو در ساعت (هر گوشی)"],
  ["lookup_per_device_day", "جستجو در روز (هر گوشی)"],
  ["lookup_per_platform_day", "جستجو در روز (هر پیام‌رسان، کل)"],
  ["lookup_manual_per_user_day", "جستجوی دستی در روز (هر کاربر)"],
  ["lookup_burst_numbers_per_hour", "حداکثر شمارهٔ متفاوت در ساعت (ضدِ جستجوی فهرستی)"],
];

function SettingsTab() {
  const s = useLoad("/mobile/admin/settings/");
  const log = useLoad<{ count: number; results: Dict[] }>(`${M}/admin/actions-log/?limit=60`);
  const act = useAction();
  const [draft, setDraft] = useState<Dict>({});
  useEffect(() => {
    if (s.data) setDraft(s.data);
  }, [s.data]);
  const save = () =>
    act.run(async () => {
      const body: Dict = {};
      for (const [k] of SWITCHES) body[k] = !!draft[k];
      for (const [k] of NUMBERS) body[k] = Number(draft[k]);
      await api.patch(`${M}/admin/settings/`, body);
      await s.reload();
      await log.reload();
    }, "ذخیره شد.");
  return (
    <div className="grid gap-5">
      <ErrorBox message={s.error || act.error} />
      <Card>
        <SectionTitle>تنظیمات</SectionTitle>
        {!s.data ? (
          <Spinner />
        ) : (
          <>
            <div className="grid gap-2">
              {SWITCHES.map(([k, label]) => (
                <label key={k} className="flex items-center gap-2 text-sm">
                  <input type="checkbox" checked={!!draft[k]} onChange={(e) => setDraft({ ...draft, [k]: e.target.checked })} />
                  {label}
                </label>
              ))}
            </div>
            <div className="mt-4 grid gap-3 sm:grid-cols-3">
              {NUMBERS.map(([k, label]) => (
                <Field key={k} label={label}>
                  <Input dir="ltr" inputMode="numeric" value={draft[k] ?? ""} onChange={(e) => setDraft({ ...draft, [k]: e.target.value })} />
                </Field>
              ))}
            </div>
            <div className="mt-4 flex items-center gap-3">
              <Button disabled={act.busy} onClick={() => void save()}>
                ذخیرهٔ تنظیمات
              </Button>
              {act.done && <span className="text-sm" style={{ color: "var(--ok)" }}>{act.done}</span>}
            </div>
          </>
        )}
      </Card>
      <Card>
        <SectionTitle>گزارشِ اقدام‌ها (چه کسی، از کدام گوشی، چه کرد)</SectionTitle>
        {!log.data?.results.length ? (
          <p className="text-sm" style={{ color: "var(--text-3)" }}>
            اقدامی ثبت نشده است.
          </p>
        ) : (
          <Table>
            <thead>
              <tr>
                <th>زمان</th>
                <th>کاربر</th>
                <th>گوشی</th>
                <th>اقدام</th>
                <th>هدف</th>
                <th>نتیجه</th>
              </tr>
            </thead>
            <tbody>
              {log.data.results.map((r, i) => (
                <tr key={`${r.at}-${i}`}>
                  <td>{when(r.at)}</td>
                  <td>{r.user || "—"}</td>
                  <td>{r.device || "پنل"}</td>
                  <td dir="ltr">{r.action}</td>
                  <td dir="ltr">{r.target || "—"}</td>
                  <td>{r.ok ? <Badge tone="ok">ok</Badge> : <Badge tone="bad">ناموفق</Badge>} {r.message}</td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
    </div>
  );
}
