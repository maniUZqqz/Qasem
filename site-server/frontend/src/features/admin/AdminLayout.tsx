import { NavLink, Navigate, Outlet } from "react-router-dom";

import Icon, { type IconName } from "../../components/Icon";
import { Alert } from "../../components/ui";
import { useAuth } from "../auth/AuthContext";
import { useFlags } from "../panel/FlagsContext";

/**
 * بخش ادمین — ابزارهای خودمان، نه فروشگاه‌دار.
 *
 * سه اندپوینت `marketing/*` از فاز ۲۶ ساخته و تست شده بودند و هیچ صفحه‌ای
 * نداشتند. دلیلش هم یک چیز کوچک بود: `UserSerializer` فیلد `is_staff` را
 * برنمی‌گرداند، پس فرانت راهی نداشت بفهمد کسی ادمین است. سه ابزار ساخته
 * شده بود که فقط با curl قابل دسترسی بود.
 *
 * این نگهبان **امنیت نیست**، ناوبری است: هر سه اندپوینت سمت سرور
 * `IsAdminUser` را دوباره چک می‌کنند. اینجا فقط تصمیم می‌گیریم منو کشیده
 * شود یا نه.
 */

/** `key` همان کلیدِ صفحه در `features/panel/registry.ts` است؛ زبانه‌ی خاموش کشیده نمی‌شود. */
const TABS: { key: string; to: string; label: string; icon: IconName; end?: boolean }[] = [
  { key: "crm", to: "/admin", label: "CRM", icon: "users", end: true },
  { key: "marketing_report", to: "/admin/marketing", label: "گزارش بازاریابی", icon: "trending" },
  { key: "rewards", to: "/admin/rewards", label: "پاداش‌ها", icon: "wallet" },
  { key: "providers", to: "/admin/providers", label: "موتورهای AI", icon: "cpu" },
];

export default function AdminLayout() {
  const { user } = useAuth();
  const { pageEnabled } = useFlags();

  // کاربر غیرادمین که آدرس را دستی زده، به داشبورد خودش برمی‌گردد — نه
  // یک صفحه‌ی «دسترسی ندارید» که فقط می‌گوید اینجا چیزی هست.
  if (!user?.is_staff) return <Navigate to="/" replace />;

  return (
    <div className="u-rise space-y-5">
      <div>
        <h1 className="text-2xl font-extrabold" style={{ color: "var(--text)" }}>
          ابزارهای ادمین
        </h1>
        <p className="text-xs" style={{ color: "var(--text-3)" }}>
          این صفحه‌ها همه‌ی مشتری‌ها را با هم می‌بینند — فروشگاه‌دارها به آن‌ها دسترسی
          ندارند.
        </p>
      </div>

      <nav className="u-tabs">
        {TABS.filter((tab) => pageEnabled(tab.key)).map((tab) => (
          <NavLink
            key={tab.to}
            to={tab.to}
            end={tab.end}
            className={({ isActive }) => `u-tab ${isActive ? "active" : ""}`}
          >
            <span className="flex items-center gap-1.5">
              <Icon name={tab.icon} size={15} />
              {tab.label}
            </span>
          </NavLink>
        ))}
      </nav>

      <Outlet />
    </div>
  );
}

/** پیام مشترک وقتی سرور دسترسی را رد می‌کند با اینکه منو نشان داده شده. */
export function AdminDenied() {
  return (
    <Alert tone="bad" title="سرور این درخواست را رد کرد">
      حساب شما دیگر دسترسی ادمین ندارد. اگر فکر می‌کنید اشتباه است، یک بار خارج و
      دوباره وارد شوید.
    </Alert>
  );
}
