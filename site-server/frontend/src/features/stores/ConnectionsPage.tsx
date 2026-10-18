import { useCallback, useEffect, useState } from "react";

import { api, errorMessage } from "../../api/client";
import Icon from "../../components/Icon";
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
  Spinner,
} from "../../components/ui";
import { useStore } from "./StoreLayout";

/**
 * صفحه ۳، بند ۱ — اتصال سوشال مدیاها.
 *
 * بک‌اندش از اول بود: `novinhub_token`، `novinhub_account_ids`،
 * `social_links`، و `services/publishing/channels.py` که می‌داند هر کانال
 * چه چیزی کم دارد. **ولی هیچ صفحه‌ای هیچ‌وقت آن‌ها را نپرسید.** یعنی هر
 * فروشگاهی یا از توکن مشترک ما منتشر می‌کرد یا اصلاً نمی‌کرد، و صندوق پیام
 * کنار کانال‌ها می‌نوشت «تنظیم نشده» بدون اینکه راهی برای تنظیم کردنشان
 * وجود داشته باشد.
 *
 * توکن هیچ‌وقت برنمی‌گردد — فقط اینکه *هست یا نه*. برای یک صفحه‌ی تنظیمات
 * همین کافی است، و اعتبارنامه‌ای که هر بار در پاسخ می‌آید، اعتبارنامه‌ای است
 * که روزی در لاگ می‌نشیند.
 */

type Channel = {
  key: string;
  title: string;
  can_receive: boolean;
  can_send: boolean;
  configured: boolean;
  requires: string[];
  note: string;
  reason: string;
};

type Payload = {
  has_token: boolean;
  has_telegram_token: boolean;
  /** true یعنی این فروشگاه دارد با ربات مشترک سرویس جواب می‌دهد. */
  telegram_shared: boolean;
  novinhub_account_ids: string[];
  social_links: Record<string, string>;
  social_keys: { key: string; label: string }[];
  channels: Channel[];
  webhooks: Record<string, string>;
  webhook_note: string;
  shared_token_note: string;
};

const WEBHOOK_LABEL: Record<string, string> = {
  telegram: "تلگرام — در @BotFather دستور setWebhook",
  instagram: "اینستاگرام — در تنظیمات اپ Meta",
  whatsapp: "واتس‌اپ — در تنظیمات اپ Meta",
};

export default function ConnectionsPage() {
  const { storeId } = useStore();
  const [data, setData] = useState<Payload | null>(null);
  const [token, setToken] = useState("");
  const [telegramToken, setTelegramToken] = useState("");
  const [accounts, setAccounts] = useState("");
  const [links, setLinks] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [copied, setCopied] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const { data: body } = await api.get<Payload>(`/stores/${storeId}/connections/`);
      setData(body);
      setAccounts(body.novinhub_account_ids.join("، "));
      setLinks(body.social_links);
      setError(null);
    } catch (err) {
      setError(errorMessage(err));
    }
  }, [storeId]);

  useEffect(() => {
    void load();
  }, [load]);

  if (!data) return error ? <ErrorBox message={error} /> : <Spinner />;

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      const body: Record<string, unknown> = {
        novinhub_account_ids: accounts
          .replace(/،/g, ",")
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean),
        social_links: links,
      };
      // Only sent when typed. An empty box means "leave it alone", not
      // "delete the token" — deleting needs the button below, which says so.
      if (token.trim()) body.novinhub_token = token.trim();
      if (telegramToken.trim()) body.telegram_bot_token = telegramToken.trim();
      const { data: fresh } = await api.patch<Payload>(
        `/stores/${storeId}/connections/`,
        body,
      );
      setData(fresh);
      setToken("");
      setTelegramToken("");
      setSaved(true);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  };

  const clearTelegramToken = async () => {
    if (
      !window.confirm(
        "توکن ربات اختصاصی پاک شود؟ بعد از آن پیام‌ها دوباره از ربات مشترک سرویس می‌رود.",
      )
    ) {
      return;
    }
    setSaving(true);
    try {
      const { data: fresh } = await api.patch<Payload>(
        `/stores/${storeId}/connections/`,
        { telegram_bot_token: "" },
      );
      setData(fresh);
      setSaved(true);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  };

  const clearToken = async () => {
    if (!window.confirm("توکن اختصاصی پاک شود؟ بعد از آن انتشار از حساب مشترک آپ‌مارکت انجام می‌شود.")) {
      return;
    }
    setSaving(true);
    try {
      const { data: fresh } = await api.patch<Payload>(
        `/stores/${storeId}/connections/`,
        { novinhub_token: "" },
      );
      setData(fresh);
      setSaved(true);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div>
      <PageHeader
        title="اتصال شبکه‌های اجتماعی"
        subtitle="کجا منتشر شود و از کجا پیام بگیریم."
      />

      <ErrorBox message={error} />

      {/* -------------------------------------------------- وضعیت کانال‌ها */}
      <Card className="mb-4">
        <SectionTitle>الان چه چیزی کار می‌کند</SectionTitle>
        <div className="grid gap-2">
          {data.channels.map((c) => (
            <div
              key={c.key}
              className="flex flex-wrap items-center justify-between gap-2 rounded-xl px-3 py-2"
              style={{ background: "var(--surface-2)" }}
            >
              <span className="font-medium">{c.title}</span>
              <span className="flex flex-wrap items-center gap-2">
                {c.can_receive && <Badge tone="ok">پیام می‌گیرد</Badge>}
                {c.can_send && <Badge tone="brand">پیام می‌فرستد</Badge>}
                {!c.configured && <Badge tone="warn">تنظیم نشده</Badge>}
                {c.reason && (
                  <span className="text-xs" style={{ color: "var(--text-3)" }}>
                    {c.reason}
                  </span>
                )}
              </span>
            </div>
          ))}
        </div>
      </Card>

      {/* ---------------------------------------------------- اینستاگرام */}
      <Card className="mb-4">
        <SectionTitle
          action={
            data.has_token ? (
              <Badge tone="ok">توکن اختصاصی ثبت شده</Badge>
            ) : (
              <Badge tone="neutral">توکن مشترک</Badge>
            )
          }
        >
          انتشار در اینستاگرام
        </SectionTitle>

        <Alert tone="info">{data.shared_token_note}</Alert>

        <div className="mt-4 grid gap-4">
          <Field
            label="توکن نوین‌هاب این فروشگاه"
            hint={
              data.has_token
                ? "توکنی ثبت شده است. برای عوض کردنش توکن تازه را بنویسید؛ خالی گذاشتن چیزی را پاک نمی‌کند."
                : "اختیاری. خالی بماند، از حساب مشترک آپ‌مارکت استفاده می‌شود."
            }
          >
            <Input
              type="password"
              value={token}
              onChange={(e) => {
                setToken(e.target.value);
                setSaved(false);
              }}
              placeholder={data.has_token ? "••••••••" : "توکن را اینجا بچسبانید"}
              autoComplete="off"
            />
          </Field>

          <Field
            label="شناسه‌ی اکانت‌ها"
            hint="با ویرگول جدا کنید. پست روی همین اکانت‌ها منتشر می‌شود."
          >
            <Input
              value={accounts}
              onChange={(e) => {
                setAccounts(e.target.value);
                setSaved(false);
              }}
              placeholder="مثلاً ۱۲۳۴۵، ۶۷۸۹۰"
            />
          </Field>

          {data.has_token && (
            <div>
              <Button variant="ghost" onClick={clearToken} disabled={saving}>
                <Icon name="trash" /> پاک کردن توکن اختصاصی
              </Button>
            </div>
          )}
        </div>
      </Card>

      {/* ------------------------------------------------------- تلگرام */}
      <Card className="mb-4">
        <SectionTitle
          action={
            data.has_telegram_token ? (
              <Badge tone="ok">ربات اختصاصی</Badge>
            ) : (
              <Badge tone="neutral">ربات مشترک</Badge>
            )
          }
        >
          ربات تلگرام
        </SectionTitle>

        {data.telegram_shared && (
          <Alert tone="warn">
            الان از ربات مشترک سرویس استفاده می‌کنید؛ یعنی پیام‌ها با نام همان ربات
            به مشتری می‌رسد. برای اینکه مشتری‌ها با ربات خودِ فروشگاه شما حرف بزنند،
            در @BotFather یک ربات بسازید و توکنش را اینجا بگذارید.
          </Alert>
        )}

        <div className="mt-4 grid gap-4">
          <Field
            label="توکن ربات تلگرام این فروشگاه"
            hint={
              data.has_telegram_token
                ? "توکنی ثبت شده است. برای عوض کردنش توکن تازه را بنویسید؛ خالی گذاشتن چیزی را پاک نمی‌کند."
                : "اختیاری. خالی بماند، از ربات مشترک استفاده می‌شود."
            }
          >
            <Input
              type="password"
              value={telegramToken}
              onChange={(e) => {
                setTelegramToken(e.target.value);
                setSaved(false);
              }}
              placeholder={data.has_telegram_token ? "••••••••" : "123456:ABC-DEF…"}
              autoComplete="off"
            />
          </Field>

          {data.has_telegram_token && (
            <div>
              <Button variant="ghost" onClick={clearTelegramToken} disabled={saving}>
                <Icon name="trash" /> پاک کردن و برگشت به ربات مشترک
              </Button>
            </div>
          )}
        </div>
      </Card>

      {/* ------------------------------------------------ دریافت پیام */}
      <Card className="mb-4">
        <SectionTitle>دریافت پیام</SectionTitle>
        <p className="mb-3 text-xs" style={{ color: "var(--text-3)" }}>
          تا این آدرس را در تنظیمات پلتفرم نگذارید، پیام‌ها به صندوق نمی‌آیند و
          ایجنت فروش چیزی برای جواب دادن ندارد.
        </p>
        <Alert tone="warn">{data.webhook_note}</Alert>
        <div className="mt-4 grid gap-4">
          {Object.entries(data.webhooks).map(([channel, url]) => (
            <Field key={channel} label={WEBHOOK_LABEL[channel] ?? channel}>
              <div className="flex gap-2">
                <Input dir="ltr" value={url} readOnly onFocus={(e) => e.target.select()} />
                <Button
                  variant="ghost"
                  onClick={() => {
                    void navigator.clipboard?.writeText(url);
                    setCopied(channel);
                  }}
                >
                  <Icon name={copied === channel ? "check" : "copy"} />
                </Button>
              </div>
            </Field>
          ))}
        </div>
      </Card>

      {/* ----------------------------------------------------- لینک‌ها */}
      <Card className="mb-4">
        <SectionTitle>نشانی صفحه‌های شما</SectionTitle>
        <p className="mb-3 text-xs" style={{ color: "var(--text-3)" }}>
          ایجنت فروش وقتی مشتری می‌پرسد «صفحه‌تان کجاست» همین‌ها را می‌دهد، و در
          کپشن‌ها هم استفاده می‌شوند.
        </p>
        <div className="grid gap-4 md:grid-cols-2">
          {data.social_keys.map((s) => (
            <Field key={s.key} label={s.label}>
              <Input
                dir="ltr"
                value={links[s.key] ?? ""}
                onChange={(e) => {
                  setLinks({ ...links, [s.key]: e.target.value });
                  setSaved(false);
                }}
                placeholder="https://…"
              />
            </Field>
          ))}
        </div>
      </Card>

      <div className="flex items-center gap-3">
        <Button onClick={save} disabled={saving}>
          <Icon name="check" /> {saving ? "ذخیره…" : "ذخیره"}
        </Button>
        {saved && <Badge tone="ok">ذخیره شد</Badge>}
      </div>
    </div>
  );
}
