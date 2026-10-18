using System.Collections.Concurrent;
using System.Security.Cryptography;
using System.Text.Json;
using OpenCvSharp;
using PersianAiKit.Photo.Ai;
using PersianAiKit.Photo.Engine;

namespace PersianAiKit.Photo;

/// <summary>یک عکس در کتابخانه: فایلِ اصلی (دست‌نخورده) + نسخهٔ ویرایش + ماسکِ پس‌زمینه (اگر ساخته شده).</summary>
public sealed record PhotoDoc(string Id, string Name, int Width, int Height, DateTime Created, bool HasMask, string SourceFile);

/// <summary>ماسکِ ذخیره‌شده از کجا آمده: quick (سبک)، ai (مدل)، file (شفافیتِ خودِ PNG) یا upload (دستی/قلم).</summary>
public sealed record MaskInfo(string Method, double Seconds, double Confidence, string Note);

/// <summary>
/// همهٔ کارها در یک جا — برای سرور، آزمون و هر برنامهٔ .NETِ دیگر:
/// کتابخانهٔ عکس‌ها (data/docs/&lt;id&gt;/)، پیش‌نمایش، خروجی، حذفِ پس‌زمینه، تحلیل، تنظیمِ خودکار و ویرایشِ هوشمند.
/// </summary>
public sealed class PhotoService : IDisposable
{
    private readonly string _root;
    private readonly ConcurrentDictionary<string, (PhotoImage Img, double Scale)> _previewBase = new();
    private readonly ConcurrentDictionary<string, Mat> _previewMask = new();
    private readonly ConcurrentQueue<string> _lru = new();
    private readonly ConcurrentDictionary<string, SemaphoreSlim> _maskLocks = new();

    public PhotoService(string dataDir, PhotoModels models, VisionAgentOptions? ai = null, HttpMessageHandler? aiHandler = null)
    {
        _root = Path.Combine(dataDir, "docs");
        Directory.CreateDirectory(_root);
        Models = models;
        Remover = new BackgroundRemover(models.Background);
        Upscaler = new Upscaler(models.Upscale);
        Agent = new VisionAgent(ai ?? new VisionAgentOptions(), aiHandler);
    }

    public PhotoModels Models { get; }
    public BackgroundRemover Remover { get; }
    public Upscaler Upscaler { get; }
    public VisionAgent Agent { get; }
    /// <summary>ضلعِ بلندترِ پیش‌نمایش (پیکسل).</summary>
    public int PreviewSide { get; set; } = 1600;

    // ───────────── کتابخانه ─────────────

    public PhotoDoc Create(byte[] bytes, string? name)
    {
        using var img = PhotoIO.Decode(bytes);   // وارسیِ قالب
        var id = DateTime.Now.ToString("yyMMdd-HHmmss") + "-" + Convert.ToHexString(RandomNumberGenerator.GetBytes(3)).ToLowerInvariant();
        var dir = Path.Combine(_root, id);
        Directory.CreateDirectory(dir);
        var ext = Sniff(bytes);
        var file = "source" + ext;
        File.WriteAllBytes(Path.Combine(dir, file), bytes);
        var doc = new PhotoDoc(id, CleanName(name), img.Width, img.Height, DateTime.Now, false, file);
        File.WriteAllText(Path.Combine(dir, "doc.json"), JsonSerializer.Serialize(doc, PhotoJson.Indented));
        // اگر خودِ عکس شفافیت دارد (PNG)، همان ماسکِ آماده است
        if (img.Alpha is not null) SaveMask(id, img.Alpha, new MaskInfo("file", 0, 1, "شفافیتِ خودِ فایل."));
        return Get(id);
    }

    public IReadOnlyList<PhotoDoc> List() =>
        Directory.EnumerateDirectories(_root).Select(d => TryGet(Path.GetFileName(d))).OfType<PhotoDoc>()
            .OrderByDescending(d => d.Created).ToList();

    public PhotoDoc Get(string id) => TryGet(id) ?? throw new KeyNotFoundException($"عکسِ «{id}» پیدا نشد.");

    private PhotoDoc? TryGet(string id)
    {
        if (!IsSafeId(id)) return null;
        var f = Path.Combine(_root, id, "doc.json");
        if (!File.Exists(f)) return null;
        var d = JsonSerializer.Deserialize<PhotoDoc>(File.ReadAllText(f), PhotoJson.Options)!;
        return d with { HasMask = File.Exists(Path.Combine(_root, id, "mask.png")) };
    }

    public void Delete(string id)
    {
        Get(id);
        Forget(id);
        Directory.Delete(Path.Combine(_root, id), true);
    }

    public byte[] SourceBytes(string id) => File.ReadAllBytes(Path.Combine(_root, id, Get(id).SourceFile));

    public Recipe LoadRecipe(string id)
    {
        var f = Path.Combine(_root, Get(id).Id, "recipe.json");
        return File.Exists(f) ? Recipe.Parse(File.ReadAllText(f)) : new Recipe();
    }

    public void SaveRecipe(string id, Recipe r) =>
        File.WriteAllText(Path.Combine(_root, Get(id).Id, "recipe.json"), r.Normalized().ToJson(true));

    /// <summary>عکسِ کوچکِ اصل (برای فهرست)، یک بار ساخته و نگه داشته می‌شود.</summary>
    public byte[] Thumbnail(string id, int side = 256)
    {
        var f = Path.Combine(_root, Get(id).Id, "thumb.jpg");
        if (File.Exists(f)) return File.ReadAllBytes(f);
        var (bas, _) = PreviewBase(id);
        using var t = bas.Downscaled(side);
        using var flat = t.Alpha is null ? t.Clone() : new PhotoImage(Matte.Composite(t.Color, t.Alpha, (1, 1, 1), 0));
        var bytes = PhotoIO.Encode(flat, "jpeg", 82);
        File.WriteAllBytes(f, bytes);
        return bytes;
    }

    /// <summary>اصلِ عکس (بی ویرایش) در اندازهٔ پیش‌نمایش — برای «قبل/بعد».</summary>
    public PhotoImage Original(string id, int? maxSide = null)
    {
        var (bas, _) = PreviewBase(id);
        return maxSide is { } m ? bas.Downscaled(m) : bas.Clone();
    }

    // ───────────── پیش‌نمایش و خروجی ─────────────

    /// <summary>پیش‌نمایشِ نسخه روی عکسِ کوچک‌شده (سریع). ماسک اگر لازم باشد و نباشد، ساخته می‌شود.</summary>
    public PhotoImage RenderPreview(string id, Recipe r, int? maxSide = null)
    {
        var (bas, scale) = PreviewBase(id);
        // پیش‌نمایشِ کوچک (پیش‌نویسِ هنگامِ کشیدنِ لغزنده، عکسِ کوچکِ فیلترها) روی نسخهٔ کوچک ساخته می‌شود ⇒ چند برابر سریع‌تر
        using var src = maxSide is { } ms && ms < Math.Max(bas.Width, bas.Height) ? bas.Downscaled(ms) : bas.Clone();
        scale *= src.Width / (double)bas.Width;
        if (NeedsMask(r)) { src.Alpha?.Dispose(); src.Alpha = PreviewMask(id, src.Width, src.Height, r.Background!.Method).Clone(); }
        using var rendered = PhotoEngine.Render(src, r, scale);
        var outImg = Output.Finalize(rendered, r, null, preview: true);
        if (maxSide is { } m && Math.Max(outImg.Width, outImg.Height) > m)
        {
            var small = outImg.Downscaled(m);
            outImg.Dispose();
            return small;
        }
        return outImg;
    }

    /// <summary>خروجی در اندازهٔ اصلی (با بزرگ‌نماییِ هوشمند اگر خواسته شده). ⇒ (فایل، قالب)</summary>
    public (byte[] Bytes, string Format) Export(string id, Recipe r)
    {
        using var full = PhotoIO.Decode(SourceBytes(id));
        if (NeedsMask(r)) { full.Alpha?.Dispose(); full.Alpha = FullMask(id, full, r.Background!.Method); }
        return Export(full, r);
    }

    public (byte[] Bytes, string Format) Export(PhotoImage full, Recipe r)
    {
        using var rendered = PhotoEngine.Render(full, r, 1);
        using var outImg = Output.Finalize(rendered, r, Upscaler, preview: false);
        var o = r.Output ?? new OutputSettings();
        var format = o.Format;
        if (outImg.Alpha is not null && format == "jpeg") format = "png";
        return (PhotoIO.Encode(outImg, format, o.Quality), format);
    }

    // ───────────── پس‌زمینه ─────────────

    // عکسِ شفاف (PNG) شفافیتش را از خودِ فایل دارد؛ ماسک فقط برای «حذفِ پس‌زمینه» لازم است
    private static bool NeedsMask(Recipe r) => r.Background is { Remove: true };

    /// <summary>
    /// ماسکِ کالا را می‌سازد اگر نیست (یا روشِ دیگری خواسته شده)؛ گزارشِ تمیزیِ لبه روی پیش‌نمایش.
    /// <paramref name="force"/> ⇒ دوباره ساخته شود حتی اگر هست.
    /// </summary>
    public (EdgeReport Edge, MaskInfo Mask, double Seconds, bool Computed) PrepareBackground(string id, string method = "auto", bool force = false)
    {
        var sw = System.Diagnostics.Stopwatch.StartNew();
        Get(id);
        var computed = force || !MaskFits(id, method);
        if (force) DeleteMask(id);
        var (bas, _) = PreviewBase(id);
        var mask = PreviewMask(id, bas.Width, bas.Height, method);
        var edge = Matte.AutoCleanup(bas.Color, mask);
        return (edge, MaskInfoOf(id)!, sw.Elapsed.TotalSeconds, computed);
    }

    /// <summary>ماسکِ دستی (PNGِ خاکستری، هر اندازه) — مثلاً بعد از اصلاح با قلم در صفحه.</summary>
    public void SetMask(string id, byte[] png)
    {
        using var m = Cv2.ImDecode(png, ImreadModes.Grayscale);
        if (m.Empty()) throw new InvalidDataException("ماسک باید عکسِ خاکستری (PNG) باشد.");
        var d = Get(id);
        using var f = new Mat(); m.ConvertTo(f, MatType.CV_32FC1, 1 / 255.0);
        using var r = new Mat(); Cv2.Resize(f, r, new Size(d.Width, d.Height), 0, 0, InterpolationFlags.Linear);
        SaveMask(id, r, new MaskInfo("upload", 0, 1, "ماسکِ دستی."));
    }

    public byte[]? MaskPng(string id)
    {
        var f = Path.Combine(_root, Get(id).Id, "mask.png");
        return File.Exists(f) ? File.ReadAllBytes(f) : null;
    }

    public MaskInfo? MaskInfoOf(string id)
    {
        var dir = Path.Combine(_root, Get(id).Id);
        if (!File.Exists(Path.Combine(dir, "mask.png"))) return null;
        var f = Path.Combine(dir, "mask.json");
        return File.Exists(f) ? JsonSerializer.Deserialize<MaskInfo>(File.ReadAllText(f), PhotoJson.Options) : new MaskInfo("upload", 0, 1, "");
    }

    public void DeleteMask(string id)
    {
        Get(id);
        foreach (var n in new[] { "mask.png", "mask.json" }) File.Delete(Path.Combine(_root, id, n));
        ForgetMasks(id);
    }

    /// <summary>
    /// عکس ⇒ ماسک با روشِ خواسته‌شده. auto: زمینهٔ ساده ⇒ سبک (بی مدل)؛ وگرنه هوشِ مصنوعی اگر حافظه و مدل باشد؛ وگرنه باز هم سبک، با هشدار.
    /// </summary>
    public (Mat Alpha, MaskInfo Info) ComputeMask(Mat bgr01, string method)
    {
        var sw = System.Diagnostics.Stopwatch.StartNew();
        if (method == "ai")
        {
            var m = Remover.Mask(bgr01);   // حافظه کم باشد، پیامِ روشن می‌دهد
            return (m, new MaskInfo("ai", Math.Round(sw.Elapsed.TotalSeconds, 2), 0.9, "هوشِ مصنوعی (BiRefNet)."));
        }
        var q = QuickMatte.Mask(bgr01);
        if (method == "quick" || q.Confidence >= 0.6)
            return (q.Alpha, new MaskInfo("quick", Math.Round(sw.Elapsed.TotalSeconds, 2), q.Confidence, q.Note));
        if (Remover.CanRun(out var why))
        {
            q.Alpha.Dispose();
            var m = Remover.Mask(bgr01);
            return (m, new MaskInfo("ai", Math.Round(sw.Elapsed.TotalSeconds, 2), 0.9, "زمینه ساده نبود ⇒ هوشِ مصنوعی (BiRefNet)."));
        }
        return (q.Alpha, new MaskInfo("quick", Math.Round(sw.Elapsed.TotalSeconds, 2), q.Confidence, q.Note + " (هوشِ مصنوعی اجرا نشد: " + why + ")"));
    }

    // ماسکِ موجود به کار می‌آید؟ auto ⇒ هر ماسکی؛ روشِ مشخص ⇒ همان روش
    private bool MaskFits(string id, string method)
    {
        var info = MaskInfoOf(id);
        return info is not null && (method is not ("quick" or "ai") || info.Method == method);
    }

    private void SaveMask(string id, Mat alpha01, MaskInfo info)
    {
        using var m8 = new Mat(); alpha01.ConvertTo(m8, MatType.CV_8UC1, 255);
        Cv2.ImWrite(Path.Combine(_root, id, "mask.png"), m8);
        File.WriteAllText(Path.Combine(_root, id, "mask.json"), JsonSerializer.Serialize(info, PhotoJson.Indented));
        ForgetMasks(id);
    }

    private Mat FullMask(string id, PhotoImage full, string method)
    {
        var lk = _maskLocks.GetOrAdd(id, _ => new SemaphoreSlim(1, 1));
        lk.Wait();
        try
        {
            var f = Path.Combine(_root, id, "mask.png");
            if (!MaskFits(id, method))
            {
                var (m, info) = ComputeMask(full.Color, method);
                using (m) SaveMask(id, m, info);
            }
            using var m8 = Cv2.ImRead(f, ImreadModes.Grayscale);
            var a = new Mat(); m8.ConvertTo(a, MatType.CV_32FC1, 1 / 255.0);
            if (a.Cols != full.Width || a.Rows != full.Height) { var r = new Mat(); Cv2.Resize(a, r, full.Color.Size()); a.Dispose(); a = r; }
            return a;
        }
        finally { lk.Release(); }
    }

    private Mat PreviewMask(string id, int w, int h, string method)
    {
        if (!MaskFits(id, method))
        {
            using var full = PhotoIO.Decode(SourceBytes(id));
            using var fm = FullMask(id, full, method);
        }
        var key = $"{id}:{w}x{h}";   // هر اندازه جدا (پیش‌نویس، کامل، عکسِ فیلترها)
        if (_previewMask.TryGetValue(key, out var cached)) return cached;
        var f = Path.Combine(_root, id, "mask.png");
        using var m8 = Cv2.ImRead(f, ImreadModes.Grayscale);
        using var mf = new Mat(); m8.ConvertTo(mf, MatType.CV_32FC1, 1 / 255.0);
        var m = new Mat(); Cv2.Resize(mf, m, new Size(w, h), 0, 0, InterpolationFlags.Area);
        if (_previewMask.TryRemove(key, out var old)) old.Dispose();
        _previewMask[key] = m;
        return m;
    }

    // ───────────── تحلیل، خودکار، هوشِ مصنوعی ─────────────

    public PhotoStats Analyze(string id)
    {
        using var full = PhotoIO.Decode(SourceBytes(id));
        return Analysis.Measure(full);
    }

    public AutoResult Auto(string id) => Analysis.Auto(Analyze(id));

    /// <summary>ویرایشِ هوشمند: هوشِ مصنوعی نسخه را پیشنهاد می‌دهد (بی کلید ⇒ تنظیمِ خودکار). ماسک اگر خواست، ساخته می‌شود.</summary>
    public async Task<AgentResult> AiEditAsync(string id, string? goal, Recipe current, CancellationToken ct = default)
    {
        var stats = Analyze(id);
        var auto = Analysis.Auto(stats);
        var (bas, _) = PreviewBase(id);
        using var work = bas.Clone();
        return await Agent.EditAsync(work, stats, auto, goal, current, rec => RenderPreview(id, rec, Agent.Options.ThumbSide * 2), ct);
    }

    // ───────────── بی‌کتابخانه (یک‌باره، برای برنامه‌های دیگر و هوشِ مصنوعی) ─────────────

    /// <summary>عکس + نسخه (یا خودکار) ⇒ عکسِ ویرایش‌شده. ماسکِ پس‌زمینه در صورتِ نیاز همین‌جا ساخته می‌شود.</summary>
    public (byte[] Bytes, string Format, Recipe Used) EditOnce(byte[] image, Recipe? recipe, bool auto)
    {
        using var full = PhotoIO.Decode(image);
        var r = recipe ?? new Recipe();
        if (auto) r = Analysis.Auto(Analysis.Measure(full)).Recipe.Merge(r);
        if (r.Background is { Remove: true } && full.Alpha is null) full.Alpha = ComputeMask(full.Color, r.Background.Method).Alpha;
        var (b, f) = Export(full, r);
        return (b, f, r);
    }

    // ───────────── کمکی ─────────────

    private (PhotoImage Img, double Scale) PreviewBase(string id)
    {
        if (_previewBase.TryGetValue(id, out var c)) return c;
        using var full = PhotoIO.Decode(SourceBytes(id));
        var small = full.Downscaled(PreviewSide);
        var entry = (small, small.Width / (double)full.Width);
        _previewBase[id] = entry;
        _lru.Enqueue(id);
        while (_previewBase.Count > 4 && _lru.TryDequeue(out var old) && old != id) Forget(old);
        return entry;
    }

    private void Forget(string id)
    {
        if (_previewBase.TryRemove(id, out var e)) e.Img.Dispose();
        ForgetMasks(id);
    }

    private void ForgetMasks(string id)
    {
        foreach (var k in _previewMask.Keys.Where(k => k.StartsWith(id + ":", StringComparison.Ordinal)).ToList())
            if (_previewMask.TryRemove(k, out var m)) m.Dispose();
    }

    private static bool IsSafeId(string id) => id.Length is > 0 and < 64 && id.All(ch => char.IsAsciiLetterOrDigit(ch) || ch == '-');

    private static string CleanName(string? n)
    {
        n = Path.GetFileNameWithoutExtension(n ?? "") ?? "";
        n = new string(n.Where(ch => !Path.GetInvalidFileNameChars().Contains(ch)).ToArray()).Trim();
        return n.Length == 0 ? "عکس" : n.Length > 80 ? n[..80] : n;
    }

    private static string Sniff(byte[] b)
    {
        if (b.Length > 8 && b[0] == 0x89 && b[1] == 'P' && b[2] == 'N' && b[3] == 'G') return ".png";
        if (b.Length > 12 && b[0] == 'R' && b[1] == 'I' && b[2] == 'F' && b[3] == 'F' && b[8] == 'W' && b[9] == 'E') return ".webp";
        if (b.Length > 2 && b[0] == 'B' && b[1] == 'M') return ".bmp";
        if (b.Length > 4 && (b[0] == 'I' && b[1] == 'I' || b[0] == 'M' && b[1] == 'M')) return ".tif";
        return ".jpg";
    }

    public void Dispose()
    {
        foreach (var id in _previewBase.Keys.ToList()) Forget(id);
        Remover.Dispose();
        Upscaler.Dispose();
    }
}
