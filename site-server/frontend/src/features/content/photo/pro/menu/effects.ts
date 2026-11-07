/**
 * دستورهای «جعبهٔ فیلترها» برای منو و جستجو. پارامترها و اجرا سمتِ سرور است (backend/apps/photoedit/effects.py)؛ فرمِ هر فیلتر از
 * `GET effects/` ساخته می‌شود. شناسه‌ها باید با سرور یکی باشد (آزمونِ tests_effects.py همین را وارسی می‌کند).
 */
import type { Command, MenuId } from "./registry";

type Row = { id: string; menu: MenuId; group: string; title: string; en: string; syn: string[]; tip: string };

export const EFFECT_ROWS: Row[] = [
  // ── فیلتر ‹ محو
  { id: "gaussian_blur", menu: "filter", group: "محو", title: "محوِ گاوسی", en: "Gaussian blur", syn: ["بلور", "تار کردن", "نرم کردن", "blur", "soften", "defocus"], tip: "کلِ تصویر یا ناحیهٔ انتخاب‌شده را نرم و تار می‌کند" },
  { id: "motion_blur", menu: "filter", group: "محو", title: "محوِ حرکتی", en: "Motion blur", syn: ["حرکت", "سرعت", "کشیدگی", "speed", "streak"], tip: "اثرِ حرکتِ سریع در یک جهت" },
  { id: "radial_blur", menu: "filter", group: "محو", title: "محوِ شعاعی (چرخشی / زوم)", en: "Radial blur", syn: ["زوم", "چرخشی", "spin", "zoom blur"], tip: "از یک مرکز به بیرون یا دورِ مرکز محو می‌کند" },
  { id: "box_blur", menu: "filter", group: "محو", title: "محوِ جعبه‌ای", en: "Box blur", syn: ["جعبه ای", "میانگین", "average blur"], tip: "محوِ ساده و سریع با میانگین‌گیری" },
  { id: "lens_blur", menu: "filter", group: "محو", title: "محوِ لنز (بوکه)", en: "Lens blur", syn: ["بوکه", "بوکِ", "عمق میدان", "bokeh", "depth of field", "dof"], tip: "تارشدنِ طبیعیِ لنز با نقطه‌های نورانیِ گرد" },
  { id: "surface_blur", menu: "filter", group: "محو", title: "محوِ حفظ‌کنندهٔ لبه (پوست‌صاف‌کن)", en: "Surface blur / Smart blur", syn: ["پوست", "صاف کردن پوست", "لطافت", "skin smoothing", "bilateral", "smart blur"], tip: "سطح‌های هموار را نرم می‌کند و لبه‌ها را نگه می‌دارد" },
  { id: "tilt_shift", menu: "filter", group: "محو", title: "محوِ شیفتِ شیب (ماکت‌نما)", en: "Tilt-shift", syn: ["تیلت شیفت", "ماکت", "مینیاتور", "miniature", "tilt shift"], tip: "فقط یک نوار واضح می‌ماند؛ صحنه مثلِ ماکتِ کوچک دیده می‌شود" },
  { id: "median", menu: "filter", group: "محو", title: "میانه (حذفِ لکه و نویزِ نقطه‌ای)", en: "Median", syn: ["مدین", "لکه", "نقطه", "despeckle"], tip: "هر نقطه را با میانهٔ همسایه‌هایش عوض می‌کند" },
  // ── تیز کردن
  { id: "unsharp_mask", menu: "filter", group: "تیز کردن", title: "شارپِ ماسکِ غیرتیز", en: "Unsharp mask", syn: ["شارپ", "تیز", "وضوح", "sharpen", "usm", "clarity"], tip: "جزئیات را واضح‌تر می‌کند" },
  { id: "smart_sharpen", menu: "filter", group: "تیز کردن", title: "شارپِ هوشمند (فقط روشنایی)", en: "Smart sharpen", syn: ["شارپ هوشمند", "تیز کردن", "sharpen", "luminance sharpen"], tip: "فقط روشنایی را تیز می‌کند تا رنگ‌ها لکه نشوند" },
  { id: "high_pass", menu: "filter", group: "تیز کردن", title: "بالاگذر (برای شارپِ حرفه‌ای)", en: "High pass", syn: ["های پس", "شارپ حرفه ای", "high-pass sharpen"], tip: "لایهٔ خاکستری با جزئیاتِ ریز؛ با حالتِ «همپوشانی» تیز می‌کند" },
  // ── نویز
  { id: "add_noise", menu: "filter", group: "نویز", title: "افزودنِ نویز (دانه)", en: "Add noise / grain", syn: ["دانه", "گرین", "فیلم", "grain", "film grain", "noise"], tip: "دانهٔ فیلم یا نویز به تصویر اضافه می‌کند" },
  { id: "reduce_noise", menu: "filter", group: "نویز", title: "کاهشِ نویز", en: "Reduce noise", syn: ["نویزگیری", "دانه دانه", "denoise", "noise reduction"], tip: "دانه‌دانه‌شدنِ عکسِ شب را کم می‌کند" },
  { id: "dust_scratches", menu: "filter", group: "نویز", title: "گردوغبار و خراش", en: "Dust & scratches", syn: ["خراش", "گردوغبار", "لک", "dust", "scratches", "despeckle"], tip: "لکه‌های کوچک و خراش را پاک می‌کند" },
  // ── تغییر شکل
  { id: "wave", menu: "filter", group: "تغییر شکل", title: "موج", en: "Wave", syn: ["موجی", "لرزش", "wavy", "sine"], tip: "تصویر را موجی می‌کند" },
  { id: "ripple", menu: "filter", group: "تغییر شکل", title: "موجِ آب (ریپل)", en: "Ripple", syn: ["آب", "ریپل", "water"], tip: "اثرِ موج‌های ریزِ آب" },
  { id: "twirl", menu: "filter", group: "تغییر شکل", title: "چرخش (گرداب)", en: "Twirl", syn: ["گرداب", "چرخش", "swirl", "vortex"], tip: "مرکزِ تصویر را مثلِ گرداب می‌پیچاند" },
  { id: "pinch", menu: "filter", group: "تغییر شکل", title: "جمع / باد کردن", en: "Pinch / Bulge", syn: ["باد", "جمع", "بزرگ کردن چشم", "bulge", "pinch", "squeeze"], tip: "مرکز را جمع یا باد می‌کند" },
  { id: "spherize", menu: "filter", group: "تغییر شکل", title: "کروی‌کردن", en: "Spherize", syn: ["کره", "کروی", "ماهی چشم", "fisheye", "sphere", "bulge"], tip: "تصویر را روی یک کره می‌اندازد" },
  { id: "lens_correction", menu: "filter", group: "تغییر شکل", title: "اصلاحِ لنز (اعوجاج و تاریکیِ گوشه)", en: "Lens correction", syn: ["اعوجاج", "بشکه ای", "تاریکی گوشه", "distortion", "barrel", "pincushion", "vignette fix"], tip: "کجیِ خط‌ها در لبهٔ عکس و تاریکیِ گوشه‌ها را درست می‌کند" },
  // ── سبک‌سازی
  { id: "emboss", menu: "filter", group: "سبک‌سازی", title: "برجسته (نقش‌برجسته)", en: "Emboss", syn: ["برجسته", "برجسته سازی", "relief", "bump"], tip: "تصویر مثلِ نقش‌برجسته دیده می‌شود" },
  { id: "find_edges", menu: "filter", group: "سبک‌سازی", title: "یافتنِ لبه‌ها (طرحِ خطی)", en: "Find edges", syn: ["لبه", "طرح خطی", "خط", "edge detect", "outline", "line art"], tip: "فقط خطوطِ اطرافِ اجسام را نشان می‌دهد" },
  { id: "mosaic", menu: "filter", group: "سبک‌سازی", title: "موزاییک (پیکسلی)", en: "Mosaic / Pixelate", syn: ["پیکسل", "موزاییک", "سانسور", "pixelate", "censor"], tip: "تصویر را به خانه‌های بزرگ تبدیل می‌کند (برای سانسور هم خوب است)" },
  { id: "crystallize", menu: "filter", group: "سبک‌سازی", title: "بلورین", en: "Crystallize", syn: ["بلور", "کریستال", "شیشه ای", "voronoi", "facet"], tip: "تصویر را به بلورهای رنگیِ کوچک می‌شکند" },
  { id: "halftone", menu: "filter", group: "سبک‌سازی", title: "نیم‌تن (نقطه‌چین)", en: "Halftone", syn: ["نیم تن", "نقطه چین", "چاپی", "dots", "comic", "pop art"], tip: "تصویر با نقطه‌های چاپی ساخته می‌شود" },
  { id: "watercolor", menu: "filter", group: "سبک‌سازی", title: "آبرنگ / نقاشی", en: "Watercolor / Painting", syn: ["آبرنگ", "نقاشی", "painting", "stylize", "paint effect"], tip: "عکس شبیهِ نقاشیِ آبرنگ می‌شود" },
  { id: "oil_paint", menu: "filter", group: "سبک‌سازی", title: "رنگ‌روغن", en: "Oil paint", syn: ["روغنی", "رنگ روغن", "oil painting", "mean shift"], tip: "سطح‌های رنگیِ یکدست شبیهِ نقاشیِ روغنی" },
  { id: "cartoon", menu: "filter", group: "سبک‌سازی", title: "کارتونی", en: "Cartoon", syn: ["کارتون", "انیمیشن", "toon", "comic", "poster edges"], tip: "رنگ‌های تخت با خطِ دورِ تیره" },
  { id: "pencil_sketch", menu: "filter", group: "سبک‌سازی", title: "طرحِ مدادی", en: "Pencil sketch", syn: ["مداد", "طراحی", "اسکچ", "sketch", "drawing", "charcoal"], tip: "عکس مثلِ طرحِ مدادی" },
  // ── رندر
  { id: "clouds", menu: "filter", group: "رندر", title: "ابر", en: "Clouds", syn: ["ابر", "مه", "دود", "fog", "smoke", "render clouds"], tip: "لایهٔ ابرِ تصادفی (با حالتِ ترکیبِ «صفحه») برای مه و دود" },
  { id: "lens_flare", menu: "filter", group: "رندر", title: "شعلهٔ لنز", en: "Lens flare", syn: ["فلر", "نورِ لنز", "خورشید", "flare", "sun", "light leak"], tip: "درخششِ نورِ خورشید در لنز" },
  { id: "spotlight", menu: "filter", group: "رندر", title: "نورِ نقطه‌ای (افکتِ نور)", en: "Lighting effects / Spotlight", syn: ["نور", "اسپات", "نورپردازی", "lighting", "spot", "light"], tip: "یک نورِ نقطه‌ای روی تصویر می‌اندازد و بقیه را تیره می‌کند" },
  // ── تصویر ‹ تنظیم‌های رنگیِ پخته‌شده
  { id: "invert", menu: "image", group: "تنظیم‌های رنگیِ پخته‌شده", title: "وارونه (نگاتیو)", en: "Invert", syn: ["نگاتیو", "معکوس رنگ", "negative"], tip: "رنگ‌ها را برعکس می‌کند" },
  { id: "posterize", menu: "image", group: "تنظیم‌های رنگیِ پخته‌شده", title: "پوستری", en: "Posterize", syn: ["پوستر", "تعدادِ رنگ", "levels reduce"], tip: "تعدادِ سطحِ رنگ را کم می‌کند" },
  { id: "threshold", menu: "image", group: "تنظیم‌های رنگیِ پخته‌شده", title: "آستانه (سیاه و سفید)", en: "Threshold", syn: ["سیاه سفید خالص", "باینری", "bitmap", "1-bit"], tip: "هر نقطه یا کاملاً سیاه یا کاملاً سفید می‌شود" },
  { id: "gradient_map", menu: "image", group: "تنظیم‌های رنگیِ پخته‌شده", title: "نقشهٔ شیب (دورنگ / سه‌رنگ)", en: "Gradient map / Duotone", syn: ["دورنگ", "سه رنگ", "دوتون", "duotone", "tritone", "color grading"], tip: "سایه‌ها و روشنایی‌ها را به رنگ‌هایی که می‌خواهید می‌برد" },
  { id: "photo_filter", menu: "image", group: "تنظیم‌های رنگیِ پخته‌شده", title: "فیلترِ رنگیِ عکاسی", en: "Photo filter", syn: ["فیلتر گرم", "فیلتر سرد", "گرم کردن", "warming filter", "cooling"], tip: "مثلِ فیلترِ شیشه‌ای جلوی لنز، تصویر را رنگ می‌دهد" },
  { id: "channel_mixer", menu: "image", group: "تنظیم‌های رنگیِ پخته‌شده", title: "میکسرِ کانال‌ها", en: "Channel mixer", syn: ["کانال", "میکس رنگ", "سیاه سفید با فیلتر", "channels", "rgb mixer"], tip: "هر کانالِ رنگ را با دیگری ترکیب کنید؛ برای سیاه‌وسفیدِ حرفه‌ای هم خوب است" },
  { id: "replace_color", menu: "image", group: "تنظیم‌های رنگیِ پخته‌شده", title: "جایگزینیِ رنگ", en: "Replace color", syn: ["عوض کردن رنگ", "تغییر رنگ", "رنگ لباس", "change color", "hue shift"], tip: "یک رنگِ مشخص (مثلاً قرمزِ کفش) را به رنگ دیگری تغییر می‌دهد" },
  { id: "equalize", menu: "image", group: "تنظیم‌های رنگیِ پخته‌شده", title: "یکسان‌سازیِ هیستوگرام", en: "Equalize", syn: ["هیستوگرام", "کنتراست خودکار", "histogram equalization"], tip: "روشنایی را در کلِ محدوده پخش می‌کند" },
  { id: "color_balance", menu: "image", group: "تنظیم‌های رنگیِ پخته‌شده", title: "تعادلِ رنگ (سایه / میانه / روشن)", en: "Color balance", syn: ["تعادل رنگ", "رنگ سایه", "رنگ‌دهی", "grading", "split toning"], tip: "به سایه‌ها، میانه‌ها و روشنایی‌ها رنگِ جدا بدهید" },
  // ── تصویر ‹ اندازه و بوم
  { id: "image_size", menu: "image", group: "اندازه و بوم", title: "اندازهٔ تصویر", en: "Image size / Resize", syn: ["ریسایز", "تغییر اندازه", "پیکسل", "resolution", "scale image", "dimensions"], tip: "عکسِ تازه‌ای با اندازهٔ دلخواه در کتابخانه می‌سازد" },
  { id: "canvas_size", menu: "image", group: "اندازه و بوم", title: "اندازهٔ بوم", en: "Canvas size", syn: ["بوم", "حاشیه", "بزرگ کردن بوم", "extend canvas", "padding", "expand"], tip: "بومِ بزرگ‌تر یا کوچک‌تر با لنگرِ دلخواه" },
  { id: "trim", menu: "image", group: "اندازه و بوم", title: "پاک‌کردنِ حاشیهٔ هم‌رنگ (Trim)", en: "Trim", syn: ["حاشیه", "برش خودکار", "crop transparent", "trim edges", "autocrop"], tip: "حاشیهٔ شفاف یا هم‌رنگ را می‌بُرد" },
  { id: "rotate_free", menu: "image", group: "اندازه و بوم", title: "چرخشِ دلخواهِ بوم", en: "Rotate canvas (arbitrary)", syn: ["چرخش دلخواه", "زاویه", "rotate any angle", "tilt"], tip: "تصویر را با هر زاویه می‌چرخاند؛ عکسِ تازه می‌سازد" },
  { id: "content_aware_scale", menu: "image", group: "اندازه و بوم", title: "مقیاسِ آگاه از محتوا", en: "Content-aware scale", syn: ["seam carving", "باریک کردن", "تغییر نسبت", "آگاه از محتوا", "retarget", "reshape without squash"], tip: "عکس را باریک می‌کند بی‌آنکه سوژه له شود" },
  // ── لایه ‹ سبکِ لایه (پخته‌شده)
  { id: "color_overlay", menu: "layer", group: "سبکِ لایه (پخته‌شده)", title: "پوششِ رنگ", en: "Color overlay", syn: ["رنگ روی لایه", "تینت", "tint", "layer style"], tip: "لایهٔ فعال را با یک رنگ می‌پوشاند (با حالتِ ترکیب)" },
  { id: "gradient_overlay", menu: "layer", group: "سبکِ لایه (پخته‌شده)", title: "پوششِ شیب", en: "Gradient overlay", syn: ["گرادینت روی لایه", "شیب رنگ", "layer style"], tip: "شیبِ دورنگ روی لایهٔ فعال" },
  { id: "inner_shadow", menu: "layer", group: "سبکِ لایه (پخته‌شده)", title: "سایهٔ درونی", en: "Inner shadow", syn: ["سایه داخلی", "فرورفتگی", "layer style"], tip: "سایه‌ای که از لبه‌ها به درونِ لایه می‌افتد" },
  { id: "inner_glow", menu: "layer", group: "سبکِ لایه (پخته‌شده)", title: "درخششِ درونی", en: "Inner glow", syn: ["درخشش داخلی", "نور لبه", "layer style"], tip: "نورِ ملایم از لبه‌ها به درونِ لایه" },
  { id: "bevel_emboss", menu: "layer", group: "سبکِ لایه (پخته‌شده)", title: "برجسته‌سازی (بوِل)", en: "Bevel & emboss", syn: ["بول", "برجسته", "سه بعدی", "bevel", "emboss", "layer style"], tip: "لبه‌های لایه برجسته و براق دیده می‌شود" },
  { id: "pattern_overlay", menu: "layer", group: "سبکِ لایه (پخته‌شده)", title: "پوششِ الگو", en: "Pattern overlay", syn: ["الگو", "راه راه", "نقطه چین", "pattern", "stripes", "dots", "layer style"], tip: "الگوی راه‌راه، نقطه‌چین یا شطرنجی روی لایه" },
  // ── ویرایش ‹ ترمیم
  { id: "remove_object", menu: "edit", group: "ترمیم", title: "حذفِ شیء (پرکردنِ سبک)", en: "Remove object / Inpaint", syn: ["پاک کردن", "حذف لکه", "حذف شیء", "inpaint", "content aware fill", "heal selection", "remove"], tip: "ناحیهٔ انتخاب‌شده را از اطراف پر می‌کند (برای لکه و خطِ نازک)" },
];

export function effectCommands(): Command[] {
  return EFFECT_ROWS.map((r) => ({
    id: `fx.${r.id}`,
    menu: r.menu,
    group: r.group,
    title: r.title,
    en: r.en,
    syn: ["فیلتر", "افکت", "filter", "effect", ...r.syn],
    tip: r.tip,
    run: (h) => h.effect(r.id),
    enabled: r.id === "remove_object" ? (h) => (h.s.hasSelection ? null : "اول ناحیه‌ای را انتخاب کنید") : r.group.startsWith("سبکِ لایه") ? (h) => (["image", "text", "shape"].includes(h.s.activeType ?? "") ? null : "اول یک لایهٔ تصویر، متن یا شکل را انتخاب کنید") : undefined,
  }));
}
