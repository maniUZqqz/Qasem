import { useCallback, useEffect, useState } from "react";

import { api, errorMessage } from "../../api/client";
import { StatRow, StatTile } from "../../components/charts";
import {
  Alert,
  Card,
  EmptyState,
  ErrorBox,
  SectionTitle,
  Spinner,
  Table,
  fa,
  toman,
} from "../../components/ui";

/**
 * مشتری‌ها از کجا می‌آیند.
 *
 * `caveat` از سرور می‌آید و **همیشه نمایش داده می‌شود**: هزینه‌ی تبلیغات
 * هیچ‌جای این سیستم ثبت نمی‌شود، پس هیچ عددی اینجا ROI نیست. یک شکافِ
 * گفته‌شده بهتر از عددی است که کسی در جلسه به آن استناد کند.
 */

type Channel = {
  channel: string;
  title: string;
  signups: number;
  paying: number;
  conversion: number;
  revenue_toman: number;
  per_customer: number | null;
};

type Report = {
  acquisition: { days: number; channels: Channel[] };
  campaigns: { name: string; signups: number; paying: number; revenue_toman: number }[];
  landing_pages: { path: string; views: number; signups: number; conversion: number }[];
  plans: {
    plan: string;
    price_toman: number;
    started: number;
    active: number;
    cancelled: number;
    churn: number;
  }[];
  referrals: {
    referrers: { name: string; signups: number; paying: number }[];
    affiliates: { name: string; signups: number; paying: number }[];
    owed_toman: number;
    unpaid_count: number;
  };
  discounts: { code: string; kind: string; used: number; revenue_toman?: number }[];
  caveat: string;
};

const RANGES = [30, 90, 365];

export default function MarketingReportPage() {
  const [days, setDays] = useState(90);
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const { data } = await api.get<Report>(`/marketing/report/?days=${days}`);
      setReport(data);
      setError(null);
    } catch (err) {
      setError(errorMessage(err));
    }
  }, [days]);

  useEffect(() => {
    void load();
  }, [load]);

  if (!report) {
    return (
      <div className="py-10 text-center">
        {error ? <ErrorBox message={error} /> : <Spinner />}
      </div>
    );
  }

  const ch = report.acquisition.channels;
  const totalSignups = ch.reduce((n, c) => n + c.signups, 0);
  const totalPaying = ch.reduce((n, c) => n + c.paying, 0);
  const totalRevenue = ch.reduce((n, c) => n + c.revenue_toman, 0);
  /** A fraction (0–1) computed here in the page. */
  const pct = (v: number) => `٪${fa(Math.round(v * 100))}`;
  /** A value the backend already expressed as a percentage
   *  (marketing/intelligence.py `_rate`). It must NOT be multiplied again:
   *  that turned 3.4 % into ٪۳۴۰ everywhere on this page. */
  const percent = (v: number | null) => (v == null ? "—" : `٪${fa(Number(v).toFixed(1))}`);
  /** Churn is a percentage too, so the "too high" line sits at 20, not 0.2. */
  const CHURN_ALERT = 20;

  return (
    <div className="space-y-5">
      <ErrorBox message={error} />

      {/* فیلتر بازه در یک ردیف بالای همه — نه داخل هر کارت */}
      <div className="flex flex-wrap items-center gap-1.5">
        {RANGES.map((d) => (
          <button
            key={d}
            onClick={() => setDays(d)}
            className={`u-btn u-btn-sm ${days === d ? "u-btn-secondary" : "u-btn-ghost"}`}
            aria-pressed={days === d}
          >
            {fa(d)} روز
          </button>
        ))}
      </div>

      <StatRow>
        <StatTile series="people" label="ثبت‌نام" value={fa(totalSignups)} />
        <StatTile series="revenue" label="پرداخت‌کننده" value={fa(totalPaying)} />
        <StatTile
          label="نرخ تبدیل"
          value={pct(totalSignups ? totalPaying / totalSignups : 0)}
        />
        <StatTile label="درآمد" value={`${toman(totalRevenue)} ت`} />
      </StatRow>

      <Card>
        <SectionTitle>کانال‌های جذب</SectionTitle>
        {ch.length === 0 ? (
          <EmptyState icon="trending" title="هنوز ثبت‌نامی در این بازه نیست" />
        ) : (
          <Table>
            <thead>
              <tr>
                <th>کانال</th>
                <th>ثبت‌نام</th>
                <th>پرداخت‌کننده</th>
                <th>تبدیل</th>
                <th>درآمد</th>
                <th>به‌ازای هر مشتری</th>
              </tr>
            </thead>
            <tbody>
              {ch.map((c) => (
                <tr key={c.channel}>
                  <td style={{ color: "var(--text)", fontWeight: 500 }}>{c.title}</td>
                  <td className="u-num">{fa(c.signups)}</td>
                  <td className="u-num">{fa(c.paying)}</td>
                  <td className="u-num">{percent(c.conversion)}</td>
                  <td className="u-num">{toman(c.revenue_toman)}</td>
                  <td className="u-num">
                    {c.per_customer == null ? "—" : toman(Math.round(c.per_customer))}
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <SectionTitle>پلن‌ها و ریزش</SectionTitle>
          {report.plans.length === 0 ? (
            <EmptyState icon="wallet" title="هنوز اشتراکی شروع نشده" />
          ) : (
            <Table>
              <thead>
                <tr>
                  <th>پلن</th>
                  <th>شروع</th>
                  <th>فعال</th>
                  <th>لغو</th>
                  <th>ریزش</th>
                </tr>
              </thead>
              <tbody>
                {report.plans.map((p) => (
                  <tr key={p.plan}>
                    <td style={{ color: "var(--text)" }}>{p.plan}</td>
                    <td className="u-num">{fa(p.started)}</td>
                    <td className="u-num">{fa(p.active)}</td>
                    <td className="u-num">{fa(p.cancelled)}</td>
                    <td
                      className="u-num"
                      style={{ color: p.churn > CHURN_ALERT ? "var(--bad)" : undefined }}
                    >
                      {percent(p.churn)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
        </Card>

        <Card>
          <SectionTitle>معرفی و همکار فروش</SectionTitle>
          <div className="mb-3 flex flex-wrap gap-4 text-sm">
            <span style={{ color: "var(--text-2)" }}>
              بدهی پرداخت‌نشده:{" "}
              <strong className="u-num" style={{ color: "var(--text)" }}>
                {toman(report.referrals.owed_toman)} تومان
              </strong>
            </span>
            <span style={{ color: "var(--text-3)" }}>
              {fa(report.referrals.unpaid_count)} مورد
            </span>
          </div>
          {report.referrals.referrers.length === 0 &&
          report.referrals.affiliates.length === 0 ? (
            <EmptyState icon="users" title="هنوز کسی از راه معرفی نیامده" />
          ) : (
            <Table>
              <thead>
                <tr>
                  <th>معرف</th>
                  <th>نوع</th>
                  <th>ثبت‌نام</th>
                  <th>پرداخت‌کننده</th>
                </tr>
              </thead>
              <tbody>
                {report.referrals.referrers.map((r) => (
                  <tr key={`r-${r.name}`}>
                    <td style={{ color: "var(--text)" }}>{r.name}</td>
                    <td>مشتری</td>
                    <td className="u-num">{fa(r.signups)}</td>
                    <td className="u-num">{fa(r.paying)}</td>
                  </tr>
                ))}
                {report.referrals.affiliates.map((r) => (
                  <tr key={`a-${r.name}`}>
                    <td style={{ color: "var(--text)" }}>{r.name}</td>
                    <td>همکار فروش</td>
                    <td className="u-num">{fa(r.signups)}</td>
                    <td className="u-num">{fa(r.paying)}</td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
        </Card>
      </div>

      {report.discounts.length > 0 && (
        <Card>
          <SectionTitle>کدهای تخفیف</SectionTitle>
          <Table>
            <thead>
              <tr>
                <th>کد</th>
                <th>نوع</th>
                <th>استفاده</th>
                <th>درآمد</th>
              </tr>
            </thead>
            <tbody>
              {report.discounts.map((d) => (
                <tr key={d.code}>
                  <td dir="ltr" style={{ color: "var(--text)", fontWeight: 600 }}>
                    {d.code}
                  </td>
                  <td>{d.kind}</td>
                  <td className="u-num">{fa(d.used)}</td>
                  <td className="u-num">{d.revenue_toman ? toman(d.revenue_toman) : "—"}</td>
                </tr>
              ))}
            </tbody>
          </Table>
        </Card>
      )}

      {report.landing_pages.length > 0 && (
        <Card>
          <SectionTitle>صفحات فرود</SectionTitle>
          <Table>
            <thead>
              <tr>
                <th>مسیر</th>
                <th>بازدید</th>
                <th>ثبت‌نام</th>
                <th>تبدیل</th>
              </tr>
            </thead>
            <tbody>
              {report.landing_pages.map((p) => (
                <tr key={p.path}>
                  <td dir="ltr" style={{ color: "var(--text)" }}>
                    {p.path}
                  </td>
                  <td className="u-num">{fa(p.views)}</td>
                  <td className="u-num">{fa(p.signups)}</td>
                  <td className="u-num">{percent(p.conversion)}</td>
                </tr>
              ))}
            </tbody>
          </Table>
        </Card>
      )}

      {/* هشدار سرور، همیشه و پایین‌تر از اعداد — نه یک بار و فراموش‌شده */}
      <Alert tone="warn" title="این گزارش ROI نیست">
        {report.caveat}
      </Alert>
    </div>
  );
}
