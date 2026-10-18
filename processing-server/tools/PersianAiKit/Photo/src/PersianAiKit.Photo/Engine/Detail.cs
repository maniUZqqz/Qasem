using OpenCvSharp;

namespace PersianAiKit.Photo.Engine;

/// <summary>نویزگیری (روشنایی: Non-Local Means؛ رنگ: صاف کردنِ لبه‌آگاهِ کانال‌های a و b) و شارپ (ماسکِ غیرشارپ روی روشنایی).</summary>
internal static unsafe class Detail
{
    /// <param name="scale">اندازهٔ کار به اندازهٔ اصلی (پیش‌نمایش &lt; ۱) — شعاعِ شارپ به پیکسلِ اندازهٔ اصلی است.</param>
    public static void Apply(Mat bgr, Recipe r, double scale)
    {
        double nrL = r.Get("noiseLuma") / 100, nrC = r.Get("noiseColor") / 100;
        if (nrL > 0 || nrC > 0) Denoise(bgr, nrL, nrC);
        var amount = r.Get("sharpen") / 100;
        if (amount > 0) Sharpen(bgr, amount, r.Get("sharpenRadius") * scale, r.Get("sharpenMasking") / 100);
    }

    public static void Denoise(Mat bgr, double luma, double color)
    {
        using var lab = new Mat();
        Cv2.CvtColor(bgr, lab, ColorConversionCodes.BGR2Lab);
        var ch = Cv2.Split(lab);   // L: ۰ تا ۱۰۰، a/b: حدودِ ±۱۲۷
        try
        {
            if (luma > 0)
            {
                using var l8 = new Mat();
                ch[0].ConvertTo(l8, MatType.CV_8UC1, 2.55);
                using var d8 = new Mat();
                Cv2.FastNlMeansDenoising(l8, d8, (float)(2 + luma * 16), 7, 21);
                using var lf = new Mat();
                d8.ConvertTo(lf, MatType.CV_32FC1, 1 / 2.55);
                // فقط بخشِ نویز عوض شود، نه پلهٔ ۸بیتیِ کلِ تصویر
                using var diff = new Mat(); Cv2.Subtract(lf, ch[0], diff);
                using var diffS = new Mat(); Cv2.Min(diff, Scalar.All(20), diffS); Cv2.Max(diffS, Scalar.All(-20), diffS);
                Cv2.Add(ch[0], diffS, ch[0]);
            }
            if (color > 0)
            {
                using var guide = new Mat(); ch[0].ConvertTo(guide, MatType.CV_32FC1, 1 / 100.0);
                var radius = Math.Max(2, Math.Max(bgr.Cols, bgr.Rows) * 0.004 * (1 + color * 3));
                for (int i = 1; i <= 2; i++)
                {
                    using var a = new Mat(); ch[i].ConvertTo(a, MatType.CV_32FC1, 1 / 256.0);
                    using var f = Px.Guided(guide, a, radius, 0.002 + color * 0.01);
                    using var f2 = new Mat(); f.ConvertTo(f2, MatType.CV_32FC1, 256);
                    Cv2.AddWeighted(ch[i], 1 - Math.Min(1, color * 1.3), f2, Math.Min(1, color * 1.3), 0, ch[i]);
                }
            }
            Cv2.Merge(ch, lab);
            Cv2.CvtColor(lab, bgr, ColorConversionCodes.Lab2BGR);
        }
        finally { foreach (var m in ch) m.Dispose(); }
    }

    public static void Sharpen(Mat bgr, double amount, double radius, double masking)
    {
        using var y = Px.Luma(bgr);
        using var blur = Px.Gaussian(y, Math.Max(0.4, radius));
        using var yNew = new Mat(y.Size(), MatType.CV_32FC1);
        Mat? mag = null;
        if (masking > 0)
        {
            using var gx = new Mat(); using var gy = new Mat();
            Cv2.Sobel(blur, gx, MatType.CV_32F, 1, 0, 3);
            Cv2.Sobel(blur, gy, MatType.CV_32F, 0, 1, 3);
            mag = new Mat(); Cv2.Magnitude(gx, gy, mag);
        }
        float k = (float)(amount * 1.6), m0 = (float)(masking * 0.35);
        int w = y.Cols;
        Parallel.For(0, y.Rows, r =>
        {
            float* py = (float*)y.Ptr(r);
            float* pb = (float*)blur.Ptr(r);
            float* pm = mag is null ? null : (float*)mag.Ptr(r);
            float* pn = (float*)yNew.Ptr(r);
            for (int x = 0; x < w; x++)
            {
                var mask = pm is null ? 1f : Px.Smoothstep(m0, m0 + 0.15f, pm[x]);
                pn[x] = py[x] + k * (py[x] - pb[x]) * mask;
            }
        });
        mag?.Dispose();
        Px.ApplyLumaRatio(bgr, y, yNew);
    }
}
