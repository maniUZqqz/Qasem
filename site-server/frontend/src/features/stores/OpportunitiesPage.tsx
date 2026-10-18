import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api, errorMessage } from "../../api/client";
import {
  Alert,
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorBox,
  PageHeader,
  SectionTitle,
  Spinner,
  Stat,
  Table,
  fa,
  toman,
} from "../../components/ui";

type Opportunity = {
  id: number;
  kind: string;
  kind_label: string;
  product_name: string | null;
  title: string;
  reason: string;
  action: string;
  evidence: Record<string, unknown>;
  state: string;
  priority: number;
};

type ProductRow = {
  product_id: number;
  name: string;
  units: number;
  price: string;
  cost_price: string | null;
  revenue: string;
  profit: string | null;
  stock: number;
  margin_percent: number | null;
};

type ProfitReport = {
  days: number;
  products: ProductRow[];
  total_revenue: string;
  total_profit: string | null;
  profit_covers_products: number;
  missing_cost: string[];
  best_sellers: string[];
  most_profitable: string[];
};

/**
 * What to do next, and the numbers behind it.
 *
 * Every suggestion shows its evidence. A recommendation a shop owner cannot
 * audit is one they follow once, get burned by, and never trust again — so the
 * reason names the figures it came from rather than asserting a conclusion.
 *
 * The profit table sits underneath for the same reason: "most sold" and "most
 * profitable" are usually different products, and seeing both side by side is
 * the whole argument for entering a cost price.
 */
export default function OpportunitiesPage() {
  const { id } = useParams<{ id: string }>();
  const [rows, setRows] = useState<Opportunity[] | null>(null);
  const [report, setReport] = useState<ProfitReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    const [list, profit] = await Promise.allSettled([
      api.get(`/stores/${id}/opportunities/`),
      api.get(`/stores/${id}/profit/`),
    ]);
    if (list.status === "fulfilled") setRows(list.value.data);
    else setRows([]);
    if (profit.status === "fulfilled") setReport(profit.value.data);
  }, [id]);

  useEffect(() => {
    load();
  }, [load]);

  async function refresh() {
    setBusy(true);
    setError(null);
    try {
      const { data } = await api.post(`/stores/${id}/opportunities/`, {});
      setRows(data.opportunities);
      const { data: profit } = await api.get(`/stores/${id}/profit/`);
      setReport(profit);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function setState(row: Opportunity, state: string) {
    setError(null);
    try {
      await api.patch(`/stores/${id}/opportunities/${row.id}/`, { state });
      await load();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  if (rows === null) return <Spinner />;

  return (
    <>
      <PageHeader
        title="فرصت‌های فروش"
        subtitle="از داده‌ی واقعی فروشگاه، رقبا و سود — نه حدس"
        actions={
          <div className="flex gap-2">
            <Button onClick={refresh} disabled={busy}>
              {busy ? "در حال محاسبه…" : "بازمحاسبه"}
            </Button>
            <Link to={`/stores/${id}`}>
              <Button variant="secondary">بازگشت</Button>
            </Link>
          </div>
        }
      />

      <ErrorBox message={error} />

      {report && (
        <div className="mb-6 grid gap-4 sm:grid-cols-3">
          <Stat label="درآمد این دوره" value={toman(Number(report.total_revenue))} />
          <Stat
            label="سود واقعی"
            value={
              report.total_profit === null
                ? "نامشخص"
                : toman(Number(report.total_profit))
            }
            hint={
              report.total_profit === null
                ? "قیمت تمام‌شده وارد نشده"
                : `بر اساس ${fa(report.profit_covers_products)} محصول`
            }
          />
          <Stat label="بازه" value={`${fa(report.days)} روز`} />
        </div>
      )}

      {report && report.missing_cost.length > 0 && (
        <div className="mb-6">
          <Alert tone="warn" title="بدون قیمت تمام‌شده، سود قابل محاسبه نیست">
            برای {fa(report.missing_cost.length)} محصول قیمت خرید وارد نشده. تا
            وقتی وارد نشود، فقط درآمد را می‌بینید نه سود — و پرفروش‌ترین محصول
            لزوماً سودآورترین نیست.
          </Alert>
        </div>
      )}

      {rows.length === 0 ? (
        <EmptyState
          icon="bulb"
          title="فعلاً پیشنهادی نیست"
          description="«بازمحاسبه» را بزنید. هرچه محصول، قیمت تمام‌شده و رقیب بیشتری ثبت کرده باشید، پیشنهادها دقیق‌ترند."
        />
      ) : (
        <div className="flex flex-col gap-3">
          {rows.map((row) => (
            <Card key={row.id}>
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0 flex-1">
                  <div className="mb-1 flex flex-wrap items-center gap-2">
                    <span className="font-bold" style={{ color: "var(--text)" }}>
                      {row.title}
                    </span>
                    <Badge tone="brand">{row.kind_label}</Badge>
                  </div>
                  {/* The reason names the figures. Without them this is an
                      assertion, and assertions get ignored. */}
                  <p className="text-sm leading-7" style={{ color: "var(--text-2)" }}>
                    {row.reason}
                  </p>
                  <p className="mt-1 text-sm font-medium" style={{ color: "var(--text)" }}>
                    ← {row.action}
                  </p>
                </div>
                <div className="flex gap-2">
                  <Button variant="secondary" onClick={() => setState(row, "DONE")}>
                    انجام شد
                  </Button>
                  <Button variant="ghost" onClick={() => setState(row, "DISMISSED")}>
                    مهم نیست
                  </Button>
                </div>
              </div>
            </Card>
          ))}
        </div>
      )}

      {report && report.products.length > 0 && (
        <>
          <div className="mt-8">
            <SectionTitle>سود هر محصول</SectionTitle>
          </div>
          <Card padded={false}>
            <Table>
              <thead>
                <tr>
                  <th>محصول</th>
                  <th>فروش</th>
                  <th>قیمت</th>
                  <th>قیمت تمام‌شده</th>
                  <th>حاشیه سود</th>
                  <th>سود دوره</th>
                  <th>موجودی</th>
                </tr>
              </thead>
              <tbody>
                {report.products.map((row) => (
                  <tr key={row.product_id}>
                    <td>{row.name}</td>
                    <td className="u-num">{fa(row.units)}</td>
                    <td className="u-num">{toman(Number(row.price))}</td>
                    <td className="u-num">
                      {row.cost_price === null ? (
                        <span style={{ color: "var(--warn)" }}>وارد نشده</span>
                      ) : (
                        toman(Number(row.cost_price))
                      )}
                    </td>
                    <td className="u-num">
                      {row.margin_percent === null ? "—" : `${fa(row.margin_percent)}٪`}
                    </td>
                    <td className="u-num">
                      {row.profit === null ? "—" : toman(Number(row.profit))}
                    </td>
                    <td className="u-num">{fa(row.stock)}</td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </Card>
        </>
      )}
    </>
  );
}
