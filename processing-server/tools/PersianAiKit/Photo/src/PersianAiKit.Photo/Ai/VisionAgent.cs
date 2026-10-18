using System.Diagnostics;
using System.Globalization;
using System.Net;
using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using PersianAiKit.Photo.Engine;

namespace PersianAiKit.Photo.Ai;

/// <summary>تنظیماتِ ویرایشگرِ هوشمند. هر سرویسِ سازگار با OpenAI که عکس می‌پذیرد (OpenRouter، AvalAI، LM Studio، Ollama، …).</summary>
public sealed class VisionAgentOptions
{
    public string BaseUrl { get; set; } = "https://openrouter.ai/api/v1";
    public string ApiKey { get; set; } = "";
    /// <summary>مدل‌ها به ترتیب (با ویرگول). «auto-free» ⇒ مدل‌های بیناییِ رایگانِ OpenRouter، هر ۶ ساعت از خودش خوانده می‌شود.</summary>
    public string Models { get; set; } = "auto-free";
    /// <summary>دورهای نگاه: ۱ ⇒ فقط پیشنهاد؛ ۲ ⇒ پیشنهاد + یک بار دیدنِ نتیجه و اصلاح (پیش‌فرض).</summary>
    public int MaxRounds { get; set; } = 2;
    /// <summary>ضلعِ عکسی که برای مدل فرستاده می‌شود (کوچک‌تر ⇒ ارزان‌تر).</summary>
    public int ThumbSide { get; set; } = 512;
    public int TimeoutSeconds { get; set; } = 120;
    public int MaxTokens { get; set; } = 900;
}

public sealed record AgentStep(int Round, string Model, string Notes, bool Done, int PromptTokens, int CompletionTokens, double Seconds);

/// <summary>نتیجه: نسخهٔ ویرایش، توضیحِ فارسی، مراحل و مصرف (برای برآوردِ هزینه).</summary>
public sealed record AgentResult(Recipe Recipe, string Notes, IReadOnlyList<AgentStep> Steps, bool UsedAi, string? Error)
{
    public int PromptTokens => Steps.Sum(s => s.PromptTokens);
    public int CompletionTokens => Steps.Sum(s => s.CompletionTokens);
}

/// <summary>
/// ویرایشگرِ هوشمند با هوشِ مصنوعیِ بینا، کم‌هزینه:
/// ۱) اندازه‌گیریِ محلی + تنظیمِ خودکارِ رایگان؛ ۲) یک درخواست با عکسِ کوچک (۵۱۲ پیکسل) + اندازه‌گیری‌ها ⇒ مدل فقط JSONِ نسخهٔ ویرایش را می‌دهد
/// (نه عکس)؛ ۳) موتورِ خودمان اجرا می‌کند؛ ۴) (اختیاری) مدل نتیجه را می‌بیند و اصلاح می‌کند. بی کلید ⇒ همان تنظیمِ خودکار.
/// </summary>
public sealed class VisionAgent
{
    private readonly VisionAgentOptions _o;
    private readonly HttpClient _http;
    private List<string>? _freeModels;
    private DateTime _freeModelsAt;

    public VisionAgent(VisionAgentOptions options, HttpMessageHandler? handler = null)
    {
        _o = options;
        _http = handler is null ? new HttpClient() : new HttpClient(handler);
        _http.Timeout = TimeSpan.FromSeconds(Math.Max(10, options.TimeoutSeconds));
    }

    public VisionAgentOptions Options => _o;
    public bool Configured => !string.IsNullOrWhiteSpace(_o.ApiKey) || IsLocalEndpoint;
    private bool IsLocalEndpoint => Uri.TryCreate(_o.BaseUrl, UriKind.Absolute, out var u) && u.IsLoopback;

    /// <param name="work">عکسِ کوچک‌شده (پیش‌نمایش) — هم برای مدل و هم برای ساختنِ نتیجهٔ دورِ دوم.</param>
    /// <param name="render">اجرای یک نسخه روی عکسِ کوچک (برای دورِ دوم).</param>
    public async Task<AgentResult> EditAsync(PhotoImage work, PhotoStats stats, AutoResult auto, string? goal, Recipe current,
        Func<Recipe, PhotoImage> render, CancellationToken ct = default)
    {
        if (!Configured)
            return new AgentResult(current.Merge(auto.Recipe), "هوشِ مصنوعی تنظیم نشده (کلیدِ API) — تنظیمِ خودکارِ رایگان اعمال شد: " + string.Join(" ", auto.Notes),
                Array.Empty<AgentStep>(), false, "کلیدِ API تنظیم نشده");
        var steps = new List<AgentStep>();
        var messages = new JsonArray
        {
            new JsonObject { ["role"] = "system", ["content"] = SystemPrompt() },
            new JsonObject
            {
                ["role"] = "user",
                ["content"] = new JsonArray
                {
                    new JsonObject { ["type"] = "text", ["text"] = FirstPrompt(goal, stats, auto, current) },
                    ImagePart(work),
                },
            },
        };
        var models = await ModelsAsync(ct);
        if (models.Count == 0) return Fallback(current, auto, steps, "هیچ مدلِ بینایی در دسترس نیست");

        Recipe? recipe = null;
        string notes = "";
        string? lastError = null;
        for (int round = 1; round <= Math.Max(1, _o.MaxRounds); round++)
        {
            (JsonObject Reply, string Model, int Pt, int Ctk, double Sec)? got = null;
            foreach (var model in models)
            {
                try
                {
                    got = await AskAsync(model, messages, ct);
                    if (got is not null) break;
                }
                catch (AgentStopException e) { return Fallback(current, auto, steps, e.Message); }
                catch (Exception e) when (e is HttpRequestException or TaskCanceledException or JsonException or FormatException)
                {
                    if (ct.IsCancellationRequested) throw;
                    lastError = $"{model}: {e.Message}";
                }
            }
            if (got is null) break;
            var (reply, usedModel, pt, ctk, sec) = got.Value;
            var done = reply["done"] is JsonValue dv && (dv.TryGetValue<bool>(out var db) ? db : dv.ToString().Equals("true", StringComparison.OrdinalIgnoreCase));
            var n = reply["notes"]?.ToString() ?? "";
            if (!string.IsNullOrWhiteSpace(n)) notes = n;
            if (!done)
            {
                var proposed = ParseRecipe(reply);
                recipe = round == 1 ? proposed : (recipe ?? proposed).Merge(proposed);
            }
            steps.Add(new AgentStep(round, usedModel, n, done, pt, ctk, sec));
            if (done || round >= _o.MaxRounds || recipe is null) break;

            // دورِ دوم: مدل نتیجه را می‌بیند (فقط عکسِ نتیجه ⇒ ارزان)
            using var result = render(recipe);
            messages.Add(new JsonObject { ["role"] = "assistant", ["content"] = reply.ToJsonString() });
            messages.Add(new JsonObject
            {
                ["role"] = "user",
                ["content"] = new JsonArray
                {
                    new JsonObject { ["type"] = "text", ["text"] =
                        "This is the result of your recipe. Compare it with the goal. If it looks right, reply {\"done\":true,\"notes\":\"...\"}. " +
                        "Otherwise reply the full corrected recipe JSON (same format). Fix only real problems (too dark/bright, color cast, oversaturation, halos)." },
                    ImagePart(result),
                },
            });
        }
        if (recipe is null)
            return Fallback(current, auto, steps, lastError ?? "مدل پاسخِ درست نداد");
        return new AgentResult(recipe.Normalized(), string.IsNullOrWhiteSpace(notes) ? "ویرایش شد." : notes, steps, true, null);
    }

    private static AgentResult Fallback(Recipe current, AutoResult auto, List<AgentStep> steps, string error) =>
        new(current.Merge(auto.Recipe), "هوشِ مصنوعی جواب نداد (" + error + ") — تنظیمِ خودکارِ رایگان اعمال شد.", steps, false, error);

    private sealed class AgentStopException(string message) : Exception(message);

    private async Task<(JsonObject, string, int, int, double)?> AskAsync(string model, JsonArray messages, CancellationToken ct)
    {
        var sw = Stopwatch.StartNew();
        var body = new JsonObject
        {
            ["model"] = model,
            ["messages"] = JsonNode.Parse(messages.ToJsonString()),
            ["temperature"] = 0.2,
            ["max_tokens"] = _o.MaxTokens,
        };
        using var req = new HttpRequestMessage(HttpMethod.Post, _o.BaseUrl.TrimEnd('/') + "/chat/completions")
        {
            Content = new StringContent(body.ToJsonString(), Encoding.UTF8, "application/json"),
        };
        if (!string.IsNullOrWhiteSpace(_o.ApiKey)) req.Headers.Authorization = new AuthenticationHeaderValue("Bearer", _o.ApiKey);
        req.Headers.TryAddWithoutValidation("X-Title", "PersianAiKit Photo");
        using var res = await _http.SendAsync(req, ct);
        var text = await res.Content.ReadAsStringAsync(ct);
        if (res.StatusCode is HttpStatusCode.Unauthorized or HttpStatusCode.Forbidden)
            throw new AgentStopException("کلیدِ API نادرست است یا دسترسی ندارد");
        if (res.StatusCode == HttpStatusCode.PaymentRequired) throw new AgentStopException("اعتبارِ حسابِ سرویسِ هوشِ مصنوعی تمام شده");
        if (!res.IsSuccessStatusCode) throw new HttpRequestException($"HTTP {(int)res.StatusCode}: {Short(text)}");
        var doc = JsonNode.Parse(text) as JsonObject ?? throw new JsonException("پاسخ JSON نیست");
        var content = doc["choices"]?[0]?["message"]?["content"]?.ToString();
        if (string.IsNullOrWhiteSpace(content)) throw new FormatException("پاسخِ خالی: " + Short(text));
        var reply = ExtractJson(content) ?? throw new FormatException("در پاسخ JSON نبود: " + Short(content));
        static int Int(JsonNode? n) => n is JsonValue v && v.TryGetValue<double>(out var d) ? (int)d : 0;
        int pt = Int(doc["usage"]?["prompt_tokens"]), ctk = Int(doc["usage"]?["completion_tokens"]);
        return (reply, doc["model"]?.ToString() ?? model, pt, ctk, sw.Elapsed.TotalSeconds);
    }

    private static string Short(string s) => s.Length > 200 ? s[..200] + "…" : s;

    /// <summary>نخستین شیءِ JSONِ کامل در متن (مدل‌ها گاهی ``` یا توضیح دورش می‌گذارند).</summary>
    public static JsonObject? ExtractJson(string text)
    {
        for (int start = text.IndexOf('{'); start >= 0; start = text.IndexOf('{', start + 1))
        {
            int depth = 0; bool inStr = false;
            for (int i = start; i < text.Length; i++)
            {
                var c = text[i];
                if (inStr) { if (c == '\\') i++; else if (c == '"') inStr = false; continue; }
                if (c == '"') inStr = true;
                else if (c == '{') depth++;
                else if (c == '}' && --depth == 0)
                {
                    try { if (JsonNode.Parse(text[start..(i + 1)]) is JsonObject o) return o; } catch (JsonException) { }
                    break;
                }
            }
        }
        return null;
    }

    /// <summary>پاسخِ مدل ⇒ نسخهٔ ویرایش (کلید و عددِ نادرست کنار گذاشته می‌شود؛ همه در بازه).</summary>
    public static Recipe ParseRecipe(JsonObject reply)
    {
        var r = new Recipe();
        if (reply["adjust"] is JsonObject adj)
            foreach (var (k, v) in adj)
                if (v is JsonValue jv && (jv.TryGetValue<double>(out var d) || double.TryParse(jv.ToString(), NumberStyles.Float, CultureInfo.InvariantCulture, out d)))
                    r.Adjust[k] = d;
        T? Part<T>(string key) where T : class
        {
            try { return reply[key] is JsonObject o ? o.Deserialize<T>(PhotoJson.Options) : null; }
            catch (JsonException) { return null; }
        }
        r.Curve = Part<CurveSettings>("curve");
        r.Crop = Part<CropSettings>("crop");
        r.Background = Part<BackgroundSettings>("background");
        r.Output = Part<OutputSettings>("output");
        return r.Normalized();
    }

    private JsonObject ImagePart(PhotoImage img)
    {
        using var small = img.Downscaled(_o.ThumbSide);
        var jpg = PhotoIO.Encode(small, "jpeg", 80);
        return new JsonObject
        {
            ["type"] = "image_url",
            ["image_url"] = new JsonObject { ["url"] = "data:image/jpeg;base64," + Convert.ToBase64String(jpg) },
        };
    }

    public static string SystemPrompt()
    {
        var ci = CultureInfo.InvariantCulture;
        var sb = new StringBuilder();
        sb.AppendLine("You are an expert photo retoucher working like Lightroom / Camera Raw. You do NOT output images: you output one JSON \"recipe\" that a program applies.");
        sb.AppendLine("Reply with ONE JSON object only (no markdown, no text around it). Fields (all optional except notes):");
        sb.AppendLine("  \"adjust\": {slider: number} — only sliders you change (unlisted = default/neutral).");
        sb.AppendLine("  \"curve\": {\"rgb\": [[in,out],...]} points 0..255 (optional; also \"red\",\"green\",\"blue\").");
        sb.AppendLine("  \"crop\": {\"x\",\"y\",\"w\",\"h\" fractions 0..1 of the image, \"angle\": degrees -45..45 (positive = counter-clockwise, to straighten a tilted horizon)}.");
        sb.AppendLine("  \"background\": {\"remove\": true, \"color\": \"#ffffff\" or \"transparent\", \"shadow\": 0..100} — AI cut-out of the main subject.");
        sb.AppendLine("  \"output\": {\"square\": true, \"padding\": 0..0.4, \"longEdge\": pixels, \"format\": \"jpeg\"|\"png\"|\"webp\"}.");
        sb.AppendLine("  \"notes\": 1-3 short sentences in Persian (Farsi) explaining what you changed and why.");
        sb.AppendLine("Sliders — key [min..max] default: meaning:");
        foreach (var p in ToolCatalog.Params)
            sb.AppendLine($"  {p.Key} [{p.Min.ToString(ci)}..{p.Max.ToString(ci)}] {p.Default.ToString(ci)}: {p.Photoshop}");
        sb.AppendLine("Rules: be natural and subtle; first fix real problems (color cast via temperature/tint, exposure, clipped highlights, blocked shadows, haze, noise), then light taste.");
        sb.AppendLine("Trust the measured statistics over your eyes for exposure and color cast (the thumbnail is small and compressed). The baseline automatic recipe is a sane start: keep, tune or drop it.");
        sb.AppendLine("Never oversaturate skin; sharpen modestly (sharpen 20-50 with sharpenMasking 20-60). Use background/output only if the goal asks for a product, store, catalog or cut-out photo. Crop/straighten only if clearly needed or asked.");
        return sb.ToString();
    }

    private static string FirstPrompt(string? goal, PhotoStats stats, AutoResult auto, Recipe current)
    {
        var sb = new StringBuilder();
        sb.AppendLine("Goal: " + (string.IsNullOrWhiteSpace(goal) ? "make this photo look its best, natural and clean." : goal.Trim()));
        sb.AppendLine("Measured statistics of the full-resolution photo:");
        sb.AppendLine(stats.Describe());
        sb.AppendLine("Baseline automatic recipe: " + auto.Recipe.ToJson());
        if (current.Adjust.Count > 0 || current.Crop is not null || current.Background is not null)
            sb.AppendLine("User's current recipe (respect intentional choices like crop/background): " + current.ToJson());
        sb.AppendLine("Return the full recipe JSON now.");
        return sb.ToString();
    }

    /// <summary>فهرستِ مدل‌ها؛ «auto-free» ⇒ مدل‌های بیناییِ رایگانِ OpenRouter (هر ۶ ساعت تازه).</summary>
    public async Task<IReadOnlyList<string>> ModelsAsync(CancellationToken ct = default)
    {
        var list = _o.Models.Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries).ToList();
        var i = list.FindIndex(m => m.Equals("auto-free", StringComparison.OrdinalIgnoreCase));
        if (i < 0) return list;
        list.RemoveAt(i);
        if (_freeModels is null || DateTime.UtcNow - _freeModelsAt > TimeSpan.FromHours(6))
        {
            try
            {
                using var req = new HttpRequestMessage(HttpMethod.Get, _o.BaseUrl.TrimEnd('/') + "/models");
                if (!string.IsNullOrWhiteSpace(_o.ApiKey)) req.Headers.Authorization = new AuthenticationHeaderValue("Bearer", _o.ApiKey);
                using var res = await _http.SendAsync(req, ct);
                var doc = JsonNode.Parse(await res.Content.ReadAsStringAsync(ct));
                string[] prefer = { "qwen", "gemma", "llama", "mistral", "kimi", "glm" };
                _freeModels = (doc?["data"] as JsonArray ?? new JsonArray())
                    .OfType<JsonObject>()
                    .Where(m => (m["architecture"]?["input_modalities"] as JsonArray)?.Any(x => x?.ToString() == "image") == true
                                && m["pricing"]?["prompt"]?.ToString() is "0" or "0.0"
                                && m["pricing"]?["completion"]?.ToString() is "0" or "0.0")
                    .Select(m => m["id"]!.ToString())
                    .OrderBy(id => { var k = Array.FindIndex(prefer, p => id.Contains(p, StringComparison.OrdinalIgnoreCase)); return k < 0 ? 99 : k; })
                    .Take(6).ToList();
                _freeModelsAt = DateTime.UtcNow;
            }
            catch (Exception e) when (e is HttpRequestException or TaskCanceledException or JsonException)
            {
                _freeModels ??= new List<string>();
            }
        }
        list.InsertRange(i, _freeModels);
        return list;
    }
}
