using System.Diagnostics;
using System.Globalization;
using System.Net;
using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using PersianAiKit.Video.Engine;

namespace PersianAiKit.Video.Ai;

/// <summary>تنظیماتِ ویرایشگرِ هوشمند. هر سرویسِ سازگار با OpenAI که عکس می‌پذیرد (OpenRouter، LM Studio، Ollama، …).</summary>
public sealed class VisionAgentOptions
{
    public string BaseUrl { get; set; } = "https://openrouter.ai/api/v1";
    public string ApiKey { get; set; } = "";
    /// <summary>مدل‌ها به ترتیب (با ویرگول). «auto-free» ⇒ مدل‌های بیناییِ رایگانِ OpenRouter.</summary>
    public string Models { get; set; } = "auto-free";
    /// <summary>۱ ⇒ فقط پیشنهاد؛ ۲ ⇒ پیشنهاد + یک بار دیدنِ نتیجه و اصلاح.</summary>
    public int MaxRounds { get; set; } = 2;
    /// <summary>ضلعِ هر خانه در تصویرِ ۲×۲ (۲۵۶ ⇒ تصویرِ ۵۱۲ پیکسلی).</summary>
    public int CellSide { get; set; } = 256;
    public int TimeoutSeconds { get; set; } = 120;
    public int MaxTokens { get; set; } = 900;
}

public sealed record AgentStep(int Round, string Model, string Notes, bool Done, int PromptTokens, int CompletionTokens, double Seconds);

public sealed record AgentResult(VideoRecipe Recipe, string Notes, IReadOnlyList<AgentStep> Steps, bool UsedAi, string? Error)
{
    public int PromptTokens => Steps.Sum(s => s.PromptTokens);
    public int CompletionTokens => Steps.Sum(s => s.CompletionTokens);
}

/// <summary>
/// ویرایشگرِ هوشمندِ ویدیو، کم‌هزینه: مدل فیلم نمی‌بیند؛ یک تصویرِ ۲×۲ از چهار لحظهٔ فیلم (۵۱۲ پیکسل، ~۲۰KB) + اندازه‌گیری‌های تصویر و صدا
/// + نسخهٔ خودکار را می‌بیند و فقط JSONِ نسخه را می‌نویسد؛ موتور اجرا می‌کند؛ (اختیاری) همان چهار لحظه را بعد از ویرایش می‌بیند و اصلاح می‌کند.
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

    /// <param name="sheet">تصویرِ ۲×۲ از فیلمِ اصلی (JPEG).</param>
    /// <param name="renderSheet">همان چهار لحظه با یک نسخه (برای دورِ دوم).</param>
    public async Task<AgentResult> EditAsync(byte[] sheet, string describe, AutoResult auto, string? goal, VideoRecipe current,
        Func<VideoRecipe, Task<byte[]>> renderSheet, CancellationToken ct = default)
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
                    new JsonObject { ["type"] = "text", ["text"] = FirstPrompt(goal, describe, auto, current) },
                    ImagePart(sheet),
                },
            },
        };
        var models = await ModelsAsync(ct);
        if (models.Count == 0) return Fallback(current, auto, steps, "هیچ مدلِ بینایی در دسترس نیست");

        VideoRecipe? recipe = null;
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
                recipe = round == 1 ? KeepUserTiming(current, proposed) : (recipe ?? proposed).Merge(proposed);
            }
            steps.Add(new AgentStep(round, usedModel, n, done, pt, ctk, sec));
            if (done || round >= _o.MaxRounds || recipe is null) break;

            var result = await renderSheet(recipe);
            messages.Add(new JsonObject { ["role"] = "assistant", ["content"] = reply.ToJsonString() });
            messages.Add(new JsonObject
            {
                ["role"] = "user",
                ["content"] = new JsonArray
                {
                    new JsonObject { ["type"] = "text", ["text"] =
                        "These are the same four moments after your recipe. Compare with the goal. If it looks right, reply {\"done\":true,\"notes\":\"...\"}. " +
                        "Otherwise reply the full corrected recipe JSON (same format). Fix only real problems (too dark/bright, color cast, oversaturation, bad framing)." },
                    ImagePart(result),
                },
            });
        }
        if (recipe is null) return Fallback(current, auto, steps, lastError ?? "مدل پاسخِ درست نداد");
        return new AgentResult(recipe.Normalized(), string.IsNullOrWhiteSpace(notes) ? "ویرایش شد." : notes, steps, true, null);
    }

    /// <summary>بُرش‌ها و بازه‌های حذفیِ کاربر را مدل عوض نمی‌کند (فریم‌های کمی دیده؛ زمان‌بندی را نمی‌داند).</summary>
    private static VideoRecipe KeepUserTiming(VideoRecipe current, VideoRecipe proposed)
    {
        var r = proposed.Clone();
        r.Trim = current.Trim; r.Cuts = current.Cuts;
        if (current.Crop is not null) r.Crop = current.Crop;
        return r.Normalized();
    }

    private static AgentResult Fallback(VideoRecipe current, AutoResult auto, List<AgentStep> steps, string error) =>
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
        req.Headers.TryAddWithoutValidation("X-Title", "PersianAiKit Video");
        using var res = await _http.SendAsync(req, ct);
        var text = await res.Content.ReadAsStringAsync(ct);
        if (res.StatusCode is HttpStatusCode.Unauthorized or HttpStatusCode.Forbidden) throw new AgentStopException("کلیدِ API نادرست است یا دسترسی ندارد");
        if (res.StatusCode == HttpStatusCode.PaymentRequired) throw new AgentStopException("اعتبارِ حسابِ سرویسِ هوشِ مصنوعی تمام شده");
        if (!res.IsSuccessStatusCode) throw new HttpRequestException($"HTTP {(int)res.StatusCode}: {Short(text)}");
        var doc = JsonNode.Parse(text) as JsonObject ?? throw new JsonException("پاسخ JSON نیست");
        var content = doc["choices"]?[0]?["message"]?["content"]?.ToString();
        if (string.IsNullOrWhiteSpace(content)) throw new FormatException("پاسخِ خالی: " + Short(text));
        var reply = ExtractJson(content) ?? throw new FormatException("در پاسخ JSON نبود: " + Short(content));
        static int Int(JsonNode? n) => n is JsonValue v && v.TryGetValue<double>(out var d) ? (int)d : 0;
        return (reply, doc["model"]?.ToString() ?? model, Int(doc["usage"]?["prompt_tokens"]), Int(doc["usage"]?["completion_tokens"]), sw.Elapsed.TotalSeconds);
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

    /// <summary>پاسخِ مدل ⇒ نسخه (کلید و عددِ نادرست کنار گذاشته؛ همه در بازه).</summary>
    public static VideoRecipe ParseRecipe(JsonObject reply)
    {
        var r = new VideoRecipe();
        if (reply["preset"]?.ToString() is { Length: > 0 } pk && Presets.Find(pk) is { } preset) r = preset.Recipe.Clone();
        if (reply["adjust"] is JsonObject adj)
            foreach (var (k, v) in adj)
                if (v is JsonValue jv && (jv.TryGetValue<double>(out var d) || double.TryParse(jv.ToString(), NumberStyles.Float, CultureInfo.InvariantCulture, out d)))
                    r.Adjust[k] = d;
        T? Part<T>(string key) where T : class
        {
            try { return reply[key] is JsonObject o ? o.Deserialize<T>(VideoJson.Options) : null; }
            catch (JsonException) { return null; }
        }
        r.Curve = Part<CurveSettings>("curve") ?? r.Curve;
        r.Crop = Part<CropSettings>("crop") ?? r.Crop;
        r.Frame = Part<FrameSettings>("frame") ?? r.Frame;
        r.Stabilize = Part<StabilizeSettings>("stabilize") ?? r.Stabilize;
        r.Time = Part<TimeSettings>("time") ?? r.Time;
        r.Audio = Part<AudioSettings>("audio") ?? r.Audio;
        r.Output = Part<OutputSettings>("output") ?? r.Output;
        return r.Normalized();
    }

    private static JsonObject ImagePart(byte[] jpg) => new()
    {
        ["type"] = "image_url",
        ["image_url"] = new JsonObject { ["url"] = "data:image/jpeg;base64," + Convert.ToBase64String(jpg) },
    };

    public static string SystemPrompt()
    {
        var ci = CultureInfo.InvariantCulture;
        var sb = new StringBuilder();
        sb.AppendLine("You are an expert video editor and colorist working like Premiere Pro (Lumetri + Essential Sound). You do NOT output video: you output one JSON \"recipe\" that a program applies to the whole clip.");
        sb.AppendLine("The image shows 4 moments of the clip in a 2x2 grid (left-to-right, top-to-bottom = start to end). Reply with ONE JSON object only. Fields (all optional except notes):");
        sb.AppendLine("  \"preset\": key of a ready-made preset applied first (see list), then your other fields on top.");
        sb.AppendLine("  \"adjust\": {slider: number} — only sliders you change.");
        sb.AppendLine("  \"curve\": {\"rgb\": [[in,out],...]} points 0..255.");
        sb.AppendLine("  \"stabilize\": {\"amount\": 0..100} only if the goal mentions shaky/handheld footage.");
        sb.AppendLine("  \"frame\": {\"aspect\": \"9:16\"|\"1:1\"|\"4:5\"|\"16:9\", \"fit\": \"crop\"|\"blur\"|\"black\", \"focusX\": 0..1, \"focusY\": 0..1} — reframe for a platform (reels/stories = 9:16).");
        sb.AppendLine("  \"time\": {\"speed\": 0.25..4, \"fadeIn\": seconds, \"fadeOut\": seconds}.");
        sb.AppendLine("  \"audio\": {\"normalize\": LUFS target (-14 web, -16 podcast, -23 TV), \"hum\": 50|60 (mains hum removal), \"mute\": bool}.");
        sb.AppendLine("  \"output\": {\"format\": \"mp4\"|\"webm\"|\"gif\"|\"mp3\", \"size\": short side px (1080, 720), \"quality\": \"high\"|\"standard\"|\"small\"}.");
        sb.AppendLine("  \"notes\": 1-3 short sentences in Persian (Farsi) explaining what you changed and why.");
        sb.AppendLine("Sliders — key [min..max] default: meaning:");
        foreach (var p in ToolCatalog.Params.Where(p => p.Group != "hsl"))
            sb.AppendLine($"  {p.Key} [{p.Min.ToString(ci)}..{p.Max.ToString(ci)}] {p.Default.ToString(ci)}: {p.Premiere}");
        sb.AppendLine("  HSL per color: {red,orange,yellow,green,aqua,blue,purple,magenta}{Hue,Sat,Lum} [-100..100] 0.");
        sb.AppendLine("Presets: " + string.Join("; ", Presets.All.Select(p => $"{p.Key} ({p.Kind})")));
        sb.AppendLine("Rules: be natural and subtle; first fix real problems (color cast, exposure, clipped highlights, noise; for audio: loudness, noise, hum, rumble), then light taste.");
        sb.AppendLine("Trust the measured statistics over your eyes for exposure, color cast and audio (the images are small). The baseline automatic recipe is a sane start: keep, tune or drop it.");
        sb.AppendLine("Do not change trims or cuts. Use frame/output only if the goal names a platform or format.");
        return sb.ToString();
    }

    private static string FirstPrompt(string? goal, string describe, AutoResult auto, VideoRecipe current)
    {
        var sb = new StringBuilder();
        sb.AppendLine("Goal: " + (string.IsNullOrWhiteSpace(goal) ? "make this video look and sound its best, natural and clean." : goal.Trim()));
        sb.AppendLine("Measured statistics of the clip:");
        sb.AppendLine(describe);
        sb.AppendLine("Baseline automatic recipe: " + auto.Recipe.ToJson());
        var cur = current.Clone(); cur.Cuts = null;
        if (cur.Adjust.Count > 0 || cur.Frame is not null || cur.Audio is not null || cur.Output is not null)
            sb.AppendLine("User's current recipe (respect intentional choices): " + cur.ToJson());
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
