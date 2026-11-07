import { clipEnd, srcTimeAt, updateTrack } from "../manual/model";
import { closeGapAt, cuesOf, idsBefore } from "../manual/r4ops";
import { F } from "./core-edit";
import { MediaClip } from "../manual/model";
import { FeatureDef, needClip, needClips, needMedia, needVideo } from "./types";

const hasSound = (a: Parameters<NonNullable<FeatureDef["when"]>>[0]): string | null =>
  needMedia(a) ?? ((a.selected!.clip as MediaClip).kind === "image" ? "عکس صدا ندارد" : null);

/** دورِ چهارم: مانیتورِ منبع، درج/رویه‌گذاری، بستنِ فاصله، انتخابِ به عقب، چسباندنِ درج، ترکِ هدف، زمان، SRT، نشانگرها */
export const EDIT_FEATURES: FeatureDef[] = [
  // ───────────── مانیتورِ منبع
  F("win.source", "window", "پنل‌ها", "مانیتورِ منبع (دیدنِ رسانه، ورودی/خروجی، درج و رویه‌گذاری)", "Source monitor",
    "یک رسانه را پیش از گذاشتن ببینید، بازه‌اش را با I و O انتخاب کنید و «درج» یا «رویه‌گذاری» بزنید.",
    (a) => a.openPanel("source"), { keys: "Shift+2", words: ["source", "source monitor", "insert", "overwrite", "three point", "in out", "منبع", "درج", "رویه گذاری", "سه نقطه", "ورودی", "خروجی"] }),
  F("edit.source-selected", "edit", "درج و رویه‌گذاری", "باز کردنِ رسانهٔ قطعهٔ انتخاب‌شده در مانیتورِ منبع", "Open selection in source monitor",
    "رسانهٔ همین قطعه را در مانیتورِ منبع باز می‌کند تا بازهٔ دیگری از آن را بردارید.",
    (a) => { const c = a.selected?.clip; if (c && c.type === "media") a.openPanel("source", { ref: c.ref, at: Math.max(0, Math.min(c.end, srcTimeAt(c, Math.max(c.at, Math.min(clipEnd(c), a.time))))) }); }, { when: needMedia, words: ["match frame", "reveal", "source", "منبع", "بازکردن", "همان فریم"] }),
  F("clip.replace-footage", "clip", "ساختار", "جایگزینیِ فیلمِ قطعه با رسانهٔ دیگر (Replace footage)", "Replace footage",
    "رسانهٔ همین قطعه را با یکی دیگر از همان نوع عوض می‌کند؛ جا، رنگ، افکت، حرکت و گذار می‌ماند.",
    (a) => a.openPanel("replace"), { when: needMedia, words: ["replace", "relink", "swap footage", "replace clip", "جایگزین", "عوض کردن فیلم", "تعویض", "فیلم دیگر"] }),
  F("edit.fit-to-fill", "edit", "درج و رویه‌گذاری", "پر کردنِ بازه با تغییرِ سرعت (Fit to fill)", "Fit to fill",
    "ورودی/خروجی را روی منبع و روی تایم‌لاین بگذارید؛ سرعتِ منبع طوری عوض می‌شود که دقیقاً همان بازه را پر کند.",
    (a) => a.openPanel("source"), { words: ["fit to fill", "four point", "4 point", "چهار نقطه", "پر کردن بازه", "هم اندازه"] }),
  F("edit.insert", "edit", "درج و رویه‌گذاری", "درج (Insert) از مانیتورِ منبع", "Insert edit",
    "مانیتورِ منبع را باز می‌کند؛ با «درج» رسانه در سرِ پخش می‌نشیند و همهٔ ترک‌ها جلو می‌روند.",
    (a) => a.openPanel("source"), { words: ["insert", "درج", "ویرایش سه نقطه", "three-point"] }),
  F("edit.overwrite", "edit", "درج و رویه‌گذاری", "رویه‌گذاری (Overwrite) از مانیتورِ منبع", "Overwrite edit",
    "مانیتورِ منبع را باز می‌کند؛ با «رویه‌گذاری» رسانه روی همان بازه می‌نشیند و چیزی جابه‌جا نمی‌شود.",
    (a) => a.openPanel("source"), { words: ["overwrite", "رویه گذاری", "روی نویسی", "جایگزین"] }),
  F("edit.paste-insert", "edit", "کلیپ‌بورد", "چسباندنِ درج (بعدی‌ها جلو بروند)", "Paste insert",
    "قطعه‌های کپی‌شده را در سرِ پخش می‌گذارد و همهٔ بعدی‌ها را به اندازهٔ آن جلو می‌برد.",
    (a) => a.op.pasteInsert(), { words: ["paste insert", "درج چسباندن", "چسباندن و جلو بردن"] }),
  // ───────────── فاصله و انتخاب
  F("edit.close-gap", "edit", "برش", "بستنِ فاصلهٔ خالیِ سرِ پخش", "Close gap",
    "اگر سرِ پخش در یک فاصلهٔ خالی است، همهٔ ترک‌های بعد از آن به اندازهٔ فاصله به عقب می‌آیند.",
    (a) => { const r = closeGapAt(a.project, a.time); if (r.closed) a.apply("بستنِ فاصله", () => r.project); else a.notice(r.reason ?? "این‌جا فاصله‌ای نیست."); },
    { when: (a) => (a.hasClips ? (closeGapAt(a.project, a.time).closed ? null : closeGapAt(a.project, a.time).reason ?? "این‌جا فاصله‌ای نیست.") : "پروژه هنوز قطعه‌ای ندارد"), words: ["close gap", "ripple delete gap", "فاصله", "خالی", "بستن فاصله"] }),
  F("edit.select-backward", "edit", "انتخاب", "انتخابِ همه از این نقطه به عقب", "Track select backward",
    "همهٔ قطعه‌هایی که پیش از سرِ پخش شروع شده‌اند را انتخاب می‌کند.",
    (a) => a.select(idsBefore(a.project, a.time)), { keys: "Shift+A", when: needClips, words: ["select backward", "track select backward", "عقب", "قبل"] }),
  // ───────────── ترکِ هدف
  F("seq.target-track", "sequence", "ترک‌ها", "هدف‌کردنِ ترکِ قطعهٔ انتخاب‌شده (◎)", "Target track",
    "درج و رویه‌گذاری از مانیتورِ منبع روی این ترک می‌نشینند. (دکمهٔ ◎ در سرِ هر ترک هم همین را می‌کند.)",
    (a) => { const tr = a.selected!.track; a.apply(tr.target ? "برداشتنِ هدف" : "هدف‌کردنِ ترک", (p) => updateTrack(p, tr.id, { target: !tr.target })); },
    { when: needClip, on: (a) => !!a.selected?.track.target, words: ["target", "track targeting", "source patching", "هدف", "ترک هدف"] }),
  F("seq.target-clear", "sequence", "ترک‌ها", "برداشتنِ هدف از همهٔ ترک‌ها", "Clear track targets",
    "دوباره درج و رویه‌گذاری روی اولین ترکِ بازِ هر نوع می‌نشینند.",
    (a) => a.apply("برداشتنِ هدف‌ها", (p) => ({ ...p, tracks: p.tracks.map((t) => (t.target ? { ...t, target: false } : t)) })),
    { when: (a) => (a.project.tracks.some((t) => t.target) ? null : "ترکی هدف نشده است"), words: ["clear targets", "هدف"] }),
  // ───────────── زمان و پخش
  F("seq.goto-time", "sequence", "حرکت", "رفتن به زمانِ دقیق…", "Go to time",
    "زمان را بنویسید (۱:۲۳ یا ۸۳ ثانیه) و سرِ پخش همان‌جا برود.",
    (a) => a.openPanel("goto"), { keys: "G", words: ["go to", "timecode", "jump to time", "زمان", "تایم کد", "پریدن", "برو به"] }),
  F("seq.loop", "sequence", "حرکت", "پخشِ تکراری (Loop)", "Loop playback",
    "وقتی پخش به آخر (یا خروجی) رسید دوباره از اول (یا ورودی) شروع می‌شود.",
    (a) => a.toggle("loop"), { on: (a) => a.flags.loop, words: ["loop", "repeat", "تکرار", "حلقه"] }),
  // ───────────── صدای پیشرفته
  F("audio.eq-param", "audio", "قطعه", "EQ پارامتریک (فرکانس، بهره، Q)", "Parametric EQ",
    "تا پنج باند: هر باند یک فرکانس را بالا یا پایین می‌برد؛ مثلاً حذفِ «تو دماغی» یا روشن‌کردنِ صدا.",
    (a) => a.reveal("audio", "ap-adv"), { when: hasSound, words: ["parametric eq", "equalizer", "bands", "frequency", "q", "ایکوالایزر", "اکولایزر", "ای کیو", "ایکیو", "پارامتریک", "باند", "فرکانس", "بم و زیر"] }),
  F("audio.compressor-detail", "audio", "قطعه", "کمپرسورِ دقیق (آستانه، نسبت، حمله، رهایی)", "Compressor",
    "دامنهٔ صدا را فشرده می‌کند تا بلندترین‌ها و کم‌صداترین‌ها به هم نزدیک شوند؛ جبرانِ بلندی هم دارد.",
    (a) => a.reveal("audio", "ap-adv"), { when: hasSound, words: ["compressor", "threshold", "ratio", "attack", "release", "makeup", "limiter", "کمپرسور", "آستانه", "نسبت", "فشرده"] }),
  F("audio.pitch", "audio", "قطعه", "زیر و بمی (Pitch shift)", "Pitch shift",
    "صدا را نیم‌پرده‌نیم‌پرده زیرتر یا بم‌تر می‌کند بدونِ این‌که تندتر یا کندتر شود.",
    (a) => a.reveal("audio", "ap-adv"), { when: hasSound, words: ["pitch", "pitch shift", "voice change", "زیر و بمی", "زیرتر", "بم تر", "نیم پرده", "تغییر صدا"] }),
  F("audio.echo", "audio", "قطعه", "پژواک (Echo)", "Echo / delay",
    "صدا را با فاصلهٔ دلخواه و شدتِ دلخواه تکرار می‌کند.",
    (a) => a.reveal("audio", "ap-adv"), { when: hasSound, words: ["echo", "delay", "reverb", "پژواک", "اکو", "تکرار صدا", "ریورب"] }),
  // ───────────── خروجی‌های دیگر
  F("file.export-gif", "file", "خروجی", "خروجیِ GIF (از بازهٔ ورودی–خروجی یا ابتدای پروژه)", "Export GIF",
    "تصویرِ متحرکِ بی‌صدا تا ۲۰ ثانیه می‌سازد (از بازهٔ I تا O اگر گذاشته باشید).",
    (a) => a.op.renderAs("gif"), { when: needClips, words: ["gif", "animated", "loop image", "جیف", "گیف", "تصویر متحرک"] }),
  F("file.export-frame", "file", "خروجی", "ذخیرهٔ فریمِ سرِ پخش به‌صورتِ عکس (JPG)", "Export frame",
    "فریمِ همین لحظه را با همهٔ افکت‌ها و عنوان‌ها به‌صورتِ عکس می‌سازد (مثلاً برای کاورِ ویدیو).",
    (a) => a.op.renderAs("frame"), { when: needClips, words: ["export frame", "still", "screenshot", "cover", "thumbnail", "عکس", "کاور", "اسکرین شات", "فریم"] }),
  F("file.export-audio", "file", "خروجی", "خروجیِ فقط صدا (M4A)", "Export audio only",
    "صدای میکس‌شده را بدونِ تصویر می‌سازد؛ مثلاً برای پادکست یا آهنگِ پس‌زمینه.",
    (a) => a.op.renderAs("audio"), { when: needClips, words: ["audio only", "m4a", "mp3", "podcast", "sound only", "فقط صدا", "صدا", "پادکست"] }),
  F("file.export-range", "file", "خروجی", "خروجیِ فقط بازهٔ ورودی–خروجی", "Export in–out range",
    "فقط بخشِ بینِ I و O را به‌صورتِ ویدیو می‌سازد، نه کلِ پروژه را.",
    (a) => a.op.renderAs("range"), { when: (a) => (a.project.inout ? null : "اول روی تایم‌لاین ورودی و خروجی بگذارید (I و O)"), words: ["export range", "work area", "in out", "بازه", "ورودی خروجی", "بخشی از ویدیو"] }),
  // ───────────── تشخیصِ برش
  F("clip.scene-detect", "clip", "ساختار", "تشخیصِ برش‌ها و تقسیمِ خودکارِ فیلم", "Scene edit detection",
    "جاهایی را که فیلم نما عوض می‌کند پیدا می‌کند و قطعه را همان‌جا می‌برد. (کم‌حساس‌تر یا پرحساس‌تر هم می‌شود.)",
    (a) => a.op.detectScenes("normal"), { when: needVideo, words: ["scene detection", "scene edit detection", "detect cuts", "auto split", "shots", "برش ها", "تشخیص برش", "تغییر نما", "تقسیم خودکار", "صحنه"] }),
  F("clip.scene-detect-high", "clip", "ساختار", "تشخیصِ برش‌ها — پرحساس (برش‌های نرم هم)", "Scene detection (sensitive)",
    "مثلِ بالا، ولی برش‌های نرم و محو‌شونده را هم پیدا می‌کند؛ ممکن است چند برشِ اضافه بخورد (با برگشت پاک می‌شود).",
    (a) => a.op.detectScenes("high"), { when: needVideo, words: ["scene detection", "sensitive", "پرحساس", "برش نرم"] }),
  F("clip.scene-detect-low", "clip", "ساختار", "تشخیصِ برش‌ها — کم‌حساس (فقط برش‌های واضح)", "Scene detection (strict)",
    "فقط تغییرِ نماهای کاملاً واضح را می‌برد.",
    (a) => a.op.detectScenes("low"), { when: needVideo, words: ["scene detection", "strict", "کم حساس", "برش واضح"] }),
  // ───────────── کلیدفریم
  F("clip.keyframe-graph", "clip", "حرکت و ترکیب", "گرافِ کلیدفریم (دیدن و کشیدنِ منحنی)", "Keyframe graph",
    "منحنیِ جا، اندازه، چرخش، شفافیت، بلندی یا برشِ قطعه را ببینید؛ نقطه‌ها را بکشید و نوعِ شیبِ هر کلید را عوض کنید.",
    (a) => a.openPanel("graph"), { when: needMedia, words: ["graph editor", "value graph", "keyframes", "bezier", "ease", "کلیدفریم", "گراف", "منحنی", "نمودار", "انیمیشن", "شیب", "کپی کلید", "چسباندن کلید"] }),
  // ───────────── نشانگرها
  F("marker.panel", "marker", "نشانگر", "پنلِ نشانگرها (نام، رنگ، پرش)", "Markers panel",
    "همهٔ نشانگرها در یک فهرست؛ نام و رنگ و نوع را عوض کنید، روی زمان بزنید تا بپرید.",
    (a) => a.openPanel("markers"), { words: ["markers", "marker list", "نشانگرها", "فهرست نشانگر", "رنگ نشانگر", "نام نشانگر", "comments"] }),
  // ───────────── زیرنویس SRT و پروژه
  F("gfx.srt-import-file", "graphics", "زیرنویس", "آوردنِ فایلِ زیرنویس (SRT)", "Import SRT file",
    "یک فایلِ .srt را انتخاب کنید؛ هر خط به‌صورتِ متن روی ترکِ «زیرنویس» و در زمانِ خودش می‌نشیند.",
    (a) => a.op.importSrt(), { words: ["srt", "subtitle file", "import captions", "زیرنویس", "فایل زیرنویس", "وارد کردن"] }),
  F("gfx.srt-export", "graphics", "زیرنویس", "ذخیرهٔ زیرنویس‌ها به‌صورتِ فایلِ SRT", "Export SRT",
    "همهٔ زیرنویس‌های روی تایم‌لاین را در یک فایلِ .srt (UTF-8) می‌ریزد تا در یوتیوب، تلگرام و پخش‌کننده‌ها بگذارید.",
    (a) => a.op.exportSrt(), { when: (a) => (cuesOf(a.project).length ? null : "زیرنویسی روی تایم‌لاین نیست"), words: ["srt", "export captions", "subtitle", "خروجی زیرنویس", "ذخیره زیرنویس", "دانلود زیرنویس"] }),
  F("file.duplicate-project", "file", "پروژه", "نسخهٔ دومِ پروژه (Save as)", "Duplicate project",
    "یک کپیِ کاملِ پروژه می‌سازد و باز می‌کند؛ پروژهٔ اصلی همان‌طور می‌ماند.",
    (a) => a.op.duplicateProject(), { when: needClips, words: ["duplicate project", "save as", "copy project", "کپی پروژه", "نسخه دوم", "ذخیره به نام"] }),
];
