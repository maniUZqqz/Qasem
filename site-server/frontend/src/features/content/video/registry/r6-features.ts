import { pictureEnd, retimeToLength, setFrames, setTextMotion, stepTrackSize, setAllTrackSizes } from "../manual/r6ops";
import { F } from "./core-edit";
import { FeatureDef, needClips, needText, needVisual } from "./types";

type When = NonNullable<FeatureDef["when"]>;
const needTrack: When = (a) => (a.selected ? null : "اول یک قطعه را روی تایم‌لاین انتخاب کنید (ترکِ آن کار می‌کند)");
const needAudioClip: When = (a) => (a.selected && a.selected.clip.type === "media" && (a.selected.clip.kind === "audio" || a.selected.track.kind === "audio") ? null : "اول یک قطعهٔ صدا یا موسیقی را انتخاب کنید");
const hasSound: When = (a) => (a.selected && a.selected.clip.type === "media" && a.selected.clip.kind !== "image" ? null : "اول یک ویدیو یا صدا را روی تایم‌لاین انتخاب کنید");
const needVideoClip: When = (a) => (a.selected && a.selected.clip.type === "media" && a.selected.clip.kind === "video" ? null : "اول یک ویدیو را روی تایم‌لاین انتخاب کنید");

/** دورِ ششم: کاملِ هم‌ترازی — رسانه، تفسیر، نویزگیر، فریم، گذارِ پیش‌فرض، ترک، متن، صدا، ProRes */
export const R6_FEATURES: FeatureDef[] = [
  // ───────────── پرونده
  F("file.collect", "file", "پروژه", "جمع‌کردنِ فایل‌های پروژه (Collect / Consolidate)", "Collect project files",
    "پروژه و همهٔ فایل‌های اصلیِ آن را در یک بستهٔ zip برایتان می‌سازد تا نگه دارید یا جابه‌جا کنید (فایل‌های فروشگاهِ دیگر هرگز برداشته نمی‌شود).",
    (a) => a.op.collect(), { when: needClips, words: ["collect", "consolidate", "archive", "zip", "package", "backup", "جمع کردن", "فایل های پروژه", "بسته", "آرشیو", "پشتیبان"] }),
  F("file.media-meta", "file", "آوردن", "برچسب و یادداشتِ رسانه‌ها", "Media labels and notes",
    "به هر رسانه چند برچسب (مثلاً «محصول، بیرونی») و یک یادداشت می‌دهید؛ جستجو در «رسانه‌ها» هر دو را می‌بیند.",
    (a) => a.openPanel("mediameta"), { words: ["label", "tag", "note", "comment", "metadata", "keyword", "برچسب", "یادداشت", "توضیح", "کلمه کلیدی", "دسته بندی"] }),
  F("file.export-prores", "file", "خروجی", "خروجیِ ProRes 422 (فایلِ مادر .mov)", "Export ProRes 422",
    "خروجی را با کدکِ ProRes 422 HQ و صدای بی‌فشرده می‌سازد؛ برای تدوین یا رنگ‌بندیِ بعدی در نرم‌افزارهای دیگر. حجمش حدودِ ۱۰ برابرِ H.264 است.",
    (a) => { a.applyRoot("خروجی ProRes", (p) => ({ ...p, export: { ...(p.export ?? {}), codec: "prores" } })); a.reveal("out", "xp-manual"); }, { when: needClips, words: ["prores", "mov", "master", "mezzanine", "پرورز", "فایل مادر", "مادر"] }),
  F("file.export-prores-alpha", "file", "خروجی", "خروجیِ ProRes 4444 با پس‌زمینهٔ شفاف (آلفا)", "Export ProRes 4444 with alpha",
    "خروجی با کانالِ آلفا: هر جای قاب که چیزی نگذاشته‌اید شفاف می‌ماند (برای لوگوی متحرک، عنوان‌ها و روکش‌ها روی ویدیوی دیگر). فایل .mov است.",
    (a) => { a.applyRoot("خروجی ProRes با آلفا", (p) => ({ ...p, export: { ...(p.export ?? {}), codec: "prores4444" } })); a.reveal("out", "xp-manual"); }, { when: needClips, words: ["prores 4444", "alpha", "transparent", "transparency", "آلفا", "شفاف", "پس زمینه شفاف", "کانال آلفا"] }),
  // ───────────── کلیپ
  F("clip.interpret-fps", "clip", "زمان", "تفسیرِ فیلم: عوضِ فریم‌بر‌ثانیهٔ منبع", "Interpret footage: frame rate",
    "فیلم را «مثلِ N فریم» بخوانید: مثلاً فیلمِ ۶۰ فریمی مثلِ ۳۰ نیمه‌سرعت می‌شود. با «برگشت» به حالتِ قبل برمی‌گردد.",
    (a) => a.openPanel("clipfx", { section: "interpret" }), { when: needVideoClip, words: ["interpret footage", "frame rate", "fps", "conform", "slow motion", "فریم بر ثانیه", "تفسیر فیلم", "اسلوموشن", "فریم ریت"] }),
  F("clip.deinterlace-par", "clip", "حرکت و ترکیب", "تفسیرِ فیلم: نسبتِ پیکسل و خط‌های درهم (Interlace)", "Interpret footage: pixel aspect, interlace",
    "نسبتِ پیکسل (فیلمِ آنامورفیکِ قدیمی) را درست می‌کند و خط‌های درهمِ فیلم‌های قدیمیِ تلویزیونی را به فریمِ کامل تبدیل می‌کند.",
    (a) => a.openPanel("clipfx", { section: "interpret" }), { when: needVisual, words: ["pixel aspect", "par", "interlace", "deinterlace", "yadif", "anamorphic", "نسبت پیکسل", "خط های درهم", "آنامورفیک", "اینترلیس"] }),
  F("clip.denoise", "clip", "حرکت و ترکیب", "نویزگیرِ تصویر (Video denoise)", "Video denoise",
    "دانه‌دانه‌بودنِ فیلمِ شبانه یا گوشیِ قدیمی را کم می‌کند؛ حالتِ سریع و حالتِ قوی (کندتر) دارد.",
    (a) => a.openPanel("clipfx", { section: "denoise" }), { when: needVisual, words: ["denoise", "noise reduction", "grain", "noisy", "hqdn3d", "nlmeans", "نویز", "نویزگیر", "دانه دانه", "نویز تصویر"] }),
  F("clip.frame-blend", "clip", "زمان", "ترکیبِ فریم‌ها هنگامِ کندکردن (Frame blending)", "Frame blending",
    "برای قطعهٔ کندشده فریم‌های کنارِ هم را قاطی می‌کند تا حرکت «پله‌پله» نباشد.",
    (a) => a.applyRoot("ترکیبِ فریم‌ها", (p) => setFrames(p, a.selected!.clip.id, "blend")), { when: needVisual, words: ["frame blending", "blend frames", "smooth slow motion", "ترکیب فریم", "پله پله", "نرم کردن اسلوموشن"] }),
  F("clip.optical-flow", "clip", "زمان", "اپتیکال‌فلو: فریمِ میانیِ هوشمند برای اسلوموشن (Optical flow)", "Optical flow slow motion",
    "برای قطعهٔ کندشده فریم‌های تازه با حرکتِ درست می‌سازد. در خروجیِ نهایی روی سرورِ پردازش اجرا می‌شود؛ روی سایت فقط وقتی که خروجی را دستی روی سایت بسازید.",
    (a) => a.applyRoot("اپتیکال‌فلو", (p) => setFrames(p, a.selected!.clip.id, "flow")), { when: needVisual, words: ["optical flow", "flow", "minterpolate", "interpolation", "frame interpolation", "اپتیکال فلو", "فریم میانی", "اسلوموشن نرم"] }),
  // ───────────── سکانس
  F("seq.default-transition", "sequence", "گذار", "گذارِ پیش‌فرض برای همهٔ برش‌ها", "Default transition on all cuts",
    "یک نوع و مدتِ گذار می‌گذارید و روی همهٔ برش‌های چسبیدهٔ تصویر (یا فقط ترکِ انتخاب‌شده) می‌نشیند؛ «برشِ مورف» هم در فهرست هست.",
    (a) => a.openPanel("deftrans"), { when: needClips, words: ["default transition", "apply to all cuts", "transition all", "گذار پیش فرض", "همه برش ها", "گذار برای همه", "دیزالو همه"] }),
  F("seq.track-taller", "sequence", "ترک‌ها", "بلندترکردنِ ردیفِ ترک", "Taller track", "ردیفِ ترکِ قطعهٔ انتخاب‌شده را یک پله بلندتر می‌کند (برای دیدنِ موجِ صدا و تصاویرِ ریز).",
    (a) => { const id = a.selected!.track.id; a.applyRoot("بلندترکردنِ ترک", (p) => stepTrackSize(p, id, 1)); }, { when: needTrack, words: ["track height", "taller", "expand track", "بلندی ترک", "بزرگ کردن ترک", "ترک بلند"] }),
  F("seq.track-shorter", "sequence", "ترک‌ها", "کوتاه‌ترکردن / جمع‌کردنِ ردیفِ ترک", "Shorter / collapse track", "ردیفِ ترکِ قطعهٔ انتخاب‌شده را یک پله کوتاه‌تر می‌کند تا جمع شود و جا باز شود.",
    (a) => { const id = a.selected!.track.id; a.applyRoot("کوتاه‌ترکردنِ ترک", (p) => stepTrackSize(p, id, -1)); }, { when: needTrack, words: ["collapse track", "shorter", "minimize track", "جمع کردن ترک", "کوچک کردن ترک", "ترک کوتاه"] }),
  F("seq.tracks-collapse", "sequence", "ترک‌ها", "جمع‌کردنِ همهٔ ترک‌ها", "Collapse all tracks", "همهٔ ردیف‌های تایم‌لاین را کوتاه می‌کند تا کلِ پروژه یک‌جا دیده شود.",
    (a) => a.applyRoot("جمع‌کردنِ همهٔ ترک‌ها", (p) => setAllTrackSizes(p, "c")), { when: needClips, words: ["collapse all", "minimize all tracks", "جمع کردن همه", "همه ترک ها کوچک"] }),
  F("seq.tracks-expand", "sequence", "ترک‌ها", "بازکردنِ همهٔ ترک‌ها (اندازهٔ معمولی)", "Reset track heights", "همهٔ ردیف‌ها به اندازهٔ معمولی برمی‌گردند.",
    (a) => a.applyRoot("اندازهٔ معمولیِ ترک‌ها", (p) => setAllTrackSizes(p, "m")), { when: needClips, words: ["expand all", "reset track height", "بازکردن همه", "اندازه معمولی"] }),
  F("seq.offline-media", "sequence", "ترک‌ها", "رسانه‌های گم‌شده (Offline)", "Offline media",
    "قطعه‌هایی را نشان می‌دهد که فایلشان دیگر در رسانه‌های فروشگاه نیست (قرمزِ هاشورخورده روی تایم‌لاین)؛ از همین‌جا جایگزینشان می‌کنید.",
    (a) => a.openPanel("offline"), { words: ["offline", "missing media", "relink", "missing", "گم شده", "رسانه گم شده", "فایل گم شده", "قرمز"] }),
  // ───────────── ویرایش
  F("edit.replace-edit", "edit", "مانیتورِ منبع", "جایگزینیِ قطعه با بازهٔ منبع (Replace edit)", "Replace edit",
    "قطعهٔ انتخاب‌شده در همان جا و با همان طول، محتوایش از نقطهٔ ورودیِ مانیتورِ منبع می‌شود؛ جلوه‌ها و رنگش می‌ماند.",
    (a) => a.openPanel("source"), { words: ["replace edit", "replace", "swap clip", "جایگزینی قطعه", "جایگزین کردن", "عوض کردن فیلم قطعه"] }),
  // ───────────── صدا
  F("audio.music-retime", "audio", "موسیقی", "هم‌اندازه‌کردنِ موسیقی با ویدیو (Retime)", "Retime music to the video",
    "سرعتِ قطعهٔ موسیقیِ انتخاب‌شده (بدونِ تغییرِ زیر و بم، ۰٫۵ تا ۲ برابر) طوری عوض می‌شود که دقیقاً تا آخرِ تصویر برسد؛ اگر خیلی بلند بود می‌برد و محو می‌دهد.",
    (a) => {
      const r = retimeToLength(a.project, a.selected!.clip.id, pictureEnd(a.project));
      if ("error" in r) { a.notice(r.error); return; }
      a.apply("هم‌اندازه‌کردنِ موسیقی با ویدیو", () => r.project);
      a.notice(r.note || `موسیقی با سرعتِ ${Math.round(r.speed * 100) / 100} برابر هم‌اندازهٔ ویدیو شد (برگشت: Ctrl+Z).`);
    }, { when: needAudioClip, words: ["retime music", "fit music", "stretch music", "music length", "هم اندازه موسیقی", "طول موسیقی", "موسیقی تا آخر ویدیو", "کش دادن موسیقی"] }),
  F("audio.reverb", "audio", "قطعه", "ریورب (بازتابِ اتاق، سالن، حمام، کلیسا)", "Reverb",
    "به صدای قطعه حالتِ اتاق می‌دهد: اتاقِ کوچک، حمام، سالن یا کلیسا، با میزانِ دلخواه.",
    (a) => a.reveal("audio", "ap-adv"), { when: hasSound, words: ["reverb", "room", "hall", "cathedral", "echo room", "ریورب", "اتاق", "سالن", "کلیسا", "حمام", "بازتاب صدا"] }),
  F("audio.dereverb", "audio", "قطعه", "کاهشِ پژواکِ اتاق (Dereverb)", "Dereverb",
    "پژواکِ اتاقِ ضبط را (تقریبی: نویزگیرِ طیفی و گیتِ نرم) کم می‌کند؛ برای ضبطِ پژواک‌دار.",
    (a) => a.reveal("audio", "ap-adv"), { when: hasSound, words: ["dereverb", "remove reverb", "room echo removal", "پژواک اتاق", "حذف پژواک", "کم کردن پژواک", "پژواک گیر"] }),
  // ───────────── گرافیک
  F("gfx.text-credits", "graphics", "متن و عنوان", "متنِ رو‌به‌بالا (تیتراژ / Credits)", "Rolling credits",
    "متنِ چندخطیِ انتخاب‌شده از پایینِ قاب تا بالا می‌رود؛ مدتش خودکار به اندازهٔ خط‌ها دراز می‌شود.",
    (a) => a.applyRoot("تیتراژِ رو‌به‌بالا", (p) => setTextMotion(p, a.selected!.clip.id, "roll-up")), { when: needText, words: ["credits", "roll", "rolling credits", "end credits", "scroll", "تیتراژ", "غلتش", "متن رو به بالا", "اسکرول متن"] }),
  F("gfx.text-crawl", "graphics", "متن و عنوان", "نوارِ خبر / متنِ افقی (Crawl)", "Crawl / ticker",
    "متنِ انتخاب‌شده مثلِ نوارِ خبرِ پایینِ تلویزیون از راست به چپ می‌گذرد.",
    (a) => a.applyRoot("نوارِ خبر", (p) => setTextMotion(p, a.selected!.clip.id, "crawl-left")), { when: needText, words: ["crawl", "ticker", "news ticker", "lower third scroll", "نوار خبر", "متن افقی", "متن متحرک"] }),
  F("gfx.text-path", "graphics", "متن و عنوان", "متن روی مسیر: قوس، موج، غلتش", "Text on a path",
    "کلِ نوشته را روی یک مسیرِ آماده حرکت می‌دهد: قوس، موج، غلتشِ بالا/پایین یا نوار؛ در پیش‌نمایش و خروجی یکی است.",
    (a) => a.openPanel("textmotion"), { when: needText, words: ["text on path", "path", "arc", "wave", "curve", "motion text", "متن روی مسیر", "قوس", "موج", "مسیر متن", "منحنی"] }),
];
