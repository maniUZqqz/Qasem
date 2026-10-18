import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { api } from "../api/client";
import { NotificationInfo } from "../types";
import Icon from "./Icon";

const POLL_MS = 30_000;

const TYPE_ICON: Record<NotificationInfo["type"], string> = {
  ESCALATION: "🙋",
  ORDER: "🛒",
  RECEIPT: "🧾",
  TICKET: "🎫",
  AI_ERROR: "⚠️",
};

/** Owner notification bell — the AI "pings" the user here whenever it needs a human. */
export default function NotificationsBell() {
  const [items, setItems] = useState<NotificationInfo[]>([]);
  const [unread, setUnread] = useState(0);
  const [open, setOpen] = useState(false);
  const navigate = useNavigate();
  const rootRef = useRef<HTMLDivElement | null>(null);

  const load = useCallback(async () => {
    try {
      const { data } = await api.get<{ results: NotificationInfo[]; unread_count: number }>(
        "/notifications/?unread=true",
      );
      setItems(data.results.slice(0, 10));
      setUnread(data.unread_count ?? data.results.length);
    } catch {
      /* transient — next poll retries */
    }
  }, []);

  useEffect(() => {
    void load();
    const interval = window.setInterval(load, POLL_MS);
    return () => window.clearInterval(interval);
  }, [load]);

  // close on outside click
  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, [open]);

  const openItem = async (item: NotificationInfo) => {
    setOpen(false);
    setItems((prev) => prev.filter((n) => n.id !== item.id));
    setUnread((n) => Math.max(0, n - 1));
    try {
      await api.post(`/notifications/${item.id}/read/`);
    } catch {
      /* read-marker is best-effort */
    }
    if (item.link) navigate(item.link);
  };

  const readAll = async () => {
    setItems([]);
    setUnread(0);
    try {
      await api.post("/notifications/read-all/");
    } catch {
      /* best-effort */
    }
  };

  return (
    <div className="relative" ref={rootRef}>
      <button
        onClick={() => setOpen((v) => !v)}
        className="u-btn u-btn-ghost u-btn-sm relative"
        style={{ padding: 7 }}
        title="اعلان‌ها"
        aria-label="اعلان‌ها"
      >
        <Icon name="bell" size={17} />
        {unread > 0 && (
          <span className="absolute -top-0.5 -left-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-red-600 px-1 text-[10px] font-bold text-white">
            {unread > 9 ? "۹+" : unread.toLocaleString("fa-IR")}
          </span>
        )}
      </button>
      {/* منو `bg-white` بود — روی تم تیره یعنی جعبه‌ی سفید با متنِ روشن، که
          عملاً خالی دیده می‌شد. حالا مات و از توکن، و روی گوشی از لبه‌ی صفحه
          بیرون نمی‌زند (w-80 روی ۳۶۰ پیکسل جا نمی‌شد). */}
      {open && (
        <div
          className="absolute left-0 z-40 mt-2 w-[min(20rem,calc(100vw-2rem))] overflow-hidden rounded-xl"
          style={{
            background: "var(--void-2)",
            border: "1px solid var(--line-strong)",
            boxShadow: "var(--shadow)",
          }}
        >
          <div className="flex items-center justify-between px-4 py-2" style={{ borderBottom: "1px solid var(--line)" }}>
            <span className="text-sm font-bold" style={{ color: "var(--text)" }}>اعلان‌ها</span>
            {items.length > 0 && (
              <button onClick={readAll} className="text-xs hover:underline" style={{ color: "var(--brand-strong)" }}>
                خواندن همه
              </button>
            )}
          </div>
          {items.length === 0 ? (
            <p className="px-4 py-6 text-center text-xs" style={{ color: "var(--text-3)" }}>اعلان خوانده‌نشده‌ای نیست.</p>
          ) : (
            <ul className="max-h-80 overflow-y-auto">
              {items.map((item) => (
                <li key={item.id}>
                  <button
                    onClick={() => void openItem(item)}
                    className="u-notif-item block w-full px-4 py-2.5 text-right transition"
                  >
                    <span className="block text-sm" style={{ color: "var(--text)" }}>
                      {TYPE_ICON[item.type]} {item.title}
                    </span>
                    {item.body && (
                      <span className="mt-0.5 line-clamp-2 block text-xs" style={{ color: "var(--text-2)" }}>
                        {item.body}
                      </span>
                    )}
                    <span className="mt-0.5 block text-[10px]" style={{ color: "var(--text-3)" }}>
                      {item.store_name} ·{" "}
                      {new Date(item.created_at).toLocaleString("fa-IR", {
                        month: "short",
                        day: "numeric",
                        hour: "2-digit",
                        minute: "2-digit",
                      })}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
