using System.Globalization;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace PersianAiKit.Video.Engine;

/// <summary>
/// مشخصاتِ یک فایلِ ویدیو از ffprobe. عرض و ارتفاع «نمایشی»اند (چرخشِ گوشی حساب شده — ffmpeg هنگامِ خواندن خودش می‌چرخاند).
/// </summary>
public sealed record MediaInfo
{
    public double Duration { get; init; }
    public bool HasVideo { get; init; }
    public int Width { get; init; }
    public int Height { get; init; }
    public double Fps { get; init; }
    public string VideoCodec { get; init; } = "";
    public string PixelFormat { get; init; } = "";
    /// <summary>smpte2084 (PQ) یا arib-std-b67 (HLG) ⇒ HDR (مثلاً آیفون).</summary>
    public string ColorTransfer { get; init; } = "";
    public string ColorPrimaries { get; init; } = "";
    public string FieldOrder { get; init; } = "";
    public int Rotation { get; init; }
    public bool HasAudio { get; init; }
    public string AudioCodec { get; init; } = "";
    public int SampleRate { get; init; }
    public int Channels { get; init; }
    public long BitRate { get; init; }
    public long Size { get; init; }
    public string Container { get; init; } = "";

    [JsonIgnore] public bool Hdr => ColorTransfer is "smpte2084" or "arib-std-b67";
    [JsonIgnore] public bool Interlaced => FieldOrder is "tt" or "bb" or "tb" or "bt";
    [JsonIgnore] public bool Portrait => Height > Width;

    public string Describe()
    {
        var ci = CultureInfo.InvariantCulture;
        var parts = new List<string> { $"duration {Duration.ToString("0.0", ci)}s" };
        if (HasVideo) parts.Add($"video {Width}x{Height} {Fps.ToString("0.##", ci)}fps {VideoCodec}{(Hdr ? " HDR(" + ColorTransfer + ")" : "")}{(Interlaced ? " interlaced" : "")}");
        parts.Add(HasAudio ? $"audio {AudioCodec} {SampleRate}Hz {Channels}ch" : "no audio");
        return string.Join(", ", parts);
    }

    public static async Task<MediaInfo> ProbeAsync(FFmpegTool ff, string file, CancellationToken ct = default)
    {
        var r = await ff.FFprobeAsync(new[] { "-v", "error", "-print_format", "json", "-show_format", "-show_streams", file }, ct);
        if (!r.Ok || r.StdOut.Length == 0) throw new InvalidDataException("این فایل ویدیو یا صدا نیست یا خراب است: " + r.ErrorTail);
        using var doc = JsonDocument.Parse(r.StdOut);
        var root = doc.RootElement;
        JsonElement? v = null, a = null;
        if (root.TryGetProperty("streams", out var streams))
            foreach (var s in streams.EnumerateArray())
            {
                var type = Str(s, "codec_type");
                // کاورِ آهنگ (عکسِ ثابت) ویدیو حساب نمی‌شود
                var cover = s.TryGetProperty("disposition", out var disp) && disp.TryGetProperty("attached_pic", out var ap) && ap.GetInt32() == 1;
                if (type == "video" && v is null && !cover) v = s;
                if (type == "audio" && a is null) a = s;
            }
        var fmt = root.TryGetProperty("format", out var f) ? f : default;
        double duration = Num(fmt, "duration");
        if (duration <= 0 && v is { } vv) duration = Num(vv, "duration");
        if (duration <= 0 && a is { } aa) duration = Num(aa, "duration");
        if (v is null && a is null) throw new InvalidDataException("در این فایل نه تصویر هست نه صدا.");

        int w = 0, h = 0, rot = 0;
        double fps = 0;
        if (v is { } vs)
        {
            w = (int)Num(vs, "width"); h = (int)Num(vs, "height");
            fps = Rate(Str(vs, "avg_frame_rate"));
            if (fps is <= 0 or > 240) fps = Rate(Str(vs, "r_frame_rate"));
            if (vs.TryGetProperty("side_data_list", out var sdl))
                foreach (var sd in sdl.EnumerateArray())
                    if (sd.TryGetProperty("rotation", out var ro) && ro.ValueKind == JsonValueKind.Number) rot = (int)ro.GetDouble();
            if (rot == 0 && vs.TryGetProperty("tags", out var tags) && tags.TryGetProperty("rotate", out var rt) &&
                int.TryParse(rt.GetString(), out var rv)) rot = rv;
            rot = ((rot % 360) + 360) % 360;
            if (rot is 90 or 270) (w, h) = (h, w);
        }
        return new MediaInfo
        {
            Duration = Math.Round(duration, 3),
            HasVideo = v is not null, Width = w, Height = h, Fps = Math.Round(fps, 3),
            VideoCodec = v is { } v1 ? Str(v1, "codec_name") : "",
            PixelFormat = v is { } v2 ? Str(v2, "pix_fmt") : "",
            ColorTransfer = v is { } v3 ? Str(v3, "color_transfer") : "",
            ColorPrimaries = v is { } v4 ? Str(v4, "color_primaries") : "",
            FieldOrder = v is { } v5 ? Str(v5, "field_order") : "",
            Rotation = rot,
            HasAudio = a is not null,
            AudioCodec = a is { } a1 ? Str(a1, "codec_name") : "",
            SampleRate = a is { } a2 ? (int)Num(a2, "sample_rate") : 0,
            Channels = a is { } a3 ? (int)Num(a3, "channels") : 0,
            BitRate = (long)Num(fmt, "bit_rate"),
            Size = (long)Num(fmt, "size"),
            Container = Str(fmt, "format_name"),
        };
    }

    private static string Str(JsonElement e, string name) =>
        e.ValueKind == JsonValueKind.Object && e.TryGetProperty(name, out var p) ? p.ValueKind == JsonValueKind.String ? p.GetString() ?? "" : p.ToString() : "";

    private static double Num(JsonElement e, string name)
    {
        var s = Str(e, name);
        return double.TryParse(s, NumberStyles.Float, CultureInfo.InvariantCulture, out var d) ? d : 0;
    }

    private static double Rate(string r)
    {
        var p = r.Split('/');
        if (p.Length == 2 && double.TryParse(p[0], NumberStyles.Float, CultureInfo.InvariantCulture, out var n) &&
            double.TryParse(p[1], NumberStyles.Float, CultureInfo.InvariantCulture, out var d) && d > 0) return n / d;
        return double.TryParse(r, NumberStyles.Float, CultureInfo.InvariantCulture, out var x) ? x : 0;
    }
}
