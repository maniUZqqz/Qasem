using System.Text.Json;
using System.Text.Json.Serialization;

namespace PersianAiKit.Photo;

/// <summary>
/// «نسخهٔ ویرایش»: همهٔ تنظیم‌های یک عکس، غیرمخرب (عکسِ اصلی دست نمی‌خورد). همین JSON را صفحهٔ وب می‌سازد،
/// هوشِ مصنوعی پیشنهاد می‌دهد و موتور اجرا می‌کند. هر چه نیامده = پیش‌فرض (بی‌اثر).
/// <code>
/// { "adjust": { "exposure": 0.4, "shadows": 30, "temperature": -10 },
///   "curve":  { "rgb": [[0,0],[70,55],[190,210],[255,255]] },
///   "crop":   { "x":0.05, "y":0, "w":0.9, "h":1, "angle": 1.5 },
///   "spots":  [ { "x":0.41, "y":0.33, "r":0.01 } ],
///   "background": { "remove": true, "color": "#ffffff" },
///   "output": { "format": "jpeg", "longEdge": 1200, "square": true } }
/// </code>
/// </summary>
public sealed class Recipe
{
    /// <summary>لغزنده‌ها — کلیدها و بازه‌ها در <see cref="ToolCatalog"/>.</summary>
    public Dictionary<string, double> Adjust { get; set; } = new(StringComparer.OrdinalIgnoreCase);
    public CurveSettings? Curve { get; set; }
    public CropSettings? Crop { get; set; }
    /// <summary>لکه‌ها و خش‌هایی که پاک (ترمیم) می‌شوند.</summary>
    public List<Spot>? Spots { get; set; }
    public BackgroundSettings? Background { get; set; }
    public OutputSettings? Output { get; set; }

    public double Get(string key) => Adjust.TryGetValue(key, out var v) ? v : ToolCatalog.Default(key);
    public bool Has(string key) => Math.Abs(Get(key) - ToolCatalog.Default(key)) > 1e-9;

    public Recipe Clone() => JsonSerializer.Deserialize<Recipe>(JsonSerializer.Serialize(this, PhotoJson.Options), PhotoJson.Options)!;

    /// <summary>
    /// یکدست و امن: کلیدِ ناشناخته دور ریخته، عدد در بازه، مقدارِ پیش‌فرض حذف (JSONِ کوتاه‌تر)، برش و لکه‌ها در محدوده.
    /// ورودیِ هوشِ مصنوعی و کاربر همیشه از این‌جا می‌گذرد.
    /// </summary>
    public Recipe Normalized()
    {
        var r = new Recipe();
        foreach (var (k, v) in Adjust)
        {
            var p = ToolCatalog.Find(k);
            if (p is null) continue;
            var c = ToolCatalog.Clamp(p.Key, v);
            if (Math.Abs(c - p.Default) > 1e-9) r.Adjust[p.Key] = Math.Round(c, 4);
        }
        r.Curve = Curve?.Normalized();
        r.Crop = Crop?.Normalized();
        r.Spots = Spots?.Where(s => double.IsFinite(s.X) && double.IsFinite(s.Y) && s.R > 0)
            .Select(s => new Spot { X = Math.Clamp(s.X, 0, 1), Y = Math.Clamp(s.Y, 0, 1), R = Math.Clamp(s.R, 0.001, 0.2) })
            .Take(500).ToList() is { Count: > 0 } sp ? sp : null;
        r.Background = Background?.Normalized();
        r.Output = Output?.Normalized();
        return r;
    }

    /// <summary>دو نسخه روی هم: هر چه در <paramref name="over"/> آمده جای مقدارِ این را می‌گیرد.</summary>
    public Recipe Merge(Recipe over)
    {
        var r = Clone();
        foreach (var (k, v) in over.Adjust) r.Adjust[k] = v;
        r.Curve = over.Curve ?? r.Curve;
        r.Crop = over.Crop ?? r.Crop;
        r.Spots = over.Spots ?? r.Spots;
        r.Background = over.Background ?? r.Background;
        r.Output = over.Output ?? r.Output;
        return r.Normalized();
    }

    public static Recipe Parse(string json) =>
        (string.IsNullOrWhiteSpace(json) ? new Recipe() : JsonSerializer.Deserialize<Recipe>(json, PhotoJson.Options) ?? new Recipe()).Normalized();

    public string ToJson(bool indented = false) =>
        JsonSerializer.Serialize(this, indented ? PhotoJson.Indented : PhotoJson.Options);
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
            var identity = p.All(q => Math.Abs(q[0] - q[1]) < 1e-6);
            return p.Length < 2 || identity ? null : p;
        }
        var c = new CurveSettings { Rgb = N(Rgb), Red = N(Red), Green = N(Green), Blue = N(Blue) };
        return c.Rgb is null && c.Red is null && c.Green is null && c.Blue is null ? null : c;
    }
}

/// <summary>برش و چرخش: مستطیل به نسبتِ تصویر (۰ تا ۱)؛ angle درجه (مثبت = پادساعتگرد). چرخش خودش کمی بزرگ می‌کند تا گوشهٔ سیاه نماند.</summary>
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
        var x = Math.Clamp(double.IsFinite(X) ? X : 0, 0, 0.99);
        var y = Math.Clamp(double.IsFinite(Y) ? Y : 0, 0, 0.99);
        var c = new CropSettings
        {
            X = Math.Round(x, 5), Y = Math.Round(y, 5),
            W = Math.Round(Math.Clamp(double.IsFinite(W) ? W : 1, 0.01, 1 - x), 5),
            H = Math.Round(Math.Clamp(double.IsFinite(H) ? H : 1, 0.01, 1 - y), 5),
            Angle = Math.Round(Math.Clamp(double.IsFinite(Angle) ? Angle : 0, -45, 45), 3),
            FlipH = FlipH, FlipV = FlipV,
        };
        return c.IsIdentity ? null : c;
    }

    [JsonIgnore]
    public bool IsIdentity => X == 0 && Y == 0 && W >= 1 && H >= 1 && Angle == 0 && !FlipH && !FlipV;
}

/// <summary>یک لکه برای ترمیم: مرکز به نسبتِ عکسِ اصلی، شعاع به نسبتِ ضلعِ کوچک‌تر.</summary>
public sealed class Spot
{
    public double X { get; set; }
    public double Y { get; set; }
    public double R { get; set; } = 0.01;
}

/// <summary>حذفِ پس‌زمینه و گذاشتنِ رنگِ دلخواه.</summary>
public sealed class BackgroundSettings
{
    public bool Remove { get; set; }
    /// <summary>
    /// روشِ ساختنِ ماسک: «auto» (زمینهٔ ساده ⇒ سبک، وگرنه هوشِ مصنوعی اگر حافظه باشد)،
    /// «quick» (سبک، بی مدل — زمینهٔ ساده/استودیویی) یا «ai» (BiRefNet — سنگین، برای سرور).
    /// </summary>
    public string Method { get; set; } = "auto";
    /// <summary>«#ffffff» یا «transparent» (فقط برای PNG/WebP).</summary>
    public string Color { get; set; } = "#ffffff";
    /// <summary>تمیز کردنِ لبه (۰ تا ۱۰۰): پاک کردنِ رنگِ پس‌زمینهٔ قبلی از لبه و کمی تنگ‌تر کردنِ ماسک. −۱ ⇒ خودکار.</summary>
    public double Cleanup { get; set; } = -1;
    /// <summary>سایهٔ نرمِ زیرِ کالا (۰ تا ۱۰۰).</summary>
    public double Shadow { get; set; }

    internal BackgroundSettings? Normalized()
    {
        if (!Remove) return null;
        var color = (Color ?? "").Trim().ToLowerInvariant();
        if (color != "transparent" && !PhotoColor.TryParse(color, out _)) color = "#ffffff";
        var method = (Method ?? "").Trim().ToLowerInvariant();
        return new BackgroundSettings
        {
            Remove = true, Color = color,
            Method = method is "quick" or "ai" ? method : "auto",
            Cleanup = Cleanup < 0 ? -1 : Math.Round(Math.Clamp(Cleanup, 0, 100), 1),
            Shadow = Math.Round(Math.Clamp(double.IsFinite(Shadow) ? Shadow : 0, 0, 100), 1),
        };
    }
}

/// <summary>خروجی: قالب، اندازه، قابِ مربعیِ فروشگاه، بزرگ‌نماییِ هوشمند.</summary>
public sealed class OutputSettings
{
    /// <summary>jpeg، png یا webp.</summary>
    public string Format { get; set; } = "jpeg";
    public int Quality { get; set; } = 90;
    /// <summary>ضلعِ بلندتر به پیکسل (۰ ⇒ همان اندازه).</summary>
    public int LongEdge { get; set; }
    /// <summary>قابِ مربع (مثلِ عکسِ فروشگاه): کالا وسط، با حاشیه.</summary>
    public bool Square { get; set; }
    /// <summary>حاشیهٔ دورِ کالا در قابِ مربع (۰ تا ۰٫۴).</summary>
    public double Padding { get; set; } = 0.06;
    /// <summary>بزرگ‌نماییِ هوشمند پیش از تغییرِ اندازه: ۱، ۲ یا ۴.</summary>
    public int Upscale { get; set; } = 1;
    /// <summary>شارپِ نهایی بعد از تغییرِ اندازه (۰ تا ۱۰۰).</summary>
    public double Sharpen { get; set; }

    internal OutputSettings Normalized()
    {
        var f = (Format ?? "jpeg").Trim().ToLowerInvariant();
        f = f switch { "jpg" => "jpeg", "png" or "webp" or "jpeg" => f, _ => "jpeg" };
        return new OutputSettings
        {
            Format = f, Quality = Math.Clamp(Quality <= 0 ? 90 : Quality, 30, 100),
            LongEdge = LongEdge <= 0 ? 0 : Math.Clamp(LongEdge, 64, 8000), Square = Square,
            Padding = Math.Round(Math.Clamp(double.IsFinite(Padding) ? Padding : 0.06, 0, 0.4), 3),
            Upscale = Upscale >= 4 ? 4 : Upscale >= 2 ? 2 : 1,
            Sharpen = Math.Round(Math.Clamp(double.IsFinite(Sharpen) ? Sharpen : 0, 0, 100), 1),
        };
    }
}

public static class PhotoJson
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

public static class PhotoColor
{
    /// <summary>«#rgb» یا «#rrggbb» ⇒ (r,g,b) بینِ ۰ و ۱.</summary>
    public static bool TryParse(string? s, out (double R, double G, double B) c)
    {
        c = (1, 1, 1);
        s = s?.Trim().TrimStart('#') ?? "";
        if (s.Length == 3) s = string.Concat(s.Select(ch => new string(ch, 2)));
        if (s.Length != 6 || !int.TryParse(s, System.Globalization.NumberStyles.HexNumber, null, out var v)) return false;
        c = (((v >> 16) & 255) / 255.0, ((v >> 8) & 255) / 255.0, (v & 255) / 255.0);
        return true;
    }
}
