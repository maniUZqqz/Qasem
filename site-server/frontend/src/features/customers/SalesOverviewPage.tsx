import { ChartTable, DailyBarChart, StatRow, StatTile } from "../../components/charts";
import { Card, EmptyState, SectionTitle, Table, fa, toman } from "../../components/ui";
import { useSales } from "./SalesLayout";

/** نمای کلی فروش: پنج عدد، دو نمودار، و پرفروش‌ترین‌ها. */
export default function SalesOverviewPage() {
  const { sales } = useSales();

  const revenue = sales.series.map((p) => ({ date: p.date, value: Number(p.revenue) }));
  const orders = sales.series.map((p) => ({ date: p.date, value: p.orders }));
  /* هر عددِ این ردیف مالِ همین بازه است — قبلاً کاشی‌ها کل عمر فروشگاه را
     می‌شمردند و نمودار زیرشان یک ماه را، و هیچ‌وقت با هم نمی‌خواندند. */
  const window = `${fa(sales.days)} روز اخیر`;

  return (
    <div className="space-y-5">
      <StatRow>
        <StatTile
          series="revenue"
          label={`درآمد تأییدشده · ${window}`}
          value={toman(Number(sales.revenue.confirmed_total))}
          hint={`${fa(sales.revenue.confirmed_orders)} سفارش · میانگین ${toman(
            Number(sales.revenue.avg_order_value),
          )} · از ابتدا ${toman(Number(sales.lifetime.confirmed_total))}`}
        />
        <StatTile
          series="orders"
          label={`سفارش‌ها · ${window}`}
          value={fa(sales.orders.total)}
          hint={`تأییدشده ${fa(sales.orders.by_status["CONFIRMED"] ?? 0)} · پیش‌نویس ${fa(
            sales.orders.by_status["DRAFT"] ?? 0,
          )} · از ابتدا ${fa(sales.lifetime.orders)}`}
        />
        <StatTile
          label="در انتظار اقدام شما"
          value={fa(sales.pending.awaiting_approval)}
          hint={`${fa(sales.pending.receipts)} رسید در انتظار بررسی`}
        />
        <StatTile
          series="people"
          label={`نرخ تبدیل · ${window}`}
          value={`٪${fa(sales.conversion.rate_percent)}`}
          hint={`${fa(sales.conversion.conversations)} گفتگو → ${fa(
            sales.conversion.orders,
          )} سفارش تأییدشده`}
        />
      </StatRow>

      <div className="grid gap-4 lg:grid-cols-2">
        <div className="space-y-2">
          <DailyBarChart
            title="درآمد روزانه"
            series="revenue"
            caption={`${window} · تومان · بر اساس روزِ تأیید پرداخت`}
            points={revenue}
            format={(v) => toman(v)}
          />
          <ChartTable points={revenue} label="درآمد (تومان)" format={(v) => toman(v)} />
        </div>
        <div className="space-y-2">
          <DailyBarChart
            title="سفارش‌های روزانه"
            series="orders"
            caption={`${window} · بر اساس روزِ ثبت سفارش`}
            points={orders}
          />
          <ChartTable points={orders} label="سفارش" />
        </div>
      </div>

      <Card>
        <SectionTitle>پرفروش‌ترین محصولات · {window}</SectionTitle>
        {sales.top_products.length === 0 ? (
          <EmptyState icon="box" title="هنوز فروشی ثبت نشده">
            وقتی اولین سفارش تأیید شود، این جدول پر می‌شود.
          </EmptyState>
        ) : (
          <Table>
            <thead>
              <tr>
                <th>محصول</th>
                <th>تعداد فروش</th>
                <th>درآمد</th>
              </tr>
            </thead>
            <tbody>
              {sales.top_products.map((row) => (
                <tr key={row.name}>
                  <td style={{ color: "var(--text)", fontWeight: 500 }}>{row.name}</td>
                  <td className="u-num">{fa(row.quantity)}</td>
                  <td className="u-num">{toman(Number(row.revenue))} تومان</td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
    </div>
  );
}
