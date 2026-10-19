import { useCallback, useEffect, useState } from "react";
import { Link, NavLink, Outlet, useLocation, useOutletContext, useParams } from "react-router-dom";

import Icon, { type IconName } from "../../../components/Icon";
import { Alert, Badge, Button } from "../../../components/ui";
import { api, BASE, downloadZip, pUrl, studioError } from "./api";
import { Loading, Pre, statusTone, type Tone } from "./common";
import type { BuildResp, ProjectDetail, ProjectDetailResp } from "./types";

/**
 * قابِ سایت‌ساز.
 *
 * سایدبارِ خودِ پنل سرِ جایش می‌ماند؛ این‌جا فقط دو ردیفِ ناوبریِ خودِ ابزار
 * اضافه می‌شود — همان دو بخشی که سایدبارِ استودیوی قدیمی داشت:
 *   · «استودیو»: پروژه‌ها، پروژهٔ تازه، واردکردن، تنظیماتِ هوشِ مصنوعی
 *   · «پروژه»: نمای کلی، تنظیمات، اپ‌ها و مدل‌ها، نشانی‌ها، فرانت، AI، فایل‌ها،
 *     تاریخچه، پیش‌نمایش — به‌علاوهٔ دکمهٔ «تولیدِ کد» که در هر صفحهٔ پروژه بود.
 */

const STUDIO_NAV: { to: string; label: string; icon: IconName; end?: boolean }[] = [
  { to: BASE, label: "پروژه‌ها", icon: "dashboard", end: true },
  { to: `${BASE}/new`, label: "پروژهٔ تازه", icon: "plus" },
  { to: `${BASE}/import`, label: "واردکردنِ پروژهٔ جنگو", icon: "upload" },
  { to: `${BASE}/ai/settings`, label: "تنظیماتِ هوشِ مصنوعی", icon: "sparkle" },
];

export default function StudioShell() {
  const location = useLocation();
  const inProject = /\/p\/[^/]+/.test(location.pathname);
  return (
    <div className="u-rise space-y-5">
      {!inProject && (
        <>
          <div>
            <h1 className="text-2xl font-extrabold" style={{ color: "var(--text)" }}>
              سایت‌ساز
            </h1>
            <p className="mt-1 text-sm" style={{ color: "var(--text-3)" }}>
              هر پروژه یک سایتِ جنگوی واقعی است و بدونِ استودیو هم اجرا می‌شود.
            </p>
          </div>
          <nav className="u-tabs">
            {STUDIO_NAV.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) => `u-tab ${isActive ? "active" : ""}`}
              >
                <span className="flex items-center gap-1.5">
                  <Icon name={item.icon} size={15} />
                  {item.label}
                </span>
              </NavLink>
            ))}
          </nav>
        </>
      )}
      <Outlet />
    </div>
  );
}

/* ------------------------------------------------------------ پروژه */

type NoticeT = { text: string; tone: Tone; at: number };

export type ProjectCtx = {
  project: ProjectDetail;
  slug: string;
  reload: () => Promise<void>;
  setProject: (p: ProjectDetail) => void;
  /** پیامِ یک‌بارمصرف (همان messages ِ جنگو) — تا صفحهٔ بعدی می‌ماند */
  notify: (text: string, tone?: Tone) => void;
  build: () => Promise<boolean>;
  building: boolean;
  /** هر «تولیدِ کد» یکی بالا می‌رود تا صفحه‌ها خودشان را تازه کنند */
  buildCount: number;
};

export function useProject(): ProjectCtx {
  return useOutletContext<ProjectCtx>();
}

const PROJECT_TABS: { sub: string; label: string; icon: IconName; also?: string[]; imported?: boolean }[] = [
  { sub: "", label: "نمای کلی", icon: "dashboard" },
  { sub: "import-report", label: "گزارشِ سازگاری", icon: "shield", imported: true },
  { sub: "settings", label: "تنظیمات", icon: "settings" },
  { sub: "backend", label: "اپ‌ها و مدل‌ها", icon: "box", also: ["app", "model", "field"] },
  { sub: "urls", label: "نشانی‌ها و ویوها", icon: "link", also: ["view"] },
  { sub: "frontend", label: "فرانت · صفحه‌ها", icon: "image", also: ["page", "shared"] },
  { sub: "ai", label: "هوشِ مصنوعی", icon: "sparkle" },
  { sub: "files", label: "فایل‌ها (کدِ واقعی)", icon: "receipt" },
  { sub: "history", label: "تاریخچهٔ نسخه‌ها", icon: "clock" },
  { sub: "preview", label: "پیش‌نمایشِ زنده", icon: "play" },
];

export function ProjectShell() {
  const { slug = "" } = useParams<{ slug: string }>();
  const location = useLocation();
  const [project, setProject] = useState<ProjectDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<NoticeT | null>(null);
  const [building, setBuilding] = useState(false);
  const [buildCount, setBuildCount] = useState(0);
  const [buildDetail, setBuildDetail] = useState<string | null>(null);
  const [downloading, setDownloading] = useState(false);

  const reload = useCallback(async () => {
    try {
      const { data } = await api.get<ProjectDetailResp>(`/studio/projects/${slug}/`);
      setProject(data.project);
      setError(null);
    } catch (err) {
      setError(studioError(err));
    }
  }, [slug]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const notify = useCallback((text: string, tone: Tone = "ok") => {
    setNotice({ text, tone, at: Date.now() });
  }, []);

  // پیام تا صفحهٔ بعدی می‌ماند (مثلِ پیامِ جنگو بعد از redirect) و با ناوبریِ بعدی پاک می‌شود
  useEffect(() => {
    setNotice((n) => (n && Date.now() - n.at > 1000 ? null : n));
  }, [location.pathname]);

  // صفحه‌هایی که بیرونِ این قاب‌اند (ساختِ پروژه، واردکردن) پیامشان را با state ِ روتر می‌فرستند
  useEffect(() => {
    const st = location.state as { notice?: { text: string; tone?: Tone } } | null;
    if (st?.notice?.text) setNotice({ text: st.notice.text, tone: st.notice.tone ?? "ok", at: Date.now() });
  }, [location.state]);

  const build = useCallback(async () => {
    setBuilding(true);
    try {
      const { data } = await api.post<BuildResp>(`/studio/projects/${slug}/build/`, {});
      setProject(data.project);
      setBuildDetail(data.ok ? null : data.detail);
      notify(data.message, data.ok ? "ok" : "bad");
      setBuildCount((c) => c + 1);
      return data.ok;
    } catch (err) {
      notify(studioError(err), "bad");
      return false;
    } finally {
      setBuilding(false);
    }
  }, [slug, notify]);

  // همان ZIPِ «نمای کلی» (GET …/export/) — این‌جا کنارِ «تولیدِ کد» تا در هر صفحهٔ پروژه دمِ دست باشد
  const download = useCallback(async () => {
    setDownloading(true);
    try {
      await downloadZip(slug, false);
    } catch (err) {
      notify(err instanceof Error ? err.message : studioError(err), "bad");
    } finally {
      setDownloading(false);
    }
  }, [slug, notify]);

  if (!project) return <Loading error={error} />;

  const rest = location.pathname.slice(pUrl(slug).length).replace(/^\//, "").split("/")[0] ?? "";

  const ctx: ProjectCtx = { project, slug, reload, setProject, notify, build, building, buildCount };

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-3">
        <div className="min-w-0 flex-1">
          <Link to={BASE} className="u-back">
            <Icon name="back" size={15} />
            پروژه‌ها
          </Link>
          <h1 className="mt-1 truncate text-2xl font-extrabold" style={{ color: "var(--text)" }}>
            {project.name}
          </h1>
          <div className="mt-1 flex flex-wrap items-center gap-2 text-sm" style={{ color: "var(--text-3)" }}>
            <code dir="ltr" className="font-mono text-xs">
              {project.slug}
            </code>
            {project.is_imported && <Badge tone="brand">واردشده</Badge>}
            <Badge tone={statusTone(project.status)}>
              <Icon name={project.status === "generated" ? "ok" : project.status === "error" ? "warn" : "clock"} size={12} />
              {project.status_display}
            </Badge>
          </div>
        </div>
        <Button
          onClick={() => void build()}
          disabled={building}
          title="تعریف‌ها ⇒ فایل‌های واقعیِ جنگو + وارسی + ثبتِ نسخه"
        >
          <Icon name="play" size={15} />
          {building ? "در حالِ تولید…" : "تولیدِ کد"}
        </Button>
        <Button
          onClick={() => void download()}
          disabled={downloading || !project.exists_on_disk}
          title={
            project.exists_on_disk
              ? "دانلودِ ZIPِ کاملِ پروژه — با run.bat (ویندوز) و run.sh (لینوکس/مک) که خودشان همه‌چیز را راه می‌اندازند"
              : "اول «تولیدِ کد» را بزن"
          }
          style={{
            background: "linear-gradient(135deg, var(--ok), color-mix(in srgb, var(--ok) 70%, #065f46))",
            color: "#fff",
            boxShadow: "0 6px 20px -8px color-mix(in srgb, var(--ok) 85%, transparent)",
          }}
        >
          <Icon name="download" size={15} />
          {downloading ? "در حالِ آماده‌سازی…" : "دانلود"}
        </Button>
      </div>

      {notice && (
        <Alert
          tone={notice.tone}
          action={
            <Button variant="ghost" size="sm" onClick={() => setNotice(null)} aria-label="بستن">
              <Icon name="x" size={14} />
            </Button>
          }
        >
          {notice.text}
        </Alert>
      )}
      {buildDetail && (
        <div className="u-card p-4" style={{ borderColor: "color-mix(in srgb, var(--bad) 45%, transparent)" }}>
          <div className="mb-2 flex flex-wrap items-center gap-2">
            <b style={{ color: "var(--bad)" }}>تولید/وارسی خطا داد</b>
            <span className="text-xs" style={{ color: "var(--text-3)" }}>
              خطا معمولاً از یک فیلد یا کدِ دستی است؛ همان را درست کن و دوباره «تولیدِ کد».
            </span>
            <Button variant="ghost" size="sm" className="ms-auto" onClick={() => setBuildDetail(null)}>
              بستن
            </Button>
          </div>
          <Pre text={buildDetail} maxHeight={300} />
        </div>
      )}

      <nav className="u-tabs">
        {PROJECT_TABS.filter((t) => !t.imported || project.is_imported).map((t) => {
          const active = rest === t.sub || (t.also?.includes(rest) ?? false);
          return (
            <Link key={t.sub} to={pUrl(slug, t.sub)} className={`u-tab ${active ? "active" : ""}`}>
              <span className="flex items-center gap-1.5">
                <Icon name={t.icon} size={15} />
                {t.label}
              </span>
            </Link>
          );
        })}
      </nav>

      <Outlet context={ctx} />
    </div>
  );
}
