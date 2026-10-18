import { useCallback, useEffect, useState } from "react";
import { Link, NavLink, Outlet, useOutletContext, useParams } from "react-router-dom";

import { api } from "../../api/client";
import Icon, { type IconName } from "../../components/Icon";
import { fa } from "../../components/ui";
import { useFlags } from "../panel/FlagsContext";

/**
 * قاب کمپین‌ها.
 *
 * سه کار جدا که تا حالا یکی‌شان رابط نداشت:
 *   • فهرست و ساخت کمپین
 *   • تقویم انتشار — چه چیزی کِی می‌رود
 *   • صف انتشار — چه چیزی رفت، چه چیزی گیر کرد
 *
 * زمان‌بندی از فاز ۲۴ در بک‌اند کامل بود (`scheduling.py` با Celery beat،
 * `POST /campaigns/{id}/schedule/`، `GET /stores/{id}/scheduled/`) و هیچ
 * دکمه‌ای در پنل نداشت. مثل آن شش صفحه‌ی گم‌شده‌ی سایدبار: کد نوشته شده،
 * تست شده، و از دید کاربر وجود نداشت.
 */

export type ScheduledRow = {
  id: number;
  campaign: string;
  platform: string;
  scheduled_for: string;
  status: string;
  status_label: string;
  error: string | null;
  published_at: string | null;
};

type Ctx = { storeId: string; scheduled: ScheduledRow[]; reloadScheduled: () => Promise<void> };

export function useCampaigns() {
  return useOutletContext<Ctx>();
}

export default function CampaignsLayout() {
  const { id: storeId } = useParams<{ id: string }>();
  const { pageEnabled } = useFlags();
  const [scheduled, setScheduled] = useState<ScheduledRow[]>([]);

  const reloadScheduled = useCallback(async () => {
    try {
      const { data } = await api.get<ScheduledRow[]>(`/stores/${storeId}/scheduled/`);
      setScheduled(data);
    } catch {
      // صف زمان‌بندی خالی ماندن، دلیل خالی ماندن کل صفحه نیست
      setScheduled([]);
    }
  }, [storeId]);

  useEffect(() => {
    void reloadScheduled();
  }, [reloadScheduled]);

  if (!storeId) return null;

  const upcoming = scheduled.filter(
    (r) => r.status === "PENDING" && new Date(r.scheduled_for) > new Date(),
  ).length;
  const stuck = scheduled.filter((r) => r.status === "FAILED").length;

  // `key` همان کلیدِ صفحه در `features/panel/registry.ts` است؛ زبانه‌ی خاموش کشیده نمی‌شود.
  const tabs: { key: string; to: string; label: string; icon: IconName; end?: boolean; count?: number; bad?: boolean }[] =
    [
      { key: "campaigns", to: "", label: "کمپین‌ها", icon: "rocket", end: true },
      { key: "calendar", to: "calendar", label: "تقویم انتشار", icon: "clock", count: upcoming },
      { key: "publish_queue", to: "queue", label: "صف انتشار", icon: "upload", count: stuck, bad: true },
      { key: "performance", to: "performance", label: "چه چیزی جواب داد", icon: "target" },
    ];

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
          کمپین‌ها
        </h1>
        <p className="text-xs" style={{ color: "var(--text-3)" }}>
          محتوای تولیدشده را گروه کنید، تأیید بگیرید، و زمان انتشارش را تعیین کنید.
        </p>
      </div>

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
              {!!tab.count && (
                <span
                  className="u-num rounded-full px-1.5 text-[11px] font-bold"
                  style={{
                    background: tab.bad ? "var(--bad)" : "var(--surface-2)",
                    color: tab.bad ? "#fff" : "var(--text-2)",
                    border: tab.bad ? "none" : "1px solid var(--line)",
                  }}
                >
                  {fa(tab.count)}
                </span>
              )}
            </span>
          </NavLink>
        ))}
      </nav>

      <Outlet context={{ storeId, scheduled, reloadScheduled } satisfies Ctx} />
    </div>
  );
}
