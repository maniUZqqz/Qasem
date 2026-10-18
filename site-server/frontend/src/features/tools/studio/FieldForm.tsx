import { Field, Input, Select, TextArea } from "../../../components/ui";
import { Check } from "./common";
import type { FieldT, ModelOption, Pair } from "./types";

/**
 * فرمِ مشترکِ افزودن/ویرایشِ فیلد — همان `_field_form.html` ِ قدیمی.
 * بخش‌ها بسته به نوعِ فیلد نشان داده می‌شوند (رابطه‌ای، متنی، اعشاری، تاریخ…).
 */

export type FieldFormState = {
  name: string;
  fa: string;
  field_type: string;
  related_model: string;
  on_delete: string;
  related_name: string;
  max_length: string;
  max_digits: string;
  decimal_places: string;
  date_mode: "" | "add" | "now";
  default: string;
  choices: string;
  help: string;
  blank: boolean;
  null: boolean;
  unique: boolean;
  db_index: boolean;
};

const RELATIONAL = new Set(["ForeignKey", "ManyToManyField", "OneToOneField"]);
const LENGTH = new Set(["CharField", "SlugField", "EmailField", "URLField"]);
const DATES = new Set(["DateField", "DateTimeField", "TimeField"]);
const CHOICES = new Set(["CharField", "IntegerField", "PositiveIntegerField"]);
const DEFAULT_OK = new Set([
  "CharField", "TextField", "IntegerField", "PositiveIntegerField", "BigIntegerField", "FloatField", "DecimalField",
  "BooleanField", "DateField", "DateTimeField", "TimeField", "EmailField", "URLField", "SlugField", "UUIDField", "JSONField",
]);

export function emptyField(): FieldFormState {
  return {
    name: "",
    fa: "",
    field_type: "CharField",
    related_model: "",
    on_delete: "CASCADE",
    related_name: "",
    max_length: "",
    max_digits: "",
    decimal_places: "",
    date_mode: "",
    default: "",
    choices: "",
    help: "",
    blank: false,
    null: false,
    unique: false,
    db_index: false,
  };
}

export function fromField(f: FieldT): FieldFormState {
  return {
    name: f.name,
    fa: f.verbose_name_fa,
    field_type: f.field_type,
    related_model: f.related_ref === "settings.AUTH_USER_MODEL" ? "__user__" : f.related_model ? String(f.related_model) : "",
    on_delete: f.on_delete || "CASCADE",
    related_name: f.related_name,
    max_length: f.max_length == null ? "" : String(f.max_length),
    max_digits: f.max_digits == null ? "" : String(f.max_digits),
    decimal_places: f.decimal_places == null ? "" : String(f.decimal_places),
    date_mode: f.auto_now_add ? "add" : f.auto_now ? "now" : "",
    default: f.default,
    choices: f.choices,
    help: f.help_text_fa,
    blank: f.blank,
    null: f.null,
    unique: f.unique,
    db_index: f.db_index,
  };
}

export default function FieldForm({
  value,
  onChange,
  fieldTypes,
  onDelete,
  allModels,
  disabled,
  errors = {},
}: {
  value: FieldFormState;
  onChange: (v: FieldFormState) => void;
  fieldTypes: Pair[];
  onDelete: Pair[];
  allModels: ModelOption[];
  disabled?: boolean;
  errors?: Record<string, string>;
}) {
  const t = value.field_type;
  const set = <K extends keyof FieldFormState>(k: K, v: FieldFormState[K]) => onChange({ ...value, [k]: v });

  return (
    <div className="space-y-3">
      <div className="grid gap-3 sm:grid-cols-3">
        <Field label="نامِ فیلد (انگلیسی)" hint={errors.name}>
          <Input value={value.name} onChange={(e) => set("name", e.target.value)} placeholder="title" required dir="ltr" pattern="[a-z][a-z0-9_]*" disabled={disabled} />
        </Field>
        <Field label="برچسبِ فارسی">
          <Input value={value.fa} onChange={(e) => set("fa", e.target.value)} placeholder="عنوان" disabled={disabled} />
        </Field>
        <Field label="نوع">
          <Select value={t} onChange={(e) => set("field_type", e.target.value)} disabled={disabled}>
            {fieldTypes.map(([v, l]) => (
              <option key={v} value={v}>
                {l} · {v}
              </option>
            ))}
          </Select>
        </Field>
      </div>

      {RELATIONAL.has(t) && (
        <div className="grid gap-3 sm:grid-cols-3">
          <Field label="مدلِ مقصد" hint={errors.related_model}>
            <Select value={value.related_model} onChange={(e) => set("related_model", e.target.value)} disabled={disabled}>
              <option value="">— انتخاب کن —</option>
              <option value="__user__">کاربرِ سایت (AUTH_USER_MODEL)</option>
              {allModels.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.label}
                  {m.verbose_name_fa ? ` — ${m.verbose_name_fa}` : ""}
                </option>
              ))}
            </Select>
          </Field>
          {t !== "ManyToManyField" && (
            <Field label="وقتی مقصد حذف شد">
              <Select value={value.on_delete} onChange={(e) => set("on_delete", e.target.value)} disabled={disabled}>
                {onDelete.map(([v, l]) => (
                  <option key={v} value={v}>
                    {l}
                  </option>
                ))}
              </Select>
            </Field>
          )}
          <Field label="نامِ برگشتی (related_name)">
            <Input value={value.related_name} onChange={(e) => set("related_name", e.target.value)} placeholder="posts" dir="ltr" disabled={disabled} />
          </Field>
        </div>
      )}

      <div className="grid gap-3 sm:grid-cols-3">
        {LENGTH.has(t) && (
          <Field label="حداکثر طول">
            <Input type="number" min={1} value={value.max_length} onChange={(e) => set("max_length", e.target.value)} placeholder="200" dir="ltr" disabled={disabled} />
          </Field>
        )}
        {t === "DecimalField" && (
          <>
            <Field label="تعدادِ رقم">
              <Input type="number" min={1} value={value.max_digits} onChange={(e) => set("max_digits", e.target.value)} placeholder="12" dir="ltr" disabled={disabled} />
            </Field>
            <Field label="رقمِ اعشار">
              <Input type="number" min={0} value={value.decimal_places} onChange={(e) => set("decimal_places", e.target.value)} placeholder="0" dir="ltr" disabled={disabled} />
            </Field>
          </>
        )}
        {DATES.has(t) && (
          <div>
            <span className="mb-1.5 block text-sm font-medium" style={{ color: "var(--text-2)" }}>
              مقدارِ خودکار
            </span>
            <div className="flex flex-wrap gap-3 text-sm" style={{ color: "var(--text-2)" }}>
              {(
                [
                  ["", "دستی"],
                  ["add", "زمانِ ساخت"],
                  ["now", "هر ذخیره"],
                ] as [FieldFormState["date_mode"], string][]
              ).map(([v, l]) => (
                <label key={v} className="inline-flex cursor-pointer items-center gap-1.5">
                  <input type="radio" name="studio-date-mode" checked={value.date_mode === v} onChange={() => set("date_mode", v)} disabled={disabled} />
                  {l}
                </label>
              ))}
            </div>
          </div>
        )}
        {DEFAULT_OK.has(t) && value.date_mode === "" && (
          <Field label="پیش‌فرض">
            <Input value={value.default} onChange={(e) => set("default", e.target.value)} placeholder="0 · True · متن" dir="ltr" disabled={disabled} />
          </Field>
        )}
      </div>

      {CHOICES.has(t) && (
        <Field label="گزینه‌ها (اختیاری؛ هر خط «مقدار=برچسب»)">
          <TextArea value={value.choices} onChange={(e) => set("choices", e.target.value)} rows={3} placeholder={"new=تازه\npaid=پرداخت‌شده\nsent=ارسال‌شده"} dir="ltr" disabled={disabled} />
        </Field>
      )}

      <Field label="راهنما (زیرِ فیلد در فرم‌ها)">
        <Input value={value.help} onChange={(e) => set("help", e.target.value)} placeholder="مثلاً: قیمت به تومان" disabled={disabled} />
      </Field>

      <div className="flex flex-wrap gap-4">
        <Check label="می‌تواند خالی باشد" checked={value.blank} onChange={(v) => set("blank", v)} disabled={disabled} />
        <Check label="NULL در دیتابیس" checked={value.null} onChange={(v) => set("null", v)} disabled={disabled} />
        <Check label="یکتا" checked={value.unique} onChange={(v) => set("unique", v)} disabled={disabled} />
        <Check label="ایندکس" checked={value.db_index} onChange={(v) => set("db_index", v)} disabled={disabled} />
      </div>
    </div>
  );
}
