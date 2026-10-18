import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { Alert, Badge, Button, Card, Chip, Spinner, Table } from "../../../components/ui";
import { api, fa, pUrl, studioError } from "./api";
import { Loading, Mono, Pre, SectionHead } from "./common";
import { useProject } from "./shell";
import type { ImportReportResp } from "./types";

/** گزارشِ سازگاریِ پروژهٔ واردشده + محیطِ اجرا (وابستگی‌ها) */
export default function ImportReportPage() {
  const { slug, notify, build, building, buildCount } = useProject();
  const [data, setData] = useState<ImportReportResp | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [showUnsupported, setShowUnsupported] = useState(false);
  const [showLog, setShowLog] = useState<boolean | null>(null);

  const load = useCallback(async () => {
    try {
      const { data: d } = await api.get<ImportReportResp>(`/studio/projects/${slug}/import-report/`);
      setData(d);
      setError(null);
    } catch (err) {
      setError(studioError(err));
    }
  }, [slug]);

  useEffect(() => {
    void load();
  }, [load, buildCount]);

  // تا وقتی نصب در حالِ اجراست هر ۶ ثانیه تازه می‌شود (همان refresh ِ صفحهٔ قدیمی)
  useEffect(() => {
    if (data?.deps_status !== "running") return;
    const id = window.setInterval(() => void load(), 6000);
    return () => window.clearInterval(id);
  }, [data?.deps_status, load]);

  if (!data) return <Loading error={error} />;
  const { report, project: p } = data;
  const installed = data.data.settings?.installed_apps ?? [];
  const logOpen = showLog ?? (data.deps_status === "running" || data.deps_status === "failed");

  async function installDeps() {
    setBusy(true);
    try {
      const { data: d } = await api.post<{ message: string; started: boolean }>(`/studio/projects/${slug}/deps/`, {});
      notify(d.message, d.started ? "ok" : "info");
      await load();
    } catch (err) {
      notify(studioError(err), "bad");
    } finally {
      setBusy(false);
    }
  }

  const stats: [number, string, string | null][] = [
    [data.apps.length, "اپِ محلی", "backend"],
    [data.model_count, "مدل", "backend#er"],
    [data.route_count, "نشانی", "urls"],
    [data.pages.length, "قالب", "frontend"],
    [installed.length, "INSTALLED_APPS", null],
  ];

  return (
    <div className="space-y-4">
      <Card>
        <h2 className="text-lg font-extrabold" style={{ color: "var(--text)" }}>
          {report.level_display}
        </h2>
        <p className="mt-1 text-sm" style={{ color: "var(--text-2)" }}>
          ماژولِ تنظیمات <Mono>{p.settings_module || "—"}</Mono> · نشانی‌های ریشه <Mono>{p.urls_module || "—"}</Mono> · دیتابیس{" "}
          {data.data.settings?.db_engine || "—"}
        </p>
      </Card>

      <div className="u-stat-row grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-5">
        {stats.map(([value, label, sub], i) => {
          const inner = (
            <Card hover={sub !== null}>
              <div className="u-num text-2xl font-extrabold" style={{ color: "var(--text)" }}>
                {fa(value)}
              </div>
              <div className="mt-1 text-sm" style={{ color: "var(--text-2)" }}>
                {label}
              </div>
            </Card>
          );
          return sub ? (
            <Link key={i} to={pUrl(slug, sub)} className="no-underline">
              {inner}
            </Link>
          ) : (
            <div key={i}>{inner}</div>
          );
        })}
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card padded={false}>
          <div className="px-5 pt-5">
            <SectionHead title="شناخته شد" />
          </div>
          <Table>
            <thead>
              <tr>
                <th>اپ</th>
                <th>مدل</th>
                <th>ویو</th>
                <th>نشانی</th>
              </tr>
            </thead>
            <tbody>
              {data.apps.map((a) => (
                <tr key={a.id}>
                  <td>
                    <Link to={pUrl(slug, `app/${a.id}`)} className="font-mono" dir="ltr" style={{ color: "var(--brand-strong)" }}>
                      {a.dir}
                    </Link>
                    {a.managed && (
                      <span className="ms-1">
                        <Badge tone="ok">تازه (استودیو)</Badge>
                      </span>
                    )}
                  </td>
                  <td className="u-num">{fa(a.model_count ?? 0)}</td>
                  <td className="u-num">{fa(a.view_count ?? 0)}</td>
                  <td className="u-num">{fa(a.route_count ?? 0)}</td>
                </tr>
              ))}
            </tbody>
          </Table>
          <div className="px-5 pb-5">
            <SectionHead title={<span className="text-sm">INSTALLED_APPS</span>} />
            <div className="flex flex-wrap gap-1.5">
              {installed.map((x) => (
                <Chip key={x}>
                  <span dir="ltr" className="font-mono">
                    {x}
                  </span>
                </Chip>
              ))}
            </div>
          </div>
        </Card>

        <div className="space-y-4">
          <Card>
            <SectionHead title="هشدارها" hint={fa(report.warnings.length)} />
            {report.warnings.length === 0 ? (
              <p className="text-sm" style={{ color: "var(--text-3)" }}>
                هشداری نیست.
              </p>
            ) : (
              <div className="space-y-1.5">
                {report.warnings.map((w, i) => (
                  <Alert key={i} tone="warn">
                    {w}
                  </Alert>
                ))}
              </div>
            )}
          </Card>
          <Card>
            <SectionHead title="فقط نمایش / ناشناخته" hint={fa(report.unsupported.length)} />
            {report.unsupported.length === 0 ? (
              <p className="text-sm" style={{ color: "var(--text-3)" }}>
                همه‌چیز شناخته شد.
              </p>
            ) : (
              <>
                <Button variant="ghost" size="sm" onClick={() => setShowUnsupported(!showUnsupported)}>
                  {showUnsupported ? "بستن" : "فهرست را ببین"}
                </Button>
                {showUnsupported && (
                  <ul className="mt-2 list-disc ps-5 text-sm leading-7" style={{ color: "var(--text-2)" }}>
                    {report.unsupported.map((u, i) => (
                      <li key={i}>{u}</li>
                    ))}
                  </ul>
                )}
              </>
            )}
          </Card>
        </div>
      </div>

      <Card>
        <SectionHead
          title="محیطِ اجرا (وابستگی‌ها)"
          action={
            <>
              {data.own_env ? <Badge tone="ok">محیطِ جدا دارد (.venv)</Badge> : <Badge>با پایتونِ استودیو اجرا می‌شود</Badge>}
              {data.deps_status === "running" && (
                <Badge tone="brand">
                  <Spinner size={11} /> در حالِ نصب
                </Badge>
              )}
              {data.deps_status === "ok" && <Badge tone="ok">نصب شد</Badge>}
              {data.deps_status === "failed" && <Badge tone="bad">نصب خطا داد</Badge>}
            </>
          }
        />
        <p className="text-sm leading-7" style={{ color: "var(--text-3)" }}>
          اگر «تولیدِ کد» یا «پیش‌نمایش» خطای <Mono>ModuleNotFoundError</Mono> داد، یعنی بسته‌ای کم است. این دکمه داخلِ پوشهٔ
          همین پروژه یک <Mono>.venv</Mono> می‌سازد و <Mono>requirements.txt</Mono> را نصب می‌کند؛ از آن به بعد همین پروژه با
          محیطِ خودش اجرا می‌شود.
        </p>
        <div className="mt-3 flex flex-wrap gap-2">
          <Button onClick={installDeps} disabled={busy || data.deps_status === "running"}>
            {busy ? "…" : data.own_env ? "نصبِ دوباره" : "ساختِ محیطِ جدا و نصبِ وابستگی‌ها"}
          </Button>
          <Button variant="secondary" onClick={() => void build()} disabled={building}>
            {building ? "…" : "وارسی (check)"}
          </Button>
          <Link to={pUrl(slug, "preview")} className="no-underline">
            <Button variant="ghost">پیش‌نمایش{data.preview_running ? " (روشن)" : ""}</Button>
          </Link>
        </div>
        {data.deps_log && (
          <div className="mt-3">
            <Button variant="ghost" size="sm" onClick={() => setShowLog(!logOpen)}>
              {logOpen ? "بستنِ لاگِ نصب" : "لاگِ نصب"}
            </Button>
            {logOpen && (
              <div className="mt-2">
                <Pre text={data.deps_log} maxHeight={320} />
              </div>
            )}
          </div>
        )}
      </Card>
    </div>
  );
}
