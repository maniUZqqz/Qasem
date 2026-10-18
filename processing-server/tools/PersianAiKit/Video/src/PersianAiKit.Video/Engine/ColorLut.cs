using System.Globalization;
using System.Security.Cryptography;
using System.Text;

namespace PersianAiKit.Video.Engine;

/// <summary>
/// همهٔ ابزارهای «نقطه‌ای»ِ رنگ و نور (تعادلِ سفیدی، نوردهی، روشنی‌ها/سایه‌ها، سطوح، کنتراست، منحنی‌ها، HSL، وایبرنس، اشباع، رنگ‌دهی،
/// LUTِ ورودی و لوک) در یک LUTِ سه‌بعدیِ ۳۳×۳۳×۳۳ (.cube) خلاصه می‌شوند — دقیقاً کاری که لومتریِ پریمیر می‌کند —
/// و ffmpeg (lut3d، درون‌یابیِ چهاروجهی) روی هر فریم اجرا می‌کند. ریاضی همان ویرایشگرِ عکس است ⇒ عکس و ویدیو یک رنگ دارند.
/// روشنی‌ها/سایه‌ها این‌جا سراسری‌اند (روی روشناییِ خودِ پیکسل)، نه لبه‌آگاه مثلِ عکس.
/// </summary>
public static class ColorLut
{
    public const int Size = 33;
    private const float Wr = 0.2126f, Wg = 0.7152f, Wb = 0.0722f;
    private const int N = 4096;

    /// <summary>آیا نسخه چیزی دارد که در LUT برود؟</summary>
    public static bool Needed(VideoRecipe r) =>
        r.Adjust.Keys.Any(k => ToolCatalog.InLut(k) && r.Has(k)) || r.Curve is not null || r.Lut is not null;

    /// <summary>نامِ فایلِ LUT برای این نسخه (فقط بخش‌های رنگ ⇒ لغزندهٔ صدا LUT را دوباره نمی‌سازد).</summary>
    public static string Key(VideoRecipe r, string? lutFileHash)
    {
        var sb = new StringBuilder();
        foreach (var (k, v) in r.Adjust.OrderBy(k => k.Key, StringComparer.Ordinal))
            if (ToolCatalog.InLut(k)) sb.Append(k).Append('=').Append(v.ToString(CultureInfo.InvariantCulture)).Append(';');
        if (r.Curve is not null) sb.Append(System.Text.Json.JsonSerializer.Serialize(r.Curve, VideoJson.Options));
        if (r.Lut is not null) sb.Append(r.Lut.File).Append(r.Lut.Mode).Append(r.Lut.Amount.ToString(CultureInfo.InvariantCulture)).Append(lutFileHash);
        return Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(sb.ToString())))[..16].ToLowerInvariant();
    }

    /// <summary>LUTِ نسخه را در <paramref name="path"/> می‌نویسد. <paramref name="userLut"/> = فایلِ .cubeِ کاربر (اگر نسخه دارد).</summary>
    public static void Write(VideoRecipe r, string path, CubeLut? userLut = null)
    {
        var ctx = new Ctx(r, userLut);
        var sb = new StringBuilder(Size * Size * Size * 26);
        sb.Append("TITLE \"PersianAiKit.Video\"\nLUT_3D_SIZE ").Append(Size).Append("\nDOMAIN_MIN 0 0 0\nDOMAIN_MAX 1 1 1\n");
        var ci = CultureInfo.InvariantCulture;
        for (int b = 0; b < Size; b++)
            for (int g = 0; g < Size; g++)
                for (int rr = 0; rr < Size; rr++)
                {
                    var (vr, vg, vb) = ctx.Apply(rr / (float)(Size - 1), g / (float)(Size - 1), b / (float)(Size - 1));
                    sb.Append(Math.Clamp(vr, 0f, 1f).ToString("0.######", ci)).Append(' ')
                      .Append(Math.Clamp(vg, 0f, 1f).ToString("0.######", ci)).Append(' ')
                      .Append(Math.Clamp(vb, 0f, 1f).ToString("0.######", ci)).Append('\n');
                }
        var tmp = path + ".tmp";
        File.WriteAllText(tmp, sb.ToString(), new UTF8Encoding(false));
        File.Move(tmp, path, true);
    }

    /// <summary>یک رنگ (۰ تا ۱) از همان زنجیره — برای آزمون و پیش‌بینی.</summary>
    public static (float R, float G, float B) Apply(VideoRecipe r, float red, float green, float blue, CubeLut? userLut = null) =>
        new Ctx(r, userLut).Apply(red, green, blue);

    private sealed class Ctx
    {
        private readonly float kR, kG, kB;
        private readonly bool wb, shoulder;
        private readonly float sh, hl;
        private readonly float[]? lutR, lutG, lutB;
        private readonly float[] dh = new float[9], ds = new float[9], dl = new float[9];
        private readonly bool hsl;
        private readonly float vib, sat, shS, hiS, bal;
        private readonly (float R, float G, float B) shT, hiT;
        private readonly CubeLut? input, look;
        private readonly float lookAmount;
        private static readonly float[] Centers = { 0, 30, 60, 120, 180, 240, 270, 300, 360 };

        public Ctx(VideoRecipe r, CubeLut? userLut)
        {
            if (userLut is not null && r.Lut is { } l)
            {
                if (l.Mode == "input") input = userLut;
                else { look = userLut; lookAmount = (float)(l.Amount / 100); }
            }
            // تعادلِ سفیدی و نوردهی (فضای خطی)
            double t = r.Get("temperature") / 100, ti = r.Get("tint") / 100, ev = r.Get("exposure");
            wb = t != 0 || ti != 0 || ev != 0;
            double gr = Math.Exp(0.6 * t + 0.125 * ti), gb = Math.Exp(-0.6 * t + 0.125 * ti), gg = Math.Exp(-0.25 * ti);
            var norm = 1 / (Wr * gr + Wg * gg + Wb * gb);
            var e = Math.Pow(2, ev);
            kR = (float)(gr * norm * e); kG = (float)(gg * norm * e); kB = (float)(gb * norm * e);
            shoulder = Math.Max(kR, Math.Max(kG, kB)) > 1.0001f;
            sh = (float)(r.Get("shadows") / 100); hl = (float)(r.Get("highlights") / 100);
            // منحنی‌ها
            var baseLut = BuildBase(r, out var baseIdentity);
            var c = r.Curve;
            if (!(baseIdentity && c is null))
            {
                var rgb = c?.Rgb is { } pr ? Spline(pr) : null;
                float[] Chan(double[][]? pts)
                {
                    var s = pts is null ? null : Spline(pts);
                    var lut = new float[N + 1];
                    for (int i = 0; i <= N; i++)
                    {
                        double v = baseLut[i];
                        if (rgb is not null) v = rgb(v);
                        if (s is not null) v = s(v);
                        lut[i] = (float)Math.Clamp(v, 0, 1);
                    }
                    return lut;
                }
                lutR = Chan(c?.Red); lutG = Chan(c?.Green); lutB = Chan(c?.Blue);
            }
            // رنگ
            var bands = ToolCatalog.HslBands;
            for (int i = 0; i < 8; i++)
            {
                dh[i] = (float)(r.Get(bands[i].Key + "Hue") / 100 * 30);
                ds[i] = (float)(r.Get(bands[i].Key + "Sat") / 100);
                dl[i] = (float)(r.Get(bands[i].Key + "Lum") / 100);
                hsl |= dh[i] != 0 || ds[i] != 0 || dl[i] != 0;
            }
            dh[8] = dh[0]; ds[8] = ds[0]; dl[8] = dl[0];
            vib = (float)(r.Get("vibrance") / 100); sat = (float)(r.Get("saturation") / 100);
            shS = (float)(r.Get("shadowsSat") / 100); hiS = (float)(r.Get("highlightsSat") / 100); bal = (float)(r.Get("gradingBalance") / 100);
            shT = TintDirection(r.Get("shadowsHue"));
            hiT = TintDirection(r.Get("highlightsHue"));
        }

        public (float, float, float) Apply(float r, float g, float b)
        {
            if (input is not null) (r, g, b) = input.Sample(r, g, b);
            if (wb)
            {
                r = Encode(MathF.Pow(r, 2.2f) * kR); g = Encode(MathF.Pow(g, 2.2f) * kG); b = Encode(MathF.Pow(b, 2.2f) * kB);
            }
            if (sh != 0 || hl != 0)
            {
                var y = Wr * r + Wg * g + Wb * b;
                if (y > 1e-4f)
                {
                    var bb = Math.Clamp(y, 0f, 1f);
                    var ws = 1 - Smoothstep(0f, 0.6f, bb);
                    var wh = Smoothstep(0.4f, 1f, bb);
                    var v = y * MathF.Pow(2, sh * 1.3f * ws + hl * wh);
                    v = v > 0.95f ? 0.95f + 0.05f * (1 - MathF.Exp(-(v - 0.95f) / 0.05f)) : v;
                    var k = v / y;
                    r *= k; g *= k; b *= k;
                }
            }
            if (lutR is not null)
            {
                r = Lookup(lutR!, r); g = Lookup(lutG!, g); b = Lookup(lutB!, b);
            }
            (r, g, b) = Color(Math.Clamp(r, 0f, 1f), Math.Clamp(g, 0f, 1f), Math.Clamp(b, 0f, 1f));
            if (look is not null)
            {
                var (lr, lg, lb) = look.Sample(Math.Clamp(r, 0f, 1f), Math.Clamp(g, 0f, 1f), Math.Clamp(b, 0f, 1f));
                r += (lr - r) * lookAmount; g += (lg - g) * lookAmount; b += (lb - b) * lookAmount;
            }
            return (r, g, b);
        }

        private float Encode(float lin)
        {
            var v = lin <= 0 ? 0 : MathF.Pow(lin, 1 / 2.2f);
            return shoulder && v > 0.9f ? 0.9f + 0.1f * (1 - MathF.Exp(-(v - 0.9f) / 0.1f)) : v;
        }

        private (float, float, float) Color(float rr, float g, float b)
        {
            bool grading = shS > 0 || hiS > 0;
            if (hsl || vib != 0 || sat != 0)
            {
                ToHsv(rr, g, b, out var h, out var s, out var v);
                if (hsl && s > 0.001f)
                {
                    int i = 0;
                    while (i < 7 && h >= Centers[i + 1]) i++;
                    var t = (h - Centers[i]) / (Centers[i + 1] - Centers[i]);
                    float W(float[] a) => a[i] * (1 - t) + a[i + 1] * t;
                    h += W(dh);
                    if (h < 0) h += 360; else if (h >= 360) h -= 360;
                    s = Math.Clamp(s * (1 + W(ds)), 0f, 1f);
                    v = Math.Clamp(v * (1 + W(dl) * 0.6f * Math.Min(1, s * 1.5f)), 0f, 1f);
                }
                if (vib != 0)
                {
                    var skin = h > 5 && h < 50 ? 0.5f + 0.5f * Math.Abs(h - 27.5f) / 22.5f : 1f;
                    s = Math.Clamp(s * (1 + vib * (1 - s) * (vib > 0 ? skin : 1)), 0f, 1f);
                }
                if (sat > 0) s = Math.Clamp(s * (1 + sat), 0f, 1f);
                FromHsv(h, s, v, out rr, out g, out b);
                if (sat < 0)
                {
                    var l = Wr * rr + Wg * g + Wb * b;
                    var k = 1 + sat;
                    rr = l + (rr - l) * k; g = l + (g - l) * k; b = l + (b - l) * k;
                }
            }
            if (grading)
            {
                var l = Wr * rr + Wg * g + Wb * b;
                var ws = 1 - Smoothstep(0f, 0.6f + 0.3f * bal, l);
                var wh = Smoothstep(0.4f + 0.3f * bal, 1f, l);
                var ks = shS * 0.3f * ws; var kh = hiS * 0.3f * wh;
                rr += shT.R * ks + hiT.R * kh;
                g += shT.G * ks + hiT.G * kh;
                b += shT.B * ks + hiT.B * kh;
            }
            return (rr, g, b);
        }
    }

    // ───────────── منحنی‌ها (مثلِ Tone.cs در ویرایشگرِ عکس) ─────────────

    private static double[] BuildBase(VideoRecipe r, out bool identity)
    {
        double lb = r.Get("levelsBlack") / 255, lw = r.Get("levelsWhite") / 255, g = r.Get("levelsGamma");
        if (lw < lb + 0.02) lw = Math.Min(1, lb + 0.02);
        double blacks = r.Get("blacks") / 100, whites = r.Get("whites") / 100, contrast = r.Get("contrast") / 100, bright = r.Get("brightness") / 100;
        identity = lb == 0 && lw == 1 && g == 1 && blacks == 0 && whites == 0 && contrast == 0 && bright == 0;
        var lut = new double[N + 1];
        double ib = -blacks * 0.12, iw = 1 - whites * 0.12;
        double a = contrast > 0 ? contrast * 0.45 : contrast * 0.6;
        double gamma = Math.Pow(2, -bright * 0.8);
        for (int i = 0; i <= N; i++)
        {
            double x = i / (double)N;
            x = Math.Pow(Math.Clamp((x - lb) / (lw - lb), 0, 1), 1 / g);
            x = Math.Clamp((x - ib) / (iw - ib), 0, 1);
            x += a * 4 * (x - 0.5) * x * (1 - x);
            x = Math.Pow(Math.Clamp(x, 0, 1), gamma);
            lut[i] = x;
        }
        return lut;
    }

    /// <summary>منحنیِ نرم و یکنوا از نقاط (Fritsch–Carlson): ورودی و خروجی بینِ ۰ و ۱.</summary>
    public static Func<double, double> Spline(double[][] pts)
    {
        var p = pts.OrderBy(q => q[0]).Select(q => (X: q[0] / 255, Y: q[1] / 255)).ToArray();
        int n = p.Length;
        if (n == 1) return _ => p[0].Y;
        var d = new double[n - 1];
        for (int i = 0; i < n - 1; i++) d[i] = (p[i + 1].Y - p[i].Y) / Math.Max(1e-9, p[i + 1].X - p[i].X);
        var m = new double[n];
        m[0] = d[0]; m[n - 1] = d[n - 2];
        for (int i = 1; i < n - 1; i++) m[i] = d[i - 1] * d[i] <= 0 ? 0 : (d[i - 1] + d[i]) / 2;
        for (int i = 0; i < n - 1; i++)
        {
            if (d[i] == 0) { m[i] = 0; m[i + 1] = 0; continue; }
            double a = m[i] / d[i], b = m[i + 1] / d[i], h = a * a + b * b;
            if (h > 9) { var t = 3 / Math.Sqrt(h); m[i] = t * a * d[i]; m[i + 1] = t * b * d[i]; }
        }
        return x =>
        {
            if (x <= p[0].X) return p[0].Y;
            if (x >= p[n - 1].X) return p[n - 1].Y;
            int k = 0;
            while (k < n - 2 && x > p[k + 1].X) k++;
            double h = p[k + 1].X - p[k].X, t = (x - p[k].X) / h, t2 = t * t, t3 = t2 * t;
            return (2 * t3 - 3 * t2 + 1) * p[k].Y + (t3 - 2 * t2 + t) * h * m[k] + (-2 * t3 + 3 * t2) * p[k + 1].Y + (t3 - t2) * h * m[k + 1];
        };
    }

    private static float Lookup(float[] lut, float v)
    {
        if (!(v > 0)) return lut[0];
        if (v >= 1) return lut[N];
        var f = v * N;
        var i = (int)f;
        var t = f - i;
        return lut[i] + (lut[i + 1] - lut[i]) * t;
    }

    private static float Smoothstep(float e0, float e1, float x)
    {
        var t = Math.Clamp((x - e0) / (e1 - e0), 0f, 1f);
        return t * t * (3 - 2 * t);
    }

    private static (float R, float G, float B) TintDirection(double hue)
    {
        FromHsv((float)(hue % 360), 1, 1, out var r, out var g, out var b);
        var l = Wr * r + Wg * g + Wb * b;
        return (r - l, g - l, b - l);
    }

    private static void ToHsv(float r, float g, float b, out float h, out float s, out float v)
    {
        var max = Math.Max(r, Math.Max(g, b));
        var min = Math.Min(r, Math.Min(g, b));
        var d = max - min;
        v = max;
        s = max > 1e-6f ? d / max : 0;
        if (d < 1e-6f) { h = 0; return; }
        if (max == r) h = 60 * ((g - b) / d);
        else if (max == g) h = 60 * ((b - r) / d + 2);
        else h = 60 * ((r - g) / d + 4);
        if (h < 0) h += 360;
    }

    private static void FromHsv(float h, float s, float v, out float r, out float g, out float b)
    {
        if (s <= 0) { r = g = b = v; return; }
        h = (h % 360 + 360) % 360 / 60;
        int i = (int)h;
        var f = h - i;
        float p = v * (1 - s), q = v * (1 - s * f), t = v * (1 - s * (1 - f));
        switch (i)
        {
            case 0: r = v; g = t; b = p; break;
            case 1: r = q; g = v; b = p; break;
            case 2: r = p; g = v; b = t; break;
            case 3: r = p; g = q; b = v; break;
            case 4: r = t; g = p; b = v; break;
            default: r = v; g = p; b = q; break;
        }
    }
}

/// <summary>یک LUTِ سه‌بعدیِ .cube (Adobe/Resolve) — خواندن و نمونه‌برداری با درون‌یابیِ سه‌خطی.</summary>
public sealed class CubeLut
{
    private readonly float[] _data;
    public int Size { get; }
    private readonly float _min0, _min1, _min2, _max0, _max1, _max2;

    private CubeLut(int size, float[] data, float[] min, float[] max)
    {
        Size = size; _data = data;
        (_min0, _min1, _min2) = (min[0], min[1], min[2]);
        (_max0, _max1, _max2) = (max[0], max[1], max[2]);
    }

    public static CubeLut Parse(string text)
    {
        int size = 0;
        var min = new[] { 0f, 0f, 0f };
        var max = new[] { 1f, 1f, 1f };
        var values = new List<float>();
        var ci = CultureInfo.InvariantCulture;
        foreach (var raw in text.Split('\n'))
        {
            var line = raw.Trim();
            if (line.Length == 0 || line[0] == '#') continue;
            var p = line.Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries);
            switch (p[0].ToUpperInvariant())
            {
                case "TITLE": continue;
                case "LUT_1D_SIZE": throw new InvalidDataException("فقط LUTِ سه‌بعدی (LUT_3D_SIZE) پشتیبانی می‌شود.");
                case "LUT_3D_SIZE": size = int.Parse(p[1], ci); continue;
                case "DOMAIN_MIN": for (int i = 0; i < 3; i++) min[i] = float.Parse(p[i + 1], ci); continue;
                case "DOMAIN_MAX": for (int i = 0; i < 3; i++) max[i] = float.Parse(p[i + 1], ci); continue;
            }
            if (p.Length >= 3 && float.TryParse(p[0], NumberStyles.Float, ci, out var a) &&
                float.TryParse(p[1], NumberStyles.Float, ci, out var b) && float.TryParse(p[2], NumberStyles.Float, ci, out var c))
            { values.Add(a); values.Add(b); values.Add(c); }
        }
        if (size is < 2 or > 129) throw new InvalidDataException("فایلِ .cube اندازهٔ درست (LUT_3D_SIZE) ندارد.");
        if (values.Count != size * size * size * 3) throw new InvalidDataException($"فایلِ .cube ناقص است ({values.Count / 3} از {size * size * size} رنگ).");
        return new CubeLut(size, values.ToArray(), min, max);
    }

    public (float R, float G, float B) Sample(float r, float g, float b)
    {
        float fr = Math.Clamp((r - _min0) / (_max0 - _min0), 0f, 1f) * (Size - 1);
        float fg = Math.Clamp((g - _min1) / (_max1 - _min1), 0f, 1f) * (Size - 1);
        float fb = Math.Clamp((b - _min2) / (_max2 - _min2), 0f, 1f) * (Size - 1);
        int r0 = Math.Min((int)fr, Size - 2), g0 = Math.Min((int)fg, Size - 2), b0 = Math.Min((int)fb, Size - 2);
        float tr = fr - r0, tg = fg - g0, tb = fb - b0;
        float R = 0, G = 0, B = 0;
        for (int k = 0; k < 8; k++)
        {
            int dr = k & 1, dg = (k >> 1) & 1, db = (k >> 2) & 1;
            var w = (dr == 1 ? tr : 1 - tr) * (dg == 1 ? tg : 1 - tg) * (db == 1 ? tb : 1 - tb);
            if (w == 0) continue;
            var i = (((b0 + db) * Size + (g0 + dg)) * Size + (r0 + dr)) * 3;
            R += w * _data[i]; G += w * _data[i + 1]; B += w * _data[i + 2];
        }
        return (R, G, B);
    }
}
