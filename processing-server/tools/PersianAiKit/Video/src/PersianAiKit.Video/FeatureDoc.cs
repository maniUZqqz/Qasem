using System.Globalization;
using System.Text;

namespace PersianAiKit.Video;

/// <summary>
/// ساختنِ FEATURES.md از روی <see cref="ToolCatalog"/> و <see cref="Presets"/> (همان منبعِ صفحه و هوشِ مصنوعی)
/// + جدولِ پوششِ ۴۷ قابلیتِ «ارتقای کیفیت»ِ پریمیر از research/Premiere_Features_FA.xlsx. اجرا: Run-SelfTest.bat --write-docs
/// </summary>
public static class FeatureDoc
{
    // ردیف در اکسل، نام، وضعیت (✓ ساخته شده، ◐ بخشی، ⏳ برنامه، ✗ نه)، این‌جا چطور
    private static readonly (int Row, string Name, string Status, string How)[] Coverage =
    {
        (77, "Optical Flow", "◐", "time.smooth (minterpolate با جبرانِ حرکت) برای آهسته‌نمایی — سنگین؛ فقط سرعتِ کمتر از ۱"),
        (102, "Warp Stabilizer (Analysis)", "✓", "stabilize: پاسِ اول vidstabdetect (ردیابیِ نقاط)"),
        (103, "Warp Stabilizer (Method & Framing)", "◐", "vidstabtransform با نرمیِ مسیر و بزرگ‌نماییِ خودکار؛ Subspace Warp و Synthesize Edges نه"),
        (104, "Rolling Shutter Repair", "⏳", "برنامه"),
        (105, "Lens Distortion", "✓", "adjust.distortion (lenscorrection + بزرگ‌نمایی تا گوشه سیاه نشود)"),
        (106, "Reduce Interlace Flicker", "✓", "خودکار: ویدیوی درهم‌رفته با bwdif باز می‌شود"),
        (108, "Input LUT", "✓", "lut: {file, mode: \"input\"} (.cube، پیش از همهٔ رنگ‌ها)"),
        (109, "White Balance (Lumetri)", "✓", "temperature، tint (در فضای خطی)"),
        (110, "Tone (Lumetri)", "✓", "exposure، contrast، highlights، shadows، whites، blacks"),
        (111, "Auto (Lumetri)", "✓", "«خودکار» (رایگان، از روی چند فریمِ نمونه) + «ویرایش با هوشِ مصنوعی»"),
        (115, "Sharpen (Lumetri)", "✓", "sharpen (شارپِ تطبیقیِ CAS)"),
        (118, "RGB Curves", "✓", "curve.rgb و هر کانال"),
        (121, "Color Match", "⏳", "برنامه (هم‌رنگ کردنِ دو کلیپ از آماره‌های رنگ)"),
        (127, "Color Management", "◐", "HDR (PQ/HLG) خودکار به SDRِ bt709 با تُن‌مپینگ؛ مدیریتِ کاملِ فضای رنگ نه"),
        (139, "Levels (effect)", "✓", "levelsBlack، levelsWhite، levelsGamma"),
        (142, "Brightness & Contrast", "✓", "brightness، contrast"),
        (146, "Video Limiter", "✓", "output.broadcastSafe (روشنایی ۱۶–۲۳۵، رنگ ۱۶–۲۴۰)"),
        (151, "Gamma Correction", "✓", "levelsGamma، brightness"),
        (157, "Sharpen (effect)", "✓", "sharpen"),
        (158, "Unsharp Mask (effect)", "✓", "clarity (ماسکِ غیرشارپ با شعاعِ بزرگ)"),
        (242, "Audio Gain & Normalize", "✓", "volume، audio.normalize"),
        (253, "Loudness Meter", "✓", "سنجش: بلندیِ یکپارچه (LUFS)، محدودهٔ بلندی، قلهٔ واقعی (BS.1770)"),
        (254, "Auto-Match Loudness", "✓", "audio.normalize (دو پاس، خطی)"),
        (258, "Enhance Speech", "◐", "پریستِ «پاک‌سازیِ گفتار» (DSP)؛ مدلِ عصبی (arnndn) در برنامه"),
        (259, "Reduce Noise", "✓", "noise (afftdn، تطبیقی)"),
        (260, "Reduce Rumble", "✓", "rumble (بالاگذر)"),
        (261, "DeHum", "✓", "audio.hum = ۵۰ یا ۶۰ (فیلترِ شکافی روی پایه و سه هماهنگ) + تشخیصِ خودکار"),
        (262, "DeEss", "✓", "deess"),
        (263, "Reduce Reverb", "✗", "فیلترِ خوبی در FFmpeg نیست؛ مدلِ عصبی لازم است"),
        (264, "Clarity: Dynamics & EQ", "✓", "compress + presence"),
        (271, "Dynamics", "✓", "compress"),
        (273, "Single-band Compressor", "✓", "compress (acompressor)"),
        (274, "Multiband Compressor", "⏳", "برنامه"),
        (276, "Hard Limiter", "✓", "خودکار بعد از بلند کردنِ صدا (alimiter) و قلهٔ ‎−۱٫۵ dBTP در هم‌سطح‌سازی"),
        (277, "DeEsser (effect)", "✓", "deess"),
        (280, "Parametric Equalizer", "◐", "سه باند: bass، presence، air"),
        (283, "Notch Filter", "✓", "audio.hum"),
        (287, "DeNoise", "✓", "noise"),
        (288, "Adaptive Noise Reduction", "✓", "noise (نویز را در طولِ زمان دنبال می‌کند)"),
        (289, "Automatic Click Remover", "✓", "declick"),
        (290, "DeHummer", "✓", "audio.hum"),
        (291, "DeReverb", "✗", "مثلِ ۲۶۳"),
        (295, "Mastering", "◐", "پریستِ «موسیقی»: هم‌سطح‌سازی + لیمیتر"),
        (296, "Vocal Enhancer", "✓", "presence + پریستِ «پاک‌سازیِ گفتار»"),
        (351, "Maximum Render Quality & Maximum Depth", "✓", "تغییرِ اندازه با lanczos، رنگ با LUTِ ۳۳ و درون‌یابیِ چهاروجهی"),
        (353, "Loudness Normalization (Export)", "✓", "audio.normalize با قلهٔ واقعیِ ‎−۱٫۵"),
        (367, "Dialogue Cleanup Chain", "✓", "پریستِ «پاک‌سازیِ گفتار»: غرش ⇐ نویز ⇐ سین ⇐ اکولایزر ⇐ کمپرسور ⇐ بلندی"),
    };

    public static string Build()
    {
        var ci = CultureInfo.InvariantCulture;
        var sb = new StringBuilder();
        sb.AppendLine("# ابزارهای ویرایشگرِ ویدیو");
        sb.AppendLine();
        sb.AppendLine("> این فایل از روی کد ساخته می‌شود (`Run-SelfTest.bat --write-docs`) — دستی ویرایش نکنید. همان فهرست منبعِ لغزنده‌های صفحهٔ وب و ابزارهای هوشِ مصنوعی (`GET /api/tools`) است.");
        sb.AppendLine();
        sb.AppendLine("همهٔ این‌ها در **«نسخهٔ ویرایش» (recipe)** جمع می‌شوند؛ فایلِ اصلی دست نمی‌خورد. رنگ و نور همان ریاضیِ ویرایشگرِ عکس است و در یک LUTِ سه‌بعدی خلاصه می‌شود (مثلِ لومتری).");
        sb.AppendLine();
        sb.AppendLine("ترتیبِ تصویر: درهم‌رفتگی ⇐ HDR به SDR ⇐ تثبیت ⇐ حذفِ بازه‌ها ⇐ سرعت ⇐ لنز ⇐ چرخش، برش، قرینه ⇐ نویزگیری ⇐ LUTِ رنگ ⇐ وضوح ⇐ شارپ ⇐ وینیت، دانه ⇐ قاب ⇐ اندازه ⇐ محدودهٔ پخش ⇐ محو.");
        sb.AppendLine();
        sb.AppendLine("ترتیبِ صدا: حذفِ بازه‌ها ⇐ سرعت ⇐ غرش ⇐ وزوزِ برق ⇐ کلیک ⇐ نویز ⇐ سین ⇐ اکولایزر ⇐ کمپرسور ⇐ بلندی ⇐ هم‌سطح‌سازی ⇐ محو.");
        sb.AppendLine();
        sb.AppendLine("## ۱. لغزنده‌ها (`recipe.adjust`)");
        foreach (var g in ToolCatalog.Groups)
        {
            sb.AppendLine();
            sb.AppendLine($"### {g.Title}");
            sb.AppendLine(g.Help);
            sb.AppendLine();
            sb.AppendLine("| کلید | نام | بازه | پیش‌فرض | معادلِ پریمیر | کارش |");
            sb.AppendLine("|---|---|---|---|---|---|");
            foreach (var p in ToolCatalog.Params.Where(p => p.Group == g.Key))
                sb.AppendLine($"| `{p.Key}` | {p.Title} | {p.Min.ToString(ci)} تا {p.Max.ToString(ci)}{(p.Unit.Length > 0 ? " " + p.Unit : "")} | {p.Default.ToString(ci)} | {p.Premiere} | {p.Help} |");
        }
        sb.AppendLine();
        sb.AppendLine("## ۲. بخش‌های دیگرِ نسخه");
        sb.AppendLine();
        sb.AppendLine("| بخش | در recipe | کارش |");
        sb.AppendLine("|---|---|---|");
        sb.AppendLine("| بُرشِ سر و ته | `trim`: `start`، `end` (ثانیه) | In/Out |");
        sb.AppendLine("| حذفِ بازه‌ها | `cuts`: `[{start,end}]` | Lift/Extract، Ripple Delete؛ «یافتنِ مکث‌ها» پیشنهادش را می‌سازد (مثلِ تشخیصِ مکث در تدوینِ متن‌محور) |");
        sb.AppendLine("| سرعت و محو | `time`: `speed` (۰٫۲۵ تا ۴)، `smooth` (جریانِ نوری)، `fadeIn`، `fadeOut` | Speed/Duration، Optical Flow، Dip to Black |");
        sb.AppendLine("| منحنی | `curve.rgb`، `curve.red/green/blue`: نقاطِ `[ورودی، خروجی]` | RGB Curves |");
        sb.AppendLine("| LUT | `lut`: `file` (.cubeِ بارگذاری‌شده)، `mode` (`input`/`look`)، `amount` | Input LUT، Look |");
        sb.AppendLine("| برش و صاف کردن | `crop`: `x,y,w,h` (۰ تا ۱)، `angle` (±۴۵°)، `flipH`، `flipV` | Crop، Transform، Flip |");
        sb.AppendLine("| قابِ خروجی | `frame`: `aspect` (`9:16`، `1:1`، `4:5`، `16:9`)، `fit` (`crop`/`blur`/`black`)، `focusX`، `focusY` | Auto Reframe (دستی)، زمینهٔ محو برای ریلز |");
        sb.AppendLine("| تثبیت | `stabilize`: `amount` (۰ تا ۱۰۰) | Warp Stabilizer |");
        sb.AppendLine("| صدا | `audio`: `normalize` (LUFS)، `hum` (۵۰/۶۰)، `mute` | Loudness Normalization، DeHum، Mute |");
        sb.AppendLine("| خروجی | `output`: `format` (mp4/webm/gif/mp3/wav)، `codec` (h264/h265)، `size` (ضلعِ کوچک)، `fps`، `quality`، `broadcastSafe` | Export Settings، Video Limiter |");
        sb.AppendLine();
        sb.AppendLine("## ۳. پریست‌ها");
        sb.AppendLine();
        sb.AppendLine("در صفحه زبانهٔ «پریست»؛ در API کلیدِ `preset` در نسخه (اول پریست، بعد بقیهٔ نسخه روی آن).");
        sb.AppendLine();
        sb.AppendLine("| کلید | نام | نوع | کارش | نسخه |");
        sb.AppendLine("|---|---|---|---|---|");
        foreach (var p in Presets.All) sb.AppendLine($"| `{p.Key}` | {p.Title} | {p.Kind} | {p.Help} | `{p.Recipe.ToJson()}` |");
        sb.AppendLine();
        sb.AppendLine("## ۴. پوششِ ۴۷ قابلیتِ «ارتقای کیفیت»ِ پریمیر");
        sb.AppendLine();
        sb.AppendLine("از `research/Premiere_Features_FA.xlsx` (ستونِ «ارتقای کیفیت»). ✓ ساخته شده · ◐ بخشی · ⏳ در برنامه · ✗ نه.");
        sb.AppendLine();
        sb.AppendLine("| ردیف | قابلیت | وضعیت | این‌جا |");
        sb.AppendLine("|---|---|---|---|");
        foreach (var c in Coverage) sb.AppendLine($"| {c.Row} | {c.Name} | {c.Status} | {c.How} |");
        int done = Coverage.Count(c => c.Status == "✓"), part = Coverage.Count(c => c.Status == "◐"),
            plan = Coverage.Count(c => c.Status == "⏳"), no = Coverage.Count(c => c.Status == "✗");
        sb.AppendLine();
        sb.AppendLine($"جمع: **{done} ساخته شده، {part} بخشی، {plan} در برنامه، {no} نه** (از {Coverage.Length}).");
        return sb.ToString();
    }
}
