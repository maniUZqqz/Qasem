import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { errorMessage } from "../../api/client";
import { Alert, Badge, Button, Card, ErrorBox, Field, Input, Select, Spinner } from "../../components/ui";
import { ChannelField, ChannelInfo, get, post, put } from "./api";
import { ago, channelColor, copy, faNum } from "./format";
import { useInbox } from "./InboxLayout";

function statusOf(c: ChannelInfo): { tone: "ok" | "warn" | "bad" | "neutral"; text: string } {
  if (!c.enabled) return { tone: "neutral", text: c.ready ? "خاموش" : "وصل نشده" };
  if (c.health.ok === false) return { tone: "bad", text: "مشکل دارد" };
  if (c.health.ok === null && c.kind !== "WEBCHAT" && c.kind !== "SMS") return { tone: "warn", text: "بررسی نشده" };
  return { tone: "ok", text: "فعال" };
}

function ChannelCard({ info, storeId, canEdit, isStaff, onChanged }: { info: ChannelInfo; storeId: string; canEdit: boolean; isStaff: boolean; onChanged: () => void }) {
  const [open, setOpen] = useState(false);
  const [values, setValues] = useState<Record<string, string | boolean | string[]>>({});
  const [mode, setMode] = useState(info.mode);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const status = statusOf(info);
  const isInstagram = info.kind === "INSTAGRAM";

  useEffect(() => setMode(info.mode), [info.mode]);

  const valueOf = (f: ChannelField): string | boolean | string[] => {
    if (f.key in values) return values[f.key];
    if (f.key === "token") return "";
    const stored = info.config[f.key];
    if (f.kind === "bool") return Boolean(stored);
    if (f.kind === "list") return Array.isArray(stored) ? (stored as string[]) : [];
    return typeof stored === "string" ? stored : "";
  };

  const run = async (fn: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    setNote(null);
    try {
      await fn();
      onChanged();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const save = (enable?: boolean) =>
    run(async () => {
      const body: Record<string, unknown> = { mode };
      for (const f of info.fields) {
        if (f.key in values) body[f.key] = values[f.key];
      }
      if (enable !== undefined) body.enabled = enable;
      const res = await put<{ message?: string; enabled_refused?: string }>(storeId, `channels/${info.kind}/`, body);
      setValues({});
      if (res.enabled_refused) setError(res.enabled_refused);
      else setNote(res.message || (enable === false ? "کانال خاموش شد." : "ذخیره شد."));
    });

  const check = () =>
    run(async () => {
      const res = await post<{ ok: boolean; detail: string }>(storeId, `channels/${info.kind}/check/`);
      setNote(res.ok ? `سالم است. ${res.detail}` : `مشکل: ${res.detail}`);
    });

  return (
    <Card>
      <div className="flex items-start gap-3">
        <span className="mt-1 h-3 w-3 shrink-0 rounded-full" style={{ background: channelColor(info.kind) }} aria-hidden />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-base font-extrabold" style={{ color: "var(--text)" }}>{info.title}</h3>
            <Badge tone={status.tone}>{status.text}</Badge>
            {info.needs_owner_account && <Badge tone="warn">نیاز به حساب رسمی</Badge>}
            {info.health.account && <span className="text-xs" dir="ltr" style={{ color: "var(--text-3)" }}>{info.health.account}</span>}
          </div>
          <p className="mt-1 text-xs leading-6" style={{ color: "var(--text-3)" }}>{info.summary}</p>
        </div>
        <Button size="sm" variant={open ? "secondary" : "primary"} onClick={() => setOpen((v) => !v)} aria-expanded={open}>
          {open ? "بستن" : info.enabled ? "تنظیمات" : "وصل کن"}
        </Button>
      </div>

      <div className="mt-3 grid gap-1 text-xs" style={{ color: "var(--text-3)" }}>
        {info.health.detail && <span>وضعیت: {info.health.detail}</span>}
        {info.enabled && (
          <span>
            آخرین پیام دریافتی: {ago(info.last_inbound_at)} · دریافتی {faNum(info.inbound_count)} · ارسالی {faNum(info.outbound_count)}
          </span>
        )}
        {info.last_error && <span style={{ color: "var(--bad)" }}>آخرین خطا: {info.last_error}</span>}
      </div>

      {open && (
        <div className="mt-4 grid gap-4">
          <div>
            <h4 className="mb-2 text-sm font-bold" style={{ color: "var(--text)" }}>راهنمای قدم‌به‌قدم</h4>
            <ol className="ib-steps">
              {info.steps.map((s) => (
                <li key={s}>{s}</li>
              ))}
            </ol>
            <p className="mt-2 text-xs leading-6" style={{ color: "var(--text-3)" }}>{info.limits}</p>
            {info.docs && (
              <a href={info.docs} target="_blank" rel="noreferrer" className="text-xs" style={{ color: "var(--brand-strong)" }}>
                مستندات رسمی ↗
              </a>
            )}
          </div>

          {info.kind === "WHATSAPP" && (
            <Alert tone="warn" title="این کانال به‌طور پیش‌فرض خاموش است">
              واتساپ فقط با حساب رسمی WhatsApp Business (Cloud API) کار می‌کند. اتصال‌های غیررسمی خطر مسدود شدن شمارهٔ شما را دارند و ما چنین اتصالی نمی‌سازیم.
            </Alert>
          )}

          {isInstagram ? (
            <div className="grid gap-2 *:min-w-0">
              <Alert tone={info.ready ? "ok" : "info"} title={info.ready ? "ارسال از طریق نوین‌هاب آماده است" : "ارسال هنوز تنظیم نشده"}>
                توکن نوین‌هاب را در صفحهٔ <Link to={`/stores/${storeId}/connections`} style={{ color: "var(--brand-strong)" }}>اتصال شبکه‌ها</Link> بگذارید. دریافت دایرکت با تأیید اپ در Meta روشن می‌شود.
              </Alert>
              <Field label="نشانی وب‌هوک برای اپ Meta" hint="در تنظیمات وب‌هوک اپ خود وارد کنید.">
                <div className="flex gap-2">
                  <input className="u-input" dir="ltr" readOnly value={info.hook_url} aria-label="نشانی وب‌هوک" />
                  <Button size="sm" variant="secondary" onClick={() => void copy(info.hook_url)}>کپی</Button>
                </div>
              </Field>
            </div>
          ) : (
            <>
              {info.fields.map((f) => {
                const value = valueOf(f);
                if (f.kind === "bool") {
                  return (
                    <label key={f.key} className="flex items-start gap-2 text-sm" style={{ color: "var(--text-2)" }}>
                      <input type="checkbox" className="mt-1" checked={Boolean(value)} disabled={!canEdit} onChange={(e) => setValues({ ...values, [f.key]: e.target.checked })} />
                      <span>
                        {f.label}
                        {f.help && <span className="block text-xs" style={{ color: "var(--text-3)" }}>{f.help}</span>}
                      </span>
                    </label>
                  );
                }
                if (f.kind === "list") {
                  return (
                    <Field key={f.key} label={f.label} hint={f.help}>
                      <textarea
                        className="u-input"
                        dir="ltr"
                        rows={2}
                        disabled={!canEdit}
                        placeholder={f.placeholder}
                        value={(value as string[]).join("\n")}
                        onChange={(e) => setValues({ ...values, [f.key]: e.target.value.split("\n") })}
                      />
                    </Field>
                  );
                }
                const isToken = f.key === "token";
                const saved = f.secret && (isToken ? info.masked_token : f.key === "app_secret" && info.has_app_secret ? "••••" : "");
                return (
                  <Field key={f.key} label={f.label} hint={saved ? `ذخیره‌شده: ${saved} — برای عوض کردن، مقدار تازه بنویسید.` : f.help}>
                    <Input
                      dir="ltr"
                      type={f.secret ? "password" : "text"}
                      autoComplete="off"
                      disabled={!canEdit}
                      placeholder={f.placeholder}
                      value={typeof value === "string" ? value : ""}
                      onChange={(e) => setValues({ ...values, [f.key]: e.target.value })}
                    />
                  </Field>
                );
              })}

              {info.hook_url && info.kind !== "WEBCHAT" && (
                <Field label="نشانی وب‌هوک" hint="اگر ثبت خودکار ممکن نبود، همین را در پنل پلتفرم وارد کنید. این نشانی یک رمز است؛ جایی منتشرش نکنید.">
                  <div className="flex gap-2">
                    <input className="u-input" dir="ltr" readOnly value={info.hook_url} aria-label="نشانی وب‌هوک" />
                    <Button size="sm" variant="secondary" onClick={() => void copy(info.hook_url)}>کپی</Button>
                  </div>
                </Field>
              )}

              {info.kind === "WEBCHAT" && info.snippet && (
                <Field label="کد ویجت" hint="درست پیش از بستن برچسب </body> صفحه‌هایتان بگذارید؛ روی هر سایتی (از جمله سایت‌های سایت‌ساز) کار می‌کند.">
                  <div className="grid gap-2 *:min-w-0">
                    <div className="ib-code">{info.snippet}</div>
                    <div className="flex flex-wrap gap-2">
                      <Button size="sm" variant="secondary" onClick={() => void copy(info.snippet ?? "")}>کپی کد</Button>
                      <Link to={`/stores/${storeId}/inbox/bot`} className="u-btn u-btn-ghost u-btn-sm">ظاهر ویجت (رنگ، عنوان، پیام خوش‌آمد)</Link>
                    </div>
                  </div>
                </Field>
              )}

              {info.kind === "SMS" && info.sms && (
                <div className="grid gap-2 text-sm *:min-w-0" style={{ color: "var(--text-2)" }}>
                  <div>
                    گوشی‌های متصل: {info.sms.phones.length ? info.sms.phones.map((p) => `${p.name} (${p.online ? "آنلاین" : "آفلاین"})`).join("، ") : "هیچ گوشی‌ای جفت نشده"}
                  </div>
                  {!info.sms.forwarding && (
                    <Alert tone="warn" title="ذخیرهٔ پیامک‌های دریافتی خاموش است">
                      تا مدیر سرویس این گزینه را در بخش موبایل روشن نکند، پیامکِ مشتری وارد صندوق نمی‌شود (ارسال کار می‌کند).
                      {isStaff && (
                        <>
                          {" "}
                          <Button size="sm" variant="secondary" disabled={busy} onClick={() => void run(async () => { await post(storeId, "channels/sms/forwarding/", { on: true }); setNote("روشن شد."); })}>
                            روشنش کن
                          </Button>
                        </>
                      )}
                    </Alert>
                  )}
                </div>
              )}

              {(info.kind === "TELEGRAM" || info.kind === "BALE" || info.kind === "EITAA" || info.kind === "RUBIKA") && (
                <Field label="روشِ گرفتنِ پیام" hint="خودکار: وب‌هوک وقتی سایت روی https است، وگرنه هر ۳۰ ثانیه از ربات می‌پرسد.">
                  <Select value={mode} disabled={!canEdit} onChange={(e) => setMode(e.target.value as ChannelInfo["mode"])}>
                    <option value="AUTO">خودکار</option>
                    <option value="WEBHOOK">فقط وب‌هوک</option>
                    <option value="POLLING">فقط پرسش دوره‌ای (هر ۳۰ ثانیه)</option>
                  </Select>
                </Field>
              )}

              <ErrorBox message={error} />
              {note && <div className="text-sm" style={{ color: "var(--ok)" }}>{note}</div>}
              {canEdit ? (
                <div className="flex flex-wrap gap-2">
                  <Button size="sm" disabled={busy} onClick={() => void save()}>ذخیره و بررسی</Button>
                  {!info.enabled ? (
                    <Button size="sm" variant="secondary" disabled={busy} onClick={() => void save(true)}>روشن کن</Button>
                  ) : (
                    <Button size="sm" variant="ghost" disabled={busy} onClick={() => void save(false)}>خاموش کن</Button>
                  )}
                  {info.kind !== "WEBCHAT" && <Button size="sm" variant="ghost" disabled={busy} onClick={() => void check()}>بررسی سلامت</Button>}
                  {["BALE", "EITAA", "RUBIKA", "TELEGRAM"].includes(info.kind) && info.enabled && (
                    <>
                      <Button size="sm" variant="ghost" disabled={busy} onClick={() => void run(async () => { const r = await post<{ ok: boolean; detail: string }>(storeId, `channels/${info.kind}/webhook/`); setNote(r.ok ? "وب‌هوک ثبت شد." : r.detail); })}>
                        ثبت وب‌هوک
                      </Button>
                      <Button size="sm" variant="ghost" disabled={busy} onClick={() => void run(async () => { const r = await post<{ polled: boolean; accepted?: number; reason?: string }>(storeId, `channels/${info.kind}/poll/`); setNote(r.polled ? `${faNum(r.accepted ?? 0)} پیام تازه گرفته شد.` : r.reason ?? ""); })}>
                        الان پیام‌ها را بگیر
                      </Button>
                    </>
                  )}
                </div>
              ) : (
                <p className="text-xs" style={{ color: "var(--text-3)" }}>فقط مالک یا مدیر فروشگاه می‌تواند کانال‌ها را تنظیم کند.</p>
              )}
            </>
          )}
        </div>
      )}
    </Card>
  );
}

export default function ChannelsPage() {
  const { storeId, me } = useInbox();
  const [rows, setRows] = useState<ChannelInfo[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await get<{ channels: ChannelInfo[] }>(storeId, "channels/");
      setRows(res.channels);
      setError(null);
    } catch (err) {
      setError(errorMessage(err));
    }
  }, [storeId]);

  useEffect(() => {
    void load();
  }, [load]);

  if (!rows) return <div className="py-10 text-center">{error ? <ErrorBox message={error} /> : <Spinner />}</div>;

  const on = rows.filter((r) => r.enabled).length;
  return (
    <div className="grid gap-4 *:min-w-0">
      <ErrorBox message={error} />
      <p className="text-sm" style={{ color: "var(--text-2)" }}>
        {faNum(on)} کانال از {faNum(rows.length)} کانال روشن است. هر کانال که وصل کنید، پیام‌هایش در همین صندوق می‌آید و پاسخ‌ها از همان کانال می‌رود.
      </p>
      <div className="ib-grid">
        {rows.map((r) => (
          <ChannelCard key={r.kind} info={r} storeId={storeId} canEdit={Boolean(me?.can_settings)} isStaff={Boolean(me?.is_staff)} onChanged={() => void load()} />
        ))}
      </div>
    </div>
  );
}
