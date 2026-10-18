import { useState } from "react";
import { Link } from "react-router-dom";

import { api, errorMessage } from "../../api/client";
import Icon from "../../components/Icon";
import { Badge, Button, Card, EmptyState, fa } from "../../components/ui";
import { useSales } from "./SalesLayout";

const when = (iso: string) =>
  new Date(iso).toLocaleString("fa-IR", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });

/** تیکت‌های پشتیبانی — فوری‌ها اول، بعد قدیمی‌ترین انتظار. */
export default function TicketsPage() {
  const { tickets, storeId, reload, busyId, setBusyId, setError } = useSales();
  const [showResolved, setShowResolved] = useState(false);

  const open = tickets
    .filter((t) => t.status !== "RESOLVED")
    .sort((a, b) => {
      const urgent = (p: string) => (p === "URGENT" ? 0 : 1);
      return (
        urgent(a.priority) - urgent(b.priority) ||
        new Date(a.created_at).getTime() - new Date(b.created_at).getTime()
      );
    });
  const resolved = tickets.filter((t) => t.status === "RESOLVED");

  const resolve = async (ticketId: number) => {
    setBusyId(ticketId);
    setError(null);
    try {
      await api.post(`/tickets/${ticketId}/resolve/`);
      await reload();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div className="space-y-4">
      {open.length === 0 ? (
        <Card>
          <EmptyState icon="ok" title="تیکت بازی وجود ندارد">
            وقتی ایجنت فروش تشخیص بدهد مشتری مشکلی دارد که از دستش برنمی‌آید، اینجا یک
            تیکت می‌سازد.
          </EmptyState>
        </Card>
      ) : (
        <div className="space-y-3">
          {open.map((ticket) => {
            const urgent = ticket.priority === "URGENT";
            return (
              <Card key={ticket.id}>
                <div
                  style={
                    urgent
                      ? {
                          borderInlineStart: "3px solid var(--bad)",
                          marginInlineStart: -20,
                          paddingInlineStart: 17,
                        }
                      : undefined
                  }
                >
                  <div className="flex flex-wrap items-center gap-2">
                    {/* فوریت با آیکون *و* برچسب، نه فقط رنگ */}
                    {urgent && (
                      <Badge tone="bad">
                        <Icon name="warn" size={12} />
                        فوری
                      </Badge>
                    )}
                    <span className="font-bold" style={{ color: "var(--text)" }}>
                      {ticket.subject}
                    </span>
                    {ticket.customer?.name && (
                      <span className="text-xs" style={{ color: "var(--text-3)" }}>
                        مشتری: {ticket.customer.name}
                      </span>
                    )}
                    <span className="mr-auto text-xs" style={{ color: "var(--text-3)" }}>
                      {when(ticket.created_at)}
                    </span>
                  </div>

                  {ticket.description && (
                    <p className="mt-1.5 text-sm leading-7" style={{ color: "var(--text-2)" }}>
                      {ticket.description}
                    </p>
                  )}

                  <div className="mt-3 flex flex-wrap items-center gap-2">
                    <Button
                      variant="secondary"
                      onClick={() => void resolve(ticket.id)}
                      disabled={busyId === ticket.id}
                    >
                      <Icon name="check" size={15} />
                      حل شد
                    </Button>
                    {ticket.conversation && (
                      <Link
                        to={`/stores/${storeId}/inbox`}
                        className="u-btn u-btn-ghost u-btn-sm no-underline"
                      >
                        <Icon name="chat" size={15} />
                        گفتگوی مرتبط
                      </Link>
                    )}
                  </div>
                </div>
              </Card>
            );
          })}
        </div>
      )}

      {resolved.length > 0 && (
        <Card>
          <button
            onClick={() => setShowResolved((v) => !v)}
            className="u-btn u-btn-ghost u-btn-sm"
            aria-expanded={showResolved}
          >
            <Icon name={showResolved ? "up" : "down"} size={14} />
            تیکت‌های حل‌شده ({fa(resolved.length)})
          </button>
          {showResolved && (
            <ul className="mt-3 space-y-2">
              {resolved.map((ticket) => (
                <li key={ticket.id} className="flex gap-2 text-sm">
                  <span style={{ color: "var(--ok)" }}>
                    <Icon name="check" size={15} />
                  </span>
                  <span style={{ color: "var(--text-2)" }}>
                    {ticket.subject}
                    {ticket.resolution_note && (
                      <span style={{ color: "var(--text-3)" }}> — {ticket.resolution_note}</span>
                    )}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Card>
      )}
    </div>
  );
}
