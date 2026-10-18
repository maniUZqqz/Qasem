// سرویسِ HTTPِ صدای فارسی (PersianAiKit.Voice) — برای هر زبانی (PHP، Python، Node، C#، …) + صفحهٔ آزمایش در /
//
//   GET|POST /api/tts            text, voice, speed          ⇒ audio/wav
//   GET      /api/tts/voices                                 ⇒ صداهای نصب‌شده
//   GET|POST /api/text           text                        ⇒ متنِ خواندنی، نرمال، عددها
//   POST     /api/asr[?phrases=a|b]   بدنه: WAV (یا فرم با فیلدِ file) ⇒ { text, digits, numbers, phrase, words, seconds }
//   ── صدای طبیعی، کلون، صدای هر چیز (سرویسِ پایتونیِ voice/ — VOICE-SETUP.md) ──
//   GET      /api/voice/engines   ·   GET /api/voice/voices   ·   GET /api/voice/voices/{id}/sample   ·   DELETE /api/voice/voices/{id}
//   POST     /api/voice/tts           text, voice, engine?, seed?  ⇒ audio/wav   (engine=piper یا voice=piper:… ⇒ Piperِ خودِ کیت)
//   POST     /api/voice/sfx           prompt, seconds?, seed?, promptEn?  ⇒ audio/wav   ·   POST /api/voice/sfx/translate
//   GET      /api/voice/script    ·   POST /api/voice/clone  name, person, purpose, consent=true
//   POST     /api/voice/clone/clip?voice=ID&index=N&text=…   بدنه: WAV  ⇒ { ok, message, heard, wer, snr, ... }
//   GET      /api/health
using System.Net;
using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;
using System.Text;
using System.Text.Encodings.Web;
using System.Text.Json;
using System.Text.Json.Serialization;
using PersianAiKit;
using PersianAiKit.Asr;
using PersianAiKit.Server;
using PersianAiKit.Text;
using PersianAiKit.Tts;

Console.OutputEncoding = Encoding.UTF8;
var builder = WebApplication.CreateBuilder(args);
var kit = builder.Configuration.GetSection("Kit");
string? Resolve(string? p) =>
    string.IsNullOrWhiteSpace(p) ? null : Path.GetFullPath(Path.IsPathRooted(p) ? p : Path.Combine(builder.Environment.ContentRootPath, p));

var models = VoiceModels.Find(Resolve(kit["ModelsDir"]));
var dataDir = Resolve(kit["DataDir"]) ?? Path.Combine(Path.GetDirectoryName(models.Root)!, "data");
var httpPort = kit.GetValue("HttpPort", 5600);
var httpsPort = kit.GetValue("HttpsPort", 5601);
var lan = kit.GetValue("LanAccess", false);
var apiKey = kit["ApiKey"] ?? "";
var maxAudioSeconds = kit.GetValue("Asr:MaxSeconds", 300);

builder.WebHost.ConfigureKestrel(k =>
{
    k.Limits.MaxRequestBodySize = 30 * 1024 * 1024;
    X509Certificate2? cert = httpsPort > 0 ? SelfSignedCert.LoadOrCreate(Path.Combine(dataDir, "https.pfx")) : null;
    if (lan)
    {
        k.ListenAnyIP(httpPort);
        if (cert is not null) k.ListenAnyIP(httpsPort, l => l.UseHttps(cert));
    }
    else
    {
        k.ListenLocalhost(httpPort);
        if (cert is not null) k.ListenLocalhost(httpsPort, l => l.UseHttps(cert));
    }
});

var tts = new PiperTts(new PiperTtsOptions
{
    PiperExe = models.PiperExe,
    VoicesDir = models.VoicesDir,
    CacheDir = Path.Combine(dataDir, "tts_cache"),
    DefaultVoice = kit["Tts:Voice"] is { Length: > 0 } v ? v : "fa_IR-gyro-medium",
    DefaultSpeed = kit.GetValue("Tts:Speed", 1.0),
    MaxConcurrent = kit.GetValue("Tts:MaxConcurrent", 2),
}, Console.WriteLine);
var asr = new VoskAsr(models, kit.GetValue("Asr:MaxConcurrent", 2), Console.WriteLine);

// سرویسِ صدا: پیش‌فرض voice\.venv کنارِ پوشهٔ models (همان پروژه)
var kitRoot = Path.GetDirectoryName(models.Root)!;
var voiceDir = Path.Combine(kitRoot, "voice");
var voice = new VoiceGateway(
    kit["Voice:Url"] is { Length: > 0 } vu ? vu : "http://127.0.0.1:5620",
    Resolve(kit["Voice:Python"]) ?? Path.Combine(voiceDir, ".venv", OperatingSystem.IsWindows() ? "Scripts\\python.exe" : "bin/python"),
    Path.Combine(voiceDir, "gateway.py"), Console.WriteLine);
var voiceAutoStart = kit.GetValue("Voice:AutoStart", true);
var voiceAsrCheck = kit.GetValue("Voice:AsrCheck", true);

builder.Services.AddCors(o => o.AddDefaultPolicy(p => p.AllowAnyOrigin().AllowAnyHeader().AllowAnyMethod().WithExposedHeaders(
    "X-Voice-Engine", "X-Voice-Seconds", "X-Voice-Took", "X-Voice-Cache", "X-Voice-Check", "X-Seed", "X-Prompt-En", "X-Prompt-Method")));
builder.Services.ConfigureHttpJsonOptions(o =>
{
    o.SerializerOptions.Encoder = JavaScriptEncoder.UnsafeRelaxedJsonEscaping;   // فارسی خوانا در خروجی، نه \u06..
    o.SerializerOptions.Converters.Add(new JsonStringEnumConverter(JsonNamingPolicy.CamelCase));
});

var app = builder.Build();
app.UseCors();

// کلیدِ API + تبدیلِ خطا به پیامِ روشن
app.Use(async (ctx, next) =>
{
    var path = ctx.Request.Path;
    if (path.StartsWithSegments("/api") && !path.StartsWithSegments("/api/health") && apiKey.Length > 0)
    {
        var given = ctx.Request.Headers["X-Api-Key"].ToString();
        if (given.Length == 0) given = ctx.Request.Query["key"].ToString();
        if (!CryptographicOperations.FixedTimeEquals(Encoding.UTF8.GetBytes(given), Encoding.UTF8.GetBytes(apiKey)))
        {
            ctx.Response.StatusCode = 401;
            await ctx.Response.WriteAsJsonAsync(new { error = "کلیدِ API نادرست است (سرآیندِ X-Api-Key)." });
            return;
        }
    }
    try
    {
        await next();
    }
    catch (VoiceGatewayException ex) when (!ctx.Response.HasStarted)
    {
        ctx.Response.StatusCode = ex.Status;
        await ctx.Response.WriteAsJsonAsync(new { error = ex.Message });
    }
    catch (JsonException) when (!ctx.Response.HasStarted)
    {
        ctx.Response.StatusCode = 400;
        await ctx.Response.WriteAsJsonAsync(new { error = "JSONِ بدنه نامعتبر است." });
    }
    catch (Exception ex) when (!ctx.Response.HasStarted && ex is ArgumentException or InvalidOperationException or BadHttpRequestException
                               or DirectoryNotFoundException or InvalidDataException)
    {
        ctx.Response.StatusCode = ex switch
        {
            BadHttpRequestException b => b.StatusCode,
            ArgumentException or InvalidDataException => 400,
            _ => 503,
        };
        // بی «(Parameter 'x')»ِ انگلیسی که ArgumentException به پیام می‌چسباند
        var message = ex is ArgumentException { ParamName: { } pn } ? ex.Message.Replace($" (Parameter '{pn}')", "") : ex.Message;
        await ctx.Response.WriteAsJsonAsync(new { error = message });
    }
});

app.UseDefaultFiles();
app.UseStaticFiles();

// ───────────── وضعیت ─────────────
app.MapGet("/api/health", async (CancellationToken ct) => new
{
    tts = new { available = tts.Available, voices = tts.Voices(), defaultVoice = tts.DefaultVoice },
    voice = await voice.PingAsync(ct)
        ? (object)new { available = true, url = voice.Url.ToString() }
        : new { available = false, url = voice.Url.ToString(), error = voice.StartError ?? "سرویسِ صدا بالا نیست" },
    asr = new { available = asr.Available, model = Path.GetFileName(asr.ModelDir) },
    needsKey = apiKey.Length > 0,
    // صفحه روی http این را پیوند می‌دهد (دوربین و میکروفونِ گوشی فقط روی https)
    httpsPort = httpsPort > 0 ? httpsPort : (int?)null,
});

// ───────────── متن ⇒ گفتار ─────────────
app.MapMethods("/api/tts", new[] { "GET", "POST" }, async (HttpContext ctx) =>
{
    var p = await Params(ctx.Request);
    var speed = double.TryParse(p.GetValueOrDefault("speed"), System.Globalization.NumberStyles.Float,
        System.Globalization.CultureInfo.InvariantCulture, out var s) ? s : (double?)null;
    var wav = await tts.SpeakAsync(p.GetValueOrDefault("text"), p.GetValueOrDefault("voice"), speed, ctx.RequestAborted);
    return Results.File(wav, "audio/wav", p.ContainsKey("download") ? "speech.wav" : null);
});
app.MapGet("/api/tts/voices", () => new { voices = tts.Voices(), defaultVoice = tts.DefaultVoice });

app.MapMethods("/api/text", new[] { "GET", "POST" }, async (HttpContext ctx) =>
{
    var text = (await Params(ctx.Request)).GetValueOrDefault("text") ?? "";
    return new
    {
        speakable = PersianText.ToSpeakable(text),
        normalized = PersianText.Normalize(text),
        digits = PersianText.WordsToDigits(text),
        numbers = PersianText.ExtractNumbers(text),
    };
});

// ───────────── گفتار ⇒ متن ─────────────
app.MapPost("/api/asr", async (HttpContext ctx) =>
{
    var (wav, _) = await Upload(ctx.Request);
    var seconds = WavFile.Duration(wav);
    if (seconds > maxAudioSeconds) throw new ArgumentException($"صدا بلندتر از {maxAudioSeconds} ثانیه است — تکه‌تکه بفرستید.");
    // phrases: متن آزاد شنیده می‌شود و فرمانی که در آن گفته شد پیدا می‌شود (حرفِ بی‌ربط ⇒ phrase=null)
    // strict:  فقط همین واژه‌ها شنیده می‌شوند — هر صدایی به یکی از آن‌ها نسبت داده می‌شود (فقط برای پاسخِ بله/نه و مانندِ آن)
    string[]? List(string key) => ctx.Request.Query[key].ToString() is { Length: > 0 } v
        ? v.Split('|', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries) : null;
    var phrases = List("phrases");
    var r = await asr.RecognizeWavAsync(wav, List("strict"), ctx.RequestAborted);
    var found = phrases is null ? null : PersianText.FindPhrases(r.Text, phrases);
    return new
    {
        text = r.Text,
        digits = PersianText.WordsToDigits(r.Text),
        numbers = PersianText.ExtractNumbers(r.Text),
        phrase = found?.FirstOrDefault(),
        phrasesFound = found,
        seconds = r.Seconds,
        words = r.Words,
    };
});

// ───────────── صدای طبیعی، کلون، صدای هر چیز (پل به voice/gateway.py) ─────────────
const string PiperPrefix = "piper:";
object PiperEngine() => new
{
    id = "piper", name = "Piper (سریع، سبک)", needs = new[] { "tts" }, tier = "light", license = "MIT", commercial = true,
    enabled = true, available = tts.Available,
};

app.MapGet("/api/voice/engines", async (CancellationToken ct) =>
{
    var list = new List<object> { PiperEngine() };
    string? error = null;
    try { list.AddRange((await voice.GetJsonAsync("engines", ct)).GetProperty("engines").EnumerateArray().Select(e => (object)e)); }
    catch (InvalidOperationException ex) { error = ex.Message; }
    return new { engines = list, gateway = error is null, error };
});

app.MapGet("/api/voice/voices", async (CancellationToken ct) =>
{
    var names = new Dictionary<string, string>
    {
        ["fa_IR-gyro-medium"] = "جایرو", ["fa_IR-amir-medium"] = "امیر", ["fa_IR-ganji-medium"] = "گنجی",
        ["fa_IR-ganji_adabi-medium"] = "گنجی (ادبی)", ["fa_IR-reza_ibrahim-medium"] = "رضا ابراهیم", ["fa_IR-mana-medium"] = "مانا",
    };
    var list = tts.Voices().Select(v => (object)new
    {
        id = PiperPrefix + v, name = names.GetValueOrDefault(v, v.Replace("fa_IR-", "").Replace("-medium", "")), engine = "piper", kind = "piper",
    }).ToList();
    string? error = null;
    try { list.AddRange((await voice.GetJsonAsync("voices", ct)).GetProperty("voices").EnumerateArray().Select(e => (object)e)); }
    catch (InvalidOperationException ex) { error = ex.Message; }
    return new { voices = list, gateway = error is null, error };
});

app.MapGet("/api/voice/voices/{id}/sample", async (string id, CancellationToken ct) =>
    Results.File(await voice.GetBytesAsync($"voices/{Uri.EscapeDataString(id)}/sample", ct), "audio/wav"));
app.MapDelete("/api/voice/voices/{id}", async (string id, CancellationToken ct) =>
    Results.Json(await voice.SendJsonAsync(HttpMethod.Delete, $"voices/{Uri.EscapeDataString(id)}", null, ct)));
app.MapGet("/api/voice/script", async (CancellationToken ct) => Results.Json(await voice.GetJsonAsync("script", ct)));

app.MapPost("/api/voice/tts", async (HttpContext ctx) =>
{
    var p = await Params(ctx.Request);
    var text = p.GetValueOrDefault("text");
    var voiceId = p.GetValueOrDefault("voice") ?? "";
    var engine = p.GetValueOrDefault("engine") ?? "";
    if (engine == "piper" || voiceId.StartsWith(PiperPrefix))
    {
        var speed = double.TryParse(p.GetValueOrDefault("speed"), System.Globalization.NumberStyles.Float,
            System.Globalization.CultureInfo.InvariantCulture, out var s) ? s : (double?)null;
        var pw = await tts.SpeakAsync(text, voiceId.StartsWith(PiperPrefix) ? voiceId[PiperPrefix.Length..] : null, speed, ctx.RequestAborted);
        ctx.Response.Headers["X-Voice-Engine"] = "piper";
        return Results.File(pw, "audio/wav");
    }
    var speakable = PersianText.ToSpeakable(text);
    if (string.IsNullOrWhiteSpace(speakable)) throw new ArgumentException("متن خالی است.");
    object Body(string? seed) => new
    {
        text = speakable, voice = voiceId.Length > 0 ? voiceId : null, engine = engine.Length > 0 ? engine : null, seed,
    };
    var (wav, headers) = await voice.PostForAudioAsync("tts", Body(p.GetValueOrDefault("seed") is { Length: > 0 } sd ? sd : null), ctx.RequestAborted);
    // مدلِ طبیعی گاهی واژه‌ای را می‌اندازد یا واژه‌های صدای مرجع را می‌گوید ⇒ کیت خروجی را با گفتار‌به‌متنِ خودش می‌شنود
    // و اگر با متن جور نبود، با بذرِ دیگری دوباره می‌سازد (تا ۲ بار) و بهترین را برمی‌گرداند.
    if (voiceAsrCheck && asr.Available)
    {
        async Task<double> Check(byte[] w) => PersianText.WordErrorRate(speakable, (await asr.RecognizeWavAsync(w, null, ctx.RequestAborted)).Text);
        var wer = await Check(wav);
        for (var k = 1; k <= 2 && wer > 0.45 && long.TryParse(headers.GetValueOrDefault("X-Seed"), out var s0); k++)
        {
            var (w2, h2) = await voice.PostForAudioAsync("tts", Body((s0 + 7919 * k).ToString()), ctx.RequestAborted);
            var e2 = await Check(w2);
            if (e2 < wer) (wav, headers, wer) = (w2, h2, e2);
        }
        headers["X-Voice-Check"] = wer.ToString("0.00", System.Globalization.CultureInfo.InvariantCulture);
    }
    foreach (var (k, v) in headers) ctx.Response.Headers[k] = v;
    return Results.File(wav, "audio/wav", p.ContainsKey("download") ? "speech.wav" : null);
});

app.MapPost("/api/voice/sfx", async (HttpContext ctx) =>
{
    var p = await Params(ctx.Request);
    var (wav, headers) = await voice.PostForAudioAsync("sfx", new
    {
        prompt = p.GetValueOrDefault("prompt") ?? p.GetValueOrDefault("text"),
        promptEn = p.GetValueOrDefault("prompten"),
        seconds = p.GetValueOrDefault("seconds"),
        seed = p.GetValueOrDefault("seed") is { Length: > 0 } sd ? sd : null,
    }, ctx.RequestAborted);
    foreach (var (k, v) in headers) ctx.Response.Headers[k] = v;
    return Results.File(wav, "audio/wav", p.ContainsKey("download") ? "sound.wav" : null);
});

app.MapPost("/api/voice/sfx/translate", async (HttpContext ctx) =>
{
    var p = await Params(ctx.Request);
    return Results.Json(await voice.SendJsonAsync(HttpMethod.Post, "sfx/translate",
        new { prompt = p.GetValueOrDefault("prompt") ?? p.GetValueOrDefault("text") }, ctx.RequestAborted));
});

app.MapPost("/api/voice/clone", async (HttpContext ctx) =>
{
    var p = await Params(ctx.Request);
    var consent = p.GetValueOrDefault("consent") is "true" or "1" or "on";
    return Results.Json(await voice.SendJsonAsync(HttpMethod.Post, "clone", new
    {
        name = p.GetValueOrDefault("name"), person = p.GetValueOrDefault("person"), purpose = p.GetValueOrDefault("purpose"), consent,
    }, ctx.RequestAborted));
});

// یک جملهٔ خوانده‌شده: کیت با گفتار‌به‌متن می‌شنود و سرویسِ صدا با متن مقایسه می‌کند (غلط‌خوانی، نویز، بریدگی)
app.MapPost("/api/voice/clone/clip", async (HttpContext ctx) =>
{
    var (wav, form) = await Upload(ctx.Request);
    string Get(string k) => ctx.Request.Query[k].ToString() is { Length: > 0 } q ? q : form?[k].ToString() ?? "";
    var (voiceId, index, text) = (Get("voice"), Get("index"), Get("text"));
    if (voiceId.Length == 0 || index.Length == 0 || text.Length == 0) throw new ArgumentException("voice، index و text لازم است.");
    if (WavFile.Duration(wav) > 30) throw new ArgumentException("هر تکه حداکثر ۳۰ ثانیه — فقط همان یک جمله را بخوانید.");
    var headers = new Dictionary<string, string> { ["X-Text"] = Uri.EscapeDataString(text) };
    if (asr.Available)
    {
        try { headers["X-Heard"] = Uri.EscapeDataString((await asr.RecognizeWavAsync(wav, null, ctx.RequestAborted)).Text); }
        catch (Exception ex) when (ex is not OperationCanceledException) { }
    }
    return Results.Json(await voice.PostBytesAsync(
        $"clone/clip?voice={Uri.EscapeDataString(voiceId)}&index={Uri.EscapeDataString(index)}", wav, "audio/wav", headers, ctx.RequestAborted));
});

app.Lifetime.ApplicationStopping.Register(voice.Dispose);

app.Lifetime.ApplicationStarted.Register(() =>
{
    asr.Warm();
    if (voiceAutoStart)
        _ = Task.Run(async () =>
        {
            await voice.StartIfNeededAsync(dataDir, models.Root);
            Console.WriteLine(voice.StartError is null ? $"  صدای طبیعی/کلون/صدای هر چیز: ✓ {voice.Url}" : $"  صدای طبیعی/کلون/صدای هر چیز: ✗ {voice.StartError}");
        });
    var ok = (bool b) => b ? "✓" : "✗ (مدل نیست)";
    Console.WriteLine();
    Console.WriteLine("═══ صدای فارسی (PersianAiKit.Voice) آماده است ═══");
    Console.WriteLine($"  متن ⇒ گفتار : {ok(tts.Available)}  {tts.Voices().Count} صدا، پیش‌فرض {tts.DefaultVoice}");
    Console.WriteLine($"  گفتار ⇒ متن : {ok(Directory.Exists(asr.ModelDir))}  {Path.GetFileName(asr.ModelDir)}");
    Console.WriteLine($"  مدل‌ها: {models.Root}");
    Console.WriteLine($"  داده‌ها: {dataDir}");
    Console.WriteLine($"  صفحهٔ آزمایش: http://localhost:{httpPort}" + (httpsPort > 0 ? $"   https://localhost:{httpsPort}" : ""));
    if (lan)
        foreach (var ip in SelfSignedCert.LanIps())
            Console.WriteLine($"  از شبکه/گوشی: " + (httpsPort > 0 ? $"https://{ip}:{httpsPort}" : $"http://{ip}:{httpPort}"));
    if (lan && apiKey.Length == 0)
        Console.WriteLine("  ⚠ روی شبکه باز است و کلیدِ API ندارد — در appsettings.json مقدارِ Kit:ApiKey را بگذارید.");
    Console.WriteLine();
});

app.Run();

// ───────────── کمکی ─────────────

// پارامترها از هر جا: ?text=… ، فرم، JSON ({"text":…}) یا بدنهٔ متنیِ ساده
static async Task<Dictionary<string, string>> Params(HttpRequest req)
{
    var d = req.Query.ToDictionary(q => q.Key.ToLowerInvariant(), q => q.Value.ToString());
    if (!HttpMethods.IsPost(req.Method)) return d;
    if (req.HasFormContentType)
    {
        foreach (var f in await req.ReadFormAsync()) d[f.Key.ToLowerInvariant()] = f.Value.ToString();
        return d;
    }
    using var reader = new StreamReader(req.Body, Encoding.UTF8);
    var body = await reader.ReadToEndAsync();
    if (body.Length == 0) return d;
    if (req.ContentType?.Contains("json", StringComparison.OrdinalIgnoreCase) == true)
    {
        using var doc = JsonDocument.Parse(body);
        foreach (var p in doc.RootElement.EnumerateObject())
            if (p.Value.ValueKind != JsonValueKind.Null)
                d[p.Name.ToLowerInvariant()] = p.Value.ValueKind == JsonValueKind.String ? p.Value.GetString()! : p.Value.GetRawText();
    }
    else d["text"] = body;
    return d;
}

// فایل از بدنهٔ خام (Content-Type: audio/wav یا image/jpeg) یا از فرم (فیلدِ file)
static async Task<(byte[] Data, IFormCollection? Form)> Upload(HttpRequest req)
{
    if (req.HasFormContentType)
    {
        var form = await req.ReadFormAsync();
        var file = form.Files.GetFile("file") ?? form.Files.FirstOrDefault();
        return (await Bytes(file), form);
    }
    using var ms = new MemoryStream();
    await req.Body.CopyToAsync(ms);
    if (ms.Length == 0) throw new ArgumentException("فایلی نیامد — آن را بدنهٔ درخواست بگذارید یا در فرم با نامِ file بفرستید.");
    return (ms.ToArray(), null);
}

static async Task<byte[]> Bytes(IFormFile? file)
{
    if (file is null || file.Length == 0) throw new ArgumentException("فایل خالی است یا فرستاده نشد.");
    using var ms = new MemoryStream();
    await file.CopyToAsync(ms);
    return ms.ToArray();
}
