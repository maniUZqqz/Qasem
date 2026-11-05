import { MediaClip, updateClip } from "../manual/model";
import { F } from "./core-edit";
import { FeatureDef, needMedia, needVisual } from "./types";

const sel = (a: { selected: { clip: { id: string } } | null }) => a.selected!.clip.id;
const clipOf = (a: { selected: { clip: unknown } | null }) => a.selected?.clip as MediaClip | undefined;
/** گذاشتنِ یک ویژگیِ صوتیِ روشن/خاموش روی قطعهٔ انتخاب‌شده */
const audioFlag = (key: "denoise" | "normalize" | "enhance", label: string) => (a: Parameters<FeatureDef["run"]>[0]) => {
  const c = clipOf(a)!;
  a.apply(label, (pr) => updateClip(pr, c.id, { audio: { ...(c.audio ?? {}), [key]: !c.audio?.[key] } }));
};
const audioFlagOn = (key: "denoise" | "normalize" | "enhance") => (a: Parameters<NonNullable<FeatureDef["on"]>>[0]) => !!clipOf(a)?.audio?.[key];
const hasSound = (a: Parameters<NonNullable<FeatureDef["when"]>>[0]): string | null =>
  needMedia(a) ?? (clipOf(a)!.kind === "image" ? "عکس صدا ندارد" : null);

/** گرافیک، رنگ، صدا، نما، پنجره، راهنما */
export const CORE_UI: FeatureDef[] = [
  // ───────────────────────────── گرافیک
  F("gfx.new-text", "graphics", "متن و عنوان", "متنِ تازه (تیتر)", "New title", "یک متن در سرِ پخش می‌گذارد و تنظیماتش را باز می‌کند.", (a) => a.op.newText(), { keys: "T", legacy: true, words: ["title", "text", "تیتر", "عنوان", "نوشته"] }),
  F("gfx.templates", "graphics", "متن و عنوان", "قالب‌های عنوان (پایین‌نویس، تیترِ بزرگ…)", "Title templates", "۹ قالبِ آمادهٔ فارسی: پایین‌نویس، تیترِ بزرگ، استیکر، حباب…", (a) => { if (a.selected?.clip.type !== "text") a.op.newText(); a.reveal("text", "tx-templates"); }, { words: ["templates", "lower third", "پایین نویس", "قالب", "essential graphics"] }),
  F("gfx.text-style", "graphics", "متن و عنوان", "فونت، رنگ، لبه و سایهٔ متن", "Text style", "فونتِ فارسی، اندازه، رنگ، لبه، سایه و کادرِ پشتِ متن.", (a) => a.setTab("text"), { words: ["font", "فونت", "style", "stroke", "shadow", "سایه"] }),
  F("gfx.text-anim", "graphics", "متن و عنوان", "انیمیشنِ ورود و خروجِ متن", "Text animation", "ورودِ لغزان، جهشی، ماشین‌تحریر، زوم، محو و…", (a) => a.setTab("text"), { words: ["animation", "anim", "انیمیشن", "typewriter"] }),
  F("gfx.quick-templates", "graphics", "قالب‌های آماده", "تیترِ شروع، کارتِ پایانی و ۹:۱۶ برای همه", "Intro / outro templates", "با یک کلیک تیترِ ثانیه‌های اول، کارتِ پایانیِ «همین حالا سفارش بده» یا ۹:۱۶کردنِ همهٔ قطعه‌ها.", (a) => { a.select([]); a.reveal("text"); }, { words: ["intro", "outro", "end card", "کارت پایانی", "قلاب", "hook"] }),
  F("gfx.captions", "graphics", "زیرنویس", "زیرنویسِ خودکار (گفتار به متن)", "Auto captions / speech-to-text", "گفتارِ ویدیو را می‌شنود و زیرنویسِ کلمه‌به‌کلمه می‌سازد (به سرورِ پردازش نیاز دارد).", (a) => a.setTab("captions"), { words: ["captions", "subtitles", "speech to text", "transcribe", "زیرنویس", "گفتار", "متن گفتار"] }),
  F("gfx.caption-styles", "graphics", "زیرنویس", "سبکِ زیرنویس (پرانرژی، کادر، کارائوکه…)", "Caption styles", "پنج سبکِ آمادهٔ زیرنویسِ فارسی با هایلایتِ کلمه.", (a) => a.setTab("captions"), { words: ["caption style", "karaoke", "کارائوکه", "هایلایت"] }),
  F("gfx.srt-import", "graphics", "زیرنویس", "زیرنویس از فایلِ ساخته‌شدهٔ ویدیو (SRT)", "Import captions", "زیرنویسِ قبلاً ساخته‌شدهٔ یک ویدیو را به ترکِ متن می‌آورد.", (a) => a.setTab("captions"), { words: ["srt", "import", "زیرنویس", "وارد"] }),
  F("gfx.shape", "graphics", "شکل و استیکر", "شکل (مستطیل، دایره، ستاره، قلب…)", "Shapes", "نُه شکلِ رنگی با گرادیان و لبه.", (a) => a.reveal("pro", "sec-graphics"), { words: ["shape", "rectangle", "circle", "شکل"] }),
  F("gfx.sticker", "graphics", "شکل و استیکر", "استیکر و برچسب (تخفیف، جدید، ارسال رایگان…)", "Stickers", "برچسب‌های آمادهٔ فروشگاهی و ایموجی.", (a) => a.reveal("pro", "sec-graphics"), { words: ["sticker", "emoji", "badge", "برچسب", "تخفیف", "ایموجی"] }),
  F("gfx.safe-zone", "graphics", "شکل و استیکر", "حاشیهٔ امنِ پلتفرم", "Safe margins", "نشان می‌دهد کجای تصویر را دکمه‌ها و نوشته‌های اینستاگرام، تیک‌تاک و… می‌پوشانند.", (a) => a.click("safezone-select"), { words: ["safe zone", "safe margins", "ناحیه امن", "اینستاگرام", "تیک تاک"] }),
  F("gfx.tracker", "graphics", "شکل و استیکر", "چسباندنِ متن یا شکل به حرکت (Tracker)", "Attach to motion", "متن یا شکل به یک نقطهٔ متحرکِ ویدیو می‌چسبد.", (a) => a.reveal("pro", "sec-track"), { when: needMedia, words: ["tracker", "attach", "ردیاب"] }),
  // ───────────────────────────── رنگ
  F("color.basic", "color", "تنظیمِ رنگ", "نور و رنگِ پایه", "Basic correction", "نوردهی، کنتراست، سایه، روشنایی‌ها، دما و سایه‌رنگ، اشباع.", (a) => a.reveal("color", "color-basic"), { when: needVisual, words: ["lumetri", "basic", "exposure", "contrast", "temperature", "saturation", "نور", "کنتراست", "اشباع", "دما"] }),
  F("color.looks", "color", "تنظیمِ رنگ", "حالت‌های آماده (Looks): سینمایی، گرم، سیاه‌وسفید…", "Looks / creative", "بیش از ۱۵ حالتِ رنگیِ آماده با شدتِ قابلِ تنظیم.", (a) => a.reveal("color", "color-looks"), { when: needVisual, words: ["looks", "creative", "cinematic", "filter", "فیلتر", "سینمایی"] }),
  F("color.curves", "color", "تنظیمِ رنگ", "منحنیِ رنگ (RGB)", "Curves", "منحنیِ تُن برای روشنایی و هر کانالِ رنگ.", (a) => a.reveal("color", "color-curves"), { when: needVisual, words: ["curves", "rgb curves", "منحنی"] }),
  F("color.wheels", "color", "تنظیمِ رنگ", "چرخ‌های رنگ (سایه، میانه، روشن)", "Color wheels", "رنگ‌دهیِ جداگانهٔ سایه‌ها، میانه‌ها و روشنایی‌ها.", (a) => a.reveal("color", "color-wheels"), { when: needVisual, words: ["wheels", "lift gamma gain", "چرخ", "grading"] }),
  F("color.hsl", "color", "تنظیمِ رنگ", "رنگ به رنگ (HSL)", "HSL secondary", "هر رنگ (قرمز، زرد، سبز…) را جداگانه تغییر رنگ، اشباع و روشنایی بدهید.", (a) => a.reveal("color", "color-hsl"), { when: needVisual, words: ["hsl", "secondary", "hue", "رنگ به رنگ", "ثانویه"] }),
  F("color.fx", "color", "تنظیمِ رنگ", "تیزی، نویز، محو، وینیت و دانه", "Sharpen / vignette / grain", "جلوه‌های تصویر روی همین قطعه.", (a) => a.reveal("color", "color-fx"), { when: needVisual, words: ["sharpen", "vignette", "grain", "blur", "noise", "تیز", "دانه", "وینیت"] }),
  F("color.lut", "color", "تنظیمِ رنگ", "LUT (فایلِ رنگ‌بندی)", "LUT / look-up table", "یک LUTِ .cube را روی قطعه بزنید و شدتش را تنظیم کنید.", (a) => a.reveal("pro", "sec-lut"), { when: needVisual, words: ["lut", "cube", "رنگ بندی"] }),
  F("color.scopes", "color", "اسکوپ‌ها", "اسکوپ‌ها (موج، برداری، هیستوگرام، پرید)", "Scopes", "نمودارهای دقیقِ رنگ و روشنایی زیرِ سرِ پخش.", (a) => a.toggle("scopes"), { on: (a) => a.flags.scopes, words: ["scopes", "waveform", "vectorscope", "histogram", "parade", "موج", "برداری", "هیستوگرام"] }),
  F("color.compare", "color", "اسکوپ‌ها", "مقایسهٔ قبل و بعدِ رنگ", "Before / after", "دکمهٔ «نگه دارید» تصویرِ بدونِ رنگ را نشان می‌دهد.", (a) => a.reveal("color"), { when: needVisual, words: ["before after", "compare", "قبل و بعد", "مقایسه"] }),
  F("color.reset", "color", "تنظیمِ رنگ", "بازنشانیِ رنگِ این قطعه", "Reset color", "همهٔ تنظیماتِ رنگِ قطعه را به حالتِ اولیه برمی‌گرداند.", (a) => a.apply("بازنشانیِ رنگ", (pr) => updateClip(pr, sel(a), { color: undefined })), { when: (a) => needVisual(a) ?? (clipOf(a)!.color ? null : "این قطعه رنگِ تنظیم‌شده‌ای ندارد"), words: ["reset", "remove color", "پاک"] }),
  // ───────────────────────────── صدا
  F("audio.panel", "audio", "قطعه", "تنظیمِ صدای قطعه", "Clip audio", "بلندی، پن، محو، EQ، کمپرسور و بهبودِ صدای قطعهٔ انتخاب‌شده.", (a) => a.setTab("audio"), { words: ["clip mixer", "audio", "volume", "gain", "بلندی", "پن"] }),
  F("audio.eq", "audio", "قطعه", "EQ و بهبودِ صدا", "Equalizer", "پیش‌تنظیم‌های EQ (گفتار واضح، گرم، تلفنی…)، کمپرسور و تقویتِ گفتار.", (a) => a.reveal("audio", "ap-eq"), { when: hasSound, words: ["eq", "equalizer", "compressor", "limiter", "bass", "treble", "بم", "زیر", "کمپرسور"] }),
  F("audio.denoise", "audio", "قطعه", "حذفِ نویزِ پس‌زمینه", "Denoise", "نویزِ ثابت (فن، باد، هیس) را از صدا می‌گیرد؛ در خروجی اعمال می‌شود.", audioFlag("denoise", "حذفِ نویز"), { when: hasSound, on: audioFlagOn("denoise"), words: ["denoise", "noise reduction", "نویز", "هیس"] }),
  F("audio.normalize", "audio", "قطعه", "یکسان‌سازیِ بلندیِ قطعه (−۱۶ LUFS)", "Normalize clip", "بلندیِ این قطعه را در حدِ استاندارد یکسان می‌کند.", audioFlag("normalize", "یکسان‌سازیِ بلندی"), { when: hasSound, on: audioFlagOn("normalize"), words: ["normalize", "loudness", "gain", "یکسان", "بلندی"] }),
  F("audio.enhance", "audio", "قطعه", "تقویتِ صدای گفتار", "Enhance speech", "فیلتر، نویزگیر، EQ و کمپرسورِ مناسبِ گفتار را یک‌جا می‌زند.", audioFlag("enhance", "تقویتِ گفتار"), { when: hasSound, on: audioFlagOn("enhance"), words: ["enhance", "clean voice", "voice", "صدای تمیز", "گفتار"] }),
  F("audio.mixer", "audio", "ترک‌ها", "میکسر (بلندی، پن، Mute، Solo هر ترک)", "Track mixer", "فیدرِ هر ترک، میترِ زنده، مستر و لیمیتر.", (a) => a.setTab("mixer"), { words: ["mixer", "track mixer", "fader", "mute", "solo", "میکسر", "مستر", "master"] }),
  F("audio.ducking", "audio", "ترک‌ها", "کم‌شدنِ خودکارِ موسیقی زیرِ گفتار", "Auto ducking", "هر جا حرف می‌زنند موسیقی نرم کم می‌شود و بعد برمی‌گردد.", (a) => a.setTab("mixer"), { words: ["ducking", "duck", "sidechain", "زیر گفتار", "کم شدن"] }),
  F("audio.roles", "audio", "ترک‌ها", "نقشِ ترک (گفتار / موسیقی / افکت)", "Track role", "با دکمهٔ نقشِ بالای هر ترک در میکسر، ترک را گفتار، موسیقی یا افکت می‌کنید.", (a) => a.setTab("mixer"), { words: ["dialogue", "music", "sfx", "ambience", "role", "نقش", "گفتار", "موسیقی", "افکت"] }),
  F("audio.add-music", "audio", "یک‌کلیکی", "موسیقیِ پس‌زمینه", "Background music", "موسیقی انتخاب یا با هوش مصنوعی بسازید؛ خودکار زیرِ ویدیو می‌نشیند و زیرِ گفتار کم می‌شود.", (a) => a.click("sq-add-music", "audio"), { when: needClipsForSound, words: ["music", "موسیقی", "آهنگ", "soundtrack"] }),
  F("audio.remove-silence", "audio", "یک‌کلیکی", "حذفِ سکوت‌ها", "Remove silences", "مکث‌های بی‌صدا را می‌برد و گفتار را فشرده می‌کند.", (a) => a.click("sq-remove-silence", "audio"), { when: needClipsForSound, words: ["silence", "ripple", "سکوت", "مکث", "jump cut"] }),
  F("audio.remove-fillers", "audio", "یک‌کلیکی", "حذفِ «اِم و اوم»", "Remove filler sounds", "صداهای مکث‌دار را با کمکِ تشخیصِ گفتار می‌برد.", (a) => a.click("sq-remove-fillers", "audio"), { when: needClipsForSound, words: ["filler", "um", "uh", "ام", "اوم"] }),
  F("audio.loudness", "audio", "یک‌کلیکی", "بلندیِ استانداردِ شبکه‌ها (−۱۴ LUFS)", "Social loudness", "بلندیِ نهایی را برای اینستاگرام و تیک‌تاک استاندارد می‌کند.", (a) => a.click("sq-loudness", "audio"), { when: needClipsForSound, words: ["loudness", "lufs", "normalize", "master", "بلندی"] }),
  F("audio.voiceover", "audio", "یک‌کلیکی", "گویندگی از متن یا فایلِ ضبط‌شده", "Voice-over", "متن را به گفتارِ فارسی تبدیل می‌کند یا فایلِ ضبطِ گوشی را می‌آورد.", (a) => a.click("sq-voiceover", "audio"), { words: ["voice over", "tts", "narration", "گویندگی", "گوینده", "ضبط", "رکورد"] }),
  F("audio.auto-mix", "audio", "یک‌کلیکی", "تنظیمِ خودکارِ میکس", "Auto mix", "بلندیِ گفتار و موسیقی را متعادل و صدا را استاندارد می‌کند.", (a) => a.click("sq-automix", "audio"), { when: needClipsForSound, words: ["auto mix", "balance", "میکس", "متعادل"] }),
  F("audio.beats", "audio", "یک‌کلیکی", "علامت‌گذاریِ ضرب‌ها", "Detect beats", "ضرب‌های موسیقی را نشانگر می‌کند.", (a) => a.op.beats(), { when: needMedia, words: ["beats", "bpm", "ضرب"] }),
  // ───────────────────────────── نما
  F("view.zoom-in", "view", "بزرگ‌نمایی", "بزرگ‌نماییِ تایم‌لاین", "Zoom in", "تایم‌لاین را بزرگ‌تر می‌کند.", (a) => a.zoom(1.25), { keys: "=", legacy: true, words: ["zoom in", "+", "بزرگ"] }),
  F("view.zoom-out", "view", "بزرگ‌نمایی", "کوچک‌نماییِ تایم‌لاین", "Zoom out", "تایم‌لاین را کوچک‌تر می‌کند.", (a) => a.zoom(0.8), { keys: "-", legacy: true, words: ["zoom out", "کوچک"] }),
  F("view.zoom-fit", "view", "بزرگ‌نمایی", "جا شدنِ کلِ پروژه در تایم‌لاین", "Zoom to fit", "کلِ پروژه را در عرضِ تایم‌لاین جا می‌دهد.", (a) => a.zoom("fit"), { keys: "\\", legacy: true, words: ["fit", "zoom fit", "جا شدن"] }),
  F("view.scopes", "view", "نما", "اسکوپ‌ها", "Scopes", "موج، برداری، هیستوگرام و پرید.", (a) => a.toggle("scopes"), { on: (a) => a.flags.scopes, words: ["waveform", "vectorscope", "histogram"] }),
  F("view.safe-zone", "view", "نما", "حاشیهٔ امن", "Safe margins", "نوارِ حاشیهٔ امنِ عمومی یا هر پلتفرم روی مانیتور.", (a) => a.click("safezone-select"), { words: ["safe zone", "margins", "ناحیه امن"] }),
  F("view.crop", "view", "نما", "برشِ قاب روی مانیتور", "Crop overlay", "دستگیره‌های برشِ قاب روی تصویر.", (a) => a.toggle("crop"), { when: needVisual, on: (a) => a.flags.crop, words: ["crop", "برش"] }),
  F("view.vol-line", "view", "نما", "خطِ بلندیِ صدا روی قطعه‌ها", "Volume line", "خطِ بلندی (rubber band) و مثلثِ محو روی قطعه‌های صدا.", (a) => a.toggle("volLine"), { on: (a) => a.flags.volLine, words: ["rubber band", "volume", "keyframe", "بلندی", "خط"] }),
  F("view.snap", "view", "نما", "چسبیدن (Snap)", "Snap", "چسبیدن به لبه‌ها و نشانگرها.", (a) => a.toggle("snap"), { on: (a) => a.flags.snap, words: ["snap", "چسبیدن"] }),
  F("view.menubar", "view", "نما", "نوارِ منوی کامل", "Menu bar", "منوی کاملِ ابزارها را نشان یا پنهان می‌کند.", (a) => a.toggle("menubar"), { on: (a) => a.flags.menubar, words: ["menu", "منو", "همه ابزارها"] }),
  F("view.fullscreen", "view", "نما", "تمام‌صفحه", "Full screen", "فضای کار را تمام‌صفحه می‌کند.", (a) => a.click("ws-fullscreen"), { words: ["fullscreen"] }),
  // ───────────────────────────── پنجره
  F("win.clip", "window", "پنل‌ها", "پنلِ قطعه", "Clip panel", "ویژگی‌های قطعهٔ انتخاب‌شده: حرکت، سرعت، گذار، ماسک…", (a) => a.setTab("clip"), { words: ["effect controls", "inspector", "قطعه"] }),
  F("win.color", "window", "پنل‌ها", "پنلِ رنگ", "Color panel", "همهٔ ابزارهای رنگ.", (a) => a.setTab("color"), { words: ["lumetri", "رنگ"] }),
  F("win.audio", "window", "پنل‌ها", "پنلِ صدا", "Audio panel", "صدای قطعه و کارت‌های یک‌کلیکی.", (a) => a.setTab("audio"), { words: ["audio", "صدا"] }),
  F("win.text", "window", "پنل‌ها", "پنلِ متن", "Text panel", "متن و قالب‌های عنوان.", (a) => a.setTab("text"), { words: ["essential graphics", "متن"] }),
  F("win.effects", "window", "پنل‌ها", "پنلِ افکت‌ها", "Effects panel", "افکت‌های تصویر و ابزارهای کلِ ویدیو.", (a) => a.setTab("fx"), { words: ["effects", "افکت"] }),
  F("win.mixer", "window", "پنل‌ها", "پنلِ میکسر", "Mixer panel", "فیدر و میترِ ترک‌ها.", (a) => a.setTab("mixer"), { words: ["mixer", "میکسر"] }),
  F("win.captions", "window", "پنل‌ها", "پنلِ زیرنویس", "Captions panel", "زیرنویسِ خودکار و سبک‌ها.", (a) => a.setTab("captions"), { words: ["captions", "زیرنویس"] }),
  F("win.tools", "window", "پنل‌ها", "پنلِ ابزارها (تودرتو، مولتی‌کم، ردیاب، LUT)", "Tools panel", "ابزارهای ویژه: شکل، تودرتو، مولتی‌کم، ضرب، ردیاب، LUT، حذفِ پس‌زمینه.", (a) => a.setTab("pro"), { words: ["tools", "pro", "ابزارها"] }),
  F("win.output", "window", "پنل‌ها", "پنلِ خروجی و پروژه", "Export panel", "پروژه، قاب، پیش‌تنظیم‌های خروجی، صفِ رندر و نسخه‌ها.", (a) => a.setTab("out"), { words: ["export", "project", "خروجی", "پروژه"] }),
  F("win.history", "window", "پنل‌ها", "تاریخچهٔ تغییرها", "History", "فهرستِ همهٔ تغییرها با امکانِ پرش به هر لحظه.", (a) => a.openPanel("history"), { words: ["history", "تاریخچه"] }),
  F("win.shortcuts-edit", "window", "پنل‌ها", "ویرایشِ میان‌برها", "Keyboard shortcuts editor", "برای هر کار میان‌برِ دلخواه بگذارید (فقط در همین مرورگر ذخیره می‌شود).", (a) => a.openPanel("shortcuts"), { words: ["keyboard", "shortcuts", "keys", "میانبر", "کلید"] }),
  F("win.workspace-edit", "window", "چینش", "چینشِ کار: تدوین", "Workspace: editing", "پنلِ قطعه، تایم‌لاین و رسانه‌ها؛ اسکوپ‌ها بسته.", (a) => a.op.workspace("edit"), { words: ["workspace", "layout", "editing", "چینش", "تدوین"] }),
  F("win.workspace-color", "window", "چینش", "چینشِ کار: رنگ", "Workspace: color", "پنلِ رنگ و اسکوپ‌ها باز.", (a) => a.op.workspace("color"), { words: ["workspace", "color", "چینش", "رنگ‌دهی"] }),
  F("win.workspace-audio", "window", "چینش", "چینشِ کار: صدا", "Workspace: audio", "پنلِ صدا و خطِ بلندی روی قطعه‌ها.", (a) => a.op.workspace("audio"), { words: ["workspace", "audio", "mixing", "چینش", "میکس"] }),
  F("win.workspace-graphics", "window", "چینش", "چینشِ کار: گرافیک و زیرنویس", "Workspace: graphics", "پنلِ متن و حاشیهٔ امن.", (a) => a.op.workspace("graphics"), { words: ["workspace", "titles", "چینش", "گرافیک"] }),
  F("win.workspace-export", "window", "چینش", "چینشِ کار: خروجی", "Workspace: export", "پنلِ خروجی و صفِ رندر.", (a) => a.op.workspace("export"), { words: ["workspace", "export", "چینش", "خروجی"] }),
  // ───────────────────────────── راهنما
  F("help.search", "help", "راهنما", "جستجوی ابزار", "Command search", "هر ابزار را با نامِ فارسی، انگلیسی یا مترادف پیدا و اجرا کنید.", (a) => a.openSearch(), { keys: "Ctrl+K", inInputs: true, words: ["search", "find", "command palette", "پیدا کردن", "جستجو", "ابزار"] }),
  F("help.shortcuts", "help", "راهنما", "راهنمای میان‌برها", "Shortcut cheat sheet", "فهرستِ میان‌برهای کیبورد.", (a) => a.click("open-shortcuts"), { keys: "?", legacy: true, words: ["help", "keys", "cheat sheet", "میانبر", "راهنما"] }),
  F("help.director", "help", "راهنما", "کارگردان (ساختِ خودکارِ ویدیو از روی دستور)", "Director (semi-automatic)", "به حالتِ نیمه‌خودکار می‌روید تا با یک دستور ویدیو ساخته شود و نتیجه همین‌جا قابل‌ویرایش بماند.", (a) => a.goDirector?.(), { when: (a) => (a.goDirector ? null : "از این صفحه در دسترس نیست"), words: ["director", "ai", "auto", "نیمه خودکار", "هوش مصنوعی", "دستور"] }),
  F("help.reset-keys", "help", "راهنما", "بازگرداندنِ میان‌برها به پیش‌فرض", "Reset shortcuts", "همهٔ تغییرهای میان‌برِ شما را پاک می‌کند.", (a) => a.openPanel("shortcuts", { reset: true }), { words: ["reset", "default", "پیش فرض"] }),
];

function needClipsForSound(a: Parameters<NonNullable<FeatureDef["when"]>>[0]): string | null {
  return a.hasClips ? null : "اول ویدیو یا صدایی روی تایم‌لاین بگذارید";
}
