import { FormEvent, useCallback, useEffect, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";

import Icon from "../../../components/Icon";
import { Alert, Badge, Button, Card, Chip, EmptyState, ErrorBox, Field, Input } from "../../../components/ui";
import { api, fa, fieldErrors, pUrl, studioError, truncate } from "./api";
import { Help, Loading, Mono, SectionHead, Tabs } from "./common";
import ErDiagram from "./ErDiagram";
import { useProject } from "./shell";
import type { AppT, BackendResp } from "./types";

type Tab = "apps" | "er";

/** اپ‌ها و مدل‌ها — بک‌اندِ گرافیکی */
export default function BackendPage() {
  const { slug, project, notify } = useProject();
  const navigate = useNavigate();
  const location = useLocation();
  const [data, setData] = useState<BackendResp | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>(location.hash === "#er" ? "er" : "apps");
  const [name, setName] = useState("");
  const [faName, setFaName] = useState("");
  const [description, setDescription] = useState("");
  const [prefix, setPrefix] = useState("");
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});

  const load = useCallback(async () => {
    try {
      const { data: d } = await api.get<BackendResp>(`/studio/projects/${slug}/backend/`);
      setData(d);
      setError(null);
    } catch (err) {
      setError(studioError(err));
    }
  }, [slug]);

  useEffect(() => {
    void load();
  }, [load]);

  async function addApp(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setFormError(null);
    setErrors({});
    try {
      const { data: d } = await api.post<{ app: AppT; message: string }>(`/studio/projects/${slug}/apps/`, {
        name,
        fa: faName,
        description,
        url_prefix: prefix,
      });
      notify(d.message);
      navigate(pUrl(slug, `app/${d.app.id}`));
    } catch (err) {
      setFormError(studioError(err));
      setErrors(fieldErrors(err));
    } finally {
      setBusy(false);
    }
  }

  if (!data) return <Loading error={error} />;

  return (
    <div className="space-y-4">
      {project.is_imported && (
        <Alert tone="info">
          اپ‌ها و مدل‌های خودِ این پروژهٔ واردشده فقط <b>نمایش</b> داده می‌شوند (کدشان دست‌نخورده می‌ماند). برای
          امکانِ تازه، یک <b>اپِ تازه</b> بساز — استودیو کاملش را می‌نویسد و به settings و urls ِ پروژه وصلش می‌کند.
        </Alert>
      )}

      <Tabs<Tab>
        tabs={[
          { key: "apps", label: "اپ‌ها", count: data.apps.length },
          { key: "er", label: "نمودارِ مدل‌ها و رابطه‌ها" },
        ]}
        active={tab}
        onChange={setTab}
      />

      {tab === "apps" ? (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {data.apps.map((a) => (
            <Card key={a.id} className="flex flex-col">
              <div className="mb-1.5 flex flex-wrap items-center gap-2">
                <Icon name="box" size={18} className="shrink-0" />
                <Link to={pUrl(slug, `app/${a.id}`)} className="font-mono text-base font-bold" dir="ltr" style={{ color: "var(--brand-strong)" }}>
                  {a.name}
                </Link>
                {a.is_core && <Badge tone="brand">پایهٔ فروشگاه</Badge>}
                {!a.managed && <Badge>فقط نمایش</Badge>}
              </div>
              <div className="mb-2 text-sm" style={{ color: "var(--text-3)" }}>
                {a.verbose_name_fa || "—"}
                {a.description ? ` · ${truncate(a.description, 80)}` : ""}
              </div>
              <div className="mb-3 flex flex-wrap gap-1.5">
                {(a.models ?? []).length === 0 && (
                  <span className="text-xs" style={{ color: "var(--text-3)" }}>
                    مدلی ندارد
                  </span>
                )}
                {(a.models ?? []).map((m) => (
                  <Link key={m.id} to={pUrl(slug, `model/${m.id}`)} className="no-underline">
                    <Chip>
                      <b>{m.name}</b> <span style={{ color: "var(--text-3)" }}>{fa(m.field_count)}</span>
                    </Chip>
                  </Link>
                ))}
              </div>
              <div className="mt-auto text-xs" style={{ color: "var(--text-3)" }}>
                <Mono>/{a.effective_prefix}</Mono> · {fa(a.view_count ?? 0)} ویو · {fa(a.route_count ?? 0)} نشانی
              </div>
              <div className="mt-3 flex gap-2">
                <Link to={pUrl(slug, `app/${a.id}`)} className="no-underline">
                  <Button size="sm">باز کن</Button>
                </Link>
                <Link to={`${pUrl(slug, `app/${a.id}`)}?tab=code`} className="no-underline">
                  <Button size="sm" variant="ghost">کد</Button>
                </Link>
              </div>
            </Card>
          ))}

          <Card className="border-dashed">
            <form onSubmit={addApp} className="space-y-3">
              <SectionHead title="+ اپِ تازه" hint="idea.md §۵.۱" />
              <ErrorBox message={formError} />
              <div className="grid gap-3 sm:grid-cols-2">
                <Field label="نامِ انگلیسی" hint={errors.name}>
                  <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="blog" required dir="ltr" pattern="[a-z][a-z0-9_]+" />
                </Field>
                <Field label="نامِ فارسی">
                  <Input value={faName} onChange={(e) => setFaName(e.target.value)} placeholder="وبلاگ" />
                </Field>
              </div>
              <Field label="مسئولیت (اختیاری)">
                <Input value={description} onChange={(e) => setDescription(e.target.value)} placeholder="نوشته‌ها و نظرهای وبلاگ" />
              </Field>
              <Field label="پیشوندِ نشانی" hint="نشانی‌های این اپ زیرِ همین می‌نشینند؛ خالی = نامِ اپ.">
                <Input value={prefix} onChange={(e) => setPrefix(e.target.value)} placeholder={`${name || "blog"}/`} dir="ltr" />
              </Field>
              <Button type="submit" className="w-full" disabled={busy || !name.trim()}>
                {busy ? "…" : "ساختِ اپ"}
              </Button>
              <Help>ساخته می‌شود: models · views · urls · admin · forms · migrations + ثبت در INSTALLED_APPS</Help>
            </form>
          </Card>
        </div>
      ) : (
        <Card>
          <SectionHead
            title="نمودارِ مدل‌ها"
            hint={
              <span className="inline-flex flex-wrap items-center gap-3">
                <span className="inline-flex items-center gap-1">
                  <i className="inline-block h-0.5 w-6" style={{ background: "#7c3aed" }} />
                  چند-به-یک / یک-به-یک
                </span>
                <span className="inline-flex items-center gap-1">
                  <i className="inline-block h-0.5 w-6" style={{ borderTop: "2px dashed #7c3aed" }} />
                  چند-به-چند
                </span>
                <span>روی هر جدول بزن تا ویرایشش کنی</span>
              </span>
            }
          />
          {data.er.length === 0 ? (
            <EmptyState title="مدلی نیست">از تبِ «اپ‌ها» یک اپ بساز و در آن مدل اضافه کن.</EmptyState>
          ) : (
            <ErDiagram models={data.er} slug={slug} />
          )}
        </Card>
      )}
    </div>
  );
}
