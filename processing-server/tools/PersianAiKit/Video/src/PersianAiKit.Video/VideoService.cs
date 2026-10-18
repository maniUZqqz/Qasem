using System.Collections.Concurrent;
using System.Diagnostics;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;
using PersianAiKit.Video.Ai;
using PersianAiKit.Video.Engine;

namespace PersianAiKit.Video;

/// <summary>یک ویدیو در کتابخانه: فایلِ اصلی (دست‌نخورده) + مشخصات.</summary>
public sealed record VideoDoc(string Id, string Name, DateTime Created, string SourceFile, MediaInfo Media);

/// <summary>کارِ پس‌زمینه (پیش‌نمایشِ متحرک یا خروجی) با پیشرفت و لغو.</summary>
public sealed class VideoJob
{
    public string Id { get; init; } = "";
    public string DocId { get; init; } = "";
    /// <summary>preview یا export.</summary>
    public string Kind { get; init; } = "export";
    /// <summary>queued، running، done، failed، cancelled.</summary>
    public string State { get; set; } = "queued";
    public double Progress { get; set; }
    public string Stage { get; set; } = "در صف";
    public string? Error { get; set; }
    public string? FileName { get; set; }
    public long FileSize { get; set; }
    public int Width { get; set; }
    public int Height { get; set; }
    public double Duration { get; set; }
    public DateTime Created { get; init; } = DateTime.Now;
    public double Seconds { get; set; }
    [JsonIgnore] public string? FilePath { get; set; }
    [JsonIgnore] internal CancellationTokenSource Cts { get; } = new();
    [JsonIgnore] public bool Finished => State is "done" or "failed" or "cancelled";
}

/// <summary>خطای اجرای ffmpeg (پیامِ فارسی + چند خطِ آخرِ خودِ ffmpeg).</summary>
public sealed class FFmpegException(string message) : Exception(message);

/// <summary>
/// همهٔ کارها در یک جا — برای سرور، آزمون و هر برنامهٔ .NETِ دیگر:
/// کتابخانه (data/videos/&lt;id&gt;/)، فریم و پیش‌نمایش، نوارِ فریم‌ها و موجِ صدا، سنجش و خودکار، یافتنِ مکث‌ها، LUTها، خروجی (صف) و هوشِ مصنوعی.
/// </summary>
public sealed class VideoService : IDisposable
{
    private readonly string _root, _lutDir;
    private readonly ConcurrentDictionary<string, VideoJob> _jobs = new();
    private readonly ConcurrentDictionary<string, SemaphoreSlim> _docLocks = new();
    private readonly SemaphoreSlim _exportGate = new(1, 1);
    private readonly SemaphoreSlim _previewGate = new(1, 1);

    public VideoService(string dataDir, FFmpegTool ff, VisionAgentOptions? ai = null, HttpMessageHandler? aiHandler = null)
    {
        _root = Path.Combine(dataDir, "videos");
        _lutDir = Path.Combine(dataDir, "luts");
        Directory.CreateDirectory(_root);
        Directory.CreateDirectory(_lutDir);
        FF = ff;
        Agent = new VisionAgent(ai ?? new VisionAgentOptions(), aiHandler);
    }

    public FFmpegTool FF { get; }
    public VisionAgent Agent { get; }
    /// <summary>کمترین جای خالیِ دیسک که باید بماند (MB) — پیش از بارگذاری و خروجی وارسی می‌شود.</summary>
    public long MinFreeDiskMB { get; set; } = 1500;
    /// <summary>ضلعِ کوچکِ پیش‌نمایشِ متحرک.</summary>
    public int PreviewShort { get; set; } = 360;
    public int StripCount { get; set; } = 12;

    // ───────────── کتابخانه ─────────────

    /// <summary>ویدیو را جریانی (بی نگه داشتن در حافظه) در کتابخانه می‌نویسد و می‌شناسد.</summary>
    public async Task<VideoDoc> CreateAsync(Stream data, string? name, long? length = null, CancellationToken ct = default)
    {
        if (!FF.Available) throw new InvalidOperationException("FFmpeg پیدا نشد — tools\\Install-FFmpeg.ps1 را اجرا کنید.");
        CheckDisk(length ?? 0);
        var id = DateTime.Now.ToString("yyMMdd-HHmmss") + "-" + Convert.ToHexString(RandomNumberGenerator.GetBytes(3)).ToLowerInvariant();
        var dir = Path.Combine(_root, id);
        Directory.CreateDirectory(dir);
        var ext = Path.GetExtension(name ?? "").ToLowerInvariant();
        if (ext.Length is < 2 or > 6 || ext.Any(c => !char.IsAsciiLetterOrDigit(c) && c != '.')) ext = ".mp4";
        var file = "source" + ext;
        try
        {
            await using (var fs = new FileStream(Path.Combine(dir, file), FileMode.CreateNew, FileAccess.Write, FileShare.None, 1 << 20, true))
                await data.CopyToAsync(fs, 1 << 20, ct);
            if (new FileInfo(Path.Combine(dir, file)).Length == 0) throw new InvalidDataException("فایل خالی است.");
            var media = await MediaInfo.ProbeAsync(FF, Path.Combine(dir, file), ct);
            if (media.Duration <= 0.05) throw new InvalidDataException("مدتِ این فایل معلوم نیست یا خیلی کوتاه است.");
            var doc = new VideoDoc(id, CleanName(name), DateTime.Now, file, media);
            File.WriteAllText(Path.Combine(dir, "doc.json"), JsonSerializer.Serialize(doc, VideoJson.Indented));
            return doc;
        }
        catch
        {
            try { Directory.Delete(dir, true); } catch (IOException) { }
            throw;
        }
    }

    public IReadOnlyList<VideoDoc> List() =>
        Directory.EnumerateDirectories(_root).Select(d => TryGet(Path.GetFileName(d))).OfType<VideoDoc>()
            .OrderByDescending(d => d.Created).ToList();

    public VideoDoc Get(string id) => TryGet(id) ?? throw new KeyNotFoundException($"ویدیوی «{id}» پیدا نشد.");

    private VideoDoc? TryGet(string id)
    {
        if (!IsSafeId(id)) return null;
        var f = Path.Combine(_root, id, "doc.json");
        return File.Exists(f) ? JsonSerializer.Deserialize<VideoDoc>(File.ReadAllText(f), VideoJson.Options) : null;
    }

    public void Delete(string id)
    {
        Get(id);
        foreach (var j in _jobs.Values.Where(j => j.DocId == id && !j.Finished)) j.Cts.Cancel();
        for (int i = 0; ; i++)
        {
            try { Directory.Delete(Path.Combine(_root, id), true); return; }
            catch (IOException) when (i < 10) { Thread.Sleep(200); }   // ffmpegِ لغوشده هنوز فایل را رها نکرده
        }
    }

    public string SourcePath(string id) => Path.Combine(_root, id, Get(id).SourceFile);
    private string Dir(string id) => Path.Combine(_root, id);
    private string WorkDir(string id) { var d = Path.Combine(_root, id, "work"); Directory.CreateDirectory(d); return d; }
    private string ExportDir(string id) { var d = Path.Combine(_root, id, "exports"); Directory.CreateDirectory(d); return d; }

    public VideoRecipe LoadRecipe(string id)
    {
        var f = Path.Combine(Dir(Get(id).Id), "recipe.json");
        return File.Exists(f) ? VideoRecipe.Parse(File.ReadAllText(f)) : new VideoRecipe();
    }

    public void SaveRecipe(string id, VideoRecipe r) =>
        File.WriteAllText(Path.Combine(Dir(Get(id).Id), "recipe.json"), r.Normalized().ToJson(true));

    // ───────────── فریم، نوارِ فریم‌ها، موجِ صدا ─────────────

    /// <summary>یک فریم (JPEG) در زمانِ <paramref name="t"/> (ثانیه روی فایلِ اصلی) با نسخه — یا اصل، برای قبل/بعد.</summary>
    public async Task<(byte[] Jpeg, int W, int H)> FrameAsync(string id, VideoRecipe r, double t, int maxSide = 1280, bool original = false, CancellationToken ct = default)
    {
        var d = Get(id);
        if (!d.Media.HasVideo) throw new InvalidDataException("این فایل تصویر ندارد (فقط صدا).");
        var work = WorkDir(id);
        var ctx = new RenderContext
        {
            Media = d.Media, Source = SourcePath(id), LutFile = original ? null : PrepareLut(work, r),
            FrameTime = t, MaxSide = Math.Clamp(maxSide, 64, 3840), Original = original,
        };
        var plan = FilterGraph.Build(r, ctx, RenderKind.Frame);
        var res = await FF.FFmpegAsync(plan.Args, ct, captureStdOut: true, workDir: work);
        if (!res.Ok || res.StdOut.Length == 0) throw new FFmpegException("ساختنِ فریم نشد: " + res.ErrorTail);
        return (res.StdOut, plan.Width, plan.Height);
    }

    public async Task<byte[]> ThumbAsync(string id, CancellationToken ct = default)
    {
        var f = Path.Combine(Dir(Get(id).Id), "thumb.jpg");
        if (File.Exists(f)) return await File.ReadAllBytesAsync(f, ct);
        var d = Get(id);
        if (!d.Media.HasVideo) throw new InvalidDataException("این فایل تصویر ندارد (فقط صدا).");
        var (jpg, _, _) = await FrameAsync(id, new VideoRecipe(), Math.Min(d.Media.Duration * 0.1, 3), 320, original: true, ct);
        await File.WriteAllBytesAsync(f, jpg, ct);
        return jpg;
    }

    /// <summary>فریمِ i از نوارِ فریم‌های زیرِ خطِ زمان (اصل، ارتفاعِ ۷۲ پیکسل). بارِ اول همه ساخته می‌شوند.</summary>
    public async Task<byte[]> StripAsync(string id, int i, CancellationToken ct = default)
    {
        var d = Get(id);
        if (!d.Media.HasVideo) throw new InvalidDataException("این فایل تصویر ندارد.");
        i = Math.Clamp(i, 0, StripCount - 1);
        var dir = Path.Combine(Dir(id), "strip");
        var f = Path.Combine(dir, $"{i:00}.jpg");
        if (File.Exists(f)) return await File.ReadAllBytesAsync(f, ct);
        var lk = _docLocks.GetOrAdd(id + ":strip", _ => new SemaphoreSlim(1, 1));
        await lk.WaitAsync(ct);
        try
        {
            Directory.CreateDirectory(dir);
            var maxSide = (int)Math.Round(72.0 * Math.Max(d.Media.Width, d.Media.Height) / Math.Max(1, d.Media.Height));
            for (int k = 0; k < StripCount; k++)
            {
                var fk = Path.Combine(dir, $"{k:00}.jpg");
                if (File.Exists(fk)) continue;
                var (jpg, _, _) = await FrameAsync(id, new VideoRecipe(), d.Media.Duration * (k + 0.5) / StripCount, maxSide, original: true, ct);
                await File.WriteAllBytesAsync(fk, jpg, ct);
            }
        }
        finally { lk.Release(); }
        return await File.ReadAllBytesAsync(f, ct);
    }

    /// <summary>تصویرِ موجِ صدا (PNG، ۱۶۰۰×۱۰۰) — null اگر صدا ندارد.</summary>
    public async Task<byte[]?> WaveformAsync(string id, CancellationToken ct = default)
    {
        var d = Get(id);
        if (!d.Media.HasAudio) return null;
        var f = Path.Combine(Dir(id), "wave.png");
        if (File.Exists(f)) return await File.ReadAllBytesAsync(f, ct);
        var lk = _docLocks.GetOrAdd(id + ":wave", _ => new SemaphoreSlim(1, 1));
        await lk.WaitAsync(ct);
        try
        {
            if (!File.Exists(f))
            {
                var res = await FF.FFmpegAsync(new[] { "-y", "-i", SourcePath(id), "-filter_complex",
                    "[0:a]aformat=channel_layouts=mono,showwavespic=s=1600x100:colors=0x7aa7ff:scale=sqrt:draw=full[w]", "-map", "[w]", "-frames:v", "1", "wave.png" },
                    ct, workDir: Dir(id));
                if (!res.Ok) throw new FFmpegException("ساختنِ موجِ صدا نشد: " + res.ErrorTail);
            }
        }
        finally { lk.Release(); }
        return await File.ReadAllBytesAsync(f, ct);
    }

    /// <summary>تصویرِ ۲×۲ از چهار لحظهٔ فیلم (درونِ بُرش) — برای هوشِ مصنوعی.</summary>
    public async Task<byte[]> SheetAsync(string id, VideoRecipe? r, int cell = 256, CancellationToken ct = default)
    {
        var d = Get(id);
        var recipe = r ?? new VideoRecipe();
        var (ts, te) = FilterGraph.TrimRange(recipe, d.Media);
        var work = WorkDir(id);
        var names = new List<string>();
        var tag = Convert.ToHexString(RandomNumberGenerator.GetBytes(3));
        try
        {
            for (int i = 0; i < 4; i++)
            {
                var t = ts + (te - ts) * (i * 2 + 1) / 8.0;
                var (jpg, _, _) = await FrameAsync(id, recipe, t, cell, original: r is null, ct);
                var n = $"sheet_{tag}_{i}.jpg";
                await File.WriteAllBytesAsync(Path.Combine(work, n), jpg, ct);
                names.Add(n);
            }
            var args = new List<string> { "-y" };
            foreach (var n in names) { args.Add("-i"); args.Add(n); }
            args.AddRange(new[] { "-filter_complex", "[0][1]hstack=2[t];[2][3]hstack=2[b];[t][b]vstack=2,format=yuvj420p",
                "-frames:v", "1", "-q:v", "4", "-f", "image2pipe", "-c:v", "mjpeg", "-" });
            var res = await FF.FFmpegAsync(args, ct, captureStdOut: true, workDir: work);
            if (!res.Ok) throw new FFmpegException("ساختنِ تصویرِ نمونه نشد: " + res.ErrorTail);
            return res.StdOut;
        }
        finally
        {
            foreach (var n in names) File.Delete(Path.Combine(work, n));
        }
    }

    // ───────────── سنجش، خودکار، مکث‌ها، هوشِ مصنوعی ─────────────

    public async Task<VideoStats> AnalyzeAsync(string id, bool force = false, CancellationToken ct = default)
    {
        var d = Get(id);
        var f = Path.Combine(Dir(id), "stats.json");
        if (!force && File.Exists(f)) return JsonSerializer.Deserialize<VideoStats>(await File.ReadAllTextAsync(f, ct), VideoJson.Options)!;
        var s = await Analysis.MeasureAsync(FF, SourcePath(id), d.Media, ct: ct);
        await File.WriteAllTextAsync(f, JsonSerializer.Serialize(s, VideoJson.Indented), ct);
        return s;
    }

    /// <summary>کفِ نویزِ صدا (dBFS): از سنجشِ ذخیره‌شده، وگرنه از ۳۰ ثانیهٔ اول (سریع) — برای تنظیمِ کاهشِ نویز.</summary>
    public async Task<double?> NoiseFloorAsync(string id, CancellationToken ct = default)
    {
        var f = Path.Combine(Dir(id), "stats.json");
        if (File.Exists(f) && JsonSerializer.Deserialize<VideoStats>(await File.ReadAllTextAsync(f, ct), VideoJson.Options) is { } s && double.IsFinite(s.NoiseFloor))
            return s.NoiseFloor;
        var nf = Path.Combine(Dir(id), "noise.txt");
        if (File.Exists(nf) && double.TryParse(await File.ReadAllTextAsync(nf, ct), System.Globalization.NumberStyles.Float, System.Globalization.CultureInfo.InvariantCulture, out var cached))
            return cached;
        var (db, _) = Analysis.NoiseFloor(await Analysis.PcmAsync(FF, SourcePath(id), 16000, 30, ct), 16000);
        if (!double.IsFinite(db)) return null;
        await File.WriteAllTextAsync(nf, db.ToString(System.Globalization.CultureInfo.InvariantCulture), ct);
        return db;
    }

    public async Task<AutoResult> AutoAsync(string id, CancellationToken ct = default) => Analysis.Auto(await AnalyzeAsync(id, ct: ct), Get(id).Media);

    /// <summary>
    /// مکث‌ها (سکوت‌های بلندتر از <paramref name="minPause"/>) ⇒ بازه‌های پیشنهادی برای حذف.
    /// آستانه null ⇒ خودکار: کفِ نویزِ همین فایل + ۹ دسی‌بل (مکثِ ضبطِ پرنویز هم سکوت حساب شود).
    /// </summary>
    public async Task<(List<TimeRange> Silences, List<TimeRange> Cuts, double Saved, double Threshold)> PausesAsync(string id, double? silenceDb = null, double minPause = 0.6, double padding = 0.15, CancellationToken ct = default)
    {
        var d = Get(id);
        if (!d.Media.HasAudio) throw new InvalidDataException("این فایل صدا ندارد.");
        var thr = silenceDb ?? (await NoiseFloorAsync(id, ct) is { } fl && double.IsFinite(fl) ? Math.Clamp(Math.Round(fl + 9), -55, -25) : -38);
        var s = await Analysis.MeasureAudioAsync(FF, SourcePath(id), d.Media, new VideoStats { HasAudio = true }, ct, thr, Math.Max(0.2, minPause));
        var cuts = Analysis.PausesToCuts(s.Silences, padding, minPause);
        return (s.Silences, cuts, cuts.Sum(c => c.End - c.Start), thr);
    }

    public async Task<AgentResult> AiEditAsync(string id, string? goal, VideoRecipe current, CancellationToken ct = default)
    {
        var d = Get(id);
        var stats = await AnalyzeAsync(id, ct: ct);
        var auto = Analysis.Auto(stats, d.Media);
        var cell = Agent.Options.CellSide;
        var sheet = d.Media.HasVideo ? await SheetAsync(id, null, cell, ct) : Array.Empty<byte>();
        return await Agent.EditAsync(sheet, stats.Describe(d.Media), auto, goal, current,
            r => d.Media.HasVideo ? SheetAsync(id, r, cell, ct) : Task.FromResult(Array.Empty<byte>()), ct);
    }

    // ───────────── LUT ─────────────

    /// <summary>فایلِ .cubeِ کاربر را (بعد از وارسی) در data/luts می‌گذارد ⇒ نامی که در recipe.lut.file می‌آید.</summary>
    public string SaveLut(byte[] data, string? name)
    {
        var text = Encoding.UTF8.GetString(data);
        CubeLut.Parse(text);
        var n = CleanName(name);
        n = new string(n.Select(c => char.IsLetterOrDigit(c) || c is '-' or '_' ? c : '_').ToArray());
        if (n.Length == 0) n = "lut";
        var file = n + ".cube";
        File.WriteAllText(Path.Combine(_lutDir, file), text, new UTF8Encoding(false));
        return file;
    }

    public IReadOnlyList<string> Luts() => Directory.EnumerateFiles(_lutDir, "*.cube").Select(Path.GetFileName).OfType<string>().OrderBy(x => x).ToList();

    private readonly ConcurrentDictionary<string, (DateTime Stamp, CubeLut Lut, string Hash)> _userLuts = new();

    private string? PrepareLut(string work, VideoRecipe r)
    {
        if (!ColorLut.Needed(r)) return null;
        CubeLut? user = null; string? hash = null;
        if (r.Lut is { } l)
        {
            var p = Path.Combine(_lutDir, l.File);
            if (!File.Exists(p)) throw new ArgumentException($"LUTِ «{l.File}» نیست؛ اول بارگذاری کنید (POST /api/luts).");
            var stamp = File.GetLastWriteTimeUtc(p);
            if (!_userLuts.TryGetValue(p, out var c) || c.Stamp != stamp)
            {
                var text = File.ReadAllText(p);
                c = (stamp, CubeLut.Parse(text), Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(text)))[..12]);
                _userLuts[p] = c;
            }
            (user, hash) = (c.Lut, c.Hash);
        }
        var name = "lut_" + ColorLut.Key(r, hash) + ".cube";
        var path = Path.Combine(work, name);
        if (!File.Exists(path))
        {
            ColorLut.Write(r, path, user);
            // هر تغییرِ لغزنده یک LUT (~۱MB) ⇒ فقط ۲۰ تای آخر می‌مانند
            foreach (var old in new DirectoryInfo(work).GetFiles("lut_*.cube").OrderByDescending(x => x.LastWriteTimeUtc).Skip(20))
                try { old.Delete(); } catch (IOException) { }
        }
        else File.SetLastWriteTimeUtc(path, DateTime.UtcNow);
        return name;
    }

    // ───────────── کارهای پس‌زمینه ─────────────

    /// <summary>پیش‌نمایشِ متحرک (MP4ِ کوچک) از <paramref name="start"/> به مدتِ <paramref name="duration"/> — پیش‌نمایشِ قبلیِ همین ویدیو لغو می‌شود.</summary>
    public VideoJob StartPreview(string id, VideoRecipe r, double start, double duration = 6)
    {
        var d = Get(id);
        foreach (var old in _jobs.Values.Where(j => j.DocId == id && j.Kind == "preview" && !j.Finished)) old.Cts.Cancel();
        var job = NewJob(id, "preview");
        var rec = r.Normalized();
        _ = Task.Run(() => RunAsync(job, _previewGate, () => RenderJobAsync(job, d, rec, RenderKind.Preview, start, Math.Clamp(duration, 1, 60))));
        return job;
    }

    /// <summary>خروجی در صف (یکی یکی، با اولویتِ پایین) ⇒ کار با پیشرفت؛ فایل در data/videos/&lt;id&gt;/exports.</summary>
    public VideoJob StartExport(string id, VideoRecipe r)
    {
        var d = Get(id);
        CheckDisk(0);
        var job = NewJob(id, "export");
        var rec = r.Normalized();
        _ = Task.Run(() => RunAsync(job, _exportGate, () => RenderJobAsync(job, d, rec, RenderKind.Export, 0, 0)));
        return job;
    }

    public VideoJob? GetJob(string jobId) => _jobs.GetValueOrDefault(jobId);
    public IReadOnlyList<VideoJob> Jobs(string? docId = null) =>
        _jobs.Values.Where(j => docId is null || j.DocId == docId).OrderByDescending(j => j.Created).ToList();

    public bool CancelJob(string jobId)
    {
        if (!_jobs.TryGetValue(jobId, out var j) || j.Finished) return false;
        j.Cts.Cancel();
        return true;
    }

    /// <summary>منتظرِ پایانِ یک کار (برای برنامه‌ها و آزمون).</summary>
    public async Task<VideoJob> WaitAsync(VideoJob job, CancellationToken ct = default)
    {
        while (!job.Finished) await Task.Delay(100, ct);
        return job;
    }

    private VideoJob NewJob(string docId, string kind)
    {
        var job = new VideoJob { Id = Convert.ToHexString(RandomNumberGenerator.GetBytes(5)).ToLowerInvariant(), DocId = docId, Kind = kind };
        _jobs[job.Id] = job;
        foreach (var old in _jobs.Values.Where(j => j.Finished).OrderByDescending(j => j.Created).Skip(60)) _jobs.TryRemove(old.Id, out _);
        return job;
    }

    private static async Task RunAsync(VideoJob job, SemaphoreSlim gate, Func<Task> work)
    {
        var sw = Stopwatch.StartNew();
        try
        {
            await gate.WaitAsync(job.Cts.Token);
            try { await work(); }
            finally { gate.Release(); }
        }
        catch (OperationCanceledException) { job.State = "cancelled"; job.Stage = "لغو شد"; }
        catch (Exception e) { job.State = "failed"; job.Error = e.Message; job.Stage = "خطا"; }
        finally { job.Seconds = Math.Round(sw.Elapsed.TotalSeconds, 2); }
    }

    private async Task RenderJobAsync(VideoJob job, VideoDoc d, VideoRecipe r, RenderKind kind, double pStart, double pDur)
    {
        var ct = job.Cts.Token;
        job.State = "running";
        job.Stage = "آماده‌سازی";
        var work = WorkDir(d.Id);
        var src = SourcePath(d.Id);
        var o = r.Output ?? new OutputSettings();
        var lut = PrepareLut(work, r);
        var floor = r.Has("noise") && d.Media.HasAudio ? await NoiseFloorAsync(d.Id, ct) : (double?)null;
        var baseCtx = new RenderContext
        {
            Media = d.Media, Source = src, LutFile = lut, PreviewStart = pStart, PreviewDuration = pDur, PreviewShort = PreviewShort, NoiseFloorDb = floor,
        };
        var (ts, te) = FilterGraph.TrimRange(r, d.Media);
        double inDur = kind == RenderKind.Preview ? Math.Min(pDur, te - Math.Clamp(pStart, ts, te)) : te - ts;

        // ۱) تثبیت: تحلیلِ لرزش (نتیجه نگه داشته می‌شود تا نسخهٔ بعدی دوباره تحلیل نکند)
        string? trf = null;
        double share = 0;
        if (r.Stabilize is not null && d.Media.HasVideo && !(kind == RenderKind.Export && o.AudioOnly))
        {
            var key = Hash($"{kind}|{FFmpegTool.F(kind == RenderKind.Preview ? pStart : ts)}|{FFmpegTool.F(inDur)}|{PreviewShort}");
            trf = $"stab_{key}.trf";
            share = 0.35;
            if (!File.Exists(Path.Combine(work, trf)))
            {
                job.Stage = "تحلیلِ لرزشِ دوربین";
                var tmp = $"stab_{key}_{job.Id}.part";
                var res = await FF.FFmpegAsync(FilterGraph.StabilizeDetect(r, baseCtx, kind, tmp), ct,
                    s => job.Progress = share * Math.Clamp(s / Math.Max(0.1, inDur), 0, 1), workDir: work);
                if (!res.Ok) { File.Delete(Path.Combine(work, tmp)); throw new FFmpegException("تحلیلِ لرزش نشد: " + res.ErrorTail); }
                File.Move(Path.Combine(work, tmp), Path.Combine(work, trf), true);
            }
        }
        // ۲) هم‌سطح‌سازیِ دقیق: پاسِ اول فقط صدا را می‌سنجد
        LoudnessMeasure? lm = null;
        if (kind == RenderKind.Export && r.Audio is { Normalize: < 0, Mute: false } && d.Media.HasAudio && o.Format != "gif")
        {
            job.Stage = "سنجشِ بلندیِ صدا";
            var res = await FF.FFmpegAsync(FilterGraph.LoudnessMeasurePass(r, baseCtx), ct, workDir: work);
            lm = res.Ok ? LoudnessMeasure.Parse(res.StdErr) : null;
        }
        var ctx = new RenderContext
        {
            Media = d.Media, Source = src, LutFile = lut, TrfFile = trf, Loudness = lm,
            PreviewStart = pStart, PreviewDuration = pDur, PreviewShort = PreviewShort, NoiseFloorDb = floor,
        };
        // ۳) ساختن
        string outDir = kind == RenderKind.Preview ? work : ExportDir(d.Id);
        string outName = kind == RenderKind.Preview ? $"preview_{job.Id}.mp4" : UniqueName(outDir, SafeFileName(d.Name) + "-edited", o.Extension);
        var partName = $"part_{job.Id}{(kind == RenderKind.Preview ? ".mp4" : o.Extension)}";
        var plan = FilterGraph.Build(r, ctx, kind, Path.Combine(outDir, partName));
        job.Stage = kind == RenderKind.Preview ? "ساختنِ پیش‌نمایش" : "ساختنِ خروجی";
        var total = Math.Max(0.1, plan.OutDuration);
        var main = await FF.FFmpegAsync(plan.Args, ct, s => job.Progress = share + (1 - share) * Math.Clamp(s / total, 0, 1), workDir: work);
        var partPath = Path.Combine(outDir, partName);
        if (!main.Ok || !File.Exists(partPath))
        {
            File.Delete(partPath);
            throw new FFmpegException("ساختن نشد: " + main.ErrorTail);
        }
        var outPath = Path.Combine(outDir, outName);
        File.Move(partPath, outPath, true);
        job.FilePath = outPath; job.FileName = outName; job.FileSize = new FileInfo(outPath).Length;
        job.Width = plan.Width; job.Height = plan.Height; job.Duration = Math.Round(plan.OutDuration, 2);
        job.Progress = 1; job.State = "done"; job.Stage = "تمام";
        // جای دیسک: فقط آخرین پیش‌نمایش و ۵ خروجیِ آخرِ هر ویدیو
        if (kind == RenderKind.Preview)
            foreach (var old in Directory.GetFiles(work, "preview_*.mp4").Where(p => p != outPath)) TryDelete(old);
        else   // زمانِ ساختن نه: ویندوز به فایلِ هم‌نامِ تازه زمانِ فایلِ پاک‌شده را می‌دهد (tunneling)
            foreach (var old in new DirectoryInfo(outDir).GetFiles().Where(x => x.FullName != outPath)
                         .OrderByDescending(x => x.LastWriteTimeUtc).Skip(4)) TryDelete(old.FullName);
    }

    // ───────────── کمکی ─────────────

    private void CheckDisk(long incoming)
    {
        var drive = new DriveInfo(Path.GetPathRoot(Path.GetFullPath(_root))!);
        var freeMB = drive.AvailableFreeSpace / 1048576;
        var needMB = incoming / 1048576 + MinFreeDiskMB;
        if (freeMB < needMB)
            throw new InvalidOperationException($"جای خالیِ دیسک کم است ({freeMB:N0}MB آزاد؛ دست‌کم {needMB:N0}MB لازم است). چند ویدیو یا خروجیِ قدیمی را پاک کنید.");
    }

    private static string Hash(string s) => Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(s)))[..12].ToLowerInvariant();

    private static void TryDelete(string path) { try { File.Delete(path); } catch (IOException) { } catch (UnauthorizedAccessException) { } }

    private static string UniqueName(string dir, string stem, string ext)
    {
        var n = stem + ext;
        for (int i = 2; File.Exists(Path.Combine(dir, n)); i++) n = $"{stem}-{i}{ext}";
        return n;
    }

    private static bool IsSafeId(string id) => id.Length is > 0 and < 64 && id.All(ch => char.IsAsciiLetterOrDigit(ch) || ch == '-');

    private static string CleanName(string? n)
    {
        n = Path.GetFileNameWithoutExtension(n ?? "") ?? "";
        n = new string(n.Where(ch => !Path.GetInvalidFileNameChars().Contains(ch)).ToArray()).Trim();
        return n.Length == 0 ? "ویدیو" : n.Length > 80 ? n[..80] : n;
    }

    private static string SafeFileName(string n)
    {
        var s = new string(n.Select(c => Path.GetInvalidFileNameChars().Contains(c) ? '_' : c).ToArray()).Trim();
        return s.Length == 0 ? "video" : s;
    }

    public void Dispose()
    {
        foreach (var j in _jobs.Values.Where(j => !j.Finished)) j.Cts.Cancel();
    }
}
