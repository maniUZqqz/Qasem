using OpenCvSharp;

namespace PersianAiKit.Photo.Engine;

/// <summary>تعادلِ سفیدی، نوردهی و همهٔ منحنی‌های سراسری (سطوح، سفید/سیاه، کنتراست، روشنیِ میانه، منحنیِ تُن).</summary>
internal static unsafe class Tone
{
    private const int LutSize = 4096;
    private static readonly float[] Decode = BuildDecode();

    private static float[] BuildDecode()
    {
        var d = new float[LutSize + 1];
        for (int i = 0; i <= LutSize; i++) d[i] = MathF.Pow(i / (float)LutSize, 2.2f);
        return d;
    }

    /// <summary>ضریبِ کانال‌ها از دما و ته‌رنگ (در فضای خطی). روشنایی ثابت می‌ماند. دمای ±۱۰۰ ⇒ نسبتِ آبی به قرمز ×۳٫۳ (نورِ لامپِ رشته‌ای تا روزِ ابری).</summary>
    public static (double B, double G, double R) WhiteBalanceGains(double temperature, double tint)
    {
        double t = temperature / 100, ti = tint / 100;
        double gr = Math.Exp(0.6 * t + 0.125 * ti), gb = Math.Exp(-0.6 * t + 0.125 * ti), gg = Math.Exp(-0.25 * ti);
        var norm = 1 / (Px.Wr * gr + Px.Wg * gg + Px.Wb * gb);
        return (gb * norm, gg * norm, gr * norm);
    }

    /// <summary>عکسِ «خنثی‌سازِ» یک رنگِ خاکستری (میانگینِ خطیِ R,G,B) ⇒ دما و ته‌رنگ.</summary>
    public static (double Temperature, double Tint) NeutralizeToTempTint(double r, double g, double b)
    {
        r = Math.Max(r, 1e-6); g = Math.Max(g, 1e-6); b = Math.Max(b, 1e-6);
        var t = Math.Log(b / r) / 1.2 * 100;
        var ti = Math.Log(g / Math.Sqrt(r * b)) / 0.375 * 100;
        return (t, ti);
    }

    public static void WhiteBalanceExposure(Mat bgr, Recipe r)
    {
        double temp = r.Get("temperature"), tint = r.Get("tint"), ev = r.Get("exposure");
        if (temp == 0 && tint == 0 && ev == 0) return;
        var (gb, gg, gr) = WhiteBalanceGains(temp, tint);
        var e = Math.Pow(2, ev);
        float kB = (float)(gb * e), kG = (float)(gg * e), kR = (float)(gr * e);
        bool shoulder = Math.Max(kB, Math.Max(kG, kR)) > 1.0001f;
        const float inv = 1 / 2.2f;
        int w = bgr.Cols;
        Parallel.For(0, bgr.Rows, y =>
        {
            float* p = (float*)bgr.Ptr(y);
            for (int x = 0; x < w; x++, p += 3)
            {
                p[0] = Encode(Px.Lookup(Decode, p[0], LutSize) * kB, inv, shoulder);
                p[1] = Encode(Px.Lookup(Decode, p[1], LutSize) * kG, inv, shoulder);
                p[2] = Encode(Px.Lookup(Decode, p[2], LutSize) * kR, inv, shoulder);
            }
        });
    }

    private static float Encode(float lin, float inv, bool shoulder)
    {
        var v = lin <= 0 ? 0 : MathF.Pow(lin, inv);
        // شانهٔ نرم: روشن‌ترها به‌جای بریدن آرام به سفید می‌رسند
        return shoulder && v > 0.9f ? 0.9f + 0.1f * (1 - MathF.Exp(-(v - 0.9f) / 0.1f)) : v;
    }

    /// <summary>سطوح ⇒ سفید/سیاه ⇒ کنتراست ⇒ روشنیِ میانه ⇒ منحنیِ RGB ⇒ منحنیِ هر کانال، همه در یک جدول.</summary>
    public static void ApplyCurves(Mat bgr, Recipe r)
    {
        var baseLut = BuildBase(r, out var baseIdentity);
        var c = r.Curve;
        var rgb = c?.Rgb is { } pr ? Spline(pr) : null;
        if (baseIdentity && rgb is null && c?.Red is null && c?.Green is null && c?.Blue is null) return;
        float[] Chan(double[][]? pts)
        {
            var s = pts is null ? null : Spline(pts);
            var lut = new float[LutSize + 1];
            for (int i = 0; i <= LutSize; i++)
            {
                double v = baseLut[i];
                if (rgb is not null) v = rgb(v);
                if (s is not null) v = s(v);
                lut[i] = (float)Math.Clamp(v, 0, 1);
            }
            return lut;
        }
        Px.ApplyLut(bgr, Chan(c?.Blue), Chan(c?.Green), Chan(c?.Red));
    }

    private static double[] BuildBase(Recipe r, out bool identity)
    {
        double lb = r.Get("levelsBlack") / 255, lw = r.Get("levelsWhite") / 255, g = r.Get("levelsGamma");
        if (lw < lb + 0.02) lw = Math.Min(1, lb + 0.02);
        double blacks = r.Get("blacks") / 100, whites = r.Get("whites") / 100, contrast = r.Get("contrast") / 100,
               bright = r.Get("brightness") / 100;
        identity = lb == 0 && lw == 1 && g == 1 && blacks == 0 && whites == 0 && contrast == 0 && bright == 0;
        var lut = new double[LutSize + 1];
        double ib = -blacks * 0.12, iw = 1 - whites * 0.12;
        double a = contrast > 0 ? contrast * 0.45 : contrast * 0.6;
        double gamma = Math.Pow(2, -bright * 0.8);
        for (int i = 0; i <= LutSize; i++)
        {
            double x = i / (double)LutSize;
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
}
