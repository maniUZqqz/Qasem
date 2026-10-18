namespace PersianAiKit.Photo;

/// <summary>
/// جای مدل‌های هوشِ مصنوعی:
/// <code>
///   models/background/birefnet-lite.onnx        حذفِ پس‌زمینه (BiRefNet-lite، MIT)
///   models/upscale/realesr-general-x4v3.onnx    بزرگ‌نمایی و بهبودِ جزئیات (Real-ESRGAN، BSD-3)
/// </code>
/// ابزارهای معمولی (نور، رنگ، شارپ، …) مدل نمی‌خواهند.
/// </summary>
public sealed class PhotoModels
{
    public const string EnvironmentVariable = "PERSIAN_PHOTO_MODELS";

    public PhotoModels(string root) => Root = Path.GetFullPath(root);

    public string Root { get; }
    public string Background => Path.Combine(Root, "background", "birefnet-lite.onnx");
    public string Upscale => Path.Combine(Root, "upscale", "realesr-general-x4v3.onnx");

    /// <summary>اول مسیرِ داده‌شده، بعد متغیرِ محیطی، بعد پوشهٔ models از کنارِ برنامه رو به بالا (تا ۸ پله).</summary>
    public static PhotoModels Find(string? explicitRoot = null)
    {
        if (!string.IsNullOrWhiteSpace(explicitRoot))
        {
            if (!Directory.Exists(explicitRoot)) throw new DirectoryNotFoundException("پوشهٔ مدل‌ها نیست: " + Path.GetFullPath(explicitRoot));
            return new PhotoModels(explicitRoot);
        }
        var env = Environment.GetEnvironmentVariable(EnvironmentVariable);
        if (!string.IsNullOrWhiteSpace(env) && Directory.Exists(env)) return new PhotoModels(env);
        foreach (var start in new[] { AppContext.BaseDirectory, Directory.GetCurrentDirectory() })
        {
            var d = new DirectoryInfo(start);
            for (var i = 0; i < 8 && d is not null; i++, d = d.Parent)
            {
                var candidate = Path.Combine(d.FullName, "models");
                if (Directory.Exists(Path.Combine(candidate, "background")) || Directory.Exists(Path.Combine(candidate, "upscale")))
                    return new PhotoModels(candidate);
            }
        }
        // مدل‌ها اختیاری‌اند: بی آن‌ها همه‌چیز جز حذفِ پس‌زمینه و بزرگ‌نماییِ هوشمند کار می‌کند
        return new PhotoModels(Path.Combine(AppContext.BaseDirectory, "models"));
    }

    public override string ToString() => Root;
}
