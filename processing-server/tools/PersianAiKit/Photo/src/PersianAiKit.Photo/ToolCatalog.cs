namespace PersianAiKit.Photo;

/// <summary>یک لغزنده: کلید در recipe.adjust، بازه، پیش‌فرض و توضیحِ فارسی (برای صفحه، هوشِ مصنوعی و سند).</summary>
public sealed record ToolParam(
    string Key, string Group, string Title, string Help,
    double Min, double Max, double Default, double Step,
    string Unit = "", string Photoshop = "");

/// <summary>یک گروهِ ابزار (پنلِ صفحه).</summary>
public sealed record ToolGroup(string Key, string Title, string Help);

/// <summary>
/// فهرستِ همهٔ ابزارهای عددی. همین فهرست منبعِ صفحهٔ وب (لغزنده‌ها)، ابزارهای هوشِ مصنوعی (/api/tools) و سندِ FEATURES.md است؛
/// ابزارِ تازه = یک خط این‌جا + پیاده‌سازی در Engine.
/// </summary>
public static class ToolCatalog
{
    public static readonly IReadOnlyList<ToolGroup> Groups = new[]
    {
        new ToolGroup("light", "نور", "نوردهی، کنتراست، روشنی‌ها و سایه‌ها — بیشترِ بهتر شدنِ یک عکس از همین‌جاست."),
        new ToolGroup("color", "رنگ", "تعادلِ سفیدی (ته‌رنگ) و شدتِ رنگ‌ها."),
        new ToolGroup("hsl", "رنگ‌به‌رنگ (HSL)", "فام، اشباع و روشنیِ هر خانوادهٔ رنگ جداگانه."),
        new ToolGroup("grading", "رنگ‌دهیِ سایه و روشنی", "رنگِ دلخواه در سایه‌ها و روشنی‌ها (حال‌وهوای سینمایی)."),
        new ToolGroup("levels", "سطوح (Levels)", "نقطهٔ سیاه، نقطهٔ سفید و گامای میانه‌ها."),
        new ToolGroup("presence", "وضوح و مه", "بافت، وضوح (کنتراستِ محلی) و مه‌زدایی."),
        new ToolGroup("detail", "جزئیات", "شارپ و نویزگیری."),
        new ToolGroup("effects", "افکت", "وینیت و دانه."),
        new ToolGroup("geometry", "لنز", "اصلاحِ اعوجاجِ لنز. برش و چرخش در ابزارِ برش است."),
    };

    private static readonly (string Key, string Title, double Hue)[] Bands =
    {
        ("red", "قرمز", 0), ("orange", "نارنجی", 30), ("yellow", "زرد", 60), ("green", "سبز", 120),
        ("aqua", "فیروزه‌ای", 180), ("blue", "آبی", 240), ("purple", "بنفش", 270), ("magenta", "ارغوانی", 300),
    };

    /// <summary>هشت خانوادهٔ رنگ (برای HSL): کلید، نامِ فارسی، مرکزِ فام (درجه).</summary>
    public static IReadOnlyList<(string Key, string Title, double Hue)> HslBands => Bands;

    public static readonly IReadOnlyList<ToolParam> Params = Build();

    private static readonly Dictionary<string, ToolParam> ByKey = Params.ToDictionary(p => p.Key, StringComparer.OrdinalIgnoreCase);

    public static ToolParam? Find(string key) => ByKey.GetValueOrDefault(key);
    public static double Default(string key) => ByKey.TryGetValue(key, out var p) ? p.Default : 0;

    private static List<ToolParam> Build()
    {
        var l = new List<ToolParam>
        {
            // ── نور ──
            new("exposure", "light", "نوردهی", "روشنیِ کلی به واحدِ «استاپ» مثلِ دوربین؛ +۱ یعنی نورِ دو برابر.", -4, 4, 0, 0.05, "EV", "Exposure"),
            new("contrast", "light", "کنتراست", "فاصلهٔ تیره‌ها و روشن‌ها (منحنیِ S).", -100, 100, 0, 1, "", "Brightness/Contrast، Exposure & Contrast"),
            new("highlights", "light", "روشنی‌ها", "منفی ⇒ برگرداندنِ جزئیاتِ آسمان و بخش‌های سوخته (محلی و لبه‌آگاه).", -100, 100, 0, 1, "", "Highlights، Shadows/Highlights"),
            new("shadows", "light", "سایه‌ها", "مثبت ⇒ باز کردنِ سایه‌های تیره (مثلاً صورت در ضدنور) بی هاله.", -100, 100, 0, 1, "", "Shadows، Shadows/Highlights"),
            new("whites", "light", "سفیدها", "نقطهٔ سفید: مثبت ⇒ روشن‌ترین بخش‌ها سفیدتر.", -100, 100, 0, 1, "", "Whites"),
            new("blacks", "light", "سیاه‌ها", "نقطهٔ سیاه: منفی ⇒ سیاه‌ترها عمیق‌تر؛ مثبت ⇒ ظاهرِ مات.", -100, 100, 0, 1, "", "Blacks"),
            new("brightness", "light", "روشنیِ میانه", "روشن یا تیره کردنِ میانه‌ها بی دست زدن به سیاه و سفیدِ کامل.", -100, 100, 0, 1, "", "Brightness، Levels (gamma)"),
            // ── رنگ ──
            new("temperature", "color", "دما", "منفی ⇒ آبی‌تر (سردتر)، مثبت ⇒ زردتر (گرم‌تر). رفعِ زردیِ نورِ لامپ یا آبیِ هوای ابری.", -100, 100, 0, 1, "", "White Balance (Temp)"),
            new("tint", "color", "ته‌رنگ", "منفی ⇒ سبزتر، مثبت ⇒ ارغوانی‌تر. رفعِ سبزیِ نورِ مهتابی.", -100, 100, 0, 1, "", "White Balance (Tint)"),
            new("vibrance", "color", "وایبرنس", "افزایشِ هوشمندِ رنگ: رنگ‌های کم‌رنگ بیشتر، رنگِ پوست کمتر.", -100, 100, 0, 1, "", "Vibrance"),
            new("saturation", "color", "اشباع", "شدتِ همهٔ رنگ‌ها به یک اندازه؛ −۱۰۰ ⇒ سیاه‌وسفید.", -100, 100, 0, 1, "", "Saturation، Hue/Saturation، Desaturate"),
            // ── رنگ‌دهی ──
            new("shadowsHue", "grading", "فامِ سایه‌ها", "رنگی که به سایه‌ها افزوده می‌شود (درجه روی دایرهٔ رنگ).", 0, 360, 220, 1, "°", "Color Grading، Color Balance"),
            new("shadowsSat", "grading", "شدتِ رنگِ سایه‌ها", "۰ ⇒ بی‌اثر.", 0, 100, 0, 1, "", "Color Grading"),
            new("highlightsHue", "grading", "فامِ روشنی‌ها", "رنگی که به روشنی‌ها افزوده می‌شود.", 0, 360, 40, 1, "°", "Color Grading"),
            new("highlightsSat", "grading", "شدتِ رنگِ روشنی‌ها", "۰ ⇒ بی‌اثر.", 0, 100, 0, 1, "", "Color Grading"),
            new("gradingBalance", "grading", "تعادل", "منفی ⇒ سهمِ سایه‌ها بیشتر، مثبت ⇒ سهمِ روشنی‌ها بیشتر.", -100, 100, 0, 1, "", "Color Grading (Balance)"),
            // ── سطوح ──
            new("levelsBlack", "levels", "سیاهِ ورودی", "هر چه تیره‌تر از این است سیاهِ کامل می‌شود.", 0, 250, 0, 1, "", "Levels"),
            new("levelsWhite", "levels", "سفیدِ ورودی", "هر چه روشن‌تر از این است سفیدِ کامل می‌شود.", 5, 255, 255, 1, "", "Levels"),
            new("levelsGamma", "levels", "گامای میانه", "بیشتر از ۱ ⇒ میانه‌ها روشن‌تر.", 0.2, 5, 1, 0.01, "", "Levels"),
            // ── وضوح و مه ──
            new("texture", "presence", "بافت", "جزئیاتِ ریز تا متوسط (پوست، برگ، پارچه): مثبت ⇒ پررنگ‌تر، منفی ⇒ نرم‌تر.", -100, 100, 0, 1, "", "Texture"),
            new("clarity", "presence", "وضوح", "کنتراستِ محلیِ میانه‌ها و حسِ عمق؛ منفی ⇒ نرم و رؤیایی.", -100, 100, 0, 1, "", "Clarity، High Pass"),
            new("dehaze", "presence", "مه‌زدایی", "برداشتنِ مه و غبار (منفی ⇒ مه افزودن).", -100, 100, 0, 1, "", "Dehaze"),
            // ── جزئیات ──
            new("sharpen", "detail", "شارپ", "تیز کردنِ لبه‌ها (ماسکِ غیرشارپ روی روشنایی، بی رنگ‌پریدگی).", 0, 150, 0, 1, "", "Sharpening، Unsharp Mask، Smart Sharpen"),
            new("sharpenRadius", "detail", "شعاعِ شارپ", "اندازهٔ لبه‌هایی که تیز می‌شوند (پیکسل در اندازهٔ اصلی).", 0.5, 3, 1, 0.1, "px", "Sharpening (Radius)"),
            new("sharpenMasking", "detail", "ماسکِ شارپ", "بیشتر ⇒ فقط لبه‌های قوی تیز می‌شوند؛ پوست و آسمان دست نمی‌خورد.", 0, 100, 0, 1, "", "Sharpening (Masking)، Sharpen Edges"),
            new("noiseLuma", "detail", "نویزگیریِ روشنایی", "دانه‌های ریزِ روشن و تیره (عکسِ شب و ISO بالا).", 0, 100, 0, 1, "", "Noise Reduction، Reduce Noise، Despeckle"),
            new("noiseColor", "detail", "نویزگیریِ رنگ", "لکه‌های رنگیِ ریز در سایه‌ها.", 0, 100, 0, 1, "", "Noise Reduction (Color)"),
            // ── افکت ──
            new("vignette", "effects", "وینیت", "منفی ⇒ گوشه‌ها تیره‌تر (تمرکز روی سوژه)، مثبت ⇒ روشن‌تر.", -100, 100, 0, 1, "", "Vignette"),
            new("vignetteMidpoint", "effects", "اندازهٔ وینیت", "کمتر ⇒ وینیت به وسط نزدیک‌تر.", 0, 100, 50, 1, "", "Vignette (Midpoint)"),
            new("vignetteFeather", "effects", "نرمیِ وینیت", "بیشتر ⇒ گذارِ نرم‌تر.", 0, 100, 50, 1, "", "Vignette (Feather)"),
            new("grain", "effects", "دانه", "دانهٔ فیلمی.", 0, 100, 0, 1, "", "Grain، Add Noise"),
            new("grainSize", "effects", "اندازهٔ دانه", "درشتیِ دانه.", 0, 100, 25, 1, "", "Grain (Size)"),
            // ── لنز ──
            new("distortion", "geometry", "اعوجاجِ لنز", "مثبت ⇒ رفعِ حالتِ بشکه‌ای (لنزِ واید)، منفی ⇒ رفعِ حالتِ بالشتکی.", -100, 100, 0, 1, "", "Lens Corrections (Distortion)"),
            new("lensVignette", "geometry", "تاریکیِ گوشه‌های لنز", "مثبت ⇒ روشن کردنِ گوشه‌هایی که لنز تیره کرده.", 0, 100, 0, 1, "", "Lens Corrections (Vignetting)"),
        };
        foreach (var (key, title, _) in Bands)
        {
            l.Add(new(key + "Hue", "hsl", "فامِ " + title, $"چرخاندنِ رنگِ {title} به سمتِ رنگ‌های همسایه.", -100, 100, 0, 1, "", "HSL (Hue)، Hue/Saturation، Replace Color"));
            l.Add(new(key + "Sat", "hsl", "اشباعِ " + title, $"شدتِ رنگِ {title}.", -100, 100, 0, 1, "", "HSL (Saturation)، Selective Color"));
            l.Add(new(key + "Lum", "hsl", "روشنیِ " + title, $"روشن یا تیره کردنِ {title} (مثلاً آسمانِ آبی تیره‌تر).", -100, 100, 0, 1, "", "HSL (Luminance)، Black & White"));
        }
        return l;
    }

    public static double Clamp(string key, double v) =>
        ByKey.TryGetValue(key, out var p) ? Math.Clamp(double.IsFinite(v) ? v : p.Default, p.Min, p.Max) : v;
}
