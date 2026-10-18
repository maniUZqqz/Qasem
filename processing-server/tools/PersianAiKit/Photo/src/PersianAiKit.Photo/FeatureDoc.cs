using System.Globalization;
using System.Text;

namespace PersianAiKit.Photo;

/// <summary>
/// ساختنِ FEATURES.md از روی <see cref="ToolCatalog"/> (همان منبعِ صفحه و ابزارهای هوشِ مصنوعی) + جدولِ پوششِ ۶۲ قابلیتِ
/// «ارتقای کیفیت»ِ فتوشاپ از research/Photoshop_Features_FA.xlsx. اجرا: Run-SelfTest.bat --write-docs
/// </summary>
public static class FeatureDoc
{
    // ردیف در اکسل، نام، وضعیت (✓ ساخته شده، ◐ بخشی، ⏳ برنامه، ✗ نه)، این‌جا چطور
    private static readonly (int Row, string Name, string Status, string How)[] Coverage =
    {
        (60, "Brightness/Contrast", "✓", "brightness، contrast"),
        (61, "Levels", "✓", "levelsBlack، levelsWhite، levelsGamma"),
        (62, "Curves", "✓", "curve (rgb و هر کانال)"),
        (63, "Exposure", "✓", "exposure (در فضای خطی)"),
        (64, "Light (لایهٔ جدید)", "✓", "exposure، contrast، highlights، shadows، whites، blacks"),
        (65, "Color and Vibrance", "✓", "temperature، tint، vibrance، saturation"),
        (67, "Color Balance", "◐", "رنگ‌دهیِ سایه و روشنی (shadowsHue/Sat، highlightsHue/Sat)؛ میانه‌ها جدا نه"),
        (77, "Shadows/Highlights", "✓", "highlights، shadows (لبه‌آگاه، فیلترِ هدایت‌شده)"),
        (83, "Auto Tone", "✓", "«خودکار» (رایگان، قاعده‌ای)"),
        (84, "Auto Contrast", "✓", "«خودکار»: whites/blacks تا دو سرِ هیستوگرام"),
        (85, "Auto Color", "✓", "«خودکار»: تعادلِ سفیدی از رنگ‌های خنثی"),
        (86, "Clarity and Dehaze", "✓", "clarity، dehaze"),
        (91, "Camera Raw", "◐", "همان ترتیب و ابزارها؛ فایلِ RAWِ دوربین نه (JPEG، PNG، WebP، TIFF ۸ و ۱۶ بیتی)"),
        (93, "White Balance", "✓", "temperature، tint"),
        (94, "Exposure & Contrast", "✓", "exposure، contrast"),
        (95, "Highlights & Shadows", "✓", "highlights، shadows"),
        (96, "Whites & Blacks", "✓", "whites، blacks"),
        (97, "Texture", "✓", "texture"),
        (98, "Clarity", "✓", "clarity"),
        (99, "Dehaze", "✓", "dehaze (پیشینِ کانالِ تیره)"),
        (100, "Vibrance & Saturation", "✓", "vibrance (با محافظتِ پوست)، saturation"),
        (101, "Tone Curve", "✓", "curve"),
        (105, "Sharpening", "✓", "sharpen، sharpenRadius، sharpenMasking"),
        (106, "Noise Reduction (manual)", "✓", "noiseLuma، noiseColor"),
        (107, "Denoise (AI)", "◐", "noiseLuma با Non-Local Means (بی هوشِ مصنوعی)؛ مدلِ نویزگیری در برنامه"),
        (108, "Raw Details", "✗", "به فایلِ RAW نیاز دارد"),
        (109, "Super Resolution", "✓", "output.upscale ×۲ و ×۴ (Real-ESRGAN)"),
        (110, "Lens Profile Corrections", "◐", "distortion و lensVignette دستی؛ پایگاهِ پروفایلِ لنز نه"),
        (111, "Chromatic Aberration & Defringe", "⏳", "برنامه"),
        (112, "Manual Distortion & Vignetting", "✓", "distortion، lensVignette"),
        (113, "Geometry / Upright", "◐", "چرخش و صاف کردن دستی (crop.angle)؛ آپ‌رایتِ خودکار در برنامه"),
        (128, "Distraction Removal", "◐", "ترمیمِ لکهٔ کوچک (spots)؛ حذفِ چیزِ بزرگ با مدلِ LaMa در برنامه"),
        (131, "Auto (Camera Raw)", "✓", "«خودکار» + «ویرایشِ هوشمند» (هوشِ مصنوعیِ بینا)"),
        (133, "Photo Merge (HDR / Panorama)", "⏳", "برنامه (چند عکس)"),
        (176, "Remove Reflections", "✗", "مدلِ بزرگ لازم است"),
        (231, "Resample: Preserve Details", "✓", "خروجی با Lanczos4"),
        (232, "Preserve Details 2.0", "✓", "output.upscale (Real-ESRGAN)"),
        (247, "Lens Correction Filter", "◐", "مثلِ ۱۱۰ و ۱۱۲"),
        (248, "Adaptive Wide Angle", "⏳", "برنامه"),
        (256, "Auto-Blend: Stack Images (focus)", "⏳", "برنامه (چند عکس)"),
        (257, "Merge to HDR Pro", "⏳", "برنامه (چند عکس)"),
        (259, "Stack Mode: Median", "⏳", "برنامه (چند عکس: حذفِ رهگذر و نویز)"),
        (260, "Stack Mode: Mean", "⏳", "برنامه (چند عکس)"),
        (282, "Sharpen / Sharpen More", "✓", "sharpen"),
        (283, "Sharpen Edges", "✓", "sharpenMasking"),
        (284, "Smart Sharpen", "◐", "ماسکِ غیرشارپ با ماسکِ لبه؛ رفعِ تاریِ حرکت نه"),
        (285, "Unsharp Mask", "✓", "sharpen، sharpenRadius"),
        (286, "AI Sharpen / AI Denoise", "◐", "output.upscale (Real-ESRGAN جزئیات را هم بازسازی می‌کند)"),
        (287, "Shake Reduction", "✗", "در خودِ فتوشاپ هم حذف شده"),
        (289, "Despeckle", "✓", "noiseLuma"),
        (290, "Dust & Scratches", "◐", "spots (ترمیمِ نقطه‌ای)"),
        (291, "Median", "◐", "noiseLuma"),
        (292, "Reduce Noise", "✓", "noiseLuma، noiseColor"),
        (327, "High Pass", "✓", "clarity، texture"),
        (389, "Colorize (Neural)", "✗", "مدلِ رنگی‌کردن لازم است"),
        (390, "Super Zoom", "✓", "output.upscale"),
        (392, "JPEG Artifacts Removal", "◐", "Real-ESRGAN (مدلِ general برای عکسِ فشرده آموزش دیده) + noiseLuma"),
        (393, "Photo Restoration", "⏳", "برنامه"),
        (400, "Enhance Detail", "◐", "texture + output.upscale"),
        (404, "Generative Upscale", "◐", "Real-ESRGAN (نه مولد)"),
        (435, "Bit Depth (8/16/32)", "◐", "ورودیِ ۱۶ بیتی با دقتِ اعشاری پردازش می‌شود؛ خروجی ۸ بیتی"),
        (469, "Color Cast Removal (Average)", "✓", "«خودکار» (میانگینِ رنگ‌های خنثی)"),
    };

    public static string Build()
    {
        var ci = CultureInfo.InvariantCulture;
        var sb = new StringBuilder();
        sb.AppendLine("# ابزارهای ویرایشگرِ عکس");
        sb.AppendLine();
        sb.AppendLine("> این فایل از روی کد ساخته می‌شود (`Run-SelfTest.bat --write-docs`) — دستی ویرایش نکنید. همان فهرست منبعِ لغزنده‌های صفحهٔ وب و ابزارهای هوشِ مصنوعی (`GET /api/tools`) است.");
        sb.AppendLine();
        sb.AppendLine("همهٔ این‌ها در **«نسخهٔ ویرایش» (recipe)** جمع می‌شوند؛ عکسِ اصلی دست نمی‌خورد. ترتیبِ اجرا مثلِ Camera Raw:");
        sb.AppendLine("ترمیمِ لکه ⇐ تعادلِ سفیدی و نوردهی ⇐ مه‌زدایی ⇐ روشنی‌ها/سایه‌ها ⇐ منحنی‌ها ⇐ بافت/وضوح ⇐ رنگ ⇐ نویزگیری و شارپ ⇐ لنز، چرخش، برش ⇐ وینیت و دانه ⇐ پس‌زمینه ⇐ خروجی.");
        sb.AppendLine();
        sb.AppendLine("## ۱. لغزنده‌ها (`recipe.adjust`)");
        foreach (var g in ToolCatalog.Groups)
        {
            sb.AppendLine();
            sb.AppendLine($"### {g.Title}");
            sb.AppendLine(g.Help);
            sb.AppendLine();
            sb.AppendLine("| کلید | نام | بازه | پیش‌فرض | معادلِ فتوشاپ | کارش |");
            sb.AppendLine("|---|---|---|---|---|---|");
            foreach (var p in ToolCatalog.Params.Where(p => p.Group == g.Key))
                sb.AppendLine($"| `{p.Key}` | {p.Title} | {p.Min.ToString(ci)} تا {p.Max.ToString(ci)}{(p.Unit.Length > 0 ? " " + p.Unit : "")} | {p.Default.ToString(ci)} | {p.Photoshop} | {p.Help} |");
        }
        sb.AppendLine();
        sb.AppendLine("## ۲. ابزارهای دیگر");
        sb.AppendLine();
        sb.AppendLine("| بخش | در recipe | کارش |");
        sb.AppendLine("|---|---|---|");
        sb.AppendLine("| منحنیِ تُن | `curve.rgb`، `curve.red/green/blue`: نقاطِ `[ورودی، خروجی]` بینِ ۰ و ۲۵۵ | منحنیِ نرم و یکنوا (Fritsch–Carlson) — Curves و Tone Curve |");
        sb.AppendLine("| برش، چرخش، قرینه | `crop`: `x,y,w,h` (۰ تا ۱)، `angle` (−۴۵ تا ۴۵°)، `flipH`، `flipV` | چرخش خودش کمی بزرگ می‌کند تا گوشهٔ خالی نماند — Crop، Straighten، Flip |");
        sb.AppendLine("| ترمیمِ لکه | `spots`: `[{x,y,r}]` به نسبتِ عکس | پر کردن از اطراف (inpaint) — Spot Healing، Dust & Scratches |");
        sb.AppendLine("| حذفِ پس‌زمینه | `background`: `remove`، `method` (`auto`/`quick`/`ai`)، `color` (`#rrggbb` یا `transparent`)، `cleanup` (۰ تا ۱۰۰، −۱ = خودکار)، `shadow` | روشِ سبک بی مدل برای زمینهٔ ساده/استودیویی (زیرِ یک ثانیه) یا BiRefNet برای هر زمینه (سنگین، سرور)؛ تمیزکاریِ خودکارِ لبه با سنجشِ هاله روی رنگِ مخالف؛ قلمِ اصلاحِ ماسک در صفحه — Remove Background، Select Subject، Refine Edge، Decontaminate Colors |");
        sb.AppendLine("| خروجی | `output`: `format` (jpeg/png/webp)، `quality`، `longEdge`، `square`، `padding`، `upscale` (۱/۲/۴)، `sharpen` | قابِ مربعِ فروشگاه (کالا وسط)، بزرگ‌نماییِ هوشمند، شارپِ نهایی — Export، Image Size، Super Resolution |");
        sb.AppendLine("| خودکار | `POST /api/docs/{id}/auto` | رایگان و بی‌اینترنت: تعادلِ سفیدی، نوردهی، سیاه/سفید، روشنی‌ها/سایه‌ها، کنتراست، مه، وایبرنس، نویز، شارپ — Auto Tone/Contrast/Color |");
        sb.AppendLine("| ویرایشِ هوشمند | `POST /api/docs/{id}/ai-edit` | هوشِ مصنوعیِ بینا عکس (کوچک) و اندازه‌گیری‌ها را می‌بیند و نسخه را پیشنهاد می‌دهد؛ یک بار نتیجه را می‌بیند و اصلاح می‌کند — AI.md |");
        sb.AppendLine();
        sb.AppendLine("## ۳. فیلترهای آماده (پریست)");
        sb.AppendLine();
        sb.AppendLine("در صفحه زبانهٔ «فیلتر»؛ در API کلیدِ `preset` در نسخه (اول فیلتر، بعد بقیهٔ نسخه روی آن).");
        sb.AppendLine();
        sb.AppendLine("| کلید | نام | کارش | نسخه |");
        sb.AppendLine("|---|---|---|---|");
        foreach (var p in Presets.All) sb.AppendLine($"| `{p.Key}` | {p.Title} | {p.Help} | `{p.Recipe.ToJson()}` |");
        sb.AppendLine();
        sb.AppendLine("## ۴. پوششِ ۶۲ قابلیتِ «ارتقای کیفیت»ِ فتوشاپ");
        sb.AppendLine();
        sb.AppendLine("از `research/Photoshop_Features_FA.xlsx` (ستونِ «ارتقای کیفیت»). ✓ ساخته شده · ◐ بخشی · ⏳ در برنامه · ✗ نه.");
        sb.AppendLine();
        sb.AppendLine("| ردیف | قابلیت | وضعیت | این‌جا |");
        sb.AppendLine("|---|---|---|---|");
        foreach (var c in Coverage) sb.AppendLine($"| {c.Row} | {c.Name} | {c.Status} | {c.How} |");
        var done = Coverage.Count(c => c.Status == "✓"); var part = Coverage.Count(c => c.Status == "◐");
        var plan = Coverage.Count(c => c.Status == "⏳"); var no = Coverage.Count(c => c.Status == "✗");
        sb.AppendLine();
        sb.AppendLine($"جمع: **{done} ساخته شده، {part} بخشی، {plan} در برنامه، {no} نه** (از {Coverage.Length}).");
        return sb.ToString();
    }
}
