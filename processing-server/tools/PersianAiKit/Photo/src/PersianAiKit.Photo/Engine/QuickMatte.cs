using OpenCvSharp;

namespace PersianAiKit.Photo.Engine;

/// <summary>نتیجهٔ حذفِ سبکِ پس‌زمینه: ماسک (۰ تا ۱، اندازهٔ خودِ عکس)، اطمینان (۰ تا ۱) و توضیحِ فارسی.</summary>
public sealed record QuickMatteResult(Mat Alpha, double Confidence, bool PlainBackground, string Note);

/// <summary>
/// حذفِ پس‌زمینهٔ سبک، بی مدل (زیرِ یک ثانیه، چند ده مگابایت حافظه) — برای کالا روی زمینهٔ ساده یا استودیویی
/// (سفید، رنگی، شیب‌دار، با سایهٔ نرم):
/// ۱) رنگِ زمینه از حاشیهٔ عکس به شکلِ سطحِ نرمِ درجهٔ ۲ برازش می‌شود (شیبِ نورِ استودیو را هم می‌گیرد)؛
/// ۲) نشانهٔ کالا: رنگِ دیگر، روشن‌تر از زمینه، لبه/بافت یا خیلی تیره — سایهٔ نرم (فقط تیره‌تر و صاف) نشانه نیست؛
/// ۳) جاهای بسته‌شده با لبهٔ کالا (مثلِ بدنهٔ صافِ فلزی) کالا حساب می‌شوند، مگر هم‌رنگِ زمینه باشند (سوراخِ واقعی)؛
///    بعد GrabCut لبه را روی مرزِ رنگ می‌نشاند؛
/// ۴) لبهٔ نرم: هر پیکسلِ لبه بینِ رنگِ کالا و رنگِ زمینهٔ همان‌جا تصویر می‌شود.
/// زمینهٔ شلوغ ⇒ GrabCut با کادر و اطمینانِ کم (آن‌جا مدلِ هوشِ مصنوعی بهتر است).
/// </summary>
public static unsafe class QuickMatte
{
    private const int WorkSide = 640, RefineSide = 1600;
    private const byte Bgd = 0, Fgd = 1, PrBgd = 2, PrFgd = 3;

    public static QuickMatteResult Mask(Mat bgr01)
    {
        int W = bgr01.Cols, H = bgr01.Rows;
        using var small = Resized(bgr01, WorkSide, InterpolationFlags.Area);
        int w = small.Cols, h = small.Rows;
        using var small8 = new Mat(); small.ConvertTo(small8, MatType.CV_8UC3, 255);

        var fit = FitBackground(small);
        bool plain = fit.Inliers >= 0.75 && fit.P90 < 0.08;
        using var gc = new Mat(h, w, MatType.CV_8UC1, Scalar.All(PrBgd));
        string note;
        double conf;
        if (plain)
        {
            var tau = (float)Math.Clamp(fit.P90 * 1.5 + 0.03, 0.04, 0.15);
            using var dc = Components(small, fit.Coef, out var dl);
            using var grad = Gradient(small);
            var gT = (float)Math.Max(0.03, 4 * BorderMedian(grad));
            // گذرِ «تیره‌ترِ بی‌رنگ» (لبهٔ سایه یا لبهٔ فلز): فقط لبهٔ تیز نشانهٔ کالاست؛ نیم‌سایهٔ نرم نه
            var gTn = Math.Max(0.07f, 2 * gT);
            // «حتماً زمینه»: رنگ و روشنایی همان زمینه. «نشانهٔ کالا»: رنگِ دیگر، روشن‌تر، لبه/بافت، یا خیلی تیره.
            // سایهٔ نرم (فقط تیره‌تر، بی لبه) هیچ‌کدام نیست ⇒ از راهِ زمینه به حاشیه می‌رسد و زمینه می‌ماند.
            using var strict = new Mat(h, w, MatType.CV_8UC1, Scalar.All(0));
            using var cand = new Mat(h, w, MatType.CV_8UC1, Scalar.All(0));
            using var vague = new Mat(h, w, MatType.CV_8UC1, Scalar.All(0));
            Parallel.For(0, h, y =>
            {
                float* pc = (float*)dc.Ptr(y), pl = (float*)dl.Ptr(y), pg = (float*)grad.Ptr(y);
                byte* ps = (byte*)strict.Ptr(y), pk = (byte*)cand.Ptr(y), pv = (byte*)vague.Ptr(y);
                for (int x = 0; x < w; x++)
                {
                    float c = pc[x], l = pl[x], g = pg[x];
                    if (Math.Max(c, Math.Abs(l)) < tau) { ps[x] = 255; continue; }
                    var shade = c <= tau && l < 0;
                    if (c > tau || l > tau || g > (shade ? gTn : gT) || l < -0.45f) pk[x] = 255;
                    else pv[x] = 255;   // خاکستریِ تیره‌ترِ صاف: سایه یا بدنهٔ صافِ کالا (مثلِ کروم)
                }
            });
            dl.Dispose();
            using var k5 = Cv2.GetStructuringElement(MorphShapes.Ellipse, new Size(5, 5));
            Cv2.MorphologyEx(cand, cand, MorphTypes.Close, k5);
            // جاهای بسته‌شده با لبهٔ کالا: اگر بیشترش رنگِ زمینه است سوراخِ واقعی است، وگرنه بدنهٔ کالا
            using var region = cand.Clone();
            using (var notCand = new Mat())
            using (var labels = new Mat()) using (var stats = new Mat()) using (var cent = new Mat())
            {
                Cv2.BitwiseNot(cand, notCand);
                var n = Cv2.ConnectedComponentsWithStats(notCand, labels, stats, cent, PixelConnectivity.Connectivity4);
                var outside = BorderLabels(labels);
                var strictCount = new int[n];
                for (int y = 0; y < h; y++)
                {
                    int* pl2 = (int*)labels.Ptr(y);
                    byte* ps = (byte*)strict.Ptr(y);
                    for (int x = 0; x < w; x++) if (ps[x] != 0) strictCount[pl2[x]]++;
                }
                var fill = new bool[n];
                for (int i = 1; i < n; i++)
                    fill[i] = !outside.Contains(i) && strictCount[i] < 0.6 * stats.At<int>(i, (int)ConnectedComponentsTypes.Area);
                for (int y = 0; y < h; y++)
                {
                    int* pl2 = (int*)labels.Ptr(y);
                    byte* pr = (byte*)region.Ptr(y);
                    for (int x = 0; x < w; x++) if (fill[pl2[x]]) pr[x] = 255;
                }
            }
            var fgCount = Cv2.CountNonZero(region);
            if (fgCount < 20)
                return new QuickMatteResult(new Mat(H, W, MatType.CV_32FC1, Scalar.All(0)), 0, true, "روی زمینهٔ ساده کالایی پیدا نشد.");
            // زمینهٔ پیوسته به حاشیه (هم‌رنگِ دقیقِ زمینه) = قطعی؛ بقیهٔ بیرون (سایه) = احتمالی؛ دلِ کالا = قطعی؛ لبه‌اش را GrabCut می‌چیند
            using var sureBg = new Mat(h, w, MatType.CV_8UC1, Scalar.All(0));
            using (var labels = new Mat())
            {
                Cv2.ConnectedComponents(strict, labels, PixelConnectivity.Connectivity8, MatType.CV_32S);
                var outside = BorderLabels(labels);
                for (int y = 0; y < h; y++)
                {
                    int* pl2 = (int*)labels.Ptr(y);
                    byte* pb = (byte*)sureBg.Ptr(y);
                    for (int x = 0; x < w; x++) if (pl2[x] > 0 && outside.Contains(pl2[x])) pb[x] = 255;
                }
            }
            using var inner = new Mat(); Cv2.Erode(region, inner, null, iterations: 3);
            gc.SetTo(Scalar.All(Bgd), sureBg);
            gc.SetTo(Scalar.All(PrFgd), region);
            gc.SetTo(Scalar.All(Fgd), inner);
            RunGrabCut(small8, gc, null);
            // سهمِ بخش‌های «خاکستریِ صاف» در کالا: هر چه بیشتر، تشخیص حدسی‌تر (کروم، کالای خاکستری)
            using var vagueIn = new Mat(); Cv2.BitwiseAnd(vague, region, vagueIn);
            var vagueShare = Cv2.CountNonZero(vagueIn) / (double)fgCount;
            conf = Math.Clamp((fit.Inliers - 0.6) / 0.35, 0, 1) * (fit.P90 < 0.05 ? 1 : 0.75) * (1 - 0.6 * vagueShare);
            note = $"زمینهٔ ساده ({fit.Inliers:P0} از حاشیه یکدست) ⇒ حذفِ سبک، بی مدل.";
            if (vagueShare > 0.25) note += " بخشی از کالا خاکستری و صاف است (مثلِ فلز) — لبه را روی رنگِ مخالف ببینید.";
        }
        else
        {
            int mx = Math.Max(2, (int)(w * 0.04)), my = Math.Max(2, (int)(h * 0.04));
            RunGrabCut(small8, gc, new Rect(mx, my, w - 2 * mx, h - 2 * my));
            conf = 0.25;
            note = "زمینه ساده نیست؛ حذفِ سبک فقط حدس است — برای این عکس مدلِ هوشِ مصنوعی (روی سرور) بهتر است.";
        }

        using var bin = Binary(gc);
        var area = Cv2.CountNonZero(bin) / (double)(w * h);
        if (area < 0.003) return new QuickMatteResult(new Mat(H, W, MatType.CV_32FC1, Scalar.All(0)), 0, plain, "کالایی پیدا نشد.");
        if (area > 0.92) conf *= 0.3;
        if (BorderTouch(bin) > 0.3) { conf *= 0.7; note += " کالا به لبهٔ عکس چسبیده."; }

        var alpha = Refine(bgr01, bin);
        return new QuickMatteResult(alpha, Math.Round(conf, 2), plain, note);
    }

    // ───────────── زمینه ─────────────

    private readonly record struct Fit(double[][] Coef, double Inliers, double P90);

    /// <summary>سطحِ رنگِ زمینه از حاشیهٔ ۴٪ (دو گذر: گذرِ دوم بی پیکسل‌های پرت، مثلِ کالای چسبیده به لبه).</summary>
    private static Fit FitBackground(Mat img)
    {
        int w = img.Cols, h = img.Rows, bw = Math.Max(2, (int)(Math.Min(w, h) * 0.04));
        var pts = new List<(double X, double Y, float B, float G, float R)>();
        for (int y = 0; y < h; y += 2)
        {
            float* p = (float*)img.Ptr(y);
            for (int x = 0; x < w; x += 2)
            {
                if (x >= bw && x < w - bw && y >= bw && y < h - bw) continue;
                pts.Add((x / (double)(w - 1) * 2 - 1, y / (double)(h - 1) * 2 - 1, p[x * 3], p[x * 3 + 1], p[x * 3 + 2]));
            }
        }
        var use = Enumerable.Repeat(true, pts.Count).ToArray();
        double[][] coef = Solve(pts, use);
        var res = Residuals(pts, coef);
        var med = Median(res);
        var cut = Math.Max(0.04, med * 3);
        for (int i = 0; i < pts.Count; i++) use[i] = res[i] < cut;
        if (use.Count(u => u) >= 12) coef = Solve(pts, use);
        res = Residuals(pts, coef);
        var med2 = Median(res);
        var inl = res.Where(r => r < Math.Max(0.05, med2 * 3)).OrderBy(r => r).ToArray();
        var p90 = inl.Length == 0 ? 1 : inl[(int)(inl.Length * 0.9)];
        return new Fit(coef, inl.Length / (double)Math.Max(1, pts.Count), p90);
    }

    private static double[] Basis(double x, double y) => new[] { 1, x, y, x * x, x * y, y * y };

    private static double[][] Solve(List<(double X, double Y, float B, float G, float R)> pts, bool[] use)
    {
        var a = new double[6, 6];
        var rhs = new double[3, 6];
        for (int i = 0; i < pts.Count; i++)
        {
            if (!use[i]) continue;
            var (x, y, b, g, r) = pts[i];
            var f = Basis(x, y);
            for (int j = 0; j < 6; j++)
            {
                for (int k = 0; k < 6; k++) a[j, k] += f[j] * f[k];
                rhs[0, j] += f[j] * b; rhs[1, j] += f[j] * g; rhs[2, j] += f[j] * r;
            }
        }
        for (int j = 0; j < 6; j++) a[j, j] += 1e-6;
        var coef = new double[3][];
        for (int c = 0; c < 3; c++)
        {
            var m = (double[,])a.Clone();
            var v = new double[6];
            for (int j = 0; j < 6; j++) v[j] = rhs[c, j];
            coef[c] = Gauss(m, v);
        }
        return coef;
    }

    /// <summary>حلِ دستگاهِ ۶×۶ (حذفِ گاوسی با محور).</summary>
    private static double[] Gauss(double[,] a, double[] b)
    {
        int n = b.Length;
        for (int col = 0; col < n; col++)
        {
            int piv = col;
            for (int r = col + 1; r < n; r++) if (Math.Abs(a[r, col]) > Math.Abs(a[piv, col])) piv = r;
            if (piv != col)
            {
                for (int k = 0; k < n; k++) (a[col, k], a[piv, k]) = (a[piv, k], a[col, k]);
                (b[col], b[piv]) = (b[piv], b[col]);
            }
            var d = Math.Abs(a[col, col]) < 1e-12 ? 1e-12 : a[col, col];
            for (int r = col + 1; r < n; r++)
            {
                var f = a[r, col] / d;
                for (int k = col; k < n; k++) a[r, k] -= f * a[col, k];
                b[r] -= f * b[col];
            }
        }
        var x = new double[n];
        for (int r = n - 1; r >= 0; r--)
        {
            var s = b[r];
            for (int k = r + 1; k < n; k++) s -= a[r, k] * x[k];
            x[r] = s / (Math.Abs(a[r, r]) < 1e-12 ? 1e-12 : a[r, r]);
        }
        return x;
    }

    private static double[] Residuals(List<(double X, double Y, float B, float G, float R)> pts, double[][] coef)
    {
        var res = new double[pts.Count];
        for (int i = 0; i < pts.Count; i++)
        {
            var (x, y, b, g, r) = pts[i];
            var f = Basis(x, y);
            double eb = b, eg = g, er = r;
            for (int j = 0; j < 6; j++) { eb -= coef[0][j] * f[j]; eg -= coef[1][j] * f[j]; er -= coef[2][j] * f[j]; }
            res[i] = Math.Max(Math.Abs(eb), Math.Max(Math.Abs(eg), Math.Abs(er)));
        }
        return res;
    }

    private static double Median(double[] v)
    {
        if (v.Length == 0) return 0;
        var s = (double[])v.Clone();
        Array.Sort(s);
        return s[s.Length / 2];
    }

    /// <summary>
    /// فرق با زمینه: dc = فرقِ رنگ در روشناییِ یکسان (بی‌اثر از سایه)، <paramref name="dl"/> = فرقِ روشنایی (منفی = تیره‌تر).
    /// </summary>
    private static Mat Components(Mat img, double[][] coef, out Mat dl)
    {
        int w = img.Cols, h = img.Rows;
        var dc = new Mat(h, w, MatType.CV_32FC1);
        var dlm = new Mat(h, w, MatType.CV_32FC1);
        Parallel.For(0, h, y =>
        {
            float* p = (float*)img.Ptr(y);
            float* pc = (float*)dc.Ptr(y);
            float* pl = (float*)dlm.Ptr(y);
            var ny = y / (double)(h - 1) * 2 - 1;
            for (int x = 0; x < w; x++, p += 3)
            {
                var f = Basis(x / (double)(w - 1) * 2 - 1, ny);
                float bb = 0, bg = 0, br = 0;
                for (int j = 0; j < 6; j++) { bb += (float)(coef[0][j] * f[j]); bg += (float)(coef[1][j] * f[j]); br += (float)(coef[2][j] * f[j]); }
                float L = Px.Wb * p[0] + Px.Wg * p[1] + Px.Wr * p[2];
                float Lb = Math.Max(0.02f, Px.Wb * bb + Px.Wg * bg + Px.Wr * br);
                var s = L / Lb;
                pc[x] = Math.Max(Math.Abs(p[0] - bb * s), Math.Max(Math.Abs(p[1] - bg * s), Math.Abs(p[2] - br * s)));
                pl[x] = L - Lb;
            }
        });
        dl = dlm;
        return dc;
    }

    /// <summary>شدتِ لبه (سوبل روی روشنایی): پله‌ای به اندازهٔ s ⇒ حدودِ s.</summary>
    private static Mat Gradient(Mat img)
    {
        using var y = Px.Luma(img);
        using var gx = new Mat(); Cv2.Sobel(y, gx, MatType.CV_32F, 1, 0, 3);
        using var gy = new Mat(); Cv2.Sobel(y, gy, MatType.CV_32F, 0, 1, 3);
        var m = new Mat(); Cv2.Magnitude(gx, gy, m);
        Cv2.Multiply(m, Scalar.All(0.25), m);
        return m;
    }

    /// <summary>میانهٔ یک نقشه روی حاشیهٔ ۴٪ (سطحِ نویزِ زمینه).</summary>
    private static double BorderMedian(Mat m)
    {
        int w = m.Cols, h = m.Rows, bw = Math.Max(2, (int)(Math.Min(w, h) * 0.04));
        var v = new List<double>();
        for (int y = 0; y < h; y += 2)
        {
            float* p = (float*)m.Ptr(y);
            for (int x = 0; x < w; x += 2)
                if (x < bw || x >= w - bw || y < bw || y >= h - bw) v.Add(p[x]);
        }
        return Median(v.ToArray());
    }

    private static HashSet<int> BorderLabels(Mat labels)
    {
        int w = labels.Cols, h = labels.Rows;
        var set = new HashSet<int>();
        int* top = (int*)labels.Ptr(0), bottom = (int*)labels.Ptr(h - 1);
        for (int x = 0; x < w; x++) { set.Add(top[x]); set.Add(bottom[x]); }
        for (int y = 0; y < h; y++) { int* r = (int*)labels.Ptr(y); set.Add(r[0]); set.Add(r[w - 1]); }
        set.Remove(0);
        return set;
    }

    // ───────────── برش ─────────────

    private static void RunGrabCut(Mat img8, Mat gc, Rect? rect)
    {
        using var bgd = new Mat();
        using var fgd = new Mat();
        if (rect is { } r) Cv2.GrabCut(img8, gc, r, bgd, fgd, 5, GrabCutModes.InitWithRect);
        else Cv2.GrabCut(img8, gc, new Rect(), bgd, fgd, 5, GrabCutModes.InitWithMask);
    }

    /// <summary>کالا (۲۵۵) / زمینه (۰)، بی خال‌های ریز.</summary>
    private static Mat Binary(Mat gc)
    {
        int w = gc.Cols, h = gc.Rows;
        var bin = new Mat(h, w, MatType.CV_8UC1);
        for (int y = 0; y < h; y++)
        {
            byte* g = (byte*)gc.Ptr(y);
            byte* b = (byte*)bin.Ptr(y);
            for (int x = 0; x < w; x++) b[x] = g[x] is Fgd or PrFgd ? (byte)255 : (byte)0;
        }
        using var k = Cv2.GetStructuringElement(MorphShapes.Ellipse, new Size(3, 3));
        Cv2.MorphologyEx(bin, bin, MorphTypes.Open, k);
        // تکه‌های خیلی کوچکِ جدا (نویز، گرد و غبار) ⇒ زمینه؛ بزرگ‌ترین تکه همیشه می‌ماند
        using var labels = new Mat(); using var stats = new Mat(); using var cent = new Mat();
        var n = Cv2.ConnectedComponentsWithStats(bin, labels, stats, cent);
        if (n > 2)
        {
            int largest = 0;
            for (int i = 1; i < n; i++) largest = Math.Max(largest, stats.At<int>(i, (int)ConnectedComponentsTypes.Area));
            var minArea = Math.Max(largest * 0.02, w * h * 0.0015);
            for (int i = 1; i < n; i++)
            {
                if (stats.At<int>(i, (int)ConnectedComponentsTypes.Area) >= minArea) continue;
                using var sel = new Mat(); Cv2.Compare(labels, Scalar.All(i), sel, CmpType.EQ);
                bin.SetTo(Scalar.All(0), sel);
            }
        }
        return bin;
    }

    private static double BorderTouch(Mat bin)
    {
        int w = bin.Cols, h = bin.Rows, on = 0;
        byte* top = (byte*)bin.Ptr(0), bottom = (byte*)bin.Ptr(h - 1);
        for (int x = 0; x < w; x++) { if (top[x] != 0) on++; if (bottom[x] != 0) on++; }
        for (int y = 0; y < h; y++) { byte* r = (byte*)bin.Ptr(y); if (r[0] != 0) on++; if (r[w - 1] != 0) on++; }
        return on / (double)(2 * (w + h));
    }

    // ───────────── لبهٔ نرم ─────────────

    /// <summary>
    /// ماسکِ دودوییِ کوچک ⇒ ماسکِ نرم در اندازهٔ اصلی. در نوارِ لبه: α = تصویرِ (رنگ − زمینه) روی (کالا − زمینه)،
    /// با رنگِ کالا و زمینهٔ همان نزدیکی (همگشتِ نرمال‌شده). بیرونِ نوار: همان ۰ یا ۱.
    /// </summary>
    private static Mat Refine(Mat bgrFull, Mat bin)
    {
        int W = bgrFull.Cols, H = bgrFull.Rows;
        using var img = Resized(bgrFull, RefineSide, InterpolationFlags.Area);
        int w = img.Cols, h = img.Rows;
        using var binF = new Mat(); bin.ConvertTo(binF, MatType.CV_32FC1, 1 / 255.0);
        using var up = new Mat(); Cv2.Resize(binF, up, new Size(w, h), 0, 0, InterpolationFlags.Linear);
        var f = w / (double)bin.Cols;
        using var hard = new Mat(); Cv2.Threshold(up, hard, 0.5, 1, ThresholdTypes.Binary);
        // نوار: جایی که بزرگ‌نمایی نیمه‌راه است، کمی پهن‌تر
        using var ramp = new Mat(h, w, MatType.CV_8UC1, Scalar.All(0));
        using (var lo = new Mat()) using (var hi = new Mat())
        {
            Cv2.Compare(up, Scalar.All(0.01), lo, CmpType.GT);
            Cv2.Compare(up, Scalar.All(0.99), hi, CmpType.LT);
            Cv2.BitwiseAnd(lo, hi, ramp);
        }
        var r = Math.Max(3, (int)Math.Ceiling(1.5 * f));
        using var ker = Cv2.GetStructuringElement(MorphShapes.Ellipse, new Size(2 * r + 1, 2 * r + 1));
        using var band = new Mat(); Cv2.Dilate(ramp, band, ker);

        // رنگِ زمینه و رنگِ کالا در همسایگی
        using var bgc = Matte.EstimateBackground(img, hard);
        using var inner = new Mat(); Cv2.Erode(hard, inner, ker);
        using var inner3 = new Mat(); Cv2.Merge(new[] { inner, inner, inner }, inner3);
        using var fin = new Mat(); Cv2.Multiply(img, inner3, fin);
        var sigma = Math.Max(2, Math.Max(w, h) * 0.006);
        using var num0 = Px.Gaussian(fin, sigma);
        using var den = Px.Gaussian(inner, sigma);
        using var den3 = new Mat(); Cv2.Merge(new[] { den, den, den }, den3);
        Cv2.Max(den3, Scalar.All(1e-4), den3);
        using var num = new Mat(); Cv2.Divide(num0, den3, num);   // رنگِ کالا در همسایگی

        var a = hard.Clone();
        Parallel.For(0, h, y =>
        {
            byte* pb = (byte*)band.Ptr(y);
            float* pa = (float*)a.Ptr(y);
            float* pi = (float*)img.Ptr(y);
            float* pg = (float*)bgc.Ptr(y);
            float* pn = (float*)num.Ptr(y);
            float* pd = (float*)den.Ptr(y);
            for (int x = 0; x < w; x++, pi += 3, pg += 3, pn += 3)
            {
                if (pb[x] == 0 || pd[x] < 0.02f) continue;
                var v = Matte.MixAlpha(pi, pn, pg, out var ok);
                if (ok) pa[x] = v;   // نه ⇒ کالا هم‌رنگِ زمینه ⇒ همان لبهٔ GrabCut
            }
        });
        using (var soft = Px.Gaussian(a, 0.7)) soft.CopyTo(a, band);
        if (w == W && h == H) return a;
        var full = new Mat(); Cv2.Resize(a, full, new Size(W, H), 0, 0, InterpolationFlags.Linear);
        a.Dispose();
        return full;
    }

    private static Mat Resized(Mat src, int maxSide, InterpolationFlags interp)
    {
        var k = Math.Min(1.0, maxSide / (double)Math.Max(src.Cols, src.Rows));
        var d = new Mat();
        if (k >= 1) src.CopyTo(d);
        else Cv2.Resize(src, d, new Size(Math.Max(8, (int)Math.Round(src.Cols * k)), Math.Max(8, (int)Math.Round(src.Rows * k))), 0, 0, interp);
        return d;
    }
}
