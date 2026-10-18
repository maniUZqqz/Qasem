using OpenCvSharp;

namespace PersianAiKit.Photo.Engine;

/// <summary>وایبرنس، اشباع، رنگ‌به‌رنگ (HSL) و رنگ‌دهیِ سایه/روشنی — هر پیکسل در فضای HSV.</summary>
internal static unsafe class ColorOps
{
    private static readonly float[] Centers = { 0, 30, 60, 120, 180, 240, 270, 300, 360 };

    public static void Apply(Mat bgr, Recipe r)
    {
        var bands = ToolCatalog.HslBands;
        var dh = new float[9]; var ds = new float[9]; var dl = new float[9];
        bool hsl = false;
        for (int i = 0; i < 8; i++)
        {
            dh[i] = (float)(r.Get(bands[i].Key + "Hue") / 100 * 30);
            ds[i] = (float)(r.Get(bands[i].Key + "Sat") / 100);
            dl[i] = (float)(r.Get(bands[i].Key + "Lum") / 100);
            hsl |= dh[i] != 0 || ds[i] != 0 || dl[i] != 0;
        }
        dh[8] = dh[0]; ds[8] = ds[0]; dl[8] = dl[0];   // ۳۶۰ درجه = قرمز
        float vib = (float)(r.Get("vibrance") / 100), sat = (float)(r.Get("saturation") / 100);
        float shS = (float)(r.Get("shadowsSat") / 100), hiS = (float)(r.Get("highlightsSat") / 100), bal = (float)(r.Get("gradingBalance") / 100);
        bool grading = shS > 0 || hiS > 0;
        if (!hsl && vib == 0 && sat == 0 && !grading) return;
        var shT = TintDirection(r.Get("shadowsHue"));
        var hiT = TintDirection(r.Get("highlightsHue"));

        int w = bgr.Cols;
        Parallel.For(0, bgr.Rows, y =>
        {
            float* p = (float*)bgr.Ptr(y);
            for (int x = 0; x < w; x++, p += 3)
            {
                float b = Math.Clamp(p[0], 0f, 1f), g = Math.Clamp(p[1], 0f, 1f), rr = Math.Clamp(p[2], 0f, 1f);
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
                        // پوست (فامِ ۱۰ تا ۴۵ درجه) نصفِ بقیه تقویت می‌شود تا صورت نارنجی نشود
                        var skin = h > 5 && h < 50 ? 0.5f + 0.5f * Math.Abs(h - 27.5f) / 22.5f : 1f;
                        s = Math.Clamp(s * (1 + vib * (1 - s) * (vib > 0 ? skin : 1)), 0f, 1f);
                    }
                    if (sat > 0) s = Math.Clamp(s * (1 + sat), 0f, 1f);
                    FromHsv(h, s, v, out rr, out g, out b);
                    if (sat < 0)
                    {
                        // کم کردن رو به روشنایی (نه رو به V): اشباعِ −۱۰۰ ⇒ سیاه‌وسفیدِ درست. HSL (روشناییِ هر رنگ) پیش از این آمده ⇒ میکسرِ سیاه‌وسفید
                        var l = Px.Wr * rr + Px.Wg * g + Px.Wb * b;
                        var k = 1 + sat;
                        rr = l + (rr - l) * k; g = l + (g - l) * k; b = l + (b - l) * k;
                    }
                }
                if (grading)
                {
                    var l = Px.Wr * rr + Px.Wg * g + Px.Wb * b;
                    var ws = 1 - Px.Smoothstep(0f, 0.6f + 0.3f * bal, l);
                    var wh = Px.Smoothstep(0.4f + 0.3f * bal, 1f, l);
                    var ks = shS * 0.3f * ws; var kh = hiS * 0.3f * wh;
                    rr += shT.R * ks + hiT.R * kh;
                    g += shT.G * ks + hiT.G * kh;
                    b += shT.B * ks + hiT.B * kh;
                }
                p[0] = b; p[1] = g; p[2] = rr;
            }
        });
    }

    /// <summary>جهتِ رنگ برای یک فام (بی تغییرِ روشنایی).</summary>
    private static (float R, float G, float B) TintDirection(double hue)
    {
        FromHsv((float)(hue % 360), 1, 1, out var r, out var g, out var b);
        var l = Px.Wr * r + Px.Wg * g + Px.Wb * b;
        return (r - l, g - l, b - l);
    }

    public static void ToHsv(float r, float g, float b, out float h, out float s, out float v)
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

    public static void FromHsv(float h, float s, float v, out float r, out float g, out float b)
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
