import { useEffect, useState } from "react";
import { Link, Navigate, NavLink, Outlet, useLocation, useParams } from "react-router-dom";

import { api } from "../api/client";
import { useAuth } from "../features/auth/AuthContext";
import { useFlags } from "../features/panel/FlagsContext";
import { DASHBOARD, PAGES, SECTIONS, pageHref, type PanelPage } from "../features/panel/registry";
import Icon from "./Icon";
import NotificationsBell from "./NotificationsBell";
import ThemeToggle from "./ThemeToggle";
import UsageWidget from "./UsageWidget";
import { Spinner } from "./ui";

type Store = { id: number; name: string };

/**
 * منوی پنل از `features/panel/registry.ts` ساخته می‌شود — همان فهرستی که
 * سرور با کلیدهایش می‌گوید کدام صفحه روشن است.
 *
 * تا پیش از این، شش صفحه‌ی ساخته‌شده و تست‌شده — رقبا، فرصت‌های فروش،
 * صندوق پیام، کلیدهای API، ادیتور ویدیو و ترندها — در هیچ منویی نبودند.
 * مسیرشان در روتر بود و کاربر هیچ راهی به آن‌ها نداشت. قابلیتی که از
 * منو پیدا نشود، ساخته نشده است؛ فقط هزینه‌اش داده شده.
 *
 * گروه‌بندی برای همین است: هجده لینکِ پشت‌سرهم همان‌قدر پیدا نمی‌شود که
 * شش لینک و دوازده صفحه‌ی پنهان.
 *
 * حالا پنهان شدن فقط یک راه دارد: سوئیچِ ادمین ⇐ «صفحه‌های پنل». دسته‌ی
 * خاموش کلِ گروهش را می‌برد، صفحه‌ی خاموش فقط آیتمش را.
 */

/** ادمینِ جنگو سشن می‌خواهد نه JWT: یک فرمِ پنهان توکنِ فعلی را به پلِ ورود
 *  می‌فرستد (POST /auth/session/) و همان‌جا به /admin/ می‌رود. */
export function openTool(path: string) {
  const token = localStorage.getItem("access") || "";
  const form = document.createElement("form");
  form.method = "POST";
  form.action = "/api/v1/auth/session/";
  form.target = "_blank";
  for (const [k, v] of Object.entries({ token, next: path })) {
    const input = document.createElement("input");
    input.type = "hidden";
    input.name = k;
    input.value = v;
    form.appendChild(input);
  }
  document.body.appendChild(form);
  form.submit();
  form.remove();
}

export default function Layout() {
  const { user, loading, logout } = useAuth();
  const { pageEnabled, sectionEnabled } = useFlags();
  const location = useLocation();
  const params = useParams();
  const [stores, setStores] = useState<Store[]>([]);
  const [open, setOpen] = useState(false);

  // the store in the URL wins; otherwise remember the last one used so a
  // refresh on the dashboard still shows the right sidebar
  const urlStore = params.id && location.pathname.startsWith("/stores/") ? params.id : null;
  const [activeStore, setActiveStore] = useState<string | null>(
    urlStore ?? localStorage.getItem("last-store"),
  );

  useEffect(() => {
    if (urlStore) {
      setActiveStore(urlStore);
      localStorage.setItem("last-store", urlStore);
    }
  }, [urlStore]);

  useEffect(() => {
    if (!user) return;
    api
      .get("/stores/")
      .then(({ data }) => setStores(data.results ?? data ?? []))
      .catch(() => setStores([]));
  }, [user]);

  useEffect(() => setOpen(false), [location.pathname]);

  /**
   * گروه‌های منو تاشو‌اند.
   *
   * منو ۲۷ آیتم دارد و فقط بیشتر می‌شود. روی گوشی ۱۶۱۰ پیکسل بود — دو
   * صفحه اسکرول تا «خروج». ولی پنهان کردنِ پیش‌فرضِ آیتم‌ها همان خطایی
   * است که شش صفحه را یک دوره نامرئی کرده بود، پس:
   *
   *   • **گروهی که صفحه‌ی فعلی در آن است همیشه باز است** — هیچ‌وقت
   *     جایی نیستی که منو نشان ندهد کجایی.
   *   • دسکتاپ پیش‌فرض همه‌باز است (سایدبار چسبان است و خودش اسکرول
   *     می‌شود)؛ کشوی موبایل پیش‌فرض فقط گروه فعلی را باز می‌کند.
   *   • سرِ گروه همیشه دیده می‌شود، پس بسته بودن یعنی «یک لمس دورتر»،
   *     نه «نیست».
   *   • انتخاب کاربر به‌ازای هر گروه ذخیره می‌شود و بر پیش‌فرض می‌چربد.
   */
  const [groupChoice, setGroupChoice] = useState<Record<string, boolean>>(() => {
    try {
      return JSON.parse(localStorage.getItem("nav-groups") || "{}");
    } catch {
      return {};
    }
  });

  const toggleGroup = (group: string, next: boolean) => {
    setGroupChoice((prev) => {
      const updated = { ...prev, [group]: next };
      try {
        localStorage.setItem("nav-groups", JSON.stringify(updated));
      } catch {
        /* حالت خصوصی — انتخاب فقط تا رفرش می‌ماند */
      }
      return updated;
    });
  };

  // Escape می‌بندد، و تا کشو باز است صفحه‌ی زیرش اسکرول نمی‌شود — وگرنه
  // کشیدن انگشت روی منو، صفحه‌ی پشتش را جابه‌جا می‌کرد.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    window.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = prev;
      window.removeEventListener("keydown", onKey);
    };
  }, [open]);

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <Spinner size={30} />
      </div>
    );
  }
  if (!user) return <Navigate to="/login" replace />;

  /**
   * گروه‌های سایدبار: دسته‌های فهرست، به همان ترتیب.
   *
   *   • دسته‌های وابسته به فروشگاه فقط وقتی فروشگاهی فعال است.
   *   • ادمین و ابزارها فقط برای کارکنان. بدون این دو گروه، صفحه‌های
   *     `/admin/*` و `/tools/*` فقط با تایپ دستی آدرس پیدا می‌شدند — همان
   *     اشتباهی که قبلاً شش صفحه‌ی فروشگاه را نامرئی کرده بود.
   *   • دسته‌ی خاموش کل گروه را می‌برد؛ صفحه‌ی خاموش فقط آیتمش را. گروهی
   *     که آیتمی برایش نماند، سرش هم کشیده نمی‌شود.
   */
  const canSee = (staffOnly: boolean | undefined) => !staffOnly || !!user.is_staff;
  const groups = SECTIONS.filter(
    (s) => s.menu !== false && canSee(s.staffOnly) && sectionEnabled(s.key) && (!s.storeScoped || activeStore),
  )
    .map((section) => ({
      section,
      items: PAGES.filter(
        (p) => p.section === section.key && p.menu !== false && canSee(p.staffOnly) && pageEnabled(p.key),
      ),
    }))
    .filter(({ items }) => items.length > 0);

  const isCurrent = (page: PanelPage) => {
    if (page.external) return false;
    const path = pageHref(page, activeStore);
    return page.end
      ? location.pathname === path
      : location.pathname === path || location.pathname.startsWith(path + "/");
  };
  const activeGroup = groups.find(({ items }) => items.some(isCurrent))?.section.title;

  const isGroupOpen = (group: string, inDrawer: boolean) => {
    if (group === activeGroup) return true;
    if (group in groupChoice) return groupChoice[group];
    return !inDrawer;
  };

  const renderSidebar = (inDrawer: boolean) => (
    <aside
      className="u-glass flex h-full w-64 shrink-0 flex-col gap-0.5 overflow-y-auto overscroll-contain p-3.5"
      style={{ borderInlineStart: "1px solid var(--line)" }}
    >
      <Link
        to="/"
        className="mb-4 flex items-center gap-2.5 px-2 py-1 no-underline"
        style={{ color: "#fff" }}
      >
        <span
          className="grid h-8 w-8 place-items-center rounded-xl"
          style={{
            background: "linear-gradient(135deg, var(--aurora-1), var(--aurora-3))",
            boxShadow: "0 4px 16px -4px var(--aurora-1)",
          }}
        >
          <Icon name="sparkle" size={17} strokeWidth={2} />
        </span>
        <span className="text-lg font-extrabold">آپ‌مارکت</span>
      </Link>

      {stores.length > 0 && (
        <select
          value={activeStore ?? ""}
          onChange={(e) => {
            const id = e.target.value;
            setActiveStore(id);
            localStorage.setItem("last-store", id);
            window.location.href = `/panel/stores/${id}`;
          }}
          className="u-input mb-2"
          style={{
            background: "rgb(255 255 255 / .06)",
            color: "#e6ecfb",
            borderColor: "rgb(255 255 255 / .12)",
          }}
          aria-label="انتخاب فروشگاه"
        >
          {stores.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name}
            </option>
          ))}
        </select>
      )}

      {pageEnabled(DASHBOARD.key) && (
        <NavLink
          to={pageHref(DASHBOARD, null)}
          end={DASHBOARD.end}
          className={({ isActive }) => `u-nav-item ${isActive ? "active" : ""}`}
        >
          <Icon name={DASHBOARD.icon} />
          {DASHBOARD.label}
        </NavLink>
      )}

      {groups.map(({ section, items }) => {
        const open = isGroupOpen(section.title, inDrawer);
        return (
          <div key={section.key}>
            {/* همه‌ی گروه‌ها — ادمین هم — تاشو با یک دکمه سرشان؛ روی گوشی
                آیتم‌های یک گروهِ همیشه‌باز جا می‌گرفتند. */}
            <button
              type="button"
              className="u-nav-group"
              onClick={() => toggleGroup(section.title, !open)}
              aria-expanded={open}
            >
              <span>{section.title}</span>
              <Icon name={open ? "up" : "down"} size={13} />
            </button>
            {open &&
              items.map((item) =>
                item.external ? (
                  /* صفحه‌ی جنگو: با پلِ ورود در زبانه‌ی تازه باز می‌شود. */
                  <button
                    key={item.key}
                    type="button"
                    className="u-nav-item w-full text-start"
                    onClick={() => openTool(pageHref(item, activeStore))}
                  >
                    <Icon name={item.icon} />
                    {item.label}
                  </button>
                ) : (
                  <NavLink
                    key={item.key}
                    to={pageHref(item, activeStore)}
                    end={item.end}
                    className={({ isActive }) => `u-nav-item ${isActive ? "active" : ""}`}
                  >
                    <Icon name={item.icon} />
                    {item.label}
                  </NavLink>
                ),
              )}
          </div>
        );
      })}

      <div className="mt-auto pt-4">
        {activeStore && <UsageWidget storeId={activeStore} />}
        <div
          className="mt-2.5 flex items-center gap-2 rounded-xl px-3 py-2"
          style={{ background: "rgb(255 255 255 / .05)", border: "1px solid var(--line)" }}
        >
          <span
            className="grid h-7 w-7 shrink-0 place-items-center rounded-lg text-xs font-bold"
            style={{ background: "var(--brand-soft)", color: "var(--brand-strong)" }}
          >
            {user.username.slice(0, 2)}
          </span>
          <span className="min-w-0 flex-1 truncate text-sm" style={{ color: "var(--sidebar-fg)" }}>
            {user.username}
          </span>
          <button
            onClick={logout}
            className="u-btn u-btn-ghost u-btn-sm"
            style={{ color: "var(--bad)", padding: 6 }}
            aria-label="خروج"
            title="خروج"
          >
            <Icon name="logout" size={16} />
          </button>
        </div>
      </div>
    </aside>
  );

  return (
    <div className="flex" style={{ minHeight: "100dvh" }}>
      {/* چسبان با ارتفاع صفحه و اسکرول مستقل: روی لپ‌تاپ ۸۰۰ پیکسلی
          سایدبار ۱۶۱۰ پیکسل بود و با صفحه اسکرول می‌شد — برای رسیدن به
          «خروج» باید کل محتوا را پایین می‌رفتی، و در صفحه‌ی بلند منو از
          دید خارج می‌شد. */}
      <div className="sticky top-0 hidden h-[100dvh] self-start lg:flex">{renderSidebar(false)}</div>

      {open && (
        <div
          className="fixed inset-0 z-40 flex lg:hidden"
          role="dialog"
          aria-modal="true"
          aria-label="منو"
        >
          <div
            className="absolute inset-0"
            style={{ background: "rgb(2 4 10 / .7)" }}
            onClick={() => setOpen(false)}
          />
          {/* `u-drawer` کشو را روی موبایل مات می‌کند — شیشه روی خود محتوا،
              دو لایه متن روی هم می‌ساخت. ارتفاعش به صفحه بسته است و خودش
              اسکرول می‌شود، تا آیتم‌های پایین منو روی گوشی کوتاه از دست
              نروند. */}
          <div className="u-drawer relative z-10 flex h-[100dvh] u-rise">
            {renderSidebar(true)}
            {/* بستن با دکمه، نه فقط با زدن بیرون — کسی که نمی‌داند
                پس‌زمینه‌ی تیره قابل لمس است، راه خروجی نمی‌بیند. */}
            <button
              onClick={() => setOpen(false)}
              className="u-btn u-btn-ghost absolute top-3"
              style={{ insetInlineEnd: 10, padding: 9 }}
              aria-label="بستن منو"
            >
              <Icon name="x" size={18} />
            </button>
          </div>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <header
          className="u-glass sticky top-0 z-30 flex items-center gap-3 px-4 py-2.5"
          style={{ borderBottom: "1px solid var(--line)", background: "transparent" }}
        >
          {/* `lg:hidden` روی خودِ دکمه کار نمی‌کرد: `.u-btn` بیرون از لایه‌هاست
              و `display` را پس می‌گرفت، پس همبرگر روی دسکتاپ هم دیده می‌شد.
              پوششی که فقط پنهان‌شدن را به عهده دارد، چیزی برای شکست‌خوردن
              ندارد. */}
          <span className="lg:hidden">
            <button
              onClick={() => setOpen(true)}
              className="u-btn u-btn-ghost u-btn-sm"
              aria-label="منو"
            >
              <Icon name="menu" />
            </button>
          </span>
          <div className="mr-auto flex items-center gap-1.5">
            <ThemeToggle />
            <NotificationsBell />
          </div>
        </header>

        <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
