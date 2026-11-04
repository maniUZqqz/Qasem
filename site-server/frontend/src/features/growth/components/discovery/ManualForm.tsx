import { FormEvent, ReactNode, useState } from "react";
import { Link } from "react-router-dom";

import Icon from "../../../../components/Icon";
import { Alert, Button, Card, Input, Select, TextArea } from "../../../../components/ui";
import { g, problem } from "../../api";
import { useMeta } from "../../MetaContext";
import type { DuplicateItem, FieldError, LeadRow, ManualCheck, ManualMode, ManualResult } from "../../types";
import FormField, { groupErrors } from "../leads/FormField";
import { splitList } from "../leads/hooks";
import DuplicateDialog from "./DuplicateDialog";

type FieldKey =
  | "business_name" | "website" | "instagram" | "phone" | "email" | "whatsapp" | "telegram"
  | "category" | "description" | "country" | "city" | "address" | "tags" | "note";

const FIELDS: Record<FieldKey, { label: string; placeholder?: string; ltr?: boolean; multiline?: boolean; hint?: string }> = {
  business_name: { label: "نام کسب‌وکار", placeholder: "مثلاً فروشگاه گل‌سرخ" },
  website: { label: "آدرس وب‌سایت", placeholder: "shop.ir  یا  https://shop.ir", ltr: true },
  instagram: { label: "پیج اینستاگرام", placeholder: "https://instagram.com/shop  یا  @shop", ltr: true },
  phone: { label: "تلفن / موبایل", placeholder: "09121234567", ltr: true, hint: "چند شماره را با | یا ، جدا کنید. رقم‌های فارسی هم قبول است." },
  email: { label: "ایمیل", placeholder: "info@shop.ir", ltr: true, hint: "چند ایمیل را با | یا ، جدا کنید." },
  whatsapp: { label: "واتساپ", placeholder: "09121234567", ltr: true },
  telegram: { label: "تلگرام", placeholder: "https://t.me/shop  یا  @shop", ltr: true },
  category: { label: "دستهٔ کسب‌وکار", placeholder: "مثلاً پوشاک، آرایشی، لوازم جانبی" },
  description: { label: "توضیحات", multiline: true },
  country: { label: "کشور" },
  city: { label: "شهر", placeholder: "مثلاً تهران" },
  address: { label: "نشانی", placeholder: "اگر می‌دانید" },
  tags: { label: "برچسب‌ها", placeholder: "با کاما جدا کنید: vip، کمپین پاییز" },
  note: { label: "یادداشت", multiline: true, hint: "به‌عنوان اولین یادداشتِ لید ذخیره می‌شود." },
};

const MODES: Record<ManualMode, { required: FieldKey; optional: FieldKey[]; intro: ReactNode }> = {
  website_url: {
    required: "website",
    optional: ["business_name", "category", "country", "city", "tags", "note"],
    intro: "آدرسِ سایتِ کسب‌وکار را بدهید. فقط همان آدرس ذخیره می‌شود؛ سایت در این مرحله خوانده نمی‌شود (خواندنِ راه‌های تماس بعداً از «دیتابیس لیدها» و با دکمهٔ جدا انجام می‌شود).",
  },
  instagram_url: {
    required: "instagram",
    optional: ["business_name", "category", "country", "city", "tags", "note"],
    intro: "آدرسِ پیجِ اینستاگرام یا @نام‌کاربری را بدهید. همان چیزی که می‌دهید ذخیره می‌شود؛ سیستم هیچ‌وقت اینستاگرام را باز نمی‌کند و چیزی از آن نمی‌خواند.",
  },
  business_name: {
    required: "business_name",
    optional: ["category", "country", "city", "tags", "note"],
    intro: "فقط نامِ کسب‌وکار. بعداً می‌توانید آدرس و راه‌های تماس را به لید اضافه کنید.",
  },
  manual: {
    required: "business_name",
    optional: ["website", "instagram", "phone", "email", "whatsapp", "telegram", "category", "description", "country", "city", "address", "tags", "note"],
    intro: "هر چه از کسب‌وکار می‌دانید بنویسید؛ دست‌کم یکی از «نام»، «وب‌سایت»، «اینستاگرام»، «تلفن» یا «ایمیل» لازم است.",
  },
};

const FIELD_FA: Record<string, string> = {
  business_name: "نام", website: "وب‌سایت", instagram_url: "اینستاگرام", category: "دسته", description: "توضیحات",
  country: "کشور", city: "شهر", language: "زبان", business_type: "نوع کسب‌وکار", address: "نشانی",
  product_categories: "دسته‌های محصول", product_names: "نام محصولات",
};

type Done = { message: string; lead?: LeadRow; extra?: ReactNode };

/** One manual-entry form; the four tabs differ only in which fields are required and shown. */
export default function ManualForm({ mode }: { mode: ManualMode }) {
  const cfg = MODES[mode];
  const { meta, kindLabel } = useMeta();
  const keys: FieldKey[] = [cfg.required, ...cfg.optional.filter((k) => k !== cfg.required)];

  const [values, setValues] = useState<Record<string, string>>({ country: meta?.csv.default_country || "IR" });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [general, setGeneral] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [dups, setDups] = useState<DuplicateItem[]>([]);
  const [similar, setSimilar] = useState<LeadRow[]>([]);
  const [dupOpen, setDupOpen] = useState(false);
  const [dupBusy, setDupBusy] = useState(false);
  const [dupError, setDupError] = useState<string | null>(null);
  const [pendingSimilar, setPendingSimilar] = useState(false);
  const [done, setDone] = useState<Done | null>(null);

  const set = (key: string, value: string) => setValues((v) => ({ ...v, [key]: value }));

  const body = (resolution?: Record<string, unknown>) => {
    const out: Record<string, unknown> = { mode };
    for (const key of keys) {
      const raw = (values[key] ?? "").trim();
      if (!raw) continue;
      out[key] = key === "tags" ? splitList(raw) : raw;
    }
    if (resolution) out.resolution = resolution;
    return out;
  };

  const showErrors = (list: FieldError[]) => {
    const { byField, general: rest } = groupErrors(list, keys);
    setErrors(byField);
    setGeneral(rest);
  };

  const handleProblem = (err: unknown) => {
    const p = problem(err);
    const duplicates = p.body?.duplicates;
    if (p.status === 409 && Array.isArray(duplicates)) {
      setDups(duplicates as DuplicateItem[]);
      setDupError(null);
      setDupOpen(true);
    } else if (p.errors?.length) {
      showErrors(p.errors);
    } else {
      setGeneral([p.message]);
    }
  };

  const create = async () => {
    const result = await g.post<ManualResult>("/discovery/manual/", body());
    if (result.result === "created") {
      setDone({ message: "لید ساخته شد.", lead: result.lead });
    }
  };

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setErrors({});
    setGeneral([]);
    setPendingSimilar(false);
    try {
      const check = await g.post<ManualCheck>("/discovery/manual/check/", body());
      if (!check.valid) {
        showErrors(check.errors);
        return;
      }
      setSimilar(check.similar);
      if (check.duplicates.length) {
        setDups(check.duplicates);
        setDupError(null);
        setDupOpen(true);
        return;
      }
      if (check.similar.length) {
        setPendingSimilar(true);
        return;
      }
      await create();
    } catch (err) {
      handleProblem(err);
    } finally {
      setBusy(false);
    }
  };

  const confirmSimilar = async () => {
    setBusy(true);
    setPendingSimilar(false);
    try {
      await create();
    } catch (err) {
      handleProblem(err);
    } finally {
      setBusy(false);
    }
  };

  const merge = async (target: number, overwrite: string[]) => {
    setDupBusy(true);
    setDupError(null);
    try {
      const result = await g.post<ManualResult>("/discovery/manual/", body({ action: "merge", target_lead: target, overwrite_fields: overwrite }));
      if (result.result === "merged") {
        setDupOpen(false);
        setDone({
          message: "با لیدِ موجود ادغام شد.",
          lead: result.lead,
          extra: (
            <ul className="mt-2 space-y-1 text-sm" style={{ color: "var(--text-2)" }} data-testid="merge-result">
              {result.filled.length > 0 && <li>جای خالی پر شد: {result.filled.map((f) => FIELD_FA[f] ?? f).join("، ")}</li>}
              {result.overwritten.length > 0 && <li>جایگزین شد: {result.overwritten.map((f) => FIELD_FA[f] ?? f).join("، ")}</li>}
              {result.conflicts.length > 0 && <li>فرق داشتند و دست نخوردند: {result.conflicts.map((c) => c.label || FIELD_FA[c.field] || c.field).join("، ")}</li>}
              {result.contacts_added.length > 0 && <li>راهِ تماسِ تازه: {result.contacts_added.map((c) => `${kindLabel(c.kind)} ${c.value}`).join("، ")}</li>}
              {result.contacts_skipped.length > 0 && <li>مالِ لیدِ دیگری بود و اضافه نشد: {result.contacts_skipped.map((c) => `${kindLabel(c.kind)} ${c.value}`).join("، ")}</li>}
            </ul>
          ),
        });
      }
    } catch (err) {
      setDupError(problem(err).message);
    } finally {
      setDupBusy(false);
    }
  };

  const skip = () => {
    setDupOpen(false);
    setDone({ message: "رد شد؛ چیزی ثبت یا تغییر نکرد." });
  };

  const reset = () => {
    setValues({ country: meta?.csv.default_country || "IR" });
    setErrors({});
    setGeneral([]);
    setDone(null);
    setPendingSimilar(false);
  };

  if (done) {
    return (
      <Card>
        <div data-testid="manual-done">
          <Alert tone="ok" title={done.message}>
            {done.lead && (
              <Link to={`/growth/leads/${done.lead.id}`} className="font-medium" dir="auto" data-testid="manual-done-link">
                {done.lead.display_name} ← باز کردنِ لید
              </Link>
            )}
            {done.extra}
          </Alert>
          <div className="mt-4">
            <Button onClick={reset} data-testid="manual-again">
              <Icon name="plus" size={15} />
              ثبتِ موردِ دیگر
            </Button>
          </div>
        </div>
      </Card>
    );
  }

  const countries = meta?.countries ?? [{ code: "IR", name: "ایران" }];

  const renderField = (key: FieldKey) => {
    const f = FIELDS[key];
    const required = key === cfg.required && mode !== "manual";
    return (
      <div key={key} className={f.multiline || required ? "sm:col-span-2" : ""}>
        <FormField label={f.label} hint={f.hint} error={errors[key]} required={required} testId={`field-${key}`}>
          {key === "country" ? (
            <Select value={values.country ?? ""} onChange={(e) => set("country", e.target.value)} name="country">
              <option value="">— نامشخص —</option>
              {countries.map((c) => (
                <option key={c.code} value={c.code}>
                  {c.name}
                </option>
              ))}
            </Select>
          ) : f.multiline ? (
            <TextArea rows={3} value={values[key] ?? ""} onChange={(e) => set(key, e.target.value)} name={key} />
          ) : (
            <Input
              value={values[key] ?? ""}
              onChange={(e) => set(key, e.target.value)}
              name={key}
              placeholder={f.placeholder}
              dir={f.ltr ? "ltr" : undefined}
              style={f.ltr ? { textAlign: "left" } : undefined}
              autoComplete="off"
              data-autofocus={required ? "" : undefined}
            />
          )}
        </FormField>
      </div>
    );
  };

  return (
    <Card>
      <form onSubmit={onSubmit} noValidate data-testid={`manual-form-${mode}`} className="space-y-4">
        <p className="text-sm leading-7" style={{ color: "var(--text-2)" }}>
          {cfg.intro}
        </p>
        {general.length > 0 && (
          <Alert tone="bad" title="ثبت نشد">
            <ul className="list-disc pr-5" data-testid="manual-errors">
              {general.map((m) => (
                <li key={m}>{m}</li>
              ))}
            </ul>
          </Alert>
        )}
        <div className="grid gap-4 sm:grid-cols-2">{keys.map(renderField)}</div>

        {pendingSimilar && (
          <Alert
            tone="warn"
            title="لیدی با همین نام هست"
            action={
              <div className="flex flex-col gap-2">
                <Button size="sm" onClick={confirmSimilar} disabled={busy} data-testid="similar-confirm">
                  باز هم ثبت کن
                </Button>
                <Button size="sm" variant="secondary" onClick={() => setPendingSimilar(false)}>
                  بازگشت
                </Button>
              </div>
            }
          >
            <span data-testid="similar-hint">
              هم‌نام‌ها:{" "}
              {similar.map((s, i) => (
                <span key={s.id}>
                  {i > 0 && "، "}
                  <Link to={`/growth/leads/${s.id}`} target="_blank" rel="noopener" dir="auto">
                    {s.display_name}
                  </Link>
                </span>
              ))}
              . اگر کسب‌وکارِ دیگری است ثبتش کنید؛ اگر همان است، به‌جای ثبتِ دوباره لیدِ قبلی را باز کنید.
            </span>
          </Alert>
        )}

        <div className="flex flex-wrap items-center gap-3">
          <Button type="submit" disabled={busy} data-testid="manual-submit">
            {busy ? "در حال بررسی…" : "بررسی و ثبت"}
          </Button>
          <span className="text-xs" style={{ color: "var(--text-3)" }}>
            اگر این کسب‌وکار از قبل باشد، قبل از هر کاری نشانتان می‌دهیم.
          </span>
        </div>
      </form>

      <DuplicateDialog
        open={dupOpen}
        duplicates={dups}
        similar={similar}
        busy={dupBusy}
        error={dupError}
        onMerge={merge}
        onSkip={skip}
        onClose={() => !dupBusy && setDupOpen(false)}
      />
    </Card>
  );
}
