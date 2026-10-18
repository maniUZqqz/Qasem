import { FormEvent, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import Icon from "../../../components/Icon";
import { Badge, Button, Card, ErrorBox, Field, Input, Select } from "../../../components/ui";
import { api, pUrl, studioError } from "./api";
import AiBox from "./AiBox";
import { Check, CodeArea, confirmDo, docHtml, Help, Loading, Mono, Pre, PreviewFrame, SectionHead, StickyBar } from "./common";
import { useProject } from "./shell";
import type { ViewResp, ViewT } from "./types";

type Form = {
  kind: string;
  model: string;
  description: string;
  paginate_by: string;
  ordering: string;
  context_object_name: string;
  form_fields: string[];
  success_url_name: string;
  login_required: boolean;
  template_body: string;
  css: string;
  custom_code: string;
};

function formOf(v: ViewT, chosen: string[]): Form {
  return {
    kind: v.kind,
    model: v.model ? String(v.model) : "",
    description: v.description,
    paginate_by: v.paginate_by == null ? "" : String(v.paginate_by),
    ordering: v.ordering,
    context_object_name: v.context_object_name,
    form_fields: chosen,
    success_url_name: v.success_url_name,
    login_required: v.login_required,
    template_body: v.template_body,
    css: v.css,
    custom_code: v.custom_code,
  };
}

/** ویرایشِ ویو: رفتار، قالب، CSS، پیش‌نمایش، کد */
export default function ViewEditPage() {
  const { slug, notify } = useProject();
  const { pk = "" } = useParams<{ pk: string }>();
  const navigate = useNavigate();
  const [data, setData] = useState<ViewResp | null>(null);
  const [form, setForm] = useState<Form | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [html, setHtml] = useState("");

  useEffect(() => {
    api
      .get<ViewResp>(`/studio/projects/${slug}/views/${pk}/`)
      .then((r) => {
        setData(r.data);
        setForm(formOf(r.data.view, r.data.chosen_fields));
      })
      .catch((err) => setError(studioError(err)));
  }, [slug, pk]);

  // پیش‌نمایشِ بی‌داده با هدر/فوتر/CSSِ مشترک — با تأخیرِ کوتاه تا هر حرف یک رندر نشود
  useEffect(() => {
    if (!data || !form) return;
    const t = window.setTimeout(() => setHtml(docHtml(data.shared, form.template_body, form.css)), 250);
    return () => window.clearTimeout(t);
  }, [data, form?.template_body, form?.css]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!data || !form) return <Loading error={error} />;
  const { view: v, app, editable } = data;
  const needsModel = data.needs_model.includes(form.kind);
  const set = <K extends keyof Form>(k: K, val: Form[K]) => setForm({ ...form, [k]: val });

  async function save(e: FormEvent) {
    e.preventDefault();
    const current = form;
    if (!current) return;
    setBusy(true);
    setError(null);
    try {
      const payload: Record<string, unknown> = { ...current };
      if (!v.needs_template) {
        delete payload.template_body;
        delete payload.css;
      }
      const { data: d } = await api.put<{ view: ViewT; code: string; message: string }>(`/studio/projects/${slug}/views/${pk}/`, payload);
      setData({ ...data!, view: d.view, code: d.code, chosen_fields: d.view.field_list });
      setForm(formOf(d.view, d.view.field_list));
      notify(d.message);
    } catch (err) {
      setError(studioError(err));
    } finally {
      setBusy(false);
    }
  }

  async function reset() {
    const current = form;
    if (!current || !confirmDo("قالبِ این ویو با نسخهٔ پیش‌فرض جایگزین شود؟")) return;
    try {
      const { data: d } = await api.post<{ view: ViewT; message: string }>(`/studio/projects/${slug}/views/${pk}/reset/`, {});
      setData({ ...data!, view: d.view });
      setForm({ ...current, template_body: d.view.template_body });
      if (d.message) notify(d.message);
    } catch (err) {
      notify(studioError(err), "bad");
    }
  }

  async function remove() {
    if (!confirmDo(`ویوی ${v.name} و نشانی‌اش حذف شود؟`)) return;
    try {
      const { data: d } = await api.delete<{ message: string }>(`/studio/projects/${slug}/views/${pk}/`);
      notify(d.message);
      navigate(`${pUrl(slug, `app/${app.id}`)}?tab=views`);
    } catch (err) {
      notify(studioError(err), "bad");
    }
  }

  const routes = v.routes ?? [];

  return (
    <form onSubmit={save} className="space-y-4">
      <Card>
        <div className="flex flex-wrap items-center gap-3">
          <div className="min-w-0 flex-1">
            <h2 className="font-mono text-lg font-bold" dir="ltr" style={{ color: "var(--text)", textAlign: "left" }}>
              {app.name}.views.{v.class_name}
            </h2>
            <div className="text-sm" style={{ color: "var(--text-3)" }}>
              {v.kind_display}
              {v.model && (
                <>
                  {" "}
                  · مدلِ{" "}
                  <Link to={pUrl(slug, `model/${v.model}`)} className="font-mono" dir="ltr">
                    {v.model_name}
                  </Link>
                </>
              )}
              {routes.length === 0 ? (
                <span style={{ color: "var(--warn)" }}> · بی‌نشانی</span>
              ) : (
                routes.map((r) => (
                  <span key={r.id}>
                    {" "}
                    · <Mono>/{r.full_pattern}</Mono>
                    {r.name && <span> ({r.name})</span>}
                  </span>
                ))
              )}
            </div>
          </div>
          {!editable && <Badge>واردشده · فقط نمایش</Badge>}
          {editable && (
            <div className="flex gap-2">
              {v.needs_template && (
                <Button type="button" variant="ghost" size="sm" onClick={reset}>
                  قالبِ پیش‌فرض
                </Button>
              )}
              <Button type="button" variant="danger" size="sm" onClick={remove}>
                حذف
              </Button>
            </div>
          )}
          <Link to={`${pUrl(slug, `app/${app.id}`)}?tab=views`} className="u-back">
            <Icon name="back" size={14} />
            {app.name}
          </Link>
        </div>
      </Card>

      {editable && v.needs_template && (
        <AiBox
          slug={slug}
          endpoint={`ai/view/${v.id}/`}
          title="قالبِ این صفحه را با هوشِ مصنوعی عوض کن"
          placeholder="مثلاً: کارت‌ها را سه‌ستونه کن، تصویرِ بزرگ بالای هر کارت بگذار و تاریخ را زیرِ عنوان نشان بده"
          note="فقط قالب و CSSِ همین ویو عوض می‌شود؛ قبل از اعمال Diff را می‌بینی."
        />
      )}

      <ErrorBox message={error} />

      <div className="grid gap-4 lg:grid-cols-2">
        <div className="space-y-4">
          <Card>
            <SectionHead title="رفتارِ ویو" />
            <div className="space-y-3">
              <div className="grid gap-3 sm:grid-cols-2">
                <Field label="نوع">
                  <Select value={form.kind} onChange={(e) => set("kind", e.target.value)} disabled={!editable}>
                    {data.kinds.map(([k, l]) => (
                      <option key={k} value={k}>
                        {l}
                      </option>
                    ))}
                  </Select>
                </Field>
                {needsModel && (
                  <Field label="مدل">
                    <Select value={form.model} onChange={(e) => set("model", e.target.value)} disabled={!editable}>
                      {data.all_models.map((m) => (
                        <option key={m.id} value={m.id}>
                          {m.label}
                        </option>
                      ))}
                    </Select>
                  </Field>
                )}
              </div>
              <Field label="توضیح (عنوانِ صفحه)">
                <Input value={form.description} onChange={(e) => set("description", e.target.value)} disabled={!editable} />
              </Field>
              <div className="grid gap-3 sm:grid-cols-3">
                {form.kind === "list" && (
                  <>
                    <Field label="صفحه‌بندی (تعداد در هر صفحه)">
                      <Input type="number" min={1} value={form.paginate_by} onChange={(e) => set("paginate_by", e.target.value)} dir="ltr" disabled={!editable} />
                    </Field>
                    <Field label="ترتیب">
                      <Input value={form.ordering} onChange={(e) => set("ordering", e.target.value)} placeholder="-created_at" dir="ltr" disabled={!editable} />
                    </Field>
                  </>
                )}
                {(form.kind === "list" || form.kind === "detail") && (
                  <Field label="نامِ متغیر در قالب">
                    <Input value={form.context_object_name} onChange={(e) => set("context_object_name", e.target.value)} dir="ltr" placeholder="خودکار" disabled={!editable} />
                  </Field>
                )}
              </div>
              {(form.kind === "create" || form.kind === "update") && (
                <div>
                  <span className="mb-1.5 block text-sm font-medium" style={{ color: "var(--text-2)" }}>
                    فیلدهای فرم (هیچ‌کدام = همهٔ فیلدهای ویرایش‌پذیر)
                  </span>
                  <div className="flex flex-wrap gap-x-4 gap-y-1">
                    {data.model_fields.map((f) => (
                      <Check
                        key={f.id}
                        label={<span dir="ltr" className="font-mono text-xs">{f.name}</span>}
                        checked={form.form_fields.includes(f.name)}
                        onChange={(on) => set("form_fields", on ? [...form.form_fields, f.name] : form.form_fields.filter((x) => x !== f.name))}
                        disabled={!editable}
                      />
                    ))}
                  </div>
                  {String(v.model) !== form.model && <Help>فیلدها مالِ مدلِ ذخیره‌شده‌اند؛ بعد از ذخیره با مدلِ تازه می‌آیند.</Help>}
                </div>
              )}
              {(form.kind === "create" || form.kind === "update" || form.kind === "delete") && (
                <Field label="بعد از موفقیت برو به (نامِ نشانی)">
                  <Input value={form.success_url_name} onChange={(e) => set("success_url_name", e.target.value)} list="studio-urlnames" dir="ltr" placeholder="خودکار: فهرستِ همین مدل" disabled={!editable} />
                  <datalist id="studio-urlnames">
                    {data.url_names.map((n) => (
                      <option key={n} value={n} />
                    ))}
                  </datalist>
                </Field>
              )}
              <Check label="فقط کاربرِ واردشده (LoginRequiredMixin)" checked={form.login_required} onChange={(on) => set("login_required", on)} disabled={!editable} />
              {form.kind === "custom" && (
                <div>
                  <Field label="کدِ پایتونِ ویو (یک def یا class کامل)">
                    <CodeArea value={form.custom_code} onChange={(val) => set("custom_code", val)} minHeight={260} readOnly={!editable} />
                  </Field>
                  <Help>import ها به بالای views.py منتقل می‌شوند. قبل از ذخیره از نظرِ نحو وارسی می‌شود.</Help>
                </div>
              )}
            </div>
          </Card>

          <Card>
            <SectionHead title="کدِ این ویو" hint={<Mono>{app.dir}/views.py</Mono>} />
            <Pre text={data.code} />
          </Card>
        </div>

        <div className="space-y-4">
          {v.needs_template && (
            <>
              <Card>
                <SectionHead title="قالبِ صفحه" hint={<Mono>templates/{v.template_name}</Mono>} />
                <CodeArea value={form.template_body} onChange={(val) => set("template_body", val)} minHeight={300} readOnly={!editable} />
                <Help>
                  داخلِ <Mono>{"{% block content %}"}</Mono> می‌نشیند؛ هدر و فوترِ سایت خودکار دورش هست. متغیرها: <Mono>object</Mono> ·{" "}
                  <Mono>{form.context_object_name || "…_list"}</Mono> · <Mono>form</Mono> · <Mono>page_obj</Mono>
                </Help>
                <div className="mt-3">
                  <Field label="CSSِ همین صفحه">
                    <CodeArea value={form.css} onChange={(val) => set("css", val)} minHeight={110} readOnly={!editable} />
                  </Field>
                </div>
              </Card>
              <Card className="lg:sticky lg:top-4">
                <SectionHead title="پیش‌نمایشِ ظاهر" hint="بی‌داده — دادهٔ واقعی در «پیش‌نمایشِ زنده»" />
                <PreviewFrame html={html} height={420} />
              </Card>
            </>
          )}
        </div>
      </div>

      {editable && (
        <StickyBar>
          <Button type="submit" disabled={busy}>
            {busy ? "…" : "ذخیرهٔ ویو"}
          </Button>
          <Link to={`${pUrl(slug, `app/${app.id}`)}?tab=views`} className="no-underline">
            <Button type="button" variant="ghost">بازگشت</Button>
          </Link>
          <span className="text-sm" style={{ color: "var(--text-3)" }}>
            بعد از ذخیره «تولیدِ کد» را بزن.
          </span>
        </StickyBar>
      )}
    </form>
  );
}
