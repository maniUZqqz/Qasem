import { useCallback, useEffect, useState } from "react";

import { api, errorMessage } from "../../api/client";
import Icon from "../../components/Icon";
import { StatRow, StatTile } from "../../components/charts";
import {
  Alert,
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorBox,
  SectionTitle,
  Spinner,
  Table,
  fa,
} from "../../components/ui";
import { useCampaigns } from "./CampaignsLayout";

/**
 * چه چیزی واقعاً جواب داد. فاز ۲۵ / بند ۱۸
 *
 * این اندپوینت ساخته و تست شده بود و هیچ صفحه‌ای نداشت — یعنی «یاد
 * گرفتن از نتیجه» که سند یکی از ستون‌های محصول می‌نامدش، از پنل دیده
 * نمی‌شد.
 *
 * دو چیز که از بک‌اند می‌آید و اینجا **پنهان نمی‌شود**:
 *
 * **زیر پنج پستِ اندازه‌گیری‌شده، هیچ الگویی گفته نمی‌شود.** سرور خودش
 * `enough_data: false` برمی‌گرداند و متن دلیلش را می‌دهد. نشان دادن یک
 * «الگو» از دو پست، دنبال کردن تصادف است.
 *
 * **پستی که آمارش نیامده، حذف نمی‌شود — دلیلش نوشته می‌شود.** فهرستی
 * که فقط موفق‌ها را نشان بدهد، تصویر بهتری از واقعیت می‌سازد.
 */

type Best = {
  campaign: string;
  platform: string;
  engagement: number | null;
  views: number | null;
  rate: number | null;
  orders: number;
};

type Report = {
  enough_data: boolean;
  posts: number;
  measured: number;
  message: string;
  best?: Best[];
  patterns: { kind: string; text: string }[];
  unavailable?: { platform: string; reason: string }[];
  checked?: number;
};

export default function PerformancePage() {
  const { storeId } = useCampaigns();
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      const { data } = await api.get<Report>(`/stores/${storeId}/performance/`);
      setReport(data);
      setError(null);
    } catch (err) {
      setError(errorMessage(err));
    }
  }, [storeId]);

  useEffect(() => {
    void load();
  }, [load]);

  const refresh = async () => {
    setRefreshing(true);
    setError(null);
    try {
      const { data } = await api.post<Report>(`/stores/${storeId}/performance/`);
      setReport(data);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setRefreshing(false);
    }
  };

  if (!report) {
    return (
      <div className="py-10 text-center">
        {error ? <ErrorBox message={error} /> : <Spinner />}
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <ErrorBox message={error} />

      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm" style={{ color: "var(--text-2)" }}>
          آمار هر ساعت خودش به‌روز می‌شود؛ این دکمه همین حالا می‌پرسد.
        </p>
        <Button variant="secondary" onClick={refresh} disabled={refreshing}>
          <Icon name="refresh" size={15} />
          {refreshing ? "در حال دریافت…" : "به‌روزرسانی حالا"}
        </Button>
      </div>

      {report.checked !== undefined && (
        <Alert tone="info">
          آمار {fa(report.checked)} پست تازه دریافت شد.
        </Alert>
      )}

      <StatRow>
        <StatTile label="پست منتشرشده" value={fa(report.posts)} />
        <StatTile series="content" label="با آمار" value={fa(report.measured)} />
        <StatTile
          label="بدون آمار"
          value={fa(Math.max(0, report.posts - report.measured))}
          hint={report.posts > report.measured ? "دلیلش پایین آمده" : undefined}
        />
        {/* «از پست» ادعای انتساب بود؛ کد چنین چیزی نمی‌سنجد. چیزی که واقعاً
            شمرده می‌شود سفارش‌های همان محصول در فاصله‌ی بین این پست و پست
            بعدیِ همان محصول است — هم‌زمانی، نه علت. */}
        <StatTile
          series="orders"
          label="سفارش هم‌زمان با پست"
          value={fa((report.best ?? []).reduce((n, b) => n + b.orders, 0))}
          hint="سفارش همان محصول در بازه‌ی پست — هم‌زمانی است، نه اثبات اثر پست."
        />
      </StatRow>

      {!report.enough_data ? (
        <Alert tone="warn" title="هنوز برای نتیجه‌گیری زود است">
          {report.message}
        </Alert>
      ) : (
        <>
          <Card>
            <SectionTitle>چه چیزی جواب داد</SectionTitle>
            {report.patterns.length === 0 ? (
              <EmptyState icon="bulb" title="الگوی روشنی پیدا نشد">
                پست‌ها آمار دارند ولی تفاوتشان آن‌قدر نیست که بشود گفت یکی بهتر از
                دیگری بوده.
              </EmptyState>
            ) : (
              <ul className="space-y-2">
                {report.patterns.map((p, i) => (
                  <li key={`${p.kind}-${i}`} className="flex gap-2.5 text-sm leading-7">
                    <span className="mt-1 shrink-0" style={{ color: "var(--brand-strong)" }}>
                      <Icon name="bulb" size={16} />
                    </span>
                    <span style={{ color: "var(--text-2)" }}>{p.text}</span>
                  </li>
                ))}
              </ul>
            )}
          </Card>

          {!!report.best?.length && (
            <Card padded={false}>
              <div className="px-5 pt-5">
                <SectionTitle>بهترین پست‌ها</SectionTitle>
              </div>
              <Table>
                <thead>
                  <tr>
                    <th>کمپین</th>
                    <th>پلتفرم</th>
                    <th>تعامل</th>
                    <th>بازدید</th>
                    <th>نرخ</th>
                    <th title="سفارش همان محصول در بازه‌ی این پست — هم‌زمانی، نه انتساب">
                      سفارش هم‌زمان
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {report.best.map((b, i) => (
                    <tr key={`${b.campaign}-${b.platform}-${i}`}>
                      <td style={{ color: "var(--text)", fontWeight: 500 }}>{b.campaign}</td>
                      <td>{b.platform}</td>
                      <td className="u-num">{b.engagement == null ? "—" : fa(b.engagement)}</td>
                      <td className="u-num">{b.views == null ? "—" : fa(b.views)}</td>
                      <td className="u-num">
                        {/* Already a percentage from the backend (campaigns/learning.py
                            `engagement_rate`) — multiplying here showed 3.2 % as ٪۳۲۰. */}
                        {b.rate == null ? "—" : `٪${fa(b.rate.toFixed(1))}`}
                      </td>
                      <td className="u-num">
                        {b.orders ? <Badge tone="ok">{fa(b.orders)}</Badge> : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            </Card>
          )}
        </>
      )}

      {!!report.unavailable?.length && (
        <Card>
          <SectionTitle>پست‌هایی که آمارشان نیامد</SectionTitle>
          <ul className="space-y-1.5 text-sm">
            {report.unavailable.map((u, i) => (
              <li key={`${u.platform}-${i}`} className="flex gap-2">
                <span style={{ color: "var(--text-3)" }}>{u.platform}:</span>
                <span style={{ color: "var(--text-2)" }}>{u.reason}</span>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}
