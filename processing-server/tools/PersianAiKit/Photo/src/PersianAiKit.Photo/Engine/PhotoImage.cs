using OpenCvSharp;

namespace PersianAiKit.Photo.Engine;

/// <summary>عکس در حینِ کار: رنگ به‌صورتِ BGRِ اعشاری (۰ تا ۱) و در صورتِ وجود، شفافیت (۰ تا ۱).</summary>
public sealed class PhotoImage : IDisposable
{
    public PhotoImage(Mat color, Mat? alpha = null)
    {
        Color = color;
        Alpha = alpha;
    }

    /// <summary>CV_32FC3، BGR، ۰ تا ۱.</summary>
    public Mat Color { get; private set; }

    /// <summary>CV_32FC1، ۰ تا ۱ (۱ = کاملاً دیده می‌شود). null ⇒ بی‌شفافیت.</summary>
    public Mat? Alpha { get; set; }

    public int Width => Color.Cols;
    public int Height => Color.Rows;

    public PhotoImage Clone() => new(Color.Clone(), Alpha?.Clone());

    public void ReplaceColor(Mat m)
    {
        if (!ReferenceEquals(m, Color)) Color.Dispose();
        Color = m;
    }

    /// <summary>کوچک‌شده تا ضلعِ بلندتر حداکثر <paramref name="maxSide"/> (بزرگ نمی‌کند).</summary>
    public PhotoImage Downscaled(int maxSide)
    {
        var k = Math.Min(1.0, maxSide / (double)Math.Max(Width, Height));
        if (k >= 1) return Clone();
        var size = new Size(Math.Max(1, (int)Math.Round(Width * k)), Math.Max(1, (int)Math.Round(Height * k)));
        var c = new Mat();
        Cv2.Resize(Color, c, size, 0, 0, InterpolationFlags.Area);
        Mat? a = null;
        if (Alpha is not null) { a = new Mat(); Cv2.Resize(Alpha, a, size, 0, 0, InterpolationFlags.Area); }
        return new PhotoImage(c, a);
    }

    public void Dispose()
    {
        Color.Dispose();
        Alpha?.Dispose();
    }
}

/// <summary>خواندن و نوشتنِ فایلِ عکس.</summary>
public static class PhotoIO
{
    public const long MaxPixels = 60_000_000;

    /// <summary>
    /// JPEG، PNG (با شفافیت)، WebP، BMP، TIFF — ۸ یا ۱۶ بیتی. چرخشِ EXIFِ گوشی اعمال می‌شود.
    /// </summary>
    public static PhotoImage Decode(byte[] bytes)
    {
        if (bytes is null || bytes.Length == 0) throw new InvalidDataException("فایلِ عکس خالی است.");
        using var raw = Cv2.ImDecode(bytes, ImreadModes.Unchanged);
        if (raw.Empty())
            throw new InvalidDataException("این فایل عکس نیست یا قالبش پشتیبانی نمی‌شود (JPEG، PNG، WebP، BMP، TIFF). HEIC را اول به JPEG تبدیل کنید.");
        if ((long)raw.Rows * raw.Cols > MaxPixels) throw new InvalidDataException($"عکس خیلی بزرگ است (بیش از {MaxPixels / 1_000_000} مگاپیکسل).");
        var depth = raw.Depth();
        var scale = depth == MatType.CV_16U ? 1 / 65535.0 : depth == MatType.CV_32F ? 1.0 : 1 / 255.0;

        if (raw.Channels() == 4)
        {
            var ch = Cv2.Split(raw);
            try
            {
                using var bgr = new Mat();
                Cv2.Merge(new[] { ch[0], ch[1], ch[2] }, bgr);
                var color = new Mat();
                bgr.ConvertTo(color, MatType.CV_32FC3, scale);
                var alpha = new Mat();
                ch[3].ConvertTo(alpha, MatType.CV_32FC1, scale);
                return new PhotoImage(color, alpha);
            }
            finally { foreach (var c in ch) c.Dispose(); }
        }
        // رنگی/خاکستری: با Color تا چرخشِ EXIF هم اعمال شود؛ AnyDepth تا ۱۶ بیت بماند
        using var col = Cv2.ImDecode(bytes, ImreadModes.Color | ImreadModes.AnyDepth);
        var d2 = col.Depth();
        var s2 = d2 == MatType.CV_16U ? 1 / 65535.0 : d2 == MatType.CV_32F ? 1.0 : 1 / 255.0;
        var result = new Mat();
        col.ConvertTo(result, MatType.CV_32FC3, s2);
        return new PhotoImage(result);
    }

    /// <summary>jpeg، png یا webp. شفافیت فقط در png و webp می‌ماند.</summary>
    public static byte[] Encode(PhotoImage img, string format = "jpeg", int quality = 90)
    {
        format = (format ?? "jpeg").ToLowerInvariant();
        using var c8 = new Mat();
        img.Color.ConvertTo(c8, MatType.CV_8UC3, 255);
        Mat toWrite = c8;
        Mat? bgra = null;
        try
        {
            if (img.Alpha is not null && format is "png" or "webp")
            {
                using var a8 = new Mat();
                img.Alpha.ConvertTo(a8, MatType.CV_8UC1, 255);
                var ch = Cv2.Split(c8);
                bgra = new Mat();
                Cv2.Merge(new[] { ch[0], ch[1], ch[2], a8 }, bgra);
                foreach (var m in ch) m.Dispose();
                toWrite = bgra;
            }
            var (ext, prms) = format switch
            {
                "png" => (".png", new[] { new ImageEncodingParam(ImwriteFlags.PngCompression, 6) }),
                "webp" => (".webp", new[] { new ImageEncodingParam(ImwriteFlags.WebPQuality, Math.Clamp(quality, 1, 100)) }),
                _ => (".jpg", new[] { new ImageEncodingParam(ImwriteFlags.JpegQuality, Math.Clamp(quality, 1, 100)) }),
            };
            Cv2.ImEncode(ext, toWrite, out var bytes, prms);
            return bytes;
        }
        finally { bgra?.Dispose(); }
    }

    public static string ContentType(string format) => format switch { "png" => "image/png", "webp" => "image/webp", _ => "image/jpeg" };
    public static string Extension(string format) => format switch { "png" => ".png", "webp" => ".webp", _ => ".jpg" };
}
