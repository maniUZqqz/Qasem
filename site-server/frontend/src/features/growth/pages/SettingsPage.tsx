import { FormEvent, ReactNode, useEffect, useState } from "react";

import Icon from "../../../components/Icon";
import { Alert, Badge, Button, Card, Field, Input, PageHeader, SectionTitle, TextArea, fa } from "../../../components/ui";
import { g, useGet } from "../api";
import { ConfirmDialog } from "../components/Modal";
import { CapMeter, EmergencyStopButton, Flash, SendingBanners } from "../components/outreach/shared";
import { LoadState } from "../components/bits";
import { faDateTime } from "../format";
import { asList, fieldErrorsOf, useAction, useSettings } from "../outreach/api";
import { AUDIT_KIND, closingBlock } from "../outreach/labels";
import type { AuditEntry, GrowthSettings, SettingsPatch } from "../outreach/types";
import type { Paged } from "../types";

type Form = {
  sender_name: string;
  sender_company: string;
  sender_phone: string;
  sender_email: string;
  sender_website: string;
  opt_out_line: string;
  daily_cap: string;
  spacing_min_seconds: string;
  spacing_max_seconds: string;
};

const toForm = (s: GrowthSettings): Form => ({
  sender_name: s.sender_name,
  sender_company: s.sender_company,
  sender_phone: s.sender_phone,
  sender_email: s.sender_email,
  sender_website: s.sender_website,
  opt_out_line: s.opt_out_line,
  daily_cap: String(s.daily_cap),
  spacing_min_seconds: String(s.spacing_min_seconds),
  spacing_max_seconds: String(s.spacing_max_seconds),
});

function ErrorText({ children }: { children?: ReactNode }) {
  if (!children) return null;
  return (
    <span className="mt-1 block text-xs" style={{ color: "var(--bad)" }} role="alert">
      {children}
    </span>
  );
}

export default function SettingsPage() {
  const settings = useSettings();
  const audit = useGet<Paged<AuditEntry> | AuditEntry[]>("/settings/audit/");
  const [form, setForm] = useState<Form | null>(null);
  const [saved, setSaved] = useState(false);
  const [askEnable, setAskEnable] = useState(false);
  const save = useAction();
  const toggle = useAction();

  // fill the form once the settings arrive (and again after every save)
  useEffect(() => {
    if (settings.data && !form) setForm(toForm(settings.data));
  }, [settings.data, form]);

  const current = settings.data;
  const dirty = !!(current && form && JSON.stringify(toForm(current)) !== JSON.stringify(form));
  const errors = fieldErrorsOf(save.error);
  const set = (key: keyof Form) => (e: { target: { value: string } }) => {
    setSaved(false);
    setForm((f) => (f ? { ...f, [key]: e.target.value } : f));
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!form) return;
    const patch: SettingsPatch = {
      sender_name: form.sender_name.trim(),
      sender_company: form.sender_company.trim(),
      sender_phone: form.sender_phone.trim(),
      sender_email: form.sender_email.trim(),
      sender_website: form.sender_website.trim(),
      opt_out_line: form.opt_out_line.trim(),
      daily_cap: Number(form.daily_cap),
      spacing_min_seconds: Number(form.spacing_min_seconds),
      spacing_max_seconds: Number(form.spacing_max_seconds),
    };
    const result = await save.run(() => g.patch<GrowthSettings>("/settings/", patch));
    if (result) {
      settings.setData(result);
      setForm(toForm(result));
      setSaved(true);
      audit.reload();
    }
  };

  const setSending = async (on: boolean) => {
    const result = await toggle.run(() => g.patch<GrowthSettings>("/settings/", { sending_enabled: on }));
    if (result) {
      settings.setData(result);
      setAskEnable(false);
      audit.reload();
    }
  };

  const onToggle = () => {
    if (current?.sending_enabled) {
      void setSending(false);
    } else {
      toggle.clear();
      setAskEnable(true);
    }
  };

  const reloadAll = () => {
    settings.reload();
    audit.reload();
  };

  return (
    <LoadState loading={settings.loading && !current} error={settings.error} onRetry={settings.reload}>
      {current && form && (
        <div className="space-y-5" data-testid="settings-page">
          <SendingBanners settings={current} onChanged={reloadAll} showSettingsLink={false} />
          <PageHeader title="تنظیماتِ جذب مشتری" subtitle="هویتِ فرستنده، سقفِ ارسال، کلیدِ ارسالِ خودکار و توقفِ اضطراری" />

          <div className="grid gap-5 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
            {/* ------------------------------------------------------------ identity + limits */}
            <form onSubmit={submit} className="space-y-5" data-testid="settings-form" noValidate>
              <Card>
                <SectionTitle>مشخصاتِ فرستنده</SectionTitle>
                <p className="mb-4 text-sm leading-7" style={{ color: "var(--text-3)" }}>
                  این مشخصات عیناً زیرِ هر پیام می‌آید. باید راست و واقعی باشد: گیرنده باید بداند پیام از کیست و چطور جواب بدهد.
                </p>
                <div className="grid gap-4 sm:grid-cols-2">
                  <Field label="نام و نام‌خانوادگی">
                    <Input value={form.sender_name} onChange={set("sender_name")} maxLength={120} data-testid="sender-name" />
                    <ErrorText>{errors.sender_name}</ErrorText>
                  </Field>
                  <Field label="نامِ شرکت / برند">
                    <Input value={form.sender_company} onChange={set("sender_company")} maxLength={120} data-testid="sender-company" />
                    <ErrorText>{errors.sender_company}</ErrorText>
                  </Field>
                  <Field label="تلفن">
                    <Input dir="ltr" inputMode="tel" value={form.sender_phone} onChange={set("sender_phone")} maxLength={40} data-testid="sender-phone" />
                    <ErrorText>{errors.sender_phone}</ErrorText>
                  </Field>
                  <Field label="ایمیل">
                    <Input dir="ltr" inputMode="email" value={form.sender_email} onChange={set("sender_email")} maxLength={120} data-testid="sender-email" />
                    <ErrorText>{errors.sender_email}</ErrorText>
                  </Field>
                  <Field label="وب‌سایت (اختیاری)" hint="برای فرم‌هایی که آدرسِ سایت می‌خواهند">
                    <Input dir="ltr" inputMode="url" value={form.sender_website} onChange={set("sender_website")} maxLength={200} />
                    <ErrorText>{errors.sender_website}</ErrorText>
                  </Field>
                </div>
                <div className="mt-4">
                  <Field label="جملهٔ لغو (آخرِ هر پیام)" hint="گیرنده با همین جمله بداند چطور از دریافتِ پیام انصراف بدهد.">
                    <TextArea rows={2} value={form.opt_out_line} onChange={set("opt_out_line")} maxLength={300} data-testid="opt-out-line" />
                    <ErrorText>{errors.opt_out_line}</ErrorText>
                  </Field>
                </div>
                <div className="mt-4 rounded-xl p-4" style={{ background: "var(--surface-2)", border: "1px solid var(--line)" }} data-testid="closing-preview">
                  <div className="mb-1 text-xs font-bold" style={{ color: "var(--text-3)" }}>
                    پایانِ هر پیام این‌طور می‌شود
                  </div>
                  <pre className="whitespace-pre-wrap text-sm leading-7" dir="auto" style={{ color: "var(--text)", fontFamily: "inherit", margin: 0 }}>
                    {closingBlock(form) || "—"}
                  </pre>
                </div>
              </Card>

              <Card>
                <SectionTitle>سقف و فاصلهٔ ارسال</SectionTitle>
                <p className="mb-4 text-sm leading-7" style={{ color: "var(--text-3)" }}>
                  سقفِ روزانه برای همهٔ کمپین‌ها با هم است. فاصله بینِ دو ارسال را سیستم هر بار تصادفی بین این دو عدد می‌گذارد، فقط برای اینکه پیام‌ها پشتِ‌سرهم نروند. ارسال از یک آی‌پیِ سرور است و ارسالِ زیاد ممکن است آن را در فهرستِ اسپم بیندازد؛ سقف را کم نگه دارید.
                </p>
                <div className="grid gap-4 sm:grid-cols-3">
                  <Field label="سقفِ ارسال در روز">
                    <Input type="number" min={1} max={500} inputMode="numeric" value={form.daily_cap} onChange={set("daily_cap")} data-testid="daily-cap" />
                    <ErrorText>{errors.daily_cap}</ErrorText>
                  </Field>
                  <Field label="کمترین فاصله (ثانیه)">
                    <Input type="number" min={10} max={3600} inputMode="numeric" value={form.spacing_min_seconds} onChange={set("spacing_min_seconds")} />
                    <ErrorText>{errors.spacing_min_seconds}</ErrorText>
                  </Field>
                  <Field label="بیشترین فاصله (ثانیه)">
                    <Input type="number" min={10} max={3600} inputMode="numeric" value={form.spacing_max_seconds} onChange={set("spacing_max_seconds")} />
                    <ErrorText>{errors.spacing_max_seconds}</ErrorText>
                  </Field>
                </div>
              </Card>

              {save.error && <Flash tone="bad">{save.error.message}</Flash>}
              {saved && !dirty && <Flash tone="ok" onClose={() => setSaved(false)}>تنظیمات ذخیره شد.</Flash>}
              <div className="flex flex-wrap items-center gap-3">
                <Button type="submit" disabled={save.busy || !dirty} data-testid="settings-save">
                  <Icon name="check" size={16} />
                  {save.busy ? "در حال ذخیره…" : "ذخیرهٔ تنظیمات"}
                </Button>
                {dirty && (
                  <Button type="button" variant="ghost" onClick={() => setForm(toForm(current))}>
                    بازگرداندن
                  </Button>
                )}
                {dirty && <span className="text-xs" style={{ color: "var(--warn)" }}>تغییرها هنوز ذخیره نشده‌اند.</span>}
              </div>
            </form>

            {/* ------------------------------------------------------------ switch, cap meter, emergency */}
            <div className="space-y-5">
              <Card>
                <SectionTitle>ارسالِ خودکار</SectionTitle>
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <div className="text-sm font-bold" style={{ color: "var(--text)" }}>
                      {current.sending_enabled ? "روشن است" : "خاموش است"}
                    </div>
                    <Badge tone={current.sending_enabled ? "ok" : "neutral"}>{current.sending_enabled ? "فعال" : "غیرفعال"}</Badge>
                  </div>
                  <Button
                    type="button"
                    variant={current.sending_enabled ? "secondary" : "primary"}
                    disabled={toggle.busy || (!current.sending_enabled && dirty)}
                    onClick={onToggle}
                    data-testid="sending-toggle"
                  >
                    {current.sending_enabled ? "خاموش کن" : "روشن کن"}
                  </Button>
                </div>
                <p className="mt-3 text-sm leading-7" style={{ color: "var(--text-3)" }}>
                  روشن کردن یعنی سیستم می‌تواند فرم‌های تماسِ تأییدشده را خودش پُر و ارسال کند؛ فقط موردهایی که شما تأیید کرده‌اید و فقط در حدِ سقفِ روزانه.
                </p>
                {!current.sending_enabled && dirty && (
                  <p className="mt-2 text-xs" style={{ color: "var(--warn)" }}>
                    اول تغییرهای فرم را ذخیره کنید، بعد روشن کنید.
                  </p>
                )}
                {toggle.error && (
                  <div className="mt-3">
                    <Flash tone="bad">{toggle.error.message}</Flash>
                  </div>
                )}
                {!current.ready.ok && (
                  <div className="mt-3" data-testid="readiness-problems">
                    <Alert tone="warn" title="برای روشن شدن این‌ها کم است">
                      <ul className="list-disc ps-5">
                        {current.ready.problems.map((p) => (
                          <li key={p}>{p}</li>
                        ))}
                      </ul>
                    </Alert>
                  </div>
                )}
              </Card>

              <Card>
                <SectionTitle>مصرفِ امروز</SectionTitle>
                <CapMeter sent={current.sent_today} cap={current.daily_cap} />
                <p className="mt-2 text-xs" style={{ color: "var(--text-3)" }}>
                  {fa(current.cap_remaining)} ارسالِ دیگر تا سقفِ امروز مانده است.
                </p>
              </Card>

              <Card>
                <SectionTitle>توقفِ اضطراری</SectionTitle>
                <p className="mb-3 text-sm leading-7" style={{ color: "var(--text-3)" }}>
                  اگر چیزی اشتباه پیش رفت، این دکمه فوراً همهٔ ارسال‌ها را می‌ایستاند.
                </p>
                <EmergencyStopButton stopped={current.emergency_stop} onChanged={reloadAll} />
              </Card>
            </div>
          </div>

          {/* ------------------------------------------------------------ audit */}
          <Card padded={false}>
            <div className="flex items-center justify-between gap-3 px-5 pt-4">
              <SectionTitle>گزارشِ تغییرها و ارسال‌ها</SectionTitle>
              <Button variant="ghost" size="sm" onClick={audit.reload} aria-label="تازه‌سازی">
                <Icon name="refresh" size={14} />
              </Button>
            </div>
            <div className="max-h-96 overflow-y-auto px-5 pb-4" data-testid="audit-list">
              <LoadState loading={audit.loading && !audit.data} error={audit.error} onRetry={audit.reload}>
                {asList(audit.data).length === 0 ? (
                  <p className="py-6 text-center text-sm" style={{ color: "var(--text-3)" }}>
                    هنوز چیزی ثبت نشده است.
                  </p>
                ) : (
                  <ul className="divide-y" style={{ borderColor: "var(--line)" }}>
                    {asList(audit.data).map((entry) => (
                      <li key={entry.id} className="flex flex-wrap items-baseline gap-x-3 gap-y-1 py-2 text-sm" style={{ borderColor: "var(--line)" }}>
                        <span className="u-num w-36 shrink-0 text-xs" style={{ color: "var(--text-3)" }}>
                          {faDateTime(entry.created_at)}
                        </span>
                        <Badge>{entry.kind_label || AUDIT_KIND[entry.kind] || entry.kind}</Badge>
                        <span className="min-w-0 flex-1" style={{ color: "var(--text-2)" }}>
                          {entry.summary}
                        </span>
                        {entry.actor_name && (
                          <span className="text-xs" style={{ color: "var(--text-3)" }}>
                            {entry.actor_name}
                          </span>
                        )}
                      </li>
                    ))}
                  </ul>
                )}
              </LoadState>
            </div>
          </Card>

          <ConfirmDialog
            open={askEnable}
            title="ارسالِ خودکار روشن شود؟"
            confirmLabel="بله، روشن شود"
            busy={toggle.busy}
            onConfirm={() => setSending(true)}
            onClose={() => setAskEnable(false)}
            message={
              <div className="space-y-2">
                <p>از این لحظه سیستم می‌تواند فرم‌های تماسِ تأییدشده را خودش پُر و ارسال کند.</p>
                <p>هیچ موردی بدونِ تأییدِ شما نمی‌رود و از سقفِ روزانه ({fa(current.daily_cap)} پیام) بیشتر ارسال نمی‌شود.</p>
                {toggle.error && <p style={{ color: "var(--bad)" }}>{toggle.error.message}</p>}
              </div>
            }
          />
        </div>
      )}
    </LoadState>
  );
}
