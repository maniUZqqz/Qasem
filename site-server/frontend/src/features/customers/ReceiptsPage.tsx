import { useState } from "react";

import { api, errorMessage } from "../../api/client";
import Icon from "../../components/Icon";
import { Alert, Badge, Button, Card, EmptyState, fa, toman } from "../../components/ui";
import { OrderInfo } from "../../types";
import { useSales } from "./SalesLayout";

/**
 * رسیدهای پرداخت، به‌عنوان یک صف.
 *
 * رسیدها تا حالا صفحه‌ی خودشان را نداشتند — عکس‌های ۶۴ پیکسلی داخل کارت
 * سفارش بودند. ولی بررسی رسید یک *کار* است، نه یک جزئیات: کسی می‌آید
 * ببیند چه کسی پول فرستاده و درست فرستاده یا نه. برای این کار باید عکس
 * را بزرگ ببیند، نه در ابعاد یک آیکون.
 *
 * ترتیب، **قدیمی‌ترین اول** است نه جدیدترین. مشتری‌ای که از دیروز منتظر
 * است باید قبل از کسی که پنج دقیقه پیش فرستاده دیده شود؛ فهرستِ
 * جدیدترین‌اول دقیقاً برعکس این کار را می‌کند و همان یک نفر را ته صف
 * دفن می‌کند.
 */

type Row = {
  order: OrderInfo;
  receipt: NonNullable<OrderInfo["receipts"]>[number];
};

const when = (iso: string) =>
  new Date(iso).toLocaleString("fa-IR", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });

/** چند ساعت است که منتظر است. عددی که تصمیم را عوض می‌کند. */
function waiting(iso: string): string | null {
  const hours = (Date.now() - new Date(iso).getTime()) / 36e5;
  if (hours < 1) return null;
  if (hours < 24) return `${fa(Math.floor(hours))} ساعت منتظر`;
  return `${fa(Math.floor(hours / 24))} روز منتظر`;
}

export default function ReceiptsPage() {
  const { orders, reload, busyId, setBusyId, setNotice, setError } = useSales();
  const [showReviewed, setShowReviewed] = useState(false);

  const rows: Row[] = orders.flatMap((order) =>
    (order.receipts ?? []).map((receipt) => ({ order, receipt })),
  );
  const pending = rows
    .filter((r) => r.receipt.status === "PENDING")
    .sort(
      (a, b) =>
        new Date(a.order.created_at).getTime() - new Date(b.order.created_at).getTime(),
    );
  const reviewed = rows.filter((r) => r.receipt.status !== "PENDING");

  const decide = async (orderId: number, decision: "confirm" | "reject") => {
    setBusyId(orderId);
    setError(null);
    setNotice(null);
    try {
      await api.post(`/orders/${orderId}/${decision}/`);
      setNotice(
        decision === "confirm"
          ? `رسید سفارش #${orderId} تأیید و سفارش نهایی شد.`
          : `رسید سفارش #${orderId} رد شد — مشتری باید رسید جدید بفرستد.`,
      );
      await reload();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div className="space-y-4">
      <Alert tone="warn" title="تأیید پرداخت همیشه با یک آدم است">
        ایجنت فروش هرگز دریافت وجه را تأیید نمی‌کند. آنچه اینجا می‌بینید عکسی است که
        مشتری فرستاده — با حساب خودتان مطابقتش بدهید، بعد تأیید کنید.
      </Alert>

      {pending.length === 0 ? (
        <Card>
          <EmptyState icon="ok" title="رسیدی در انتظار بررسی نیست">
            وقتی مشتری در چت رسید پرداخت بفرستد، اینجا می‌آید.
          </EmptyState>
        </Card>
      ) : (
        <div className="space-y-3">
          {pending.map(({ order, receipt }) => {
            const wait = waiting(order.created_at);
            return (
              <Card key={receipt.id}>
                <div className="flex flex-col gap-4 sm:flex-row">
                  {/* عکس بزرگ، نه تصویر بندانگشتی: این تصمیم روی پول است */}
                  <a
                    href={receipt.image}
                    target="_blank"
                    rel="noreferrer"
                    className="block shrink-0"
                    title="باز کردن در اندازه‌ی کامل"
                  >
                    <img
                      src={receipt.image}
                      alt={`رسید سفارش #${fa(order.id)}`}
                      className="h-44 w-full rounded-xl object-cover sm:w-44"
                      style={{ border: "1px solid var(--line-strong)" }}
                    />
                  </a>

                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-bold" style={{ color: "var(--text)" }}>
                        سفارش #{fa(order.id)}
                      </span>
                      <span
                        className="u-num text-lg font-extrabold"
                        style={{ color: "var(--text)" }}
                      >
                        {toman(Number(order.total))} تومان
                      </span>
                      {wait && <Badge tone="warn">{wait}</Badge>}
                    </div>

                    <dl className="mt-2 space-y-1 text-sm" style={{ color: "var(--text-2)" }}>
                      {order.customer?.name && (
                        <div className="flex gap-2">
                          <dt style={{ color: "var(--text-3)" }}>مشتری:</dt>
                          <dd>{order.customer.name}</dd>
                        </div>
                      )}
                      <div className="flex gap-2">
                        <dt style={{ color: "var(--text-3)" }}>اقلام:</dt>
                        <dd>
                          {order.items
                            .map((it) => `${fa(it.quantity)}× ${it.product_name}`)
                            .join("، ")}
                        </dd>
                      </div>
                      <div className="flex gap-2">
                        <dt style={{ color: "var(--text-3)" }}>ثبت سفارش:</dt>
                        <dd>{when(order.created_at)}</dd>
                      </div>
                    </dl>

                    <div className="mt-4 flex flex-wrap gap-2">
                      <Button
                        onClick={() => void decide(order.id, "confirm")}
                        disabled={busyId === order.id}
                      >
                        <Icon name="check" size={15} />
                        پول رسید — تأیید کن
                      </Button>
                      <Button
                        variant="secondary"
                        onClick={() => void decide(order.id, "reject")}
                        disabled={busyId === order.id}
                      >
                        <Icon name="refresh" size={15} />
                        رسید درست نیست
                      </Button>
                    </div>
                  </div>
                </div>
              </Card>
            );
          })}
        </div>
      )}

      {reviewed.length > 0 && (
        <Card>
          <button
            onClick={() => setShowReviewed((v) => !v)}
            className="u-btn u-btn-ghost u-btn-sm"
            aria-expanded={showReviewed}
          >
            <Icon name={showReviewed ? "up" : "down"} size={14} />
            رسیدهای بررسی‌شده ({fa(reviewed.length)})
          </button>
          {showReviewed && (
            <div className="mt-3 flex flex-wrap gap-3">
              {reviewed.map(({ order, receipt }) => (
                <a
                  key={receipt.id}
                  href={receipt.image}
                  target="_blank"
                  rel="noreferrer"
                  className="block"
                  title={`سفارش #${fa(order.id)} — ${
                    receipt.status === "APPROVED" ? "تأییدشده" : "ردشده"
                  }${receipt.review_note ? `: ${receipt.review_note}` : ""}`}
                >
                  <img
                    src={receipt.image}
                    alt={`رسید #${fa(receipt.id)}`}
                    className="h-20 w-20 rounded-lg object-cover"
                    style={{
                      border: `2px solid var(--${
                        receipt.status === "APPROVED" ? "ok" : "bad"
                      })`,
                      opacity: receipt.status === "APPROVED" ? 1 : 0.55,
                    }}
                  />
                </a>
              ))}
            </div>
          )}
        </Card>
      )}
    </div>
  );
}
