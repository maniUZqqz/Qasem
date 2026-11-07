/**
 * فهرستِ یگانهٔ دستورهای ادیتور عکس (نوبت ۴).
 *
 * هم «منوی کامل» (پرونده / ویرایش / تصویر / لایه / انتخاب / فیلتر / نما / پنجره / راهنما) و هم «جستجوی ابزار» (Ctrl+K)
 * از همین فهرست ساخته می‌شوند. قاعدهٔ طلایی: فقط چیزی در این فهرست است که واقعاً کار می‌کند — هر دستور یک تابعِ `run(host)`
 * دارد که حتماً یکی از کارهای Host را صدا می‌زند (آزمونِ واحدِ tests/photo-r4-registry.test.ts با یک Host ِ جعلی همین را وارسی می‌کند).
 *
 * هیچ‌چیزِ React یا DOM اینجا نیست؛ فقط داده + منطق، تا بشود در Node آزمود.
 */

export type MenuId = "file" | "edit" | "image" | "layer" | "select" | "filter" | "view" | "window" | "help";

export const MENUS: { id: MenuId; title: string }[] = [
  { id: "file", title: "پرونده" },
  { id: "edit", title: "ویرایش" },
  { id: "image", title: "تصویر" },
  { id: "layer", title: "لایه" },
  { id: "select", title: "انتخاب" },
  { id: "filter", title: "فیلتر" },
  { id: "view", title: "نما" },
  { id: "window", title: "پنجره" },
  { id: "help", title: "راهنما" },
];

export type PanelTab = "edit" | "layers" | "presets" | "smart" | "history" | "export";

/** وضعیتِ لحظه‌ای (فقط خواندنی) که دستورها برای فعال/غیرفعال بودن نگاه می‌کنند */
export type HostState = {
  hasActive: boolean;
  activeType: string | null;
  activeIsBase: boolean;
  activeLocked: boolean;
  activeHasMask: boolean;
  hasSelection: boolean;
  canUndo: boolean;
  canRedo: boolean;
  layerCount: number;
  /** لایهٔ فعال یک لایهٔ نقاشی است */
  activeIsPaint: boolean;
  storeFrameOn: boolean;
  nodeOn: boolean;
  /** ضبطِ اکشن روشن است (نوبت ۶) */
  recording: boolean;
  /** تعدادِ نقطه‌های مسیرِ قلم و بسته‌بودنش (نوبت ۷) */
  penPoints: number;
  penClosed: boolean;
};

/** کارهایی که فضای کار انجام می‌دهد؛ دستورها فقط همین‌ها را صدا می‌زنند */
export interface Host {
  s: HostState;
  // ابزار و پنل
  tool(id: string): void;
  tab(t: PanelTab): void;
  panelToggle(): void;
  undo(): void;
  redo(): void;
  zoom(kind: "fit" | "100" | "in" | "out"): void;
  compare(): void;
  helpToggle(): void;
  build(): void;
  exportPreset(key: string): void;
  storeFrame(): void;
  kit(key: string): void;
  /** «حذفِ پس‌زمینه با مدل…»: انتخابِ مدل و مقایسه (دورِ ۸) */
  matting(): void;
  /** قلم‌موی دلخواه: ذخیرهٔ قلمِ فعلی / ساختنِ نوک از تصویر / برداشتنِ نوک (دورِ ۸) */
  brushOp(op: "save" | "fromImage" | "clearTip"): void;
  fillGradient(): void;
  openPsd(): void;
  // تصویر
  rotate(delta: number): void;
  flip(axis: "h" | "v"): void;
  autoStraighten(): void;
  quickAuto(): void;
  // لایه‌ها
  addText(): void;
  addShape(kind: "rect" | "ellipse" | "line"): void;
  pickImage(): void;
  addLogo(): void;
  addAdjust(): void;
  addRetouch(): void;
  addWatermark(): void;
  duplicate(): void;
  remove(): void;
  mergeDown(): void;
  mergeVisible(): void;
  group(): void;
  ungroup(): void;
  newGroup(): void;
  toggleClip(): void;
  move(where: "up" | "down" | "top" | "bottom"): void;
  addMask(kind: "reveal" | "hide" | "linear" | "radial"): void;
  removeMask(): void;
  maskFromSelection(): void;
  paintMask(): void;
  // انتخاب
  selAll(): void;
  selClear(): void;
  selInvert(): void;
  selFeather(): void;
  pickSubject(): void;
  adjustFromSelection(): void;
  // نقاشی و عکس‌های لحظه‌ای (نوبت ۵)
  newPaint(): void;
  /** ویرایشِ مسیرِ قلم، ذخیرهٔ مسیر و کانال‌ها (نوبت ۷) */
  pathOp(op: "toSelection" | "toMask" | "toShape" | "close" | "addAnchors" | "deleteAnchor" | "smooth" | "reverse" | "save"): void;
  channels(): void;
  /** اکشن‌های ضبط‌شدنی (نوبت ۶): شروع/پایانِ ضبط و اجرای یک اکشنِ ذخیره‌شده */
  actionRecord(): void;
  actionStop(): void;
  actionPlay(id: number): void;
  /** خروجی با قالبِ دیگر از پروژه (نوبت ۶) */
  exportAs(fmt: "psd" | "tiff" | "pdf" | "gif" | "bmp" | "png" | "svg", mode?: "gray" | "cmyk" | "indexed" | "rgb16" | "lab"): void;
  /** ویژگی‌های متنِ لایهٔ فعال (نوبت ۶) */
  textFlag(k: "underline" | "strike" | "caps" | "vertical" | "justify"): void;
  /** متن روی مسیرِ قلم (on) / برداشتنِ مسیر (دورِ ۸) */
  textPath(on: boolean): void;
  textWarp(style: "arc" | "wave" | "flag" | "bulge" | "rise" | null): void;
  fillPaint(): void;
  clearPaint(): void;
  snapshotNew(): void;
  /** گسترش / انقباض / هموارسازی / حاشیهٔ انتخاب (با پنجرهٔ مقدار) */
  selOp(op: "grow" | "shrink" | "smooth" | "border"): void;
  selReselect(): void;
  selSave(): void;
  selLoad(): void;
  /** بازهٔ رنگ / عصای جادویی */
  colorRange(): void;
  // تنظیمات و طراحیِ گروهی (صفحهٔ ادیتور عکس)
  settings(tab: "ai" | "brand"): void;
  batch(): void;
  /** باز کردنِ فرمِ یک فیلتر/افکت از «جعبهٔ فیلترها» (effects.ts) */
  effect(id: string): void;
  /** ابزارهای افزوده‌شده در نوبت‌های بعد (فیلترها، سبک‌ها…) از همین راه می‌آیند */
  extra: Record<string, (arg?: unknown) => void>;
}

export type Command = {
  id: string;
  menu: MenuId;
  /** زیرگروه داخلِ منو (تیترِ بخش) */
  group: string;
  title: string;
  en: string;
  syn?: string[];
  /** فقط کلیدهایی که واقعاً بسته شده‌اند */
  key?: string;
  tip: string;
  run: (h: Host) => void;
  /** null = فعال؛ متن = دلیلِ غیرفعال بودن (به کاربر نشان داده می‌شود) */
  enabled?: (h: Host) => string | null;
};

/** دستورهای تنظیمات و طراحیِ گروهی؛ فقط وقتی صفحهٔ میزبان این کارها را بلد است به فهرست اضافه می‌شوند (تا دستورِ مرده نداشته باشیم). */
export function pageCommands(): Command[] {
  return [
    { id: "file.settingsAi", menu: "file", group: "تنظیمات", title: "پیش‌فرضِ کمکِ هوش مصنوعی (روشن / خاموش)", en: "AI assist default", syn: ["هوش مصنوعی", "خاموش کردن", "روشن کردن", "هزینه", "اعتبار", "ai", "off", "on", "assist", "settings", "تنظیمات"], tip: "تعیین کنید طراحِ خودکار پیش‌فرض از هوش مصنوعی کمک بگیرد یا نه؛ هزینه‌اش (تعدادِ فراخوانی) همان‌جا نوشته شده", run: (h) => h.settings("ai") },
    { id: "file.settingsBrand", menu: "file", group: "تنظیمات", title: "سبکِ برند (رنگ، فونت، لوگو، لحن)", en: "Brand style", syn: ["برند", "رنگ برند", "لوگو", "فونت برند", "لحن", "brand kit", "brand", "logo", "tone", "colors"], tip: "یک بار ذخیره کنید؛ طراحِ خودکار و طراحیِ گروهی پیش‌فرض از آن استفاده می‌کنند", run: (h) => h.settings("brand") },
    { id: "file.batch", menu: "file", group: "طراحیِ خودکار", title: "طراحیِ گروهیِ چند عکس", en: "Batch design", syn: ["گروهی", "دسته ای", "چند عکس", "همه عکس ها", "batch", "bulk", "zip", "طراحی خودکار"], tip: "یک الگو و سبکِ برند روی چند عکس؛ مرور در جدول، ویرایشِ تکی و دریافتِ همه در یک zip", run: (h) => h.batch() },
  ];
}

/** یک دستور برای هر اکشنِ ذخیره‌شده (Ctrl+K ⇒ «اجرای اکشن…»)؛ فقط وقتی فضای کار اکشن‌ها را بلد است به فهرست اضافه می‌شود */
export function actionCommands(items: { id: number; name: string }[]): Command[] {
  return items.map((it) => ({
    id: `action.run.${it.id}`, menu: "edit" as const, group: "اکشن‌های من", title: `اجرای اکشن: ${it.name}`, en: `Run action: ${it.name}`,
    syn: ["اکشن", "اجرا", it.name, "run action", "play"], tip: "همهٔ گام‌های ضبط‌شدهٔ این اکشن را روی عکسِ باز اجرا می‌کند؛ با یک برگشت (Ctrl+Z) همه یک‌جا برمی‌گردد",
    run: (h: Host) => h.actionPlay(it.id),
  }));
}

export type ToolMeta = { id: string; key: string; title: string; hint: string };

// ───────────────────────── شرط‌های فعال‌بودن (پیام‌ها فارسی و رهنما)
const needLayer = (h: Host) => (h.s.hasActive ? null : "اول یک لایه را انتخاب کنید");
const needEditable = (h: Host) => (!h.s.hasActive ? "اول یک لایه را انتخاب کنید" : h.s.activeIsBase ? "این کار روی عکسِ اصلی نیست؛ یک لایه بسازید" : h.s.activeLocked ? "لایه قفل است" : null);
const needMask = (h: Host) => needEditable(h) ?? (h.s.activeHasMask ? null : "این لایه ماسک ندارد");
const needNoMask = (h: Host) => needEditable(h) ?? (h.s.activeHasMask ? "این لایه از قبل ماسک دارد" : null);
const needSelection = (h: Host) => (h.s.hasSelection ? null : "اول ناحیه‌ای را انتخاب کنید");

export const TOOL_META: Record<string, { en: string; syn: string[] }> = {
  move: { en: "Move / Transform", syn: ["جابجایی", "انتقال", "اندازه", "چرخش", "تبدیل آزاد", "free transform", "scale", "rotate"] },
  hand: { en: "Hand / Zoom", syn: ["دست", "پن", "پیمایش", "pan", "scroll"] },
  crop: { en: "Crop", syn: ["کراپ", "برش", "قاب", "نسبت", "ابعاد", "crop tool", "aspect"] },
  straighten: { en: "Straighten / Rotate", syn: ["صاف کردن", "افق", "کج", "چرخاندن", "horizon", "tilt", "level"] },
  persp: { en: "Perspective", syn: ["پرسپکتیو", "اعوجاج", "ساختمان", "keystone", "distort"] },
  text: { en: "Type", syn: ["نوشتن", "تایپ", "فونت", "type tool", "text tool", "typography"] },
  brush: { en: "Mask Brush", syn: ["براش", "قلم نقاشی", "قلمو", "paint", "brush", "ماسک"] },
  gradient: { en: "Gradient (local)", syn: ["گرادینت", "شیب", "گرادیان", "gradient tool", "linear", "radial", "graduated filter"] },
  clone: { en: "Clone Stamp", syn: ["کلون", "مهر", "کپی نقطه", "stamp", "duplicate area"] },
  heal: { en: "Healing Brush", syn: ["ترمیم", "اصلاح پوست", "لکه", "heal", "retouch", "blemish"] },
  spot: { en: "Spot Healing", syn: ["لکه", "جوش", "گردوغبار", "spot", "dust", "remove blemish"] },
  marquee: { en: "Rectangular Marquee", syn: ["انتخاب مربع", "مستطیل", "select box", "rectangle select"] },
  ellipse: { en: "Elliptical Marquee", syn: ["انتخاب دایره", "بیضی", "oval select", "circle select"] },
  lasso: { en: "Lasso", syn: ["لاسو", "کمند", "انتخاب آزاد", "freehand select"] },
  subject: { en: "Select Subject", syn: ["سوژه", "انتخاب خودکار", "quick selection", "auto select", "object select"] },
  wb: { en: "White Balance Picker", syn: ["قطره چکان", "تعادل سفیدی", "رنگ زدگی", "eyedropper", "white balance", "color cast"] },
  redeye: { en: "Red Eye", syn: ["قرمزی چشم", "چشم قرمز", "red-eye"] },
  pen: { en: "Pen", syn: ["پن", "مسیر", "بزیه", "منحنی", "path", "bezier", "vector"] },
  liquify: { en: "Liquify", syn: ["مایع", "لاغری", "تغییر شکل", "warp", "reshape", "push", "bloat", "pucker"] },
  paint: { en: "Brush", syn: ["قلم", "نقاشی", "رنگ", "براش", "قلمو", "برس", "paint", "brush", "draw", "airbrush", "spray"] },
  pencil: { en: "Pencil", syn: ["مداد", "پیکسلی", "pencil", "pixel", "draw"] },
  eraser: { en: "Eraser", syn: ["پاک کن", "پاک‌کن", "پاک کردن", "eraser", "erase", "rubber"] },
  bucket: { en: "Paint Bucket", syn: ["سطل", "سطل رنگ", "پر کردن", "رنگ کردن ناحیه", "bucket", "paint bucket", "fill", "flood fill"] },
  history: { en: "History Brush", syn: ["تاریخچه", "بازگرداندن", "برگرداندن موضعی", "history brush", "restore", "revert area"] },
  blur: { en: "Blur tool", syn: ["محو", "ابزار محو", "نرم کردن", "blur", "soften", "smooth brush"] },
  sharpen: { en: "Sharpen tool", syn: ["تیز", "ابزار تیز", "وضوح", "sharpen", "sharpen brush", "crisp"] },
  dodge: { en: "Dodge tool", syn: ["روشن کننده", "روشن‌کردن موضعی", "دوج", "dodge", "lighten brush", "brighten brush"] },
  burn: { en: "Burn tool", syn: ["تیره کننده", "تیره‌کردن موضعی", "برن", "burn", "darken brush", "shadow brush"] },
  sponge: { en: "Sponge tool", syn: ["اسفنج", "اشباع موضعی", "sponge", "saturate brush", "desaturate brush"] },
  smudge: { en: "Smudge tool", syn: ["لکه کش", "لکه‌کش", "انگشت", "کشیدن رنگ", "smudge", "finger", "drag color"] },
  picker: { en: "Eyedropper", syn: ["قطره چکان", "برداشتن رنگ", "رنگ", "eyedropper", "color picker", "sample color", "pipette"] },
  genfill: { en: "Generative Fill", syn: ["هوش مصنوعی", "حذف شیء", "پر کردن", "inpaint", "remove object", "content aware", "ai fill"] },
};

// ───────────────────────── ساختنِ فهرست
export function buildCommands(tools: ToolMeta[], extra: Command[] = []): Command[] {
  const C: Command[] = [];
  const add = (c: Command) => C.push(c);

  // ── پرونده
  add({ id: "file.build", menu: "file", group: "ساخت و ذخیره", title: "ساختِ نسخهٔ نهایی", en: "Export / Save final", syn: ["ذخیره", "خروجی", "save", "render", "export", "دانلود"], tip: "همهٔ ویرایش‌ها را روی عکسِ اصلی اعمال می‌کند و نسخهٔ تازه‌ای می‌سازد (عکسِ اصلی دست‌نخورده می‌ماند)", run: (h) => h.build() });
  add({ id: "file.exportTab", menu: "file", group: "ساخت و ذخیره", title: "تنظیمِ خروجی (قالب، کیفیت، حجم)", en: "Export settings", syn: ["قالب", "jpg", "png", "webp", "کیفیت", "حجم", "format", "quality"], tip: "قالبِ فایل، کیفیت و سقفِ حجم را تعیین کنید", run: (h) => h.tab("export") });
  add({ id: "file.placeImage", menu: "file", group: "افزودن به صفحه", title: "افزودنِ عکس از کامپیوتر…", en: "Place image", syn: ["آپلود", "بارگذاری", "درج عکس", "upload", "import", "open", "place embedded"], tip: "یک عکس از کامپیوتر انتخاب کنید؛ به‌صورتِ لایهٔ تازه روی بوم می‌نشیند", run: (h) => h.pickImage() });
  add({ id: "file.addLogo", menu: "file", group: "افزودن به صفحه", title: "افزودنِ لوگوی فروشگاه", en: "Place logo", syn: ["لوگو", "آرم", "برند", "logo", "brand"], tip: "لوگوی ثبت‌شدهٔ فروشگاه را به‌صورتِ لایه می‌گذارد", run: (h) => h.addLogo() });
  add({ id: "file.addWatermark", menu: "file", group: "افزودن به صفحه", title: "افزودنِ مهر / واترمارک", en: "Add watermark", syn: ["واترمارک", "مهر", "watermark", "stamp"], tip: "نامِ فروشگاه را کم‌رنگ و تکرارشونده روی عکس می‌گذارد", run: (h) => h.addWatermark() });
  for (const [k, fa, en, syn, tip] of [
    ["psd", "ذخیره به‌صورتِ فایلِ لایه‌دار (PSD)", "Save layered file (PSD)", ["لایه دار", "فایل لایه ای", "psd", "layered", "export layers"], "هر لایه (عکس، تصویر، نقاشی، متن، شکل) جدا در یک فایلِ PSD می‌آید تا در نرم‌افزارهای دیگر ویرایش شود؛ لایه‌های تنظیم فقط در تصویرِ ترکیبیِ فایل اثر دارند"],
    ["tiff", "خروجی TIFF", "Export TIFF", ["تیف", "tif", "tiff", "چاپ", "کیفیت بالا", "lossless"], "فایلِ بی‌افت (با شفافیت) برای چاپ و بایگانی"],
    ["pdf", "خروجی PDF", "Export PDF", ["پی دی اف", "pdf", "سند", "کاتالوگ"], "عکسِ نهایی در یک صفحهٔ PDF (برای ارسال یا چاپ)"],
    ["gif", "خروجی GIF", "Export GIF", ["جیف", "gif", "۲۵۶ رنگ"], "تصویرِ ثابتِ GIF با ۲۵۶ رنگ"],
    ["bmp", "خروجی BMP", "Export BMP", ["بی ام پی", "bmp", "bitmap"], "فایلِ ساده و بی‌فشرده"],
  ] as const) {
    add({ id: `file.export.${k}`, menu: "file", group: "خروجی با قالبِ دیگر", title: fa, en, syn: [...syn], tip, run: (h) => h.exportAs(k) });
  }
  add({ id: "file.export.svg", menu: "file", group: "خروجی با قالبِ دیگر", title: "خروجی SVG (فقط شکل‌ها)", en: "Export SVG (shapes)", syn: ["اس وی جی", "svg", "برداری", "وکتور", "vector", "لوگو برداری"], tip: "لایه‌های شکل (مستطیل، بیضی، خط، مسیر و شکل‌های آماده) به‌صورتِ فایلِ برداری؛ عکس و متن در SVG نمی‌آید", run: (h) => h.exportAs("svg") });
  for (const [k, fmt, mode, fa, en, syn, tip] of [
    ["gray", "png", "gray", "خروجیِ سیاه‌وسفید (۸ بیت)", "Export grayscale", ["خاکستری", "سیاه و سفید", "grayscale", "gray", "تک کانال"], "تصویر با یک کانالِ روشنایی (PNG)؛ کم‌حجم‌تر و مناسبِ چاپِ سیاه‌وسفید"],
    ["cmyk", "tiff", "cmyk", "خروجیِ CMYK (TIFF، تبدیلِ ساده)", "Export CMYK", ["سی ام وای کی", "cmyk", "چاپخانه", "چاپ", "جوهر"], "چهار کانالِ جوهر برای چاپخانه؛ تبدیلِ ساده است (بی پروفایلِ ماشین) — اگر دقتِ رنگ مهم است همان RGB را به چاپخانه بدهید"],
    ["indexed", "png", "indexed", "خروجیِ ۲۵۶ رنگ (PNG)", "Export indexed color", ["۲۵۶ رنگ", "پالت", "indexed", "palette", "کم حجم", "آیکون"], "تصویر با پالتِ ۲۵۶ رنگ (برای آیکون و گرافیکِ ساده)"],
    ["rgb16", "tiff", "rgb16", "خروجیِ ۱۶ بیت (TIFF)", "Export 16-bit TIFF", ["۱۶ بیت", "16 bit", "16-bit", "عمق رنگ", "tiff16", "هایبیت"], "فایلِ ۱۶ بیت در هر کانال برای نرم‌افزارهایی که می‌خواهند؛ ترکیبِ ما ۸ بیتی است و دقتِ بیشتری ساخته نمی‌شود"],
    ["lab", "tiff", "lab", "خروجیِ Lab (TIFF)", "Export Lab TIFF", ["لب", "lab", "cielab", "l*a*b"], "فضای رنگیِ CIE L*a*b* برای کارهای رنگ‌سنجی و چاپ"],
  ] as const) {
    add({ id: `file.export.${k}`, menu: "file", group: "خروجی با حالتِ رنگ", title: fa, en, syn: [...syn], tip, run: (h) => h.exportAs(fmt, mode) });
  }
  add({ id: "file.exportInstagram", menu: "file", group: "اندازه‌های آمادهٔ خروجی", title: "اندازهٔ اینستاگرام", en: "Instagram size", syn: ["اینستا", "پست", "instagram", "square", "post"], tip: "قاب و قالبِ فایل برای پستِ اینستاگرام تنظیم می‌شود", run: (h) => h.exportPreset("insta") });
  add({ id: "file.exportStory", menu: "file", group: "اندازه‌های آمادهٔ خروجی", title: "اندازهٔ استوری", en: "Story size", syn: ["استوری", "ریلز", "story", "reels", "9:16"], tip: "قابِ عمودیِ ۹:۱۶", run: (h) => h.exportPreset("story") });
  add({ id: "file.exportBanner", menu: "file", group: "اندازه‌های آمادهٔ خروجی", title: "بنرِ سایت و تلگرام", en: "Banner size", syn: ["بنر", "تلگرام", "banner", "telegram", "cover"], tip: "۱۲۰۰×۶۳۰، تا ۲۵۰ کیلوبایت", run: (h) => h.exportPreset("banner") });
  add({ id: "file.exportMarket", menu: "file", group: "اندازه‌های آمادهٔ خروجی", title: "بازار و فروشگاه", en: "Marketplace size", syn: ["بازار", "فروشگاه", "market", "shop", "product photo", "مربع"], tip: "مربعِ ۲۰۰۰ با زمینهٔ سفید و کالا وسط، تا ۵۰۰ کیلوبایت", run: (h) => h.exportPreset("market") });
  add({ id: "file.exportChat", menu: "file", group: "اندازه‌های آمادهٔ خروجی", title: "واتساپ و پیام‌رسان", en: "Messenger size", syn: ["واتساپ", "پیام رسان", "whatsapp", "chat", "کم حجم"], tip: "ضلعِ بلند ۱۶۰۰ و تا ۲۰۰ کیلوبایت", run: (h) => h.exportPreset("chat") });

  // ── ویرایش
  add({ id: "edit.undo", menu: "edit", group: "تاریخچه", title: "برگرداندن", en: "Undo", syn: ["بازگشت", "undo", "عقب"], key: "Ctrl+Z", tip: "آخرین کار را برمی‌گرداند", run: (h) => h.undo(), enabled: (h) => (h.s.canUndo ? null : "کاری برای برگرداندن نیست") });
  add({ id: "edit.redo", menu: "edit", group: "تاریخچه", title: "از نو", en: "Redo", syn: ["جلو", "redo", "تکرار"], key: "Ctrl+Shift+Z", tip: "کارِ برگردانده‌شده را دوباره اعمال می‌کند", run: (h) => h.redo(), enabled: (h) => (h.s.canRedo ? null : "کاری برای تکرار نیست") });
  add({ id: "edit.history", menu: "edit", group: "تاریخچه", title: "فهرستِ تاریخچه", en: "History panel", syn: ["تاریخچه", "history", "گام ها"], tip: "همهٔ کارها را ببینید و به هر مرحله بپرید", run: (h) => h.tab("history") });
  add({ id: "action.record", menu: "edit", group: "اکشن (ضبط و اجرا)", title: "شروعِ ضبطِ اکشن", en: "Record action", syn: ["اکشن", "ضبط", "ماکرو", "تکرارِ کارها", "کارهای تکراری", "ضبط کارها", "record", "macro", "actions", "automate", "repeat"], tip: "از این لحظه تنظیمِ نور و رنگ، برش، متن، لوگو و لایه‌های بی‌پیکسلی که می‌سازید ثبت می‌شود تا با یک کلیک روی هر عکسِ دیگر اجرا شود (نقاشی و ترمیمِ همین عکس ثبت نمی‌شود)", run: (h) => h.actionRecord(), enabled: (h) => (h.s.recording ? "ضبط همین حالا روشن است" : null) });
  add({ id: "action.stop", menu: "edit", group: "اکشن (ضبط و اجرا)", title: "پایانِ ضبط و ذخیرهٔ اکشن", en: "Stop recording and save action", syn: ["توقف ضبط", "ذخیره اکشن", "تمام ضبط", "stop recording", "save action", "finish macro"], tip: "ضبط را تمام می‌کند و از شما یک نام می‌خواهد؛ اکشنِ ذخیره‌شده برای همهٔ عکس‌های این فروشگاه در دسترس است", run: (h) => h.actionStop(), enabled: (h) => (h.s.recording ? null : "اول ضبط را شروع کنید") });
  add({ id: "action.panel", menu: "edit", group: "اکشن (ضبط و اجرا)", title: "اکشن‌های ذخیره‌شده (اجرا و حذف)", en: "Saved actions", syn: ["اجرای اکشن", "فهرست اکشن", "اکشن ها", "play action", "run action", "actions list", "batch steps"], tip: "فهرستِ اکشن‌های ذخیره‌شده؛ هر کدام را با یک کلیک روی عکسِ باز اجرا کنید", run: (h) => h.tab("history") });
  add({ id: "brush.save", menu: "edit", group: "قلم‌موی دلخواه", title: "ذخیرهٔ قلمِ فعلی با یک نام…", en: "Save brush preset", syn: ["ذخیره قلم", "پیش تنظیم قلم", "قلم من", "save brush", "brush preset", "custom brush"], tip: "اندازه، سختی، شدت، فاصله، پخش و نوکِ تصویریِ قلمِ فعلی را با یک نام نگه می‌دارد تا بعداً با یک کلیک برگردد", run: (h) => h.brushOp("save") });
  add({ id: "brush.fromImage", menu: "edit", group: "قلم‌موی دلخواه", title: "ساختنِ قلم از روی یک تصویر…", en: "Brush from image", syn: ["قلم از تصویر", "نوک قلم", "قلم تصویری", "brush tip", "image brush", "stamp brush", "define brush"], tip: "یک تصویر (مثلاً ستاره یا برگ) انتخاب کنید؛ نوکِ قلم همان شکل می‌شود (تاریک‌تر = پُررنگ‌تر)", run: (h) => h.brushOp("fromImage") });
  add({ id: "brush.clearTip", menu: "edit", group: "قلم‌موی دلخواه", title: "برداشتنِ نوکِ تصویریِ قلم", en: "Clear brush tip", syn: ["برداشتن نوک", "قلم ساده", "clear brush tip"], tip: "قلم دوباره گرد و ساده می‌شود", run: (h) => h.brushOp("clearTip") });
  add({ id: "edit.fillGradient", menu: "edit", group: "نقاشی", title: "پرکردنِ لایهٔ نقاشی با شیب…", en: "Fill with gradient", syn: ["پر کردن با شیب", "گرادینت", "شیب چندرنگ", "gradient fill", "gradient tool", "fill gradient", "stops"], tip: "لایهٔ نقاشیِ فعال (یا فقط ناحیهٔ انتخاب) را با شیبِ چندتوقفی پر می‌کند؛ توقف‌ها را بکشید و رنگ بدهید", run: (h) => h.fillGradient(), enabled: (h) => (h.s.activeIsPaint ? null : "اول یک لایهٔ نقاشی را انتخاب کنید") });
  add({ id: "layer.shapeLibrary", menu: "layer", group: "افزودن", title: "شکل‌های آماده (چندضلعی، ستاره، قلب، فلش…)", en: "Custom shapes / polygon / star", syn: ["شکل آماده", "چندضلعی", "ستاره", "قلب", "فلش", "کادر گفتگو", "ابر", "polygon", "star", "heart", "arrow", "custom shape", "shape library", "badge"], tip: "یک شکلِ آماده یا چندضلعی/ستارهٔ دلخواه را به‌صورتِ لایهٔ شکل اضافه می‌کند", run: (h) => h.extra.shapeLibrary() });
  add({ id: "image.flatten", menu: "image", group: "ترکیب", title: "تخت‌کردنِ همهٔ لایه‌ها (تصویرِ تازه)", en: "Flatten image", syn: ["تخت کردن", "یکی کردن لایه ها", "ادغام همه", "flatten", "flatten image", "merge all"], tip: "همهٔ لایه‌ها را در یک تصویر می‌ریزد و آن را به‌عنوانِ عکسِ تازه در کتابخانه باز می‌کند؛ عکسِ فعلی با لایه‌هایش سر جایش می‌ماند", run: (h) => h.extra.flatten() });
  add({ id: "layer.copy", menu: "layer", group: "رونوشت", title: "رونوشتِ لایه (برای چسباندن در عکسِ دیگر)", en: "Copy layer", syn: ["کپی لایه", "رونوشت لایه", "copy layer"], tip: "لایه (با زیرمجموعه‌اش) را نگه می‌دارد؛ بعد در همین عکس یا عکسِ دیگر می‌چسبانید", run: (h) => h.extra.layerCopy(), enabled: (h) => (h.s.hasActive && !h.s.activeIsBase ? null : "اول یک لایه (غیر از «عکس») را انتخاب کنید") });
  add({ id: "layer.paste", menu: "layer", group: "رونوشت", title: "چسباندنِ لایه", en: "Paste layer", syn: ["چسباندن لایه", "paste layer"], tip: "آخرین لایهٔ رونوشت‌شده را بالای لایهٔ فعال می‌گذارد", run: (h) => h.extra.layerPaste() });
  add({ id: "layer.link", menu: "layer", group: "پیوند", title: "پیوندِ لایه با لایهٔ زیرین", en: "Link layers", syn: ["پیوند لایه", "لینک لایه", "همراه کردن", "link layers", "link"], tip: "دو لایه با هم جابه‌جا می‌شوند؛ کشیدنِ یکی هر دو را می‌برد", run: (h) => h.extra.layerLink(), enabled: (h) => (h.s.hasActive && !h.s.activeIsBase ? null : "اول یک لایه (غیر از «عکس») را انتخاب کنید") });
  add({ id: "layer.unlink", menu: "layer", group: "پیوند", title: "قطعِ پیوندِ لایه", en: "Unlink layer", syn: ["قطع پیوند", "جدا کردن لایه", "unlink"], tip: "لایهٔ فعال از گروهِ پیوندی بیرون می‌آید", run: (h) => h.extra.layerUnlink(), enabled: (h) => (h.s.hasActive ? null : "اول یک لایه را انتخاب کنید") });
  for (const [lid, lt] of [["red", "قرمز"], ["orange", "نارنجی"], ["yellow", "زرد"], ["green", "سبز"], ["blue", "آبی"], ["violet", "بنفش"], ["gray", "خاکستری"]] as const) {
    add({ id: `layer.label.${lid}`, menu: "layer", group: "برچسبِ رنگی", title: `برچسبِ ${lt}`, en: `Color label ${lid}`, syn: ["برچسب رنگی", "رنگ لایه", "color label", `label ${lid}`], tip: "یک نقطهٔ رنگی کنارِ نامِ لایه می‌گذارد تا لایه‌ها را دسته‌بندی کنید", run: (h) => h.extra.layerLabel(lid), enabled: (h) => (h.s.hasActive ? null : "اول یک لایه را انتخاب کنید") });
  }
  add({ id: "layer.label.none", menu: "layer", group: "برچسبِ رنگی", title: "برداشتنِ برچسبِ رنگی", en: "Clear color label", syn: ["برداشتن برچسب", "بی رنگ", "clear label"], tip: "نقطهٔ رنگیِ لایه برداشته می‌شود", run: (h) => h.extra.layerLabel(null), enabled: (h) => (h.s.hasActive ? null : "اول یک لایه را انتخاب کنید") });
  add({ id: "layer.rasterize", menu: "layer", group: "تبدیل", title: "تبدیلِ متن/شکل به تصویرِ پیکسلی", en: "Rasterize layer", syn: ["رستر", "پیکسلی کردن", "تبدیل به تصویر", "rasterize", "rasterize layer", "convert to image"], tip: "متن یا شکل (با سایه و دورخطش) به یک لایهٔ تصویری تبدیل می‌شود؛ بعد با فیلترها و قلم‌ها ویرایش‌پذیر است ولی دیگر متن نیست", run: (h) => h.extra.rasterize(), enabled: (h) => (h.s.activeType === "text" || h.s.activeType === "shape" ? null : "فقط لایهٔ متن یا شکل") });
  add({ id: "select.typeMask", menu: "select", group: "از لایه", title: "ماسکِ متن: انتخابِ شکلِ حرف‌ها", en: "Type mask", syn: ["ماسک متن", "انتخاب از متن", "شکل حرف", "type mask", "text selection", "text to selection"], tip: "شکلِ حرف‌های لایهٔ متن (یا شکل) را به‌صورتِ انتخاب درمی‌آورد؛ بعد می‌توانید ماسک یا لایهٔ تنظیم روی همان حرف‌ها بسازید", run: (h) => h.extra.typeMask(), enabled: (h) => (h.s.activeType === "text" || h.s.activeType === "shape" ? null : "اول یک لایهٔ متن (یا شکل) را انتخاب کنید") });
  add({ id: "text.inShape", menu: "layer", group: "متن", title: "متن داخلِ شکلِ زیرین", en: "Text in shape", syn: ["متن داخل شکل", "متن در شکل", "جا دادن متن", "text in shape", "fit text to shape"], tip: "متن را وسطِ نزدیک‌ترین شکلِ زیرش می‌گذارد و خط‌ها را به اندازهٔ داخلِ شکل می‌شکند", run: (h) => h.extra.textInShape(), enabled: (h) => (h.s.activeType === "text" ? null : "اول یک لایهٔ متن را انتخاب کنید") });
  add({ id: "select.transform", menu: "select", group: "ویرایشِ انتخاب", title: "تبدیلِ انتخاب (بزرگ/کوچک، چرخش، جابه‌جایی)…", en: "Transform selection", syn: ["تبدیل انتخاب", "چرخاندن انتخاب", "بزرگ کردن انتخاب", "transform selection", "rotate selection", "scale selection"], tip: "خودِ ناحیهٔ انتخاب را (نه پیکسل‌ها را) بزرگ/کوچک، بچرخان و جابه‌جا می‌کند", run: (h) => h.extra.selTransform(), enabled: (h) => (h.s.hasSelection ? null : "اول ناحیه‌ای را انتخاب کنید") });
  add({ id: "layer.styles", menu: "layer", group: "سبک‌ها", title: "سبک‌ها: لایه، حرف و پاراگراف…", en: "Styles library", syn: ["سبک", "سبک لایه", "سبک متن", "سبک حرف", "سبک پاراگراف", "ذخیره سبک", "styles", "layer style", "character style", "paragraph style", "text style", "preset style"], tip: "سبکِ آماده یا ذخیره‌شده را روی لایهٔ فعال می‌گذارد؛ سبکِ لایهٔ فعال (سایه، درخشش، دورخط؛ برای متن: قلم، رنگ، فاصله…) را با یک نام نگه می‌دارد", run: (h) => h.extra.styles(), enabled: (h) => (h.s.hasActive ? null : "اول یک لایه را انتخاب کنید") });
  for (const [k, mode, fa, en, syn, tip] of [
    ["contactSheet", "sheet", "شیتِ تماس (چند عکس در یک صفحه)…", "Contact sheet", ["شیت تماس", "کاتالوگ", "چند عکس در یک صفحه", "contact sheet", "catalog", "grid of photos"], "عکس‌های انتخابی را با نام در یک صفحهٔ شبکه‌ای می‌چیند"],
    ["hdr", "hdr", "ادغامِ HDR (چند نوردهی)…", "HDR merge", ["اچ دی آر", "hdr", "نوردهی", "exposure fusion", "bracketing", "merge exposures"], "۲ تا ۷ عکسِ هم‌کادر با نوردهیِ متفاوت را به یک عکسِ متعادل تبدیل می‌کند"],
    ["panorama", "pano", "پانوراما (دوختنِ چند عکس)…", "Panorama stitch", ["پانوراما", "دوختن", "عکس پهن", "panorama", "stitch", "photomerge"], "عکس‌های هم‌پوشان را به یک عکسِ پهن می‌دوزد"],
    ["processor", "proc", "پردازشگرِ تصویر (چند اندازه، چند عکس)…", "Image processor", ["پردازشگر تصویر", "چند اندازه", "تغییر اندازه گروهی", "image processor", "batch resize", "bulk export", "zip"], "هر عکس را در چند اندازه می‌سازد و همه را در یک zip می‌دهد"],
    ["batchAction", "action", "اجرای اکشن روی چند عکس…", "Run action on many photos", ["اکشن روی چند عکس", "دسته ای", "گروهی", "batch", "droplet", "run action", "apply to all", "اسکریپت"], "اکشنِ ذخیره‌شده را روی چند عکسِ کتابخانه اجرا می‌کند؛ هر عکس یک نسخهٔ تازه می‌شود"],
  ] as const) {
    add({ id: `file.${k}`, menu: "file", group: "چند عکس با هم", title: fa, en, syn: [...syn], tip, run: (h) => h.extra.multi(mode) });
  }
  add({ id: "image.lut", menu: "image", group: "رنگ از فایل یا عکسِ دیگر", title: "LUT رنگی (فایلِ .cube)…", en: "Color lookup (LUT .cube)", syn: ["ال یو تی", "lut", "cube", "جدول رنگ", "فیلتر رنگی فایل", "color lookup", "3dlut"], tip: "فایلِ LUT را روی عکس اعمال می‌کند؛ نتیجه عکسِ تازه است", run: (h) => h.extra.colorTool("lut") });
  add({ id: "image.matchColor", menu: "image", group: "رنگ از فایل یا عکسِ دیگر", title: "تطبیقِ رنگ با عکسِ دیگر…", en: "Match color", syn: ["تطبیق رنگ", "هم رنگ کردن", "رنگ از عکس دیگر", "match color", "color transfer", "reference color"], tip: "رنگ و روشناییِ کلیِ یک عکسِ مرجع را روی این عکس می‌آورد؛ نتیجه عکسِ تازه است", run: (h) => h.extra.colorTool("match") });
  add({ id: "select.sky", menu: "select", group: "انتخابِ خودکار", title: "انتخابِ آسمان", en: "Select sky", syn: ["آسمان", "انتخاب آسمان", "sky", "select sky"], tip: "آسمانِ آبی/ابری/غروبِ روشنِ بالای عکس را انتخاب می‌کند (روشِ سبک)", run: (h) => h.extra.selectAuto("sky") });
  add({ id: "select.focus", menu: "select", group: "انتخابِ خودکار", title: "ناحیهٔ تمرکز (جاهای تیز)", en: "Focus area", syn: ["ناحیه تمرکز", "جاهای تیز", "فوکوس", "focus area", "in focus", "sharp area"], tip: "جاهایی از عکس که تیز (در فوکوس) هستند را انتخاب می‌کند", run: (h) => h.extra.selectAuto("focus") });
  add({ id: "file.openPsd", menu: "file", group: "افزودن به صفحه", title: "باز کردنِ فایلِ لایه‌دار (PSD)…", en: "Open layered file (PSD)", syn: ["باز کردن psd", "فایل لایه دار", "ورود psd", "import psd", "open psd", "layered file"], tip: "فایلِ PSD را انتخاب کنید؛ هر لایه (شفافیت، حالتِ ترکیب و پنهان‌بودن) جدا در یک عکسِ تازه باز می‌شود. لایهٔ متن و تنظیم به‌صورتِ تصویر می‌آید یا نمی‌آید (یادداشت می‌دهد)", run: (h) => h.openPsd() });
  add({ id: "edit.fillFg", menu: "edit", group: "نقاشی", title: "پرکردنِ لایه (یا انتخاب) با رنگِ پیش‌زمینه", en: "Fill with foreground color", syn: ["پر کردن", "رنگ کردن لایه", "fill layer", "fill selection", "foreground"], key: "Alt+Backspace", tip: "لایهٔ نقاشیِ فعال (یا فقط ناحیهٔ انتخاب‌شده) را با رنگِ پیش‌زمینه پر می‌کند", run: (h) => h.fillPaint(), enabled: (h) => (h.s.activeIsPaint ? null : "اول یک لایهٔ نقاشی را انتخاب کنید") });
  add({ id: "edit.clearPaint", menu: "edit", group: "نقاشی", title: "پاک‌کردنِ محتوای لایهٔ نقاشی (یا انتخاب)", en: "Clear paint layer", syn: ["خالی کردن لایه", "پاک کردن نقاشی", "clear layer", "erase all"], tip: "همهٔ نقاشیِ این لایه (یا فقط ناحیهٔ انتخاب‌شده) را پاک می‌کند؛ برگشت‌پذیر", run: (h) => h.clearPaint(), enabled: (h) => (h.s.activeIsPaint ? null : "اول یک لایهٔ نقاشی را انتخاب کنید") });
  add({ id: "edit.snapshot", menu: "edit", group: "تاریخچه", title: "عکسِ لحظه‌ایِ تازه", en: "New snapshot", syn: ["اسنپ شات", "نگه داشتن حالت", "ذخیره حالت", "snapshot", "save state", "checkpoint"], tip: "حالتِ فعلیِ کار را نگه می‌دارد تا بعداً به آن برگردید یا قلمِ تاریخچه از آن رنگ بگیرد", run: (h) => h.snapshotNew() });
  add({ id: "edit.duplicate", menu: "edit", group: "لایه", title: "رونوشتِ لایه", en: "Duplicate layer", syn: ["کپی", "کپی لایه", "duplicate", "copy"], key: "Ctrl+J", tip: "یک نسخهٔ دقیق از لایهٔ فعال می‌سازد", run: (h) => h.duplicate(), enabled: needEditable });
  add({ id: "edit.delete", menu: "edit", group: "لایه", title: "حذفِ لایه", en: "Delete layer", syn: ["پاک", "delete", "remove"], key: "Delete", tip: "لایهٔ فعال را برمی‌دارد (برگشت‌پذیر)", run: (h) => h.remove(), enabled: needEditable });
  add({ id: "edit.transform", menu: "edit", group: "تبدیل", title: "تبدیلِ آزاد (جابه‌جایی، اندازه، چرخش)", en: "Free Transform", syn: ["ترنسفورم", "تغییر اندازه", "چرخاندن", "scale", "rotate", "resize", "move"], key: "Ctrl+T", tip: "لایه را با دستگیره‌ها بزرگ، کوچک یا بچرخانید", run: (h) => h.tool("move") });

  // ── تصویر
  add({ id: "image.autoAll", menu: "image", group: "خودکار", title: "تنظیمِ خودکارِ نور و رنگ", en: "Auto tone / color", syn: ["اتو", "خودکار", "auto", "auto tone", "auto contrast", "auto levels", "بهبود"], tip: "یک کلیک: نور، کنتراست و رنگ را متعادل می‌کند (بعدش هر چیزی را می‌توانید دستی عوض کنید)", run: (h) => h.quickAuto() });
  add({ id: "image.autoStraighten", menu: "image", group: "خودکار", title: "صاف کردنِ خودکارِ افق", en: "Auto straighten", syn: ["افق", "صاف", "level", "horizon", "auto straighten"], tip: "کجیِ افق را پیدا و جبران می‌کند", run: (h) => h.autoStraighten() });
  add({ id: "image.adjust", menu: "image", group: "تنظیم‌ها", title: "نور، رنگ و جزئیات (لغزنده‌ها)", en: "Adjustments", syn: ["روشنایی", "کنتراست", "اشباع", "نوردهی", "سطوح", "منحنی", "brightness", "contrast", "saturation", "exposure", "levels", "curves", "hsl"], tip: "همهٔ لغزنده‌های نور و رنگ و منحنی‌ها", run: (h) => h.tab("edit") });
  add({ id: "image.adjustLayer", menu: "image", group: "تنظیم‌ها", title: "لایهٔ تنظیمِ تازه (با ماسک)", en: "New adjustment layer", syn: ["لایه تنظیم", "adjustment layer", "غیرمخرب"], tip: "لغزنده‌های نور و رنگ را روی یک لایهٔ جدا بگذارید تا بشود ماسکش کرد", run: (h) => h.addAdjust() });
  add({ id: "image.crop", menu: "image", group: "برش و چرخش", title: "برش", en: "Crop", syn: ["کراپ", "crop"], key: "C", tip: "قاب را بکشید یا نسبتی انتخاب کنید؛ Enter = اعمال", run: (h) => h.tool("crop") });
  add({ id: "image.rotateCW", menu: "image", group: "برش و چرخش", title: "چرخش ۹۰ درجه به راست", en: "Rotate 90° CW", syn: ["چرخش", "rotate", "clockwise"], tip: "کل تصویر را ۹۰ درجه می‌چرخاند", run: (h) => h.rotate(90) });
  add({ id: "image.rotateCCW", menu: "image", group: "برش و چرخش", title: "چرخش ۹۰ درجه به چپ", en: "Rotate 90° CCW", syn: ["چرخش", "rotate", "counter clockwise"], tip: "کل تصویر را ۹۰ درجه به چپ می‌چرخاند", run: (h) => h.rotate(-90) });
  add({ id: "image.rotate180", menu: "image", group: "برش و چرخش", title: "چرخش ۱۸۰ درجه", en: "Rotate 180°", syn: ["وارونه", "upside down", "rotate 180"], tip: "تصویر را سر و ته می‌کند", run: (h) => h.rotate(180) });
  add({ id: "image.flipH", menu: "image", group: "برش و چرخش", title: "قرینهٔ افقی", en: "Flip horizontal", syn: ["آینه", "قرینه", "mirror", "flip"], tip: "چپ و راستِ تصویر را عوض می‌کند", run: (h) => h.flip("h") });
  add({ id: "image.flipV", menu: "image", group: "برش و چرخش", title: "قرینهٔ عمودی", en: "Flip vertical", syn: ["آینه", "قرینه", "mirror", "flip"], tip: "بالا و پایینِ تصویر را عوض می‌کند", run: (h) => h.flip("v") });
  add({ id: "image.persp", menu: "image", group: "برش و چرخش", title: "اصلاحِ پرسپکتیو", en: "Perspective correction", syn: ["پرسپکتیو", "ساختمان", "keystone", "perspective crop"], key: "Y", tip: "چهار گوشه را روی لبه‌های کج بکشید تا صاف شود", run: (h) => h.tool("persp") });
  add({ id: "image.storeFrame", menu: "image", group: "قاب", title: "قابِ مربعِ فروشگاه", en: "Store square frame", syn: ["مربع", "قاب", "فروشگاه", "square", "frame", "padding"], tip: "عکس را در مربعِ ۲۰۰۰ با حاشیهٔ یکسان می‌گذارد؛ دوباره بزنید تا برداشته شود", run: (h) => h.storeFrame() });
  add({ id: "image.removeBg", menu: "image", group: "هوش مصنوعی (سرورِ پردازش)", title: "حذف / تعویضِ پس‌زمینه", en: "Remove background", syn: ["بک گراند", "پس زمینه", "background", "cutout", "remove bg", "برش سوژه"], tip: "پس‌زمینه را حذف یا سفید می‌کند (روی سرورِ پردازش انجام می‌شود؛ اگر خاموش باشد «در صف — منتظرِ سرورِ پردازش» می‌ماند و بعداً خودکار انجام می‌شود)", run: (h) => h.kit("kit_background") });
  add({ id: "image.matting", menu: "image", group: "هوش مصنوعی (سرورِ پردازش)", title: "حذفِ پس‌زمینه با مدل (انتخاب و مقایسه)…", en: "Remove background with models (compare)", syn: ["مدل", "مقایسه مدل", "u2netp", "isnet", "is-net", "birefnet", "rvm", "matting", "cutout compare", "بک گراند", "پس زمینه", "جداسازی سوژه"], tip: "یکی از چهار مدل (RVM روی سایت، u2netp، IS-Net، BiRefNet-lite روی سرورِ پردازش) را انتخاب کنید یا همه را کنارِ هم مقایسه کنید؛ وضعیتِ نصبِ مدل‌ها دیده می‌شود و کارِ مدل‌های دانلودنشده در صف می‌ماند", run: (h) => h.matting() });
  add({ id: "image.upscale", menu: "image", group: "هوش مصنوعی (سرورِ پردازش)", title: "بزرگ‌نماییِ هوشمند", en: "Super resolution", syn: ["بزرگ کردن", "افزایش کیفیت", "upscale", "enlarge", "resolution"], tip: "عکس را بدونِ کدر شدن بزرگ می‌کند (روی سرورِ پردازش انجام می‌شود؛ اگر خاموش باشد «در صف — منتظرِ سرورِ پردازش» می‌ماند و بعداً خودکار انجام می‌شود)", run: (h) => h.kit("kit_upscale") });
  add({ id: "image.denoise", menu: "image", group: "هوش مصنوعی (سرورِ پردازش)", title: "نویزگیریِ هوشمند", en: "Denoise", syn: ["نویز", "دانه", "noise", "grain", "denoise"], tip: "دانه‌دانه‌شدنِ عکسِ شب را کم می‌کند (روی سرورِ پردازش انجام می‌شود؛ اگر خاموش باشد «در صف — منتظرِ سرورِ پردازش» می‌ماند و بعداً خودکار انجام می‌شود)", run: (h) => h.kit("kit_denoise") });
  add({ id: "image.sharpenKit", menu: "image", group: "هوش مصنوعی (سرورِ پردازش)", title: "شارپِ حرفه‌ای", en: "Smart sharpen", syn: ["تیز کردن", "شارپ", "sharpen"], tip: "جزئیات را تیز می‌کند (روی سرورِ پردازش انجام می‌شود؛ اگر خاموش باشد «در صف — منتظرِ سرورِ پردازش» می‌ماند و بعداً خودکار انجام می‌شود)", run: (h) => h.kit("kit_sharpen") });

  // ── لایه
  add({ id: "layer.text", menu: "layer", group: "لایهٔ تازه", title: "لایهٔ متن", en: "Text layer", syn: ["نوشته", "متن", "تایپ", "type", "text"], key: "T", tip: "روی عکس متنِ فارسی یا انگلیسی بنویسید", run: (h) => h.addText() });
  const needText = (h: Host) => (h.s.activeType === "text" && !h.s.activeLocked ? null : "اول یک لایهٔ متن را انتخاب کنید");
  add({ id: "text.underline", menu: "layer", group: "متن", title: "زیرخط (روشن/خاموش)", en: "Underline", syn: ["خط زیر متن", "زیر خط", "underline"], tip: "زیرِ هر خطِ متنِ لایهٔ فعال خط می‌کشد", run: (h) => h.textFlag("underline"), enabled: needText });
  add({ id: "text.strike", menu: "layer", group: "متن", title: "خط‌خوردگی (روشن/خاموش)", en: "Strikethrough", syn: ["خط وسط", "خط زدن", "قیمت قبلی", "strikethrough", "strike", "line through"], tip: "وسطِ هر خطِ متن خط می‌کشد؛ برای «قیمتِ قبلی» عالی است", run: (h) => h.textFlag("strike"), enabled: needText });
  add({ id: "text.vertical", menu: "layer", group: "متن", title: "متنِ عمودی (روشن/خاموش)", en: "Vertical type", syn: ["عمودی", "حرف زیر حرف", "نوشتن عمودی", "vertical text", "vertical type", "stacked letters"], tip: "هر حرفِ متن زیرِ حرفِ قبلی می‌آید؛ برای تابلو و عنوان‌های باریک (در فارسی حروف جدا می‌شوند)", run: (h) => h.textFlag("vertical"), enabled: needText });
  add({ id: "text.justify", menu: "layer", group: "متن", title: "تراز دوطرفه (روشن/خاموش)", en: "Justify", syn: ["دوطرفه", "جاگذاری خط ها", "justify", "justified", "تورفتگی", "indent"], tip: "فاصلهٔ کلمه‌ها پهن می‌شود تا همهٔ خط‌ها (جز آخری) به پهنای کادر برسند؛ پهنای کادر را در بازرس تعیین کنید", run: (h) => h.textFlag("justify"), enabled: needText });
  add({ id: "text.onPath", menu: "layer", group: "متن", title: "متن روی مسیرِ قلم", en: "Text on path", syn: ["متن روی مسیر", "متن روی منحنی", "متن منحنی", "text on a path", "text on path", "curved path text"], tip: "اول با ابزارِ قلم یک مسیر بکشید؛ متنِ لایهٔ فعال در امتدادِ همان مسیر می‌نشیند", run: (h) => h.textPath(true), enabled: needText });
  add({ id: "text.offPath", menu: "layer", group: "متن", title: "برداشتنِ متن از روی مسیر", en: "Remove text from path", syn: ["برداشتن مسیر متن", "remove text path"], tip: "متن دوباره صاف و افقی می‌شود", run: (h) => h.textPath(false), enabled: needText });
  add({ id: "text.caps", menu: "layer", group: "متن", title: "حروفِ بزرگِ لاتین (روشن/خاموش)", en: "All caps", syn: ["حروف بزرگ", "کپیتال", "uppercase", "caps", "all caps", "capital"], tip: "حروفِ انگلیسیِ متن بزرگ دیده می‌شود؛ متنِ فارسی تغییری نمی‌کند", run: (h) => h.textFlag("caps"), enabled: needText });
  for (const [k, fa, en, syn] of [
    ["arc", "قوس", "Arc", ["کمان", "نیم دایره", "قوسی", "arch", "curve"]],
    ["wave", "موج", "Wave", ["موجی", "سینوسی", "wavy"]],
    ["flag", "پرچم", "Flag", ["پرچمی", "بادخورده", "waving"]],
    ["bulge", "برآمده", "Bulge", ["باد کرده", "وسط درشت", "inflate", "fisheye"]],
    ["rise", "شیب", "Rise", ["سربالا", "مایل", "slope", "slant"]],
  ] as const) {
    add({ id: `text.warp.${k}`, menu: "layer", group: "متنِ خمیده", title: `متنِ خمیده: ${fa}`, en: `Warp text: ${en}`, syn: ["خمیده", "خم کردن متن", "warp text", "text warp", "curved text", ...syn], tip: `متنِ لایهٔ فعال را به شکلِ «${fa}» خم می‌کند؛ میزانش در پنلِ لایه است`, run: (h) => h.textWarp(k), enabled: needText });
  }
  add({ id: "text.warp.none", menu: "layer", group: "متنِ خمیده", title: "برداشتنِ خمیدگیِ متن", en: "Remove text warp", syn: ["صاف کردن متن", "بدون خمیدگی", "unwarp", "straight text"], tip: "متنِ لایهٔ فعال را دوباره صاف می‌کند", run: (h) => h.textWarp(null), enabled: needText });
  add({ id: "layer.rect", menu: "layer", group: "لایهٔ تازه", title: "لایهٔ شکل: مستطیل", en: "Rectangle shape", syn: ["مربع", "کادر", "rectangle", "box", "rounded"], tip: "مستطیل با گوشهٔ گرد، رنگ و دورخط", run: (h) => h.addShape("rect") });
  add({ id: "layer.ellipse", menu: "layer", group: "لایهٔ تازه", title: "لایهٔ شکل: بیضی", en: "Ellipse shape", syn: ["دایره", "بیضی", "circle", "ellipse", "oval"], tip: "دایره یا بیضی", run: (h) => h.addShape("ellipse") });
  add({ id: "layer.line", menu: "layer", group: "لایهٔ تازه", title: "لایهٔ شکل: خط", en: "Line shape", syn: ["خط", "line", "divider"], tip: "یک خطِ ساده", run: (h) => h.addShape("line") });
  add({ id: "layer.newPaint", menu: "layer", group: "لایهٔ تازه", title: "لایهٔ نقاشی", en: "Paint layer (new)", syn: ["لایه خالی", "لایه جدید", "نقاشی", "رستر", "new layer", "blank layer", "raster layer", "pixel layer"], tip: "یک لایهٔ شفافِ تازه که با قلم، مداد، پاک‌کن و سطلِ رنگ رویش نقاشی می‌کنید (روی سرور هم همین‌طور ساخته می‌شود)", run: (h) => h.newPaint() });
  add({ id: "layer.adjust", menu: "layer", group: "لایهٔ تازه", title: "لایهٔ تنظیم", en: "Adjustment layer", syn: ["تنظیم", "adjustment", "غیرمخرب"], tip: "تنظیمِ نور و رنگِ جدا که می‌شود ماسکش کرد", run: (h) => h.addAdjust() });
  add({ id: "layer.retouch", menu: "layer", group: "لایهٔ تازه", title: "لایهٔ روتوش (کلون و ترمیم)", en: "Retouch layer", syn: ["روتوش", "کلون", "retouch", "clone layer"], tip: "کلون و ترمیم روی لایهٔ جدا؛ برگشت‌پذیر", run: (h) => h.addRetouch() });
  add({ id: "layer.group", menu: "layer", group: "گروه", title: "گروهِ تازه از این لایه", en: "Group layers", syn: ["پوشه", "گروه", "group", "folder"], key: "Ctrl+G", tip: "لایه را در یک پوشه می‌گذارد", run: (h) => h.group(), enabled: needEditable });
  add({ id: "layer.newGroup", menu: "layer", group: "گروه", title: "گروهِ خالی", en: "New group", syn: ["پوشه خالی", "empty group"], tip: "یک پوشهٔ خالی بالای لایهٔ فعال", run: (h) => h.newGroup() });
  add({ id: "layer.ungroup", menu: "layer", group: "گروه", title: "بازکردنِ گروه", en: "Ungroup", syn: ["باز کردن پوشه", "ungroup"], key: "Ctrl+Shift+G", tip: "لایه‌های داخلِ گروه را بیرون می‌آورد", run: (h) => h.ungroup(), enabled: (h) => (h.s.activeType === "group" ? null : "اول یک گروه را انتخاب کنید") });
  add({ id: "layer.clip", menu: "layer", group: "گروه", title: "برش به لایهٔ زیرین", en: "Clipping mask", syn: ["کلیپینگ", "clipping", "clip to layer"], tip: "اثرِ لایه فقط روی محتوای لایهٔ زیرش دیده می‌شود", run: (h) => h.toggleClip(), enabled: needEditable });
  add({ id: "layer.merge", menu: "layer", group: "ترکیب", title: "ادغام با لایهٔ زیرین", en: "Merge down", syn: ["ادغام", "merge", "flatten"], key: "Ctrl+E", tip: "لایه را با لایهٔ پایینیِ خودش یکی می‌کند", run: (h) => h.mergeDown(), enabled: needEditable });
  add({ id: "layer.mergeVisible", menu: "layer", group: "ترکیب", title: "ادغامِ لایه‌های دیده‌شده", en: "Merge visible", syn: ["ادغام همه", "یکی کردن لایه ها", "merge all", "merge visible", "flatten layers"], key: "Ctrl+Shift+E", tip: "همهٔ لایه‌های تصویر، متن و شکلِ دیده‌شده را یک لایه می‌کند (عکسِ اصلی و لایه‌های تنظیم دست‌نخورده می‌مانند)", run: (h) => h.mergeVisible(), enabled: (h) => (h.s.layerCount > 2 ? null : "دست‌کم دو لایهٔ بالای عکس لازم است") });
  add({ id: "layer.top", menu: "layer", group: "ترتیب", title: "آوردن به بالاترین", en: "Bring to front", syn: ["روی همه", "bring to front", "arrange"], tip: "لایه را بالای همهٔ هم‌سطح‌ها می‌برد", run: (h) => h.move("top"), enabled: needEditable });
  add({ id: "layer.up", menu: "layer", group: "ترتیب", title: "یک پله بالاتر", en: "Bring forward", syn: ["بالا", "forward", "arrange"], tip: "لایه را یک پله بالا می‌برد", run: (h) => h.move("up"), enabled: needEditable });
  add({ id: "layer.down", menu: "layer", group: "ترتیب", title: "یک پله پایین‌تر", en: "Send backward", syn: ["پایین", "backward", "arrange"], tip: "لایه را یک پله پایین می‌برد", run: (h) => h.move("down"), enabled: needEditable });
  add({ id: "layer.bottom", menu: "layer", group: "ترتیب", title: "فرستادن به پایین‌ترین", en: "Send to back", syn: ["زیر همه", "send to back", "arrange"], tip: "لایه را زیرِ همهٔ هم‌سطح‌ها می‌برد", run: (h) => h.move("bottom"), enabled: needEditable });
  add({ id: "layer.maskReveal", menu: "layer", group: "ماسک", title: "ماسکِ سفید (همه دیده شود)", en: "Reveal-all mask", syn: ["ماسک", "mask", "layer mask", "reveal all"], tip: "ماسکی می‌سازد که همه‌جا دیده می‌شود؛ با قلمِ سیاه جاهایی را پنهان کنید", run: (h) => h.addMask("reveal"), enabled: needNoMask });
  add({ id: "layer.maskHide", menu: "layer", group: "ماسک", title: "ماسکِ سیاه (همه پنهان)", en: "Hide-all mask", syn: ["ماسک", "mask", "hide all"], tip: "همه‌جا پنهان است؛ با قلمِ سفید جاهایی را آشکار کنید", run: (h) => h.addMask("hide"), enabled: needNoMask });
  add({ id: "layer.maskLinear", menu: "layer", group: "ماسک", title: "ماسکِ شیبِ خطی", en: "Linear gradient mask", syn: ["ماسک شیب", "گرادینت", "gradient mask", "fade"], tip: "لایه از یک طرف به طرفِ دیگر محو می‌شود", run: (h) => h.addMask("linear"), enabled: needNoMask });
  add({ id: "layer.maskRadial", menu: "layer", group: "ماسک", title: "ماسکِ شیبِ شعاعی", en: "Radial gradient mask", syn: ["ماسک دایره", "وینیت", "radial mask", "vignette mask"], tip: "اثر از مرکز به لبه‌ها محو می‌شود", run: (h) => h.addMask("radial"), enabled: needNoMask });
  add({ id: "layer.maskFromSel", menu: "layer", group: "ماسک", title: "ماسک از روی انتخاب", en: "Mask from selection", syn: ["ماسک انتخاب", "selection to mask"], tip: "ناحیهٔ انتخاب‌شده را ماسکِ لایه می‌کند", run: (h) => h.maskFromSelection(), enabled: (h) => needNoMask(h) ?? needSelection(h) });
  add({ id: "layer.maskPaint", menu: "layer", group: "ماسک", title: "نقاشی روی ماسک", en: "Paint on mask", syn: ["براش ماسک", "mask brush"], key: "B", tip: "به قلمِ ماسک می‌رود (سفید = دیده شود، X = پاک‌کن)", run: (h) => h.paintMask(), enabled: needMask });
  add({ id: "layer.maskRemove", menu: "layer", group: "ماسک", title: "حذفِ ماسک", en: "Delete mask", syn: ["پاک کردن ماسک", "remove mask"], tip: "ماسکِ لایه را برمی‌دارد", run: (h) => h.removeMask(), enabled: needMask });

  // ── انتخاب
  add({ id: "select.all", menu: "select", group: "انتخاب", title: "انتخابِ همه", en: "Select all", syn: ["همه", "کل تصویر", "select all", "everything"], key: "Ctrl+A", tip: "کلِ بوم را انتخاب می‌کند", run: (h) => h.selAll() });
  add({ id: "select.clear", menu: "select", group: "انتخاب", title: "برداشتنِ انتخاب", en: "Deselect", syn: ["لغو انتخاب", "deselect", "clear selection"], key: "Ctrl+D", tip: "انتخاب را پاک می‌کند", run: (h) => h.selClear(), enabled: needSelection });
  add({ id: "select.invert", menu: "select", group: "انتخاب", title: "وارونهٔ انتخاب", en: "Inverse", syn: ["معکوس", "invert selection", "inverse"], key: "Ctrl+Shift+I", tip: "هر چه انتخاب بود نشود و برعکس", run: (h) => h.selInvert() });
  add({ id: "select.reselect", menu: "select", group: "انتخاب", title: "انتخابِ دوباره", en: "Reselect", syn: ["بازگرداندن انتخاب", "انتخاب قبلی", "reselect", "restore selection"], key: "Ctrl+Shift+D", tip: "آخرین انتخابی را که برداشتید برمی‌گرداند", run: (h) => h.selReselect() });
  add({ id: "select.colorRange", menu: "select", group: "خودکار", title: "بازهٔ رنگ / عصای جادویی…", en: "Color range / Magic wand", syn: ["عصای جادویی", "انتخاب رنگ", "رنگ مشابه", "magic wand", "color range", "select similar", "select by color"], tip: "روی یک رنگ کلیک کنید تا همهٔ رنگ‌های مشابه (یا فقط ناحیهٔ پیوسته) انتخاب شود", run: (h) => h.colorRange() });
  add({ id: "select.grow", menu: "select", group: "تغییرِ انتخاب", title: "گسترش…", en: "Grow / Expand", syn: ["بزرگ کردن انتخاب", "گسترش", "expand selection", "grow"], tip: "لبهٔ انتخاب را چند پیکسل به بیرون می‌برد", run: (h) => h.selOp("grow"), enabled: needSelection });
  add({ id: "select.shrink", menu: "select", group: "تغییرِ انتخاب", title: "انقباض…", en: "Shrink / Contract", syn: ["کوچک کردن انتخاب", "انقباض", "contract selection", "shrink"], tip: "لبهٔ انتخاب را چند پیکسل به داخل می‌آورد", run: (h) => h.selOp("shrink"), enabled: needSelection });
  add({ id: "select.smooth", menu: "select", group: "تغییرِ انتخاب", title: "هموارسازی…", en: "Smooth", syn: ["نرم کردن گوشه", "صاف کردن لبه", "smooth selection"], tip: "گوشه‌ها و دندانه‌های لبهٔ انتخاب را گرد و صاف می‌کند", run: (h) => h.selOp("smooth"), enabled: needSelection });
  add({ id: "select.border", menu: "select", group: "تغییرِ انتخاب", title: "حاشیه…", en: "Border", syn: ["قاب انتخاب", "حلقه", "border selection", "outline selection"], tip: "فقط نوارِ اطرافِ لبه را انتخاب می‌کند (برای دورخط)", run: (h) => h.selOp("border"), enabled: needSelection });
  add({ id: "select.save", menu: "select", group: "ذخیره", title: "ذخیرهٔ انتخاب", en: "Save selection", syn: ["نگه داشتن انتخاب", "save selection", "alpha channel"], tip: "انتخابِ فعلی را نگه می‌دارد تا بعداً برگردانید", run: (h) => h.selSave(), enabled: needSelection });
  add({ id: "select.load", menu: "select", group: "ذخیره", title: "بارگذاریِ انتخابِ ذخیره‌شده…", en: "Load selection", syn: ["بازگرداندن انتخاب ذخیره", "load selection", "saved selections"], tip: "یکی از انتخاب‌های ذخیره‌شده را دوباره فعال می‌کند", run: (h) => h.selLoad() });
  add({ id: "select.feather", menu: "select", group: "لبه", title: "نرم کردنِ لبهٔ انتخاب", en: "Feather", syn: ["فدر", "نرمی", "feather", "soften edge"], tip: "لبهٔ انتخاب را به اندازهٔ نوارِ گزینه‌ها نرم می‌کند", run: (h) => h.selFeather(), enabled: needSelection });
  add({ id: "select.subject", menu: "select", group: "خودکار", title: "انتخابِ سوژه", en: "Select subject", syn: ["سوژه", "subject", "auto select"], key: "W", tip: "روی عکس کلیک کنید تا سوژه خودکار انتخاب شود", run: (h) => h.pickSubject() });
  // ── مسیرِ قلم (نوبت ۷)
  const needPath2 = (h: Host) => (h.s.penPoints >= 2 ? null : "اول با ابزارِ قلم یک مسیر (دست‌کم ۲ نقطه) بکشید");
  const needPath3 = (h: Host) => (h.s.penPoints >= 3 ? null : "اول با ابزارِ قلم یک مسیر با دست‌کم ۳ نقطه بکشید");
  add({ id: "path.toSelection", menu: "select", group: "مسیرِ قلم", title: "مسیر ⇒ انتخاب", en: "Path to selection", syn: ["مسیر به انتخاب", "ناحیه از مسیر", "make selection from path", "path selection", "pen selection"], tip: "مسیرِ قلم را به یک ناحیهٔ انتخاب‌شده تبدیل می‌کند (مسیرِ باز خودش بسته حساب می‌شود)", run: (h) => h.pathOp("toSelection"), enabled: needPath3 });
  add({ id: "path.toMask", menu: "select", group: "مسیرِ قلم", title: "مسیر ⇒ ماسکِ لایهٔ فعال", en: "Path to layer mask", syn: ["ماسک از مسیر", "پنهان کردن بیرونِ مسیر", "vector mask", "path mask"], tip: "فقط داخلِ مسیر در لایهٔ فعال دیده می‌شود", run: (h) => h.pathOp("toMask"), enabled: (h) => needPath3(h) ?? needLayer(h) });
  add({ id: "path.toShape", menu: "select", group: "مسیرِ قلم", title: "مسیر ⇒ لایهٔ شکل", en: "Path to shape layer", syn: ["شکل از مسیر", "لایه شکل", "vector shape", "shape from path"], tip: "مسیر را به یک لایهٔ شکلِ پُر (یا خطِ دور برای مسیرِ باز) تبدیل می‌کند", run: (h) => h.pathOp("toShape"), enabled: needPath2 });
  add({ id: "path.close", menu: "select", group: "مسیرِ قلم", title: "بستنِ مسیر", en: "Close path", syn: ["بستن مسیر", "close path", "join ends"], tip: "آخرین نقطه را به نقطهٔ اول وصل می‌کند", run: (h) => h.pathOp("close"), enabled: (h) => (h.s.penPoints < 3 ? "مسیر دست‌کم ۳ نقطه می‌خواهد" : h.s.penClosed ? "مسیر از قبل بسته است" : null) });
  add({ id: "path.addAnchors", menu: "select", group: "مسیرِ قلم", title: "افزودنِ نقطه در وسطِ همهٔ پاره‌ها", en: "Add anchors between points", syn: ["نقطه بیشتر", "ظریف کردن مسیر", "add anchor point", "subdivide path"], tip: "وسطِ هر پاره یک نقطه می‌گذارد تا مسیر را دقیق‌تر بتوانید شکل دهید؛ شکلِ مسیر عوض نمی‌شود (روی خودِ مسیر کلیک کنید تا یک نقطهٔ دلخواه بگذارید)", run: (h) => h.pathOp("addAnchors"), enabled: needPath2 });
  add({ id: "path.deleteAnchor", menu: "select", group: "مسیرِ قلم", title: "برداشتنِ نقطهٔ انتخاب‌شدهٔ مسیر", en: "Delete anchor point", syn: ["حذف نقطه", "پاک کردن نقطه", "delete anchor point", "remove point"], tip: "آخرین نقطهٔ کلیک‌شده را برمی‌دارد؛ (Shift+کلیک روی هر نقطه هم همین کار را می‌کند)", run: (h) => h.pathOp("deleteAnchor"), enabled: (h) => (h.s.penPoints >= 1 ? null : "مسیری نیست") });
  add({ id: "path.smooth", menu: "select", group: "مسیرِ قلم", title: "نقطهٔ انتخاب‌شده: گوشه ⇄ نرم", en: "Convert anchor point (corner / smooth)", syn: ["تبدیل نقطه", "نرم کردن نقطه", "گوشه", "convert anchor point", "smooth point", "corner point"], tip: "نقطهٔ گوشه را نرم (منحنی) و نقطهٔ نرم را گوشه می‌کند (Alt+کلیک روی نقطه هم همین است)", run: (h) => h.pathOp("smooth"), enabled: needPath2 });
  add({ id: "path.reverse", menu: "select", group: "مسیرِ قلم", title: "برعکس‌کردنِ جهتِ مسیر", en: "Reverse path direction", syn: ["جهت مسیر", "معکوس مسیر", "reverse path"], tip: "ترتیبِ نقطه‌ها را برعکس می‌کند (شکل همان می‌ماند)", run: (h) => h.pathOp("reverse"), enabled: needPath2 });
  add({ id: "path.save", menu: "select", group: "مسیرِ قلم", title: "ذخیرهٔ مسیر در پنلِ مسیرها", en: "Save path", syn: ["ذخیره مسیر", "پنل مسیرها", "paths panel", "save path", "store path"], tip: "مسیر را با یک نام نگه می‌دارد تا بعداً دوباره بارگذاری یا به انتخاب تبدیل کنید (تا بستنِ صفحه می‌ماند)", run: (h) => h.pathOp("save"), enabled: needPath2 });
  add({ id: "path.panel", menu: "select", group: "مسیرِ قلم", title: "پنلِ مسیرها و کانال‌ها", en: "Paths and channels panel", syn: ["مسیرها", "کانال ها", "paths", "channels", "paths panel"], tip: "مسیرهای ذخیره‌شده و دکمهٔ «کانال‌ها» در زبانهٔ لایه‌ها", run: (h) => h.tab("layers") });
  add({ id: "select.channels", menu: "select", group: "خودکار", title: "کانال‌ها (نمایش و بارگذاری به‌عنوان انتخاب)…", en: "Channels (load as selection)", syn: ["کانال", "قرمز سبز آبی", "کانال آلفا", "روشنایی", "channels", "alpha channel", "rgb channels", "load channel as selection", "luminosity mask"], tip: "قرمز، سبز، آبی، شفافیت و روشنایی را سیاه‌وسفید ببینید و هر کدام را به‌صورتِ انتخاب (نرم) بارگذاری کنید", run: (h) => h.channels() });
  add({ id: "select.adjust", menu: "select", group: "استفاده از انتخاب", title: "تنظیمِ نور و رنگ فقط روی انتخاب", en: "Adjust selection only", syn: ["تنظیم موضعی", "روی انتخاب", "local adjustment"], tip: "یک لایهٔ تنظیم با ماسکِ انتخاب می‌سازد", run: (h) => h.adjustFromSelection(), enabled: needSelection });

  // ── فیلتر (نوبت ۴: بقیه با extra می‌آیند)
  add({ id: "filter.presets", menu: "filter", group: "فیلترهای آماده", title: "فیلترهای آماده و پیش‌تنظیم‌ها", en: "Looks & presets", syn: ["فیلتر", "افکت", "استایل", "preset", "look", "filter", "lut"], tip: "فیلترِ آماده را با یک کلیک بزنید یا تنظیمِ خودتان را ذخیره کنید", run: (h) => h.tab("presets") });
  add({ id: "filter.liquify", menu: "filter", group: "تغییر شکل", title: "مایع‌سازی", en: "Liquify", syn: ["مایع", "لاغر", "liquify", "warp", "push", "bloat", "pucker"], key: "Q", tip: "با قلم بخش‌هایی را جابه‌جا، باد یا جمع کنید", run: (h) => h.tool("liquify") });

  // ── نما
  add({ id: "view.fit", menu: "view", group: "بزرگ‌نمایی", title: "جا شدن در پنجره", en: "Fit on screen", syn: ["فیت", "fit", "همه"], key: "0", tip: "کل عکس را در پنجره می‌گنجاند", run: (h) => h.zoom("fit") });
  add({ id: "view.100", menu: "view", group: "بزرگ‌نمایی", title: "اندازهٔ واقعی (۱۰۰٪)", en: "Actual pixels 100%", syn: ["صد درصد", "100", "actual size"], key: "1", tip: "هر پیکسلِ عکس یک پیکسلِ صفحه", run: (h) => h.zoom("100") });
  add({ id: "view.in", menu: "view", group: "بزرگ‌نمایی", title: "درشت‌نمایی", en: "Zoom in", syn: ["زوم", "zoom in", "بزرگ"], key: "+", tip: "نزدیک‌تر", run: (h) => h.zoom("in") });
  add({ id: "view.out", menu: "view", group: "بزرگ‌نمایی", title: "دورنمایی", en: "Zoom out", syn: ["زوم", "zoom out", "کوچک"], key: "-", tip: "دورتر", run: (h) => h.zoom("out") });
  add({ id: "view.compare", menu: "view", group: "مقایسه", title: "مقایسهٔ قبل و بعد", en: "Before / after", syn: ["قبل", "بعد", "before", "after", "compare"], key: "\\", tip: "عکسِ اصلی را موقتاً نشان می‌دهد", run: (h) => h.compare() });

  // ── پنجره
  add({ id: "window.panel", menu: "window", group: "پنل", title: "نمایش / پنهان‌کردنِ پنلِ کناری", en: "Toggle side panel", syn: ["پنل", "panel", "sidebar"], tip: "فضای بیشتری برای عکس", run: (h) => h.panelToggle() });
  add({ id: "window.edit", menu: "window", group: "زبانه‌ها", title: "زبانهٔ تنظیم", en: "Adjust panel", syn: ["تنظیم", "نور", "adjust", "develop"], tip: "لغزنده‌های نور و رنگ، قاب، برش", run: (h) => h.tab("edit") });
  add({ id: "window.layers", menu: "window", group: "زبانه‌ها", title: "زبانهٔ لایه‌ها", en: "Layers panel", syn: ["لایه", "layers"], tip: "فهرستِ لایه‌ها، ماسک‌ها و ویژگی‌های لایه", run: (h) => h.tab("layers") });
  add({ id: "window.presets", menu: "window", group: "زبانه‌ها", title: "زبانهٔ فیلتر", en: "Filters panel", syn: ["فیلتر", "پیش تنظیم", "presets", "looks"], tip: "فیلترهای آماده و پیش‌تنظیم‌های شما", run: (h) => h.tab("presets") });
  add({ id: "window.smart", menu: "window", group: "زبانه‌ها", title: "زبانهٔ هوشمند", en: "Smart panel", syn: ["هوشمند", "ai", "kit", "کیت"], tip: "ابزارهای سرورِ پردازش", run: (h) => h.tab("smart") });
  add({ id: "window.history", menu: "window", group: "زبانه‌ها", title: "زبانهٔ تاریخچه", en: "History panel", syn: ["تاریخچه", "history"], tip: "همهٔ کارها و پرش به هر مرحله", run: (h) => h.tab("history") });
  add({ id: "window.export", menu: "window", group: "زبانه‌ها", title: "زبانهٔ خروجی", en: "Export panel", syn: ["خروجی", "export", "save"], tip: "قالب، کیفیت، اندازه‌های آماده و ساخت", run: (h) => h.tab("export") });

  // ── راهنما
  add({ id: "help.keys", menu: "help", group: "راهنما", title: "میان‌برهای صفحه‌کلید", en: "Keyboard shortcuts", syn: ["کلید", "میانبر", "shortcuts", "keys", "hotkeys"], key: "?", tip: "فهرستِ همهٔ کلیدها", run: (h) => h.helpToggle() });

  // ── ابزارها: هر ابزارِ نوارِ کناری یک دستور (منوی «نما ← ابزارها» و «انتخاب» برای ابزارهای انتخاب…)
  const toolMenu = (id: string): { menu: MenuId; group: string } => {
    if (["marquee", "ellipse", "lasso", "subject"].includes(id)) return { menu: "select", group: "ابزارهای انتخاب" };
    if (["clone", "heal", "spot", "redeye"].includes(id)) return { menu: "image", group: "ابزارهای ترمیم" };
    if (id === "liquify") return { menu: "filter", group: "ابزارهای ویژه" };
    if (id === "genfill") return { menu: "select", group: "استفاده از انتخاب" };
    if (["paint", "pencil", "eraser", "bucket", "history", "picker", "blur", "sharpen", "smudge", "dodge", "burn", "sponge"].includes(id)) return { menu: "layer", group: "ابزارهای نقاشی" };
    if (["text", "brush", "gradient", "pen"].includes(id)) return { menu: "layer", group: "ابزارهای ساخت" };
    return { menu: "view", group: "ابزارها" };
  };
  for (const t of tools) {
    const meta = TOOL_META[t.id] ?? { en: t.id, syn: [] };
    const where = toolMenu(t.id);
    add({ id: `tool.${t.id}`, ...where, title: t.title, en: meta.en, syn: ["ابزار", "tool", ...meta.syn], key: t.key, tip: t.hint, run: (h) => h.tool(t.id) });
  }

  // ── افزوده‌های نوبت‌های بعد
  for (const c of extra) add(c);
  return C;
}

// ───────────────────────── جستجو
const DIGITS_AR = /[٠-٩]/g;
const DIGITS_FA = /[۰-۹]/g;
/** یکسان‌سازیِ نوشتار: ي/ك عربی، نیم‌فاصله، اعرابِ فارسی و رقم‌های فارسی/عربی، حروفِ بزرگ لاتین */
export function norm(s: string): string {
  return s
    .toLowerCase()
    .replace(/ي|ى/g, "ی")
    .replace(/ك/g, "ک")
    .replace(/ۀ/g, "ه")
    .replace(/[ً-ٰٟـ]/g, "")
    .replace(DIGITS_AR, (d) => String(d.charCodeAt(0) - 0x660))
    .replace(DIGITS_FA, (d) => String(d.charCodeAt(0) - 0x6f0))
    .replace(/[‌‍‎‏]/g, " ")
    .replace(/[()«»\-_/،,.:؛;!؟?[\]{}"'+]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

export type Hit = { cmd: Command; score: number; reason: string | null };

/** هرچه امتیاز بالاتر بهتر؛ همهٔ واژه‌های جستجو باید جایی (عنوان، نامِ انگلیسی، هم‌معنی، گروه، منو) پیدا شوند */
export function searchCommands(cmds: Command[], q: string, h?: Host): Hit[] {
  const toks = norm(q).split(" ").filter(Boolean);
  const keyq = q.toLowerCase().replace(/\s+/g, "");
  const out: Hit[] = [];
  for (const cmd of cmds) {
    const title = norm(cmd.title);
    const en = norm(cmd.en);
    const syn = (cmd.syn ?? []).map(norm);
    const grp = norm(cmd.group);
    const menu = norm(MENUS.find((m) => m.id === cmd.menu)?.title ?? "");
    let score = 0;
    let ok = toks.length > 0;
    for (const t of toks) {
      let s = 0;
      if (title.startsWith(t)) s = 40;
      else if (title.split(" ").some((w) => w.startsWith(t))) s = 32;
      else if (title.includes(t)) s = 22;
      else if (en.startsWith(t) || en.split(" ").some((w) => w.startsWith(t))) s = 30;
      else if (syn.some((x) => x === t)) s = 28;
      else if (syn.some((x) => x.startsWith(t) || x.split(" ").some((w) => w.startsWith(t)))) s = 20;
      else if (en.includes(t) || syn.some((x) => x.includes(t))) s = 12;
      else if (grp.includes(t) || menu.includes(t)) s = 6;
      if (!s) {
        ok = false;
        break;
      }
      score += s;
    }
    // کلید: «ctrl+j» یا «j»
    if (!ok && cmd.key && keyq.length >= 1 && cmd.key.toLowerCase().replace(/\s+/g, "") === keyq) {
      ok = true;
      score = 26;
    }
    if (!ok) continue;
    out.push({ cmd, score, reason: h && cmd.enabled ? cmd.enabled(h) : null });
  }
  // فعال‌ها اول، بعد امتیاز، بعد کوتاه‌تر
  out.sort((a, b) => Number(!!a.reason) - Number(!!b.reason) || b.score - a.score || a.cmd.title.length - b.cmd.title.length);
  return out;
}
