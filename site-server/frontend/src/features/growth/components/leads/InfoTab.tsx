import { FormEvent, useEffect, useMemo, useRef, useState } from "react";

import { Alert, Button, Card, Input, Select, TextArea } from "../../../../components/ui";
import { g, problem } from "../../api";
import { useMeta } from "../../MetaContext";
import type { DuplicateItem, LeadDetail } from "../../types";
import FormField, { groupErrors } from "./FormField";
import OwningLeadDialog from "./OwningLeadDialog";
import { splitList } from "./hooks";
import { provenanceLabel } from "./provenance";

type Form = {
  business_name: string;
  category: string;
  description: string;
  country: string;
  city: string;
  website: string;
  instagram_url: string;
  language: string;
  business_type: string;
  address: string;
  product_categories: string;
  product_names: string;
};

const toForm = (lead: LeadDetail): Form => ({
  business_name: lead.business_name,
  category: lead.category,
  description: lead.description,
  country: lead.country,
  city: lead.city,
  website: lead.website,
  instagram_url: lead.instagram_url,
  language: lead.profile.language,
  business_type: lead.profile.business_type,
  address: lead.profile.address,
  product_categories: lead.profile.product_categories.join("، "),
  product_names: lead.profile.product_names.join("، "),
});

const KNOWN = ["business_name", "category", "description", "country", "city", "website", "instagram_url", "profile.language", "profile.business_type", "profile.address", "profile.product_categories", "profile.product_names"];

function Chip({ text, title }: { text: string; title: string }) {
  if (!text) return null;
  return (
    <span className="u-badge u-badge-neutral" style={{ fontWeight: 500 }} title={title} data-testid="prov-chip">
      منبع: {text}
    </span>
  );
}

/** The «اطلاعات» tab: every editable field with where its value came from; saves only what changed. */
export default function InfoTab({ lead, onSaved }: { lead: LeadDetail; onSaved: (lead: LeadDetail) => void }) {
  const { meta } = useMeta();
  const initial = useMemo(() => toForm(lead), [lead]);
  const [form, setForm] = useState<Form>(initial);
  // when the lead changes from outside (another tab, an extraction run) untouched fields follow it; edited ones stay
  const previous = useRef(initial);
  useEffect(() => {
    setForm((f) => (JSON.stringify(f) === JSON.stringify(previous.current) ? initial : f));
    previous.current = initial;
  }, [initial]);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [general, setGeneral] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const [owners, setOwners] = useState<DuplicateItem[]>([]);

  const set = (key: keyof Form, value: string) => {
    setForm((f) => ({ ...f, [key]: value }));
    setSaved(false);
  };
  const dirty = (Object.keys(form) as (keyof Form)[]).some((k) => form[k] !== initial[k]);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!dirty || busy) return;
    const body: Record<string, unknown> = {};
    for (const key of ["business_name", "category", "description", "city", "website", "instagram_url", "country"] as const) {
      if (form[key] !== initial[key]) body[key] = form[key];
    }
    const profile: Record<string, unknown> = {};
    for (const key of ["language", "business_type", "address"] as const) {
      if (form[key] !== initial[key]) profile[key] = form[key];
    }
    for (const key of ["product_categories", "product_names"] as const) {
      if (form[key] !== initial[key]) profile[key] = splitList(form[key]);
    }
    if (Object.keys(profile).length) body.profile = profile;

    setBusy(true);
    setErrors({});
    setGeneral([]);
    try {
      const updated = await g.patch<LeadDetail>(`/leads/${lead.id}/`, body);
      setForm(toForm(updated));
      setSaved(true);
      onSaved(updated);
    } catch (err) {
      const p = problem(err);
      const duplicates = p.body?.duplicates;
      if (p.status === 409 && Array.isArray(duplicates)) {
        setOwners(duplicates as DuplicateItem[]);
      } else if (p.errors?.length) {
        const { byField, general: rest } = groupErrors(p.errors, KNOWN);
        setErrors(byField);
        setGeneral(rest);
      } else {
        setGeneral([p.message]);
      }
    } finally {
      setBusy(false);
    }
  };

  const prov = (field: string, profile = false) => {
    const { text, title } = provenanceLabel(profile ? lead.profile.provenance : lead.provenance, field);
    return <Chip text={text} title={title} />;
  };
  const countries = meta?.countries ?? [];
  const countryKnown = !form.country || countries.some((c) => c.code === form.country);

  return (
    <Card>
      <form onSubmit={submit} noValidate className="space-y-5" data-testid="info-form">
        {general.length > 0 && (
          <Alert tone="bad" title="ذخیره نشد">
            <ul className="list-disc pr-5">{general.map((m) => <li key={m}>{m}</li>)}</ul>
          </Alert>
        )}
        {saved && !dirty && (
          <Alert tone="ok">
            <span data-testid="info-saved">ذخیره شد.</span>
          </Alert>
        )}

        <div className="grid gap-4 sm:grid-cols-2">
          <FormField label="نام کسب‌وکار" error={errors.business_name} extra={prov("business_name")} testId="f-business_name">
            <Input value={form.business_name} onChange={(e) => set("business_name", e.target.value)} />
          </FormField>
          <FormField label="دسته" error={errors.category} extra={prov("category")}>
            <Input value={form.category} onChange={(e) => set("category", e.target.value)} />
          </FormField>
          <FormField label="وب‌سایت" error={errors.website} extra={prov("website")} testId="f-website">
            <Input dir="ltr" style={{ textAlign: "left" }} value={form.website} onChange={(e) => set("website", e.target.value)} placeholder="https://shop.ir" />
          </FormField>
          <FormField label="پیجِ اینستاگرام" error={errors.instagram_url} extra={prov("instagram_url")} testId="f-instagram_url">
            <Input dir="ltr" style={{ textAlign: "left" }} value={form.instagram_url} onChange={(e) => set("instagram_url", e.target.value)} placeholder="https://www.instagram.com/shop/" />
          </FormField>
          <FormField label="کشور" error={errors.country} extra={prov("country")}>
            <Select value={form.country} onChange={(e) => set("country", e.target.value)}>
              <option value="">— نامشخص —</option>
              {!countryKnown && <option value={form.country}>{form.country}</option>}
              {countries.map((c) => (
                <option key={c.code} value={c.code}>
                  {c.name}
                </option>
              ))}
            </Select>
          </FormField>
          <FormField label="شهر" error={errors.city} extra={prov("city")}>
            <Input value={form.city} onChange={(e) => set("city", e.target.value)} />
          </FormField>
          <div className="sm:col-span-2">
            <FormField label="توضیحات" error={errors.description} extra={prov("description")}>
              <TextArea rows={4} value={form.description} onChange={(e) => set("description", e.target.value)} />
            </FormField>
          </div>
        </div>

        <div>
          <h3 className="mb-3 text-sm font-bold" style={{ color: "var(--text)" }}>
            پروفایلِ کسب‌وکار
          </h3>
          <div className="grid gap-4 sm:grid-cols-2">
            <FormField label="نوعِ کسب‌وکار" error={errors["profile.business_type"]} extra={prov("business_type", true)}>
              <Select value={form.business_type} onChange={(e) => set("business_type", e.target.value)}>
                {(meta?.business_types ?? [{ value: "unknown", label: "نامشخص" }]).map((b) => (
                  <option key={b.value} value={b.value}>
                    {b.label}
                  </option>
                ))}
              </Select>
            </FormField>
            <FormField label="زبانِ سایت / پیج" hint="کدِ کوتاه، مثل fa یا en" error={errors["profile.language"]} extra={prov("language", true)}>
              <Input dir="ltr" style={{ textAlign: "left" }} value={form.language} onChange={(e) => set("language", e.target.value)} placeholder="fa" />
            </FormField>
            <div className="sm:col-span-2">
              <FormField label="نشانی" error={errors["profile.address"]} extra={prov("address", true)}>
                <Input value={form.address} onChange={(e) => set("address", e.target.value)} />
              </FormField>
            </div>
            <FormField label="دسته‌های محصول" hint="با کاما جدا کنید" error={errors["profile.product_categories"]} extra={prov("product_categories", true)}>
              <Input value={form.product_categories} onChange={(e) => set("product_categories", e.target.value)} />
            </FormField>
            <FormField label="نامِ محصولات" hint="با کاما جدا کنید" error={errors["profile.product_names"]} extra={prov("product_names", true)}>
              <Input value={form.product_names} onChange={(e) => set("product_names", e.target.value)} />
            </FormField>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <Button type="submit" disabled={!dirty || busy} data-testid="info-save">
            {busy ? "در حال ذخیره…" : "ذخیرهٔ تغییرها"}
          </Button>
          {dirty && (
            <Button type="button" variant="secondary" onClick={() => setForm(initial)} disabled={busy}>
              برگرداندنِ تغییرها
            </Button>
          )}
          <span className="text-xs" style={{ color: "var(--text-3)" }}>
            هر مقداری که اینجا عوض کنید با منبعِ «ثبت دستی» و در تاریخچه ثبت می‌شود.
          </span>
        </div>
      </form>

      <OwningLeadDialog open={owners.length > 0} duplicates={owners} onClose={() => setOwners([])} />
    </Card>
  );
}
