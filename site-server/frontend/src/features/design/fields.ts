const fa = (v: number | string) => String(v).replace(/[0-9]/g, (d) => "۰۱۲۳۴۵۶۷۸۹"[Number(d)]);

/** تعریفِ فیلدهای فرمِ هر نوعِ صفحهٔ کاتالوگ و هر نوعِ اسلاید — هر نوعِ بک‌اند (apps/design_studio) اینجا فرم دارد (آزمون: tests/design-fields.test.ts). */
export type FieldDef = {
  k: string; l: string;
  t: "text" | "textarea" | "number" | "image" | "imagelist" | "products" | "product" | "lines" | "objs" | "select" | "check";
  sub?: FieldDef[]; opts?: { v: string; l: string }[]; min?: number; max?: number; wide?: boolean; help?: string;
};

const T = (k: string, l: string, extra: Partial<FieldDef> = {}): FieldDef => ({ k, l, t: "text", ...extra });
export const NOTES = (): FieldDef => ({ k: "notes", l: "یادداشتِ گوینده / توضیحِ داخلی", t: "textarea" });

export const CATALOG_FIELDS: Record<string, FieldDef[]> = {
  cover: [T("title", "عنوانِ جلد"), T("subtitle", "زیرعنوان (مثلاً «کاتالوگ محصولات»)"), T("tagline", "شعار"), T("date_text", "تاریخ/فصل"), { k: "image", l: "تصویرِ جلد", t: "image" }],
  toc: [T("title", "عنوان")],
  text: [T("title", "عنوان"), T("kicker", "برچسبِ بالا"), { k: "paragraphs", l: "پاراگراف‌ها", t: "lines" }, { k: "image", l: "تصویر", t: "image" }],
  grid: [T("title", "عنوانِ بخش"), T("kicker", "برچسبِ بالا"), { k: "cols", l: "ستون", t: "select", opts: [1, 2, 3, 4].map((n) => ({ v: String(n), l: fa(n) })) }, { k: "rows", l: "ردیف", t: "select", opts: [1, 2, 3, 4, 5].map((n) => ({ v: String(n), l: fa(n) })) }, { k: "products", l: "محصول‌ها", t: "products" }],
  hero: [{ k: "product", l: "محصولِ ویژه", t: "product" }, T("title", "عنوانِ دلخواه (خالی = نامِ محصول)"), { k: "text", l: "متنِ توضیح (خالی = توضیحِ ثبت‌شدهٔ محصول)", t: "textarea" }, { k: "points", l: "نکته‌ها (خالی = ویژگی‌های ثبت‌شده)", t: "lines" }],
  price_list: [T("title", "عنوان"), T("kicker", "برچسبِ بالا"), T("note", "یادداشتِ زیرِ جدول"), { k: "products", l: "محصول‌ها", t: "products" }],
  lookbook: [T("title", "عنوان"), T("kicker", "برچسبِ بالا"), { k: "images", l: "تصویرها", t: "imagelist" }, { k: "captions", l: "زیرنویس‌ها", t: "lines" }],
  steps: [T("title", "عنوان"), T("kicker", "برچسبِ بالا"), { k: "steps", l: "گام‌ها", t: "objs", sub: [T("title", "عنوان"), T("text", "توضیح")] }],
  divider: [T("title", "عنوان"), T("subtitle", "زیرعنوان")],
  back: [T("title", "عنوان"), { k: "text", l: "متن", t: "textarea" }, { k: "contacts", l: "راه‌های تماس", t: "objs", sub: [T("label", "برچسب"), T("value", "مقدار")] }],
};
export const DECK_FIELDS: Record<string, FieldDef[]> = {
  title: [T("title", "عنوانِ ارائه"), T("subtitle", "زیرعنوان"), T("kicker", "برچسب"), T("date", "تاریخ"), { k: "image", l: "تصویر", t: "image" }],
  agenda: [T("title", "عنوان"), { k: "items", l: "موضوع‌ها", t: "lines" }],
  text: [T("title", "عنوان"), { k: "bullets", l: "نکته‌ها", t: "lines" }, { k: "image", l: "تصویر", t: "image" }],
  product: [{ k: "product", l: "محصول", t: "product" }, T("title", "عنوانِ دلخواه"), { k: "text", l: "متنِ توضیح", t: "textarea" }, { k: "points", l: "نکته‌ها", t: "lines" }],
  comparison: [T("title", "عنوان"), { k: "items", l: "موردها (۲ یا ۳)", t: "objs", sub: [{ k: "product", l: "محصول", t: "product" }, { k: "points", l: "نکته‌ها", t: "lines" }, { k: "highlight", l: "برجسته", t: "check" }] }],
  stats: [T("title", "عنوان"), { k: "items", l: "آمار (فقط عددِ واقعی؛ منبع الزامی است)", t: "objs", sub: [T("value", "عدد"), T("label", "برچسب"), T("source", "منبع")] }],
  timeline: [T("title", "عنوان"), { k: "steps", l: "گام‌ها", t: "objs", sub: [T("title", "عنوان"), T("text", "توضیح")] }],
  team: [T("title", "عنوان"), { k: "members", l: "اعضا (اطلاعاتِ واقعی)", t: "objs", sub: [T("name", "نام"), T("role", "سمت")] }],
  cta: [T("title", "عنوان"), { k: "text", l: "متن", t: "textarea" }, T("button", "متنِ دکمه"), T("link", "نشانیِ دکمه (https://…)"), T("note", "یادداشت")],
  section: [T("title", "عنوان"), T("subtitle", "زیرعنوان")],
  image: [{ k: "image", l: "تصویر", t: "image" }, T("caption", "زیرنویس")],
};

