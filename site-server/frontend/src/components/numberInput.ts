/**
 * عددی که فارسی‌زبان تایپ می‌کند → عددی که برنامه می‌فهمد.
 *
 * صاحب فروشگاه «۳۰۰٬۰۰۰» می‌نویسد؛ کیبوردش همین را می‌دهد. `<input type="number">`
 * ارقام فارسی را بی‌صدا دور می‌ریخت (کادر خالی می‌ماند) و سرور هم «۳۰۰٬۰۰۰» را
 * با پیامی کلی رد می‌کرد. اینجا همان لحظه‌ی تایپ به لاتین برمی‌گردد و جداکننده‌ها
 * برمی‌افتند؛ آنچه نمی‌شود فهمید (حرف، منفی) حذف می‌شود *و گفته می‌شود* —
 * نه بی‌صدا.
 *
 * سمتِ سرور همین کار را می‌کند (`backend/apps/common/numbers.py`)، تا هر کلاینتی
 * همین بخشندگی را داشته باشد.
 *
 * بدون وابستگی به React؛ با esbuild آزمون می‌شود (tests/number-input.test.ts).
 */

const FA = "۰۱۲۳۴۵۶۷۸۹";
const AR = "٠١٢٣٤٥٦٧٨٩";

/** ارقام فارسی و عربی → لاتین. */
export function toLatinDigits(text: string): string {
  return text
    .replace(/[۰-۹]/g, (d) => String(FA.indexOf(d)))
    .replace(/[٠-٩]/g, (d) => String(AR.indexOf(d)));
}

/** ارقام لاتین → فارسی. */
export function toFaDigits(text: string | number): string {
  return String(text).replace(/[0-9]/g, (d) => FA[Number(d)]);
}

export interface CleanNumber {
  /** فقط ارقام لاتین (و یک «.» اگر اعشار مجاز باشد). */
  value: string;
  /** چیزی حذف شد که عدد نبود (حرف، علامتِ دیگر). */
  rejected: boolean;
  /** علامتِ منفی تایپ شد (حذف می‌شود؛ این فیلدها منفی نمی‌پذیرند). */
  negative: boolean;
}

/** جداکننده‌های هزارگان و فاصله‌های نامرئی که هنگام تایپ/چسباندن می‌آیند. */
const SEPARATORS = /[,٬،_'’\s   ‌‎‏⁦-⁩]/g;

export function cleanNumberInput(
  raw: string,
  opts: { decimals?: boolean; maxDigits?: number } = {},
): CleanNumber {
  const maxDigits = opts.maxDigits ?? 15;
  let text = toLatinDigits(raw ?? "").replace(SEPARATORS, "").replace(/٫/g, ".");

  const negative = /[-−–]/.test(text);
  text = text.replace(/[-−–]/g, "");

  let rejected = false;
  if (!opts.decimals && text.includes(".")) {
    // «300.000» = سیصد هزار (نقطه به‌جای جداکننده)؛ «1.5» برای تومان معنایی ندارد.
    if (/^\d{1,3}(\.\d{3})+$/.test(text)) text = text.replace(/\./g, "");
    else {
      rejected = true;
      text = text.replace(/\./g, "");
    }
  }

  let out = "";
  let seenDot = false;
  for (const ch of text) {
    if (ch >= "0" && ch <= "9") out += ch;
    else if (ch === "." && opts.decimals && !seenDot) {
      out += ch;
      seenDot = true;
    } else rejected = true;
  }

  // صفرهای ابتدایی («007» → «7»)؛ «0.5» دست نمی‌خورد.
  out = out.replace(/^0+(?=\d)/, "");
  if (out.replace(".", "").length > maxDigits) {
    out = out.slice(0, maxDigits + (seenDot ? 1 : 0));
    rejected = true;
  }
  return { value: out, rejected, negative };
}

/**
 * عددِ سرور → متنِ کادر: «300000.00» → «300000»، «1500.50» → «1500.5».
 * بدونش کادرِ عددی مقدارِ ذخیره‌شده را «۳۰۰۰۰۰۰۰» می‌دید (نقطه حذف می‌شد).
 */
export function plainNumber(value: unknown): string {
  if (value === null || value === undefined || value === "") return "";
  const s = toLatinDigits(String(value)).trim();
  if (!/^\d+(\.\d+)?$/.test(s)) return "";
  return s.includes(".") ? s.replace(/\.?0+$/, "") : s;
}

/** «۳۰۰٬۰۰۰» از «300000». برای مقدارِ خالی/نامعتبر: «». */
export function formatGrouped(value: string): string {
  if (!/^\d+(\.\d+)?$/.test(value)) return "";
  const [whole, frac] = value.split(".");
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, "٬");
  return toFaDigits(frac ? `${grouped}٫${frac}` : grouped);
}

/** پیام وقتی کاربر چیزی نوشت که عدد نبود. */
export function rejectedMessage(c: CleanNumber, decimals = false): string {
  if (c.negative) return "عدد منفی قبول نیست.";
  return decimals
    ? "فقط عدد بنویسید؛ ارقام فارسی هم اشکال ندارد."
    : "فقط عدد صحیح بنویسید؛ ارقام فارسی هم اشکال ندارد.";
}

/** خطای فیلدهای محصول از سرور → جمله‌ی فارسی با نامِ فارسیِ فیلد (نه «price: …»). */
export const FIELD_LABEL_FA: Record<string, string> = {
  price: "قیمت",
  compare_at_price: "قیمت قبل از تخفیف",
  cost_price: "قیمت تمام‌شده",
  price_override: "قیمت",
  stock_quantity: "موجودی",
  price_toman: "قیمت",
  name: "نام",
};

export function fieldErrorSentence(data: unknown): string | null {
  if (!data || typeof data !== "object") return null;
  const body = data as Record<string, unknown>;
  for (const key of Object.keys(FIELD_LABEL_FA)) {
    const v = body[key];
    const first = Array.isArray(v) ? v[0] : typeof v === "string" ? v : null;
    if (typeof first === "string" && first) {
      // پیام‌های فارسیِ سرور خودشان نامِ فیلد را دارند؛ انگلیسیِ پیش‌فرضِ DRF را با برچسب می‌گوییم.
      return /[؀-ۿ]/.test(first) ? first : `${FIELD_LABEL_FA[key]}: ${first}`;
    }
  }
  return null;
}
