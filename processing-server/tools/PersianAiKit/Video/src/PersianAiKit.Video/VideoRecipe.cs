using System.Globalization;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace PersianAiKit.Video;

/// <summary>
/// «نسخهٔ ویرایشِ ویدیو»: همهٔ تنظیم‌های یک کلیپ، غیرمخرب (فایلِ اصلی دست نمی‌خورد). همین JSON را صفحهٔ وب می‌سازد،
/// هوشِ مصنوعی پیشنهاد می‌دهد و موتور به زنجیرهٔ فیلترهای FFmpeg تبدیل می‌کند. هر چه نیامده = پیش‌فرض (بی‌اثر).
/// زمان‌ها همه به ثانیه و روی زمانِ فایلِ اصلی‌اند.
/// <code>
/// { "trim": { "start": 1.5, "end": 42 },
///   "cuts": [ { "start": 10.2, "end": 11.0 } ],
///   "time": { "speed": 1.25, "fadeIn": 0.5, "fadeOut": 1 },
///   "adjust": { "exposure": 0.3, "temperature": -8, "sharpen": 30, "noise": 40, "presence": 3 },
///   "curve": { "rgb": [[0,0],[70,55],[190,210],[255,255]] },
///   "crop": { "angle": 1.2 },
///   "frame": { "aspect": "9:16", "fit": "blur" },
///   "stabilize": { "amount": 50 },
///   "audio": { "normalize": -14, "hum": 50 },
///   "output": { "format": "mp4", "size": 1080, "quality": "standard" } }
/// </code>
/// </summary>
public sealed class VideoRecipe
{
    public TrimSettings? Trim { get; set; }
    /// <summary>بازه‌هایی که حذف می‌شوند (مثلاً مکث‌ها).</summary>
    public List<TimeRange>? Cuts { get; set; }
    public TimeSettings? Time { get; set; }
    /// <summary>لغزنده‌ها — کلیدها و بازه‌ها در <see cref="ToolCatalog"/>.</summary>
    public Dictionary<string, double> Adjust { get; set; } = new(StringComparer.OrdinalIgnoreCase);
    public CurveSettings? Curve { get; set; }
    public LutSettings? Lut { get; set; }
    public CropSettings? Crop { get; set; }
    public FrameSettings? Frame { get; set; }
    public StabilizeSettings? Stabilize { get; set; }
    public AudioSettings? Audio { get; set; }
    public OutputSettings? Output { get; set; }

    public double Get(string key) => Adjust.TryGetValue(key, out var v) ? v : ToolCatalog.Default(key);
    public bool Has(string key) => Math.Abs(Get(key) - ToolCatalog.Default(key)) > 1e-9;
    [JsonIgnore] public double Speed => Time?.Speed is > 0 and var s ? s : 1;

    public VideoRecipe Clone() => JsonSerializer.Deserialize<VideoRecipe>(JsonSerializer.Serialize(this, VideoJson.Options), VideoJson.Options)!;

    /// <summary>یکدست و امن: کلیدِ ناشناخته دور، عدد در بازه، پیش‌فرض حذف. ورودیِ هوشِ مصنوعی و کاربر همیشه از این‌جا می‌گذرد.</summary>
    public VideoRecipe Normalized()
    {
        var r = new VideoRecipe();
        foreach (var (k, v) in Adjust)
        {
            var p = ToolCatalog.Find(k);
            if (p is null) continue;
            var c = ToolCatalog.Clamp(p.Key, v);
            if (Math.Abs(c - p.Default) > 1e-9) r.Adjust[p.Key] = Math.Round(c, 4);
        }
        r.Trim = Trim?.Normalized();
        r.Cuts = TimeRange.Merge(Cuts) is { Count: > 0 } cuts ? cuts : null;
        r.Time = Time?.Normalized();
        r.Curve = Curve?.Normalized();
        r.Lut = Lut?.Normalized();
        r.Crop = Crop?.Normalized();
        r.Frame = Frame?.Normalized();
        r.Stabilize = Stabilize?.Normalized();
        r.Audio = Audio?.Normalized();
        r.Output = Output?.Normalized();
        return r;
    }

    /// <summary>دو نسخه روی هم: هر چه در <paramref name="over"/> آمده جای مقدارِ این را می‌گیرد.</summary>
    public VideoRecipe Merge(VideoRecipe over)
    {
        var r = Clone();
        foreach (var (k, v) in over.Adjust) r.Adjust[k] = v;
        r.Trim = over.Trim ?? r.Trim;
        r.Cuts = over.Cuts ?? r.Cuts;
        r.Time = over.Time ?? r.Time;
        r.Curve = over.Curve ?? r.Curve;
        r.Lut = over.Lut ?? r.Lut;
        r.Crop = over.Crop ?? r.Crop;
        r.Frame = over.Frame ?? r.Frame;
        r.Stabilize = over.Stabilize ?? r.Stabilize;
        r.Audio = over.Audio ?? r.Audio;
        r.Output = over.Output ?? r.Output;
        return r.Normalized();
    }

    /// <summary>JSON ⇒ نسخهٔ امن. «preset»: کلیدِ یک پریست ⇒ اول آن، بعد بقیهٔ نسخه روی آن.</summary>
    public static VideoRecipe Parse(string json)
    {
        if (string.IsNullOrWhiteSpace(json)) return new VideoRecipe();
        var r = (JsonSerializer.Deserialize<VideoRecipe>(json, VideoJson.Options) ?? new VideoRecipe()).Normalized();
        using var doc = JsonDocument.Parse(json, new JsonDocumentOptions { AllowTrailingCommas = true, CommentHandling = JsonCommentHandling.Skip });
        if (doc.RootElement.ValueKind == JsonValueKind.Object && doc.RootElement.TryGetProperty("preset", out var p) && p.ValueKind == JsonValueKind.String &&
            p.GetString() is { Length: > 0 } key)
            r = (Presets.Find(key) ?? throw new ArgumentException($"پریستِ «{key}» نیست.")).Recipe.Merge(r);
        return r;
    }

    public string ToJson(bool indented = false) => JsonSerializer.Serialize(this, indented ? VideoJson.Indented : VideoJson.Options);
}

/// <summary>بُرشِ سر و ته: از start تا end (ثانیه؛ end = ۰ ⇒ تا آخر).</summary>
public sealed class TrimSettings
{
    public double Start { get; set; }
    public double End { get; set; }

    internal TrimSettings? Normalized()
    {
        var s = Math.Max(0, double.IsFinite(Start) ? Start : 0);
        var e = double.IsFinite(End) && End > 0 ? End : 0;
        if (e > 0 && e < s + 0.05) e = s + 0.05;
        return s <= 0 && e <= 0 ? null : new TrimSettings { Start = Math.Round(s, 3), End = Math.Round(e, 3) };
    }
}

public sealed class TimeRange
{
    public double Start { get; set; }
    public double End { get; set; }

    /// <summary>مرتب، بی هم‌پوشانی، بی بازهٔ خیلی کوتاه (زیرِ ۴۰ میلی‌ثانیه)؛ حداکثر ۵۰۰ بازه.</summary>
    public static List<TimeRange> Merge(IEnumerable<TimeRange>? ranges)
    {
        var list = (ranges ?? Array.Empty<TimeRange>())
            .Where(c => c is not null && double.IsFinite(c.Start) && double.IsFinite(c.End))
            .Select(c => (S: Math.Max(0, Math.Min(c.Start, c.End)), E: Math.Max(c.Start, c.End)))
            .Where(c => c.E - c.S >= 0.04).OrderBy(c => c.S).ToList();
        var outList = new List<TimeRange>();
        foreach (var (s, e) in list)
        {
            if (outList.Count > 0 && s <= outList[^1].End + 0.001) outList[^1].End = Math.Max(outList[^1].End, Math.Round(e, 3));
            else outList.Add(new TimeRange { Start = Math.Round(s, 3), End = Math.Round(e, 3) });
        }
        return outList.Take(500).ToList();
    }
}

/// <summary>سرعت و محوِ ابتدا و انتها.</summary>
public sealed class TimeSettings
{
    /// <summary>۰٫۲۵ تا ۴ (۱ = عادی). صدا بی تغییرِ زیر و بمی تند یا کند می‌شود.</summary>
    public double Speed { get; set; } = 1;
    /// <summary>آهسته‌نمایشِ نرم با ساختنِ فریمِ میانی (جریانِ نوری) — سنگین.</summary>
    public bool Smooth { get; set; }
    public double FadeIn { get; set; }
    public double FadeOut { get; set; }

    internal TimeSettings? Normalized()
    {
        var t = new TimeSettings
        {
            Speed = Math.Round(Math.Clamp(double.IsFinite(Speed) && Speed > 0 ? Speed : 1, 0.25, 4), 3),
            FadeIn = Math.Round(Math.Clamp(double.IsFinite(FadeIn) ? FadeIn : 0, 0, 10), 2),
            FadeOut = Math.Round(Math.Clamp(double.IsFinite(FadeOut) ? FadeOut : 0, 0, 10), 2),
        };
        t.Smooth = Smooth && t.Speed < 1;
        return t.Speed == 1 && t.FadeIn == 0 && t.FadeOut == 0 ? null : t;
    }
}

/// <summary>منحنیِ تُن: نقاطِ [ورودی، خروجی] بینِ ۰ و ۲۵۵. rgb روی هر سه کانال؛ red/green/blue جدا.</summary>
public sealed class CurveSettings
{
    public double[][]? Rgb { get; set; }
    public double[][]? Red { get; set; }
    public double[][]? Green { get; set; }
    public double[][]? Blue { get; set; }

    internal CurveSettings? Normalized()
    {
        static double[][]? N(double[][]? pts)
        {
            if (pts is null) return null;
            var p = pts.Where(q => q is { Length: >= 2 } && double.IsFinite(q[0]) && double.IsFinite(q[1]))
                .Select(q => new[] { Math.Round(Math.Clamp(q[0], 0, 255), 2), Math.Round(Math.Clamp(q[1], 0, 255), 2) })
                .GroupBy(q => q[0]).Select(g => g.First()).OrderBy(q => q[0]).Take(16).ToArray();
            return p.Length < 2 || p.All(q => Math.Abs(q[0] - q[1]) < 1e-6) ? null : p;
        }
        var c = new CurveSettings { Rgb = N(Rgb), Red = N(Red), Green = N(Green), Blue = N(Blue) };
        return c.Rgb is null && c.Red is null && c.Green is null && c.Blue is null ? null : c;
    }
}

/// <summary>
/// فایلِ LUT (.cube) که کاربر داده: input ⇒ اول از همه (برگرداندنِ فیلمِ لاگ به رنگِ عادی)،
/// look ⇒ آخرِ رنگ، با شدتِ amount (۰ تا ۱۰۰) — مثلِ Input LUT و Look در لومتری.
/// </summary>
public sealed class LutSettings
{
    public string File { get; set; } = "";
    public string Mode { get; set; } = "look";
    public double Amount { get; set; } = 100;

    internal LutSettings? Normalized()
    {
        var f = Path.GetFileName(File ?? "").Trim();
        if (f.Length == 0 || !f.EndsWith(".cube", StringComparison.OrdinalIgnoreCase)) return null;
        var mode = (Mode ?? "").Trim().ToLowerInvariant() == "input" ? "input" : "look";
        var a = Math.Round(Math.Clamp(double.IsFinite(Amount) ? Amount : 100, 0, 100), 1);
        return a <= 0 ? null : new LutSettings { File = f, Mode = mode, Amount = a };
    }
}

/// <summary>برش، صاف کردن و قرینه: مستطیل به نسبتِ تصویر (۰ تا ۱)؛ angle درجه (مثبت = پادساعتگرد، با بزرگ‌نماییِ خودکار تا گوشه خالی نماند).</summary>
public sealed class CropSettings
{
    public double X { get; set; }
    public double Y { get; set; }
    public double W { get; set; } = 1;
    public double H { get; set; } = 1;
    public double Angle { get; set; }
    public bool FlipH { get; set; }
    public bool FlipV { get; set; }

    internal CropSettings? Normalized()
    {
        var x = Math.Clamp(double.IsFinite(X) ? X : 0, 0, 0.95);
        var y = Math.Clamp(double.IsFinite(Y) ? Y : 0, 0, 0.95);
        var c = new CropSettings
        {
            X = Math.Round(x, 5), Y = Math.Round(y, 5),
            W = Math.Round(Math.Clamp(double.IsFinite(W) ? W : 1, 0.05, 1 - x), 5),
            H = Math.Round(Math.Clamp(double.IsFinite(H) ? H : 1, 0.05, 1 - y), 5),
            Angle = Math.Round(Math.Clamp(double.IsFinite(Angle) ? Angle : 0, -45, 45), 2),
            FlipH = FlipH, FlipV = FlipV,
        };
        return c.IsIdentity ? null : c;
    }

    [JsonIgnore] public bool IsIdentity => X == 0 && Y == 0 && W >= 1 && H >= 1 && Angle == 0 && !FlipH && !FlipV;
    [JsonIgnore] public bool HasRect => X > 0 || Y > 0 || W < 1 || H < 1;
}

/// <summary>
/// قابِ خروجی (مثلِ Auto Reframe): aspect = «9:16» (ریلز/استوری)، «1:1»، «4:5»، «16:9» یا «original».
/// fit: crop ⇒ بریدن با مرکزِ focusX/focusY؛ blur ⇒ کلِ تصویر روی زمینهٔ محوِ خودش؛ black ⇒ نوارِ سیاه.
/// </summary>
public sealed class FrameSettings
{
    public string Aspect { get; set; } = "original";
    public string Fit { get; set; } = "crop";
    public double FocusX { get; set; } = 0.5;
    public double FocusY { get; set; } = 0.5;

    internal FrameSettings? Normalized()
    {
        var a = (Aspect ?? "").Trim();
        if (Ratio(a) is null) return null;
        var fit = (Fit ?? "").Trim().ToLowerInvariant() is "blur" or "black" ? Fit!.Trim().ToLowerInvariant() : "crop";
        return new FrameSettings
        {
            Aspect = a, Fit = fit,
            FocusX = Math.Round(Math.Clamp(double.IsFinite(FocusX) ? FocusX : 0.5, 0, 1), 3),
            FocusY = Math.Round(Math.Clamp(double.IsFinite(FocusY) ? FocusY : 0.5, 0, 1), 3),
        };
    }

    /// <summary>«9:16» ⇒ ۰٫۵۶۲۵ (عرض بر ارتفاع). نامعتبر یا «original» ⇒ null.</summary>
    public static double? Ratio(string? aspect)
    {
        var p = (aspect ?? "").Split(':');
        if (p.Length != 2) return null;
        if (!double.TryParse(p[0], NumberStyles.Float, CultureInfo.InvariantCulture, out var w) ||
            !double.TryParse(p[1], NumberStyles.Float, CultureInfo.InvariantCulture, out var h) || w <= 0 || h <= 0) return null;
        var r = w / h;
        return r is >= 0.2 and <= 5 ? r : null;
    }
}

/// <summary>تثبیتِ تصویرِ لرزان (مثلِ Warp Stabilizer): amount ۰ تا ۱۰۰ = نرمیِ مسیرِ دوربین.</summary>
public sealed class StabilizeSettings
{
    public double Amount { get; set; } = 50;

    internal StabilizeSettings? Normalized()
    {
        var a = Math.Round(Math.Clamp(double.IsFinite(Amount) ? Amount : 50, 0, 100), 1);
        return a <= 0 ? null : new StabilizeSettings { Amount = a };
    }
}

/// <summary>صدا: بی‌صدا، هم‌سطح‌سازیِ بلندی (LUFS؛ ۰ = خاموش) و حذفِ وزوزِ برق (۵۰ یا ۶۰ هرتز).</summary>
public sealed class AudioSettings
{
    public bool Mute { get; set; }
    /// <summary>بلندیِ هدف: −۱۴ (اینستاگرام، یوتیوب)، −۱۶ (پادکست)، −۲۳ (تلویزیون). ۰ ⇒ خاموش.</summary>
    public double Normalize { get; set; }
    /// <summary>فرکانسِ برق برای حذفِ وزوز: ۵۰ (ایران، اروپا) یا ۶۰. ۰ ⇒ خاموش.</summary>
    public int Hum { get; set; }

    internal AudioSettings? Normalized()
    {
        var n = double.IsFinite(Normalize) && Normalize < 0 ? Math.Round(Math.Clamp(Normalize, -31, -9), 1) : 0;
        var hum = Hum is 50 or 60 ? Hum : 0;
        return !Mute && n == 0 && hum == 0 ? null : new AudioSettings { Mute = Mute, Normalize = n, Hum = hum };
    }
}

/// <summary>خروجی: قالب، اندازه (ضلعِ کوچک‌تر)، نرخِ فریم، کیفیت.</summary>
public sealed class OutputSettings
{
    /// <summary>mp4، webm، gif، mp3 یا wav.</summary>
    public string Format { get; set; } = "mp4";
    /// <summary>h264 (همه‌جا پخش می‌شود) یا h265 (نصفِ حجم). برای webm همیشه vp9.</summary>
    public string Codec { get; set; } = "h264";
    /// <summary>ضلعِ کوچک‌ترِ تصویر به پیکسل: ۱۰۸۰ ⇒ 1920×1080 یا 1080×1920. ۰ ⇒ همان فایل.</summary>
    public int Size { get; set; }
    /// <summary>فریم در ثانیه؛ ۰ ⇒ همان فایل.</summary>
    public double Fps { get; set; }
    /// <summary>high، standard یا small.</summary>
    public string Quality { get; set; } = "standard";
    /// <summary>روشنایی و رنگ در محدودهٔ مجازِ پخشِ تلویزیونی (Video Limiter).</summary>
    public bool BroadcastSafe { get; set; }

    internal OutputSettings Normalized()
    {
        var f = (Format ?? "mp4").Trim().ToLowerInvariant();
        f = f is "mp4" or "webm" or "gif" or "mp3" or "wav" ? f : "mp4";
        var codec = (Codec ?? "h264").Trim().ToLowerInvariant() is "h265" or "hevc" ? "h265" : "h264";
        var q = (Quality ?? "").Trim().ToLowerInvariant() is "high" or "small" ? Quality!.Trim().ToLowerInvariant() : "standard";
        var size = Size <= 0 ? 0 : Math.Clamp(Size, 120, 2160);
        if (f == "gif" && (size == 0 || size > 720)) size = size == 0 ? 360 : 720;
        return new OutputSettings
        {
            Format = f, Codec = f == "mp4" ? codec : f == "webm" ? "vp9" : "",
            Size = size - size % 2,
            Fps = double.IsFinite(Fps) && Fps > 0 ? Math.Round(Math.Clamp(Fps, 5, 60), 3) : f == "gif" ? 12 : 0,
            Quality = q, BroadcastSafe = BroadcastSafe && f is "mp4" or "webm",
        };
    }

    [JsonIgnore] public bool AudioOnly => Format is "mp3" or "wav";
    [JsonIgnore] public string Extension => "." + Format;
}

public static class VideoJson
{
    public static readonly JsonSerializerOptions Options = Make(false);
    public static readonly JsonSerializerOptions Indented = Make(true);

    private static JsonSerializerOptions Make(bool indented) => new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
        DictionaryKeyPolicy = null,
        PropertyNameCaseInsensitive = true,
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
        NumberHandling = JsonNumberHandling.AllowReadingFromString | JsonNumberHandling.AllowNamedFloatingPointLiterals,
        AllowTrailingCommas = true,
        ReadCommentHandling = JsonCommentHandling.Skip,
        WriteIndented = indented,
        Encoder = System.Text.Encodings.Web.JavaScriptEncoder.UnsafeRelaxedJsonEscaping,
    };
}
