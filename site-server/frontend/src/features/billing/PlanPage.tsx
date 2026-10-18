import { useEffect, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";

import { api, errorMessage } from "../../api/client";
import ReferralCard from "../../components/ReferralCard";
import {
  Alert,
  Badge,
  Button,
  Card,
  EmptyState,
  Meter,
  PageHeader,
  SectionTitle,
  Skeleton,
  Stat,
  Table,
  fa,
  toman,
} from "../../components/ui";

type Metric = {
  metric: string;
  label: string;
  allowed: number;
  used: number;
  remaining: number;
  percent: number;
  /** Credits handed back this period because the output was not usable. */
  refunded?: number;
};

type Snapshot = {
  subscription: {
    plan: string;
    plan_slug: string;
    status: string;
    status_label: string;
    period_end: string;
    days_left: number;
    price_toman: number;
  } | null;
  metrics: Metric[];
  blocked: boolean;
  billing?: boolean;
};

type Plan = {
  slug: string;
  name: string;
  description: string;
  price_toman: number;
  video_seconds: number;
  images: number;
  captions: number;
  max_products: number;
  allows_publishing: boolean;
  allows_sales_agent: boolean;
};

type Usage = {
  id: number;
  metric: string;
  metric_label: string;
  quantity: number;
  state: string;
  external: boolean;
  detail: string;
  attempt?: number;
  quality_reason?: string;
  created_at: string;
};

const STATE_TONE: Record<string, "ok" | "warn" | "neutral" | "info"> = {
  COMMITTED: "ok",
  RESERVED: "warn",
  RELEASED: "neutral",
  REFUNDED: "info",
};

const STATE_LABEL: Record<string, string> = {
  COMMITTED: "مصرف‌شده",
  RESERVED: "رزرو‌شده",
  RELEASED: "آزاد‌شده",
  REFUNDED: "برگشت‌خورده",
};

export default function PlanPage() {
  const { id } = useParams();
  const [snap, setSnap] = useState<Snapshot | null>(null);
  const [plans, setPlans] = useState<Plan[]>([]);
  const [history, setHistory] = useState<Usage[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState("");
  const [providers, setProviders] = useState<
    { key: string; label: string; automatic: boolean }[]
  >([]);
  const [provider, setProvider] = useState<string>("");
  const [message, setMessage] = useState("");
  const [rejecting, setRejecting] = useState<number | null>(null);

  async function load() {
    const [s, p, h] = await Promise.allSettled([
      api.get(`/stores/${id}/usage/`),
      api.get("/plans/"),
      api.get(`/stores/${id}/usage/history/`),
    ]);
    if (s.status === "fulfilled") setSnap(s.value.data);
    if (p.status === "fulfilled") setPlans(p.value.data ?? []);
    if (h.status === "fulfilled") setHistory(h.value.data ?? []);
    setLoading(false);
  }

  /**
   * "This output was not usable."
   *
   * The credit goes back and the attempt counts against the quality guarantee.
   * The message says where the store now stands, because "you have one more
   * try before it is free" is the part that decides whether they try again.
   */
  async function reject(row: Usage) {
    setRejecting(row.id);
    setMessage("");
    try {
      const { data } = await api.post(`/stores/${id}/usage/${row.id}/reject/`, {
        reason: "فروشگاه‌دار خروجی را نپسندید",
      });
      const left = data?.guarantee?.attempts_left;
      setMessage(
        left === 0
          ? `${fa(row.quantity)} ${row.metric_label} برگشت خورد. تلاش بعدی روی این مورد رایگان است.`
          : `${fa(row.quantity)} ${row.metric_label} برگشت خورد.` +
            (left != null ? ` ${fa(left)} تلاش دیگر تا رایگان شدن.` : ""),
      );
      await load();
    } catch (err) {
      setMessage(errorMessage(err));
    } finally {
      setRejecting(null);
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  // The gateway sends the customer back here rather than to a dead-end page,
  // so the result has to be readable the moment they land.
  const [params, setParams] = useSearchParams();
  const payment = params.get("payment");
  const invoice = params.get("invoice");

  useEffect(() => {
    if (!payment) return;
    if (payment === "ok") {
      setMessage(
        invoice
          ? `پرداخت انجام شد. شماره فاکتور: ${invoice}`
          : "پرداخت انجام شد و اشتراک فعال است.",
      );
    } else if (payment === "failed") {
      setMessage("پرداخت تأیید نشد. اگر مبلغ کم شده، طی ۷۲ ساعت برمی‌گردد.");
    } else {
      setMessage("پرداخت ناتمام ماند. دوباره تلاش کنید.");
    }
    // Clear the flag so a refresh does not replay the banner.
    params.delete("payment");
    params.delete("invoice");
    setParams(params, { replace: true });
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [payment]);

  /** راه‌های پرداختی که همین حالا واقعاً کار می‌کنند.
   *
   *  اندپوینتش از قبل بود و صفحه هرگز نمی‌پرسید — یعنی فروشگاه‌دار همیشه
   *  به درگاه پیش‌فرض می‌رفت، حتی وقتی می‌خواست کارت‌به‌کارت کند. سند سه
   *  راه را وعده می‌دهد (زرین‌پال، واریز بانکی، درگاه آزمایشی)؛ رابط
   *  هیچ‌کدام را نمی‌داد. */
  useEffect(() => {
    api
      .get<{ default: string; providers: { key: string; label: string; automatic: boolean }[] }>(
        "/payment-providers/",
      )
      .then(({ data }) => {
        setProviders(data.providers ?? []);
        setProvider((current) => current || data.default || data.providers?.[0]?.key || "");
      })
      // یک راه پرداخت که فهرست نشد، دلیل نمی‌شود صفحه بالا نیاید: سرور
      // بدون `provider` هم پیش‌فرض خودش را برمی‌دارد.
      .catch(() => setProviders([]));
  }, []);

  async function choose(slug: string, price: number) {
    setSaving(slug);
    setMessage("");
    try {
      // A free plan needs no gateway; anything priced goes through payment.
      if (price <= 0) {
        await api.post(`/stores/${id}/subscription/`, { plan: slug });
        setMessage("پلن رایگان فعال شد.");
        await load();
        return;
      }

      const { data } = await api.post(`/stores/${id}/payments/`, {
        plan: slug,
        ...(provider ? { provider } : {}),
      });

      if (data.redirect_url) {
        // Leave the panel for the gateway. Coming back lands here again with
        // ?payment=ok|failed, which the banner reads.
        window.location.href = data.redirect_url;
        return;
      }

      // No redirect means bank transfer: show where to send the money.
      setMessage(
        [
          `فاکتور ${data.invoice_number} به مبلغ ${toman(data.amount_toman)} تومان ثبت شد.`,
          data.instructions,
          "پس از واریز، رسید را بفرستید تا تأیید شود.",
        ]
          .filter(Boolean)
          .join("\n"),
      );
      await load();
    } catch (err) {
      setMessage(errorMessage(err));
    } finally {
      setSaving("");
    }
  }

  if (loading) {
    return (
      <>
        <PageHeader title="پلن و مصرف" />
        <div className="grid gap-4 sm:grid-cols-3">
          <Skeleton className="h-28" />
          <Skeleton className="h-28" />
          <Skeleton className="h-28" />
        </div>
      </>
    );
  }

  if (snap?.billing === false) {
    return (
      <>
        <PageHeader title="پلن و مصرف" />
        <Card>
          <EmptyState
            icon="receipt"
            title="سیستم اشتراک هنوز فعال نشده"
            description="تا وقتی پلنی تعریف نشده باشد، سقفی هم اعمال نمی‌شود. مدیر سیستم می‌تواند با «seed_plans» پلن‌ها را بسازد."
          />
        </Card>
      </>
    );
  }

  const sub = snap?.subscription;
  const statusTone =
    sub?.status === "ACTIVE" ? "ok" : sub?.status === "TRIALING" ? "info" : "warn";

  return (
    <>
      <PageHeader
        title="پلن و مصرف"
        subtitle="سهمیه‌ی این دوره و تاریخچه‌ی مصرف"
        actions={sub && <Badge tone={statusTone}>{sub.status_label}</Badge>}
      />

      {message && (
        <div className="mb-5">
          <Alert tone="info">{message}</Alert>
        </div>
      )}

      {!sub ? (
        <Card>
          <EmptyState
            icon="shield"
            title="اشتراک فعالی ندارید"
            description="برای تولید محتوا یکی از پلن‌های زیر را انتخاب کنید."
          />
        </Card>
      ) : (
        <>
          {snap!.metrics.some((m) => m.percent >= 90) && (
            <div className="mb-5">
              <Alert tone="warn" title="سهمیه رو به اتمام است">
                بخشی از سهمیه‌ی این دوره تقریباً تمام شده. برای ادامه می‌توانید
                پلن را ارتقا دهید یا تا {fa(sub.days_left)} روز دیگر صبر کنید.
              </Alert>
            </div>
          )}

          <div className="mb-6 grid gap-4 sm:grid-cols-3">
            <Stat value={sub.plan} label="پلن فعلی" hint={`${toman(sub.price_toman)} تومان در ماه`} />
            <Stat value={fa(sub.days_left)} label="روز تا پایان دوره" tone="info" />
            <Stat
              value={fa(snap!.metrics.reduce((n, m) => n + m.remaining, 0))}
              label="مجموع سهمیه‌ی باقی‌مانده"
              tone="ok"
            />
          </div>

          <SectionTitle>مصرف این دوره</SectionTitle>
          <div className="mb-8 grid gap-4 sm:grid-cols-3">
            {snap!.metrics.map((m) => (
              <Card key={m.metric}>
                <div className="mb-2 flex items-baseline justify-between">
                  <span className="text-sm font-semibold" style={{ color: "var(--text)" }}>
                    {m.label}
                  </span>
                  <span className="u-num text-sm" style={{ color: "var(--text-3)" }}>
                    {fa(m.used)} از {fa(m.allowed)}
                  </span>
                </div>
                <Meter used={m.used} total={m.allowed} />
                <div className="mt-2 text-xs" style={{ color: "var(--text-3)" }}>
                  {fa(m.remaining)} باقی‌مانده
                  {/* Shown rather than left implicit: a store that got credits
                      back should see that, not quietly notice its allowance
                      lasting longer than expected. */}
                  {m.refunded ? ` · ${fa(m.refunded)} برگشت‌خورده` : ""}
                </div>
              </Card>
            ))}
          </div>
        </>
      )}

      <SectionTitle>پلن‌ها</SectionTitle>

      {/* راه پرداخت، *بالای* دکمه‌ها: بعد از فشردن «انتخاب»، مقصد بعدی
          یا درگاه است یا شماره‌ی کارت — و آن لحظه، جای پرسیدن نیست.
          وقتی فقط یک راه هست، انتخابی در کار نیست و چیزی نشان داده
          نمی‌شود. */}
      {providers.length > 1 && (
        <fieldset className="mb-4 flex flex-wrap items-center gap-2">
          <legend className="mb-1.5 text-sm" style={{ color: "var(--text-2)" }}>
            پرداخت با
          </legend>
          {providers.map((p) => (
            <label
              key={p.key}
              className="flex cursor-pointer items-center gap-1.5 rounded-xl px-3 py-2 text-sm"
              style={{
                background: provider === p.key ? "var(--brand-soft)" : "var(--surface-2)",
                border: `1px solid ${
                  provider === p.key ? "var(--brand)" : "var(--line)"
                }`,
                color: "var(--text)",
              }}
            >
              <input
                type="radio"
                name="payment-provider"
                checked={provider === p.key}
                onChange={() => setProvider(p.key)}
              />
              {p.label}
              {!p.automatic && (
                <span className="text-xs" style={{ color: "var(--text-3)" }}>
                  (دستی — رسید لازم دارد)
                </span>
              )}
            </label>
          ))}
        </fieldset>
      )}
      <div className="mb-8 grid gap-4 md:grid-cols-3">
        {plans.map((plan) => {
          const current = sub?.plan_slug === plan.slug;
          return (
            <Card
              key={plan.slug}
              className={current ? "ring-2" : ""}
              // ring colour has to come from the token, not a Tailwind palette
              // entry, so it follows the theme
            >
              <div className="flex items-center justify-between">
                <h3 className="text-base font-bold" style={{ color: "var(--text)" }}>
                  {plan.name}
                </h3>
                {current && <Badge tone="brand">پلن فعلی</Badge>}
              </div>

              <div className="u-num mt-3 text-2xl font-extrabold" style={{ color: "var(--text)" }}>
                {toman(plan.price_toman)}
                <span className="mr-1 text-sm font-normal" style={{ color: "var(--text-3)" }}>
                  تومان / ماه
                </span>
              </div>

              <ul className="mt-4 flex flex-col gap-2 text-sm" style={{ color: "var(--text-2)" }}>
                <li>✓ {fa(plan.video_seconds)} ثانیه ویدیو</li>
                <li>✓ {fa(plan.images)} تصویر</li>
                <li>✓ {fa(plan.captions)} کپشن</li>
                <li>
                  ✓ {plan.max_products === 0 ? "محصول نامحدود" : `تا ${fa(plan.max_products)} محصول`}
                </li>
                {plan.allows_publishing && <li>✓ انتشار خودکار</li>}
                {plan.allows_sales_agent && <li>✓ پشتیبان فروش</li>}
              </ul>

              <Button
                variant={current ? "secondary" : "primary"}
                disabled={current || saving === plan.slug}
                onClick={() => choose(plan.slug, plan.price_toman)}
                className="mt-4 w-full"
              >
                {current
                  ? "پلن فعلی شما"
                  : saving === plan.slug
                    ? "…"
                    : plan.price_toman > 0
                      ? "پرداخت و فعال‌سازی"
                      : "انتخاب این پلن"}
              </Button>
            </Card>
          );
        })}
      </div>

      <SectionTitle>تاریخچه‌ی مصرف</SectionTitle>
      <Card padded={false}>
        {history.length === 0 ? (
          <EmptyState icon="chart" title="هنوز مصرفی ثبت نشده" />
        ) : (
          <Table>
            <thead>
              <tr>
                <th>تاریخ</th>
                <th>نوع</th>
                <th>مقدار</th>
                <th>وضعیت</th>
                <th>اجرا روی</th>
                <th>توضیح</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {history.map((row) => (
                <tr key={row.id}>
                  <td className="u-num">
                    {new Date(row.created_at).toLocaleDateString("fa-IR")}
                  </td>
                  <td>{row.metric_label}</td>
                  <td className="u-num">{fa(row.quantity)}</td>
                  <td>
                    <Badge tone={STATE_TONE[row.state] ?? "neutral"}>
                      {STATE_LABEL[row.state] ?? row.state}
                    </Badge>
                  </td>
                  <td>{row.external ? "☁️ سرویس بیرونی" : "🖥️ سرور ما"}</td>
                  <td style={{ color: "var(--text-3)" }}>
                    {row.quality_reason || row.detail || "—"}
                  </td>
                  <td>
                    {/* Only a committed row can be rejected: a reservation was
                        never charged, and a refunded one already came back. */}
                    {row.state === "COMMITTED" ? (
                      <Button
                        variant="ghost"
                        onClick={() => void reject(row)}
                        disabled={rejecting === row.id}
                      >
                        {rejecting === row.id ? "…" : "خروجی بد بود"}
                      </Button>
                    ) : (
                      <span style={{ color: "var(--text-3)" }}>—</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>

      {id && (
        <div className="mt-6">
          <ReferralCard storeId={id} />
        </div>
      )}
    </>
  );
}
