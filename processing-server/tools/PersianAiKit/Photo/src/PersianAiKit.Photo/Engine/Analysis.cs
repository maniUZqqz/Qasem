using System.Globalization;
using OpenCvSharp;

namespace PersianAiKit.Photo.Engine;

/// <summary>اندازه‌گیری‌های یک عکس — برای تنظیمِ خودکار و برای هوشِ مصنوعی (متنِ کوتاه به‌جای عکسِ بزرگ ⇒ ارزان‌تر).</summary>
public sealed record PhotoStats
{
    public int Width { get; init; }
    public int Height { get; init; }
    public bool HasAlpha { get; init; }
    /// <summary>روشنایی (۰ تا ۱): میانگین و صدک‌ها.</summary>
    public double Mean { get; init; }
    public double P1 { get; init; }
    public double P5 { get; init; }
    public double P50 { get; init; }
    public double P95 { get; init; }
    public double P99 { get; init; }
    /// <summary>درصدِ پیکسل‌های سیاهِ کامل / سوخته.</summary>
    public double ClipShadows { get; init; }
    public double ClipHighlights { get; init; }
    /// <summary>انحرافِ معیارِ روشنایی (کنتراستِ کلی).</summary>
    public double Contrast { get; init; }
    public double Saturation { get; init; }
    /// <summary>دما و ته‌رنگی که رنگ‌های خنثی را خنثی می‌کند (۰ ⇒ ته‌رنگ ندارد).</summary>
    public double CastTemperature { get; init; }
    public double CastTint { get; init; }
    /// <summary>سهمِ پیکسل‌های تقریباً خاکستری (پایهٔ سنجشِ ته‌رنگ).</summary>
    public double NeutralShare { get; init; }
    /// <summary>واریانسِ لاپلاسین (بیشتر ⇒ تیزتر).</summary>
    public double Sharpness { get; init; }
    /// <summary>انحرافِ معیارِ نویز در مقیاسِ ۰ تا ۲۵۵.</summary>
    public double Noise { get; init; }
    /// <summary>حاشیهٔ عکس یکدست است (مثلِ عکسِ کالا روی زمینهٔ ساده).</summary>
    public bool PlainBackground { get; init; }
    public string BorderColor { get; init; } = "#ffffff";
    /// <summary>هیستوگرامِ ۱۶ خانه‌ایِ روشنایی (درصد).</summary>
    public double[] Histogram { get; init; } = Array.Empty<double>();

    /// <summary>خلاصهٔ انگلیسی برای مدلِ زبانی (کوتاه = ارزان).</summary>
    public string Describe()
    {
        var ci = CultureInfo.InvariantCulture;
        string F(double v, string f = "0.000") => v.ToString(f, ci);
        return string.Join("\n", new[]
        {
            $"size {Width}x{Height}{(HasAlpha ? ", has transparency" : "")}",
            $"luminance 0..1: mean {F(Mean)}, p1 {F(P1)}, p5 {F(P5)}, median {F(P50)}, p95 {F(P95)}, p99 {F(P99)}, std {F(Contrast)}",
            $"clipped: shadows {F(ClipShadows, "0.0")}%, highlights {F(ClipHighlights, "0.0")}%",
            $"mean saturation {F(Saturation)}; neutral pixels {F(NeutralShare, "0.0")}%; white-balance fix that neutralizes grays: temperature {F(CastTemperature, "0")}, tint {F(CastTint, "0")}",
            $"sharpness(laplacian var) {F(Sharpness, "0.00000")}; noise sigma {F(Noise, "0.0")}/255",
            $"plain uniform border/background: {(PlainBackground ? "yes, color " + BorderColor : "no")}",
            "histogram(16 bins %): " + string.Join(" ", Histogram.Select(h => h.ToString("0.#", ci))),
        });
    }
}

/// <summary>نتیجهٔ تنظیمِ خودکار: نسخهٔ ویرایش + توضیحِ فارسیِ هر کار.</summary>
public sealed record AutoResult(Recipe Recipe, IReadOnlyList<string> Notes);

public static unsafe class Analysis
{
    public static PhotoStats Measure(PhotoImage full)
    {
        using var img = full.Downscaled(800);
        using var y = Px.Luma(img.Color);
        var p = Px.Percentiles(y, 1, 5, 50, 95, 99);
        Cv2.MeanStdDev(y, out var mean, out var std);

        long clipS = 0, clipH = 0, n = (long)y.Rows * y.Cols;
        double satSum = 0, wr = 0, wg = 0, wb = 0; long mid = 0;
        var hist = new double[16];
        // گذرِ ۱: میانگینِ رنگِ میانه‌ها (دنیای خاکستری) — ته‌رنگِ کلیِ عکس
        for (int r = 0; r < img.Height; r++)
        {
            float* c = (float*)img.Color.Ptr(r);
            float* py = (float*)y.Ptr(r);
            for (int x = 0; x < img.Width; x++, c += 3)
            {
                float b = c[0], g = c[1], rr = c[2], l = py[x];
                if (l < 0.01f) clipS++;
                if (Math.Max(rr, Math.Max(g, b)) > 0.99f) clipH++;
                hist[Math.Clamp((int)(l * 16), 0, 15)]++;
                var max = Math.Max(rr, Math.Max(g, b)); var min = Math.Min(rr, Math.Min(g, b));
                satSum += max > 1e-4f ? (max - min) / max : 0;
                if (l > 0.12f && l < 0.92f && max < 0.98f)
                {
                    mid++;
                    wr += MathF.Pow(rr, 2.2f); wg += MathF.Pow(g, 2.2f); wb += MathF.Pow(b, 2.2f);
                }
            }
        }
        // گذرِ ۲: پیکسل‌هایی که بعد از برداشتنِ آن ته‌رنگ خاکستری‌اند (در ته‌رنگِ شدید، خاکستریِ واقعی دیگر خاکستری دیده نمی‌شود)
        double nr = 0, ng = 0, nb = 0; long neutral = 0;
        if (mid > 0)
        {
            float kr = (float)(wg / Math.Max(wr, 1e-9)), kb = (float)(wg / Math.Max(wb, 1e-9));
            for (int r = 0; r < img.Height; r++)
            {
                float* c = (float*)img.Color.Ptr(r);
                float* py = (float*)y.Ptr(r);
                for (int x = 0; x < img.Width; x++, c += 3)
                {
                    var l = py[x];
                    if (l <= 0.12f || l >= 0.92f) continue;
                    // رنگِ خیلی پررنگ (چمن، آسمان) خاکستریِ ته‌رنگ‌دار نیست
                    var amax = Math.Max(c[2], Math.Max(c[1], c[0])); var amin = Math.Min(c[2], Math.Min(c[1], c[0]));
                    if (amax > 1e-4f && (amax - amin) / amax > 0.5f) continue;
                    float lb = MathF.Pow(c[0], 2.2f), lg = MathF.Pow(c[1], 2.2f), lr = MathF.Pow(c[2], 2.2f);
                    float cb = lb * kb, cr = lr * kr;
                    var max = Math.Max(cr, Math.Max(lg, cb)); var min = Math.Min(cr, Math.Min(lg, cb));
                    if (max > 1e-5f && (max - min) / max < 0.2f) { neutral++; nr += lr; ng += lg; nb += lb; }
                }
            }
        }
        double castT = 0, castTi = 0;
        if (neutral > n * 0.02)
            (castT, castTi) = Tone.NeutralizeToTempTint(nr / neutral, ng / neutral, nb / neutral);
        else if (mid > n * 0.2)   // خاکستری کم است ⇒ دنیای خاکستری، با احتیاط
        {
            (castT, castTi) = Tone.NeutralizeToTempTint(wr / mid, wg / mid, wb / mid);
            castT *= 0.5; castTi *= 0.5;
        }
        castT = Math.Clamp(castT, -100, 100); castTi = Math.Clamp(castTi, -100, 100);

        // حاشیه: یکدست بودن و رنگش
        int bw = Math.Max(2, (int)(Math.Min(img.Width, img.Height) * 0.04));
        using var border = new Mat(img.Height, img.Width, MatType.CV_8UC1, Scalar.All(255));
        using (var inner = new Mat(border, new Rect(bw, bw, Math.Max(1, img.Width - 2 * bw), Math.Max(1, img.Height - 2 * bw)))) inner.SetTo(Scalar.All(0));
        Cv2.MeanStdDev(img.Color, out var bMean, out var bStd, border);
        var plain = full.Alpha is null && Math.Max(bStd.Val0, Math.Max(bStd.Val1, bStd.Val2)) < 0.06;
        string Hex(double v) => ((int)Math.Round(Math.Clamp(v, 0, 1) * 255)).ToString("x2");

        return new PhotoStats
        {
            Width = full.Width, Height = full.Height, HasAlpha = full.Alpha is not null,
            Mean = mean.Val0, P1 = p[0], P5 = p[1], P50 = p[2], P95 = p[3], P99 = p[4], Contrast = std.Val0,
            ClipShadows = clipS * 100.0 / n, ClipHighlights = clipH * 100.0 / n,
            Saturation = satSum / n, CastTemperature = castT, CastTint = castTi, NeutralShare = neutral * 100.0 / n,
            Sharpness = LaplacianVariance(img.Color), Noise = NoiseSigma(full.Color),
            PlainBackground = plain, BorderColor = "#" + Hex(bMean.Val2) + Hex(bMean.Val1) + Hex(bMean.Val0),
            Histogram = hist.Select(h => Math.Round(h * 100 / n, 1)).ToArray(),
        };
    }

    /// <summary>
    /// تنظیمِ خودکارِ رایگان (بی هوشِ مصنوعی) — مثلِ Auto در Camera Raw ولی با قاعده: تعادلِ سفیدی از رنگ‌های خنثی،
    /// نوردهی تا میانه ~۰٫۴۶، سیاه و سفید تا دو سرِ هیستوگرام، روشنی‌ها/سایه‌ها اگر بریده‌اند، کمی وایبرنس و شارپ.
    /// </summary>
    public static AutoResult Auto(PhotoStats s)
    {
        var r = new Recipe();
        var notes = new List<string>();
        void Set(string k, double v) { v = Math.Round(ToolCatalog.Clamp(k, v), 2); if (Math.Abs(v - ToolCatalog.Default(k)) > 0.01) r.Adjust[k] = v; }

        if (s.NeutralShare > 1 && (Math.Abs(s.CastTemperature) > 6 || Math.Abs(s.CastTint) > 6))
        {
            // خاکستریِ کافی ⇒ اطمینان ⇒ تقریباً کامل؛ وگرنه (دنیای خاکستری) با احتیاط
            double wbK = s.NeutralShare > 5 ? 0.9 : 0.6, lim = s.NeutralShare > 5 ? 80 : 40;
            Set("temperature", Math.Clamp(s.CastTemperature * wbK, -lim, lim));
            Set("tint", Math.Clamp(s.CastTint * wbK, -lim, lim));
            notes.Add($"ته‌رنگ گرفته شد (دما {r.Get("temperature"):0}، ته‌رنگ {r.Get("tint"):0}).");
        }
        double ev = 0;
        if (!(s.PlainBackground && s.P50 > 0.6))
        {
            ev = Math.Clamp(2.2 * Math.Log2(0.46 / Math.Max(0.02, s.P50)) * 0.6, -1.2, 1.2);
            if (Math.Abs(ev) >= 0.15) { Set("exposure", ev); notes.Add(ev > 0 ? $"عکس تیره بود: نوردهی +{ev:0.0#}." : $"عکس روشن بود: نوردهی {ev:0.0#}."); }
            else ev = 0;
        }
        var k = Math.Pow(2, ev / 2.2);
        double p1 = Math.Min(1, s.P1 * k), p99 = Math.Min(1, s.P99 * k);
        if (p1 > 0.05) { Set("blacks", -Math.Clamp((p1 - 0.02) / 0.12 * 100, 0, 50)); notes.Add("سیاه‌ها عمیق‌تر (عکس کدر بود)."); }
        if (p99 < 0.92 && !s.PlainBackground) { Set("whites", Math.Clamp((0.97 - p99) / 0.12 * 80, 0, 40)); notes.Add("سفیدها روشن‌تر."); }
        if (s.ClipHighlights > 0.5 && !s.PlainBackground) { Set("highlights", -Math.Clamp(15 + s.ClipHighlights * 4, 0, 60)); notes.Add("جزئیاتِ بخش‌های سوخته برگردانده شد."); }
        if (s.P5 < 0.07 && s.Mean < 0.4) { Set("shadows", Math.Clamp((0.12 - s.P5) * 350, 0, 45)); notes.Add("سایه‌ها باز شد."); }
        if (s.Contrast < 0.16 && !s.PlainBackground) { Set("contrast", Math.Clamp((0.2 - s.Contrast) * 250, 0, 25)); notes.Add("کنتراست کمی بیشتر."); }
        if (s.P1 > 0.15 && s.Saturation < 0.25 && !s.PlainBackground) { Set("dehaze", Math.Clamp((s.P1 - 0.1) * 150, 0, 30)); notes.Add("مه‌زدایی."); }
        if (s.Saturation < 0.22) { Set("vibrance", Math.Clamp((0.3 - s.Saturation) * 120, 0, 25)); notes.Add("رنگ‌ها کمی زنده‌تر (وایبرنس)."); }
        if (s.Noise > 2.5)
        {
            Set("noiseLuma", Math.Clamp((s.Noise - 2) * 8, 0, 60));
            Set("noiseColor", 25);
            notes.Add($"نویز گرفته شد (نویزِ سنجیده {s.Noise:0.0}).");
        }
        Set("sharpen", s.Noise > 2.5 ? 25 : 35);
        Set("sharpenMasking", s.Noise > 2.5 ? 50 : 25);
        notes.Add("شارپِ ملایم با ماسک (فقط لبه‌ها).");
        return new AutoResult(r.Normalized(), notes);
    }

    private static double LaplacianVariance(Mat bgr)
    {
        using var g = new Mat(); Cv2.CvtColor(bgr, g, ColorConversionCodes.BGR2GRAY);
        using var lap = new Mat(); Cv2.Laplacian(g, lap, MatType.CV_32F, 1);
        Cv2.MeanStdDev(lap, out _, out var sd);
        return sd.Val0 * sd.Val0;
    }

    /// <summary>نویز به روشِ Immerkær روی تکهٔ وسطِ عکس در اندازهٔ اصلی (کوچک کردن نویز را پنهان می‌کند).</summary>
    private static double NoiseSigma(Mat bgr)
    {
        int side = Math.Min(768, Math.Min(bgr.Cols, bgr.Rows));
        var rect = new Rect((bgr.Cols - side) / 2, (bgr.Rows - side) / 2, side, side);
        using var crop = new Mat(bgr, rect);
        using var g = new Mat(); Cv2.CvtColor(crop, g, ColorConversionCodes.BGR2GRAY);
        using var g255 = new Mat(); g.ConvertTo(g255, MatType.CV_32FC1, 255);
        using var kernel = new Mat(3, 3, MatType.CV_32FC1);
        float[] k = { 1, -2, 1, -2, 4, -2, 1, -2, 1 };
        for (int i = 0; i < 9; i++) kernel.Set(i / 3, i % 3, k[i]);
        using var conv = new Mat(); Cv2.Filter2D(g255, conv, MatType.CV_32F, kernel);
        using var abs = new Mat(); Cv2.Absdiff(conv, Scalar.All(0), abs);
        // فقط بخش‌های صاف: لبه و بافت نویز نیستند (وگرنه عکسِ پرجزئیات «پرنویز» سنجیده می‌شود)
        using var gx = new Mat(); using var gy = new Mat(); using var mag = new Mat();
        Cv2.Sobel(g255, gx, MatType.CV_32F, 1, 0, 3); Cv2.Sobel(g255, gy, MatType.CV_32F, 0, 1, 3);
        Cv2.Magnitude(gx, gy, mag);
        using var magN = new Mat(); mag.ConvertTo(magN, MatType.CV_32FC1, 1 / 2000.0);
        var thr = Px.Percentiles(magN, 40)[0] * 2000;
        using var flat = new Mat(); Cv2.Threshold(mag, flat, Math.Max(thr, 1e-3), 255, ThresholdTypes.BinaryInv);
        using var flat8 = new Mat(); flat.ConvertTo(flat8, MatType.CV_8UC1);
        var meanAbs = Cv2.Mean(abs, flat8).Val0;
        return Math.Sqrt(Math.PI / 2) * meanAbs / 6;
    }
}
