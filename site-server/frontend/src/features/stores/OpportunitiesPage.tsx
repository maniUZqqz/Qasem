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

type ChannelLink = { title: string; url: string; price_toman: number | null; seller: string };

type Evidence = {
  channel?: string;
  channel_label?: string;
  listings?: number;
  same_product?: number;
  sellers?: number;
  min_price?: number | null;
  median_price?: number | null;
  our_price?: number | null;
  our_vs_median_percent?: number | null;
  demand?: { kind: string; label: string; total: number; week?: number };
  links?: ChannelLink[];
  signup?: string;
  our_price_toman?: number;
  competitor_price?: number;
  competitor?: string;
  gap_percent?: number;
  margin_percent?: number;
  units?: number;
  stock?: number;
  missing?: string[];
  [key: string]: unknown;
};

type Opportunity = {
  id: number;
  kind: string;
  kind_label: string;
  product: number | null;
  product_name: string | null;
  title: string;
  reason: string;
  action: string;
  evidence: Evidence;
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

type ReadinessItem = {
  key: string;
  title: string;
  done: boolean;
  detail: string;
  unlocks: string;
  unlocks_count: number | null;
  fix: { label: string; to?: string; action?: string } | null;
};

type ChannelRow = {
  label: string;
  ok: boolean;
  error?: string;
  results?: number;
  relevant?: number;
  sellers?: number;
  min_price?: number | null;
  median_price?: number | null;
  our_vs_median_percent?: number;
  links?: ChannelLink[];
  demand?: { label: string; total: number; week?: number };
};

type ChannelReport = {
  checked_at: string;
  products: { id: number; name: string }[];
  channels: Record<string, Record<string, ChannelRow>>;
  problems: string[];
};

type Readiness = {
  items: ReadinessItem[];
  done: number;
  total: number;
  channels: ChannelReport | null;
};

const KIND_HELP: Record<string, string> = {
  CHANNEL: "کجا بفروشم",
  PRICING: "قیمت",
  CONTENT: "محتوا",
  BUNDLE: "فروشِ مکمل",
  INVENTORY: "داده‌ی ناقص",
  NEW_PRODUCT: "محصولِ تازه",
};

/**
 * «چه کاری بکنم که بیشتر بفروشم؟» — and the numbers behind each answer.
 *
 * The page used to show an empty list to any shop without cost prices, sales
 * and competitors, without saying so. Now it starts with «چه چیزی لازم است»:
 * which data is missing, a link to fix each, and what it would unlock. «کجا
 * بفروشم» searches Digikala/Basalam/Torob for the shop's products and suggests
 * the marketplaces where the product sells and the shop's price is competitive.
 *
 * Every card: a plain title, «چرا» with the numbers it came from, one concrete
 * «چه کنم», and «انجام شد / رد».
 */
export default function OpportunitiesPage() {
  const { id } = useParams<{ id: string }>();
  const [rows, setRows] = useState<Opportunity[] | null>(null);
  const [report, setReport] = useState<ProfitReport | null>(null);
  const [readiness, setReadiness] = useState<Readiness | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    const [list, profit, ready] = await Promise.allSettled([
      api.get(`/stores/${id}/opportunities/`),
      api.get(`/stores/${id}/profit/`),
      api.get(`/stores/${id}/opportunities/readiness/`),
    ]);
    if (list.status === "fulfilled") setRows(list.value.data);
    else setRows([]);
    if (profit.status === "fulfilled") setReport(profit.value.data);
    if (ready.status === "fulfilled") setReadiness(ready.value.data);
  }, [id]);

  useEffect(() => {
    load();
  }, [load]);

  async function refresh() {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const { data } = await api.post(`/stores/${id}/opportunities/`, { check_channels: true });
      setRows(data.opportunities);
      setReadiness(data.readiness);
      const s = data.summary;
      setNotice(
        `${fa(s.created)} پیشنهادِ تازه، ${fa(s.updated)} به‌روز، ${fa(s.resolved)} بسته شد (دیگر صدق نمی‌کرد).`,
      );
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
      setRows((current) => (current ?? []).filter((r) => r.id !== row.id));
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  if (rows === null) return <Spinner />;

  const channelCards = rows.filter((r) => r.kind === "CHANNEL");
  const otherCards = rows.filter((r) => r.kind !== "CHANNEL");

  return (
    <>
      <PageHeader
        title="فرصت‌های فروش"
        subtitle="چه کنم که بیشتر و سودمندتر بفروشم — هر پیشنهاد با عددی که از آن آمده"
        actions={
          <div className="flex gap-2">
            <Button onClick={refresh} disabled={busy}>
              {busy ? "در حال بررسی…" : "بازمحاسبه"}
            </Button>
            <Link to={`/stores/${id}`}>
              <Button variant="secondary">بازگشت</Button>
            </Link>
          </div>
        }
      />

      <ErrorBox message={error} />
      {notice && (
        <div className="mb-4">
          <Alert tone="ok">{notice}</Alert>
        </div>
      )}

      <div className="mb-6">
        <Alert tone="info" title="این صفحه چطور کمک می‌کند">
          «بازمحاسبه» سه کار می‌کند: (۱) محصولاتِ شما را در دیجی‌کالا، باسلام و ترب جست‌وجو
          می‌کند و می‌گوید <b>کجا بفروشید</b> (جایی که همین کالا خریدار دارد و قیمتِ شما
          رقابتی است)، (۲) قیمتِ شما را با رقبای ثبت‌شده می‌سنجد، (۳) از فروش و موجودی می‌گوید
          کدام کالا مانده و کدام پرفروش است. هر پیشنهاد عددهایش را نشان می‌دهد؛ چیزی حدس زده
          نمی‌شود.
        </Alert>
      </div>

      {readiness && (
        <Card>
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
            <SectionTitle>چه چیزی لازم است</SectionTitle>
            <Badge tone={readiness.done === readiness.total ? "ok" : "warn"}>
              {fa(readiness.done)} از {fa(readiness.total)} آماده
            </Badge>
          </div>
          <ul className="flex flex-col divide-y" style={{ borderColor: "var(--line)" }}>
            {readiness.items.map((item) => (
              <li key={item.key} className="flex flex-wrap items-start justify-between gap-3 py-2">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span style={{ color: item.done ? "var(--ok)" : "var(--warn)" }}>
                      {item.done ? "✓" : "○"}
                    </span>
                    <span className="font-medium" style={{ color: "var(--text)" }}>
                      {item.title}
                    </span>
                  </div>
                  <p className="text-sm" style={{ color: "var(--text-2)" }}>
                    {item.detail}
                  </p>
                  {!item.done && (
                    <p className="text-xs" style={{ color: "var(--text-3)" }}>
                      با این، باز می‌شود: {item.unlocks}
                      {item.unlocks_count ? ` (تا ${fa(item.unlocks_count)} محصول)` : ""}
                    </p>
                  )}
                </div>
                {item.fix &&
                  (item.fix.action === "check_channels" ? (
                    <Button variant={item.done ? "ghost" : "secondary"} onClick={refresh} disabled={busy}>
                      {item.done ? "بررسیِ دوباره" : item.fix.label}
                    </Button>
                  ) : item.fix.to && !item.done ? (
                    <Link to={item.fix.to}>
                      <Button variant="secondary">{item.fix.label}</Button>
                    </Link>
                  ) : null)}
              </li>
            ))}
          </ul>
        </Card>
      )}

      <div className="mt-6">
        <SectionTitle>کجا بفروشم</SectionTitle>
      </div>
      {channelCards.length > 0 ? (
        <div className="flex flex-col gap-3">
          {channelCards.map((row) => (
            <OpportunityCard key={row.id} row={row} onState={setState} />
          ))}
        </div>
      ) : (
        <Card>
          <p className="text-sm leading-7" style={{ color: "var(--text-2)" }}>
            {readiness?.channels
              ? "در بررسیِ آخر، برای محصولاتِ شما در بازارها آگهیِ هم‌کالایی پیدا نشد که بشود از رویش پیشنهاد داد. جزئیاتِ هر بازار پایین‌تر است."
              : "هنوز بررسی نشده. «بازمحاسبه» را بزنید تا محصولاتتان در دیجی‌کالا، باسلام و ترب جست‌وجو شوند."}
          </p>
        </Card>
      )}

      {readiness?.channels && <ChannelTable report={readiness.channels} />}

      <div className="mt-8">
        <SectionTitle>پیشنهادهای دیگر</SectionTitle>
      </div>
      {otherCards.length === 0 ? (
        <EmptyState
          icon="bulb"
          title="فعلاً پیشنهادِ دیگری نیست"
          description="هرچه موارد «چه چیزی لازم است» کامل‌تر باشد، پیشنهادِ قیمت، محتوا و موجودی بیشتری ساخته می‌شود."
        />
      ) : (
        <div className="flex flex-col gap-3">
          {otherCards.map((row) => (
            <OpportunityCard key={row.id} row={row} onState={setState} />
          ))}
        </div>
      )}

      {report && (
        <div className="mt-8 grid gap-4 sm:grid-cols-3">
          <Stat label="درآمد این دوره" value={toman(Number(report.total_revenue))} />
          <Stat
            label="سود واقعی"
            value={report.total_profit === null ? "نامشخص" : toman(Number(report.total_profit))}
            hint={
              report.total_profit === null
                ? "قیمت تمام‌شده وارد نشده"
                : `بر اساس ${fa(report.profit_covers_products)} محصول`
            }
          />
          <Stat label="بازه" value={`${fa(report.days)} روز`} />
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
                    <td>
                      <Link to={`/products/${row.product_id}`} className="underline">
                        {row.name}
                      </Link>
                    </td>
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
                    <td className="u-num">{row.profit === null ? "—" : toman(Number(row.profit))}</td>
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

function OpportunityCard({
  row,
  onState,
}: {
  row: Opportunity;
  onState: (row: Opportunity, state: string) => void;
}) {
  const ev = row.evidence || {};
  return (
    <Card>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="mb-1 flex flex-wrap items-center gap-2">
            <span className="font-bold" style={{ color: "var(--text)" }}>
              {row.title}
            </span>
            <Badge tone={row.kind === "CHANNEL" ? "info" : "brand"}>
              {KIND_HELP[row.kind] ?? row.kind_label}
            </Badge>
          </div>
          <p className="text-sm leading-7" style={{ color: "var(--text-2)" }}>
            <b>چرا: </b>
            {row.reason}
          </p>
          <p className="mt-1 text-sm font-medium" style={{ color: "var(--text)" }}>
            <b>چه کنم: </b>
            {row.action}
          </p>
          {row.kind === "CHANNEL" && (
            <div className="mt-2 flex flex-wrap gap-2 text-xs">
              {ev.listings != null && <Badge tone="neutral">{fa(ev.listings)} آگهیِ مشابه</Badge>}
              {ev.sellers != null && <Badge tone="neutral">{fa(ev.sellers)} فروشنده</Badge>}
              {ev.min_price != null && <Badge tone="neutral">ارزان‌ترین {toman(ev.min_price)}</Badge>}
              {ev.median_price != null && <Badge tone="neutral">میانه {toman(ev.median_price)}</Badge>}
              {ev.our_price != null && <Badge tone="brand">قیمت شما {toman(ev.our_price)}</Badge>}
              {ev.demand && ev.demand.total > 0 && (
                <Badge tone="ok">
                  {fa(ev.demand.total)} — {ev.demand.label}
                </Badge>
              )}
            </div>
          )}
          {ev.links && ev.links.length > 0 && (
            <ul className="mt-2 list-inside list-disc text-xs leading-6" style={{ color: "var(--text-3)" }}>
              {ev.links.map((link) => (
                <li key={link.url || link.title}>
                  <a href={link.url} target="_blank" rel="noreferrer" className="underline">
                    {link.title}
                  </a>
                  {link.price_toman ? ` — ${toman(link.price_toman)}` : ""}
                  {link.seller ? ` · ${link.seller}` : ""}
                </li>
              ))}
            </ul>
          )}
          {ev.signup && (
            <a
              href={ev.signup}
              target="_blank"
              rel="noreferrer"
              className="mt-1 inline-block text-xs underline"
            >
              ثبت‌نامِ فروشنده در {ev.channel_label}
            </a>
          )}
        </div>
        <div className="flex gap-2">
          <Button variant="secondary" onClick={() => onState(row, "DONE")}>
            انجام شد
          </Button>
          <Button variant="ghost" onClick={() => onState(row, "DISMISSED")}>
            رد
          </Button>
        </div>
      </div>
    </Card>
  );
}

function ChannelTable({ report }: { report: ChannelReport }) {
  const channelKeys = ["digikala", "basalam", "torob"];
  return (
    <div className="mt-3">
      <Card padded={false}>
        <div className="px-4 pt-3 text-xs" style={{ color: "var(--text-3)" }}>
          بررسیِ بازارها — {new Date(report.checked_at).toLocaleString("fa-IR")}. فقط آگهی‌هایی
          شمرده شده که همان کالا یا جایگزینِ آن‌اند.
          {report.problems.length > 0 && ` در دسترس نبود: ${report.problems.join("؛ ")}`}
        </div>
        <Table>
          <thead>
            <tr>
              <th>محصول</th>
              {channelKeys.map((key) => (
                <th key={key}>{{ digikala: "دیجی‌کالا", basalam: "باسلام", torob: "ترب" }[key]}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {report.products.map((product) => (
              <tr key={product.id}>
                <td>{product.name}</td>
                {channelKeys.map((key) => {
                  const cell = report.channels[String(product.id)]?.[key];
                  if (!cell) return <td key={key}>—</td>;
                  if (!cell.ok)
                    return (
                      <td key={key} className="text-xs" style={{ color: "var(--warn)" }}>
                        در دسترس نبود
                      </td>
                    );
                  return (
                    <td key={key} className="text-xs leading-6">
                      {cell.relevant
                        ? `${fa(cell.relevant)} آگهیِ مشابه از ${fa(cell.results ?? 0)} نتیجه`
                        : `از ${fa(cell.results ?? 0)} نتیجه هیچ‌کدام همین کالا نبود`}
                      {cell.median_price ? (
                        <div>
                          میانه {toman(cell.median_price)}
                          {cell.our_vs_median_percent != null &&
                            ` (شما ${cell.our_vs_median_percent > 0 ? "+" : ""}${fa(
                              Math.round(cell.our_vs_median_percent),
                            )}٪)`}
                        </div>
                      ) : null}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </Table>
      </Card>
    </div>
  );
}
