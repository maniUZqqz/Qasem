import { FormEvent, useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import Icon from "../../../components/Icon";
import { Alert, Badge, Button, Card, Chip, EmptyState, ErrorBox, Field, Input, Select, Table } from "../../../components/ui";
import { api, fa, pUrl, studioError } from "./api";
import { confirmDo, Loading, Mono, SectionHead } from "./common";
import { openVisual } from "./visualEntry";
import { useProject } from "./shell";
import type { FrontendResp, PageT, SharedKind } from "./types";

const SHARED: { kind: SharedKind; label: string }[] = [
  { kind: "header", label: "هدر" },
  { kind: "footer", label: "فوتر" },
  { kind: "base_css", label: "CSSِ مشترک" },
];

/** فرانتِ سه‌بخشی: صفحه‌ها + بخش‌های مشترک */
export default function FrontendPage() {
  const { slug, project, notify } = useProject();
  const navigate = useNavigate();
  const [data, setData] = useState<FrontendResp | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [title, setTitle] = useState("");
  const [pslug, setPslug] = useState("");
  const [kind, setKind] = useState("static");
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const { data: d } = await api.get<FrontendResp>(`/studio/projects/${slug}/frontend/`);
      setData(d);
      setError(null);
    } catch (err) {
      setError(studioError(err));
    }
  }, [slug]);

  useEffect(() => {
    void load();
  }, [load]);

  async function addPage(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setFormError(null);
    try {
      const { data: d } = await api.post<{ page: PageT; message: string }>(`/studio/projects/${slug}/pages/`, { title, slug: pslug, kind });
      notify(d.message);
      navigate(pUrl(slug, `page/${d.page.id}`));
    } catch (err) {
      setFormError(studioError(err));
    } finally {
      setBusy(false);
    }
  }

  async function removePage(pg: PageT) {
    if (!confirmDo(`صفحهٔ «${pg.title}» حذف شود؟`)) return;
    try {
      const { data: d } = await api.delete<{ message: string }>(`/studio/projects/${slug}/pages/${pg.id}/`);
      notify(d.message);
      await load();
    } catch (err) {
      notify(studioError(err), "bad");
    }
  }

  if (!data) return <Loading error={error} />;

  if (project.is_imported) {
    return (
      <div className="space-y-4">
        <Alert tone="info">
          این پروژه واردشده است: هر <b>قالب</b> (فایلِ .html) جدا ویرایش می‌شود — دستی یا با هوشِ مصنوعی. با «تولیدِ کد»
          فقط قالب‌هایی که عوض کرده‌ای روی دیسک نوشته می‌شوند.
        </Alert>
        <Card padded={false}>
          <div className="px-5 pt-5">
            <SectionHead title="قالب‌های پروژه" hint={`${fa(data.pages.length)} فایل`} />
          </div>
          <Table>
            <thead>
              <tr>
                <th>فایل</th>
                <th>اندازه</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {data.pages.length === 0 && (
                <tr>
                  <td colSpan={3} style={{ color: "var(--text-3)" }}>
                    قالبی پیدا نشد.
                  </td>
                </tr>
              )}
              {data.pages.map((pg) => (
                <tr key={pg.id}>
                  <td dir="ltr" className="font-mono text-xs" style={{ textAlign: "left" }}>
                    <Link to={pUrl(slug, `page/${pg.id}`)} style={{ color: "var(--brand-strong)" }}>
                      {pg.file_path}
                    </Link>
                  </td>
                  <td>{fa(pg.body_length)} کاراکتر</td>
                  <td>
                    <Link to={pUrl(slug, `page/${pg.id}`)} className="no-underline">
                      <Button variant="ghost" size="sm">ویرایش</Button>
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <Card>
        <div className="flex flex-wrap items-center gap-4">
          <div className="min-w-0 flex-1">
            <h2 className="flex items-center gap-2 text-lg font-extrabold" style={{ color: "var(--text)" }}>
              <Icon name="image" size={18} />
              سایت را با کشیدن و زدن بساز
            </h2>
            <p className="mt-1 text-sm leading-7" style={{ color: "var(--text-2)" }}>
              بی‌هیچ کدی: بلوک‌ها را روی صفحه بینداز، متن را همان‌جا بنویس، رنگ‌ها را عوض کن و منتشر کن.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Link to={pUrl(slug, "start")} className="no-underline" data-testid="visual-new">
              <Button>صفحهٔ تازه از روی قالب</Button>
            </Link>
            <Link to={pUrl(slug, "builder/header")} className="no-underline">
              <Button variant="secondary">سربرگ و منو</Button>
            </Link>
            <Link to={pUrl(slug, "builder/footer")} className="no-underline">
              <Button variant="secondary">پابرگ</Button>
            </Link>
          </div>
        </div>
      </Card>

      <Card>
        <div className="flex flex-wrap items-center gap-4">
          <div className="min-w-0 flex-1">
            <h2 className="flex items-center gap-2 text-lg font-extrabold" style={{ color: "var(--text)" }}>
              <Icon name="sparkle" size={18} />
              ظاهرِ سایت را با هوشِ مصنوعی بساز
            </h2>
            <p className="mt-1 text-sm leading-7" style={{ color: "var(--text-2)" }}>
              بگو سایتت چیست؛ سربرگ، پابرگ و صفحه‌ها پیشنهاد می‌شوند و بعد هر صفحه را جدا ویرایش می‌کنی.
              هیچ‌چیز بدونِ دیدنِ تغییرها و تأییدِ تو اعمال نمی‌شود.
            </p>
          </div>
          <Link to={pUrl(slug, "ai")} className="no-underline">
            <Button>شروع با هوشِ مصنوعی</Button>
          </Link>
        </div>
      </Card>

      <div className="grid gap-4 lg:grid-cols-[360px_minmax(0,1fr)]">
        <div className="space-y-4">
          <Card>
            <SectionHead title="هر صفحه سه قسمت دارد" />
            <div className="space-y-1.5 text-center text-sm font-bold">
              <div className="rounded-lg p-2" style={{ background: "var(--brand-soft)", color: "var(--brand-strong)" }}>
                سربرگ — در همهٔ صفحه‌ها یکی است
              </div>
              <div className="rounded-lg p-5" style={{ border: "1px dashed var(--line-strong)", color: "var(--text)" }}>
                محتوای هر صفحه
                <br />
                <small className="font-normal" style={{ color: "var(--text-3)" }}>
                  جداگانه ویرایش می‌شود
                </small>
              </div>
              <div className="rounded-lg p-2" style={{ background: "var(--brand-soft)", color: "var(--brand-strong)" }}>
                پابرگ — در همهٔ صفحه‌ها یکی است
              </div>
            </div>
            <p className="mt-3 text-sm leading-6" style={{ color: "var(--text-3)" }}>
              ویرایشِ یک صفحه روی صفحه‌های دیگر و سربرگ و پابرگ اثری ندارد؛ هوشِ مصنوعی هم فقط همان صفحه را عوض می‌کند.
            </p>
          </Card>
          <Card>
            <SectionHead title="کدِ بخش‌های مشترک (پیشرفته)" />
            <div className="space-y-2">
              {SHARED.map((s) => (
                <Link key={s.kind} to={pUrl(slug, `shared/${s.kind}`)} className="no-underline">
                  <Button variant="secondary" className="w-full !justify-start">
                    {s.label}
                    <span className="ms-auto">
                      {data.parts[s.kind] ? <Badge tone="ok">سفارشی</Badge> : <Badge>پیش‌فرض</Badge>}
                    </span>
                  </Button>
                </Link>
              ))}
            </div>
          </Card>
        </div>

        <div className="space-y-4">
          <Card>
            <SectionHead title="صفحه‌ها" hint={`${fa(data.pages.length)} صفحه`} />
            {data.pages.length === 0 ? (
              <EmptyState title="صفحه‌ای نیست">از فرمِ پایین یکی بساز.</EmptyState>
            ) : (
              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                {data.pages.map((pg) => (
                  <div key={pg.id} className="rounded-xl p-3" style={{ border: "1px solid var(--line)" }}>
                    <div className="mb-1 flex items-center gap-2">
                      <b className="min-w-0 flex-1 truncate" style={{ color: "var(--text)" }}>
                        {pg.title}
                      </b>
                      <Badge>{pg.kind_display}</Badge>
                    </div>
                    <div>
                      <Mono>/{pg.slug}</Mono>
                    </div>
                    <div className="my-2 text-xs" style={{ color: "var(--text-3)" }}>
                      {pg.body_length ? `${fa(pg.body_length)} کاراکتر بدنه` : <span style={{ color: "var(--warn)" }}>بدنه خالی است</span>}
                      {pg.has_css && " · CSS دارد"}
                      {pg.in_menu && " · در منو"}
                    </div>
                    <div className="flex flex-wrap gap-2">
                      <Link to={openVisual(slug, pg.id)} className="no-underline" data-visual={pg.id}>
                        <Button size="sm">ویرایش</Button>
                      </Link>
                      <Link to={pUrl(slug, `page/${pg.id}`)} className="no-underline" title="حالتِ پیشرفته: ویرایشِ کدِ این صفحه">
                        <Button size="sm" variant="ghost">کد (پیشرفته)</Button>
                      </Link>
                      <Button size="sm" variant="danger" onClick={() => removePage(pg)}>
                        حذف
                      </Button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </Card>

          <Card>
            <form onSubmit={addPage} className="space-y-3">
              <SectionHead title="+ صفحهٔ کدی (پیشرفته)" hint="برای برنامه‌نویس؛ صفحهٔ عادی را از «صفحهٔ تازه از روی قالب» بساز" />
              <ErrorBox message={formError} />
              <div className="grid gap-3 sm:grid-cols-[1fr_1fr_1fr_auto] sm:items-end">
                <Field label="عنوان">
                  <Input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="دربارهٔ ما" required />
                </Field>
                <Field label="نشانی (بعد از /)">
                  <Input value={pslug} onChange={(e) => setPslug(e.target.value)} placeholder="about" dir="ltr" pattern="[a-z0-9-]*" />
                </Field>
                <Field label="نوع">
                  <Select value={kind} onChange={(e) => setKind(e.target.value)}>
                    {data.kinds.map(([v, l]) => (
                      <option key={v} value={v}>
                        {l}
                      </option>
                    ))}
                  </Select>
                </Field>
                <Button type="submit" disabled={busy || !title.trim()}>
                  {busy ? "…" : "افزودن"}
                </Button>
              </div>
            </form>
          </Card>

          {data.view_templates.length > 0 && (
            <Card>
              <SectionHead title="قالب‌های ویوها" hint="صفحه‌هایی که از ویوهای اپ‌ها می‌آیند (فهرست/جزئیات/فرم…)" />
              <div className="flex flex-wrap gap-1.5">
                {data.view_templates.map((v) => (
                  <Link key={v.id} to={pUrl(slug, `view/${v.id}`)} className="no-underline">
                    <Chip>
                      <span dir="ltr" className="font-mono">
                        {v.app_name}/{v.name}
                      </span>{" "}
                      <span style={{ color: "var(--text-3)" }}>{v.kind_display}</span>
                    </Chip>
                  </Link>
                ))}
              </div>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
