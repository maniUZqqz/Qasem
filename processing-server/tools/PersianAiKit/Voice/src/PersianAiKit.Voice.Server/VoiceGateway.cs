using System.Diagnostics;
using System.Net;
using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;

namespace PersianAiKit.Server;

/// <summary>
/// پلِ کیت به سرویسِ صدای پایتونی (voice/gateway.py): گفتارِ طبیعی، کلونِ صدا، صدای هر چیز — VOICE-SETUP.md.
/// اگر نشانی روی همین کامپیوتر باشد و سرویس بالا نباشد، کیت خودش آن را اجرا می‌کند و با خودش می‌بندد.
/// </summary>
public sealed class VoiceGateway : IDisposable
{
    private readonly HttpClient _http;
    private readonly Action<string> _log;
    private Process? _proc;
    private string? _startError;

    public Uri Url { get; }
    public string? PythonExe { get; }
    public string? Script { get; }

    public VoiceGateway(string url, string? pythonExe, string? script, Action<string> log)
    {
        Url = new Uri(url.TrimEnd('/') + "/");
        PythonExe = pythonExe;
        Script = script;
        _log = log;
        // صدای هر چیز روی CPU و بارِ اولِ مدل‌ها چند ده ثانیه طول می‌کشد
        _http = new HttpClient { BaseAddress = Url, Timeout = TimeSpan.FromMinutes(10) };
    }

    public bool IsLocal => Url.IsLoopback;
    public bool CanStart => IsLocal && File.Exists(PythonExe) && File.Exists(Script);

    /// <summary>بالا بودن را می‌سنجد؛ اگر نبود و می‌شود، اجرا می‌کند و تا ۲۰ ثانیه صبر می‌کند.</summary>
    public async Task StartIfNeededAsync(string dataDir, string modelsDir, CancellationToken ct = default)
    {
        if (await PingAsync(ct)) { _log($"سرویسِ صدا از قبل بالاست: {Url}"); return; }
        if (!CanStart)
        {
            _startError = IsLocal
                ? $"سرویسِ صدا نصب نیست (پایتونِ {PythonExe} یا {Script} نیست) — VOICE-SETUP.md بخشِ ۵"
                : $"سرویسِ صدا در {Url} جواب نمی‌دهد";
            return;
        }
        var psi = new ProcessStartInfo(PythonExe!)
        {
            WorkingDirectory = Path.GetDirectoryName(Script)!,
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            StandardOutputEncoding = Encoding.UTF8,
            StandardErrorEncoding = Encoding.UTF8,
        };
        foreach (var a in new[] { Script!, "--port", Url.Port.ToString(), "--data", dataDir, "--models", modelsDir,
                                  "--parent-pid", Environment.ProcessId.ToString() })
            psi.ArgumentList.Add(a);
        psi.Environment["PYTHONIOENCODING"] = "utf-8";
        psi.Environment["PYTHONUNBUFFERED"] = "1";
        try
        {
            _proc = Process.Start(psi)!;
            _proc.OutputDataReceived += (_, e) => Relay(e.Data);
            _proc.ErrorDataReceived += (_, e) => Relay(e.Data);
            _proc.BeginOutputReadLine();
            _proc.BeginErrorReadLine();
        }
        catch (Exception ex) { _startError = "سرویسِ صدا اجرا نشد: " + ex.Message; return; }
        for (var i = 0; i < 40 && !ct.IsCancellationRequested; i++)
        {
            await Task.Delay(500, ct);
            if (_proc.HasExited) { _startError = $"سرویسِ صدا بسته شد (کدِ {_proc.ExitCode}) — گزارشِ بالا را ببینید."; return; }
            if (await PingAsync(ct)) { _startError = null; return; }
        }
        _startError = "سرویسِ صدا در ۲۰ ثانیه بالا نیامد.";
    }

    public string? StartError => _startError;

    // LiteRT (صدای هر چیز) پیام‌های داخلیِ بی‌خطر چاپ می‌کند (شتاب‌دهندهٔ GPU/NPU نیست) — نشان داده نشوند
    private void Relay(string? line)
    {
        if (string.IsNullOrWhiteSpace(line)) return;
        if (line.StartsWith("INFO: [litert", StringComparison.Ordinal) || line.StartsWith("WARNING: [litert", StringComparison.Ordinal)
            || line.Contains("Failed to initialize Dispatch API", StringComparison.Ordinal) || line.StartsWith("INFO: Created TensorFlow Lite", StringComparison.Ordinal))
            return;
        _log("  [صدا] " + line);
    }

    public async Task<bool> PingAsync(CancellationToken ct = default)
    {
        try
        {
            using var cts = CancellationTokenSource.CreateLinkedTokenSource(ct);
            cts.CancelAfter(TimeSpan.FromSeconds(2));
            using var r = await _http.GetAsync("health", cts.Token);
            return r.IsSuccessStatusCode;
        }
        catch { return false; }
    }

    /// <summary>JSON از سرویس؛ اگر بالا نبود ⇒ InvalidOperationException (کیت ۵۰۳ می‌دهد).</summary>
    public async Task<JsonElement> GetJsonAsync(string path, CancellationToken ct)
    {
        using var r = await SendAsync(new HttpRequestMessage(HttpMethod.Get, path), ct);
        return await ReadJsonAsync(r, ct);
    }

    public async Task<JsonElement> SendJsonAsync(HttpMethod method, string path, object? body, CancellationToken ct)
    {
        var msg = new HttpRequestMessage(method, path);
        if (body is not null) msg.Content = new StringContent(JsonSerializer.Serialize(body), Encoding.UTF8, "application/json");
        using var r = await SendAsync(msg, ct);
        return await ReadJsonAsync(r, ct);
    }

    /// <summary>درخواستی که صدا (WAV) برمی‌گرداند؛ سرآیندهای X-* هم برگردانده می‌شوند.</summary>
    public async Task<(byte[] Wav, Dictionary<string, string> Headers)> PostForAudioAsync(string path, object body, CancellationToken ct)
    {
        var msg = new HttpRequestMessage(HttpMethod.Post, path)
        {
            Content = new StringContent(JsonSerializer.Serialize(body), Encoding.UTF8, "application/json"),
        };
        using var r = await SendAsync(msg, ct);
        if (!r.IsSuccessStatusCode) await ThrowFrom(r, ct);
        var headers = r.Headers.Where(h => h.Key.StartsWith("X-", StringComparison.OrdinalIgnoreCase))
            .ToDictionary(h => h.Key, h => string.Join(",", h.Value));
        return (await r.Content.ReadAsByteArrayAsync(ct), headers);
    }

    public async Task<JsonElement> PostBytesAsync(string path, byte[] data, string contentType, IDictionary<string, string> headers, CancellationToken ct)
    {
        var msg = new HttpRequestMessage(HttpMethod.Post, path) { Content = new ByteArrayContent(data) };
        msg.Content.Headers.ContentType = new MediaTypeHeaderValue(contentType);
        foreach (var (k, v) in headers) msg.Headers.TryAddWithoutValidation(k, v);
        using var r = await SendAsync(msg, ct);
        return await ReadJsonAsync(r, ct);
    }

    public async Task<byte[]> GetBytesAsync(string path, CancellationToken ct)
    {
        using var r = await SendAsync(new HttpRequestMessage(HttpMethod.Get, path), ct);
        if (!r.IsSuccessStatusCode) await ThrowFrom(r, ct);
        return await r.Content.ReadAsByteArrayAsync(ct);
    }

    private async Task<HttpResponseMessage> SendAsync(HttpRequestMessage msg, CancellationToken ct)
    {
        try { return await _http.SendAsync(msg, ct); }
        catch (HttpRequestException)
        {
            throw new InvalidOperationException(_startError ?? $"سرویسِ صدا در {Url} جواب نمی‌دهد (VOICE-SETUP.md).");
        }
        catch (TaskCanceledException) when (!ct.IsCancellationRequested)
        {
            throw new InvalidOperationException("سرویسِ صدا دیر جواب داد.");
        }
    }

    private static async Task<JsonElement> ReadJsonAsync(HttpResponseMessage r, CancellationToken ct)
    {
        if (!r.IsSuccessStatusCode) await ThrowFrom(r, ct);
        using var doc = JsonDocument.Parse(await r.Content.ReadAsStringAsync(ct));
        return doc.RootElement.Clone();
    }

    private static async Task ThrowFrom(HttpResponseMessage r, CancellationToken ct)
    {
        var body = await r.Content.ReadAsStringAsync(ct);
        string msg;
        try { msg = JsonDocument.Parse(body).RootElement.GetProperty("error").GetString() ?? body; }
        catch { msg = body.Length > 0 ? body : $"خطای {(int)r.StatusCode} از سرویسِ صدا"; }
        throw new VoiceGatewayException((int)r.StatusCode, msg);
    }

    public void Dispose()
    {
        try { if (_proc is { HasExited: false }) _proc.Kill(entireProcessTree: true); } catch { }
        _proc?.Dispose();
        _http.Dispose();
    }
}

/// <summary>خطایی که سرویسِ صدا با کد و پیامِ فارسیِ خودش برگرداند؛ کیت همان را به برنامه می‌دهد.</summary>
public sealed class VoiceGatewayException(int status, string message) : Exception(message)
{
    public int Status { get; } = status;
}
