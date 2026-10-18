import { FormEvent, useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { Alert, Button, Card, ErrorBox, Field, Input, Select, TextArea } from "../../../components/ui";
import { api, pUrl, studioError } from "./api";
import { CodeArea, CopyButton, Help, Loading, Mono, Pre, SectionHead } from "./common";
import { useProject } from "./shell";
import type { ProjectDetail, SettingsResp } from "./types";

type Form = Pick<
  ProjectDetail,
  | "name"
  | "site_title"
  | "description"
  | "brand_color"
  | "language_code"
  | "time_zone"
  | "allowed_hosts"
  | "extra_apps"
  | "extra_requirements"
  | "custom_settings"
>;

function pick(p: ProjectDetail): Form {
  return {
    name: p.name,
    site_title: p.site_title,
    description: p.description,
    brand_color: p.brand_color,
    language_code: p.language_code,
    time_zone: p.time_zone,
    allowed_hosts: p.allowed_hosts,
    extra_apps: p.extra_apps,
    extra_requirements: p.extra_requirements,
    custom_settings: p.custom_settings,
  };
}

/** تنظیمات — settings.py ِ گرافیکی */
export default function SettingsPage() {
  const { slug, notify, setProject } = useProject();
  const [data, setData] = useState<SettingsResp | null>(null);
  const [form, setForm] = useState<Form | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const { data: d } = await api.get<SettingsResp>(`/studio/projects/${slug}/settings/`);
      setData(d);
      setForm((f) => f ?? pick(d.project));
      setError(null);
    } catch (err) {
      setError(studioError(err));
    }
  }, [slug]);

  useEffect(() => {
    void load();
  }, [load]);

  if (!data || !form) return <Loading error={error} />;
  const p = data.project;
  const set = <K extends keyof Form>(k: K, v: Form[K]) => setForm({ ...form, [k]: v });

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const { data: d } = await api.post<{ project: ProjectDetail; message: string }>(`/studio/projects/${slug}/settings/`, form);
      setProject(d.project);
      notify(d.message);
      setForm(pick(d.project));
      await load(); // کدِ سمتِ راست از روی مقدارهای تازه ساخته می‌شود
    } catch (err) {
      setError(studioError(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid gap-5 lg:grid-cols-2">
      <Card>
        <form onSubmit={submit} className="space-y-4">
          <SectionHead title="مشخصاتِ سایت" />
          <ErrorBox message={error} />
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="نامِ پروژه">
              <Input value={form.name} onChange={(e) => set("name", e.target.value)} required />
            </Field>
            <Field label="عنوانِ سایت (SITE_TITLE)">
              <Input value={form.site_title} onChange={(e) => set("site_title", e.target.value)} />
            </Field>
          </div>
          <Field label="توضیحِ فروشگاه">
            <TextArea value={form.description} onChange={(e) => set("description", e.target.value)} rows={3} />
          </Field>
          <div>
            <span className="mb-1.5 block text-sm font-medium" style={{ color: "var(--text-2)" }}>
              رنگِ برند
            </span>
            <div className="flex items-center gap-3">
              <input
                type="color"
                value={form.brand_color}
                onChange={(e) => set("brand_color", e.target.value)}
                className="h-10 w-14 cursor-pointer rounded-lg"
                style={{ border: "1px solid var(--line)", background: "var(--surface-2)", padding: 3 }}
              />
              <span className="text-sm" style={{ color: "var(--text-3)" }}>
                اگر CSSِ مشترک را دستی/با AI عوض نکرده باشی، رنگِ دکمه‌ها از همین می‌آید.
              </span>
            </div>
          </div>

          {p.is_imported ? (
            <Alert tone="info">
              این پروژه واردشده است؛ <Mono>settings.py</Mono> ِ خودش را استودیو بازنویسی نمی‌کند. فقط وقتی اپِ تازه
              بسازی، نامش با یک خط (<Mono># studio</Mono>) به INSTALLED_APPS اضافه می‌شود.
            </Alert>
          ) : (
            <>
              <SectionHead title="محیط" />
              <div className="grid gap-3 sm:grid-cols-2">
                <Field label="زبان (LANGUAGE_CODE)">
                  <Select value={form.language_code} onChange={(e) => set("language_code", e.target.value)}>
                    {data.languages.map(([c, n]) => (
                      <option key={c} value={c}>
                        {c} — {n}
                      </option>
                    ))}
                  </Select>
                </Field>
                <Field label="منطقهٔ زمانی (TIME_ZONE)">
                  <Input value={form.time_zone} onChange={(e) => set("time_zone", e.target.value)} list="studio-tzs" dir="ltr" />
                  <datalist id="studio-tzs">
                    {data.timezones.map((z) => (
                      <option key={z} value={z} />
                    ))}
                  </datalist>
                </Field>
              </div>
              <Field label="میزبان‌های مجاز (ALLOWED_HOSTS — پیش‌فرض، با کاما)">
                <Input value={form.allowed_hosts} onChange={(e) => set("allowed_hosts", e.target.value)} dir="ltr" placeholder="example.com,www.example.com" />
              </Field>
              <Help>
                روی سرورِ واقعی با متغیرِ محیطیِ <Mono>DJANGO_ALLOWED_HOSTS</Mono> هم عوض می‌شود.
              </Help>

              <SectionHead title="اپ‌ها و بسته‌های بیرونی" />
              <div className="grid gap-3 sm:grid-cols-2">
                <div>
                  <Field label="اپ‌های بیرونی (هر خط یکی)">
                    <CodeArea value={form.extra_apps} onChange={(v) => set("extra_apps", v)} minHeight={96} placeholder={"rest_framework\ndjango_filters"} />
                  </Field>
                  <Help>به INSTALLED_APPS اضافه می‌شوند (قبل از اپ‌های خودت).</Help>
                </div>
                <div>
                  <Field label="بسته‌های pip (هر خط یکی)">
                    <CodeArea value={form.extra_requirements} onChange={(v) => set("extra_requirements", v)} minHeight={96} placeholder={"djangorestframework>=3.15\ndjango-filter"} />
                  </Field>
                  <Help>در requirements.txt می‌نشیند.</Help>
                </div>
              </div>

              <SectionHead title="تنظیماتِ دستی" hint="پایتون؛ عیناً به انتهای settings.py اضافه می‌شود" />
              <CodeArea
                value={form.custom_settings}
                onChange={(v) => set("custom_settings", v)}
                minHeight={120}
                placeholder={"EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'\nSESSION_COOKIE_AGE = 60 * 60 * 24 * 14"}
              />
              <Help>
                قبل از ذخیره از نظرِ نحو وارسی می‌شود. هر کدِ دیگری را هم می‌توانی زیرِ خطِ <Mono>studio:custom</Mono> در خودِ
                فایل بنویسی؛ با تولیدِ دوباره پاک نمی‌شود.
              </Help>
            </>
          )}

          <div className="flex gap-2">
            <Button type="submit" disabled={busy}>
              {busy ? "…" : "ذخیره"}
            </Button>
            <Link to={pUrl(slug)} className="no-underline">
              <Button type="button" variant="ghost">بازگشت</Button>
            </Link>
          </div>
        </form>
      </Card>

      <Card className="self-start lg:sticky lg:top-4">
        <SectionHead
          title={p.is_imported ? "فایلِ تنظیماتِ پروژه" : "کدی که تولید می‌شود"}
          hint={<Mono>{data.code_path}</Mono>}
          action={<CopyButton text={data.code} />}
        />
        <Pre text={data.code} maxHeight="calc(100vh - 220px)" />
      </Card>
    </div>
  );
}
