import { useState } from "react";
import { Link } from "react-router-dom";

import { api, errorMessage } from "../../api/client";
import Icon from "../../components/Icon";
import { Badge, Button, Card, EmptyState, fa, toman } from "../../components/ui";
import { OrderInfo, OrderStatus } from "../../types";
import { useSales } from "./SalesLayout";

const STATUS: Record<OrderStatus, { label: string; tone: "neutral" | "info" | "warn" | "ok" | "bad" }> =
  {
    DRAFT: { label: "پیش‌نویس", tone: "neutral" },
    AWAITING_RECEIPT: { label: "منتظر رسید مشتری", tone: "info" },
    AWAITING_APPROVAL: { label: "منتظر تأیید شما", tone: "warn" },
    COD: { label: "پرداخت در محل", tone: "info" },
    CONFIRMED: { label: "تأییدشده", tone: "ok" },
    CANCELLED: { label: "لغوشده", tone: "bad" },
  };

const FILTERS = [
  { key: "action", label: "منتظر اقدام" },
  { key: "open", label: "در جریان" },
  { key: "all", label: "همه" },
] as const;

type Filter = (typeof FILTERS)[number]["key"];

const when = (iso: string) =>
  new Date(iso).toLocaleString("fa-IR", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });

export default function OrdersPage() {
  const { orders, storeId, reload, busyId, setBusyId, setNotice, setError } = useSales();
  const [filter, setFilter] = useState<Filter>("action");

  const decide = async (
    orderId: number,
    decision: "confirm" | "reject" | "cod" | "cancel",
  ) => {
    setBusyId(orderId);
    setError(null);
    setNotice(null);
    try {
      await api.post(`/orders/${orderId}/${decision}/`);
      setNotice(
        decision === "confirm"
          ? `سفارش #${orderId} تأیید شد — کالا از موجودی کم شد.`
          : decision === "reject"
            ? `رسید سفارش #${orderId} رد شد — مشتری باید رسید جدید بفرستد.`
            : decision === "cod"
              ? `سفارش #${orderId} «پرداخت در محل» شد — کالا کنار گذاشته شد و تأیید نهایی بعد از گرفتن پول است.`
              : `سفارش #${orderId} لغو شد.`,
      );
      await reload();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusyId(null);
    }
  };

  const counts: Record<Filter, number> = {
    action: orders.filter((o) => o.status === "AWAITING_APPROVAL").length,
    open: orders.filter((o) => o.status !== "CONFIRMED" && o.status !== "CANCELLED").length,
    all: orders.length,
  };

  // «منتظر اقدام» پیش‌فرض است، ولی اگر خالی باشد نشان دادن یک صفحه‌ی خالی
  // به کسی که ده سفارش دارد، غلط است — به «در جریان» می‌افتد.
  const active: Filter = filter === "action" && counts.action === 0 ? "open" : filter;

  const shown: OrderInfo[] = orders
    .filter((o) =>
      active === "all"
        ? true
        : active === "action"
          ? o.status === "AWAITING_APPROVAL"
          : o.status !== "CONFIRMED" && o.status !== "CANCELLED",
    )
    .sort((a, b) => {
      // منتظر تأیید همیشه بالا — این تنها ردیفی است که کار می‌خواهد
      const rank = (o: OrderInfo) => (o.status === "AWAITING_APPROVAL" ? 0 : 1);
      return rank(a) - rank(b) || b.id - a.id;
    });

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-1.5">
        {FILTERS.map((f) => (
          <button
            key={f.key}
            onClick={() => setFilter(f.key)}
            className={`u-btn u-btn-sm ${active === f.key ? "u-btn-secondary" : "u-btn-ghost"}`}
            aria-pressed={active === f.key}
          >
            {f.label}
            <span className="u-num opacity-60">{fa(counts[f.key])}</span>
          </button>
        ))}
      </div>

      {shown.length === 0 ? (
        <Card>
          <EmptyState icon="receipt" title="سفارشی در این دسته نیست">
            سفارش‌ها از چت فروش ثبت می‌شوند — ایجنت می‌تواند سفارش را پیشنهاد کند، ولی
            تأییدش همیشه با شماست.
          </EmptyState>
        </Card>
      ) : (
        <div className="space-y-3">
          {shown.map((order) => {
            const needsAction = order.status === "AWAITING_APPROVAL";
            const done = order.status === "CONFIRMED" || order.status === "CANCELLED";
            // The backend refuses a confirmation with no receipt and no
            // pay-on-delivery decision; the button follows the same rule so
            // nobody clicks their way into an error message.
            const canConfirm =
              order.status === "COD" ||
              (order.receipts ?? []).some((r) => r.status === "PENDING");
            return (
              <Card key={order.id}>
                {/* ردیفی که کار می‌خواهد لبه‌ی رنگی می‌گیرد، نه پس‌زمینه‌ی
                    رنگی: روی سطح شیشه‌ای، یک زردِ کم‌رنگ دیده نمی‌شود، ولی
                    خطِ سه‌پیکسلی کنار کارت در فهرست بلند هم پیدا است. */}
                <div
                  style={
                    needsAction
                      ? {
                          borderInlineStart: "3px solid var(--warn)",
                          marginInlineStart: -20,
                          paddingInlineStart: 17,
                        }
                      : undefined
                  }
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-bold" style={{ color: "var(--text)" }}>
                      سفارش #{fa(order.id)}
                    </span>
                    <Badge tone={STATUS[order.status].tone}>{STATUS[order.status].label}</Badge>
                    <span className="u-num text-sm" style={{ color: "var(--text-2)" }}>
                      {toman(Number(order.total))} تومان
                    </span>
                    {order.customer?.name && (
                      <span className="text-xs" style={{ color: "var(--text-3)" }}>
                        مشتری: {order.customer.name}
                      </span>
                    )}
                    <span className="mr-auto text-xs" style={{ color: "var(--text-3)" }}>
                      {when(order.created_at)}
                    </span>
                  </div>

                  <p className="mt-1.5 text-sm" style={{ color: "var(--text-2)" }}>
                    {order.items.map((it) => `${fa(it.quantity)}× ${it.product_name}`).join("، ")}
                  </p>

                  {(order.receipts?.length ?? 0) > 0 && (
                    <div className="mt-2.5 flex flex-wrap items-center gap-2">
                      {order.receipts!.map((receipt) => (
                        <a
                          key={receipt.id}
                          href={receipt.image}
                          target="_blank"
                          rel="noreferrer"
                          title={
                            receipt.status === "PENDING"
                              ? "در انتظار بررسی — برای بزرگ‌نمایی کلیک کنید"
                              : receipt.status === "APPROVED"
                                ? "تأییدشده"
                                : `ردشده${receipt.review_note ? `: ${receipt.review_note}` : ""}`
                          }
                        >
                          <img
                            src={receipt.image}
                            alt={`رسید #${fa(receipt.id)}`}
                            className="h-16 w-16 rounded-lg object-cover"
                            style={{
                              border: `2px solid var(--${
                                receipt.status === "PENDING"
                                  ? "warn"
                                  : receipt.status === "APPROVED"
                                    ? "ok"
                                    : "bad"
                              })`,
                              opacity: receipt.status === "REJECTED" ? 0.55 : 1,
                            }}
                          />
                        </a>
                      ))}
                    </div>
                  )}

                  {order.stock_state === "RESERVED" && order.reserved_until && (
                    <p className="mt-2 text-xs" style={{ color: "var(--text-3)" }}>
                      کالا تا {when(order.reserved_until)} برای این سفارش کنار گذاشته شده؛
                      بعد از آن دوباره قابل فروش می‌شود.
                    </p>
                  )}

                  {!done && (
                    <div className="mt-3 flex flex-wrap gap-2">
                      {/* «تأیید» یعنی پول رسید. بدون رسید فقط وقتی معنی دارد که
                          خودتان گفته باشید پول را در محل می‌گیرید — برای همین
                          دو دکمه‌ی جداست، نه یکی که هر دو کار را بکند. */}
                      {canConfirm && (
                        <Button
                          onClick={() => void decide(order.id, "confirm")}
                          disabled={busyId === order.id}
                        >
                          <Icon name="check" size={15} />
                          {order.status === "COD" ? "پول را گرفتم" : "تأیید پرداخت"}
                        </Button>
                      )}
                      {order.status !== "COD" && (
                        <Button
                          variant="secondary"
                          onClick={() => void decide(order.id, "cod")}
                          disabled={busyId === order.id}
                          title="مشتری هنگام تحویل پرداخت می‌کند؛ رسیدی در کار نیست."
                        >
                          پرداخت در محل
                        </Button>
                      )}
                      {needsAction && (
                        <Button
                          variant="secondary"
                          onClick={() => void decide(order.id, "reject")}
                          disabled={busyId === order.id}
                        >
                          <Icon name="refresh" size={15} />
                          رد رسید
                        </Button>
                      )}
                      <Button
                        variant="danger"
                        onClick={() => void decide(order.id, "cancel")}
                        disabled={busyId === order.id}
                      >
                        لغو
                      </Button>
                    </div>
                  )}
                </div>
              </Card>
            );
          })}
        </div>
      )}

      <p className="text-xs" style={{ color: "var(--text-3)" }}>
        گفتگوی هر سفارش در{" "}
        <Link to={`/stores/${storeId}/inbox`} style={{ color: "var(--brand-strong)" }}>
          صندوق پیام
        </Link>{" "}
        است.
      </p>
    </div>
  );
}
