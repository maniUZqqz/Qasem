import { FormEvent, ReactNode, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import Icon from "../../../components/Icon";
import { Alert, Badge, Button, Card, ErrorBox } from "../../../components/ui";
import { api, fieldErrors, pUrl, studioError } from "./api";
import { KV, Loading, Mono, Pre, SectionHead } from "./common";
import FieldForm, { fromField, type FieldFormState } from "./FieldForm";
import { useProject } from "./shell";
import type { FieldResp, FieldT } from "./types";

/** ویرایشِ یک فیلد */
export default function FieldEditPage() {
  const { slug, notify } = useProject();
  const { pk = "" } = useParams<{ pk: string }>();
  const navigate = useNavigate();
  const [data, setData] = useState<FieldResp | null>(null);
  const [form, setForm] = useState<FieldFormState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api
      .get<FieldResp>(`/studio/projects/${slug}/fields/${pk}/`)
      .then((r) => {
        setData(r.data);
        setForm(fromField(r.data.field));
      })
      .catch((err) => setError(studioError(err)));
  }, [slug, pk]);

  if (!data || !form) return <Loading error={error} />;
  const { field: f, model: m } = data;
  const readOnlyRows: [ReactNode, ReactNode][] = [
    ["نام", <Mono key="n">{f.name}</Mono>],
    ["نوع", f.field_type_display],
  ];
  if (f.related_ref || f.related_model) readOnlyRows.push(["مقصد", <Mono key="t">{f.target_label}</Mono>]);
  readOnlyRows.push(["کدِ اصلی", <Mono key="c">{f.raw_code}</Mono>]);

  async function save(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setErrors({});
    try {
      const { data: d } = await api.put<{ field: FieldT; message: string }>(`/studio/projects/${slug}/fields/${pk}/`, form);
      notify(d.message);
      navigate(pUrl(slug, `model/${m.id}`));
    } catch (err) {
      setError(studioError(err));
      setErrors(fieldErrors(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2 text-sm" style={{ color: "var(--text-3)" }}>
        <Link to={pUrl(slug, "backend")} className="u-back">
          <Icon name="back" size={14} />
          اپ‌ها
        </Link>
        <span>›</span>
        <Link to={pUrl(slug, `model/${m.id}`)} className="font-mono" dir="ltr" style={{ color: "var(--brand-strong)" }}>
          {m.label}
        </Link>
        <span>›</span>
        <b className="font-mono" dir="ltr" style={{ color: "var(--text)" }}>
          {f.name}
        </b>
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_380px]">
        {data.editable ? (
          <Card>
            <form onSubmit={save} className="space-y-4">
              <SectionHead title="ویرایشِ فیلد" hint={<>مدلِ <Mono>{m.name}</Mono></>} />
              <ErrorBox message={error} />
              <FieldForm value={form} onChange={setForm} fieldTypes={data.field_types} onDelete={data.on_delete} allModels={data.all_models} errors={errors} />
              <div className="flex gap-2">
                <Button type="submit" disabled={busy}>
                  {busy ? "…" : "ذخیره"}
                </Button>
                <Link to={pUrl(slug, `model/${m.id}`)} className="no-underline">
                  <Button type="button" variant="ghost">بازگشت</Button>
                </Link>
              </div>
              <Alert tone="warn">
                تغییرِ نام یا نوعِ فیلد روی دیتابیسِ موجود یک مهاجرت می‌سازد. اگر داده داری، مهاجرت ممکن است مقدارِ پیش‌فرض
                بخواهد.
              </Alert>
            </form>
          </Card>
        ) : (
          <Card>
            <SectionHead title="فیلدِ واردشده" action={<Badge>فقط نمایش</Badge>} />
            <KV rows={readOnlyRows} />
          </Card>
        )}
        <Card className="self-start">
          <SectionHead title="کد" />
          <Pre text={data.code} />
        </Card>
      </div>
    </div>
  );
}
