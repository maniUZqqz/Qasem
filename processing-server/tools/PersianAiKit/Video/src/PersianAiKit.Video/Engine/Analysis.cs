using System.Globalization;
using System.Text.RegularExpressions;

namespace PersianAiKit.Video.Engine;

/// <summary>اندازه‌گیری‌های یک ویدیو — برای تنظیمِ خودکار و برای هوشِ مصنوعی (متنِ کوتاه به‌جای فیلم ⇒ ارزان).</summary>
public sealed record VideoStats
{
    public int Frames { get; init; }
    /// <summary>روشنایی (۰ تا ۱) روی چند فریمِ نمونه.</summary>
    public double Mean { get; init; }
    public double P1 { get; init; }
    public double P5 { get; init; }
    public double P50 { get; init; }
    public double P95 { get; init; }
    public double P99 { get; init; }
    public double ClipShadows { get; init; }
    public double ClipHighlights { get; init; }
    public double Contrast { get; init; }
    public double Saturation { get; init; }
    /// <summary>دما و ته‌رنگی که رنگ‌های خنثی را خنثی می‌کند.</summary>
    public double CastTemperature { get; init; }
    public double CastTint { get; init; }
    public double NeutralShare { get; init; }
    /// <summary>انحرافِ معیارِ نویز (مقیاسِ ۰ تا ۲۵۵) روی فریمِ ۴۸۰ پیکسلی.</summary>
    public double Noise { get; init; }
    /// <summary>روشنایی میانِ فریم‌ها چقدر عوض می‌شود (صحنه‌های متفاوت).</summary>
    public double FrameVariation { get; init; }

    // صدا
    public bool HasAudio { get; init; }
    /// <summary>بلندیِ یکپارچه (LUFS)، محدودهٔ بلندی (LU)، قلهٔ واقعی (dBTP).</summary>
    public double Loudness { get; init; } = double.NaN;
    public double LoudnessRange { get; init; } = double.NaN;
    public double TruePeak { get; init; } = double.NaN;
    /// <summary>کفِ نویز (dBFS، آرام‌ترین لحظه‌ها).</summary>
    public double NoiseFloor { get; init; } = double.NaN;
    /// <summary>نویز یکنواخت است (هیس، کولر) ⇒ نویزگیری کمکش می‌کند.</summary>
    public bool NoiseSteady { get; init; }
    /// <summary>وزوزِ برق (۵۰ یا ۶۰ هرتز) پیدا شد؟ ۰ ⇒ نه.</summary>
    public int Hum { get; init; }
    public double HumStrength { get; init; }
    /// <summary>سهمِ زمانِ ساکت (درصد) و بازه‌های سکوت (ثانیه).</summary>
    public double SilenceShare { get; init; }
    public List<TimeRange> Silences { get; init; } = new();

    /// <summary>خلاصهٔ انگلیسی برای مدلِ زبانی (کوتاه = ارزان).</summary>
    public string Describe(MediaInfo m)
    {
        var ci = CultureInfo.InvariantCulture;
        string F(double v, string f = "0.000") => double.IsFinite(v) ? v.ToString(f, ci) : "n/a";
        var l = new List<string> { m.Describe() };
        if (Frames > 0)
        {
            l.Add($"luminance over {Frames} sample frames (0..1): mean {F(Mean)}, p1 {F(P1)}, p5 {F(P5)}, median {F(P50)}, p95 {F(P95)}, p99 {F(P99)}, std {F(Contrast)}");
            l.Add($"clipped: shadows {F(ClipShadows, "0.0")}%, highlights {F(ClipHighlights, "0.0")}%; mean saturation {F(Saturation)}; frame-to-frame brightness variation {F(FrameVariation)}");
            l.Add($"white-balance fix that neutralizes grays: temperature {F(CastTemperature, "0")}, tint {F(CastTint, "0")} (neutral pixels {F(NeutralShare, "0.0")}%); noise sigma {F(Noise, "0.0")}/255");
            if (m.Hdr) l.Add("source is HDR: it is tone-mapped to SDR automatically.");
        }
        if (HasAudio)
            l.Add($"audio: integrated loudness {F(Loudness, "0.0")} LUFS, loudness range {F(LoudnessRange, "0.0")} LU, true peak {F(TruePeak, "0.0")} dBTP, noise floor {F(NoiseFloor, "0.0")} dBFS{(NoiseSteady ? " (steady hiss/hum)" : "")}, " +
                  $"mains hum {(Hum > 0 ? Hum + "Hz (" + F(HumStrength, "0.0") + "x)" : "none")}, silence {F(SilenceShare, "0")}% of time in {Silences.Count} pauses");
        return string.Join("\n", l);
    }
}

/// <summary>نتیجهٔ تنظیمِ خودکار: نسخه + توضیحِ فارسیِ هر کار.</summary>
public sealed record AutoResult(VideoRecipe Recipe, IReadOnlyList<string> Notes);

public static partial class Analysis
{
    private const int SampleW = 480;

    public static async Task<VideoStats> MeasureAsync(FFmpegTool ff, string source, MediaInfo m, int frames = 6, CancellationToken ct = default)
    {
        var s = new VideoStats { HasAudio = m.HasAudio };
        if (m.HasVideo && m.Width > 0) s = MeasureFrames(await SampleFramesAsync(ff, source, m, frames, SampleW, ct), s);
        if (m.HasAudio) s = await MeasureAudioAsync(ff, source, m, s, ct);
        return s;
    }

    /// <summary>چند فریمِ پخش در طولِ فیلم، RGBِ خام با عرضِ <paramref name="width"/>.</summary>
    public static async Task<List<(byte[] Rgb, int W, int H, double T)>> SampleFramesAsync(FFmpegTool ff, string source, MediaInfo m, int count, int width, CancellationToken ct = default)
    {
        int w = Math.Min(width, m.Width) / 2 * 2, h = Math.Max(2, (int)Math.Round(w * (double)m.Height / m.Width / 2) * 2);
        var list = new List<(byte[], int, int, double)>();
        for (int i = 0; i < count; i++)
        {
            var t = m.Duration * (i + 0.5) / count;
            var vf = $"scale={w}:{h}:flags=area";
            if (m.Hdr) vf = "zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,tonemap=tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv,format=yuv420p," + vf;
            var r = await ff.FFmpegAsync(new[] { "-ss", FFmpegTool.F(t, 3), "-i", source, "-frames:v", "1", "-vf", vf, "-f", "rawvideo", "-pix_fmt", "rgb24", "-" }, ct, captureStdOut: true);
            if (r.Ok && r.StdOut.Length == w * h * 3) list.Add((r.StdOut, w, h, t));
        }
        return list;
    }

    private static VideoStats MeasureFrames(List<(byte[] Rgb, int W, int H, double T)> frames, VideoStats s)
    {
        if (frames.Count == 0) return s;
        var hist = new long[1024];
        long n = 0, clipS = 0, clipH = 0, mid = 0, neutral = 0;
        double satSum = 0, sum = 0, sum2 = 0, wr = 0, wg = 0, wb = 0, nr = 0, ng = 0, nb = 0;
        var means = new List<double>();
        var noise = new List<double>();
        foreach (var (rgb, w, h, _) in frames)
        {
            double fsum = 0;
            for (int i = 0; i < w * h; i++)
            {
                float r = rgb[i * 3] / 255f, g = rgb[i * 3 + 1] / 255f, b = rgb[i * 3 + 2] / 255f;
                var l = 0.2126f * r + 0.7152f * g + 0.0722f * b;
                hist[Math.Clamp((int)(l * 1023), 0, 1023)]++;
                sum += l; sum2 += l * l; fsum += l; n++;
                if (l < 0.01f) clipS++;
                var max = Math.Max(r, Math.Max(g, b)); var min = Math.Min(r, Math.Min(g, b));
                if (max > 0.99f) clipH++;
                satSum += max > 1e-4f ? (max - min) / max : 0;
                if (l > 0.12f && l < 0.92f && max < 0.98f)
                {
                    mid++;
                    wr += MathF.Pow(r, 2.2f); wg += MathF.Pow(g, 2.2f); wb += MathF.Pow(b, 2.2f);
                }
            }
            means.Add(fsum / (w * h));
            noise.Add(NoiseSigma(rgb, w, h));
        }
        // ته‌رنگ: خاکستری‌هایی که بعد از برداشتنِ ته‌رنگِ کلی خاکستری‌اند (مثلِ ویرایشگرِ عکس)
        if (mid > 0)
        {
            float kr = (float)(wg / Math.Max(wr, 1e-9)), kb = (float)(wg / Math.Max(wb, 1e-9));
            foreach (var (rgb, w, h, _) in frames)
                for (int i = 0; i < w * h; i++)
                {
                    float r = rgb[i * 3] / 255f, g = rgb[i * 3 + 1] / 255f, b = rgb[i * 3 + 2] / 255f;
                    var l = 0.2126f * r + 0.7152f * g + 0.0722f * b;
                    if (l <= 0.12f || l >= 0.92f) continue;
                    var amax = Math.Max(r, Math.Max(g, b)); var amin = Math.Min(r, Math.Min(g, b));
                    if (amax > 1e-4f && (amax - amin) / amax > 0.5f) continue;
                    float lr = MathF.Pow(r, 2.2f), lg = MathF.Pow(g, 2.2f), lb = MathF.Pow(b, 2.2f);
                    float cr = lr * kr, cb = lb * kb;
                    var mx = Math.Max(cr, Math.Max(lg, cb)); var mn = Math.Min(cr, Math.Min(lg, cb));
                    if (mx > 1e-5f && (mx - mn) / mx < 0.2f) { neutral++; nr += lr; ng += lg; nb += lb; }
                }
        }
        double castT = 0, castTi = 0;
        if (neutral > n * 0.02) (castT, castTi) = Neutralize(nr / neutral, ng / neutral, nb / neutral);
        else if (mid > n * 0.2) { (castT, castTi) = Neutralize(wr / mid, wg / mid, wb / mid); castT *= 0.5; castTi *= 0.5; }

        double P(double q)
        {
            long target = (long)(q / 100 * n), acc = 0;
            for (int i = 0; i < 1024; i++) { acc += hist[i]; if (acc >= target) return i / 1023.0; }
            return 1;
        }
        var mean = sum / n;
        var avgMean = means.Average();
        return s with
        {
            Frames = frames.Count, Mean = mean, P1 = P(1), P5 = P(5), P50 = P(50), P95 = P(95), P99 = P(99),
            Contrast = Math.Sqrt(Math.Max(0, sum2 / n - mean * mean)),
            ClipShadows = clipS * 100.0 / n, ClipHighlights = clipH * 100.0 / n, Saturation = satSum / n,
            CastTemperature = Math.Clamp(castT, -100, 100), CastTint = Math.Clamp(castTi, -100, 100), NeutralShare = neutral * 100.0 / n,
            Noise = noise.OrderBy(x => x).ElementAt(noise.Count / 2),
            FrameVariation = Math.Sqrt(means.Sum(x => (x - avgMean) * (x - avgMean)) / means.Count),
        };
    }

    /// <summary>دما و ته‌رنگی که یک خاکستری (میانگینِ خطیِ R,G,B) را خنثی می‌کند (همان رابطهٔ LUT).</summary>
    public static (double Temperature, double Tint) Neutralize(double r, double g, double b)
    {
        r = Math.Max(r, 1e-6); g = Math.Max(g, 1e-6); b = Math.Max(b, 1e-6);
        return (Math.Log(b / r) / 1.2 * 100, Math.Log(g / Math.Sqrt(r * b)) / 0.375 * 100);
    }

    /// <summary>نویز به روشِ Immerkær فقط روی جاهای صاف (یک‌سومِ کم‌لبه‌ترِ تصویر).</summary>
    private static double NoiseSigma(byte[] rgb, int w, int h)
    {
        var y = new float[w * h];
        for (int i = 0; i < w * h; i++) y[i] = 0.2126f * rgb[i * 3] + 0.7152f * rgb[i * 3 + 1] + 0.0722f * rgb[i * 3 + 2];
        var vals = new List<(float Grad, float Lap)>();
        for (int r = 1; r < h - 1; r++)
            for (int x = 1; x < w - 1; x++)
            {
                int i = r * w + x;
                float lap = y[i - w - 1] - 2 * y[i - w] + y[i - w + 1] - 2 * y[i - 1] + 4 * y[i] - 2 * y[i + 1] + y[i + w - 1] - 2 * y[i + w] + y[i + w + 1];
                float gx = y[i + 1] - y[i - 1], gy = y[i + w] - y[i - w];
                vals.Add((MathF.Abs(gx) + MathF.Abs(gy), MathF.Abs(lap)));
            }
        if (vals.Count == 0) return 0;
        var flat = vals.OrderBy(v => v.Grad).Take(vals.Count / 3).ToList();
        return Math.Sqrt(Math.PI / 2) / 6 * flat.Average(v => v.Lap);
    }

    // ───────────── صدا ─────────────

    [GeneratedRegex(@"silence_start:\s*(-?[\d.]+)")] private static partial Regex SilenceStart();
    [GeneratedRegex(@"silence_end:\s*([\d.]+)")] private static partial Regex SilenceEnd();

    /// <summary>
    /// یک بار خواندنِ کلِ صدا: سکوت‌ها (silencedetect) و بلندی (loudnorm)؛
    /// + ۳۰ ثانیهٔ اول به‌صورتِ نمونهٔ خام: کفِ نویز (آرام‌ترین پنجره‌های ۵۰ میلی‌ثانیه‌ای) و وزوزِ برق (گورتزل).
    /// </summary>
    public static async Task<VideoStats> MeasureAudioAsync(FFmpegTool ff, string source, MediaInfo m, VideoStats s, CancellationToken ct = default,
        double silenceDb = -38, double minSilence = 0.5)
    {
        var af = $"silencedetect=n={FFmpegTool.F(silenceDb, 1)}dB:d={FFmpegTool.F(minSilence, 2)},loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json";
        var r = await ff.FFmpegAsync(new[] { "-i", source, "-vn", "-sn", "-af", af, "-f", "null", "-" }, ct);
        var err = r.StdErr;
        var lm = LoudnessMeasure.Parse(err);
        var silences = ParseSilences(err, m.Duration);
        var pcm = await PcmAsync(ff, source, PcmRate, 30, ct);
        var (floor, steady) = NoiseFloor(pcm, PcmRate);
        var (hum, strength) = DetectHum(pcm, PcmRate);
        return s with
        {
            Loudness = lm?.I ?? double.NaN, LoudnessRange = lm?.LRA ?? double.NaN, TruePeak = lm?.TP ?? double.NaN,
            NoiseFloor = floor, NoiseSteady = steady, Hum = hum, HumStrength = strength,
            Silences = silences,
            SilenceShare = m.Duration > 0 ? silences.Sum(x => x.End - x.Start) / m.Duration * 100 : 0,
        };
    }

    private const int PcmRate = 16000;

    /// <summary>صدای تک‌کانالهٔ خام (float) از ابتدای فایل.</summary>
    public static async Task<float[]> PcmAsync(FFmpegTool ff, string source, int sampleRate, double seconds, CancellationToken ct = default)
    {
        var r = await ff.FFmpegAsync(new[] { "-t", FFmpegTool.F(seconds, 1), "-i", source, "-vn", "-ac", "1", "-ar", sampleRate.ToString(CultureInfo.InvariantCulture), "-f", "f32le", "-" },
            ct, captureStdOut: true);
        if (!r.Ok) return Array.Empty<float>();
        var x = new float[r.StdOut.Length / 4];
        Buffer.BlockCopy(r.StdOut, 0, x, 0, x.Length * 4);
        return x;
    }

    /// <summary>
    /// کفِ نویز = دهکِ پایینِ RMSِ پنجره‌های ۵۰ میلی‌ثانیه‌ای (dBFS) — در گفتار همان نویزِ لای کلمه‌هاست.
    /// «ثابت» اگر دهک و سی‌امین صدک نزدیک باشند (نویزِ یکنواخت مثلِ هیس و کولر، نه بخشِ آرامِ موسیقی).
    /// </summary>
    public static (double Db, bool Steady) NoiseFloor(float[] x, int sr)
    {
        int win = sr / 20;
        var levels = new List<double>();
        for (int start = 0; start + win <= x.Length; start += win)
        {
            double e = 0;
            for (int i = start; i < start + win; i++) e += x[i] * x[i];
            levels.Add(10 * Math.Log10(Math.Max(e / win, 1e-12)));
        }
        if (levels.Count < 10) return (double.NaN, false);
        levels.Sort();
        double p10 = levels[levels.Count / 10], p30 = levels[levels.Count * 3 / 10];
        return (Math.Round(Math.Max(p10, -120), 1), p30 - p10 < 6 && p10 > -100);
    }

    /// <summary>
    /// وزوزِ برق: توانِ ۵۰/۱۰۰/۱۵۰ (یا ۶۰/۱۲۰/۱۸۰) هرتز در برابرِ همسایه‌هایش، در پنجره‌های یک‌ثانیه‌ای؛ میانه ⇒ مقاوم در برابرِ گفتار و موسیقی.
    /// </summary>
    public static (int Hz, double Strength) DetectHum(float[] x, int sr)
    {
        if (x.Length < sr * 2) return (0, 0);
        var hann = new double[sr];
        for (int i = 0; i < sr; i++) hann[i] = 0.5 - 0.5 * Math.Cos(2 * Math.PI * i / (sr - 1));
        double Score(int baseHz)
        {
            var ratios = new List<double>();
            for (int start = 0; start + sr <= x.Length; start += sr)
            {
                double peak = 0, side = 0;
                foreach (var k in new[] { 1, 2, 3 })
                {
                    double f = baseHz * k;
                    peak += Goertzel(x, start, hann, f, sr);
                    side += (Goertzel(x, start, hann, f - 8, sr) + Goertzel(x, start, hann, f + 8, sr)) / 2;
                }
                if (peak > 1e-9) ratios.Add(peak / Math.Max(side, 1e-12));
            }
            if (ratios.Count == 0) return 0;
            ratios.Sort();
            return Math.Min(999, ratios[ratios.Count / 2]);
        }
        double s50 = Score(50), s60 = Score(60);
        var best = s50 >= s60 ? (50, s50) : (60, s60);
        return best.Item2 > 6 ? (best.Item1, Math.Round(best.Item2, 1)) : (0, Math.Round(Math.Max(s50, s60), 1));
    }

    private static double Goertzel(float[] x, int start, double[] window, double freq, int sr)
    {
        var w = 2 * Math.PI * freq / sr;
        double c = 2 * Math.Cos(w), s1 = 0, s2 = 0;
        for (int i = 0; i < window.Length; i++)
        {
            var s0 = x[start + i] * window[i] + c * s1 - s2;   // پنجرهٔ هان تا نشتِ طیف کم شود
            s2 = s1; s1 = s0;
        }
        return s1 * s1 + s2 * s2 - c * s1 * s2;
    }

    public static List<TimeRange> ParseSilences(string stderr, double duration)
    {
        var list = new List<TimeRange>();
        double? start = null;
        foreach (var line in stderr.Split('\n'))
        {
            var a = SilenceStart().Match(line);
            if (a.Success) { start = Math.Max(0, double.Parse(a.Groups[1].Value, CultureInfo.InvariantCulture)); continue; }
            var b = SilenceEnd().Match(line);
            if (b.Success && start is { } st)
            {
                list.Add(new TimeRange { Start = Math.Round(st, 3), End = Math.Round(double.Parse(b.Groups[1].Value, CultureInfo.InvariantCulture), 3) });
                start = null;
            }
        }
        if (start is { } open && duration > open + 0.05) list.Add(new TimeRange { Start = Math.Round(open, 3), End = Math.Round(duration, 3) });
        return list;
    }

    // ───────────── خودکار ─────────────

    /// <summary>تنظیمِ خودکارِ رایگان و بی‌اینترنت (قاعده‌ای، محتاط): تصویر مثلِ ویرایشگرِ عکس، صدا مثلِ Essential Sound.</summary>
    public static AutoResult Auto(VideoStats s, MediaInfo m)
    {
        var r = new VideoRecipe();
        var notes = new List<string>();
        void Set(string k, double v) { v = Math.Round(ToolCatalog.Clamp(k, v), 2); if (Math.Abs(v - ToolCatalog.Default(k)) > 0.01) r.Adjust[k] = v; }

        if (s.Frames > 0)
        {
            if (s.NeutralShare > 1 && (Math.Abs(s.CastTemperature) > 6 || Math.Abs(s.CastTint) > 6))
            {
                double k = s.NeutralShare > 5 ? 0.85 : 0.5, lim = s.NeutralShare > 5 ? 70 : 35;
                Set("temperature", Math.Clamp(s.CastTemperature * k, -lim, lim));
                Set("tint", Math.Clamp(s.CastTint * k, -lim, lim));
                notes.Add($"ته‌رنگ گرفته شد (دما {r.Get("temperature"):0}، ته‌رنگ {r.Get("tint"):0}).");
            }
            // ویدیوی شب یا صحنهٔ تیره ممکن است عمدی باشد ⇒ نصفِ فاصله تا میانهٔ معمول
            var ev = Math.Clamp(2.2 * Math.Log2(0.45 / Math.Max(0.02, s.P50)) * 0.5, -1, 1);
            if (Math.Abs(ev) >= 0.15) { Set("exposure", ev); notes.Add(ev > 0 ? $"تیره بود: نوردهی +{ev:0.0#}." : $"روشن بود: نوردهی {ev:0.0#}."); }
            else ev = 0;
            var k2 = Math.Pow(2, ev / 2.2);
            double p1 = Math.Min(1, s.P1 * k2), p99 = Math.Min(1, s.P99 * k2);
            if (p1 > 0.06) { Set("blacks", -Math.Clamp((p1 - 0.03) / 0.12 * 100, 0, 40)); notes.Add("سیاه‌ها عمیق‌تر (تصویر کدر بود)."); }
            if (p99 < 0.9) { Set("whites", Math.Clamp((0.96 - p99) / 0.12 * 70, 0, 35)); notes.Add("سفیدها روشن‌تر."); }
            if (s.ClipHighlights > 1) { Set("highlights", -Math.Clamp(10 + s.ClipHighlights * 3, 0, 50)); notes.Add("جزئیاتِ بخش‌های سوخته برگردانده شد."); }
            if (s.P5 < 0.05 && s.Mean < 0.35) { Set("shadows", Math.Clamp((0.1 - s.P5) * 300, 0, 35)); notes.Add("سایه‌ها باز شد."); }
            if (s.Contrast < 0.15) { Set("contrast", Math.Clamp((0.19 - s.Contrast) * 220, 0, 20)); notes.Add("کنتراست کمی بیشتر."); }
            if (s.Saturation < 0.22) { Set("vibrance", Math.Clamp((0.3 - s.Saturation) * 110, 0, 25)); notes.Add("رنگ‌ها کمی زنده‌تر."); }
            if (s.Noise > 3)
            {
                Set("denoise", Math.Clamp((s.Noise - 2) * 10, 0, 50));
                Set("denoiseColor", 25);
                notes.Add($"نویزِ تصویر گرفته شد (نویزِ سنجیده {s.Noise:0.0}).");
            }
            else { Set("sharpen", 20); notes.Add("شارپِ ملایم."); }
        }
        if (s.HasAudio && double.IsFinite(s.Loudness))
        {
            var audio = new AudioSettings { Normalize = -14 };
            notes.Add($"بلندیِ صدا {s.Loudness:0} LUFS بود ⇒ هم‌سطح با ‎−۱۴ (اینستاگرام و یوتیوب).");
            // فقط نویزِ یکنواخت (هیس، کولر)؛ بخشِ آرامِ موسیقی نویز نیست
            if (double.IsFinite(s.NoiseFloor) && s.NoiseSteady && s.NoiseFloor > -60 && s.NoiseFloor < -12)
            {
                Set("noise", Math.Clamp((s.NoiseFloor + 64) * 2.5, 15, 60));
                notes.Add($"نویزِ پس‌زمینهٔ صدا کم شد (کفِ نویز {s.NoiseFloor:0} dB).");
            }
            if (s.Hum > 0) { audio.Hum = s.Hum; notes.Add($"وزوزِ برقِ {s.Hum} هرتز حذف شد."); }
            Set("rumble", 25);
            if (double.IsFinite(s.LoudnessRange) && s.LoudnessRange > 12) { Set("compress", 30); notes.Add("فاصلهٔ آرام و بلند زیاد بود ⇒ کمی یکدست شد."); }
            r.Audio = audio;
        }
        return new AutoResult(r.Normalized(), notes);
    }

    /// <summary>بازه‌های سکوت ⇒ بازه‌هایی برای حذف (مکث‌ها)، با کمی حاشیه تا جمله‌ها بریده نشوند.</summary>
    public static List<TimeRange> PausesToCuts(IEnumerable<TimeRange> silences, double keepPadding = 0.15, double minPause = 0.6)
    {
        var cuts = new List<TimeRange>();
        foreach (var s in silences)
        {
            var a = s.Start + keepPadding; var b = s.End - keepPadding;
            if (b - a >= minPause - 2 * keepPadding && b > a) cuts.Add(new TimeRange { Start = Math.Round(a, 3), End = Math.Round(b, 3) });
        }
        return TimeRange.Merge(cuts);
    }
}
