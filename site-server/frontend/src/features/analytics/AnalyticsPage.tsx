import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api, errorMessage } from "../../api/client";
import Icon from "../../components/Icon";
import { ChartTable, DailyBarChart, type Series, StatRow, StatTile } from "../../components/charts";
import { ErrorBox, Spinner, fa, toman } from "../../components/ui";

/**
 * آمار فروشگاه.
 *
 * `StatTile` و `MiniBarChart` اینجا تعریف شده بودند و نسخه‌ی دیگرشان در
 * صفحه‌ی فروش — با کامنتی که خودش می‌گفت «همان پالت آن یکی». حالا هر دو
 * از `components/charts` می‌آیند، پس یک پالت اعتبارسنجی‌شده وجود دارد نه
 * دو تا که تصادفاً شبیه‌اند.
 */

const SERIES: { key: "conversations" | "orders" | "ai_requests"; label: string; series: Series }[] =
  [
    { key: "conversations", label: "گفتگوها", series: "people" },
    { key: "orders", label: "سفارش‌ها", series: "orders" },
    { key: "ai_requests", label: "درخواست‌های AI", series: "content" },
  ];

interface Overview {
  products: { total: number; available: number };
  conversations: { total: number; by_state: Record<string, number>; messages: number };
  orders: {
    total: number;
    by_status: Record<string, number>;
    confirmed_revenue: string;
    draft_value: string;
  };
  campaigns: { total: number; by_state: Record<string, number> };
  publishing: { total: number; by_status: Record<string, number> };
  content: { generated_images: number; captions: number; videos_ready: number };
  ai: { requests: number; by_status: Record<string, number>; avg_latency_ms: number };
  jobs: { total: number; by_state: Record<string, number> };
}

interface DayPoint {
  date: string;
  conversations: number;
  orders: number;
  ai_requests: number;
}

export default function AnalyticsPage() {
  const { id: storeId } = useParams<{ id: string }>();
  const [overview, setOverview] = useState<Overview | null>(null);
  const [series, setSeries] = useState<DayPoint[]>([]);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [overviewRes, seriesRes] = await Promise.all([
        api.get<Overview>(`/stores/${storeId}/analytics/`),
        api.get<{ series: DayPoint[] }>(`/stores/${storeId}/analytics/timeseries/?days=14`),
      ]);
      setOverview(overviewRes.data);
      setSeries(seriesRes.data.series);
    } catch (err) {
      setError(errorMessage(err));
    }
  }, [storeId]);

  useEffect(() => {
    void load();
  }, [load]);

  if (!overview) {
    return (
      <div className="py-10 text-center">
        {error ? <ErrorBox message={error} /> : <Spinner />}
      </div>
    );
  }

  const aiErrors = overview.ai.requests - (overview.ai.by_status["OK"] ?? 0);

  return (
    <div className="u-rise space-y-5">
      <div>
        <Link
          to={`/stores/${storeId}`}
          className="u-back"
        >
          <Icon name="back" size={15} />
          بازگشت به فروشگاه
        </Link>
        <h1 className="mt-1 text-2xl font-extrabold" style={{ color: "var(--text)" }}>
          آمار فروشگاه
        </h1>
        <p className="text-xs" style={{ color: "var(--text-3)" }}>
          همه‌ی اعداد مستقیم از داده‌ی واقعی دیتابیس — هیچ نمونه‌ای ساخته نمی‌شود.
        </p>
      </div>

      <ErrorBox message={error} />

      <section>
        <h2 className="mb-2 text-sm font-bold" style={{ color: "var(--text-2)" }}>
          کاتالوگ و فروش
        </h2>
        <StatRow>
          <StatTile
            label="محصولات"
            value={fa(overview.products.total)}
            hint={`${fa(overview.products.available)} موجود`}
          />
          <StatTile
            series="people"
            label="گفتگوهای فروش"
            value={fa(overview.conversations.total)}
            hint={`${fa(overview.conversations.messages)} پیام`}
          />
          <StatTile
            series="orders"
            label="سفارش‌ها"
            value={fa(overview.orders.total)}
            hint={`درآمد تأییدشده ${toman(Number(overview.orders.confirmed_revenue))} تومان`}
          />
          <StatTile
            label="کمپین‌ها"
            value={fa(overview.campaigns.total)}
            hint={`${fa(overview.campaigns.by_state["PUBLISHED"] ?? 0)} منتشرشده`}
          />
        </StatRow>
      </section>

      <section>
        <h2 className="mb-2 text-sm font-bold" style={{ color: "var(--text-2)" }}>
          تولید محتوا و ماشین
        </h2>
        <StatRow>
          <StatTile label="تصاویر تولیدی" value={fa(overview.content.generated_images)} />
          <StatTile
            label="کپشن / ویدیوی آماده"
            value={`${fa(overview.content.captions)} / ${fa(overview.content.videos_ready)}`}
          />
          <StatTile
            series="content"
            label="درخواست‌های AI"
            value={fa(overview.ai.requests)}
            hint={`میانگین تأخیر ${fa(overview.ai.avg_latency_ms)}ms${
              aiErrors ? ` · ${fa(aiErrors)} خطا` : ""
            }`}
          />
          <StatTile
            label="کارها"
            value={fa(overview.jobs.total)}
            hint={`${fa(overview.jobs.by_state["COMPLETED"] ?? 0)} موفق · ${fa(
              overview.jobs.by_state["FAILED"] ?? 0,
            )} ناموفق`}
          />
        </StatRow>
      </section>

      <section>
        <h2 className="mb-2 text-sm font-bold" style={{ color: "var(--text-2)" }}>
          روند ۱۴ روز اخیر
        </h2>
        {/* سه نمودار تک‌سری کنار هم، نه یک نمودار با سه سری روی یک محور:
            گفتگو، سفارش و درخواست AI مقیاس‌های کاملاً متفاوتی دارند و
            کشیدنشان روی یک محور، دوتایشان را به خط صاف تبدیل می‌کند. */}
        <div className="grid gap-4 lg:grid-cols-3">
          {SERIES.map((s) => {
            const points = series.map((p) => ({ date: p.date, value: p[s.key] }));
            return (
              <div key={s.key} className="space-y-2">
                <DailyBarChart title={s.label} series={s.series} points={points} />
                <ChartTable points={points} label={s.label} />
              </div>
            );
          })}
        </div>
      </section>
    </div>
  );
}
