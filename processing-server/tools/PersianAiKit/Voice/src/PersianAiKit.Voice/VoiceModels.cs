namespace PersianAiKit;

/// <summary>
/// جای مدل‌های صدا. ساختارِ پوشهٔ models:
/// <code>
///   models/piper/piper/piper.exe          موتورِ متن‌به‌گفتار (+ espeak-ng-data و dllها)
///   models/piper/voices/*.onnx (+ .json)   صداهای فارسی
///   models/vosk/vosk-model-small-fa-0.42/  مدلِ گفتار‌به‌متن
///   models/tts، sfx، text، clone           مدل‌های سرویسِ پایتونیِ صدا (voice\ — VOICE-SETUP.md)
/// </code>
/// </summary>
public sealed class VoiceModels
{
    public const string EnvironmentVariable = "PERSIAN_VOICE_MODELS";

    public VoiceModels(string root) => Root = Path.GetFullPath(root);

    public string Root { get; }

    public string PiperExe => Path.Combine(Root, "piper", "piper", OperatingSystem.IsWindows() ? "piper.exe" : "piper");

    public string VoicesDir => Path.Combine(Root, "piper", "voices");

    /// <summary>نخستین پوشهٔ مدلِ Vosk زیرِ models/vosk (پوشه‌ای که «am» دارد).</summary>
    public string VoskModelDir
    {
        get
        {
            var dir = Path.Combine(Root, "vosk");
            var preferred = Path.Combine(dir, "vosk-model-small-fa-0.42");
            if (Directory.Exists(preferred)) return preferred;
            if (!Directory.Exists(dir)) return preferred;
            return Directory.GetDirectories(dir).OrderBy(d => d).FirstOrDefault(d => Directory.Exists(Path.Combine(d, "am"))) ?? preferred;
        }
    }

    /// <summary>
    /// پوشهٔ models را پیدا می‌کند: اول مسیرِ داده‌شده، بعد متغیرِ محیطیِ PERSIAN_VOICE_MODELS، بعد از کنارِ برنامه و
    /// پوشهٔ جاری رو به بالا (تا ۸ پله) — پس هم با dotnet run از داخلِ src و هم از خروجیِ publish کار می‌کند.
    /// </summary>
    public static VoiceModels Find(string? explicitRoot = null)
    {
        if (!string.IsNullOrWhiteSpace(explicitRoot))
        {
            if (!Directory.Exists(explicitRoot)) throw new DirectoryNotFoundException("پوشهٔ مدل‌ها نیست: " + Path.GetFullPath(explicitRoot));
            return new VoiceModels(explicitRoot);
        }
        var env = Environment.GetEnvironmentVariable(EnvironmentVariable);
        if (!string.IsNullOrWhiteSpace(env) && Directory.Exists(env)) return new VoiceModels(env);

        foreach (var start in new[] { AppContext.BaseDirectory, Directory.GetCurrentDirectory() })
        {
            var d = new DirectoryInfo(start);
            for (var i = 0; i < 8 && d is not null; i++, d = d.Parent)
            {
                var candidate = Path.Combine(d.FullName, "models");
                if (Directory.Exists(Path.Combine(candidate, "piper")) || Directory.Exists(Path.Combine(candidate, "vosk")))
                    return new VoiceModels(candidate);
            }
        }
        throw new DirectoryNotFoundException(
            $"پوشهٔ models پیدا نشد. مسیرش را بدهید (VoiceModels.Find(@\"...\\models\")) یا متغیرِ محیطیِ {EnvironmentVariable} را بگذارید.");
    }

    public override string ToString() => Root;
}
