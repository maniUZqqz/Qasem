import { FormEvent, useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import Icon from "../../../components/Icon";
import { Badge, Button, Card, Chip, ErrorBox, Field, Input, Select, Table } from "../../../components/ui";
import { api, fa, fieldErrors, pUrl, studioError, truncate } from "./api";
import { Check, confirmDo, CopyButton, Help, Loading, Mono, Pre, SectionHead } from "./common";
import FieldForm, { emptyField, type FieldFormState } from "./FieldForm";
import { useProject } from "./shell";
import type { FieldT, ModelResp, ModelT, ViewT } from "./types";

type Props = {
  fa: string;
  fa_plural: string;
  ordering: string;
  has_str: boolean;
  str_field: string;
  in_admin: boolean;
  admin_list_display: string[];
  admin_search_fields: string[];
  admin_list_filter: string[];
};

function propsOf(m: ModelT): Props {
  return {
    fa: m.verbose_name_fa,
    fa_plural: m.verbose_plural_fa,
    ordering: m.ordering,
    has_str: m.has_str,
    str_field: m.str_field,
    in_admin: m.in_admin,
    admin_list_display: m.list_display,
    admin_search_fields: m.search_fields,
    admin_list_filter: m.list_filter,
  };
}

function toggle(list: string[], v: string, on: boolean): string[] {
  return on ? (list.includes(v) ? list : [...list, v]) : list.filter((x) => x !== v);
}

/** ویرایشِ مدل: فیلدها، مشخصات، ادمین، کد، ویوها */
export default function ModelEditPage() {
  const { slug, notify } = useProject();
  const { pk = "" } = useParams<{ pk: string }>();
  const navigate = useNavigate();
  const [data, setData] = useState<ModelResp | null>(null);
  const [props, setProps] = useState<Props | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [propsError, setPropsError] = useState<string | null>(null);
  const [newField, setNewField] = useState<FieldFormState>(emptyField());
  const [fieldError, setFieldError] = useState<string | null>(null);
  const [fieldErrs, setFieldErrs] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const { data: d } = await api.get<ModelResp>(`/studio/projects/${slug}/models/${pk}/`);
      setData(d);
      setProps((p) => p ?? propsOf(d.model));
      setError(null);
    } catch (err) {
      setError(studioError(err));
    }
  }, [slug, pk]);

  // رفتن از یک مدل به مدلِ دیگر (لینکِ رابطه‌ها، «مدل‌هایی که اشاره می‌کنند»): همان نمونهٔ کامپوننت می‌ماند،
  // پس فرمِ «مشخصاتِ مدل» باید خالی شود وگرنه مقدارهای مدلِ قبلی روی مدلِ تازه ذخیره می‌شد
  useEffect(() => {
    setData(null);
    setProps(null);
  }, [slug, pk]);

  useEffect(() => {
    void load();
  }, [load]);

  if (!data || !props) return <Loading error={error} />;
  const { model: m, app, fields, editable } = data;
  const M = `/studio/projects/${slug}/models/${m.id}/`;

  async function crud() {
    setBusy("crud");
    try {
      const { data: d } = await api.post<{ message: string }>(`${M}crud/`, {});
      notify(d.message);
      navigate(`${pUrl(slug, `app/${app.id}`)}?tab=views`);
    } catch (err) {
      notify(studioError(err), "bad");
    } finally {
      setBusy(null);
    }
  }

  async function removeModel() {
    if (!confirmDo(`مدلِ ${m.name} با همهٔ فیلدها و ویوهایش حذف شود؟`)) return;
    try {
      const { data: d } = await api.delete<{ message: string }>(M);
      notify(d.message);
      navigate(pUrl(slug, `app/${app.id}`));
    } catch (err) {
      notify(studioError(err), "bad");
    }
  }

  async function move(f: FieldT, dir: "up" | "down") {
    try {
      const { data: d } = await api.post<{ fields: FieldT[] }>(`/studio/projects/${slug}/fields/${f.id}/move/`, { dir });
      setData({ ...data!, fields: d.fields });
    } catch (err) {
      notify(studioError(err), "bad");
    }
  }

  async function removeField(f: FieldT) {
    if (!confirmDo(`فیلدِ ${f.name} حذف شود؟`)) return;
    try {
      const { data: d } = await api.delete<{ message: string }>(`/studio/projects/${slug}/fields/${f.id}/`);
      notify(d.message);
      await load();
    } catch (err) {
      notify(studioError(err), "bad");
    }
  }

  async function addField(e: FormEvent) {
    e.preventDefault();
    setBusy("field");
    setFieldError(null);
    setFieldErrs({});
    try {
      const { data: d } = await api.post<{ message: string }>(`/studio/projects/${slug}/fields/`, { ...newField, model: m.id });
      notify(d.message);
      setNewField(emptyField());
      await load();
    } catch (err) {
      setFieldError(studioError(err));
      setFieldErrs(fieldErrors(err));
    } finally {
      setBusy(null);
    }
  }

  async function saveProps(e: FormEvent) {
    e.preventDefault();
    setBusy("props");
    setPropsError(null);
    try {
      const { data: d } = await api.post<{ model: ModelT; message: string }>(M, props);
      notify(d.message);
      setProps(propsOf(d.model));
      await load();
    } catch (err) {
      setPropsError(studioError(err));
    } finally {
      setBusy(null);
    }
  }

  const filterable = (f: FieldT) =>
    f.field_type === "BooleanField" || f.field_type === "ForeignKey" || !!f.choices || f.field_type === "DateField" || f.field_type === "DateTimeField";

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2 text-sm" style={{ color: "var(--text-3)" }}>
        <Link to={pUrl(slug, "backend")} className="u-back">
          <Icon name="back" size={14} />
          اپ‌ها
        </Link>
        <span>›</span>
        <Link to={pUrl(slug, `app/${app.id}`)} className="font-mono" dir="ltr" style={{ color: "var(--brand-strong)" }}>
          {app.name}
        </Link>
        <span>›</span>
        <b className="font-mono" dir="ltr" style={{ color: "var(--text)" }}>
          {m.name}
        </b>
      </div>

      <Card>
        <div className="flex flex-wrap items-center gap-3">
          <div className="min-w-0 flex-1">
            <h2 className="font-mono text-lg font-bold" dir="ltr" style={{ color: "var(--text)", textAlign: "left" }}>
              {app.name}.<span style={{ color: "var(--brand-strong)" }}>{m.name}</span>
            </h2>
            <div className="text-sm" style={{ color: "var(--text-3)" }}>
              {m.verbose_name_fa || "—"}
              {m.verbose_plural_fa ? ` / ${m.verbose_plural_fa}` : ""} · جدولِ{" "}
              <Mono>
                {app.name}_{m.name.toLowerCase()}
              </Mono>
            </div>
          </div>
          {!editable && <Badge>واردشده · فقط نمایش</Badge>}
          {editable && (
            <div className="flex flex-wrap gap-2">
              <Button size="sm" onClick={crud} disabled={busy === "crud"} title="فهرست، جزئیات، ساخت، ویرایش و حذف + نشانی و قالب">
                <Icon name="sparkle" size={14} />
                {busy === "crud" ? "…" : "صفحه‌های CRUD با یک کلیک"}
              </Button>
              <Button size="sm" variant="danger" onClick={removeModel}>
                حذفِ مدل
              </Button>
            </div>
          )}
        </div>
      </Card>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_380px]">
        <div className="space-y-4">
          <Card padded={false}>
            <div className="px-5 pt-5">
              <SectionHead title="فیلدها (ستون‌ها)" hint={`${fa(fields.length)} فیلد + id`} />
            </div>
            <Table>
              <thead>
                <tr>
                  <th style={{ width: 70 }} />
                  <th>فیلد</th>
                  <th>نوع</th>
                  <th>گزینه‌ها</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td />
                  <td>
                    <Mono>id</Mono>
                    <div className="text-xs" style={{ color: "var(--text-3)" }}>
                      کلیدِ اصلی
                    </div>
                  </td>
                  <td>خودکار</td>
                  <td>
                    <Chip>PK</Chip>
                  </td>
                  <td />
                </tr>
                {fields.length === 0 && (
                  <tr>
                    <td colSpan={5} style={{ color: "var(--text-3)" }}>
                      این مدل هنوز فیلدی ندارد — از فرمِ پایین اضافه کن.
                    </td>
                  </tr>
                )}
                {fields.map((f, i) => (
                  <tr key={f.id}>
                    <td className="whitespace-nowrap">
                      {editable && (
                        <span className="inline-flex gap-0.5">
                          <Button variant="ghost" size="sm" title="بالا" disabled={i === 0} onClick={() => move(f, "up")}>
                            <Icon name="up" size={13} />
                          </Button>
                          <Button variant="ghost" size="sm" title="پایین" disabled={i === fields.length - 1} onClick={() => move(f, "down")}>
                            <Icon name="down" size={13} />
                          </Button>
                        </span>
                      )}
                    </td>
                    <td>
                      <Link to={pUrl(slug, `field/${f.id}`)} className="font-mono" dir="ltr" style={{ color: "var(--brand-strong)" }}>
                        {f.name}
                      </Link>
                      <div className="text-xs" style={{ color: "var(--text-3)" }}>
                        {f.verbose_name_fa}
                      </div>
                    </td>
                    <td>
                      {f.field_type_display}
                      {f.related_model ? (
                        <div className="text-xs" style={{ color: "var(--text-3)" }}>
                          ←{" "}
                          <Link to={pUrl(slug, `model/${f.related_model}`)} className="font-mono" dir="ltr">
                            {f.related_model_label}
                          </Link>
                        </div>
                      ) : f.related_ref ? (
                        <div className="text-xs" style={{ color: "var(--text-3)" }}>
                          ← <Mono>{f.related_ref}</Mono>
                        </div>
                      ) : null}
                    </td>
                    <td>
                      <div className="flex flex-wrap gap-1">
                        {f.max_length && f.field_type !== "TextField" ? <Chip>طول {fa(f.max_length)}</Chip> : null}
                        {f.field_type === "DecimalField" && (
                          <Chip>
                            {fa(f.max_digits ?? 12)} رقم · {fa(f.decimal_places ?? 0)} اعشار
                          </Chip>
                        )}
                        {f.null && <Chip>null</Chip>}
                        {f.blank && <Chip>اختیاری</Chip>}
                        {f.unique && <Chip>یکتا</Chip>}
                        {f.db_index && <Chip>ایندکس</Chip>}
                        {f.auto_now_add && <Chip>زمانِ ساخت</Chip>}
                        {f.auto_now && <Chip>هر ذخیره</Chip>}
                        {f.default && (
                          <Chip>
                            پیش‌فرض <Mono>{truncate(f.default, 20)}</Mono>
                          </Chip>
                        )}
                        {f.choices && <Chip>گزینه‌دار</Chip>}
                        {f.related_model && <Chip>{f.on_delete}</Chip>}
                        {f.field_type === "custom" && (
                          <Chip>
                            <span title={f.raw_code}>
                              <Mono>{truncate(f.raw_code, 40)}</Mono>
                            </span>
                          </Chip>
                        )}
                      </div>
                    </td>
                    <td className="whitespace-nowrap">
                      <Link to={pUrl(slug, `field/${f.id}`)} className="no-underline">
                        <Button variant="ghost" size="sm">{editable ? "ویرایش" : "دیدن"}</Button>
                      </Link>
                      {editable && (
                        <Button variant="ghost" size="sm" onClick={() => removeField(f)} style={{ color: "var(--bad)" }}>
                          حذف
                        </Button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </Table>
            {data.incoming.length > 0 && (
              <div className="px-5 pb-5 text-sm" style={{ color: "var(--text-3)" }}>
                مدل‌هایی که به این مدل اشاره می‌کنند:{" "}
                {data.incoming.map((x) => (
                  <Link key={x.id} to={pUrl(slug, `model/${x.model_id}`)} className="no-underline">
                    <Chip>{x.label}</Chip>
                  </Link>
                ))}
              </div>
            )}
          </Card>

          {editable && (
            <Card>
              <form onSubmit={addField} className="space-y-4">
                <SectionHead title="+ فیلدِ تازه" hint="یک ستون — یا یک رابطه با مدلِ دیگر" />
                <ErrorBox message={fieldError} />
                <FieldForm value={newField} onChange={setNewField} fieldTypes={data.field_types} onDelete={data.on_delete} allModels={data.all_models} errors={fieldErrs} />
                <Button type="submit" disabled={busy === "field"}>
                  {busy === "field" ? "…" : "افزودنِ فیلد"}
                </Button>
                <Help>بعد از تغییرِ فیلدها: «تولیدِ کد» ⇒ «مهاجرت» تا جدولِ دیتابیس هم عوض شود.</Help>
              </form>
            </Card>
          )}

          <Card>
            <SectionHead title="ویوهای این مدل" />
            {data.views.length === 0 ? (
              <p className="text-sm" style={{ color: "var(--text-3)" }}>
                هنوز ویویی ندارد. دکمهٔ «صفحه‌های CRUD با یک کلیک» را بزن.
              </p>
            ) : (
              data.views.map((v: ViewT) => (
                <div key={v.id} className="flex flex-wrap items-center gap-3 border-b py-1.5 text-sm last:border-b-0" style={{ borderColor: "var(--line)" }}>
                  <Link to={pUrl(slug, `view/${v.id}`)} className="font-mono" dir="ltr" style={{ color: "var(--brand-strong)" }}>
                    {v.label}
                  </Link>
                  <span style={{ color: "var(--text-3)" }}>{v.kind_display}</span>
                  <span className="ms-auto font-mono text-xs" dir="ltr" style={{ color: "var(--text-3)" }}>
                    {(v.routes ?? []).map((r) => `/${r.full_pattern}`).join(" ")}
                  </span>
                </div>
              ))
            )}
          </Card>
        </div>

        <div className="space-y-4">
          <Card>
            <form onSubmit={saveProps} className="space-y-3">
              <SectionHead title="مشخصاتِ مدل" />
              <ErrorBox message={propsError} />
              <div className="grid gap-3 sm:grid-cols-2">
                <Field label="نامِ فارسی">
                  <Input value={props.fa} onChange={(e) => setProps({ ...props, fa: e.target.value })} disabled={!editable} />
                </Field>
                <Field label="جمع">
                  <Input value={props.fa_plural} onChange={(e) => setProps({ ...props, fa_plural: e.target.value })} disabled={!editable} />
                </Field>
              </div>
              <Field label="ترتیبِ پیش‌فرض (ordering)" hint="نامِ فیلد؛ با - یعنی نزولی. چندتا را با کاما جدا کن.">
                <Input value={props.ordering} onChange={(e) => setProps({ ...props, ordering: e.target.value })} dir="ltr" placeholder="-created_at" disabled={!editable} />
              </Field>
              <div className="flex flex-wrap items-center gap-3">
                <Check label="__str__" checked={props.has_str} onChange={(v) => setProps({ ...props, has_str: v })} disabled={!editable} />
                <div className="min-w-[12rem] flex-1">
                  <Select value={props.str_field} onChange={(e) => setProps({ ...props, str_field: e.target.value })} disabled={!editable}>
                    <option value="">اولین فیلدِ متنی</option>
                    {fields.map((f) => (
                      <option key={f.id} value={f.name}>
                        {f.name}
                      </option>
                    ))}
                  </Select>
                </div>
              </div>

              <SectionHead
                title={<span className="text-sm">پنلِ ادمینِ سایت</span>}
                action={<Check label="ثبت در ادمین" checked={props.in_admin} onChange={(v) => setProps({ ...props, in_admin: v })} disabled={!editable} />}
              />
              <ChipChecks
                label="ستون‌های فهرست"
                items={fields.filter((f) => f.field_type !== "ManyToManyField").map((f) => f.name)}
                value={props.admin_list_display}
                onChange={(v) => setProps({ ...props, admin_list_display: v })}
                disabled={!editable}
              />
              <ChipChecks
                label="جست‌وجو در"
                items={fields.filter((f) => f.is_textual).map((f) => f.name)}
                value={props.admin_search_fields}
                onChange={(v) => setProps({ ...props, admin_search_fields: v })}
                disabled={!editable}
              />
              <ChipChecks
                label="فیلترِ کناری"
                items={fields.filter(filterable).map((f) => f.name)}
                value={props.admin_list_filter}
                onChange={(v) => setProps({ ...props, admin_list_filter: v })}
                disabled={!editable}
              />
              <Help>هیچ‌کدام را نزنی، خودکار انتخاب می‌شود.</Help>
              {editable && (
                <Button type="submit" disabled={busy === "props"}>
                  {busy === "props" ? "…" : "ذخیرهٔ مشخصات"}
                </Button>
              )}
            </form>
          </Card>

          <Card>
            <SectionHead title="کدِ این مدل" action={<CopyButton text={data.code} />} />
            <Pre text={data.code} maxHeight={520} />
            <Help>
              در <Mono>{app.dir}/models.py</Mono> می‌نشیند.
            </Help>
          </Card>
        </div>
      </div>
    </div>
  );
}

function ChipChecks({
  label,
  items,
  value,
  onChange,
  disabled,
}: {
  label: string;
  items: string[];
  value: string[];
  onChange: (v: string[]) => void;
  disabled?: boolean;
}) {
  return (
    <div>
      <span className="mb-1.5 block text-sm font-medium" style={{ color: "var(--text-2)" }}>
        {label}
      </span>
      <div className="flex flex-wrap gap-x-4 gap-y-1">
        {items.length === 0 && (
          <span className="text-xs" style={{ color: "var(--text-3)" }}>
            —
          </span>
        )}
        {items.map((name) => (
          <Check key={name} label={<span dir="ltr" className="font-mono text-xs">{name}</span>} checked={value.includes(name)} onChange={(on) => onChange(toggle(value, name, on))} disabled={disabled} />
        ))}
      </div>
    </div>
  );
}
