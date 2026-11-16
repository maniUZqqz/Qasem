import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { Link, NavLink, Outlet, useParams } from "react-router-dom";

import { errorMessage } from "../../api/client";
import Icon, { type IconName } from "../../components/Icon";
import { ErrorBox, Select } from "../../components/ui";
import { useFlags } from "../panel/FlagsContext";
import { InboxList, PRESENCE_TITLE, PresenceStatus, get, post } from "./api";
import { faNum } from "./format";
import "./inbox.css";

/**
 * قاب «صندوق پیام» — یک جا برای همهٔ کانال‌ها.
 *
 * دو کار مشترک این‌جاست که همهٔ زیرصفحه‌ها لازم دارند:
 *  - «حضور»: تا این قاب باز است هر ۶۰ ثانیه به سرور می‌گوییم این نفر پای صندوق است؛
 *    تقسیم خودکارِ گفتگو فقط به آنلاین‌ها می‌دهد و با بسته‌شدن صفحه خودش آفلاین می‌شود.
 *  - شمارنده‌ها: «منتظر پاسخ» و «ردشدهٔ SLA» کنار زبانه‌ها.
 */

type Ctx = {
  storeId: string;
  counts: InboxList["counts"] | null;
  me: InboxList["me"] | null;
  members: InboxList["members"];
  refreshCounts: () => void;
};

const InboxCtx = createContext<Ctx | null>(null);

export function useInbox(): Ctx {
  const ctx = useContext(InboxCtx);
  if (!ctx) throw new Error("useInbox must be used inside InboxLayout");
  return ctx;
}

function Badge({ n, bad }: { n: number; bad?: boolean }) {
  if (!n) return null;
  return (
    <span
      className="u-num rounded-full px-1.5 text-[11px] font-bold"
      style={{
        background: bad ? "var(--bad)" : "var(--surface-2)",
        color: bad ? "#fff" : "var(--text-2)",
        border: bad ? "none" : "1px solid var(--line)",
      }}
    >
      {faNum(n)}
    </span>
  );
}

export default function InboxLayout() {
  const { id: storeId = "" } = useParams<{ id: string }>();
  const { pageEnabled } = useFlags();
  const [counts, setCounts] = useState<InboxList["counts"] | null>(null);
  const [me, setMe] = useState<InboxList["me"] | null>(null);
  const [members, setMembers] = useState<InboxList["members"]>([]);
  const [status, setStatus] = useState<PresenceStatus>(() => {
    // اگر کسی «آفلاین» را انتخاب کرده بود، با باز کردن دوبارهٔ صفحه خودکار آنلاین نشود.
    try {
      const saved = localStorage.getItem("ib-presence") as PresenceStatus | null;
      if (saved === "ONLINE" || saved === "BUSY" || saved === "OFFLINE") return saved;
    } catch {
      /* حافظهٔ مرورگر بسته است */
    }
    return "ONLINE";
  });
  const [error, setError] = useState<string | null>(null);
  const alive = useRef(true);

  const refreshCounts = useCallback(() => {
    get<InboxList>(storeId, "v2/", { limit: 1 })
      .then((data) => {
        if (!alive.current) return;
        setCounts(data.counts);
        setMe(data.me);
        setMembers(data.members);
      })
      .catch((err) => alive.current && setError(errorMessage(err)));
  }, [storeId]);

  useEffect(() => {
    alive.current = true;
    refreshCounts();
    const timer = window.setInterval(() => document.visibilityState === "visible" && refreshCounts(), 20000);
    return () => {
      alive.current = false;
      window.clearInterval(timer);
    };
  }, [refreshCounts]);

  // حضور: فقط کسی که اجازهٔ پاسخ دارد (نه بازدیدکننده). وضعیتِ انتخاب‌شده هر بار با خودِ پینگ می‌رود.
  useEffect(() => {
    if (!me?.can_write) return;
    const ping = () => {
      if (document.visibilityState === "visible") void post(storeId, "presence/", { status }).catch(() => undefined);
    };
    ping();
    const timer = window.setInterval(ping, 60000);
    return () => window.clearInterval(timer);
  }, [storeId, me?.can_write, status]);

  const choose = async (next: PresenceStatus) => {
    setStatus(next);
    try {
      localStorage.setItem("ib-presence", next);
    } catch {
      /* مهم نیست */
    }
    try {
      await post(storeId, "presence/", { status: next });
      refreshCounts();
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  const tabs: { key: string; to: string; label: string; icon: IconName; end?: boolean; badge?: JSX.Element }[] = [
    {
      key: "inbox", to: "", label: "گفتگوها", icon: "inbox", end: true,
      badge: <Badge n={counts?.waiting ?? 0} bad />,
    },
    { key: "inbox_channels", to: "channels", label: "کانال‌ها", icon: "link" },
    { key: "inbox_team", to: "team", label: "تیم و SLA", icon: "users", badge: <Badge n={counts?.breached ?? 0} bad /> },
    { key: "inbox_bot", to: "bot", label: "ربات و تنظیمات", icon: "sparkle" },
    { key: "inbox_crm", to: "crm", label: "مشتریان", icon: "tag" },
    { key: "inbox_broadcasts", to: "broadcasts", label: "ارسال گروهی", icon: "send" },
    { key: "inbox_followups", to: "followups", label: "پیگیری‌ها", icon: "clock" },
    { key: "inbox_dev", to: "developers", label: "توسعه‌دهندگان", icon: "key" },
  ];

  const ctx = useMemo<Ctx>(() => ({ storeId, counts, me, members, refreshCounts }), [storeId, counts, me, members, refreshCounts]);

  return (
    <InboxCtx.Provider value={ctx}>
      <div className="u-rise space-y-4">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <Link to={`/stores/${storeId}`} className="u-back">
              <Icon name="back" size={15} />
              بازگشت به فروشگاه
            </Link>
            <h1 className="mt-1 text-2xl font-extrabold" style={{ color: "var(--text)" }}>
              صندوق پیام
            </h1>
            <p className="text-xs" style={{ color: "var(--text-3)" }}>
              تلگرام، بله، ایتا، روبیکا، پیامک و چت سایت در یک پنجره؛ ربات جواب می‌دهد و هرجا لازم شد به همکارتان می‌سپارد.
            </p>
          </div>
          {me?.can_write && (
            <label className="flex items-center gap-2 text-xs" style={{ color: "var(--text-3)" }}>
              وضعیت من
              <Select
                value={status}
                onChange={(e) => void choose(e.target.value as PresenceStatus)}
                style={{ width: 120 }}
                aria-label="وضعیت من"
              >
                {(Object.keys(PRESENCE_TITLE) as PresenceStatus[]).map((s) => (
                  <option key={s} value={s}>
                    {PRESENCE_TITLE[s]}
                  </option>
                ))}
              </Select>
            </label>
          )}
        </div>

        <ErrorBox message={error} />

        <nav className="u-tabs">
          {tabs
            .filter((tab) => pageEnabled(tab.key))
            .map((tab) => (
              <NavLink
                key={tab.key}
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

        <Outlet />
      </div>
    </InboxCtx.Provider>
  );
}
