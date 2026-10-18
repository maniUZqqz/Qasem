using OpenCvSharp;

namespace PersianAiKit.Photo.Engine;

/// <summary>کارهای پیکسلیِ سریع (حلقهٔ موازی روی سطرها) و فیلترهای پایه.</summary>
internal static unsafe class Px
{
    public const float Wr = 0.2126f, Wg = 0.7152f, Wb = 0.0722f;

    /// <summary>روشنایی (Y) از BGR.</summary>
    public static Mat Luma(Mat bgr)
    {
        var y = new Mat(bgr.Rows, bgr.Cols, MatType.CV_32FC1);
        int w = bgr.Cols;
        Parallel.For(0, bgr.Rows, r =>
        {
            float* s = (float*)bgr.Ptr(r);
            float* d = (float*)y.Ptr(r);
            for (int x = 0; x < w; x++, s += 3) d[x] = Wb * s[0] + Wg * s[1] + Wr * s[2];
        });
        return y;
    }

    /// <summary>
    /// هر کانال از جدولِ خودش (۴۰۹۶ خانه روی ۰ تا ۱، با درون‌یابی). ورودیِ بیرون از بازه بریده می‌شود.
    /// </summary>
    public static void ApplyLut(Mat bgr, float[] lutB, float[] lutG, float[] lutR)
    {
        int w = bgr.Cols, n = lutB.Length - 1;
        Parallel.For(0, bgr.Rows, r =>
        {
            float* p = (float*)bgr.Ptr(r);
            for (int x = 0; x < w; x++, p += 3)
            {
                p[0] = Lookup(lutB, p[0], n);
                p[1] = Lookup(lutG, p[1], n);
                p[2] = Lookup(lutR, p[2], n);
            }
        });
    }

    public static float Lookup(float[] lut, float v, int n)
    {
        if (!(v > 0)) return lut[0];
        if (v >= 1) return lut[n];
        var f = v * n;
        var i = (int)f;
        var t = f - i;
        return lut[i] + (lut[i + 1] - lut[i]) * t;
    }

    /// <summary>رنگ را با نسبتِ روشناییِ تازه به قدیم ضرب می‌کند (رنگ می‌ماند، روشنایی عوض می‌شود).</summary>
    public static void ApplyLumaRatio(Mat bgr, Mat yOld, Mat yNew)
    {
        int w = bgr.Cols;
        Parallel.For(0, bgr.Rows, r =>
        {
            float* p = (float*)bgr.Ptr(r);
            float* a = (float*)yOld.Ptr(r);
            float* b = (float*)yNew.Ptr(r);
            for (int x = 0; x < w; x++, p += 3)
            {
                var y0 = a[x];
                var y1 = b[x];
                if (y0 > 1e-4f)
                {
                    var k = y1 / y0;
                    p[0] *= k; p[1] *= k; p[2] *= k;
                }
                else
                {
                    var d = y1 - y0;
                    p[0] += d; p[1] += d; p[2] += d;
                }
            }
        });
    }

    public static void Clamp01(Mat m)
    {
        Cv2.Max(m, Scalar.All(0), m);
        Cv2.Min(m, Scalar.All(1), m);
    }

    public static Mat Box(Mat src, int r)
    {
        var d = new Mat();
        Cv2.BoxFilter(src, d, MatType.CV_32F, new Size(2 * r + 1, 2 * r + 1), null, true, BorderTypes.Reflect);
        return d;
    }

    /// <summary>
    /// فیلترِ هدایت‌شده (He و همکاران): صاف کردنِ p بی آن‌که لبه‌های I خراب شوند (پایهٔ کارهای محلی و لبه‌آگاه).
    /// برای شعاعِ بزرگ روی نسخهٔ کوچک حساب می‌شود و ضرایب بزرگ می‌شوند (Fast Guided Filter).
    /// </summary>
    public static Mat Guided(Mat I, Mat p, double radius, double eps, int workSide = 640)
    {
        var k = Math.Min(1.0, workSide / (double)Math.Max(I.Cols, I.Rows));
        Mat Il = I, pl = p;
        bool small = k < 1;
        if (small)
        {
            var sz = new Size(Math.Max(1, (int)(I.Cols * k)), Math.Max(1, (int)(I.Rows * k)));
            Il = new Mat(); Cv2.Resize(I, Il, sz, 0, 0, InterpolationFlags.Area);
            pl = new Mat(); Cv2.Resize(p, pl, sz, 0, 0, InterpolationFlags.Area);
        }
        int r = Math.Max(1, (int)Math.Round(radius * k));
        using var meanI = Box(Il, r);
        using var meanP = Box(pl, r);
        using var ii = new Mat(); Cv2.Multiply(Il, Il, ii);
        using var ip = new Mat(); Cv2.Multiply(Il, pl, ip);
        using var corrI = Box(ii, r);
        using var corrIp = Box(ip, r);
        using var mImI = new Mat(); Cv2.Multiply(meanI, meanI, mImI);
        using var mImP = new Mat(); Cv2.Multiply(meanI, meanP, mImP);
        using var varI = new Mat(); Cv2.Subtract(corrI, mImI, varI);
        using var covIp = new Mat(); Cv2.Subtract(corrIp, mImP, covIp);
        using var den = new Mat(); Cv2.Add(varI, Scalar.All(eps), den);
        using var a = new Mat(); Cv2.Divide(covIp, den, a);
        using var aMi = new Mat(); Cv2.Multiply(a, meanI, aMi);
        using var b = new Mat(); Cv2.Subtract(meanP, aMi, b);
        var meanA = Box(a, r);
        var meanB = Box(b, r);
        if (small)
        {
            Il.Dispose(); pl.Dispose();
            var ma = new Mat(); Cv2.Resize(meanA, ma, I.Size(), 0, 0, InterpolationFlags.Linear); meanA.Dispose(); meanA = ma;
            var mb = new Mat(); Cv2.Resize(meanB, mb, I.Size(), 0, 0, InterpolationFlags.Linear); meanB.Dispose(); meanB = mb;
        }
        var q = new Mat();
        Cv2.Multiply(meanA, I, q);
        Cv2.Add(q, meanB, q);
        meanA.Dispose(); meanB.Dispose();
        return q;
    }

    public static Mat Gaussian(Mat src, double sigma)
    {
        var d = new Mat();
        Cv2.GaussianBlur(src, d, new Size(0, 0), Math.Max(0.3, sigma), Math.Max(0.3, sigma), BorderTypes.Reflect);
        return d;
    }

    public static float Smoothstep(float e0, float e1, float x)
    {
        var t = Math.Clamp((x - e0) / (e1 - e0), 0f, 1f);
        return t * t * (3 - 2 * t);
    }

    /// <summary>صدک‌های یک تصویرِ تک‌کاناله (۰ تا ۱) با هیستوگرامِ ۴۰۹۶ خانه‌ای.</summary>
    public static double[] Percentiles(Mat y, params double[] ps)
    {
        const int N = 4096;
        var hist = new long[N];
        int w = y.Cols;
        for (int r = 0; r < y.Rows; r++)
        {
            float* p = (float*)y.Ptr(r);
            for (int x = 0; x < w; x++)
            {
                var v = p[x];
                var i = v <= 0 ? 0 : v >= 1 ? N - 1 : (int)(v * (N - 1));
                hist[i]++;
            }
        }
        long total = (long)y.Rows * w;
        var res = new double[ps.Length];
        for (int k = 0; k < ps.Length; k++)
        {
            var target = ps[k] / 100.0 * total;
            long acc = 0;
            int i = 0;
            for (; i < N; i++) { acc += hist[i]; if (acc >= target) break; }
            res[k] = Math.Min(i, N - 1) / (double)(N - 1);
        }
        return res;
    }
}
