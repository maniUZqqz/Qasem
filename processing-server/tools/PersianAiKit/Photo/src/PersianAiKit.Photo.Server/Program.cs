// سرویسِ HTTPِ ویرایشگرِ عکس (PersianAiKit.Photo) — «فوتوشاپِ وب» در / و همان ابزارها برای هر برنامه و هر هوشِ مصنوعی:
//
//   GET    /api/health                                   وضعیت: مدل‌ها، حافظه، هوشِ مصنوعی
//   GET    /api/tools                                    همهٔ ابزارها (بازه، پیش‌فرض، توضیح) + فیلترهای آماده
//   GET    /api/tools/openai                             همان در قالبِ «tools»ِ OpenAI (function calling)
//   GET    /api/docs  ·  POST /api/docs (عکس)  ·  GET|DELETE /api/docs/{id}
//   GET    /api/docs/{id}/thumb  ·  /original?max=       عکسِ کوچک / اصلِ بی‌ویرایش (برای قبل/بعد)
//   GET|PUT /api/docs/{id}/recipe                        «نسخهٔ ویرایش» (JSON)
//   POST   /api/docs/{id}/render?max=                    بدنه: نسخه (خالی ⇒ ذخیره‌شده) ⇒ پیش‌نمایش
//   POST   /api/docs/{id}/export                         ⇒ فایلِ نهایی در اندازهٔ اصلی
//   GET    /api/docs/{id}/analyze  ·  POST /auto         اندازه‌گیری‌ها / تنظیمِ خودکارِ رایگان
//   POST   /api/docs/{id}/background?method=&force=      ماسکِ کالا + گزارشِ تمیزیِ لبه
//   GET|PUT|DELETE /api/docs/{id}/mask                   ماسک (PNGِ خاکستری)
//   POST   /api/docs/{id}/ai-edit                        بدنه: { goal, recipe } ⇒ ویرایش با هوشِ مصنوعیِ بینا
//   POST   /api/edit?auto=1&recipe=…                     بی‌کتابخانه: عکس (+ نسخه) ⇒ عکسِ ویرایش‌شده
//   POST   /api/analyze                                  بی‌کتابخانه: عکس ⇒ اندازه‌گیری‌ها + پیشنهادِ خودکار
//   GET    /api/ai/models                                مدل‌هایی که ویرایشگرِ هوشمند امتحان می‌کند
using System.Diagnostics;
using System.Security.Cryptography;
using System.Text;
using System.Text.Encodings.Web;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.Json.Serialization;
using Microsoft.AspNetCore.Http.Features;
using PersianAiKit.Photo;
using PersianAiKit.Photo.Ai;
using PersianAiKit.Photo.Engine;

Console.OutputEncoding = Encoding.UTF8;
var builder = WebApplication.CreateBuilder(args);
var cfg = builder.Configuration.GetSection("Photo");
string? Resolve(string? p) =>
    string.IsNullOrWhiteSpace(p) ? null : Path.GetFullPath(Path.IsPathRooted(p) ? p : Path.Combine(builder.Environment.ContentRootPath, p));

var models = PhotoModels.Find(Resolve(cfg["ModelsDir"]));
var dataDir = Resolve(cfg["DataDir"]) ?? Path.Combine(Path.GetDirectoryName(models.Root)!, "data");
var httpPort = cfg.GetValue("HttpPort", 5670);
var lan = cfg.GetValue("LanAccess", false);
var apiKey = cfg["ApiKey"] ?? "";
const long MaxUpload = 60L * 1024 * 1024;

builder.WebHost.ConfigureKestrel(k =>
{
    k.Limits.MaxRequestBodySize = MaxUpload;
    if (lan) k.ListenAnyIP(httpPort);
    else k.ListenLocalhost(httpPort);
});
builder.Services.Configure<FormOptions>(o => o.MultipartBodyLengthLimit = MaxUpload);
builder.Services.AddCors(o => o.AddDefaultPolicy(p => p.AllowAnyOrigin().AllowAnyHeader().AllowAnyMethod()
    .WithExposedHeaders("X-Render-Ms", "X-Width", "X-Height", "X-Recipe", "Content-Disposition")));
builder.Services.ConfigureHttpJsonOptions(o =>
{
    o.SerializerOptions.Encoder = JavaScriptEncoder.UnsafeRelaxedJsonEscaping;   // فارسی خوانا در خروجی
    o.SerializerOptions.DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull;
});

var aiOptions = new VisionAgentOptions();
cfg.GetSection("Ai").Bind(aiOptions);
var svc = new PhotoService(dataDir, models, aiOptions) { PreviewSide = cfg.GetValue("PreviewSide", 1600) };
svc.Remover.Enabled = cfg.GetValue("Background:Ai", true);
svc.Remover.RequiredMemoryMB = cfg.GetValue("Background:RequiredMemoryMB", 6500);
if (cfg.GetValue("ModelThreads", 0) is > 0 and var threads) { svc.Remover.Threads = threads; svc.Upscaler.Threads = threads; }
// پیش‌نمایش و خروجی پردازنده‌بَرند ⇒ هم‌زمان فقط چندتا
var gate = new SemaphoreSlim(Math.Max(1, cfg.GetValue("MaxParallelRenders", 2)));

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
                               or InvalidDataException or KeyNotFoundException or JsonException or OpenCvSharp.OpenCVException)
    {
        ctx.Response.StatusCode = ex switch
        {
            BadHttpRequestException b => b.StatusCode,
            KeyNotFoundException => 404,
            ArgumentException or InvalidDataException or JsonException or OpenCvSharp.OpenCVException => 400,
            _ => 503,   // مدل نیست، حافظه کم است، …
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
    var canAi = svc.Remover.CanRun(out var why);
    return new
    {
        ok = true,
        docs = svc.List().Count,
        previewSide = svc.PreviewSide,
        memory = new { freeMB = SystemMemory.AvailableMB(), totalMB = SystemMemory.TotalMB() },
        background = new
        {
            quick = true,
            ai = new { installed = svc.Remover.Available, enabled = svc.Remover.Enabled, canRun = canAi, reason = canAi ? null : why, requiredMB = svc.Remover.RequiredMemoryMB },
        },
        upscale = new { installed = svc.Upscaler.Available, maxOutputSide = svc.Upscaler.MaxOutputSide },
        ai = new { configured = svc.Agent.Configured, baseUrl = aiOptions.BaseUrl, models = aiOptions.Models, maxRounds = aiOptions.MaxRounds },
        needsKey = apiKey.Length > 0,
    };
});

app.MapGet("/api/tools", () => new
{
    groups = ToolCatalog.Groups.Select(g => new { g.Key, g.Title, g.Help }),
    @params = ToolCatalog.Params.Select(p => new { p.Key, p.Group, p.Title, p.Help, p.Min, p.Max, p.Default, p.Step, p.Unit, p.Photoshop }),
    hslBands = ToolCatalog.HslBands.Select(b => new { key = b.Key, title = b.Title, hue = b.Hue }),
    presets = Presets.All.Select(p => new { p.Key, p.Title, p.Help, p.Kind, recipe = Node(p.Recipe) }),
    recipeHelp = new
    {
        adjust = "لغزنده‌ها: { کلید: عدد } — فقط آن‌هایی که عوض می‌شوند",
        curve = "{ rgb|red|green|blue: [[ورودی، خروجی], ...] } بینِ ۰ و ۲۵۵",
        crop = "{ x, y, w, h (۰ تا ۱)، angle (−۴۵ تا ۴۵ درجه)، flipH، flipV }",
        spots = "[{ x, y, r }] — لکه‌هایی که ترمیم می‌شوند (به نسبتِ عکس)",
        background = "{ remove, method: auto|quick|ai, color: \"#ffffff\"|\"transparent\", cleanup: −1 (خودکار) یا ۰ تا ۱۰۰، shadow: ۰ تا ۱۰۰ }",
        output = "{ format: jpeg|png|webp, quality, longEdge, square, padding (۰ تا ۰٫۴)، upscale: ۱|۲|۴، sharpen }",
        preset = "کلیدِ یک فیلترِ آماده؛ اول آن و بعد بقیهٔ نسخه روی آن",
    },
});

app.MapGet("/api/tools/openai", () => Results.Text(OpenAiTools().ToJsonString(new JsonSerializerOptions { WriteIndented = true, Encoder = JavaScriptEncoder.UnsafeRelaxedJsonEscaping }),
    "application/json; charset=utf-8"));

app.MapGet("/api/ai/models", async (CancellationToken ct) => new { models = await svc.Agent.ModelsAsync(ct), configured = svc.Agent.Configured });

// ───────────── کتابخانه ─────────────

app.MapGet("/api/docs", () => svc.List().Select(DocDto));

app.MapPost("/api/docs", async (HttpRequest req) =>
{
    var (bytes, name) = await ReadImage(req);
    var doc = await Heavy(() => svc.Create(bytes, req.Query["name"].FirstOrDefault() ?? name));
    return DocDto(doc);
});

app.MapGet("/api/docs/{id}", (string id) => new { doc = DocDto(svc.Get(id)), recipe = Node(svc.LoadRecipe(id)) });

app.MapDelete("/api/docs/{id}", (string id) => { svc.Delete(id); return new { ok = true }; });

app.MapGet("/api/docs/{id}/thumb", async (string id) => Results.File(await Heavy(() => svc.Thumbnail(id)), "image/jpeg"));

app.MapGet("/api/docs/{id}/original", async (string id, int? max) =>
{
    var (bytes, fmt) = await Heavy(() => { using var img = svc.Original(id, max is >= 64 ? max : null); return Encode(img); });
    return Results.File(bytes, PhotoIO.ContentType(fmt));
});

app.MapGet("/api/docs/{id}/recipe", (string id) => Json(svc.LoadRecipe(id)));

app.MapPut("/api/docs/{id}/recipe", async (string id, HttpRequest req) =>
{
    var r = ParseRecipe(await ReadText(req));
    svc.SaveRecipe(id, r);
    return Json(svc.LoadRecipe(id));
});

// ───────────── پیش‌نمایش و خروجی ─────────────

app.MapPost("/api/docs/{id}/render", async (string id, HttpContext ctx) =>
{
    var json = await ReadText(ctx.Request);
    var r = string.IsNullOrWhiteSpace(json) ? svc.LoadRecipe(id) : ParseRecipe(json);
    int? max = int.TryParse(ctx.Request.Query["max"], out var m) && m >= 64 ? m : null;
    var sw = Stopwatch.StartNew();
    var (bytes, fmt, w, h) = await Heavy(() =>
    {
        using var img = svc.RenderPreview(id, r, max);
        var (b, f) = Encode(img);
        return (b, f, img.Width, img.Height);
    });
    ctx.Response.Headers["X-Render-Ms"] = sw.ElapsedMilliseconds.ToString();
    ctx.Response.Headers["X-Width"] = w.ToString();
    ctx.Response.Headers["X-Height"] = h.ToString();
    ctx.Response.Headers.CacheControl = "no-store";
    return Results.File(bytes, PhotoIO.ContentType(fmt));
});

app.MapPost("/api/docs/{id}/export", async (string id, HttpRequest req) =>
{
    var json = await ReadText(req);
    var r = string.IsNullOrWhiteSpace(json) ? svc.LoadRecipe(id) : ParseRecipe(json);
    var doc = svc.Get(id);
    var (bytes, fmt) = await Heavy(() => svc.Export(id, r));
    return Results.File(bytes, PhotoIO.ContentType(fmt), doc.Name + "-edited" + PhotoIO.Extension(fmt));
});

// ───────────── تحلیل، خودکار، پس‌زمینه، هوشِ مصنوعی ─────────────

app.MapGet("/api/docs/{id}/analyze", async (string id) =>
{
    var stats = await Heavy(() => svc.Analyze(id));
    var auto = Analysis.Auto(stats);
    return new { stats, text = stats.Describe(), auto = new { recipe = Node(auto.Recipe), notes = auto.Notes } };
});

app.MapPost("/api/docs/{id}/auto", async (string id) =>
{
    var auto = await Heavy(() => svc.Auto(id));
    return new { recipe = Node(auto.Recipe), notes = auto.Notes };
});

app.MapPost("/api/docs/{id}/background", async (string id, string? method, string? force) =>
{
    method = (method ?? "auto").Trim().ToLowerInvariant();
    if (method is not ("auto" or "quick" or "ai")) throw new ArgumentException("روش باید auto، quick یا ai باشد.");
    var (edge, mask, secs, computed) = await Heavy(() => svc.PrepareBackground(id, method, force is "1" or "true"));
    return new { edge = EdgeDto(edge), mask, seconds = Math.Round(secs, 2), computed };
});

app.MapGet("/api/docs/{id}/mask", (string id) =>
    svc.MaskPng(id) is { } png ? Results.File(png, "image/png") : Results.NotFound(new { error = "هنوز ماسکی ساخته نشده (POST /background)." }));

app.MapPut("/api/docs/{id}/mask", async (string id, HttpRequest req) =>
{
    var (bytes, _) = await ReadImage(req);
    await Heavy(() => { svc.SetMask(id, bytes); return 0; });
    return new { ok = true, mask = svc.MaskInfoOf(id) };
});

app.MapDelete("/api/docs/{id}/mask", (string id) => { svc.DeleteMask(id); return new { ok = true }; });

app.MapPost("/api/docs/{id}/ai-edit", async (string id, HttpRequest req, CancellationToken ct) =>
{
    var text = await ReadText(req);
    var body = (string.IsNullOrWhiteSpace(text) ? null : JsonNode.Parse(text)) as JsonObject ?? new JsonObject();
    var current = body["recipe"] is JsonObject ro ? ParseRecipe(ro.ToJsonString()) : svc.LoadRecipe(id);
    // بیشترِ زمان انتظار برای سرویسِ بیرونی است ⇒ دروازهٔ پردازنده را نمی‌گیرد
    var res = await svc.AiEditAsync(id, body["goal"]?.ToString(), current, ct);
    return new
    {
        recipe = Node(res.Recipe),
        res.Notes,
        res.UsedAi,
        res.Error,
        res.PromptTokens,
        res.CompletionTokens,
        steps = res.Steps.Select(s => new { s.Round, s.Model, s.Notes, s.Done, s.PromptTokens, s.CompletionTokens, seconds = Math.Round(s.Seconds, 1) }),
    };
});

// ───────────── بی‌کتابخانه (یک درخواست، یک جواب) ─────────────

app.MapPost("/api/edit", async (HttpContext ctx) =>
{
    var req = ctx.Request;
    string? recipeJson = req.Query["recipe"].FirstOrDefault();
    if (req.HasFormContentType)
    {
        var form = await req.ReadFormAsync();
        recipeJson = form["recipe"].FirstOrDefault() ?? recipeJson;
    }
    var (bytes, name) = await ReadImage(req);
    var auto = req.Query["auto"].FirstOrDefault() is "1" or "true";
    var r = string.IsNullOrWhiteSpace(recipeJson) ? null : ParseRecipe(recipeJson);
    var (outBytes, fmt, used) = await Heavy(() => svc.EditOnce(bytes, r, auto));
    ctx.Response.Headers["X-Recipe"] = Uri.EscapeDataString(used.ToJson());
    return Results.File(outBytes, PhotoIO.ContentType(fmt), Path.GetFileNameWithoutExtension(name ?? "photo") + "-edited" + PhotoIO.Extension(fmt));
});

app.MapPost("/api/analyze", async (HttpRequest req) =>
{
    var (bytes, _) = await ReadImage(req);
    var stats = await Heavy(() => { using var img = PhotoIO.Decode(bytes); return Analysis.Measure(img); });
    var auto = Analysis.Auto(stats);
    return new { stats, text = stats.Describe(), auto = new { recipe = Node(auto.Recipe), notes = auto.Notes } };
});

var url = $"http://localhost:{httpPort}";
Console.WriteLine($"ویرایشگرِ عکس: {url}   (مدل‌ها: {models.Root}، داده: {dataDir})");
Console.WriteLine(svc.Remover.CanRun(out var bgWhy)
    ? "حذفِ پس‌زمینه: سبک + هوشِ مصنوعی (BiRefNet)"
    : "حذفِ پس‌زمینه: فقط روشِ سبک — " + bgWhy);
Console.WriteLine(svc.Agent.Configured ? $"ویرایشگرِ هوشمند: {aiOptions.BaseUrl} ({aiOptions.Models})" : "ویرایشگرِ هوشمند: کلید ندارد ⇒ فقط تنظیمِ خودکارِ رایگان");
// Run-Server.bat ⇒ --Photo:OpenBrowser=true: مرورگر وقتی باز می‌شود که سرور آماده است
if (cfg.GetValue("OpenBrowser", false))
    app.Lifetime.ApplicationStarted.Register(() =>
    {
        try { Process.Start(new ProcessStartInfo(url) { UseShellExecute = true }); }
        catch (Exception e) when (e is System.ComponentModel.Win32Exception or InvalidOperationException) { }
    });
app.Run();

// ───────────── کمکی ─────────────

async Task<T> Heavy<T>(Func<T> work)
{
    await gate.WaitAsync();
    try { return await Task.Run(work); }
    finally { gate.Release(); }
}

object DocDto(PhotoDoc d) => new { d.Id, d.Name, d.Width, d.Height, d.Created, d.HasMask, mask = svc.MaskInfoOf(d.Id) };

static object EdgeDto(EdgeReport e) => new
{
    cleanup = e.Cleanup, haloPercent = e.HaloPercent, score = e.Score, clean = e.Clean,
    tried = e.Tried.Select(t => new { cleanup = t.Cleanup, halo = t.Halo }),
};

static JsonNode? Node(Recipe r) => JsonNode.Parse(r.ToJson());

static IResult Json(Recipe r) => Results.Text(r.ToJson(), "application/json; charset=utf-8");

// پیش‌نمایشِ شفاف ⇒ WebP (کوچک و سریع، با شفافیت)؛ بقیه JPEG
static (byte[] Bytes, string Format) Encode(PhotoImage img) =>
    img.Alpha is null ? (PhotoIO.Encode(img, "jpeg", 88), "jpeg") : (PhotoIO.Encode(img, "webp", 90), "webp");

// «preset» در JSON ⇒ اول آن فیلتر، بعد بقیهٔ نسخه روی آن
static Recipe ParseRecipe(string json)
{
    var r = Recipe.Parse(json);
    if (JsonNode.Parse(json) is JsonObject o && o["preset"]?.ToString() is { Length: > 0 } key)
        r = (Presets.Find(key) ?? throw new ArgumentException($"فیلترِ «{key}» نیست.")).Recipe.Merge(r);
    return r;
}

static async Task<string> ReadText(HttpRequest req)
{
    using var reader = new StreamReader(req.Body, Encoding.UTF8);
    return await reader.ReadToEndAsync();
}

// عکس از فرم (فیلدِ file) یا بدنهٔ خام
static async Task<(byte[] Bytes, string? Name)> ReadImage(HttpRequest req)
{
    using var ms = new MemoryStream();
    string? name = null;
    if (req.HasFormContentType)
    {
        var form = await req.ReadFormAsync();
        var f = form.Files.GetFile("file") ?? form.Files.FirstOrDefault() ?? throw new ArgumentException("فایلِ عکس نیامده (فیلدِ file).");
        await f.CopyToAsync(ms);
        name = f.FileName;
    }
    else await req.Body.CopyToAsync(ms);
    if (ms.Length == 0) throw new ArgumentException("عکسی نیامده؛ فایل را در بدنهٔ درخواست یا فیلدِ file بفرستید.");
    return (ms.ToArray(), name);
}

// ابزارها برای هوشِ مصنوعیِ بیرونی (function calling): تحلیل، ویرایش (پیش‌نمایش)، خروجی
static JsonArray OpenAiTools()
{
    JsonObject Num(double min, double max, string desc) => new() { ["type"] = "number", ["minimum"] = min, ["maximum"] = max, ["description"] = desc };
    var adjust = new JsonObject();
    foreach (var p in ToolCatalog.Params)
        adjust[p.Key] = Num(p.Min, p.Max, $"{p.Photoshop}. default {p.Default}. {p.Help}");
    var points = new JsonObject
    {
        ["type"] = "array",
        ["items"] = new JsonObject { ["type"] = "array", ["items"] = new JsonObject { ["type"] = "number" }, ["minItems"] = 2, ["maxItems"] = 2 },
        ["description"] = "[[in,out],...] 0..255",
    };
    var recipe = new JsonObject
    {
        ["id"] = new JsonObject { ["type"] = "string", ["description"] = "photo id from the library (POST /api/docs)" },
        ["preset"] = new JsonObject { ["type"] = "string", ["enum"] = new JsonArray(Presets.All.Select(p => (JsonNode)p.Key).ToArray()), ["description"] = "optional ready-made look applied first: " + string.Join("; ", Presets.All.Select(p => $"{p.Key} = {p.Help}")) },
        ["adjust"] = new JsonObject { ["type"] = "object", ["properties"] = adjust, ["additionalProperties"] = false, ["description"] = "only sliders you change" },
        ["curve"] = new JsonObject { ["type"] = "object", ["properties"] = new JsonObject { ["rgb"] = points.DeepClone(), ["red"] = points.DeepClone(), ["green"] = points.DeepClone(), ["blue"] = points.DeepClone() } },
        ["crop"] = new JsonObject
        {
            ["type"] = "object",
            ["properties"] = new JsonObject
            {
                ["x"] = Num(0, 1, "left"), ["y"] = Num(0, 1, "top"), ["w"] = Num(0.01, 1, "width"), ["h"] = Num(0.01, 1, "height"),
                ["angle"] = Num(-45, 45, "degrees, positive = counter-clockwise"),
                ["flipH"] = new JsonObject { ["type"] = "boolean" }, ["flipV"] = new JsonObject { ["type"] = "boolean" },
            },
        },
        ["spots"] = new JsonObject
        {
            ["type"] = "array", ["description"] = "blemishes/dust to heal",
            ["items"] = new JsonObject { ["type"] = "object", ["properties"] = new JsonObject { ["x"] = Num(0, 1, "center x"), ["y"] = Num(0, 1, "center y"), ["r"] = Num(0.001, 0.2, "radius / shorter side") } },
        },
        ["background"] = new JsonObject
        {
            ["type"] = "object",
            ["properties"] = new JsonObject
            {
                ["remove"] = new JsonObject { ["type"] = "boolean" },
                ["method"] = new JsonObject { ["type"] = "string", ["enum"] = new JsonArray("auto", "quick", "ai") },
                ["color"] = new JsonObject { ["type"] = "string", ["description"] = "#rrggbb or transparent" },
                ["cleanup"] = Num(-1, 100, "edge cleanup; -1 = automatic"),
                ["shadow"] = Num(0, 100, "soft contact shadow"),
            },
        },
        ["output"] = new JsonObject
        {
            ["type"] = "object",
            ["properties"] = new JsonObject
            {
                ["format"] = new JsonObject { ["type"] = "string", ["enum"] = new JsonArray("jpeg", "png", "webp") },
                ["quality"] = Num(30, 100, "jpeg/webp quality"),
                ["longEdge"] = Num(0, 8000, "pixels, 0 = original"),
                ["square"] = new JsonObject { ["type"] = "boolean", ["description"] = "store-style square canvas, subject centered" },
                ["padding"] = Num(0, 0.4, "margin around the subject on the square canvas"),
                ["upscale"] = new JsonObject { ["type"] = "integer", ["enum"] = new JsonArray(1, 2, 4) },
                ["sharpen"] = Num(0, 100, "final sharpening after resize"),
            },
        },
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
    return new JsonArray
    {
        Fn("analyze_photo", "Measure a photo (exposure, clipping, color cast, noise, sharpness, plain background) and get a free automatic recipe. GET /api/docs/{id}/analyze",
            new JsonObject { ["id"] = recipe["id"]!.DeepClone() }, "id"),
        Fn("edit_photo", "Set the full non-destructive recipe of photo {id} and render a preview to look at. PUT /api/docs/{id}/recipe then POST /api/docs/{id}/render",
            (JsonObject)recipe.DeepClone(), "id"),
        Fn("export_photo", "Export photo {id} at full resolution with its saved recipe. POST /api/docs/{id}/export",
            new JsonObject { ["id"] = recipe["id"]!.DeepClone() }, "id"),
    };
}
