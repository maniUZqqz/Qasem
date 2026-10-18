namespace PersianAiKit.Video;

/// <summary>یک لغزنده: کلید در recipe.adjust، بازه، پیش‌فرض، توضیحِ فارسی و معادلِ پریمیر (برای صفحه، هوشِ مصنوعی و سند).</summary>
public sealed record ToolParam(
    string Key, string Group, string Title, string Help,
    double Min, double Max, double Default, double Step,
    string Unit = "", string Premiere = "");

/// <summary>یک گروهِ ابزار (پنلِ صفحه).</summary>
public sealed record ToolGroup(string Key, string Title, string Help, string Stage);

/// <summary>
/// فهرستِ همهٔ ابزارهای عددیِ ویدیو. همین فهرست منبعِ صفحهٔ وب، ابزارهای هوشِ مصنوعی (/api/tools) و FEATURES.md است.
/// رنگ و نور همان ریاضیِ ویرایشگرِ عکس است و در یک LUTِ سه‌بعدی خلاصه می‌شود (مثلِ Lumetri)؛ بقیه فیلترهای FFmpeg‌اند.
/// </summary>
public static class ToolCatalog
{
    public static readonly IReadOnlyList<ToolGroup> Groups = new[]
    {
        new ToolGroup("light", "نور", "نوردهی، کنتراست، روشنی‌ها و سایه‌ها — بخشِ Basicِ لومتری.", "color"),
        new ToolGroup("color", "رنگ", "تعادلِ سفیدی و شدتِ رنگ‌ها.", "color"),
        new ToolGroup("hsl", "رنگ‌به‌رنگ (HSL)", "فام، اشباع و روشنیِ هر خانوادهٔ رنگ جداگانه (HSL Secondary).", "color"),
        new ToolGroup("grading", "رنگ‌دهیِ سایه و روشنی", "رنگِ دلخواه در سایه‌ها و روشنی‌ها (Creative و چرخ‌های رنگ).", "color"),
        new ToolGroup("levels", "سطوح و گاما", "نقطهٔ سیاه، نقطهٔ سفید و گامای میانه‌ها.", "color"),
        new ToolGroup("detail", "جزئیات", "شارپ، وضوح و نویزگیریِ تصویر.", "color"),
        new ToolGroup("effects", "افکت", "وینیت و دانهٔ فیلم.", "color"),
        new ToolGroup("lens", "لنز", "اصلاحِ اعوجاجِ لنزِ واید (بشکه‌ای).", "color"),
        new ToolGroup("audio", "صدا", "بلندی، کاهشِ نویز و غرش و کلیک، سین‌گیر، اکولایزر و کمپرسور — مثلِ Essential Sound.", "audio"),
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

    /// <summary>کلیدهایی که در LUTِ رنگ جمع می‌شوند (نقطه‌ای: هر پیکسل مستقل).</summary>
    public static bool InLut(string key) => ByKey.TryGetValue(key, out var p) && p.Group is "light" or "color" or "hsl" or "grading" or "levels";

    private static List<ToolParam> Build()
    {
        var l = new List<ToolParam>
        {
            // ── نور ──
            new("exposure", "light", "نوردهی", "روشنیِ کلی به واحدِ «استاپ»؛ +۱ یعنی نورِ دو برابر.", -3, 3, 0, 0.05, "EV", "Lumetri: Exposure"),
            new("contrast", "light", "کنتراست", "فاصلهٔ تیره‌ها و روشن‌ها (منحنیِ S).", -100, 100, 0, 1, "", "Lumetri: Contrast، Brightness & Contrast"),
            new("highlights", "light", "روشنی‌ها", "منفی ⇒ برگرداندنِ جزئیاتِ آسمان و بخش‌های سوخته.", -100, 100, 0, 1, "", "Lumetri: Highlights"),
            new("shadows", "light", "سایه‌ها", "مثبت ⇒ باز کردنِ سایه‌های تیره (صورت در ضدنور).", -100, 100, 0, 1, "", "Lumetri: Shadows"),
            new("whites", "light", "سفیدها", "نقطهٔ سفید: مثبت ⇒ روشن‌ترین بخش‌ها سفیدتر.", -100, 100, 0, 1, "", "Lumetri: Whites"),
            new("blacks", "light", "سیاه‌ها", "نقطهٔ سیاه: منفی ⇒ سیاه‌ترها عمیق‌تر؛ مثبت ⇒ ظاهرِ مات (Faded Film).", -100, 100, 0, 1, "", "Lumetri: Blacks، Faded Film"),
            new("brightness", "light", "روشنیِ میانه", "روشن یا تیره کردنِ میانه‌ها بی دست زدن به سیاه و سفیدِ کامل.", -100, 100, 0, 1, "", "Brightness، Gamma Correction"),
            // ── رنگ ──
            new("temperature", "color", "دما", "منفی ⇒ آبی‌تر (سردتر)، مثبت ⇒ زردتر (گرم‌تر). رفعِ زردیِ لامپ یا آبیِ هوای ابری.", -100, 100, 0, 1, "", "Lumetri: White Balance (Temperature)"),
            new("tint", "color", "ته‌رنگ", "منفی ⇒ سبزتر، مثبت ⇒ ارغوانی‌تر. رفعِ سبزیِ نورِ مهتابی.", -100, 100, 0, 1, "", "Lumetri: White Balance (Tint)"),
            new("vibrance", "color", "وایبرنس", "افزایشِ هوشمندِ رنگ: رنگ‌های کم‌رنگ بیشتر، رنگِ پوست کمتر.", -100, 100, 0, 1, "", "Lumetri: Vibrance"),
            new("saturation", "color", "اشباع", "شدتِ همهٔ رنگ‌ها؛ −۱۰۰ ⇒ سیاه‌وسفید.", -100, 100, 0, 1, "", "Lumetri: Saturation، Black & White"),
            // ── رنگ‌دهی ──
            new("shadowsHue", "grading", "فامِ سایه‌ها", "رنگی که به سایه‌ها افزوده می‌شود (درجه روی دایرهٔ رنگ).", 0, 360, 220, 1, "°", "Lumetri: Shadow Tint، Color Wheels"),
            new("shadowsSat", "grading", "شدتِ رنگِ سایه‌ها", "۰ ⇒ بی‌اثر.", 0, 100, 0, 1, "", "Lumetri: Shadow Tint"),
            new("highlightsHue", "grading", "فامِ روشنی‌ها", "رنگی که به روشنی‌ها افزوده می‌شود.", 0, 360, 40, 1, "°", "Lumetri: Highlight Tint"),
            new("highlightsSat", "grading", "شدتِ رنگِ روشنی‌ها", "۰ ⇒ بی‌اثر.", 0, 100, 0, 1, "", "Lumetri: Highlight Tint"),
            new("gradingBalance", "grading", "تعادل", "منفی ⇒ سهمِ سایه‌ها بیشتر، مثبت ⇒ سهمِ روشنی‌ها بیشتر.", -100, 100, 0, 1, "", "Lumetri: Tint Balance"),
            // ── سطوح ──
            new("levelsBlack", "levels", "سیاهِ ورودی", "هر چه تیره‌تر از این است سیاهِ کامل می‌شود.", 0, 250, 0, 1, "", "Levels"),
            new("levelsWhite", "levels", "سفیدِ ورودی", "هر چه روشن‌تر از این است سفیدِ کامل می‌شود.", 5, 255, 255, 1, "", "Levels"),
            new("levelsGamma", "levels", "گامای میانه", "بیشتر از ۱ ⇒ میانه‌ها روشن‌تر.", 0.2, 5, 1, 0.01, "", "Levels، Gamma Correction"),
            // ── جزئیات ──
            new("sharpen", "detail", "شارپ", "تیز کردنِ لبه‌ها (شارپِ تطبیقی: لبهٔ قوی کمتر، تا هاله نیفتد).", 0, 100, 0, 1, "", "Lumetri: Sharpen، Sharpen، Unsharp Mask"),
            new("clarity", "detail", "وضوح", "کنتراستِ محلیِ درشت و حسِ عمق؛ منفی ⇒ نرم و رؤیایی.", -100, 100, 0, 1, "", "Unsharp Mask (شعاعِ بزرگ)"),
            new("denoise", "detail", "نویزگیری", "دانه‌های روشن و تیره (فیلمِ شب و نورِ کم) — مکانی و زمانی.", 0, 100, 0, 1, "", "Median، Noise (پلاگین)"),
            new("denoiseColor", "detail", "نویزگیریِ رنگ", "لکه‌های رنگیِ ریز در سایه‌ها.", 0, 100, 0, 1, "", "Noise (پلاگین)"),
            // ── افکت ──
            new("vignette", "effects", "وینیت", "تیره کردنِ گوشه‌ها برای تمرکز روی سوژه.", 0, 100, 0, 1, "", "Lumetri: Vignette"),
            new("grain", "effects", "دانهٔ فیلم", "دانهٔ ریزِ متحرک، حسِ فیلم.", 0, 100, 0, 1, "", "Noise، Film look"),
            // ── لنز ──
            new("distortion", "lens", "اعوجاجِ لنز", "مثبت ⇒ رفعِ حالتِ بشکه‌ای (لنزِ واید، اکشن‌کم)، منفی ⇒ رفعِ حالتِ بالشتکی.", -100, 100, 0, 1, "", "Lens Distortion"),
            // ── صدا ──
            new("volume", "audio", "بلندی", "افزایش یا کاهشِ صدا (دسی‌بل). برای بلندیِ استانداردِ پخش، «هم‌سطح‌سازی» را روشن کنید.", -20, 20, 0, 0.5, "dB", "Audio Gain"),
            new("rumble", "audio", "کاهشِ غرش", "بریدنِ صداهای خیلی بم: باد، لرزشِ میز، کولر.", 0, 100, 0, 1, "", "Reduce Rumble (Essential Sound)"),
            new("noise", "audio", "کاهشِ نویز", "هیس و نویزِ ثابتِ پس‌زمینه (تطبیقی: نویز را دنبال می‌کند).", 0, 100, 0, 1, "", "Reduce Noise، DeNoise، Adaptive Noise Reduction"),
            new("declick", "audio", "حذفِ کلیک", "تق‌تق و خش‌های کوتاه.", 0, 100, 0, 1, "", "Automatic Click Remover"),
            new("deess", "audio", "سین‌گیر", "نرم کردنِ «س» و «ش»ِ تیز در گفتار.", 0, 100, 0, 1, "", "DeEss، DeEsser"),
            new("bass", "audio", "بم", "صداهای بم (زیرِ ۱۵۰ هرتز).", -12, 12, 0, 0.5, "dB", "Parametric Equalizer"),
            new("presence", "audio", "وضوحِ گفتار", "محدودهٔ ۳ کیلوهرتز: مثبت ⇒ گفتار واضح‌تر و جلوتر.", -12, 12, 0, 0.5, "dB", "Vocal Enhancer، Clarity (EQ)"),
            new("air", "audio", "درخشش", "صداهای زیر (بالای ۹ کیلوهرتز).", -12, 12, 0, 0.5, "dB", "Parametric Equalizer"),
            new("compress", "audio", "یکدست کردنِ بلندی", "کمپرسور: فاصلهٔ آرام و بلند کمتر ⇒ گفتار یکنواخت‌تر.", 0, 100, 0, 1, "", "Dynamics، Single-band Compressor، Clarity"),
        };
        foreach (var (key, title, _) in Bands)
        {
            l.Add(new(key + "Hue", "hsl", "فامِ " + title, $"چرخاندنِ رنگِ {title} به سمتِ رنگ‌های همسایه.", -100, 100, 0, 1, "", "HSL Secondary، Change Color"));
            l.Add(new(key + "Sat", "hsl", "اشباعِ " + title, $"شدتِ رنگِ {title}.", -100, 100, 0, 1, "", "HSL Secondary، Hue vs Sat"));
            l.Add(new(key + "Lum", "hsl", "روشنیِ " + title, $"روشن یا تیره کردنِ {title} (مثلاً آسمانِ آبی تیره‌تر).", -100, 100, 0, 1, "", "HSL Secondary، Hue vs Luma"));
        }
        return l;
    }

    public static double Clamp(string key, double v) =>
        ByKey.TryGetValue(key, out var p) ? Math.Clamp(double.IsFinite(v) ? v : p.Default, p.Min, p.Max) : v;
}
