using System.Diagnostics;
using System.Globalization;
using System.Security.Cryptography;
using System.Text;
using PersianAiKit.Text;

namespace PersianAiKit.Tts;

public sealed class PiperTtsOptions
{
    /// <summary>مسیرِ piper.exe (در پوشه‌اش espeak-ng-data و dllها هم باید باشند).</summary>
    public required string PiperExe { get; set; }

    /// <summary>پوشهٔ صداها: هر صدا یک X.onnx و یک X.onnx.json.</summary>
    public required string VoicesDir { get; set; }

    /// <summary>صدای پیش‌فرض. gyro در سنجشِ رفت‌وبرگشت (صدا ⇒ گفتار‌به‌متن) فهمیدنی‌ترین بود: خطای واژه ۴٪ در برابرِ ۱۴٪ِ amir.</summary>
    public string DefaultVoice { get; set; } = "fa_IR-gyro-medium";

    /// <summary>سرعت = length_scaleِ Piper: ۱ عادی، بزرگ‌تر ⇒ آرام‌تر (۱٫۱۵ برای جای پرسروصدا)، کوچک‌تر ⇒ تندتر.</summary>
    public double DefaultSpeed { get; set; } = 1.0;

    /// <summary>پوشهٔ کشِ WAV (هر متنِ تکراری بی‌ساختِ دوباره). null ⇒ بی‌کش.</summary>
    public string? CacheDir { get; set; }

    public int MaxCacheFiles { get; set; } = 1500;

    /// <summary>چند ساختِ هم‌زمان؛ بقیه صف می‌کشند (هر ساخت یک هستهٔ CPU را پر می‌کند).</summary>
    public int MaxConcurrent { get; set; } = 2;

    public int MaxChars { get; set; } = 600;

    /// <summary>مکث بینِ جمله‌ها (ثانیه).</summary>
    public double SentenceSilence { get; set; } = 0.3;

    /// <summary>عدد/ساعت/کدِ لاتین پیش از خواندن به واژهٔ فارسی شوند (<see cref="PersianText.ToSpeakable"/>).</summary>
    public bool MakeSpeakable { get; set; } = true;

    public TimeSpan Timeout { get; set; } = TimeSpan.FromSeconds(40);

    public static PiperTtsOptions From(VoiceModels paths, string? cacheDir = null) =>
        new() { PiperExe = paths.PiperExe, VoicesDir = paths.VoicesDir, CacheDir = cacheDir };
}

/// <summary>
/// متن ⇒ گفتارِ فارسی (WAV) با Piper (https://github.com/rhasspy/piper) — آفلاین، روی CPU، بی‌اینترنت.
/// هر درخواست یک اجرای کوتاهِ piper.exe است (۰٫۵ تا ۲ ثانیه برای یک جمله)؛ نتیجه با هشِ (صدا، سرعت، متن) کش می‌شود.
/// امن برای استفادهٔ هم‌زمان (singleton).
/// </summary>
public sealed class PiperTts
{
    private readonly PiperTtsOptions _o;
    private readonly Action<string>? _log;
    private readonly SemaphoreSlim _gate;

    public PiperTts(PiperTtsOptions options, Action<string>? log = null)
    {
        _o = options;
        _log = log;
        _gate = new SemaphoreSlim(Math.Max(1, options.MaxConcurrent));
    }

    public PiperTts(VoiceModels paths, string? cacheDir = null, Action<string>? log = null) : this(PiperTtsOptions.From(paths, cacheDir), log) { }

    public PiperTtsOptions Options => _o;

    /// <summary>piper.exe و دست‌کم یک صدا هست.</summary>
    public bool Available => File.Exists(_o.PiperExe) && Voices().Count > 0;

    /// <summary>صداهای نصب‌شده (نامِ فایل بی‌پسوند) — مدل و json هر دو باید باشند.</summary>
    public IReadOnlyList<string> Voices()
    {
        try
        {
            return Directory.Exists(_o.VoicesDir)
                ? Directory.GetFiles(_o.VoicesDir, "*.onnx").Where(f => File.Exists(f + ".json"))
                           .Select(Path.GetFileNameWithoutExtension).OfType<string>().OrderBy(n => n).ToList()
                : new List<string>();
        }
        catch { return new List<string>(); }
    }

    /// <summary>صدای پیش‌فرض اگر نصب است، وگرنه نخستین صدای موجود.</summary>
    public string DefaultVoice
    {
        get
        {
            var v = Voices();
            return v.Contains(_o.DefaultVoice) ? _o.DefaultVoice : v.FirstOrDefault() ?? _o.DefaultVoice;
        }
    }

    /// <summary>
    /// متن ⇒ WAVِ PCMِ ۱۶بیتی (۲۲۰۵۰ هرتز، تک‌کاناله). voice/speed خالی ⇒ پیش‌فرض.
    /// متنِ بلندتر از <see cref="PiperTtsOptions.MaxChars"/> بریده می‌شود — متنِ بلند را جمله‌جمله بفرستید.
    /// </summary>
    /// <exception cref="ArgumentException">متن خالی است یا صدا نصب نیست.</exception>
    /// <exception cref="InvalidOperationException">piper نیست یا نساخت (پیامِ خطای piper در متنِ استثنا).</exception>
    public async Task<byte[]> SpeakAsync(string? text, string? voice = null, double? speed = null, CancellationToken ct = default)
    {
        if (!File.Exists(_o.PiperExe)) throw new InvalidOperationException("piper پیدا نشد: " + _o.PiperExe);
        voice = string.IsNullOrWhiteSpace(voice) ? DefaultVoice : voice.Trim();
        var model = Path.Combine(_o.VoicesDir, voice + ".onnx");
        if (!File.Exists(model) || !File.Exists(model + ".json")) throw new ArgumentException("این صدا نصب نیست: " + voice, nameof(voice));
        var scale = Math.Clamp(speed ?? _o.DefaultSpeed, 0.5, 2.0);
        var input = (_o.MakeSpeakable ? PersianText.ToSpeakable(text) : text?.Trim() ?? "").Replace('\r', ' ').Replace('\n', ' ');
        if (input.Length == 0) throw new ArgumentException("متن خالی است.", nameof(text));
        if (input.Length > _o.MaxChars) input = input[.._o.MaxChars];

        var scaleText = scale.ToString("0.00", CultureInfo.InvariantCulture);
        string? cached = null;
        if (_o.CacheDir is { Length: > 0 })
        {
            var key = Convert.ToHexString(SHA1.HashData(Encoding.UTF8.GetBytes(voice + "|" + scaleText + "|" + _o.SentenceSilence + "|" + input)))[..20].ToLowerInvariant();
            cached = Path.Combine(_o.CacheDir, key + ".wav");
            if (File.Exists(cached)) return await File.ReadAllBytesAsync(cached, ct);
        }

        await _gate.WaitAsync(ct);
        var tmp = Path.Combine(_o.CacheDir is { Length: > 0 } ? _o.CacheDir : Path.GetTempPath(), "piper-" + Guid.NewGuid().ToString("N") + ".tmp");
        try
        {
            if (cached is not null && File.Exists(cached)) return await File.ReadAllBytesAsync(cached, ct);
            Directory.CreateDirectory(Path.GetDirectoryName(tmp)!);
            var psi = new ProcessStartInfo(_o.PiperExe)
            {
                RedirectStandardInput = true, RedirectStandardError = true, RedirectStandardOutput = true,
                UseShellExecute = false, CreateNoWindow = true,
                WorkingDirectory = Path.GetDirectoryName(_o.PiperExe)!,   // espeak-ng-data کنارِ exe است
                StandardInputEncoding = new UTF8Encoding(false),
            };
            psi.ArgumentList.Add("--model"); psi.ArgumentList.Add(model);
            psi.ArgumentList.Add("--output_file"); psi.ArgumentList.Add(tmp);
            psi.ArgumentList.Add("--sentence_silence"); psi.ArgumentList.Add(_o.SentenceSilence.ToString("0.##", CultureInfo.InvariantCulture));
            psi.ArgumentList.Add("--length_scale"); psi.ArgumentList.Add(scaleText);
            using var p = Process.Start(psi) ?? throw new InvalidOperationException("piper اجرا نشد.");
            var errTask = p.StandardError.ReadToEndAsync(ct);
            _ = p.StandardOutput.ReadToEndAsync(ct);
            // یک خط = یک گفته
            await p.StandardInput.WriteLineAsync(input);
            p.StandardInput.Close();
            using var timeout = CancellationTokenSource.CreateLinkedTokenSource(ct);
            timeout.CancelAfter(_o.Timeout);
            try { await p.WaitForExitAsync(timeout.Token); }
            catch (OperationCanceledException) { try { p.Kill(true); } catch { } throw; }
            if (p.ExitCode != 0 || !File.Exists(tmp))
            {
                var err = await errTask;
                throw new InvalidOperationException($"piper نساخت (کد {p.ExitCode}): {(err.Length <= 400 ? err : err[^400..])}");
            }
            var wav = await File.ReadAllBytesAsync(tmp, ct);
            if (cached is not null)
            {
                File.Move(tmp, cached, overwrite: true);
                TrimCache();
            }
            return wav;
        }
        finally
        {
            try { if (File.Exists(tmp)) File.Delete(tmp); } catch { }
            _gate.Release();
        }
    }

    /// <summary>همان <see cref="SpeakAsync"/>، نوشته در فایل.</summary>
    public async Task SpeakToFileAsync(string text, string wavPath, string? voice = null, double? speed = null, CancellationToken ct = default)
    {
        var wav = await SpeakAsync(text, voice, speed, ct);
        var dir = Path.GetDirectoryName(Path.GetFullPath(wavPath));
        if (dir is not null) Directory.CreateDirectory(dir);
        await File.WriteAllBytesAsync(wavPath, wav, ct);
    }

    /// <summary>
    /// متنِ بلند ⇒ تکه‌های کوتاه (مرزِ جمله، هر تکه ≤ maxChars) تا پشتِ هم ساخته و پخش شوند؛
    /// تکهٔ اول زود می‌رسد و شنونده منتظرِ ساختِ کلِ متن نمی‌ماند.
    /// </summary>
    public static List<string> SplitSentences(string text, int maxChars = 220)
    {
        var parts = System.Text.RegularExpressions.Regex.Split(text ?? "", @"(?<=[.؟?!:؛\n])\s+").Where(p => p.Trim().Length > 0);
        var outp = new List<string>(); var cur = "";
        foreach (var p0 in parts)
        {
            var p = p0.Trim();
            while (p.Length > maxChars)
            {
                var cut = p.LastIndexOf(' ', maxChars);
                if (cut < maxChars / 2) cut = maxChars;
                if (cur.Length > 0) { outp.Add(cur); cur = ""; }
                outp.Add(p[..cut].Trim()); p = p[cut..].Trim();
            }
            if (cur.Length > 0 && cur.Length + 1 + p.Length > maxChars) { outp.Add(cur); cur = p; }
            else cur = cur.Length > 0 ? cur + " " + p : p;
        }
        if (cur.Length > 0) outp.Add(cur);
        return outp;
    }

    private void TrimCache()
    {
        try
        {
            var files = new DirectoryInfo(_o.CacheDir!).GetFiles("*.wav");
            if (files.Length <= _o.MaxCacheFiles) return;
            foreach (var f in files.OrderBy(f => f.LastAccessTimeUtc).Take(files.Length - _o.MaxCacheFiles * 4 / 5)) f.Delete();
        }
        catch (Exception ex) { _log?.Invoke("کشِ صدا کوچک نشد: " + ex.Message); }
    }
}
