import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../api/client";
import { badgeCount, badgeView, parseSummary, type QueueSummary } from "../features/tools/compute/queue/model";
import Icon from "./Icon";
import "./queue-badge.css";

const POLL_MS = 20_000;

/**
 * نشانِ «صفِ پردازش» کنار ساعتِ هدر — فقط برای کارکنان (Layout فقط برای آن‌ها می‌گذاردش).
 *
 * هر ۲۰ ثانیه خلاصهٔ صف را می‌پرسد، فقط تا وقتی زبانهٔ مرورگر دیده می‌شود. خطا را ساکت می‌بلعد: نشانِ هدر
 * نباید با یک قطعیِ لحظه‌ای چیزی را در صفحه خراب کند؛ همان آخرین مقدار می‌ماند.
 * پنهان است وقتی نه کاری منتظر است نه در حال اجرا. زرد است وقتی کار منتظر است و هیچ سروری روشن نیست.
 */
export default function QueueBadge() {
  const [summary, setSummary] = useState<QueueSummary | null>(null);

  useEffect(() => {
    let alive = true;
    const ctrl = new AbortController();

    const load = async () => {
      if (document.hidden) return;
      try {
        const { data } = await api.get("/compute/queue/summary/", { signal: ctrl.signal });
        const next = parseSummary(data);
        if (alive && next) setSummary(next);
      } catch {
        /* ساکت: دورِ بعد دوباره */
      }
    };

    void load();
    const timer = window.setInterval(() => void load(), POLL_MS);
    const onVisible = () => {
      if (!document.hidden) void load();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      alive = false;
      ctrl.abort();
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, []);

  const view = badgeView(summary);
  if (!view) return null;

  return (
    <Link
      to="/tools/compute/queue"
      className={`nmq-pill ${view.tone === "warn" ? "warn" : ""}`}
      title={view.title}
      aria-label={`صفِ پردازش: ${view.title}`}
      data-testid="queue-badge"
    >
      <Icon name="clock" size={16} />
      {view.waiting > 0 && <span>{badgeCount(view.waiting)}</span>}
      {view.running > 0 && (
        <span className="nmq-pill-run">
          <span className="nmq-pulse" aria-hidden="true" />
          {badgeCount(view.running)}
        </span>
      )}
    </Link>
  );
}
