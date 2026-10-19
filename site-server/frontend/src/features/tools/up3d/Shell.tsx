import { NavLink, Navigate, Outlet } from "react-router-dom";

import Icon, { type IconName } from "../../../components/Icon";
import { openTool } from "../../../components/Layout";
import { Badge } from "../../../components/ui";
import { useAuth } from "../../auth/AuthContext";
import { P, fa } from "./api";
import { ToastProvider, useStatus } from "./shared";

/**
 * قابِ بخشِ سه‌بعدی: عنوان + نوارِ زیرصفحه‌ها (همان منوی بالای پنلِ قدیمی) + شمارنده‌های زنده.
 *
 * این نگهبان ناوبری است نه امنیت: هر اندپوینت سمتِ سرور `IsAdminUser` را دوباره چک می‌کند.
 */
const TABS: { to: string; label: string; icon: IconName; end?: boolean; count?: "jobs" | "workers" }[] = [
  { to: P.dashboard(), label: "داشبورد", icon: "dashboard", end: true },
  { to: P.newProject(), label: "پروژهٔ تازه", icon: "plus" },
  { to: P.jobs(), label: "کارها", icon: "clock", count: "jobs" },
  { to: P.assets(), label: "کتابخانهٔ دارایی‌ها", icon: "box" },
  { to: P.workers(), label: "کارگرها", icon: "cpu", count: "workers" },
  { to: P.docs(), label: "راهنما و API", icon: "info" },
  { to: P.token(), label: "توکنِ API", icon: "key" },
];

export default function Shell() {
  const { user } = useAuth();
  const status = useStatus(15000);

  if (!user?.is_staff) return <Navigate to="/" replace />;

  return (
    <ToastProvider>
      <div className="u-rise space-y-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <span
              className="grid h-9 w-9 place-items-center rounded-xl text-xs font-black"
              style={{
                background: "conic-gradient(from 210deg, #f0b54a, #f97362, #6aa9ff, #3ecf8e, #f0b54a)",
                color: "#111",
              }}
            >
              3D
            </span>
            <div>
              <h1 className="text-xl font-extrabold" style={{ color: "var(--text)" }}>
                ویدیوی سه‌بعدی
              </h1>
              <p className="text-xs" style={{ color: "var(--text-3)" }}>
                از یک جمله تا یک تبلیغِ سه‌بعدیِ کامل — کارگردانِ هوشِ مصنوعی، موتورِ Blender، صدای فارسی
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={() => openTool("/admin/up3d/")}
            className="u-btn u-btn-ghost u-btn-sm"
            title="تنظیماتِ هوشِ مصنوعی و صدا در جنگو ادمین"
          >
            <Icon name="settings" size={15} />
            تنظیمات (ادمین)
          </button>
        </div>

        <nav className="u-tabs">
          {TABS.map((tab) => (
            <NavLink key={tab.to} to={tab.to} end={tab.end} className={({ isActive }) => `u-tab ${isActive ? "active" : ""}`}>
              <span className="flex items-center gap-1.5">
                <Icon name={tab.icon} size={15} />
                {tab.label}
                {tab.count === "jobs" && status && status.active_jobs > 0 && <Badge tone="brand">{fa(status.active_jobs)}</Badge>}
                {tab.count === "workers" && status && (
                  <Badge tone={status.workers_online ? "ok" : "bad"}>{fa(status.workers_online)}</Badge>
                )}
              </span>
            </NavLink>
          ))}
        </nav>

        <Outlet />
      </div>
    </ToastProvider>
  );
}
