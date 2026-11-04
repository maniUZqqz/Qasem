import { NavLink, Navigate, Outlet } from "react-router-dom";

import Icon, { type IconName } from "../../components/Icon";
import { useAuth } from "../auth/AuthContext";
import { useFlags } from "../panel/FlagsContext";
import { MetaProvider } from "./MetaContext";

/**
 * The «جذب مشتری» frame: a title and sub-page tabs. Staff only - the server checks again on every call;
 * this guard only decides what is drawn. A tab whose panel page is switched off in the Django admin
 * (صفحه‌های پنل) disappears.
 */
const TABS: { key: string; to: string; label: string; icon: IconName; end?: boolean }[] = [
  { key: "growth_dashboard", to: "/growth", label: "داشبورد", icon: "chart", end: true },
  { key: "growth_discovery", to: "/growth/discovery", label: "کشف مشتری", icon: "search" },
  { key: "growth_leads", to: "/growth/leads", label: "دیتابیس لیدها", icon: "users" },
  { key: "growth_outreach", to: "/growth/outreach", label: "پیام‌رسانی", icon: "send" },
  { key: "growth_templates", to: "/growth/templates", label: "قالب‌های پیام", icon: "file" },
  { key: "growth_suppression", to: "/growth/do-not-contact", label: "تماس نگیر", icon: "ban" },
  { key: "growth_settings", to: "/growth/settings", label: "تنظیمات", icon: "settings" },
];

export default function GrowthLayout() {
  const { user } = useAuth();
  const { pageEnabled } = useFlags();
  if (!user?.is_staff) return <Navigate to="/" replace />;

  return (
    <MetaProvider>
      <div className="u-rise space-y-5" data-testid="growth-root">
        <div>
          <h1 className="text-2xl font-extrabold" style={{ color: "var(--text)" }}>
            جذب مشتری
          </h1>
          <p className="text-xs" style={{ color: "var(--text-3)" }}>
            ابزارِ داخلیِ آپ‌مارکت برای پیدا کردنِ کسب‌وکارها، جمع‌کردنِ راهِ تماسشان و پیام‌رسانی. فقط کارکنان.
          </p>
        </div>

        <nav className="u-tabs" style={{ overflowX: "auto" }}>
          {TABS.filter((tab) => pageEnabled(tab.key)).map((tab) => (
            <NavLink key={tab.to} to={tab.to} end={tab.end} className={({ isActive }) => `u-tab ${isActive ? "active" : ""}`}>
              <span className="flex items-center gap-1.5 whitespace-nowrap">
                <Icon name={tab.icon} size={15} />
                {tab.label}
              </span>
            </NavLink>
          ))}
        </nav>

        <Outlet />
      </div>
    </MetaProvider>
  );
}
