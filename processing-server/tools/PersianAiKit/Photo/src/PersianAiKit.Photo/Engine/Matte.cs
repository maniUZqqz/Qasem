using OpenCvSharp;

namespace PersianAiKit.Photo.Engine;

/// <summary>گزارشِ تمیزیِ لبه بعد از حذفِ پس‌زمینه.</summary>
public sealed record EdgeReport(double Cleanup, double HaloPercent, double EdgePixels, IReadOnlyList<(double Cleanup, double Halo)> Tried)
{
    /// <summary>نمرهٔ تمیزیِ لبه (۰ تا ۱۰۰).</summary>
    public double Score => Math.Round(Math.Max(0, 100 - HaloPercent * 5), 1);
    public bool Clean => HaloPercent < 3;
}

/// <summary>
/// ماسکِ پس‌زمینه: تمیز کردنِ لبه (رنگِ پس‌زمینهٔ قبلی از لبه پاک می‌شود و ماسک کمی تنگ‌تر)، سنجشِ هاله، و گذاشتن روی رنگِ تازه.
/// سنجشِ هاله همان روشِ «روی رنگِ مخالف بینداز» است: لبه‌ای که رنگش با داخلِ کالا فرق دارد (ته‌ماندهٔ پس‌زمینه) هاله است.
/// </summary>
public static unsafe class Matte
{
    private const int WorkSide = 1024;

    /// <summary>
    /// رنگِ پس‌زمینهٔ قدیمیِ نزدیکِ هر لبه: میانگینِ وزن‌دارِ پیکسل‌های بیرون (همگشتِ نرمال‌شده).
    /// میدانِ نرمی است ⇒ روی نسخهٔ کوچک (۱۰۲۴) حساب و بزرگ می‌شود (عکسِ ۲۴ مگاپیکسلی هم حافظهٔ کمی می‌گیرد).
    /// </summary>
    public static Mat EstimateBackground(Mat bgr, Mat alpha)
    {
        var k = WorkSide / (double)Math.Max(bgr.Cols, bgr.Rows);
        if (k >= 0.8) return EstimateBackgroundAt(bgr, alpha);
        var sz = new Size(Math.Max(8, (int)(bgr.Cols * k)), Math.Max(8, (int)(bgr.Rows * k)));
        using var s = new Mat(); Cv2.Resize(bgr, s, sz, 0, 0, InterpolationFlags.Area);
        using var a = new Mat(); Cv2.Resize(alpha, a, sz, 0, 0, InterpolationFlags.Area);
        using var b = EstimateBackgroundAt(s, a);
        var full = new Mat(); Cv2.Resize(b, full, bgr.Size(), 0, 0, InterpolationFlags.Linear);
        return full;
    }

    private static Mat EstimateBackgroundAt(Mat bgr, Mat alpha)
    {
        var dim = Math.Max(bgr.Cols, bgr.Rows);
        using var wBg = new Mat(); Cv2.Subtract(Scalar.All(1), alpha, wBg); Cv2.Pow(wBg, 4, wBg);
        using var wBg3 = new Mat(); Cv2.Merge(new[] { wBg, wBg, wBg }, wBg3);
        using var num0 = new Mat(); Cv2.Multiply(bgr, wBg3, num0);
        var sigma = Math.Max(3, dim * 0.01);
        using var num = Px.Gaussian(num0, sigma);
        using var den = Px.Gaussian(wBg, sigma);
        using var den3 = new Mat(); Cv2.Merge(new[] { den, den, den }, den3);
        Cv2.Max(den3, Scalar.All(1e-4), den3);
        var b = new Mat(); Cv2.Divide(num, den3, b);
        return b;
    }

    /// <summary>
    /// رنگِ داخلِ کالا نزدیکِ هر لبه (همگشتِ نرمال‌شدهٔ جاهایی که ماسک بالای ۰٫۹۷ است) و وزنش (کم ⇒ داخلی در کار نیست).
    /// مثلِ زمینه روی نسخهٔ کوچک حساب می‌شود.
    /// </summary>
    public static (Mat Color, Mat Weight) EstimateForeground(Mat bgr, Mat alpha)
    {
        var k = WorkSide / (double)Math.Max(bgr.Cols, bgr.Rows);
        if (k >= 0.8) return EstimateForegroundAt(bgr, alpha);
        var sz = new Size(Math.Max(8, (int)(bgr.Cols * k)), Math.Max(8, (int)(bgr.Rows * k)));
        using var s = new Mat(); Cv2.Resize(bgr, s, sz, 0, 0, InterpolationFlags.Area);
        using var a = new Mat(); Cv2.Resize(alpha, a, sz, 0, 0, InterpolationFlags.Area);
        var (f, wt) = EstimateForegroundAt(s, a);
        using (f) using (wt)
        {
            var F = new Mat(); Cv2.Resize(f, F, bgr.Size(), 0, 0, InterpolationFlags.Linear);
            var W = new Mat(); Cv2.Resize(wt, W, bgr.Size(), 0, 0, InterpolationFlags.Linear);
            return (F, W);
        }
    }

    private static (Mat Color, Mat Weight) EstimateForegroundAt(Mat bgr, Mat alpha)
    {
        var dim = Math.Max(bgr.Cols, bgr.Rows);
        using var inner = new Mat(); Cv2.Threshold(alpha, inner, 0.97, 1, ThresholdTypes.Binary);
        using var inner3 = new Mat(); Cv2.Merge(new[] { inner, inner, inner }, inner3);
        using var cin = new Mat(); Cv2.Multiply(bgr, inner3, cin);
        var sigma = Math.Max(2, dim * 0.006);
        using var num = Px.Gaussian(cin, sigma);
        var den = Px.Gaussian(inner, sigma);
        using var den3 = new Mat(); Cv2.Merge(new[] { den, den, den }, den3);
        Cv2.Max(den3, Scalar.All(1e-4), den3);
        var f = new Mat(); Cv2.Divide(num, den3, f);
        return (f, den);
    }

    /// <summary>
    /// تمیزکاریِ لبه به میزانِ <paramref name="cleanup"/> (۰ تا ۱) — همان «دوباره نگاه کن و تمیز کن»:
    /// ۱) ماسک: پیکسلِ لبه که رنگش (بینِ رنگِ کالا و رنگِ زمینهٔ همان‌جا) به زمینه نزدیک‌تر است کم‌رنگ‌تر می‌شود
    ///    (ماسکِ گشاد که زمینه را هم برداشته، تنگ می‌شود — فقط کم می‌شود، هرگز زیاد)؛
    /// ۲) رنگ: رنگِ زمینهٔ قدیمی از پیکسل‌های نیمه‌شفاف بیرون کشیده می‌شود؛ ۳) کمی تنگ‌تر کردنِ کلی.
    /// </summary>
    public static (Mat Color, Mat Alpha) Clean(Mat bgr, Mat alpha, double cleanup, Mat? background = null)
    {
        var color = bgr.Clone();
        var a2 = alpha.Clone();
        if (cleanup <= 0) return (color, a2);
        var bg = background ?? EstimateBackground(bgr, alpha);
        var (fg, fw) = EstimateForeground(bgr, alpha);
        float c = (float)Math.Clamp(cleanup, 0, 1);
        float choke = 0.15f * c;
        int w = bgr.Cols;
        Parallel.For(0, bgr.Rows, r =>
        {
            float* pc = (float*)color.Ptr(r);
            float* pa = (float*)a2.Ptr(r);
            float* pb = (float*)bg.Ptr(r);
            float* pf = (float*)fg.Ptr(r);
            float* pw = (float*)fw.Ptr(r);
            for (int x = 0; x < w; x++, pc += 3, pb += 3, pf += 3)
            {
                var a = pa[x];
                if (a > 0.01f && a < 0.995f)
                {
                    if (pw[x] > 0.03f)
                    {
                        var ac = MixAlpha(pc, pf, pb, out var ok);
                        if (ok && ac < a) a += (ac - a) * c;
                    }
                    // مدلِ ترکیب: دیده = پیش‌زمینه×α + پس‌زمینه×(۱−α) ⇒ پیش‌زمینه را برمی‌گردانیم
                    var ia = 1 / Math.Max(a, 0.08f);
                    for (int k = 0; k < 3; k++)
                    {
                        var f = Math.Clamp((pc[k] - (1 - a) * pb[k]) * ia, 0f, 1f);
                        pc[k] += (f - pc[k]) * c;
                    }
                }
                pa[x] = Math.Clamp((a - choke) / (1 - choke), 0f, 1f);
            }
        });
        fg.Dispose(); fw.Dispose();
        if (background is null) bg.Dispose();
        return (color, a2);
    }

    /// <summary>
    /// α از رنگ (دیده = α·کالا + (۱−α)·زمینه، پیکسل‌ها BGR). اول در «رنگِ جدا از روشنایی»: c(p) = p − (L(p)/L(زمینه))·زمینه؛
    /// چون c(دیده) = α·c(کالا) دقیق است و سایه (زمینهٔ تیره‌تر) c = ۰ دارد ⇒ سایه هرگز هالهٔ نیمه‌شفاف نمی‌شود.
    /// کالای بی‌رنگ نسبت به زمینه (خاکستری/کروم روی سفید) ⇒ همان تصویرِ RGB. <paramref name="ok"/> = false ⇒ کالا و زمینه هم‌رنگ‌اند.
    /// </summary>
    internal static float MixAlpha(float* i, float* f, float* b, out bool ok)
    {
        float lb = Math.Max(0.02f, Px.Wb * b[0] + Px.Wg * b[1] + Px.Wr * b[2]);
        float si = (Px.Wb * i[0] + Px.Wg * i[1] + Px.Wr * i[2]) / lb, sf = (Px.Wb * f[0] + Px.Wg * f[1] + Px.Wr * f[2]) / lb;
        float dot = 0, nn = 0;
        for (int k = 0; k < 3; k++)
        {
            var cf = f[k] - sf * b[k];
            dot += (i[k] - si * b[k]) * cf;
            nn += cf * cf;
        }
        if (nn > 0.01f) { ok = true; return Math.Clamp(dot / nn, 0f, 1f); }
        dot = 0; nn = 0;
        for (int k = 0; k < 3; k++)
        {
            var d = f[k] - b[k];
            dot += (i[k] - b[k]) * d;
            nn += d * d;
        }
        ok = nn > 0.01f;
        return ok ? Math.Clamp(dot / nn, 0f, 1f) : 0f;
    }

    /// <summary>
    /// درصدِ لبه که رنگش به پس‌زمینهٔ قدیمی نزدیک‌تر است تا به داخلِ کالا (ته‌ماندهٔ پس‌زمینه = هالهٔ روی رنگِ مخالف).
    /// لبهٔ براق یا تیرهٔ خودِ کالا (مثلِ فلز) هاله حساب نمی‌شود.
    /// </summary>
    public static (double HaloPercent, double EdgePixels) Halo(Mat color, Mat alpha, Mat background)
    {
        var (num, den) = EstimateForeground(color, alpha);
        using var _n = num; using var _d = den;
        int w = color.Cols;
        var rows = new (double H, double T)[color.Rows];
        Parallel.For(0, color.Rows, r =>
        {
            float* pc = (float*)color.Ptr(r);
            float* pa = (float*)alpha.Ptr(r);
            float* pn = (float*)num.Ptr(r);
            float* pd = (float*)den.Ptr(r);
            float* pb = (float*)background.Ptr(r);
            double h = 0, t = 0;
            for (int x = 0; x < w; x++, pc += 3, pn += 3, pb += 3)
            {
                var a = pa[x];
                if (a <= 0.08f || a >= 0.97f || pd[x] < 0.03f) continue;
                float dIn = 0, dBg = 0;
                for (int k = 0; k < 3; k++)
                {
                    dIn = Math.Max(dIn, Math.Abs(pc[k] - pn[k]));
                    dBg = Math.Max(dBg, Math.Abs(pc[k] - pb[k]));
                }
                t += a;
                if (dBg < 0.15f && dBg < dIn * 0.6f) h += a;
            }
            rows[r] = (h, t);
        });
        double halo = 0, total = 0;
        foreach (var (h, t) in rows) { halo += h; total += t; }
        return (total < 1 ? 0 : halo / total * 100, total);
    }

    /// <summary>
    /// تمیزکاریِ خودکار: از کم به زیاد امتحان می‌کند و کمترین مقداری را برمی‌دارد که هاله‌اش زیرِ ۳٪ است
    /// (بیشتر از لازم تنگ کردن جزئیاتِ لبه را می‌خورد). عکسِ بزرگ روی نسخهٔ ۱۰۲۴ سنجیده می‌شود (درصد به اندازه بستگی ندارد).
    /// </summary>
    public static EdgeReport AutoCleanup(Mat bgr, Mat alpha)
    {
        var k = WorkSide / (double)Math.Max(bgr.Cols, bgr.Rows);
        if (k < 0.8)
        {
            var sz = new Size(Math.Max(8, (int)(bgr.Cols * k)), Math.Max(8, (int)(bgr.Rows * k)));
            using var s = new Mat(); Cv2.Resize(bgr, s, sz, 0, 0, InterpolationFlags.Area);
            using var a = new Mat(); Cv2.Resize(alpha, a, sz, 0, 0, InterpolationFlags.Area);
            return AutoCleanup(s, a);
        }
        using var bg = EstimateBackground(bgr, alpha);
        var tried = new List<(double, double)>();
        (double C, double H, double E) best = (0, double.MaxValue, 0);
        foreach (var c in new[] { 0.0, 0.25, 0.5, 0.75, 1.0 })
        {
            var (col, a) = Clean(bgr, alpha, c, bg);
            var (h, e) = Halo(col, a, bg);
            col.Dispose(); a.Dispose();
            tried.Add((c * 100, Math.Round(h, 2)));
            if (h < best.H - 0.3) best = (c, h, e);
            if (h < 3) { best = (c, h, e); break; }
        }
        return new EdgeReport(best.C * 100, Math.Round(best.H, 2), best.E, tried);
    }

    public static EdgeReport Report(Mat bgr, Mat alpha, double cleanup01)
    {
        using var bg = EstimateBackground(bgr, alpha);
        var (col, a) = Clean(bgr, alpha, cleanup01, bg);
        var (h, e) = Halo(col, a, bg);
        col.Dispose(); a.Dispose();
        return new EdgeReport(cleanup01 * 100, Math.Round(h, 2), e, new[] { (cleanup01 * 100, Math.Round(h, 2)) });
    }

    /// <summary>رنگِ پیش‌زمینه × ماسک + رنگِ پس‌زمینه × (۱ − ماسک)، با سایهٔ نرمِ دلخواه زیرِ کالا.</summary>
    public static Mat Composite(Mat fg, Mat alpha, (double R, double G, double B) bg, double shadow)
    {
        int w = fg.Cols, h = fg.Rows;
        Mat? sh = null;
        if (shadow > 0)
        {
            using var shifted = new Mat();
            var dy = Math.Max(1, (int)(h * 0.02));
            using var m = new Mat(2, 3, MatType.CV_64FC1);
            m.Set(0, 0, 1.0); m.Set(0, 1, 0.0); m.Set(0, 2, 0.0);
            m.Set(1, 0, 0.0); m.Set(1, 1, 1.0); m.Set(1, 2, (double)dy);
            Cv2.WarpAffine(alpha, shifted, m, alpha.Size(), InterpolationFlags.Linear, BorderTypes.Constant, Scalar.All(0));
            sh = Px.Gaussian(shifted, Math.Max(3, Math.Max(w, h) * 0.025));
        }
        var outM = new Mat(h, w, MatType.CV_32FC3);
        float bB = (float)bg.B, bG = (float)bg.G, bR = (float)bg.R, s = (float)(shadow / 100 * 0.6);
        Parallel.For(0, h, r =>
        {
            float* pf = (float*)fg.Ptr(r);
            float* pa = (float*)alpha.Ptr(r);
            float* po = (float*)outM.Ptr(r);
            float* ps = sh is null ? null : (float*)sh.Ptr(r);
            for (int x = 0; x < w; x++, pf += 3, po += 3)
            {
                var a = Math.Clamp(pa[x], 0f, 1f);
                var k = ps is null ? 1f : 1 - s * Math.Clamp(ps[x], 0f, 1f);
                po[0] = pf[0] * a + bB * k * (1 - a);
                po[1] = pf[1] * a + bG * k * (1 - a);
                po[2] = pf[2] * a + bR * k * (1 - a);
            }
        });
        sh?.Dispose();
        return outM;
    }
}
