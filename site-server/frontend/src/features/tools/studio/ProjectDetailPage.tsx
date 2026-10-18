import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import Icon from "../../../components/Icon";
import { Badge, Button, Card, Chip, EmptyState, Table } from "../../../components/ui";
import { api, BASE, downloadZip, fa, fmtDate, pUrl, studioError, truncate } from "./api";
import { Help, KV, Loading, Mono, Pre, proposalTone, SectionHead } from "./common";
import { useProject } from "./shell";
import type { BuildResp, ProjectDetailResp } from "./types";

/** نمای کلیِ پروژه */
export default function ProjectDetailPage() {
  const { slug, build, building, notify, setProject, buildCount } = useProject();
  const navigate = useNavigate();
  const [data, setData] = useState<ProjectDetailResp | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [migrating, setMigrating] = useState(false);
  const [askDelete, setAskDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [openBuild, setOpenBuild] = useState<number | null>(null);

  const load = useCallback(async () => {
    try {
      const { data: d } = await api.get<ProjectDetailResp>(`/studio/projects/${slug}/`);
      setData(d);
      setError(null);
    } catch (err) {
      setError(studioError(err));
    }
  }, [slug]);

  useEffect(() => {
    void load();
  }, [load, buildCount]);

  async function migrate() {
    setMigrating(true);
    try {
      const { data: d } = await api.post<BuildResp>(`/studio/projects/${slug}/migrate/`, {});
      setProject(d.project);
      notify(d.message, d.ok ? "ok" : "bad");
      await load();
    } catch (err) {
      notify(studioError(err), "bad");
    } finally {
      setMigrating(false);
    }
  }

  async function zip(withGit: boolean) {
    try {
      await downloadZip(slug, withGit);
    } catch (err) {
      notify(err instanceof Error ? err.message : studioError(err), "bad");
    }
  }

  async function remove() {
    setDeleting(true);
    try {
      const { data: d } = await api.delete<{ message: string }>(`/studio/projects/${slug}/`);
      navigate(BASE, { state: { notice: { text: d.message } } });
    } catch (err) {
      notify(studioError(err), "bad");
      setDeleting(false);
    }
  }

  if (!data) return <Loading error={error} />;
  const p = data.project;
  const pageWord = p.is_imported ? "قالب" : "صفحه";

  const stats: [number, string, string][] = [
    [data.apps.length, "اپ", "backend"],
    [data.model_count, `مدل · ${fa(data.field_count)} فیلد`, "backend"],
    [data.view_count, "ویو", "urls"],
    [data.route_count, "نشانی (URL)", "urls"],
    [data.pages.length, pageWord, "frontend"],
    [data.file_count, "فایل", "files"],
  ];

  return (
    <div className="space-y-5">
      <div className="u-stat-row grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-6">
        {stats.map(([value, label, sub], i) => (
          <Link key={i} to={pUrl(slug, sub)} className="no-underline">
            <Card hover>
              <div className="u-num text-2xl font-extrabold" style={{ color: "var(--text)" }}>
                {fa(value)}
              </div>
              <div className="mt-1 text-sm" style={{ color: "var(--text-2)" }}>
                {label}
              </div>
            </Card>
          </Link>
        ))}
      </div>

      {p.last_error && (
        <Card>
          <SectionHead
            tone="bad"
            title="آخرین تولید/وارسی خطا داد"
            hint="خطا معمولاً از یک فیلد یا کدِ دستی است؛ همان را درست کن و دوباره «تولیدِ کد»."
          />
          <Pre text={p.last_error} maxHeight={320} />
        </Card>
      )}

      <div className="grid gap-5 lg:grid-cols-2">
        <Card>
          <SectionHead
            title="وضعیت و عملیات"
            action={
              <>
                <Badge tone={p.exists_on_disk ? "ok" : "warn"}>{p.exists_on_disk ? "روی دیسک هست" : "هنوز تولید نشده"}</Badge>
                {p.is_imported && (
                  <Link to={pUrl(slug, "import-report")} className="no-underline">
                    <Badge tone="brand">واردشده · گزارش</Badge>
                  </Link>
                )}
              </>
            }
          />
          <KV
            rows={[
              ["شناسه", <Mono key="s">{p.slug}</Mono>],
              ["پوشه", <Mono key="p">{p.path}</Mono>],
              ["تنظیمات", <Mono key="m">{p.settings_module_name}</Mono>],
              [
                "رنگِ برند",
                <span key="c" className="inline-flex items-center gap-2">
                  <i className="inline-block h-3.5 w-3.5 rounded" style={{ background: p.brand_color }} />
                  <Mono>{p.brand_color}</Mono>
                </span>,
              ],
              ["آخرین تولید", fmtDate(p.generated_at)],
              [
                "پیش‌نمایش",
                data.preview_url ? (
                  <a key="u" href={data.preview_url} target="_blank" rel="noreferrer" dir="ltr" style={{ color: "var(--brand-strong)" }}>
                    {data.preview_url}
                  </a>
                ) : (
                  <span key="u" style={{ color: "var(--text-3)" }}>
                    خاموش
                  </span>
                ),
              ],
            ]}
          />
          <div className="mt-4 flex flex-wrap gap-2">
            <Button onClick={() => void build()} disabled={building}>
              <Icon name="play" size={15} />
              {building ? "در حالِ تولید…" : "تولیدِ کد"}
            </Button>
            <Button variant="secondary" onClick={migrate} disabled={migrating} title="makemigrations + migrate روی دیتابیسِ همین پروژه">
              {migrating ? "در حالِ مهاجرت…" : "ساخت و اجرای مهاجرت"}
            </Button>
            <Link to={pUrl(slug, "preview")} className="no-underline">
              <Button variant="ghost">پیش‌نمایشِ زنده</Button>
            </Link>
          </div>

          <SectionHead title={<span className="text-sm">خروجی (کدِ کامل)</span>} />
          <div className="flex flex-wrap gap-2">
            <Button variant="secondary" onClick={() => void zip(false)}>
              <Icon name="download" size={15} />
              دانلودِ ZIP
            </Button>
            <Button variant="ghost" onClick={() => void zip(true)} title="همراهِ پوشهٔ .git و همهٔ نسخه‌ها">
              ZIP با تاریخچهٔ Git
            </Button>
          </div>
          <Help>
            خروجی یک پروژهٔ کاملِ جنگوست: <Mono>pip install -r requirements.txt</Mono> ⇒ <Mono>migrate</Mono> ⇒{" "}
            <Mono>runserver</Mono>. دستورها در README ِ خودِ پروژه هست.
          </Help>

          <div className="mt-4 border-t pt-3" style={{ borderColor: "var(--line)" }}>
            {!askDelete ? (
              <Button variant="danger" size="sm" onClick={() => setAskDelete(true)}>
                حذفِ پروژه…
              </Button>
            ) : (
              <div className="space-y-2">
                <p className="text-sm font-bold" style={{ color: "var(--bad)" }}>
                  حذفِ پروژه
                </p>
                <p className="text-sm" style={{ color: "var(--text-2)" }}>
                  پروژهٔ «{p.name}» با همهٔ اپ‌ها، مدل‌ها، صفحه‌ها و پوشه‌اش روی دیسک حذف شود؟
                </p>
                <p className="text-xs" style={{ color: "var(--text-3)" }}>
                  پوشهٔ <Mono>{p.path}</Mono> هم از دیسک پاک می‌شود. برگشت‌پذیر نیست — اگر لازم داری، اول ZIP بگیر.
                </p>
                <div className="flex gap-2">
                  <Button variant="danger" onClick={remove} disabled={deleting}>
                    {deleting ? "…" : "بله، حذف کن"}
                  </Button>
                  <Button variant="ghost" onClick={() => setAskDelete(false)}>
                    انصراف
                  </Button>
                </div>
              </div>
            )}
          </div>
        </Card>

        <Card>
          <SectionHead
            title="ساختار"
            action={
              <Link to={pUrl(slug, "backend")} className="no-underline">
                <Button variant="ghost" size="sm">اپ‌ها و مدل‌ها</Button>
              </Link>
            }
          />
          {data.apps.length === 0 ? (
            <EmptyState title="اپی نیست">از «اپ‌ها و مدل‌ها» یکی اضافه کن.</EmptyState>
          ) : (
            data.apps.map((a) => (
              <div key={a.id} className="border-b py-2 last:border-b-0" style={{ borderColor: "var(--line)" }}>
                <div className="flex flex-wrap items-center gap-2">
                  <Link to={pUrl(slug, `app/${a.id}`)} className="font-mono text-sm font-bold" dir="ltr" style={{ color: "var(--brand-strong)" }}>
                    {a.dir}
                  </Link>
                  <span className="text-sm" style={{ color: "var(--text-3)" }}>
                    {a.verbose_name_fa}
                  </span>
                  {!a.managed && <Badge>فقط نمایش</Badge>}
                </div>
                <div className="mt-1 flex flex-wrap gap-1.5">
                  {(a.models ?? []).length === 0 && (
                    <span className="text-xs" style={{ color: "var(--text-3)" }}>
                      مدلی ندارد
                    </span>
                  )}
                  {(a.models ?? []).map((m) => (
                    <Link key={m.id} to={pUrl(slug, `model/${m.id}`)} className="no-underline">
                      <Chip>
                        {m.name} <span style={{ color: "var(--text-3)" }}>{fa(m.field_count)} فیلد</span>
                      </Chip>
                    </Link>
                  ))}
                  {(a.view_count ?? 0) > 0 && <Chip>{fa(a.view_count ?? 0)} ویو</Chip>}
                </div>
              </div>
            ))
          )}
          <SectionHead
            title={p.is_imported ? "قالب‌ها" : "صفحه‌ها"}
            action={
              <Link to={pUrl(slug, "frontend")} className="no-underline">
                <Button variant="ghost" size="sm">فرانت</Button>
              </Link>
            }
          />
          <div className="flex flex-wrap gap-1.5">
            {data.pages.length === 0 && (
              <span className="text-sm" style={{ color: "var(--text-3)" }}>
                صفحه‌ای نیست
              </span>
            )}
            {data.pages.slice(0, 24).map((pg) => (
              <Link key={pg.id} to={pUrl(slug, `page/${pg.id}`)} className="no-underline">
                <Chip>
                  {truncate(pg.title, 40)}
                  {!pg.is_imported && (
                    <span dir="ltr" className="ms-1 font-mono" style={{ color: "var(--text-3)" }}>
                      /{pg.slug}
                    </span>
                  )}
                </Chip>
              </Link>
            ))}
            {data.pages.length > 24 && (
              <Link to={pUrl(slug, "frontend")} className="no-underline">
                <Chip>+ {fa(data.pages.length - 24)} تای دیگر</Chip>
              </Link>
            )}
          </div>
        </Card>
      </div>

      <div className="grid gap-5 lg:grid-cols-2">
        <Card>
          <SectionHead
            title="آخرین نسخه‌ها"
            action={
              <Link to={pUrl(slug, "history")} className="no-underline">
                <Button variant="ghost" size="sm">همهٔ تاریخچه</Button>
              </Link>
            }
          />
          {data.history.length === 0 ? (
            <p className="text-sm" style={{ color: "var(--text-3)" }}>
              هنوز نسخه‌ای ثبت نشده — اولین «تولیدِ کد» یک نسخه می‌سازد.
            </p>
          ) : (
            data.history.map((c) => (
              <div key={c.sha} className="flex items-baseline gap-3 border-b py-1.5 text-sm last:border-b-0" style={{ borderColor: "var(--line)" }}>
                <Link to={`${pUrl(slug, "history")}?c=${c.sha}`} className="font-mono" style={{ color: "var(--brand-strong)" }}>
                  {c.short}
                </Link>
                <span className="min-w-0 flex-1 truncate" style={{ color: "var(--text-2)" }}>
                  {truncate(c.subject, 60)}
                </span>
                <span className="text-xs" style={{ color: "var(--text-3)" }}>
                  {c.date}
                </span>
              </div>
            ))
          )}
        </Card>
        <Card>
          <SectionHead
            title="هوشِ مصنوعی"
            action={
              <Link to={pUrl(slug, "ai")} className="no-underline">
                <Button size="sm">
                  <Icon name="sparkle" size={14} />
                  باز کن
                </Button>
              </Link>
            }
          />
          {data.proposals.length === 0 ? (
            <p className="text-sm" style={{ color: "var(--text-3)" }}>
              هنوز پیشنهادی نیست. از «هوشِ مصنوعی» فرانت را بساز یا یک صفحه را ویرایش کن.
            </p>
          ) : (
            data.proposals.map((pr) => (
              <div key={pr.id} className="flex items-baseline gap-3 border-b py-1.5 text-sm last:border-b-0" style={{ borderColor: "var(--line)" }}>
                <Link to={pUrl(slug, `ai/proposal/${pr.id}`)} className="min-w-0 flex-1 truncate" style={{ color: "var(--brand-strong)" }}>
                  {truncate(pr.title || pr.task_display, 50)}
                </Link>
                <Badge tone={proposalTone(pr.status)}>{pr.status_display}</Badge>
              </div>
            ))
          )}
        </Card>
      </div>

      <Card padded={false}>
        <div className="px-5 pt-5">
          <SectionHead title="گزارشِ تولیدها" hint={`${fa(data.builds.length)} موردِ آخر`} />
        </div>
        {data.builds.length === 0 ? (
          <EmptyState title="هنوز تولیدی نشده">دکمهٔ «تولیدِ کد» را بزن.</EmptyState>
        ) : (
          <Table>
            <thead>
              <tr>
                <th>زمان</th>
                <th>نتیجه</th>
                <th>خلاصه</th>
                <th>فایل</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {data.builds.map((b) => (
                <tr key={b.id}>
                  <td className="whitespace-nowrap">{fmtDate(b.created_at)}</td>
                  <td>
                    <Badge tone={b.ok ? "ok" : "bad"}>
                      <Icon name={b.ok ? "ok" : "ban"} size={12} />
                      {b.ok ? "موفق" : "خطا"}
                    </Badge>
                  </td>
                  <td>{b.summary}</td>
                  <td className="u-num">{fa(b.files_written)}</td>
                  <td>
                    {b.detail && (
                      <Button variant="ghost" size="sm" onClick={() => setOpenBuild(openBuild === b.id ? null : b.id)}>
                        {openBuild === b.id ? "بستن" : "جزئیات"}
                      </Button>
                    )}
                    {openBuild === b.id && (
                      <div className="mt-2">
                        <Pre text={b.detail} maxHeight={260} />
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
    </div>
  );
}
