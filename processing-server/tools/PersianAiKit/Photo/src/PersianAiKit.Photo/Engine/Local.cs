using OpenCvSharp;

namespace PersianAiKit.Photo.Engine;

/// <summary>کارهای «محلی» و لبه‌آگاه: روشنی‌ها/سایه‌ها، بافت و وضوح، مه‌زدایی. شعاع‌ها به نسبتِ اندازهٔ عکس‌اند ⇒ پیش‌نمایش و خروجی یکی.</summary>
internal static unsafe class Local
{
    /// <summary>
    /// روشنایی با پایهٔ لبه‌آگاه سنجیده می‌شود (نه تک‌پیکسل) ⇒ سایهٔ یک «ناحیه» باز می‌شود بی آن‌که کنتراستِ داخلش از بین برود یا دورِ لبه هاله بیفتد.
    /// </summary>
    public static void HighlightsShadows(Mat bgr, double highlights, double shadows)
    {
        using var y = Px.Luma(bgr);
        var dim = Math.Max(bgr.Cols, bgr.Rows);
        using var baseY = Px.Guided(y, y, dim * 0.025, 0.02);
        using var yNew = new Mat(y.Size(), MatType.CV_32FC1);
        float sh = (float)(shadows / 100), hl = (float)(highlights / 100);
        int w = y.Cols;
        Parallel.For(0, y.Rows, r =>
        {
            float* py = (float*)y.Ptr(r);
            float* pb = (float*)baseY.Ptr(r);
            float* pn = (float*)yNew.Ptr(r);
            for (int x = 0; x < w; x++)
            {
                var b = Math.Clamp(pb[x], 0f, 1f);
                var ws = 1 - Px.Smoothstep(0f, 0.6f, b);
                var wh = Px.Smoothstep(0.4f, 1f, b);
                var g = sh * 1.3f * ws + hl * 1.0f * wh;
                var v = py[x] * MathF.Pow(2, g);
                pn[x] = v > 0.95f ? 0.95f + 0.05f * (1 - MathF.Exp(-(v - 0.95f) / 0.05f)) : v;
            }
        });
        Px.ApplyLumaRatio(bgr, y, yNew);
    }

    /// <summary>بافت = جزئیاتِ ریز (تفاضلِ گاوسیِ کوچک)؛ وضوح = کنتراستِ محلیِ درشت در میانه‌ها (پایهٔ لبه‌آگاه).</summary>
    public static void TextureClarity(Mat bgr, double texture, double clarity)
    {
        using var y = Px.Luma(bgr);
        var dim = Math.Max(bgr.Cols, bgr.Rows);
        using var yNew = y.Clone();
        if (clarity != 0)
        {
            using var baseY = Px.Guided(y, y, dim * 0.015, 0.01);
            float c = (float)(clarity / 100 * 1.2);
            int w = y.Cols;
            Parallel.For(0, y.Rows, r =>
            {
                float* py = (float*)y.Ptr(r);
                float* pb = (float*)baseY.Ptr(r);
                float* pn = (float*)yNew.Ptr(r);
                for (int x = 0; x < w; x++)
                {
                    var v = py[x];
                    var mid = 4 * Math.Clamp(v, 0f, 1f) * (1 - Math.Clamp(v, 0f, 1f));
                    pn[x] += c * (v - pb[x]) * (0.35f + 0.65f * mid);
                }
            });
        }
        if (texture != 0)
        {
            using var blur = Px.Gaussian(y, Math.Max(1.0, dim * 0.003));
            float t = (float)(texture / 100);
            int w = y.Cols;
            Parallel.For(0, y.Rows, r =>
            {
                float* py = (float*)y.Ptr(r);
                float* pb = (float*)blur.Ptr(r);
                float* pn = (float*)yNew.Ptr(r);
                for (int x = 0; x < w; x++) pn[x] += t * (py[x] - pb[x]);
            });
        }
        Px.ApplyLumaRatio(bgr, y, yNew);
    }

    /// <summary>
    /// مه‌زدایی با «پیشینِ کانالِ تیره» (He و همکاران): مه = آمیختنِ تصویر با نورِ هوا ⇒ ضخامتِ مه تخمین و معادله برعکس حل می‌شود.
    /// منفی ⇒ مهِ مصنوعی.
    /// </summary>
    public static void Dehaze(Mat bgr, double amount)
    {
        var k = Math.Min(1.0, 600.0 / Math.Max(bgr.Cols, bgr.Rows));
        using var small = new Mat();
        Cv2.Resize(bgr, small, new Size(Math.Max(1, (int)(bgr.Cols * k)), Math.Max(1, (int)(bgr.Rows * k))), 0, 0, InterpolationFlags.Area);
        int patch = Math.Max(3, (int)(Math.Max(small.Cols, small.Rows) * 0.02)) | 1;
        using var kernel = Cv2.GetStructuringElement(MorphShapes.Rect, new Size(patch, patch));

        using var dark = MinChannel(small, 1, 1, 1);
        using var darkE = new Mat(); Cv2.Erode(dark, darkE, kernel);
        var air = AirLight(small, darkE);
        using var norm = MinChannel(small, air.B, air.G, air.R);
        using var normE = new Mat(); Cv2.Erode(norm, normE, kernel);
        using var tRaw = new Mat(); Cv2.Multiply(normE, Scalar.All(-0.95), tRaw); Cv2.Add(tRaw, Scalar.All(1), tRaw);
        using var gray = Px.Luma(small);
        using var tRef = Px.Guided(gray, tRaw, Math.Max(small.Cols, small.Rows) * 0.03, 1e-3, 10_000);
        using var t = new Mat(); Cv2.Resize(tRef, t, bgr.Size(), 0, 0, InterpolationFlags.Linear);

        float a = (float)(amount / 100);
        float aB = (float)air.B, aG = (float)air.G, aR = (float)air.R;
        int w = bgr.Cols;
        Parallel.For(0, bgr.Rows, r =>
        {
            float* p = (float*)bgr.Ptr(r);
            float* pt = (float*)t.Ptr(r);
            for (int x = 0; x < w; x++, p += 3)
            {
                var tt = Math.Max(pt[x], 0.1f);
                if (a > 0)
                {
                    var s = a * 0.85f;
                    p[0] += s * ((p[0] - aB) / tt + aB - p[0]);
                    p[1] += s * ((p[1] - aG) / tt + aG - p[1]);
                    p[2] += s * ((p[2] - aR) / tt + aR - p[2]);
                }
                else
                {
                    var s = -a * 0.45f * (1.2f - tt);
                    p[0] += s * (aB - p[0]);
                    p[1] += s * (aG - p[1]);
                    p[2] += s * (aR - p[2]);
                }
            }
        });
    }

    private static Mat MinChannel(Mat bgr, double dB, double dG, double dR)
    {
        var m = new Mat(bgr.Rows, bgr.Cols, MatType.CV_32FC1);
        float iB = (float)(1 / dB), iG = (float)(1 / dG), iR = (float)(1 / dR);
        int w = bgr.Cols;
        Parallel.For(0, bgr.Rows, r =>
        {
            float* s = (float*)bgr.Ptr(r);
            float* d = (float*)m.Ptr(r);
            for (int x = 0; x < w; x++, s += 3) d[x] = Math.Min(s[0] * iB, Math.Min(s[1] * iG, s[2] * iR));
        });
        return m;
    }

    /// <summary>نورِ هوا: میانگینِ رنگِ روشن‌ترین ۰٫۱٪ِ کانالِ تیره.</summary>
    private static (double B, double G, double R) AirLight(Mat bgr, Mat dark)
    {
        var thr = Px.Percentiles(dark, 99.9)[0];
        double b = 0, g = 0, rr = 0; long n = 0;
        for (int r = 0; r < bgr.Rows; r++)
        {
            float* s = (float*)bgr.Ptr(r);
            float* d = (float*)dark.Ptr(r);
            for (int x = 0; x < bgr.Cols; x++, s += 3)
                if (d[x] >= thr) { b += s[0]; g += s[1]; rr += s[2]; n++; }
        }
        if (n == 0) return (1, 1, 1);
        return (Math.Clamp(b / n, 0.3, 1), Math.Clamp(g / n, 0.3, 1), Math.Clamp(rr / n, 0.3, 1));
    }
}
