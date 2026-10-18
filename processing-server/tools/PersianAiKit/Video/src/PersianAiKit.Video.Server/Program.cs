// سرویسِ HTTPِ ویرایشگرِ ویدیو (PersianAiKit.Video) — «پریمیرِ وب» در / و همان ابزارها برای هر برنامه و هر هوشِ مصنوعی:
//
//   GET    /api/health                                   وضعیت: FFmpeg، دیسک، هوشِ مصنوعی
//   GET    /api/tools  ·  /api/tools/openai              همهٔ ابزارها و پریست‌ها · همان در قالبِ function calling
//   GET    /api/videos  ·  POST /api/videos?name=        کتابخانه (بارگذاری: بدنهٔ خام یا فیلدِ file)
//   GET|DELETE /api/videos/{id}
//   GET    /api/videos/{id}/thumb | /strip/{i} | /waveform | /source      عکسِ کوچک، نوارِ فریم‌ها، موجِ صدا، فایلِ اصلی
//   GET|PUT /api/videos/{id}/recipe                      «نسخهٔ ویرایش» (JSON)
//   POST   /api/videos/{id}/frame?t=&max=&original=1     بدنه: نسخه ⇒ فریمِ JPEG در زمانِ t
//   POST   /api/videos/{id}/preview?start=&dur=          بدنه: نسخه ⇒ کار ⇒ MP4ِ کوچک
//   POST   /api/videos/{id}/export                       بدنه: نسخه (خالی ⇒ ذخیره‌شده) ⇒ کار ⇒ فایلِ نهایی
//   GET    /api/jobs?video=  ·  /api/jobs/{id}  ·  /api/jobs/{id}/file  ·  DELETE /api/jobs/{id} (لغو)
//   GET    /api/videos/{id}/analyze  ·  POST /auto       اندازه‌گیریِ تصویر و صدا · تنظیمِ خودکارِ رایگان
//   POST   /api/videos/{id}/pauses?db=&min=&pad=         مکث‌ها ⇒ بازه‌های پیشنهادی برای حذف
//   GET    /api/videos/{id}/sheet                        تصویرِ ۲×۲ از چهار لحظه (برای هوشِ مصنوعیِ بیرونی)
//   POST   /api/videos/{id}/ai-edit                      بدنه: { goal, recipe } ⇒ ویرایش با هوشِ مصنوعیِ بینا
//   GET    /api/luts  ·  POST /api/luts?name=            LUTهای .cube
using System.Diagnostics;
using System.Security.Cryptography;
using System.Text;
using System.Text.Encodings.Web;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.Json.Serialization;
using Microsoft.AspNetCore.Http.Features;
using PersianAiKit.Video;
using PersianAiKit.Video.Ai;
using PersianAiKit.Video.Engine;

Console.OutputEncoding = Encoding.UTF8;
var builder = WebApplication.CreateBuilder(args);
var cfg = builder.Configuration.GetSection("Video");
string? Resolve(string? p) =>
    string.IsNullOrWhiteSpace(p) ? null : Path.GetFullPath(Path.IsPathRooted(p) ? p : Path.Combine(builder.Environment.ContentRootPath, p));

var ff = FFmpegTool.Find(Resolve(cfg["FFmpegDir"]));
var dataDir = Resolve(cfg["DataDir"]) ?? Path.Combine(FindProjectRoot(builder.Environment.ContentRootPath), "data");
var httpPort = cfg.GetValue("HttpPort", 5680);
var lan = cfg.GetValue("LanAccess", false);
var apiKey = cfg["ApiKey"] ?? "";
var maxUpload = cfg.GetValue("MaxUploadMB", 4096L) * 1024 * 1024;

builder.WebHost.ConfigureKestrel(k =>
{
    k.Limits.MaxRequestBodySize = maxUpload;
    if (lan) k.ListenAnyIP(httpPort);
    else k.ListenLocalhost(httpPort);
});
builder.Services.Configure<FormOptions>(o => o.MultipartBodyLengthLimit = maxUpload);
builder.Services.AddCors(o => o.AddDefaultPolicy(p => p.AllowAnyOrigin().AllowAnyHeader().AllowAnyMethod()
    .WithExposedHeaders("X-Width", "X-Height", "X-Render-Ms", "Content-Disposition")));
builder.Services.ConfigureHttpJsonOptions(o =>
{
    o.SerializerOptions.Encoder = JavaScriptEncoder.UnsafeRelaxedJsonEscaping;
    o.SerializerOptions.DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull;
    o.SerializerOptions.NumberHandling = JsonNumberHandling.AllowNamedFloatingPointLiterals;
});

var aiOptions = new VisionAgentOptions();
cfg.GetSection("Ai").Bind(aiOptions);
var svc = new VideoService(dataDir, ff, aiOptions)
{
    MinFreeDiskMB = cfg.GetValue("MinFreeDiskMB", 1500L),
    PreviewShort = cfg.GetValue("PreviewShort", 360),
};

var app = builder.Build();
app.Lifetime.ApplicationStopping.Register(svc.Dispose);
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
    catch (Exception ex) when (!ctx.Response.HasStarted && ex is ArgumentException or InvalidOperationException or BadHttpRequestException
                               or InvalidDataException or KeyNotFoundException or JsonException or FFmpegException)
    {
        ctx.Response.StatusCode = ex switch
        {
            BadHttpRequestException b => b.StatusCode,
            KeyNotFoundException => 404,
            ArgumentException or InvalidDataException or JsonException => 400,
            FFmpegException => 500,
            _ => 503,   // FFmpeg نیست، دیسک پر است، …
        };
        var message = ex switch
        {
            ArgumentException { ParamName: { } pn } => ex.Message.Replace($" (Parameter '{pn}')", ""),
            JsonException => "JSONِ نسخهٔ ویرایش خراب است: " + ex.Message,
            _ => ex.Message,
        };
        await ctx.Response.WriteAsJsonAsync(new { error = message });
    }
});

app.UseDefaultFiles();
app.UseStaticFiles();

// ───────────── وضعیت و ابزارها ─────────────

app.MapGet("/api/health", () =>
{
    var drive = new DriveInfo(Path.GetPathRoot(dataDir)!);
    return new
    {
        ok = ff.Available,
        ffmpeg = new { available = ff.Available, path = ff.FFmpegPath, version = ff.Available ? ff.Version : null },
        videos = svc.List().Count,
        disk = new { freeMB = drive.AvailableFreeSpace / 1048576, minFreeMB = svc.MinFreeDiskMB },
        ai = new { configured = svc.Agent.Configured, baseUrl = aiOptions.BaseUrl, models = aiOptions.Models, maxRounds = aiOptions.MaxRounds },
        previewShort = svc.PreviewShort,
        maxUploadMB = maxUpload / 1048576,
        needsKey = apiKey.Length > 0,
    };
});

app.MapGet("/api/tools", () => new
{
    groups = ToolCatalog.Groups.Select(g => new { g.Key, g.Title, g.Help, g.Stage }),
    @params = ToolCatalog.Params.Select(p => new { p.Key, p.Group, p.Title, p.Help, p.Min, p.Max, p.Default, p.Step, p.Unit, p.Premiere }),
    hslBands = ToolCatalog.HslBands.Select(b => new { key = b.Key, title = b.Title, hue = b.Hue }),
    presets = Presets.All.Select(p => new { p.Key, p.Title, p.Help, p.Kind, recipe = Node(p.Recipe) }),
    aspects = new[] { "original", "9:16", "1:1", "4:5", "16:9" },
});

app.MapGet("/api/tools/openai", () => Results.Text(OpenAiTools().ToJsonString(new JsonSerializerOptions { WriteIndented = true, Encoder = JavaScriptEncoder.UnsafeRelaxedJsonEscaping }),
    "application/json; charset=utf-8"));

// ───────────── کتابخانه ─────────────

app.MapGet("/api/videos", () => svc.List());

app.MapPost("/api/videos", async (HttpRequest req, CancellationToken ct) =>
{
    if (req.HasFormContentType)
    {
        var form = await req.ReadFormAsync(ct);
        var f = form.Files.GetFile("file") ?? form.Files.FirstOrDefault() ?? throw new ArgumentException("فایل نیامده (فیلدِ file).");
        await using var s = f.OpenReadStream();
        return await svc.CreateAsync(s, req.Query["name"].FirstOrDefault() ?? f.FileName, f.Length, ct);
    }
    return await svc.CreateAsync(req.Body, req.Query["name"].FirstOrDefault(), req.ContentLength, ct);
});

app.MapGet("/api/videos/{id}", (string id) => new { video = svc.Get(id), recipe = Node(svc.LoadRecipe(id)) });

app.MapDelete("/api/videos/{id}", (string id) => { svc.Delete(id); return new { ok = true }; });

app.MapGet("/api/videos/{id}/thumb", async (string id, CancellationToken ct) => Results.File(await svc.ThumbAsync(id, ct), "image/jpeg"));

app.MapGet("/api/videos/{id}/strip/{i:int}", async (string id, int i, CancellationToken ct) => Results.File(await svc.StripAsync(id, i, ct), "image/jpeg"));

app.MapGet("/api/videos/{id}/waveform", async (string id, CancellationToken ct) =>
    await svc.WaveformAsync(id, ct) is { } png ? Results.File(png, "image/png") : Results.NotFound(new { error = "این فایل صدا ندارد." }));

app.MapGet("/api/videos/{id}/source", (string id) =>
    Results.File(svc.SourcePath(id), ContentTypeOf(svc.SourcePath(id)), enableRangeProcessing: true));

app.MapGet("/api/videos/{id}/recipe", (string id) => Json(svc.LoadRecipe(id)));

app.MapPut("/api/videos/{id}/recipe", async (string id, HttpRequest req) =>
{
    svc.SaveRecipe(id, VideoRecipe.Parse(await ReadText(req)));
    return Json(svc.LoadRecipe(id));
});

// ───────────── فریم، پیش‌نمایش، خروجی ─────────────

app.MapPost("/api/videos/{id}/frame", async (string id, HttpContext ctx) =>
{
    var q = ctx.Request.Query;
    var json = await ReadText(ctx.Request);
    var r = string.IsNullOrWhiteSpace(json) ? svc.LoadRecipe(id) : VideoRecipe.Parse(json);
    var t = double.TryParse(q["t"], System.Globalization.NumberStyles.Float, System.Globalization.CultureInfo.InvariantCulture, out var tv) ? tv : 0;
    var max = int.TryParse(q["max"], out var mv) ? mv : 1280;
    var sw = Stopwatch.StartNew();
    var (jpg, w, h) = await svc.FrameAsync(id, r, t, max, q["original"] == "1", ctx.RequestAborted);
    ctx.Response.Headers["X-Width"] = w.ToString();
    ctx.Response.Headers["X-Height"] = h.ToString();
    ctx.Response.Headers["X-Render-Ms"] = sw.ElapsedMilliseconds.ToString();
    ctx.Response.Headers.CacheControl = "no-store";
    return Results.File(jpg, "image/jpeg");
});

app.MapPost("/api/videos/{id}/preview", async (string id, HttpRequest req) =>
{
    var json = await ReadText(req);
    var r = string.IsNullOrWhiteSpace(json) ? svc.LoadRecipe(id) : VideoRecipe.Parse(json);
    double Num(string k, double d) => double.TryParse(req.Query[k], System.Globalization.NumberStyles.Float, System.Globalization.CultureInfo.InvariantCulture, out var v) ? v : d;
    return svc.StartPreview(id, r, Num("start", 0), Num("dur", 6));
});

app.MapPost("/api/videos/{id}/export", async (string id, HttpRequest req) =>
{
    var json = await ReadText(req);
    var r = string.IsNullOrWhiteSpace(json) ? svc.LoadRecipe(id) : VideoRecipe.Parse(json);
    return svc.StartExport(id, r);
});

app.MapGet("/api/jobs", (string? video) => svc.Jobs(video));

app.MapGet("/api/jobs/{jobId}", (string jobId) => svc.GetJob(jobId) is { } j ? Results.Json(j) : Results.NotFound(new { error = "این کار نیست (شاید سرور دوباره روشن شده)." }));

app.MapGet("/api/jobs/{jobId}/file", (string jobId, string? download) =>
{
    var j = svc.GetJob(jobId);
    if (j is not { State: "done", FilePath: { } path } || !File.Exists(path)) return Results.NotFound(new { error = "فایلِ این کار آماده نیست." });
    return download == "1"
        ? Results.File(path, ContentTypeOf(path), j.FileName, enableRangeProcessing: true)
        : Results.File(path, ContentTypeOf(path), enableRangeProcessing: true);
});

app.MapDelete("/api/jobs/{jobId}", (string jobId) => new { ok = svc.CancelJob(jobId) });

// ───────────── سنجش، خودکار، مکث‌ها، هوشِ مصنوعی، LUT ─────────────

app.MapGet("/api/videos/{id}/analyze", async (string id, string? force, CancellationToken ct) =>
{
    var s = await svc.AnalyzeAsync(id, force == "1", ct);
    var auto = Analysis.Auto(s, svc.Get(id).Media);
    return new { stats = s, text = s.Describe(svc.Get(id).Media), auto = new { recipe = Node(auto.Recipe), notes = auto.Notes } };
});

app.MapPost("/api/videos/{id}/auto", async (string id, CancellationToken ct) =>
{
    var a = await svc.AutoAsync(id, ct);
    return new { recipe = Node(a.Recipe), notes = a.Notes };
});

app.MapPost("/api/videos/{id}/pauses", async (string id, double? db, double? min, double? pad, CancellationToken ct) =>
{
    var (silences, cuts, saved, threshold) = await svc.PausesAsync(id, db, min ?? 0.6, pad ?? 0.15, ct);
    return new { silences, cuts, saved = Math.Round(saved, 2), threshold };
});

app.MapGet("/api/videos/{id}/sheet", async (string id, string? edited, CancellationToken ct) =>
    Results.File(await svc.SheetAsync(id, edited == "1" ? svc.LoadRecipe(id) : null, aiOptions.CellSide, ct), "image/jpeg"));

app.MapPost("/api/videos/{id}/ai-edit", async (string id, HttpRequest req, CancellationToken ct) =>
{
    var text = await ReadText(req);
    var body = (string.IsNullOrWhiteSpace(text) ? null : JsonNode.Parse(text)) as JsonObject ?? new JsonObject();
    var current = body["recipe"] is JsonObject ro ? VideoRecipe.Parse(ro.ToJsonString()) : svc.LoadRecipe(id);
    var res = await svc.AiEditAsync(id, body["goal"]?.ToString(), current, ct);
    return new
    {
        recipe = Node(res.Recipe), res.Notes, res.UsedAi, res.Error, res.PromptTokens, res.CompletionTokens,
        steps = res.Steps.Select(s => new { s.Round, s.Model, s.Notes, s.Done, s.PromptTokens, s.CompletionTokens, seconds = Math.Round(s.Seconds, 1) }),
    };
});

app.MapGet("/api/luts", () => svc.Luts());

app.MapPost("/api/luts", async (HttpRequest req) =>
{
    using var ms = new MemoryStream();
    string? name = req.Query["name"].FirstOrDefault();
    if (req.HasFormContentType)
    {
        var form = await req.ReadFormAsync();
        var f = form.Files.FirstOrDefault() ?? throw new ArgumentException("فایلِ .cube نیامده.");
        await f.CopyToAsync(ms);
        name ??= f.FileName;
    }
    else await req.Body.CopyToAsync(ms);
    if (ms.Length is 0 or > 64 * 1024 * 1024) throw new ArgumentException("فایلِ .cube خالی یا خیلی بزرگ است.");
    return new { file = svc.SaveLut(ms.ToArray(), name), luts = svc.Luts() };
});

var url = $"http://localhost:{httpPort}";
Console.WriteLine($"ویرایشگرِ ویدیو: {url}   (داده: {dataDir})");
Console.WriteLine(ff.Available ? "FFmpeg: " + ff.Version : "FFmpeg پیدا نشد! tools\\Install-FFmpeg.ps1 را اجرا کنید.");
Console.WriteLine(svc.Agent.Configured ? $"ویرایشگرِ هوشمند: {aiOptions.BaseUrl} ({aiOptions.Models})" : "ویرایشگرِ هوشمند: کلید ندارد ⇒ فقط تنظیمِ خودکارِ رایگان");
if (cfg.GetValue("OpenBrowser", false))
    app.Lifetime.ApplicationStarted.Register(() =>
    {
        try { Process.Start(new ProcessStartInfo(url) { UseShellExecute = true }); }
        catch (Exception e) when (e is System.ComponentModel.Win32Exception or InvalidOperationException) { }
    });
app.Run();

// ───────────── کمکی ─────────────

static JsonNode? Node(VideoRecipe r) => JsonNode.Parse(r.ToJson());

static IResult Json(VideoRecipe r) => Results.Text(r.ToJson(), "application/json; charset=utf-8");

static async Task<string> ReadText(HttpRequest req)
{
    using var reader = new StreamReader(req.Body, Encoding.UTF8);
    return await reader.ReadToEndAsync();
}

static string ContentTypeOf(string path) => Path.GetExtension(path).ToLowerInvariant() switch
{
    ".mp4" or ".m4v" => "video/mp4",
    ".mov" => "video/quicktime",
    ".webm" => "video/webm",
    ".mkv" => "video/x-matroska",
    ".gif" => "image/gif",
    ".mp3" => "audio/mpeg",
    ".wav" => "audio/wav",
    ".m4a" => "audio/mp4",
    ".ogg" or ".opus" => "audio/ogg",
    _ => "application/octet-stream",
};

// پوشهٔ پروژه (جایی که research و src هست) ⇒ data کنارش
static string FindProjectRoot(string start)
{
    var d = new DirectoryInfo(start);
    for (int i = 0; i < 8 && d is not null; i++, d = d.Parent)
        if (Directory.Exists(Path.Combine(d.FullName, "src")) && Directory.Exists(Path.Combine(d.FullName, "research"))) return d.FullName;
    return start;
}

// ابزارها برای هوشِ مصنوعیِ بیرونی (function calling)
static JsonArray OpenAiTools()
{
    JsonObject Num(double min, double max, string desc) => new() { ["type"] = "number", ["minimum"] = min, ["maximum"] = max, ["description"] = desc };
    JsonObject Str(string desc, params string[] values)
    {
        var o = new JsonObject { ["type"] = "string", ["description"] = desc };
        if (values.Length > 0) o["enum"] = new JsonArray(values.Select(v => (JsonNode)v).ToArray());
        return o;
    }
    JsonObject Obj(JsonObject props, string desc = "") => new() { ["type"] = "object", ["properties"] = props, ["description"] = desc };
    var adjust = new JsonObject();
    foreach (var p in ToolCatalog.Params) adjust[p.Key] = Num(p.Min, p.Max, $"{p.Premiere}. default {p.Default}. {p.Help}");
    var range = Obj(new JsonObject { ["start"] = Num(0, 1e6, "seconds"), ["end"] = Num(0, 1e6, "seconds") });
    var recipe = new JsonObject
    {
        ["id"] = Str("video id from the library (POST /api/videos)"),
        ["preset"] = Str("optional ready-made preset applied first: " + string.Join("; ", Presets.All.Select(p => $"{p.Key} = {p.Help}")), Presets.All.Select(p => p.Key).ToArray()),
        ["adjust"] = new JsonObject { ["type"] = "object", ["properties"] = adjust, ["additionalProperties"] = false, ["description"] = "only sliders you change" },
        ["trim"] = range.DeepClone(),
        ["cuts"] = new JsonObject { ["type"] = "array", ["items"] = range.DeepClone(), ["description"] = "ranges removed from the clip (source seconds)" },
        ["time"] = Obj(new JsonObject { ["speed"] = Num(0.25, 4, "playback speed"), ["fadeIn"] = Num(0, 10, "seconds"), ["fadeOut"] = Num(0, 10, "seconds") }),
        ["crop"] = Obj(new JsonObject { ["x"] = Num(0, 1, "left"), ["y"] = Num(0, 1, "top"), ["w"] = Num(0.05, 1, "width"), ["h"] = Num(0.05, 1, "height"), ["angle"] = Num(-45, 45, "degrees, positive = counter-clockwise") }),
        ["frame"] = Obj(new JsonObject { ["aspect"] = Str("output aspect", "original", "9:16", "1:1", "4:5", "16:9"), ["fit"] = Str("how to fit", "crop", "blur", "black"), ["focusX"] = Num(0, 1, "crop center x"), ["focusY"] = Num(0, 1, "crop center y") }),
        ["stabilize"] = Obj(new JsonObject { ["amount"] = Num(0, 100, "smoothing of the camera path") }),
        ["audio"] = Obj(new JsonObject { ["normalize"] = Num(-31, 0, "target LUFS, 0 = off (-14 web, -16 podcast, -23 TV)"), ["hum"] = new JsonObject { ["type"] = "integer", ["enum"] = new JsonArray(0, 50, 60) }, ["mute"] = new JsonObject { ["type"] = "boolean" } }),
        ["output"] = Obj(new JsonObject { ["format"] = Str("container", "mp4", "webm", "gif", "mp3", "wav"), ["codec"] = Str("video codec for mp4", "h264", "h265"), ["size"] = Num(0, 2160, "short side px, 0 = source"), ["fps"] = Num(0, 60, "0 = source"), ["quality"] = Str("quality", "high", "standard", "small") }),
    };
    JsonObject Fn(string name, string desc, JsonObject props, params string[] required) => new()
    {
        ["type"] = "function",
        ["function"] = new JsonObject
        {
            ["name"] = name, ["description"] = desc,
            ["parameters"] = new JsonObject { ["type"] = "object", ["properties"] = props, ["required"] = new JsonArray(required.Select(r => (JsonNode)r).ToArray()) },
        },
    };
    JsonObject IdOnly() => new() { ["id"] = recipe["id"]!.DeepClone() };
    return new JsonArray
    {
        Fn("analyze_video", "Measure a video (exposure, color cast, noise; audio loudness LUFS, noise floor, mains hum, pauses) and get a free automatic recipe. GET /api/videos/{id}/analyze", IdOnly(), "id"),
        Fn("look_at_video", "Get a 2x2 JPEG of four moments of the clip (original or with the saved recipe). GET /api/videos/{id}/sheet?edited=1", IdOnly(), "id"),
        Fn("edit_video", "Set the full non-destructive recipe of video {id}. PUT /api/videos/{id}/recipe; then look_at_video with edited=1 to check", (JsonObject)recipe.DeepClone(), "id"),
        Fn("find_pauses", "Find silent pauses and get suggested cut ranges (for talking videos). POST /api/videos/{id}/pauses", IdOnly(), "id"),
        Fn("export_video", "Render the final file with the saved recipe; returns a job to poll (GET /api/jobs/{jobId}) and download (/api/jobs/{jobId}/file). POST /api/videos/{id}/export", IdOnly(), "id"),
    };
}
