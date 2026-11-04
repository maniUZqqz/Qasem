import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import Icon from "../../../components/Icon";
import { Alert, Badge, Button, Card, Field, Input, PageHeader, Select, fa } from "../../../components/ui";
import { g, useGet } from "../api";
import { LoadState } from "../components/bits";
import { ChannelBadge } from "../components/outreach/ChannelBits";
import { Flash, SendingBanners } from "../components/outreach/shared";
import { asList, useAction, useSettings } from "../outreach/api";
import type { ChannelInfo, Template } from "../outreach/types";
import type { Paged } from "../types";

type FormState = {
  cap: string;
  spacingMin: string;
  spacingMax: string;
  template: string;
  config: Record<string, string>;
  password: string;
};

function initial(ch: ChannelInfo): FormState {
  const config: Record<string, string> = {};
  for (const field of ch.config_schema) {
    const value = ch.config.set?.[field.name];
    config[field.name] = value === undefined || value === null ? "" : String(value);
  }
  return {
    cap: ch.daily_cap == null ? "" : String(ch.daily_cap),
    spacingMin: ch.spacing_min_seconds == null ? "" : String(ch.spacing_min_seconds),
    spacingMax: ch.spacing_max_seconds == null ? "" : String(ch.spacing_max_seconds),
    template: ch.default_template ? String(ch.default_template.id) : "",
    config,
    password: "",
  };
}

const num = (value: string): number | null => (value.trim() === "" ? null : Number(value));

function ChannelCard({
  ch,
  index,
  total,
  templates,
  onMove,
  onChanged,
}: {
  ch: ChannelInfo;
  index: number;
  total: number;
  templates: Template[];
  onMove: (delta: number) => void;
  onChanged: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState<FormState>(() => initial(ch));
  const [flash, setFlash] = useState<{ tone: "ok" | "bad" | "warn"; text: string } | null>(null);
  const toggle = useAction();
  const save = useAction();
  const verify = useAction();
  const clearPassword = useAction();
  const manual = ch.kind === "manual";
  const inForce = ch.config.in_force ?? {};
  const fromServer = new Set(ch.config.from_server ?? []);

  useEffect(() => {
    setForm(initial(ch));
  }, [ch]);

  const options = templates.filter((t) => !t.channel || t.channel === "any" || t.channel === ch.key);
  const set = (patch: Partial<FormState>) => setForm((f) => ({ ...f, ...patch }));

  const flip = async () => {
    const done = await toggle.run(() => g.patch<ChannelInfo>(`/outreach/channels/${ch.key}/`, { enabled: !ch.enabled }));
    if (done) {
      setFlash({ tone: "ok", text: done.enabled ? `کانالِ «${ch.label}» روشن شد.` : `کانالِ «${ch.label}» خاموش شد.` });
      onChanged();
    }
  };

  const submit = async () => {
    const body: Record<string, unknown> = { default_template_id: num(form.template) };
    if (!manual) {
      body.daily_cap = num(form.cap);
      body.spacing_min_seconds = num(form.spacingMin);
      body.spacing_max_seconds = num(form.spacingMax);
    }
    if (ch.config_schema.length) {
      const config: Record<string, unknown> = {};
      for (const field of ch.config_schema) {
        const raw = form.config[field.name] ?? "";
        config[field.name] = raw === "" ? "" : field.type === "int" ? Number(raw) : raw;
      }
      body.config = config;
    }
    if (form.password) body.secrets = { smtp_password: form.password };
    const done = await save.run(() => g.patch<ChannelInfo>(`/outreach/channels/${ch.key}/`, body));
    if (done) {
      setFlash({ tone: "ok", text: "ذخیره شد." });
      set({ password: "" });
      onChanged();
    }
  };

  const check = async () => {
    const result = await verify.run(() => g.post<{ ok: boolean; message: string }>("/outreach/channels/email/verify/"));
    if (result) setFlash({ tone: result.ok ? "ok" : "bad", text: result.message });
  };

  const dropPassword = async () => {
    const done = await clearPassword.run(() => g.patch<ChannelInfo>(`/outreach/channels/${ch.key}/`, { clear_secrets: ["smtp_password"] }));
    if (done) {
      setFlash({ tone: "ok", text: "رمزِ ذخیره‌شده پاک شد." });
      onChanged();
    }
  };

  const status = !ch.ready ? (
    <Badge tone="warn">{ch.needs_app ? "نیاز به اپِ NM-Mobile" : "کامل نیست"}</Badge>
  ) : ch.enabled ? (
    <Badge tone="ok">روشن</Badge>
  ) : (
    <Badge tone="neutral">خاموش</Badge>
  );

  return (
    <Card>
      <div className="space-y-4" data-testid={`channel-${ch.key}`} data-enabled={ch.enabled ? "1" : "0"}>
        <div className="flex flex-wrap items-center gap-3">
          <span className="u-num grid h-7 w-7 place-items-center rounded-full text-xs font-bold" style={{ background: "var(--surface-2)", border: "1px solid var(--line)", color: "var(--text-2)" }} aria-label={`اولویت ${index + 1}`}>
            {fa(index + 1)}
          </span>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="text-base font-extrabold" style={{ color: "var(--text)" }}>
                {ch.label}
              </h3>
              <ChannelBadge channel={ch.key} label={manual ? "را خودتان می‌فرستید" : "سیستم می‌فرستد (با تأییدِ شما)"} />
              {status}
            </div>
            <p className="mt-0.5 text-xs leading-6" style={{ color: "var(--text-3)" }}>
              {ch.description}
            </p>
          </div>
          <div className="mr-auto flex flex-wrap items-center gap-1.5">
            <Button variant="ghost" size="sm" onClick={() => onMove(-1)} disabled={index === 0} aria-label="اولویتِ بیشتر" data-testid={`move-up-${ch.key}`}>
              <Icon name="up" size={15} />
            </Button>
            <Button variant="ghost" size="sm" onClick={() => onMove(1)} disabled={index === total - 1} aria-label="اولویتِ کمتر" data-testid={`move-down-${ch.key}`}>
              <Icon name="down" size={15} />
            </Button>
            <Button variant={ch.enabled ? "secondary" : "primary"} size="sm" onClick={flip} disabled={toggle.busy} data-testid={`toggle-${ch.key}`}>
              {ch.enabled ? "خاموش کن" : "روشن کن"}
            </Button>
            <Button variant="secondary" size="sm" onClick={() => setOpen((v) => !v)} aria-expanded={open} data-testid={`open-${ch.key}`}>
              <Icon name="settings" size={14} /> تنظیمات
            </Button>
          </div>
        </div>

        {!ch.ready && ch.not_ready_reason && (
          <Alert tone="warn" title="این کانال هنوز آماده نیست" action={ch.needs_app ? <Link to="/tools/mobile" className="u-btn u-btn-secondary u-btn-sm no-underline">دستگاه‌های موبایل</Link> : undefined}>
            {ch.not_ready_reason}
          </Alert>
        )}
        {toggle.error && <Flash tone="bad">{toggle.error.message}</Flash>}
        {ch.hint && (
          <p className="text-xs" style={{ color: "var(--text-3)" }}>
            {ch.hint}
          </p>
        )}
        {!manual && (
          <p className="text-xs" style={{ color: "var(--text-3)" }}>
            امروز {fa(ch.sent_today ?? 0)} بار استفاده شد
            {ch.cap_remaining != null ? ` · ${fa(ch.cap_remaining)} بارِ دیگر برای امروز مانده (سقفِ این کانال)` : " · سقفِ جداگانه ندارد (فقط سقفِ کلی)"}.
          </p>
        )}

        {open && (
          <div className="space-y-4 border-t pt-4" style={{ borderColor: "var(--line)" }} data-testid={`form-${ch.key}`}>
            {!manual && (
              <div className="grid gap-4 sm:grid-cols-3">
                <Field label="سقفِ روزانهٔ این کانال" hint="خالی = فقط سقفِ کلیِ «تنظیمات»">
                  <Input type="number" min={1} max={500} value={form.cap} onChange={(e) => set({ cap: e.target.value })} data-testid={`cap-${ch.key}`} />
                </Field>
                <Field label="حداقل فاصلهٔ دو ارسال (ثانیه)" hint="خالی = مثلِ «تنظیمات»">
                  <Input type="number" min={10} max={3600} value={form.spacingMin} onChange={(e) => set({ spacingMin: e.target.value })} data-testid={`spacing-min-${ch.key}`} />
                </Field>
                <Field label="حداکثر فاصله (ثانیه)" hint="هر دو را پر کنید یا هر دو را خالی بگذارید">
                  <Input type="number" min={10} max={3600} value={form.spacingMax} onChange={(e) => set({ spacingMax: e.target.value })} data-testid={`spacing-max-${ch.key}`} />
                </Field>
              </div>
            )}

            <Field label="قالبِ پیش‌فرضِ این کانال" hint="وقتی کمپینی «خودکار (بر اساسِ اولویت)» است و این کانال برای یک لید انتخاب شود، از این قالب استفاده می‌شود. خالی = اولین قالبِ فعالِ همین کانال.">
              <Select value={form.template} onChange={(e) => set({ template: e.target.value })} data-testid={`template-${ch.key}`}>
                <option value="">— خودکار —</option>
                {options.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.name}
                  </option>
                ))}
              </Select>
            </Field>

            {ch.config_schema.length > 0 && (
              <div className="space-y-3">
                <h4 className="text-sm font-extrabold" style={{ color: "var(--text)" }}>
                  {ch.key === "email" ? "حسابِ ایمیل (SMTP)" : "تنظیماتِ این کانال"}
                </h4>
                <div className="grid gap-4 sm:grid-cols-2">
                  {ch.config_schema.map((field) => {
                    const server = fromServer.has(field.name) ? inForce[field.name] : undefined;
                    const placeholder = server !== undefined && server !== "" ? `مقدارِ سرور: ${String(server)}` : field.default !== undefined ? String(field.default) : "";
                    return (
                      <Field key={field.name} label={field.label} hint={field.help}>
                        {field.type === "choice" ? (
                          <Select value={form.config[field.name] ?? ""} onChange={(e) => set({ config: { ...form.config, [field.name]: e.target.value } })} data-testid={`cfg-${field.name}`}>
                            <option value="">{placeholder ? `— ${placeholder} —` : "— مقدارِ سرور —"}</option>
                            {(field.choices ?? []).map(([value, label]) => (
                              <option key={value} value={value}>
                                {label}
                              </option>
                            ))}
                          </Select>
                        ) : (
                          <Input
                            type={field.type === "int" ? "number" : "text"}
                            dir={field.type === "email" || field.name === "host" || field.name === "username" ? "ltr" : undefined}
                            min={field.min}
                            max={field.max}
                            value={form.config[field.name] ?? ""}
                            placeholder={placeholder}
                            onChange={(e) => set({ config: { ...form.config, [field.name]: e.target.value } })}
                            data-testid={`cfg-${field.name}`}
                          />
                        )}
                      </Field>
                    );
                  })}
                </div>
                {Object.entries(ch.secrets).map(([name, secret]) => (
                  <div key={name} className="space-y-1.5">
                    <Field
                      label={secret.label}
                      hint={secret.is_set ? "رمز ذخیره شده است و هرگز دوباره نشان داده نمی‌شود. فقط اگر می‌خواهید عوضش کنید چیزی بنویسید." : secret.server_default ? "رمز از تنظیمِ سرور (.env) خوانده می‌شود؛ اینجا می‌توانید رمزِ دیگری بگذارید." : "رمز را اینجا بنویسید؛ فقط در پایگاه داده می‌ماند و جای دیگری نمی‌رود."}
                    >
                      <Input type="password" autoComplete="new-password" dir="ltr" value={form.password} onChange={(e) => set({ password: e.target.value })} placeholder={secret.is_set ? "••••••••  (ذخیره شده)" : ""} data-testid="smtp-password" />
                    </Field>
                    {secret.is_set && (
                      <Button variant="ghost" size="sm" onClick={dropPassword} disabled={clearPassword.busy} data-testid="smtp-password-clear">
                        پاک کردنِ رمزِ ذخیره‌شده
                      </Button>
                    )}
                  </div>
                ))}
              </div>
            )}

            {ch.key === "email" && (
              <Alert tone="info" title="دربارهٔ ایمیل">
                هر ایمیل امضای فرستنده و جملهٔ لغو دارد و پاسخ‌ها به ایمیلِ «تنظیماتِ جذب مشتری» می‌آید؛ هدرِ «لغو عضویت» هم دارد. «بررسیِ اتصال» فقط وارد سرور می‌شود و هیچ ایمیلی نمی‌فرستد. فرستادنِ زیاد از یک سرورِ جدید ممکن است ایمیل‌ها را به هرزنامه ببرد؛ سقفِ روزانه را کم نگه دارید.
              </Alert>
            )}
            {ch.key === "sms" && (
              <Alert tone="info" title="دربارهٔ پیامک">
                پیامک از سیم‌کارتِ گوشیِ جفت‌شده با اپِ NM-Mobile می‌رود. ساعتِ سکوتِ ۲۱ تا ۸، سقفِ ساعتی و فهرستِ «لغو» را خودِ اپ هم رعایت می‌کند. «ارسال شد» فقط وقتی نوشته می‌شود که گوشی گزارش بدهد.
              </Alert>
            )}

            {flash && (
              <Flash tone={flash.tone} onClose={() => setFlash(null)}>
                {flash.text}
              </Flash>
            )}
            {(save.error || verify.error || clearPassword.error) && <Flash tone="bad">{(save.error ?? verify.error ?? clearPassword.error)?.message}</Flash>}
            <div className="flex flex-wrap items-center gap-2">
              <Button onClick={submit} disabled={save.busy} data-testid={`save-${ch.key}`}>
                {save.busy ? "در حال ذخیره…" : "ذخیره"}
              </Button>
              {ch.key === "email" && (
                <Button variant="secondary" onClick={check} disabled={verify.busy} data-testid="email-verify">
                  {verify.busy ? "در حال بررسی…" : "بررسیِ اتصال (ایمیلی نمی‌فرستد)"}
                </Button>
              )}
            </div>
          </div>
        )}
        {!open && flash && (
          <Flash tone={flash.tone} onClose={() => setFlash(null)}>
            {flash.text}
          </Flash>
        )}
      </div>
    </Card>
  );
}

/**
 * «کانال‌ها»: which ways of reaching a business are on, in which order they are tried, how much each may send per day and how
 * far apart, the default template of each, and the e-mail account. Secrets are never shown back.
 */
export default function ChannelsPage() {
  const channels = useGet<{ channels: ChannelInfo[] }>("/outreach/channels/");
  const templatesData = useGet<Paged<Template> | Template[]>("/outreach/templates/", { active: 1, page_size: 100 });
  const settings = useSettings();
  const reorder = useAction();
  const templates = useMemo(() => asList(templatesData.data).filter((t) => t.is_active), [templatesData.data]);
  const list = channels.data?.channels ?? [];

  const move = async (index: number, delta: number) => {
    const order = list.map((c) => c.key);
    const target = index + delta;
    if (target < 0 || target >= order.length) return;
    [order[index], order[target]] = [order[target], order[index]];
    const done = await reorder.run(() => g.post<{ channels: ChannelInfo[] }>("/outreach/channels/reorder/", { order }));
    if (done) channels.setData(done);
  };

  return (
    <div className="space-y-5" data-testid="channels-page">
      <SendingBanners settings={settings.data} onChanged={settings.reload} />
      <PageHeader
        title="کانال‌های ارسال"
        subtitle="پیام از چه راهی برود؟ هر کانال را روشن یا خاموش کنید، ترتیبِ امتحان‌شدنشان را بچینید و سقف و فاصلهٔ هر کدام را بگذارید."
      />
      <Alert tone="info" title="اولویت یعنی چه؟">
        در یک کمپینِ «خودکار (بر اساسِ اولویت)»، برای هر لید اولین کانالِ <b>روشن</b> که بتواند به او برسد انتخاب می‌شود (بالاترین کارت = اول). سه کانالِ اول را سیستم بعد از تأییدِ شما می‌فرستد؛ بقیه را خودتان با لینکِ آماده از «صفِ دستی» می‌فرستید و نتیجه را ثبت می‌کنید. هیچ حسابِ پیام‌رسانی خودکار نمی‌شود.
      </Alert>
      {reorder.error && <Flash tone="bad">{reorder.error.message}</Flash>}
      <LoadState loading={channels.loading && !channels.data} error={channels.error} onRetry={channels.reload}>
        <div className="space-y-4">
          {list.map((ch, i) => (
            <ChannelCard key={ch.key} ch={ch} index={i} total={list.length} templates={templates} onMove={(d) => void move(i, d)} onChanged={channels.reload} />
          ))}
        </div>
      </LoadState>
    </div>
  );
}
