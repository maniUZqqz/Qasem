import { useCallback, useEffect, useState } from "react";
import { Link, NavLink, Outlet, useOutletContext, useParams } from "react-router-dom";

import { api, errorMessage, fetchAllPages } from "../../api/client";
import Icon, { type IconName } from "../../components/Icon";
import { ErrorBox, Spinner } from "../../components/ui";
import { OrderInfo, SalesData, TicketInfo } from "../../types";
import { useFlags } from "../panel/FlagsContext";

/**
 * قاب «فروش و پشتیبانی».
 *
 * صفحه‌ی قبلی ۴۹۰ خط بود و پنج کار جدا را پشت سر هم می‌ریخت: کاشی‌های
 * آمار، دو نمودار، پرفروش‌ترین‌ها، فهرست سفارش‌ها و فهرست تیکت‌ها. کسی
 * که می‌آمد یک رسید را تأیید کند، باید از کنار همه‌ی اینها رد می‌شد.
 *
 * حالا چهار زیرصفحه است. داده یک بار اینجا بار می‌شود و از راه
 * `useSales()` به همه می‌رسد — چهار صفحه چهار بار همان سه درخواست را
 * نمی‌زنند، و بعد از هر اقدام، `reload` هر چهارتا را با هم تازه می‌کند.
 */

export type SalesCtx = {
  sales: SalesData;
  orders: OrderInfo[];
  tickets: TicketInfo[];
  storeId: string;
  reload: () => Promise<void>;
  busyId: number | null;
  setBusyId: (id: number | null) => void;
  notice: string | null;
  setNotice: (message: string | null) => void;
  error: string | null;
  setError: (message: string | null) => void;
};

export function useSales() {
  return useOutletContext<SalesCtx>();
}

/** شمارنده‌ی کنار تب. صفر نشان داده نمی‌شود — «۰ منتظر اقدام» یک
 *  اطلاعات نیست، یک لکه است. */
function Count({ n, tone }: { n: number; tone?: "bad" }) {
  if (!n) return null;
  return (
    <span
      className="u-num rounded-full px-1.5 text-[11px] font-bold"
      style={{
        background: tone === "bad" ? "var(--bad)" : "var(--surface-2)",
        color: tone === "bad" ? "#fff" : "var(--text-2)",
        border: tone === "bad" ? "none" : "1px solid var(--line)",
      }}
    >
      {n.toLocaleString("fa-IR")}
    </span>
  );
}

export default function SalesLayout() {
  const { id: storeId } = useParams<{ id: string }>();
  const { pageEnabled } = useFlags();
  const [sales, setSales] = useState<SalesData | null>(null);
  const [orders, setOrders] = useState<OrderInfo[]>([]);
  const [tickets, setTickets] = useState<TicketInfo[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);

  const reload = useCallback(async () => {
    try {
      const [salesRes, ordersList, ticketsList] = await Promise.all([
        api.get<SalesData>(`/stores/${storeId}/analytics/sales/?days=30`),
        fetchAllPages<OrderInfo>(`/stores/${storeId}/orders/`),
        fetchAllPages<TicketInfo>(`/stores/${storeId}/tickets/`),
      ]);
      setSales(salesRes.data);
      setOrders(ordersList);
      setTickets(ticketsList);
    } catch (err) {
      setError(errorMessage(err));
    }
  }, [storeId]);

  useEffect(() => {
    void reload();
  }, [reload]);

  if (!sales || !storeId) {
    return (
      <div className="py-10 text-center">
        {error ? <ErrorBox message={error} /> : <Spinner />}
      </div>
    );
  }

  const needsAction = orders.filter((o) => o.status === "AWAITING_APPROVAL").length;
  const pendingReceipts = orders.reduce(
    (n, o) => n + (o.receipts ?? []).filter((r) => r.status === "PENDING").length,
    0,
  );
  const openTickets = tickets.filter((t) => t.status !== "RESOLVED").length;

  // `key` همان کلیدِ صفحه در `features/panel/registry.ts` است؛ زبانه‌ی خاموش کشیده نمی‌شود.
  const tabs: { key: string; to: string; label: string; icon: IconName; badge?: JSX.Element; end?: boolean }[] =
    [
      { key: "sales", to: "", label: "نمای کلی", icon: "chart", end: true },
      {
        key: "orders",
        to: "orders",
        label: "سفارش‌ها",
        icon: "receipt",
        badge: <Count n={needsAction} tone="bad" />,
      },
      {
        key: "receipts",
        to: "receipts",
        label: "رسیدها",
        icon: "wallet",
        badge: <Count n={pendingReceipts} tone="bad" />,
      },
      { key: "tickets", to: "tickets", label: "تیکت‌ها", icon: "ticket", badge: <Count n={openTickets} /> },
    ];

  const ctx: SalesCtx = {
    sales,
    orders,
    tickets,
    storeId,
    reload,
    busyId,
    setBusyId,
    notice,
    setNotice,
    error,
    setError,
  };

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
          فروش و پشتیبانی
        </h1>
        <p className="text-xs" style={{ color: "var(--text-3)" }}>
          سفارش‌ها را AI ثبت و رسیدها را جمع می‌کند؛ تأیید نهایی همیشه با شماست.
        </p>
      </div>

      <ErrorBox message={error} />
      {notice && (
        <div
          className="rounded-xl px-4 py-2.5 text-sm"
          style={{
            background: "var(--ok-soft)",
            color: "var(--ok)",
            border: "1px solid color-mix(in srgb, var(--ok) 30%, transparent)",
          }}
        >
          {notice}
        </div>
      )}

      <nav className="u-tabs">
        {tabs.filter((tab) => pageEnabled(tab.key)).map((tab) => (
          <NavLink
            key={tab.to}
            to={tab.to}
            end={tab.end}
            className={({ isActive }) => `u-tab ${isActive ? "active" : ""}`}
          >
            <span className="flex items-center gap-1.5">
              <Icon name={tab.icon} size={15} />
              {tab.label}
              {tab.badge}
            </span>
          </NavLink>
        ))}
      </nav>

      <Outlet context={ctx} />
    </div>
  );
}
