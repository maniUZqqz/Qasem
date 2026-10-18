using System.Diagnostics;
using System.Globalization;
using System.Text;

namespace PersianAiKit.Video.Engine;

/// <summary>نتیجهٔ یک اجرای ffmpeg/ffprobe.</summary>
public sealed record FfResult(int ExitCode, string StdErr, byte[] StdOut, double Seconds)
{
    public bool Ok => ExitCode == 0;
    /// <summary>چند خطِ آخرِ خطا (برای پیام به کاربر).</summary>
    public string ErrorTail => string.Join(" | ", StdErr.Split('\n', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries).TakeLast(3));
}

/// <summary>
/// پیدا کردن و اجرای ffmpeg.exe و ffprobe.exe (برنامهٔ جدا؛ هیچ کتابخانه‌ای به برنامهٔ ما پیوند نمی‌خورد).
/// با اولویتِ پایین اجرا می‌شود تا کامپیوتر هنگامِ خروجی گرفتن کند نشود؛ لغو ⇒ فرایند کشته می‌شود.
/// </summary>
public sealed class FFmpegTool
{
    public const string EnvironmentVariable = "PERSIAN_FFMPEG";

    public FFmpegTool(string? ffmpeg, string? ffprobe)
    {
        FFmpegPath = ffmpeg ?? "";
        FFprobePath = ffprobe ?? "";
    }

    public string FFmpegPath { get; }
    public string FFprobePath { get; }
    public bool Available => File.Exists(FFmpegPath) && File.Exists(FFprobePath);

    /// <summary>
    /// ترتیب: پوشهٔ داده‌شده ⇐ متغیرِ محیطیِ PERSIAN_FFMPEG ⇐ tools\ffmpeg\bin کنارِ برنامه (رو به بالا) ⇐ PATH ⇐ نصبِ winget (Gyan.FFmpeg).
    /// </summary>
    public static FFmpegTool Find(string? explicitDir = null)
    {
        foreach (var dir in Candidates(explicitDir))
        {
            var ff = Path.Combine(dir, "ffmpeg.exe");
            var fp = Path.Combine(dir, "ffprobe.exe");
            if (!OperatingSystem.IsWindows()) { ff = Path.Combine(dir, "ffmpeg"); fp = Path.Combine(dir, "ffprobe"); }
            if (File.Exists(ff) && File.Exists(fp)) return new FFmpegTool(ff, fp);
        }
        return new FFmpegTool(null, null);
    }

    private static IEnumerable<string> Candidates(string? explicitDir)
    {
        if (!string.IsNullOrWhiteSpace(explicitDir)) yield return File.Exists(explicitDir) ? Path.GetDirectoryName(explicitDir)! : explicitDir;
        var env = Environment.GetEnvironmentVariable(EnvironmentVariable);
        if (!string.IsNullOrWhiteSpace(env)) yield return File.Exists(env) ? Path.GetDirectoryName(env)! : env;
        foreach (var start in new[] { AppContext.BaseDirectory, Directory.GetCurrentDirectory() })
        {
            var d = new DirectoryInfo(start);
            for (var i = 0; i < 8 && d is not null; i++, d = d.Parent)
                yield return Path.Combine(d.FullName, "tools", "ffmpeg", "bin");
        }
        foreach (var p in (Environment.GetEnvironmentVariable("PATH") ?? "").Split(Path.PathSeparator, StringSplitOptions.RemoveEmptyEntries))
            yield return p.Trim('"');
        var winget = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Microsoft", "WinGet", "Packages");
        if (Directory.Exists(winget))
            foreach (var pkg in SafeDirs(winget, "Gyan.FFmpeg*"))
                foreach (var build in SafeDirs(pkg, "ffmpeg-*").OrderByDescending(x => x))
                    yield return Path.Combine(build, "bin");
    }

    private static IEnumerable<string> SafeDirs(string dir, string pattern)
    {
        try { return Directory.GetDirectories(dir, pattern); }
        catch (Exception e) when (e is IOException or UnauthorizedAccessException) { return Array.Empty<string>(); }
    }

    private string? _version;
    /// <summary>«ffmpeg version 9.0.1-full_build…» (خطِ اول).</summary>
    public string Version
    {
        get
        {
            if (_version is not null || !Available) return _version ?? "";
            var r = RunAsync(FFmpegPath, new[] { "-hide_banner", "-version" }, captureStdOut: true).GetAwaiter().GetResult();
            _version = Encoding.UTF8.GetString(r.StdOut).Split('\n').FirstOrDefault()?.Trim() ?? "";
            return _version;
        }
    }

    /// <param name="workDir">پوشهٔ کار (نامِ فایل‌های LUT و تثبیت در فیلترها نسبت به این‌جا).</param>
    public Task<FfResult> FFmpegAsync(IEnumerable<string> args, CancellationToken ct = default, Action<double>? progressSeconds = null, bool captureStdOut = false, string? workDir = null) =>
        RunAsync(FFmpegPath, Prefix(args, progressSeconds is not null), captureStdOut && progressSeconds is null, ct, progressSeconds, workDir);

    public Task<FfResult> FFprobeAsync(IEnumerable<string> args, CancellationToken ct = default) =>
        RunAsync(FFprobePath, args, captureStdOut: true, ct);

    private static IEnumerable<string> Prefix(IEnumerable<string> args, bool progress)
    {
        yield return "-hide_banner";
        yield return "-nostdin";
        if (progress) { yield return "-progress"; yield return "pipe:1"; yield return "-nostats"; }
        foreach (var a in args) yield return a;
    }

    /// <param name="progressSeconds">هر بار که ffmpeg زمانِ خروجی را گزارش می‌دهد (ثانیه).</param>
    public static async Task<FfResult> RunAsync(string exe, IEnumerable<string> args, bool captureStdOut, CancellationToken ct = default, Action<double>? progressSeconds = null, string? workDir = null)
    {
        if (!File.Exists(exe)) throw new InvalidOperationException("FFmpeg پیدا نشد — tools\\Install-FFmpeg.ps1 را اجرا کنید (یا winget install Gyan.FFmpeg).");
        var sw = Stopwatch.StartNew();
        var psi = new ProcessStartInfo(exe)
        {
            UseShellExecute = false, CreateNoWindow = true,
            RedirectStandardOutput = true, RedirectStandardError = true, RedirectStandardInput = false,
            StandardErrorEncoding = Encoding.UTF8,
        };
        if (workDir is not null) psi.WorkingDirectory = workDir;
        foreach (var a in args) psi.ArgumentList.Add(a);
        using var p = new Process { StartInfo = psi };
        p.Start();
        try { p.PriorityClass = ProcessPriorityClass.BelowNormal; } catch (Exception e) when (e is InvalidOperationException or System.ComponentModel.Win32Exception) { }
        using var reg = ct.Register(() => { try { if (!p.HasExited) p.Kill(true); } catch (InvalidOperationException) { } });

        var err = new StringBuilder();
        var errTask = Task.Run(async () =>
        {
            var buf = new char[8192];
            int n;
            while ((n = await p.StandardError.ReadAsync(buf, 0, buf.Length)) > 0)
                lock (err) { if (err.Length < 16_000_000) err.Append(buf, 0, n); }
        });
        byte[] stdout = Array.Empty<byte>();
        if (progressSeconds is not null)
        {
            string? line;
            while ((line = await p.StandardOutput.ReadLineAsync()) is not null)
                if (line.StartsWith("out_time_us=", StringComparison.Ordinal) &&
                    long.TryParse(line.AsSpan(12), NumberStyles.Integer, CultureInfo.InvariantCulture, out var us) && us >= 0)
                    progressSeconds(us / 1e6);
        }
        else if (captureStdOut)
        {
            using var ms = new MemoryStream();
            await p.StandardOutput.BaseStream.CopyToAsync(ms, ct).ConfigureAwait(false);
            stdout = ms.ToArray();
        }
        else await p.StandardOutput.BaseStream.CopyToAsync(Stream.Null, ct).ConfigureAwait(false);
        await p.WaitForExitAsync(CancellationToken.None);
        await errTask;
        ct.ThrowIfCancellationRequested();
        return new FfResult(p.ExitCode, err.ToString(), stdout, sw.Elapsed.TotalSeconds);
    }

    /// <summary>عدد با نقطهٔ اعشارِ انگلیسی (ffmpeg ویرگولِ فارسی نمی‌فهمد).</summary>
    public static string F(double v, int digits = 4) => Math.Round(v, digits).ToString(CultureInfo.InvariantCulture);
}
