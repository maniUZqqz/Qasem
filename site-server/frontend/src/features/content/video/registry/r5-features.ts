import type { Project } from "../manual/model";
import { verticalText } from "../manual/r5ops";
import { F } from "./core-edit";
import { FeatureDef, needClips, needText, needVisual } from "./types";

const selTrackOf = (a: Parameters<FeatureDef["run"]>[0]) => a.selected!.track;
const needTrack = (a: Parameters<NonNullable<FeatureDef["when"]>>[0]): string | null => (a.selected ? null : "اول یک قطعه را روی تایم‌لاین انتخاب کنید (ترکِ آن کار می‌کند)");
const toggleSync = (p: Project, id: string): Project => ({ ...p, tracks: p.tracks.map((t) => (t.id === id ? { ...t, sync: !t.sync } : t)) });
const syncAll = (p: Project): Project => {
  const on = !p.tracks.filter((t) => t.kind !== "text").every((t) => t.sync);
  return { ...p, tracks: p.tracks.map((t) => (t.kind === "text" ? t : { ...t, sync: on })) };
};

/** دورِ پنجم: ابزارهای رنگِ خودکار، رسانه‌ها، قفلِ همگامی، ویرایش با متن، مسیرِ حرکت، متنِ عمودی */
export const R5_FEATURES: FeatureDef[] = [
  // ───────────── رنگ
  F("color.auto", "color", "تنظیمِ رنگ", "رنگِ خودکار (Auto color)", "Auto color",
    "از روی یک فریمِ قطعه نوردهی، کنتراست، تعادلِ سفید و اشباع را خودکار تنظیم می‌کند؛ نتیجه لغزنده‌های همین قطعه است و قابلِ ویرایش و برگشت.",
    (a) => a.op.autoColor(), { when: needVisual, words: ["auto color", "auto tone", "auto contrast", "auto white balance", "رنگ خودکار", "اصلاح خودکار", "نور خودکار", "تعادل سفید خودکار"] }),
  F("color.wb-eyedropper", "color", "تنظیمِ رنگ", "قطره‌چکانِ تعادلِ سفید", "White balance eyedropper",
    "روی یک نقطهٔ تصویر که باید سفید یا خاکستری باشد کلیک کنید؛ دما و تینتِ قطعه طوری تنظیم می‌شود که آن نقطه بی‌رنگ شود.",
    (a) => a.op.pickWhiteBalance(), { when: needVisual, words: ["white balance", "eyedropper", "picker", "wb", "قطره چکان", "قطره‌چکان", "تعادل سفید", "رنگ غالب", "دما"] }),
  F("color.match", "color", "تنظیمِ رنگ", "تطبیقِ رنگِ دو نما (Color match)", "Color match",
    "رنگ و روشنایی این نما را به نمای دیگری که انتخاب می‌کنید نزدیک می‌کند تا دو نما در کنار هم یکدست دیده شوند.",
    (a) => a.openPanel("color-match"), { when: needVisual, words: ["color match", "match", "shot match", "تطبیق رنگ", "هماهنگ کردن رنگ", "یکدست", "شبیه نمای دیگر"] }),
  F("color.hue-vs", "color", "تنظیمِ رنگ", "منحنی‌های Hue-vs (رنگ در برابرِ اشباع / رنگ / روشنایی)", "Hue vs Sat / Hue / Lum curves",
    "شش نقطه روی چرخهٔ رنگ (قرمز تا ارغوانی)؛ هر رنگ را جدا کم‌رنگ، تغییرِ رنگ یا روشن/تیره کنید. همان HSLِ ثانویه با نمودار.",
    (a) => a.openPanel("huevs"), { when: needVisual, words: ["hue vs sat", "hue vs hue", "hue vs lum", "hue curves", "secondary", "رنگ در برابر اشباع", "منحنی رنگ", "هیو", "ثانویه"] }),
  // ───────────── رسانه‌ها
  F("file.bin-search", "file", "آوردن", "جستجو در رسانه‌ها", "Search media",
    "نامِ ویدیو، صدا یا عکس را بنویسید تا فهرستِ رسانه‌ها همان‌جا فیلتر شود.",
    (a) => a.click("bin-search"), { words: ["search media", "find clip", "filter", "جستجو", "پیدا کردن فیلم", "فیلتر رسانه"] }),
  F("file.bin-folder", "file", "آوردن", "پوشهٔ تازه برای رسانه‌ها (Bin)", "New bin",
    "پوشه بسازید و رسانه‌ها را در آن دسته‌بندی کنید (برای پروژه‌های بزرگ). پوشه‌ها در همین پروژه ذخیره می‌شوند.",
    (a) => a.click("bin-new-folder"), { words: ["bin", "folder", "organize", "new bin", "پوشه", "دسته بندی", "سطل"] }),
  F("win.source-jkl", "window", "پنل‌ها", "پخشِ J / K / L در مانیتورِ منبع", "Source monitor J/K/L",
    "در مانیتورِ منبع: J = عقب، K = ایست، L = جلو؛ هر بار تکرار کنید سریع‌تر می‌شود (تا ۴ برابر).",
    (a) => a.openPanel("source"), { words: ["jkl", "shuttle", "j k l", "پخش سریع", "عقب جلو"] }),
  // ───────────── تایم‌لاین
  F("seq.sync-lock", "sequence", "ترک‌ها", "قفلِ همگامی برای ترکِ قطعهٔ انتخاب‌شده (Sync lock)", "Sync lock",
    "با «حذفِ بی‌فاصله» روی ترکی دیگر، این ترک هم به اندازهٔ جای خالی جلو می‌آید و صدا و تصویر از هم جدا نمی‌شوند.",
    (a) => { const tr = selTrackOf(a); a.apply(tr.sync ? "برداشتنِ قفلِ همگامی" : "قفلِ همگامی", (p) => toggleSync(p, tr.id)); },
    { when: needTrack, on: (a) => !!a.selected?.track.sync, words: ["sync lock", "sync", "lock sync", "همگامی", "قفل همگامی", "هم زمان"] }),
  F("seq.sync-lock-all", "sequence", "ترک‌ها", "قفلِ همگامی برای همهٔ ترک‌های تصویر و صدا", "Sync lock all tracks",
    "همهٔ ترک‌های تصویر و صدا با هم جلو می‌آیند. بهترین حالت برای ویرایشِ گفتگو و مصاحبه.",
    (a) => a.apply("قفلِ همگامیِ همهٔ ترک‌ها", syncAll),
    { when: needClips, on: (a) => a.project.tracks.filter((t) => t.kind !== "text").every((t) => t.sync), words: ["sync lock all", "all tracks", "همه ترک ها", "قفل همگامی همه"] }),
  F("edit.text-based", "edit", "ویرایش با متن", "ویرایش با متنِ گفتار (کلمه را انتخاب کن و حذف کن)", "Text-based editing",
    "گفتار به‌صورتِ متن نشان داده می‌شود؛ هر کلمه یا جمله را انتخاب و حذف کنید تا همان بخش از ویدیو بریده شود. مکث‌های طولانی را هم یک‌جا می‌برد.",
    (a) => a.openPanel("transcript"), { words: ["text based editing", "transcript", "edit by text", "delete words", "متن گفتار", "ویرایش با متن", "حذف کلمه", "رونوشت", "مکث"] }),
  F("clip.motion-path", "clip", "حرکت و ترکیب", "مسیرِ حرکت روی قاب (Motion path)", "Motion path",
    "مسیرِ حرکتِ قطعه را روی قاب می‌بینید؛ نقطه‌ها را بکشید یا نقطهٔ تازه بگذارید. هر نقطه یک کلیدفریمِ جابه‌جایی است.",
    (a) => a.openPanel("motionpath"), { when: needVisual, words: ["motion path", "path", "trajectory", "move along", "مسیر حرکت", "مسیر", "جابه جایی", "انیمیشن حرکتی"] }),
  F("clip.adjustment-layer", "clip", "حرکت و ترکیب", "لایهٔ تنظیم (Adjustment layer)", "Adjustment layer",
    "یک لایهٔ بی‌تصویر روی بقیه می‌گذارد؛ رنگ، LUT و افکتی که به آن بدهید روی همهٔ ترک‌های زیرش اعمال می‌شود، فقط در مدتِ خودش. یک‌جا رنگ‌بندیِ کلِ فیلم.",
    (a) => a.op.addAdjustment(), { when: needClips, words: ["adjustment layer", "adjust layer", "grade all", "لایه تنظیم", "لایه رنگ", "رنگ بندی همه", "یکجا رنگ"] }),
  F("clip.luma-key", "clip", "حرکت و ترکیب", "کلیدِ روشنایی (Luma key)", "Luma key",
    "تاریک‌ها (یا روشن‌ها)ی قطعه را شفاف می‌کند؛ برای افکتِ نور، دود و آتش روی پس‌زمینهٔ سیاه.",
    (a) => a.openPanel("clipfx", { section: "luma" }), { when: needVisual, words: ["luma key", "lumakey", "key out black", "screen", "کلید روشنایی", "حذف سیاه", "افکت نور", "شفاف کردن تاریک"] }),
  F("clip.lens-correct", "clip", "حرکت و ترکیب", "اصلاحِ اعوجاجِ لنز (Lens distortion)", "Lens distortion correction",
    "خم‌شدنِ خط‌ها در لنزِ واید یا اکشن‌کم را صاف می‌کند (یا برعکس، برای حالتِ هنری).",
    (a) => a.openPanel("clipfx", { section: "lens" }), { when: needVisual, words: ["lens distortion", "lens correction", "fisheye", "barrel", "wide angle", "اعوجاج لنز", "لنز", "ماهی چشم", "صاف کردن خط"] }),
  F("clip.track-matte", "clip", "حرکت و ترکیب", "ماتِ ترک (Track matte)", "Track matte",
    "قطعه فقط از پشتِ قطعهٔ هم‌زمانِ ترکِ بالاتر دیده می‌شود (روشنایی یا شفافیتِ آن قطعه معیار است)؛ مثلاً ویدیو داخلِ یک شکل یا نوشته.",
    (a) => a.openPanel("clipfx", { section: "matte" }), { when: needVisual, words: ["track matte", "luma matte", "alpha matte", "video in text", "mask by layer", "مات ترک", "ماتِ لایه", "ویدیو داخل نوشته", "ویدیو داخل شکل"] }),
  F("clip.anchor-point", "clip", "حرکت و ترکیب", "نقطهٔ لنگر (Anchor point)", "Anchor point",
    "مرکزِ چرخش و بزرگ‌نماییِ قطعه را عوض می‌کند؛ مثلاً از گوشه یا لبه بچرخد.",
    (a) => a.openPanel("clipfx", { section: "anchor" }), { when: needVisual, words: ["anchor point", "pivot", "rotate around", "نقطه لنگر", "مرکز چرخش", "محور چرخش", "پیوت"] }),
  F("file.export-multi", "file", "خروجی", "چند خروجی یک‌جا (ریلز + یوتیوب + تلگرام + GIF…)", "Multi-output render queue",
    "چند خروجی را تیک می‌زنید و یکی‌یکی به صفِ رندر می‌روند (سرور هم‌زمان سه رندر می‌پذیرد، بقیه منتظر می‌مانند). خطای یکی بقیه را نمی‌ایستاند.",
    (a) => a.openPanel("outqueue"), { when: needClips, words: ["multi output", "render queue", "batch export", "export all", "چند خروجی", "صف رندر", "همه خروجی ها", "یکجا خروجی"] }),
  F("file.export-on-site", "file", "خروجی", "ساختِ خروجی روی خودِ سایت (دستی)", "Render on the site (manual)",
    "رندرِ نهایی را عمداً روی خودِ سرورِ سایت می‌سازد (کندتر). رندرِ نهایی همیشه منتظرِ سرورِ پردازش می‌ماند و خودکار به سایت برنمی‌گردد؛ این فقط وقتی است که خودتان بخواهید.",
    (a) => a.op.renderOnSite(), { when: needClips, words: ["site render", "render on site", "cpu render", "رندر روی سایت", "ساخت روی سایت", "دستی", "خروجی روی سایت"] }),
  F("clip.render-replace", "clip", "ساختار", "رندر و جایگزینی (Render and replace)", "Render and replace",
    "قطعه‌های انتخاب‌شده با همهٔ افکت و رنگشان روی سرور یک فایل می‌شوند و همان فایل جایشان می‌نشیند؛ برای بخش‌های سنگین که پیش‌نمایششان کند است. Ctrl+Z برمی‌گرداند.",
    (a) => a.op.renderReplace(), { when: needClips, words: ["render and replace", "render replace", "bake", "flatten", "prerender", "رندر و جایگزینی", "پختن", "تبدیل به یک فایل", "سبک کردن", "پیش رندر"] }),
  // ───────────── گرافیک
  F("gfx.caption-translate", "graphics", "زیرنویس", "ترجمهٔ زیرنویس به زبانِ دیگر", "Translate captions",
    "خط‌های زیرنویسِ تایم‌لاین را با هوش مصنوعی به انگلیسی، عربی، ترکی و… ترجمه می‌کند و روی ترکِ تازه می‌گذارد؛ اصل می‌ماند. اگر هوش مصنوعی در دسترس نباشد دلیلش را می‌گوید.",
    (a) => a.openPanel("translate"), { words: ["translate captions", "translate subtitles", "subtitle translation", "ترجمه زیرنویس", "ترجمه", "انگلیسی کردن", "زیرنویس انگلیسی"] }),
  F("gfx.vertical-text-down", "graphics", "متن و عنوان", "متنِ عمودی (خواندن از بالا به پایین)", "Vertical text (top to bottom)",
    "متنِ انتخاب‌شده ۹۰ درجه می‌چرخد و کنارِ راستِ قاب می‌نشیند؛ مناسبِ نوارِ کناری و برچسب.",
    (a) => a.apply("متنِ عمودی", (p) => verticalText(p, a.selected!.clip.id, "right")), { when: needText, words: ["vertical text", "vertical type", "sideways", "متن عمودی", "عمودی", "چرخش متن", "نوشته کنار"] }),
  F("gfx.vertical-text-up", "graphics", "متن و عنوان", "متنِ عمودی (خواندن از پایین به بالا)", "Vertical text (bottom to top)",
    "متنِ انتخاب‌شده ۹۰ درجه به سمتِ دیگر می‌چرخد و کنارِ چپِ قاب می‌نشیند.",
    (a) => a.apply("متنِ عمودی", (p) => verticalText(p, a.selected!.clip.id, "left")), { when: needText, words: ["vertical text", "متن عمودی", "عمودی"] }),
];
