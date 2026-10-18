using OpenCvSharp;
using PersianAiKit.Photo.Ai;

namespace PersianAiKit.Photo.Engine;

/// <summary>
/// آخرِ کار: تمیزکاریِ لبهٔ کالا، بزرگ‌نماییِ هوشمند، قابِ مربعِ فروشگاه، تغییرِ اندازه، و در آخر گذاشتن روی رنگِ تازه (با سایه) و شارپِ نهایی.
/// رنگِ تازه و سایه عمداً آخر از همه است: سایه روی قابِ نهایی ساخته می‌شود و هیچ‌جا بریده نمی‌شود.
/// </summary>
public static class Output
{
    /// <param name="preview">پیش‌نمایش: بی بزرگ‌نمایی و بی تغییرِ اندازه (فقط چیدمانِ قاب).</param>
    public static PhotoImage Finalize(PhotoImage img, Recipe r, Upscaler? upscaler, bool preview)
    {
        var o = r.Output ?? new OutputSettings();
        var bg = r.Background;
        var cur = img.Clone();
        try
        {
            // محدودهٔ کالا (برای قابِ مربع)
            Rect? subject = cur.Alpha is null ? null : SubjectBox(cur.Alpha);

            bool removing = bg is { Remove: true } && cur.Alpha is not null;
            bool transparent = removing && bg!.Color == "transparent";
            (double R, double G, double B) fill = (1, 1, 1);
            if (removing)
            {
                var cleanup = bg!.Cleanup >= 0 ? bg.Cleanup / 100 : Matte.AutoCleanup(cur.Color, cur.Alpha!).Cleanup / 100;
                var (fg, a) = Matte.Clean(cur.Color, cur.Alpha!, cleanup);
                cur.ReplaceColor(fg);
                cur.Alpha!.Dispose(); cur.Alpha = a;
                if (!transparent) PhotoColor.TryParse(bg.Color, out fill);
            }

            if (!preview && o.Upscale > 1 && upscaler is { Available: true })
            {
                var up = upscaler.Upscale(cur.Color, o.Upscale);
                var sx = up.Cols / (double)cur.Width;
                cur.ReplaceColor(up);
                if (cur.Alpha is not null)
                {
                    var a = new Mat(); Cv2.Resize(cur.Alpha, a, up.Size(), 0, 0, InterpolationFlags.Cubic);
                    cur.Alpha.Dispose(); cur.Alpha = a;
                }
                if (subject is { } s) subject = new Rect((int)(s.X * sx), (int)(s.Y * sx), (int)(s.Width * sx), (int)(s.Height * sx));
            }

            if (o.Square)
            {
                var sq = SquareCanvas(cur, subject, o.Padding, preview ? 0 : o.LongEdge, fill);
                cur.Dispose();
                cur = sq;
            }
            else if (!preview && o.LongEdge > 0 && Math.Max(cur.Width, cur.Height) != o.LongEdge)
            {
                var k = o.LongEdge / (double)Math.Max(cur.Width, cur.Height);
                var size = new Size(Math.Max(1, (int)Math.Round(cur.Width * k)), Math.Max(1, (int)Math.Round(cur.Height * k)));
                var interp = k < 1 ? InterpolationFlags.Area : InterpolationFlags.Lanczos4;
                var c2 = new Mat(); Cv2.Resize(cur.Color, c2, size, 0, 0, interp); cur.ReplaceColor(c2);
                if (cur.Alpha is not null) { var a = new Mat(); Cv2.Resize(cur.Alpha, a, size, 0, 0, interp); cur.Alpha.Dispose(); cur.Alpha = a; }
            }

            // رنگِ تازه (و سایه) روی قابِ نهایی. عکسِ شفاف (PNG) با خروجیِ JPEG ⇒ روی سفید
            if (cur.Alpha is not null && !transparent && (removing || o.Format == "jpeg"))
            {
                Px.Clamp01(cur.Alpha);
                var comp = Matte.Composite(cur.Color, cur.Alpha, fill, removing ? bg!.Shadow : 0);
                cur.ReplaceColor(comp);
                cur.Alpha.Dispose(); cur.Alpha = null;
            }

            if (o.Sharpen > 0) Detail.Sharpen(cur.Color, o.Sharpen / 100 * 0.7, 0.8, 0.1);
            Px.Clamp01(cur.Color);
            if (cur.Alpha is not null) Px.Clamp01(cur.Alpha);
            return cur;
        }
        catch
        {
            cur.Dispose();
            throw;
        }
    }

    /// <summary>کادرِ کالا: جایی که ماسک بالای ۰٫۵ است (null ⇒ کلِ عکس).</summary>
    public static Rect? SubjectBox(Mat alpha)
    {
        using var m = new Mat();
        Cv2.Threshold(alpha, m, 0.5, 255, ThresholdTypes.Binary);
        using var m8 = new Mat(); m.ConvertTo(m8, MatType.CV_8UC1);
        var r = Cv2.BoundingRect(m8);
        return r.Width < 2 || r.Height < 2 ? null : r;
    }

    /// <summary>کالا وسطِ قابِ مربع با حاشیه. شفافیت (اگر هست) هم‌راهش می‌آید؛ بیرونِ کالا شفاف و به رنگِ <paramref name="fill"/>.</summary>
    private static PhotoImage SquareCanvas(PhotoImage img, Rect? subject, double padding, int side, (double R, double G, double B) fill)
    {
        var box = subject ?? new Rect(0, 0, img.Width, img.Height);
        box = box.Intersect(new Rect(0, 0, img.Width, img.Height));
        var inner = Math.Max(box.Width, box.Height);
        if (side <= 0) side = (int)Math.Round(inner / Math.Max(0.2, 1 - 2 * padding));
        var target = side * (1 - 2 * padding);
        var k = target / inner;
        var size = new Size(Math.Max(1, (int)Math.Round(box.Width * k)), Math.Max(1, (int)Math.Round(box.Height * k)));
        var interp = k < 1 ? InterpolationFlags.Area : InterpolationFlags.Lanczos4;
        using var content = new Mat(img.Color, box);
        using var scaled = new Mat(); Cv2.Resize(content, scaled, size, 0, 0, interp);
        var canvas = new Mat(side, side, MatType.CV_32FC3, new Scalar(fill.B, fill.G, fill.R));
        int ox = (side - size.Width) / 2, oy = (side - size.Height) / 2;
        var dst = new Rect(ox, oy, size.Width, size.Height).Intersect(new Rect(0, 0, side, side));
        using (var roi = new Mat(canvas, dst)) new Mat(scaled, new Rect(0, 0, dst.Width, dst.Height)).CopyTo(roi);
        Mat? alpha = null;
        if (img.Alpha is not null)
        {
            alpha = new Mat(side, side, MatType.CV_32FC1, Scalar.All(0));
            using var ac = new Mat(img.Alpha, box);
            using var asz = new Mat(); Cv2.Resize(ac, asz, size, 0, 0, interp);
            using var roiA = new Mat(alpha, dst);
            new Mat(asz, new Rect(0, 0, dst.Width, dst.Height)).CopyTo(roiA);
        }
        return new PhotoImage(canvas, alpha);
    }
}
