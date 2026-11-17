import { useRef } from "react";

import Icon from "../../../components/Icon";
import { Button, Field, Input, Select, TextArea, fa } from "../../../components/ui";
import { FieldSpec, Library, Source } from "./api";

/** نامِ فارسیِ فیلدها (کلیدهای شمای قطعه‌ها در backend/apps/motion/components.py) */
export const FIELD_LABELS: Record<string, string> = {
  kicker: "عنوانِ کوچک (اختیاری)", title: "عنوان", subtitle: "زیرعنوان (اختیاری)", items: "موردها", numbered: "شماره‌دار", text: "متن", author: "گوینده (اختیاری)",
  value: "عدد", prefix: "پیش‌وند", suffix: "پس‌وند", label: "برچسب", count_up: "شمارشِ تدریجی", decimals: "رقمِ اعشار", before_label: "برچسبِ «قبل»", after_label: "برچسبِ «بعد»",
  before: "متنِ قبل", after: "متنِ بعد", before_image: "تصویرِ قبل", after_image: "تصویرِ بعد", name: "نام", price: "قیمت", badge: "برچسب", features: "ویژگی‌ها", image: "تصویر",
  tagline: "شعار", caption: "عنوان", bullets: "قابلیت‌ها", screenshot: "اسکرین‌شات", button: "متنِ دکمه", note: "یادداشت", bars: "میله‌ها", unit: "واحد", show_values: "نمایشِ عددها",
  horizontal: "افقی", points: "نقطه‌ها", slices: "بخش‌ها", center_label: "نوشتهٔ وسط", cards: "کارت‌ها", old_price: "قیمتِ قبلی", columns: "ستون‌ها", rows: "ردیف‌ها", highlight: "ستونِ برجسته",
  score: "امتیاز (۰ تا ۵)", count_label: "توضیحِ تعداد", from: "شروع از", finish_text: "نوشتهٔ پایان", role: "سمت", steps: "مراحل", layout: "چیدمان", icon: "آیکون", emoji: "ایموجی", quote: "نقل‌قول",
  rating: "ستاره (۰ تا ۵)", size: "اندازه", kind: "شکل", color: "رنگ", platform: "شبکه", handle: "نام‌کاربری / نشانی", tags: "برچسب‌ها", speed: "سرعت",
  values: "مقدارِ هر ستون (هر مورد یک خط)",
  // «شخصیتِ برند» (apps.brandchar): دو تصویرِ شفافِ همان شخصیت، کارِ او در صحنه، از کجا بیاید و در کدام سوی کادر بایستد
  image_a: "تصویرِ شخصیت (ایستاده)", image_b: "تصویرِ شخصیت (در حالِ حرکت)", action: "شخصیت چه کار کند؟", arrive: "از کجا وارد شود؟", side: "جای شخصیت در کادر", bubble: "حبابِ گفتار",
};

const KIND_FA: Record<string, string> = { burst: "انفجاری", circle: "دایره", tag: "برچسب", emoji: "ایموجیِ پرشی", horizontal: "افقی", vertical: "عمودی", accent: "رنگِ ۱", accent2: "رنگِ ۲", accent3: "رنگِ ۳" };

/** نامِ فارسیِ گزینه‌های هر فیلدِ enum؛ کلیدِ بیرونی نامِ فیلد است چون «left» در دو فیلدِ مختلف یک معنا ندارد (ورود از چپ ≠ ایستادن در چپ). گزینهٔ ناشناخته همان‌طور که هست دیده می‌شود. */
export const ENUM_FA: Record<string, Record<string, string>> = {
  action: { wave: "دست تکان‌دادن", point: "اشاره کردن", thumbs: "شستِ بالا (تأیید)", explain: "توضیح‌دادن", think: "فکر کردن" },
  arrive: { left: "از چپ", right: "از راست", bottom: "از پایین" },
  side: { left: "چپِ کادر", right: "راستِ کادر" },
  platform: { instagram: "اینستاگرام", telegram: "تلگرام", whatsapp: "واتس‌اپ", website: "وب‌سایت", youtube: "یوتیوب", aparat: "آپارات", eitaa: "ایتا", rubika: "روبیکا", phone: "تلفن", email: "ایمیل", app: "اپلیکیشن" },
};

/** برچسبِ یک منبعِ تصویر که (هنوز) در فهرستِ منبع‌ها نیست؛ مثلاً عکسِ کتابخانه‌ای که از بخشِ دیگری آمده */
export function refLabel(ref: string): string {
  const [head, tail = ""] = ref.split(":");
  const n = /^\d+$/.test(tail) ? ` ${fa(Number(tail))}` : "";
  if (ref === "store-logo") return "لوگوی فروشگاه";
  if (head === "photo") return `تصویرِ کتابخانهٔ ادیتورِ عکس${n}`;
  if (head === "upload") return `تصویرِ بارگذاری‌شده${n}`;
  if (head === "pimg") return `عکسِ محصول${n}`;
  if (head === "gimg") return `تصویرِ ساخته‌شده${n}`;
  return ref;
}

export function ImagePicker({ value, sources, onPick, onUpload }: { value: string; sources: Source[]; onPick: (ref: string) => void; onUpload?: (f: File) => void }) {
  const file = useRef<HTMLInputElement>(null);
  const current = sources.find((s) => s.ref === value);
  // مقدارِ فعلی که در فهرست نیست (مثلاً photo:<id> از «شخصیتِ برند») نباید «بدونِ تصویر» دیده شود: همان را نشان می‌دهیم تا انتخابِ فعلی گم نشود
  const orphan = value && !current ? value : "";
  return (
    <div className="flex items-center gap-2">
      {current ? <img src={current.url} alt="" className="h-10 w-10 rounded-lg object-cover" /> : <span className="h-10 w-10 rounded-lg" style={{ background: "var(--surface-2)" }} />}
      <div className="min-w-0 flex-1">
        <Select value={value} onChange={(e) => onPick(e.target.value)}>
          <option value="">— بدونِ تصویر —</option>
          {orphan ? <option value={orphan}>{refLabel(orphan)}</option> : null}
          {sources.map((s) => (
            <option key={s.ref} value={s.ref}>
              {s.group}: {s.title}
            </option>
          ))}
        </Select>
      </div>
      {onUpload ? (
        <>
          <input ref={file} type="file" accept="image/png,image/jpeg,image/webp" hidden onChange={(e) => e.target.files?.[0] && onUpload(e.target.files[0])} />
          <Button variant="secondary" size="sm" type="button" onClick={() => file.current?.click()}>
            <Icon name="upload" size={14} /> بارگذاری
          </Button>
        </>
      ) : null}
    </div>
  );
}

type Rec = Record<string, unknown>;
type Ctx = { lib: Library; sources: Source[]; onUpload?: (f: File) => void };

function Leaf({ name, spec, value, onChange, ctx }: { name: string; spec: FieldSpec; value: unknown; onChange: (v: unknown) => void; ctx: Ctx }) {
  const label = FIELD_LABELS[name] || name;
  if (spec.kind === "bool")
    return (
      <label className="flex items-center gap-2 text-sm" style={{ color: "var(--text-2)" }}>
        <input type="checkbox" checked={!!value} onChange={(e) => onChange(e.target.checked)} /> {label}
      </label>
    );
  if (spec.kind === "enum") {
    const iconField = (spec.choices?.length ?? 0) > 30;
    return (
      <Field label={label}>
        <Select value={String(value ?? "")} onChange={(e) => onChange(e.target.value || undefined)}>
          <option value="">— پیش‌فرض —</option>
          {(spec.choices ?? []).map((c) => (
            <option key={c} value={c}>
              {iconField ? `${ctx.lib.icon_labels[c] || ctx.lib.emoji_labels?.[c] || c} (${c})` : ENUM_FA[name]?.[c] || KIND_FA[c] || c}
            </option>
          ))}
        </Select>
      </Field>
    );
  }
  if (spec.kind === "num" || spec.kind === "int")
    return (
      <Field label={label} hint={spec.min !== undefined && spec.max !== undefined && spec.max < 1e8 ? `${fa(spec.min)} تا ${fa(spec.max)}` : undefined}>
        <input
          type="number"
          className="u-input"
          min={spec.min}
          max={spec.max && spec.max < 1e8 ? spec.max : undefined}
          step={spec.kind === "int" ? 1 : "any"}
          value={value === undefined || value === null ? "" : Number(value)}
          onChange={(e) => onChange(e.target.value === "" ? undefined : Number(e.target.value))}
        />
      </Field>
    );
  if (spec.kind === "ref")
    return (
      <Field label={label}>
        <ImagePicker value={String(value ?? "")} sources={ctx.sources} onPick={(r) => onChange(r || undefined)} onUpload={ctx.onUpload} />
      </Field>
    );
  if (spec.kind === "strs")
    return (
      <Field label={label} hint={`هر مورد در یک خط؛ حداکثر ${fa(spec.max_items ?? 6)}`}>
        <TextArea rows={3} value={(Array.isArray(value) ? (value as string[]) : []).join("\n")} onChange={(e) => onChange(e.target.value.split("\n"))} />
      </Field>
    );
  const long = (spec.max ?? 0) > 150;
  return (
    <Field label={label} hint={spec.max ? `حداکثر ${fa(spec.max)} نویسه` : undefined}>
      {long ? (
        <TextArea rows={2} value={String(value ?? "")} onChange={(e) => onChange(e.target.value)} maxLength={spec.max} />
      ) : (
        <Input value={String(value ?? "")} onChange={(e) => onChange(e.target.value)} maxLength={spec.max} />
      )}
    </Field>
  );
}

function Rows({ name, spec, value, onChange, ctx }: { name: string; spec: FieldSpec; value: unknown; onChange: (v: unknown) => void; ctx: Ctx }) {
  const rows = (Array.isArray(value) ? (value as Rec[]) : []) as Rec[];
  const fields = spec.fields ?? {};
  const max = spec.max_items ?? 6;
  const set = (i: number, k: string, v: unknown) => onChange(rows.map((r, j) => (j === i ? { ...r, [k]: v } : r)));
  const first = Object.keys(fields)[0];
  return (
    <div className="sm:col-span-2">
      <div className="mb-1 text-sm font-semibold" style={{ color: "var(--text-2)" }}>
        {FIELD_LABELS[name] || name} <span className="text-xs font-normal" style={{ color: "var(--text-3)" }}>(حداکثر {fa(max)})</span>
      </div>
      <div className="space-y-2">
        {rows.map((r, i) => (
          <div key={i} className="flex flex-wrap items-end gap-2 rounded-lg p-2" style={{ background: "var(--surface-2)" }}>
            {Object.entries(fields).map(([k, fs]) => (
              <div key={k} className={fs.kind === "strs" || fs.kind === "str" ? "min-w-[140px] flex-1" : "w-28"}>
                <Leaf name={k} spec={fs} value={r[k]} onChange={(v) => set(i, k, v)} ctx={ctx} />
              </div>
            ))}
            <Button variant="ghost" size="sm" type="button" onClick={() => onChange(rows.filter((_, j) => j !== i))} title="حذفِ ردیف">
              <Icon name="trash" size={14} />
            </Button>
          </div>
        ))}
        <Button variant="secondary" size="sm" type="button" disabled={rows.length >= max} onClick={() => onChange([...rows, first ? { [first]: "" } : {}])}>
          <Icon name="plus" size={14} /> افزودنِ ردیف
        </Button>
      </div>
    </div>
  );
}

/** فرمِ یک قطعه از روی شمای فیلدهایش؛ هر قطعه‌ای که به کتابخانه اضافه شود خودکار فرم دارد. */
export default function FieldsForm({ fields, value, onChange, lib, sources, onUpload }: { fields: Record<string, FieldSpec>; value: Rec; onChange: (v: Rec) => void; lib: Library; sources: Source[]; onUpload?: (f: File) => void }) {
  const ctx: Ctx = { lib, sources, onUpload };
  const set = (k: string, v: unknown) => {
    const next = { ...value };
    if (v === undefined) delete next[k];
    else next[k] = v;
    onChange(next);
  };
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      {Object.entries(fields).map(([k, fs]) => {
        if (fs.kind === "objs") return <Rows key={k} name={k} spec={fs} value={value[k]} onChange={(v) => set(k, v)} ctx={ctx} />;
        const wide = fs.kind === "strs" || fs.kind === "ref" || ((fs.kind === "str" && (fs.max ?? 0) > 150) as boolean);
        return (
          <div key={k} className={wide ? "sm:col-span-2" : ""}>
            <Leaf name={k} spec={fs} value={value[k]} onChange={(v) => set(k, v)} ctx={ctx} />
          </div>
        );
      })}
    </div>
  );
}
