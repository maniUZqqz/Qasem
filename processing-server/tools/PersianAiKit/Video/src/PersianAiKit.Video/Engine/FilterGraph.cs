using System.Globalization;
using System.Text;
using System.Text.Json;

namespace PersianAiKit.Video.Engine;

public enum RenderKind { Frame, Preview, Export }

/// <summary>نتیجهٔ پاسِ اولِ loudnorm (برای هم‌سطح‌سازیِ دقیق و خطی در پاسِ دوم).</summary>
public sealed record LoudnessMeasure(double I, double TP, double LRA, double Thresh, double Offset)
{
    /// <summary>بلوکِ JSONِ آخرِ خروجیِ loudnorm=print_format=json.</summary>
    public static LoudnessMeasure? Parse(string stderr)
    {
        var end = stderr.LastIndexOf('}');
        var start = end < 0 ? -1 : stderr.LastIndexOf('{', end);
        if (start < 0) return null;
        try
        {
            using var doc = JsonDocument.Parse(stderr[start..(end + 1)]);
            var r = doc.RootElement;
            double G(string n) => double.TryParse(r.GetProperty(n).GetString(), NumberStyles.Float, CultureInfo.InvariantCulture, out var d) ? d : double.NaN;
            var m = new LoudnessMeasure(G("input_i"), G("input_tp"), G("input_lra"), G("input_thresh"), G("target_offset"));
            return double.IsFinite(m.I) && m.I > -70 ? m : null;   // سکوتِ کامل ⇒ -inf
        }
        catch (Exception e) when (e is JsonException or KeyNotFoundException or InvalidOperationException) { return null; }
    }
}

/// <summary>یک اجرای ffmpeg که ساخته شده: آرگومان‌ها + اندازه و مدتِ خروجی.</summary>
public sealed record RenderPlan(List<string> Args, int Width, int Height, double OutDuration, bool HasVideo, bool HasAudio);

/// <summary>هر چیزی که زنجیره جز نسخه لازم دارد.</summary>
public sealed class RenderContext
{
    public required MediaInfo Media { get; init; }
    /// <summary>فایلِ اصلی (مسیرِ کامل).</summary>
    public required string Source { get; init; }
    /// <summary>نامِ فایلِ LUT در پوشهٔ کار (ffmpeg با همین پوشه اجرا می‌شود ⇒ نامِ ساده، بی دردسرِ «:» و «\»).</summary>
    public string? LutFile { get; init; }
    /// <summary>نتیجهٔ تحلیلِ لرزش (vidstabdetect) در پوشهٔ کار.</summary>
    public string? TrfFile { get; init; }
    public LoudnessMeasure? Loudness { get; init; }
    /// <summary>کفِ نویزِ سنجیده‌شدهٔ صدا (dBFS) — کاهشِ نویز با همین تنظیم می‌شود.</summary>
    public double? NoiseFloorDb { get; init; }
    /// <summary>فریم: زمان (ثانیه روی فایلِ اصلی) و بزرگ‌ترین ضلع.</summary>
    public double FrameTime { get; init; }
    public int MaxSide { get; init; } = 1280;
    /// <summary>فریم: بی هیچ ویرایشی (برای قبل/بعد).</summary>
    public bool Original { get; init; }
    /// <summary>پیش‌نمایشِ متحرک: از کجا و چقدر (زمانِ فایلِ اصلی)، ضلعِ کوچکِ خروجی.</summary>
    public double PreviewStart { get; init; }
    public double PreviewDuration { get; init; } = 6;
    public int PreviewShort { get; init; } = 360;
}

/// <summary>
/// نسخهٔ ویرایش ⇒ آرگومان‌های ffmpeg. ترتیبِ تصویر (مثلِ ترتیبِ پیشنهادیِ پریمیر برای کیفیت):
/// درهم‌رفتگی ⇐ HDR به SDR ⇐ تثبیت ⇐ حذفِ بازه‌ها ⇐ سرعت ⇐ لنز ⇐ چرخش، برش، قرینه ⇐ نویزگیری ⇐ LUTِ رنگ ⇐ وضوح ⇐ شارپ ⇐ وینیت، دانه ⇐ قاب ⇐ اندازه، نرخِ فریم ⇐ محدودهٔ پخش ⇐ محو.
/// صدا: حذفِ بازه‌ها ⇐ سرعت ⇐ غرش ⇐ وزوزِ برق ⇐ کلیک ⇐ نویز ⇐ سین ⇐ اکولایزر ⇐ کمپرسور ⇐ بلندی ⇐ هم‌سطح‌سازی ⇐ محو.
/// </summary>
public static class FilterGraph
{
    private static readonly CultureInfo Ci = CultureInfo.InvariantCulture;
    private static string F(double v, int d = 4) => FFmpegTool.F(v, d);
    private static int Even(double x) => Math.Max(2, (int)Math.Round(x / 2) * 2);

    // ───────────── زمان ─────────────

    public static (double Start, double End) TrimRange(VideoRecipe r, MediaInfo m)
    {
        var dur = m.Duration > 0 ? m.Duration : 0;
        var s = Math.Clamp(r.Trim?.Start ?? 0, 0, Math.Max(0, dur - 0.05));
        var e = r.Trim is { End: > 0 } t ? Math.Min(t.End, dur) : dur;
        return (s, Math.Max(s + 0.05, e));
    }

    /// <summary>بخش‌هایی از [start, start+dur] که می‌مانند (نسبت به start).</summary>
    public static List<(double S, double E)> Keep(VideoRecipe r, double start, double dur)
    {
        var keep = new List<(double, double)>();
        double cur = 0;
        foreach (var c in r.Cuts ?? new List<TimeRange>())
        {
            double s = c.Start - start, e = c.End - start;
            if (e <= 0 || s >= dur) continue;
            s = Math.Max(0, s); e = Math.Min(dur, e);
            if (s > cur + 0.02) keep.Add((cur, s));
            cur = Math.Max(cur, e);
        }
        if (dur > cur + 0.02) keep.Add((cur, dur));
        return keep;
    }

    /// <summary>مدتِ خروجی (بعد از بُرش، حذفِ بازه‌ها و سرعت).</summary>
    public static double OutDuration(VideoRecipe r, MediaInfo m)
    {
        var (s, e) = TrimRange(r, m);
        return Keep(r, s, e - s).Sum(k => k.E - k.S) / r.Speed;
    }

    // ───────────── ساختن ─────────────

    public static RenderPlan Build(VideoRecipe r, RenderContext ctx, RenderKind kind, string outputFile = "-")
    {
        var m = ctx.Media;
        var o = r.Output ?? new OutputSettings();
        var args = new List<string> { "-y" };
        double inStart, inDur;
        if (kind == RenderKind.Frame)
        {
            inStart = Math.Clamp(ctx.FrameTime, 0, Math.Max(0, m.Duration - 0.04));
            inDur = 0;
        }
        else
        {
            var (ts, te) = TrimRange(r, m);
            if (kind == RenderKind.Preview)
            {
                inStart = Math.Clamp(ctx.PreviewStart, ts, Math.Max(ts, te - 0.2));
                inDur = Math.Min(ctx.PreviewDuration, te - inStart);
            }
            else { inStart = ts; inDur = te - ts; }
        }
        if (inStart > 0) { args.Add("-ss"); args.Add(F(inStart, 3)); }
        if (inDur > 0) { args.Add("-t"); args.Add(F(inDur, 3)); }
        args.Add("-i"); args.Add(ctx.Source);

        bool audioOnly = kind == RenderKind.Export && o.AudioOnly;
        bool wantVideo = m.HasVideo && !audioOnly;
        bool wantAudio = kind != RenderKind.Frame && m.HasAudio && !(r.Audio?.Mute ?? false) && o.Format != "gif";
        var keep = kind == RenderKind.Frame ? new List<(double S, double E)>() : Keep(r, inStart, inDur);
        bool cutting = keep.Count != 1 || keep[0].S > 0.001 || keep[0].E < inDur - 0.001;
        var outDur = kind == RenderKind.Frame ? 0 : keep.Sum(k => k.E - k.S) / r.Speed;
        var graph = new List<string>();
        int W = 0, H = 0;

        if (wantVideo)
        {
            var (chain, w, h) = VideoChain(r, ctx, kind, keep, cutting, outDur, o);
            graph.Add(chain);
            W = w; H = h;
        }
        if (wantAudio) graph.Add(AudioChain(r, ctx, kind, keep, cutting, outDur, includeNormalize: true));

        if (graph.Count > 0) { args.Add("-filter_complex"); args.Add(string.Join(";", graph)); }
        if (wantVideo) { args.Add("-map"); args.Add("[vout]"); }
        if (wantAudio) { args.Add("-map"); args.Add("[aout]"); }
        if (!wantAudio) args.Add("-an");
        if (!wantVideo) args.Add("-vn");
        args.Add("-sn"); args.Add("-dn");

        switch (kind)
        {
            case RenderKind.Frame:
                args.AddRange(new[] { "-frames:v", "1", "-f", "image2pipe", "-c:v", "mjpeg", "-q:v", "3", outputFile });
                break;
            case RenderKind.Preview:
                args.AddRange(new[] { "-c:v", "libx264", "-preset", "ultrafast", "-crf", "30", "-pix_fmt", "yuv420p", "-movflags", "+faststart" });
                if (wantAudio) args.AddRange(new[] { "-c:a", "aac", "-b:a", "96k" });
                args.Add(outputFile);
                break;
            default:
                args.AddRange(Encoder(o, wantVideo, wantAudio, m.Hdr));
                args.Add(outputFile);
                break;
        }
        return new RenderPlan(args, W, H, outDur, wantVideo, wantAudio);
    }

    /// <summary>پاسِ اولِ تثبیت: همان ورودی و همان فیلترهای پیش از تثبیت + vidstabdetect ⇒ فایلِ trf.</summary>
    public static List<string> StabilizeDetect(VideoRecipe r, RenderContext ctx, RenderKind kind, string trfFile)
    {
        var plan = Build(r, ctx, kind);   // فقط برای ورودی
        var args = TakeInput(plan.Args);
        var (pre, _, _) = PreChain(r, ctx, kind);
        pre.Add($"vidstabdetect=shakiness=6:accuracy=12:stepsize=6:result={trfFile}");
        args.AddRange(new[] { "-vf", string.Join(",", pre), "-an", "-f", "null", "-" });
        return args;
    }

    /// <summary>پاسِ اولِ هم‌سطح‌سازی: همان ورودی و زنجیرهٔ صدا تا پیش از loudnorm + اندازه‌گیری.</summary>
    public static List<string> LoudnessMeasurePass(VideoRecipe r, RenderContext ctx)
    {
        var m = ctx.Media;
        var plan = Build(r, ctx, RenderKind.Export);
        var args = TakeInput(plan.Args);
        var (ts, te) = TrimRange(r, m);
        var keep = Keep(r, ts, te - ts);
        bool cutting = keep.Count != 1 || keep[0].S > 0.001 || keep[0].E < te - ts - 0.001;
        var chain = AudioChain(r, ctx, RenderKind.Export, keep, cutting, keep.Sum(k => k.E - k.S) / r.Speed, includeNormalize: false);
        var target = r.Audio?.Normalize ?? -14;
        chain = chain.Replace("[aout]", $",loudnorm=I={F(target, 1)}:TP=-1.5:LRA=11:print_format=json[aout]");
        args.AddRange(new[] { "-filter_complex", chain, "-map", "[aout]", "-vn", "-f", "null", "-" });
        return args;
    }

    private static List<string> TakeInput(List<string> full)
    {
        var i = full.IndexOf("-i");
        return full.Take(i + 2).ToList();
    }

    // ───────────── تصویر ─────────────

    /// <summary>فیلترهای پیش از تثبیت (برای پاسِ تحلیل هم همین‌ها): درهم‌رفتگی، کوچک کردنِ پیش‌نمایش، HDR.</summary>
    private static (List<string> Chain, double W, double H) PreChain(VideoRecipe r, RenderContext ctx, RenderKind kind)
    {
        var m = ctx.Media;
        var f = new List<string>();
        double w = m.Width, h = m.Height;
        if (m.Interlaced) f.Add("bwdif=mode=send_frame");
        // پیش‌نمایش و فریم روی نسخهٔ کوچک ⇒ چند برابر سریع‌تر
        double k = 1;
        if (kind == RenderKind.Frame) k = Math.Min(1, ctx.MaxSide * 1.5 / Math.Max(w, h));
        else if (kind == RenderKind.Preview) k = Math.Min(1, ctx.PreviewShort * 1.5 / Math.Min(w, h));
        if (k < 0.999)
        {
            w = Even(w * k); h = Even(h * k);
            f.Add($"scale={(int)w}:{(int)h}:flags=bilinear");
        }
        if (m.Hdr && !ctx.Original)
            f.Add("zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,tonemap=tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv,format=yuv420p");
        return (f, w, h);
    }

    private static (string Chain, int W, int H) VideoChain(VideoRecipe r, RenderContext ctx, RenderKind kind, List<(double S, double E)> keep, bool cutting, double outDur, OutputSettings o)
    {
        var m = ctx.Media;
        var (f, w, h) = PreChain(r, ctx, kind);
        var parts = new List<string>();
        string Label(string name) => $"[{name}]";
        string cur = "0:v";

        void Flush(string next)
        {
            parts.Add($"[{cur}]{(f.Count > 0 ? string.Join(",", f) : "null")}{Label(next)}");
            f.Clear();
            cur = next;
        }

        if (ctx.Original)
        {
            f.Add(FitBox(w, h, ctx.MaxSide, out var ow, out var oh));
            f.Add("format=yuvj420p");
            Flush("vout");
            return (string.Join(";", parts), ow, oh);
        }

        // تثبیت (فقط پیش‌نمایشِ متحرک و خروجی: به فریم‌های پشتِ سرِ هم نیاز دارد)
        if (kind != RenderKind.Frame && r.Stabilize is { } st && ctx.TrfFile is { } trf)
        {
            var smoothing = (int)Math.Round(5 + st.Amount * 0.4);
            f.Add($"vidstabtransform=input={trf}:smoothing={smoothing}:optzoom=1:zoomspeed=0.2:interpol=bicubic");
            f.Add("unsharp=5:5:0.5:3:3:0.2");
        }
        // حذفِ بازه‌ها: هر تکه جدا (با زمانِ واقعیِ فریم‌ها ⇒ ویدیوی نرخ‌متغیرِ گوشی هم با صدا هم‌زمان می‌ماند)
        if (cutting && keep.Count > 0)
        {
            Flush("vc0");
            var labels = Enumerable.Range(0, keep.Count).Select(i => $"vk{i}").ToList();
            parts.Add(keep.Count == 1 ? $"[vc0]null[vk0]" : $"[vc0]split={keep.Count}{string.Concat(labels.Select(Label))}");
            for (int i = 0; i < keep.Count; i++)
                parts.Add($"[{labels[i]}]trim=start={F(keep[i].S, 3)}:end={F(keep[i].E, 3)},setpts=PTS-STARTPTS[vt{i}]");
            parts.Add(string.Concat(Enumerable.Range(0, keep.Count).Select(i => $"[vt{i}]")) + $"concat=n={keep.Count}:v=1:a=0[vcut]");
            cur = "vcut";
        }
        // سرعت
        if (kind != RenderKind.Frame && Math.Abs(r.Speed - 1) > 1e-6)
        {
            f.Add($"setpts=PTS/{F(r.Speed, 4)}");
            if (r.Time?.Smooth == true)
            {
                var fps = o.Fps > 0 ? o.Fps : m.Fps > 0 ? m.Fps : 30;
                f.Add($"minterpolate=fps={F(fps, 3)}:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1");
            }
        }
        // لنز: نمونه از شعاعِ بزرگ‌تر ⇒ صاف شدنِ خطِ بشکه‌ای؛ کمی بزرگ‌نمایی تا گوشه‌ها سیاه نشوند
        var dist = r.Get("distortion");
        if (dist != 0)
        {
            var k1 = dist / 100 * 0.25;
            f.Add($"lenscorrection=k1={F(k1)}:k2=0:i=bilinear");
            if (k1 > 0) f.Add($"scale=trunc(iw*{F(1 + k1)}/2)*2:trunc(ih*{F(1 + k1)}/2)*2,crop=trunc(iw/{F(1 + k1)}/2)*2:trunc(ih/{F(1 + k1)}/2)*2");
        }
        // چرخش (با بزرگ‌نماییِ پوشاننده)، برش، قرینه
        if (r.Crop is { } c)
        {
            if (c.Angle != 0)
            {
                var z = CoverZoom(w, h, c.Angle);
                f.Add($"scale=trunc(iw*{F(z)}/2)*2:trunc(ih*{F(z)}/2)*2,rotate={F(-c.Angle * Math.PI / 180, 6)}:ow=trunc(iw/{F(z)}/2)*2:oh=trunc(ih/{F(z)}/2)*2:bilinear=1");
            }
            if (c.HasRect)
            {
                f.Add($"crop=trunc(iw*{F(c.W, 5)}/2)*2:trunc(ih*{F(c.H, 5)}/2)*2:trunc(iw*{F(c.X, 5)}):trunc(ih*{F(c.Y, 5)})");
                w = Even(w * c.W); h = Even(h * c.H);
            }
            if (c.FlipH) f.Add("hflip");
            if (c.FlipV) f.Add("vflip");
        }
        // نویزگیری پیش از رنگ (کنتراستِ بیشتر نویز را هم بزرگ می‌کند)
        double dn = r.Get("denoise") / 100, dc = r.Get("denoiseColor") / 100;
        if (dn > 0 || dc > 0)
            f.Add($"hqdn3d=luma_spatial={F(dn * 6, 2)}:chroma_spatial={F(Math.Max(dc * 8, dn * 3), 2)}:luma_tmp={F(kind == RenderKind.Frame ? 0 : dn * 8, 2)}:chroma_tmp={F(kind == RenderKind.Frame ? 0 : Math.Max(dc * 10, dn * 4), 2)}");
        if (ctx.LutFile is { } lut) f.Add($"lut3d=file={lut}:interp=tetrahedral");
        // وضوح: کنتراستِ محلیِ درشت فقط روی روشنایی (شعاع به نسبتِ اندازه)
        var clarity = r.Get("clarity") / 100;
        if (clarity != 0)
        {
            var rad = Math.Clamp((int)Math.Round(13 * Math.Min(w, h) / 1080.0) | 1, 3, 23);
            f.Add($"unsharp=lx={rad}:ly={rad}:la={F(clarity * 1.2, 3)}:cx=3:cy=3:ca=0");
        }
        var sharpen = r.Get("sharpen") / 100;
        if (sharpen > 0) f.Add($"cas=strength={F(Math.Min(1, sharpen * 0.9), 3)}");
        var vig = r.Get("vignette") / 100;
        if (vig > 0) f.Add($"vignette=angle={F(vig * 1.1, 3)}:mode=forward");
        var grain = r.Get("grain") / 100;
        if (grain > 0) f.Add($"noise=c0s={F(grain * 30, 1)}:c0f=t+u");

        // قاب و اندازهٔ نهایی
        var (cw, ch, canvasW, canvasH) = Framing(r, w, h);
        int outW, outH;
        if (kind == RenderKind.Frame) { var fit = FitDims(canvasW, canvasH, ctx.MaxSide); (outW, outH) = fit; }
        else
        {
            var shortTarget = kind == RenderKind.Preview ? Math.Min(ctx.PreviewShort, Math.Min(canvasW, canvasH)) : o.Size > 0 ? o.Size : Math.Min(canvasW, canvasH);
            var sc = shortTarget / Math.Min(canvasW, canvasH);
            (outW, outH) = (Even(canvasW * sc), Even(canvasH * sc));
        }
        var frame = r.Frame;
        if (frame is not null && FrameSettings.Ratio(frame.Aspect) is { } a && frame.Fit == "blur")
        {
            Flush("vf0");
            var blur = Math.Max(8, Math.Min(outW, outH) / 25.0);
            parts.Add($"[vf0]split=2[fg0][bg0]");
            parts.Add($"[bg0]scale={outW}:{outH}:force_original_aspect_ratio=increase,crop={outW}:{outH},gblur=sigma={F(blur, 1)},eq=brightness=-0.06:saturation=0.85[bg1]");
            parts.Add($"[fg0]scale={outW}:{outH}:force_original_aspect_ratio=decrease:flags=lanczos,setsar=1[fg1]");
            parts.Add($"[bg1][fg1]overlay=(W-w)/2:(H-h)/2[vfr]");
            cur = "vfr";
        }
        else if (frame is not null && FrameSettings.Ratio(frame.Aspect) is { } a2 && frame.Fit == "black")
        {
            f.Add($"scale={outW}:{outH}:force_original_aspect_ratio=decrease:flags=lanczos,pad={outW}:{outH}:(ow-iw)/2:(oh-ih)/2:black");
        }
        else
        {
            if (frame is not null && FrameSettings.Ratio(frame.Aspect) is { } a3)
                f.Add($"crop={Even(cw)}:{Even(ch)}:trunc((iw-{Even(cw)})*{F(frame.FocusX, 3)}/2)*2:trunc((ih-{Even(ch)})*{F(frame.FocusY, 3)}/2)*2");
            if (Math.Abs(outW - canvasW) > 1 || Math.Abs(outH - canvasH) > 1 || kind != RenderKind.Export)
                f.Add($"scale={outW}:{outH}:flags={(kind == RenderKind.Export ? "lanczos" : "bilinear")}");
        }
        f.Add("setsar=1");
        if (kind != RenderKind.Frame && o.Fps > 0 && !(r.Time?.Smooth ?? false)) f.Add($"fps={F(o.Fps, 3)}");
        if (kind == RenderKind.Export && o.BroadcastSafe) f.Add("format=yuv420p,limiter=min=16:max=235:planes=1,limiter=min=16:max=240:planes=6");
        if (kind != RenderKind.Frame && r.Time is { } t)
        {
            var atStart = kind == RenderKind.Export || Math.Abs(ctx.PreviewStart - TrimRange(r, m).Start) < 0.05;
            var atEnd = kind == RenderKind.Export || ctx.PreviewStart + ctx.PreviewDuration >= TrimRange(r, m).End - 0.05;
            if (t.FadeIn > 0 && atStart) f.Add($"fade=t=in:st=0:d={F(Math.Min(t.FadeIn, outDur / 2), 3)}");
            if (t.FadeOut > 0 && atEnd) f.Add($"fade=t=out:st={F(Math.Max(0, outDur - t.FadeOut), 3)}:d={F(Math.Min(t.FadeOut, outDur / 2), 3)}");
        }
        if (o.Format == "gif" && kind == RenderKind.Export)
        {
            Flush("vg");
            parts.Add("[vg]split=2[ga][gb];[ga]palettegen=stats_mode=diff:max_colors=200[gp];[gb][gp]paletteuse=dither=bayer:bayer_scale=4[vout]");
            return (string.Join(";", parts), outW, outH);
        }
        f.Add(kind == RenderKind.Frame ? "format=yuvj420p" : "format=yuv420p");
        Flush("vout");
        return (string.Join(";", parts), outW, outH);
    }

    /// <summary>
    /// اندازهٔ بعد از قاب: crop ⇒ بزرگ‌ترین مستطیلِ آن نسبت درونِ تصویر؛ blur/black ⇒ بومی که کلِ تصویر در آن جا شود.
    /// </summary>
    public static (double CropW, double CropH, double CanvasW, double CanvasH) Framing(VideoRecipe r, double w, double h)
    {
        if (r.Frame is not { } fr || FrameSettings.Ratio(fr.Aspect) is not { } a) return (w, h, w, h);
        if (fr.Fit == "crop")
        {
            var cw = Math.Min(w, h * a); var ch = Math.Min(h, w / a);
            return (cw, ch, cw, ch);
        }
        var W = Math.Max(w, h * a); var H = Math.Max(h, w / a);
        return (w, h, W, H);
    }

    public static double CoverZoom(double w, double h, double angle)
    {
        var a = Math.Abs(angle) * Math.PI / 180;
        double cos = Math.Cos(a), sin = Math.Sin(a);
        return Math.Max((w * cos + h * sin) / w, (w * sin + h * cos) / h);
    }

    private static (int W, int H) FitDims(double w, double h, int maxSide)
    {
        var k = Math.Min(1, maxSide / Math.Max(w, h));
        return (Even(w * k), Even(h * k));
    }

    private static string FitBox(double w, double h, int maxSide, out int ow, out int oh)
    {
        (ow, oh) = FitDims(w, h, maxSide);
        return $"scale={ow}:{oh}:flags=bilinear";
    }

    // ───────────── صدا ─────────────

    private static string AudioChain(VideoRecipe r, RenderContext ctx, RenderKind kind, List<(double S, double E)> keep, bool cutting, double outDur, bool includeNormalize)
    {
        var parts = new List<string>();
        var f = new List<string>();
        string cur = "0:a";
        if (cutting && keep.Count > 0)
        {
            var labels = Enumerable.Range(0, keep.Count).Select(i => $"ak{i}").ToList();
            parts.Add(keep.Count == 1 ? "[0:a]anull[ak0]" : $"[0:a]asplit={keep.Count}{string.Concat(labels.Select(l => $"[{l}]"))}");
            for (int i = 0; i < keep.Count; i++)
                parts.Add($"[{labels[i]}]atrim=start={F(keep[i].S, 3)}:end={F(keep[i].E, 3)},asetpts=PTS-STARTPTS[at{i}]");
            parts.Add(string.Concat(Enumerable.Range(0, keep.Count).Select(i => $"[at{i}]")) + $"concat=n={keep.Count}:v=0:a=1[acut]");
            cur = "acut";
        }
        // سرعت بی تغییرِ زیر و بمی (atempo در هر قدم ۰٫۵ تا ۲)
        var sp = r.Speed;
        while (sp > 2.0001) { f.Add("atempo=2"); sp /= 2; }
        while (sp < 0.4999) { f.Add("atempo=0.5"); sp /= 0.5; }
        if (Math.Abs(sp - 1) > 1e-4) f.Add($"atempo={F(sp, 4)}");

        var rumble = r.Get("rumble") / 100;
        if (rumble > 0) f.Add($"highpass=f={F(20 + rumble * 140, 0)}:poles=2");
        if (r.Audio is { Hum: > 0 } au)
            foreach (var k in new[] { 1, 2, 3, 4 })
                f.Add($"bandreject=f={au.Hum * k}:width_type=q:width={F(k == 1 ? 12 : 16, 0)}");
        var declick = r.Get("declick") / 100;
        if (declick > 0) f.Add($"adeclick=t={F(10 - declick * 8, 2)}");
        var noise = r.Get("noise") / 100;
        if (noise > 0)
        {
            // afftdn باید کفِ نویزِ همین ضبط را بداند (سنجش + ۶ دسی‌بل)؛ ردیابیِ خودکارش (tn) روی نویزِ یکنواخت کم‌اثر است
            var nf = Math.Clamp((ctx.NoiseFloorDb is { } fl && double.IsFinite(fl) ? fl : -46) + 6, -80, -20);
            f.Add($"afftdn=nr={F(6 + noise * 34, 1)}:nf={F(nf, 1)}");
        }
        var deess = r.Get("deess") / 100;
        if (deess > 0) f.Add($"deesser=i={F(deess, 2)}:m=0.5:f=0.5:s=o");
        var bass = r.Get("bass"); var presence = r.Get("presence"); var air = r.Get("air");
        if (bass != 0) f.Add($"bass=g={F(bass, 1)}:f=120:w=0.7");
        if (presence != 0) f.Add($"equalizer=f=3000:t=q:w=1.1:g={F(presence, 1)}");
        if (air != 0) f.Add($"treble=g={F(air, 1)}:f=9000:w=0.7");
        var comp = r.Get("compress") / 100;
        if (comp > 0)
        {
            var thr = Math.Pow(10, (-14 - comp * 16) / 20);
            var ratio = 1.5 + comp * 4.5;
            var makeup = Math.Pow(10, comp * 6 / 20);
            f.Add($"acompressor=threshold={F(thr, 5)}:ratio={F(ratio, 2)}:attack=10:release=180:makeup={F(makeup, 3)}:knee=4");
        }
        var vol = r.Get("volume");
        if (vol != 0) f.Add($"volume={F(vol, 1)}dB");
        var norm = r.Audio?.Normalize ?? 0;
        if (includeNormalize && norm < 0)
        {
            if (ctx.Loudness is { } lm && kind == RenderKind.Export)
                f.Add($"loudnorm=I={F(norm, 1)}:TP=-1.5:LRA=11:measured_I={F(lm.I, 2)}:measured_TP={F(lm.TP, 2)}:measured_LRA={F(lm.LRA, 2)}:measured_thresh={F(lm.Thresh, 2)}:offset={F(lm.Offset, 2)}:linear=true");
            else f.Add($"loudnorm=I={F(norm, 1)}:TP=-1.5:LRA=11");
        }
        else if (includeNormalize && vol > 0) f.Add("alimiter=limit=0.891:level=false");
        if (includeNormalize && r.Time is { } t)
        {
            var atStart = kind == RenderKind.Export || Math.Abs(ctx.PreviewStart - TrimRange(r, ctx.Media).Start) < 0.05;
            var atEnd = kind == RenderKind.Export || ctx.PreviewStart + ctx.PreviewDuration >= TrimRange(r, ctx.Media).End - 0.05;
            if (t.FadeIn > 0 && atStart) f.Add($"afade=t=in:st=0:d={F(Math.Min(t.FadeIn, outDur / 2), 3)}");
            if (t.FadeOut > 0 && atEnd) f.Add($"afade=t=out:st={F(Math.Max(0, outDur - t.FadeOut), 3)}:d={F(Math.Min(t.FadeOut, outDur / 2), 3)}");
        }
        if (includeNormalize) f.Add("aresample=48000");
        parts.Add($"[{cur}]{(f.Count > 0 ? string.Join(",", f) : "anull")}[aout]");
        return string.Join(";", parts);
    }

    // ───────────── کدگذاری ─────────────

    private static IEnumerable<string> Encoder(OutputSettings o, bool video, bool audio, bool wasHdr)
    {
        var l = new List<string>();
        switch (o.Format)
        {
            case "mp3":
                l.AddRange(new[] { "-c:a", "libmp3lame", "-q:a", o.Quality == "small" ? "5" : "2" });
                return l;
            case "wav":
                l.AddRange(new[] { "-c:a", "pcm_s16le" });
                return l;
            case "gif":
                l.AddRange(new[] { "-loop", "0" });
                return l;
            case "webm":
                if (video) l.AddRange(new[] { "-c:v", "libvpx-vp9", "-b:v", "0", "-crf", o.Quality switch { "high" => "28", "small" => "40", _ => "33" },
                    "-row-mt", "1", "-deadline", "good", "-cpu-used", o.Quality == "high" ? "2" : "4" });
                if (audio) l.AddRange(new[] { "-c:a", "libopus", "-b:a", o.Quality == "small" ? "80k" : "128k" });
                break;
            default:
                if (video)
                {
                    if (o.Codec == "h265")
                        l.AddRange(new[] { "-c:v", "libx265", "-preset", o.Quality == "small" ? "fast" : "medium", "-crf", o.Quality switch { "high" => "20", "small" => "30", _ => "25" },
                            "-tag:v", "hvc1", "-x265-params", "log-level=error" });
                    else
                        l.AddRange(new[] { "-c:v", "libx264", "-preset", o.Quality == "small" ? "veryfast" : "medium", "-crf", o.Quality switch { "high" => "18", "small" => "27", _ => "21" },
                            "-profile:v", "high" });
                    l.AddRange(new[] { "-movflags", "+faststart" });
                }
                if (audio) l.AddRange(new[] { "-c:a", "aac", "-b:a", o.Quality switch { "high" => "192k", "small" => "96k", _ => "160k" } });
                break;
        }
        // بعد از تبدیلِ HDR، برچسبِ رنگِ استانداردِ SDR تا پخش‌کننده‌ها درست نشان دهند
        if (video && wasHdr) l.AddRange(new[] { "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709" });
        return l;
    }

    /// <summary>برای گزارش و آزمون: آرگومان‌ها با نقل‌قول، مثلِ خطِ فرمان.</summary>
    public static string ToCommandLine(IEnumerable<string> args)
    {
        var sb = new StringBuilder("ffmpeg");
        foreach (var a in args)
            sb.Append(' ').Append(a.Any(ch => ch is ' ' or ';' or '[' or '\'' or '"') ? "\"" + a.Replace("\"", "\\\"") + "\"" : a);
        return sb.ToString();
    }
}
