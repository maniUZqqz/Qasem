/** برچسب‌های فارسیِ گزینه‌ها و پارامترهای طراحِ خودکار (کلیدها لاتین‌اند؛ کاربر فقط فارسی می‌بیند) */

export const OPT_FA: Record<string, Record<string, string>> = {
  role: { caption: "ریز", sub: "متنِ دوم", body: "متنِ معمولی", cta: "دکمه", badge: "برچسب", title: "تیتر", price: "قیمت", hero: "تیترِ درشت", display: "تیترِ خیلی درشت" },
  align: { right: "راست", center: "وسط", left: "چپ" },
  v: { start: "بالای جا", center: "وسطِ جا", end: "پایینِ جا" },
  plate: { none: "بدونِ کادر", auto: "خودکار", solid: "کادرِ تیره", pill: "قرصی", accent: "قرصِ رنگی" },
  style: { solid: "تک‌رنگ", gradient: "شیب", studio: "استودیویی" },
  edge: { top: "از بالا", bottom: "از پایین", left: "از چپ", right: "از راست", full: "روی همه" },
  kind: { contact: "سایهٔ زیرِ محصول", drop: "سایهٔ پشتِ محصول", both: "هر دو", spotlight: "نورِ نقطه‌ای", vignette: "تیرگیِ گوشه‌ها", circle: "گرد", pill: "قرصی" },
  fit: { cover: "پر کردن", contain: "جا دادن", keep: "همان‌جا", center: "وسط", hero: "درشت و وسطِ قاب" },
  shape: { rect: "مستطیل", ellipse: "بیضی", line: "خط" },
  position: { tl: "بالا-چپ", tr: "بالا-راست", bl: "پایین-چپ", br: "پایین-راست", bottom_center: "پایین، وسط", top_center: "بالا، وسط" },
  focus: { smart: "خودکار", center: "وسط", top: "بالا", bottom: "پایین", left: "چپ", right: "راست" },
  fill: { blur: "محوِ خودِ عکس", white: "سفید", black: "سیاه", color: "رنگِ دلخواه", transparent: "شفاف" },
  scope: { auto: "خودکار", photo: "فقط عکس", all: "همهٔ لایه‌ها" },
  turn: { "0": "بی‌چرخش", "90": "۹۰° پادساعتگرد", "180": "۱۸۰°", "270": "۹۰° ساعتگرد" },
  format: { jpeg: "JPEG", png: "PNG", webp: "WebP", square: "مربع ۱:۱", portrait: "عمودی ۴:۵", story: "استوری ۹:۱۶", landscape: "افقی ۱٫۹۱:۱", wide: "افقی ۱۶:۹", store: "مربعِ فروشگاه", orig: "اندازهٔ خودِ عکس" },
};

export const COLOR_FA: Record<string, string> = {
  auto: "خودکار", text: "رنگِ متنِ پالت", text_dim: "متنِ کم‌رنگ", accent: "رنگِ تأکید", accent_text: "متنِ روی رنگِ تأکید", plate: "رنگِ کادر",
  bg_a: "زمینه ۱", bg_b: "زمینه ۲", white: "سفید", black: "مشکی",
};

/** پارامترهایی که همیشه دیده می‌شوند؛ بقیه پشتِ «گزینه‌های بیشتر» اند */
export const PRIMARY: Record<string, string[]> = {
  text: ["text", "role", "slot", "align", "color", "font"],
  badge: ["text", "sub", "slot", "color"],
  shape: ["slot", "color", "opacity"],
  scrim: ["edge", "strength"],
  cutout: ["scale", "anchor_y"],
  backdrop: ["style", "c0", "c1"],
  shadow: ["strength"],
  local_adjust: ["kind", "strength"],
  frame: ["format", "fit"],
  logo: ["position", "size"],
  image: ["slot", "size"],
  compare: ["before", "after"],
  grade: ["scope"],
  rotate: ["turn", "straighten"],
  crop: ["x", "y", "w", "h"],
  export: ["format", "quality"],
  ai_fill: ["prompt"],
};

export const CRITERIA_FA: Record<string, string> = {
  hierarchy: "سلسله‌مراتب", legibility: "خوانایی", contrast: "کنتراست", margins: "حاشیه و حاشیهٔ امن", balance: "تعادل", color: "هماهنگیِ رنگ",
  typography: "تایپوگرافیِ فارسی", prompt_fit: "هم‌خوانی با دستور",
};

export const TOOL_ICON: Record<string, string> = {
  frame: "▭", cutout: "✂", backdrop: "▦", shadow: "◐", grade: "☼", local_adjust: "◉", scrim: "▤", shape: "◼", text: "T", badge: "●", logo: "★", image: "▣",
  compare: "◧", rotate: "↻", crop: "⌗", export: "⇩", ai_fill: "✦",
};

export const EXAMPLES = [
  "تبلیغِ کفش ورزشی، تخفیف ۳۰ درصد، همین حالا سفارش دهید",
  "پستِ «محصولِ جدید» برای قهوهٔ ترک، شیک و گرم",
  "عکسِ کاتالوگ با پس‌زمینهٔ سفید",
  "استوریِ حراجِ پاییزه، رنگی و پرانرژی",
  "برچسبِ قیمت: ۴۵۰ هزار تومان، قبلاً ۶۰۰ هزار تومان",
];

export const COPY_FIELDS: { key: string; label: string; ph: string }[] = [
  { key: "headline", label: "تیتر", ph: "مثلاً: حراجِ پاییزه" },
  { key: "subline", label: "متنِ دوم", ph: "مثلاً: تا پایانِ هفته" },
  { key: "price", label: "قیمت", ph: "مثلاً: ۴۵۰ هزار تومان" },
  { key: "old_price", label: "قیمتِ قبلی", ph: "مثلاً: ۶۰۰ هزار تومان" },
  { key: "discount", label: "درصدِ تخفیف", ph: "مثلاً: ۳۰" },
  { key: "cta", label: "متنِ دکمه", ph: "مثلاً: همین حالا بخرید" },
  { key: "badge", label: "برچسب", ph: "مثلاً: جدید" },
];

export function paramText(v: unknown): string {
  if (v === true) return "بله";
  if (v === false) return "خیر";
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v === "number") return String(Math.round(v * 1000) / 1000).replace(/[0-9]/g, (d) => "۰۱۲۳۴۵۶۷۸۹"[Number(d)]);
  return String(v);
}
