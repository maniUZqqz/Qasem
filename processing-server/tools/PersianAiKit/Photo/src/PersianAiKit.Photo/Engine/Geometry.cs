using OpenCvSharp;

namespace PersianAiKit.Photo.Engine;

/// <summary>اصلاحِ لنز (اعوجاج، تاریکیِ گوشه)، چرخش (با بزرگ‌نماییِ خودکار تا گوشهٔ خالی نماند)، برش و قرینه — روی رنگ و شفافیت با هم.</summary>
internal static unsafe class Geometry
{
    public static void Apply(PhotoImage img, Recipe r)
    {
        var dist = r.Get("distortion");
        if (dist != 0) Remap(img, dist);
        var lv = r.Get("lensVignette");
        if (lv > 0) LensVignette(img.Color, lv);
        var c = r.Crop;
        if (c is null) return;
        if (c.Angle != 0) Rotate(img, c.Angle);
        if (c.X > 0 || c.Y > 0 || c.W < 1 || c.H < 1)
        {
            int x = (int)Math.Round(c.X * img.Width), y = (int)Math.Round(c.Y * img.Height);
            int w = Math.Max(1, Math.Min(img.Width - x, (int)Math.Round(c.W * img.Width)));
            int h = Math.Max(1, Math.Min(img.Height - y, (int)Math.Round(c.H * img.Height)));
            var rect = new Rect(Math.Clamp(x, 0, img.Width - 1), Math.Clamp(y, 0, img.Height - 1), w, h);
            img.ReplaceColor(new Mat(img.Color, rect).Clone());
            if (img.Alpha is not null) { var a = new Mat(img.Alpha, rect).Clone(); img.Alpha.Dispose(); img.Alpha = a; }
        }
        if (c.FlipH || c.FlipV)
        {
            var mode = c.FlipH && c.FlipV ? FlipMode.XY : c.FlipH ? FlipMode.Y : FlipMode.X;
            Cv2.Flip(img.Color, img.Color, mode);
            if (img.Alpha is not null) Cv2.Flip(img.Alpha, img.Alpha, mode);
        }
    }

    /// <summary>بزرگ‌نمایی که تصویرِ چرخیده کلِ قاب را بپوشاند.</summary>
    public static double CoverZoom(int w, int h, double angle)
    {
        var a = Math.Abs(angle) * Math.PI / 180;
        double cos = Math.Cos(a), sin = Math.Sin(a);
        return Math.Max((w * cos + h * sin) / w, (w * sin + h * cos) / h);
    }

    private static void Rotate(PhotoImage img, double angle)
    {
        var center = new Point2f(img.Width / 2f, img.Height / 2f);
        using var m = Cv2.GetRotationMatrix2D(center, angle, CoverZoom(img.Width, img.Height, angle));
        var dst = new Mat();
        Cv2.WarpAffine(img.Color, dst, m, img.Color.Size(), InterpolationFlags.Cubic, BorderTypes.Reflect101);
        img.ReplaceColor(dst);
        if (img.Alpha is not null)
        {
            var a = new Mat();
            Cv2.WarpAffine(img.Alpha, a, m, img.Alpha.Size(), InterpolationFlags.Linear, BorderTypes.Replicate);
            img.Alpha.Dispose(); img.Alpha = a;
        }
    }

    /// <summary>مثبت ⇒ رفعِ حالتِ بشکه‌ای؛ منفی ⇒ رفعِ حالتِ بالشتکی (مدلِ شعاعیِ یک‌ضریبی).</summary>
    private static void Remap(PhotoImage img, double distortion)
    {
        int w = img.Width, h = img.Height;
        double k = -distortion / 100 * 0.25;
        double cx = (w - 1) / 2.0, cy = (h - 1) / 2.0, R = Math.Sqrt(cx * cx + cy * cy);
        double norm = k > 0 ? 1 / (1 + k) : 1;   // تا گوشهٔ خالی نماند
        using var mx = new Mat(h, w, MatType.CV_32FC1);
        using var my = new Mat(h, w, MatType.CV_32FC1);
        Parallel.For(0, h, y =>
        {
            float* px = (float*)mx.Ptr(y);
            float* py = (float*)my.Ptr(y);
            for (int x = 0; x < w; x++)
            {
                double nx = (x - cx) / R, ny = (y - cy) / R;
                var f = (1 + k * (nx * nx + ny * ny)) * norm;
                px[x] = (float)(cx + nx * f * R);
                py[x] = (float)(cy + ny * f * R);
            }
        });
        var dst = new Mat();
        Cv2.Remap(img.Color, dst, mx, my, InterpolationFlags.Cubic, BorderTypes.Reflect101);
        img.ReplaceColor(dst);
        if (img.Alpha is not null)
        {
            var a = new Mat();
            Cv2.Remap(img.Alpha, a, mx, my, InterpolationFlags.Linear, BorderTypes.Replicate);
            img.Alpha.Dispose(); img.Alpha = a;
        }
    }

    private static void LensVignette(Mat bgr, double amount)
    {
        int w = bgr.Cols, h = bgr.Rows;
        float cx = (w - 1) / 2f, cy = (h - 1) / 2f, k = (float)(amount / 100 * 0.9);
        Parallel.For(0, h, y =>
        {
            float* p = (float*)bgr.Ptr(y);
            var ny = (y - cy) / cy;
            for (int x = 0; x < w; x++, p += 3)
            {
                var nx = (x - cx) / cx;
                var g = 1 + k * (nx * nx + ny * ny) / 2;
                p[0] *= g; p[1] *= g; p[2] *= g;
            }
        });
    }
}

/// <summary>وینیتِ هنری (بعد از برش) و دانهٔ فیلمی.</summary>
internal static unsafe class Effects
{
    public static void Apply(Mat bgr, Recipe r, double scale)
    {
        var v = r.Get("vignette");
        if (v != 0) Vignette(bgr, v / 100, r.Get("vignetteMidpoint") / 100, r.Get("vignetteFeather") / 100);
        var g = r.Get("grain");
        if (g > 0) Grain(bgr, g / 100, r.Get("grainSize") / 100, scale);
    }

    private static void Vignette(Mat bgr, double amount, double mid, double feather)
    {
        int w = bgr.Cols, h = bgr.Rows;
        float cx = (w - 1) / 2f, cy = (h - 1) / 2f, a = (float)amount;
        float inner = (float)(0.15 + mid * 0.7), outer = inner + (float)(0.05 + feather * 0.8);
        Parallel.For(0, h, y =>
        {
            float* p = (float*)bgr.Ptr(y);
            var ny = (y - cy) / cy;
            for (int x = 0; x < w; x++, p += 3)
            {
                var nx = (x - cx) / cx;
                var d = MathF.Sqrt((nx * nx + ny * ny) / 2);
                var m = Px.Smoothstep(inner, outer, d) * Math.Abs(a) * 0.85f;
                if (a < 0) { var k = 1 - m; p[0] *= k; p[1] *= k; p[2] *= k; }
                else { p[0] += (1 - p[0]) * m; p[1] += (1 - p[1]) * m; p[2] += (1 - p[2]) * m; }
            }
        });
    }

    /// <summary>دانهٔ روشنایی با بذرِ ثابت ⇒ پیش‌نمایش و خروجی یک دانه دارند. اندازهٔ دانه به نسبتِ اندازهٔ اصلی است.</summary>
    private static void Grain(Mat bgr, double amount, double size, double scale)
    {
        var cell = Math.Max(1.0, (1 + size * 4) * scale);
        int gw = Math.Max(2, (int)(bgr.Cols / cell)), gh = Math.Max(2, (int)(bgr.Rows / cell));
        using var noise = new Mat(gh, gw, MatType.CV_32FC1);
        var rnd = new Random(1405);
        for (int y = 0; y < gh; y++)
        {
            float* p = (float*)noise.Ptr(y);
            for (int x = 0; x < gw; x++)
            {
                double u1 = 1 - rnd.NextDouble(), u2 = rnd.NextDouble();
                p[x] = (float)(Math.Sqrt(-2 * Math.Log(u1)) * Math.Cos(2 * Math.PI * u2));
            }
        }
        using var big = new Mat();
        Cv2.Resize(noise, big, bgr.Size(), 0, 0, InterpolationFlags.Cubic);
        float k = (float)(amount * 0.09);
        int w = bgr.Cols;
        Parallel.For(0, bgr.Rows, y =>
        {
            float* p = (float*)bgr.Ptr(y);
            float* n = (float*)big.Ptr(y);
            for (int x = 0; x < w; x++, p += 3)
            {
                var l = Math.Clamp(Px.Wr * p[2] + Px.Wg * p[1] + Px.Wb * p[0], 0f, 1f);
                var d = n[x] * k * (0.4f + 2.4f * l * (1 - l));
                p[0] += d; p[1] += d; p[2] += d;
            }
        });
    }
}

/// <summary>ترمیمِ لکه، خش و گردوغبار (inpaint): ناحیه از روی اطرافش پر می‌شود.</summary>
internal static class Retouch
{
    public static void Heal(Mat bgr, IReadOnlyList<Spot> spots)
    {
        int w = bgr.Cols, h = bgr.Rows, minSide = Math.Min(w, h);
        using var mask = new Mat(h, w, MatType.CV_8UC1, Scalar.All(0));
        var maxR = 0;
        foreach (var s in spots)
        {
            var r = Math.Max(1, (int)Math.Round(s.R * minSide));
            maxR = Math.Max(maxR, r);
            Cv2.Circle(mask, new Point((int)Math.Round(s.X * (w - 1)), (int)Math.Round(s.Y * (h - 1))), r, Scalar.All(255), -1, LineTypes.AntiAlias);
        }
        using var c8 = new Mat(); bgr.ConvertTo(c8, MatType.CV_8UC3, 255);
        using var healed = new Mat();
        Cv2.Inpaint(c8, mask, healed, Math.Max(3, maxR * 0.25), InpaintMethod.Telea);
        using var hf = new Mat(); healed.ConvertTo(hf, MatType.CV_32FC3, 1 / 255.0);
        hf.CopyTo(bgr, mask);
    }
}
