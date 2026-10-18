// آزمونِ نصبِ ویرایشگرِ ویدیو — روی همین ماشین، سبک (کلیپ‌های ساختگیِ ۱ تا ۶ ثانیه‌ای، ۳۲۰ پیکسل):
//   dotnet run -c Release                   همهٔ ابزارها روی ویدیو و صدای ساختگی با جوابِ معلوم + کتابخانه + خروجی‌ها + هوشِ مصنوعیِ ساختگی
//   dotnet run -c Release -- --video D:\a.mp4   + سنجش و تنظیمِ خودکار روی ویدیوی خودتان (فقط ۱۰ ثانیهٔ اول خروجی گرفته می‌شود)
//   dotnet run -c Release -- --write-docs   FEATURES.md را از روی فهرستِ ابزارها دوباره می‌سازد
//   dotnet run -c Release -- --prompt       متنِ ثابتی که برای هوشِ مصنوعی فرستاده می‌شود
using System.Diagnostics;
using System.Globalization;
using System.Net;
using System.Text;
using PersianAiKit.Video;
using PersianAiKit.Video.Ai;
using PersianAiKit.Video.Engine;

Console.OutputEncoding = Encoding.UTF8;
string? Arg(string name) { var i = Array.IndexOf(args, name); return i >= 0 && i + 1 < args.Length ? args[i + 1] : null; }

var root = FindRoot();
if (args.Contains("--write-docs"))
{
    var f = Path.Combine(root, "FEATURES.md");
    File.WriteAllText(f, FeatureDoc.Build(), new UTF8Encoding(false));
    Console.WriteLine("نوشته شد: " + f);
    return 0;
}
if (args.Contains("--prompt"))
{
    var sp = VisionAgent.SystemPrompt();
    Console.WriteLine(sp);
    Console.WriteLine($"— {sp.Length} نویسه، حدودِ {sp.Length / 4} توکن");
    return 0;
}

var outDir = Arg("--out") ?? Path.Combine(root, "data", "selftest");
var srcDir = Path.Combine(outDir, "src");
Directory.CreateDirectory(srcDir);
var ff = FFmpegTool.Find(Arg("--ffmpeg"));
var fails = 0;
void Check(bool ok, string what)
{
    Console.ForegroundColor = ok ? ConsoleColor.Green : ConsoleColor.Red;
    Console.Write(ok ? "  ✓ " : "  ✗ ");
    Console.ResetColor();
    Console.WriteLine(what);
    if (!ok) fails++;
}
void Section(string t) { Console.ForegroundColor = ConsoleColor.Cyan; Console.WriteLine("\n■ " + t); Console.ResetColor(); }
var ci = CultureInfo.InvariantCulture;

// ───────────── ۱. فهرستِ ابزارها و نسخه ─────────────
Section("۱. فهرستِ ابزارها و «نسخهٔ ویرایش»");
var keys = ToolCatalog.Params.Select(p => p.Key).ToList();
Check(keys.Distinct(StringComparer.OrdinalIgnoreCase).Count() == keys.Count, $"{keys.Count} لغزنده، کلیدِ تکراری ندارد");
Check(ToolCatalog.Params.All(p => p.Default >= p.Min && p.Default <= p.Max && ToolCatalog.Groups.Any(g => g.Key == p.Group)), "پیش‌فرضِ همه در بازه و گروه‌ها معلوم");
var raw = VideoRecipe.Parse("""{ "adjust": { "exposure": 9, "noise": "40", "nope": 1 }, "trim": { "start": -3, "end": 2 }, "cuts": [{"start":3,"end":2},{"start":2.5,"end":4}], "time": { "speed": 10 }, "frame": { "aspect": "9:16", "fit": "wat" }, "audio": { "normalize": 5, "hum": 55 }, "output": { "format": "avi", "size": 5000 } }""");
Check(raw.Get("exposure") == 3 && raw.Get("noise") == 40 && !raw.Adjust.ContainsKey("nope") && raw.Trim!.Start == 0 && raw.Cuts!.Count == 1 && raw.Cuts[0].Start == 2 &&
      raw.Time!.Speed == 4 && raw.Frame!.Fit == "crop" && raw.Audio is null && raw.Output!.Format == "mp4" && raw.Output.Size == 2160,
    "ورودیِ خراب امن می‌شود: " + raw.ToJson());
Check(VideoRecipe.Parse(raw.ToJson()).ToJson() == raw.ToJson(), "JSON رفت‌وبرگشت یکسان است");
Check(Presets.All.All(p => p.Recipe.ToJson().Length > 10), $"{Presets.All.Count} پریست سالم ({string.Join("، ", Presets.All.Select(p => p.Title))})");

// ───────────── ۲. FFmpeg و ساختنِ کلیپ‌های ساختگی ─────────────
Section("۲. FFmpeg و شناختِ فایل");
Check(ff.Available, "FFmpeg: " + (ff.Available ? ff.FFmpegPath : "پیدا نشد"));
if (!ff.Available) { Console.WriteLine("بی FFmpeg بقیهٔ آزمون ممکن نیست — tools\\Install-FFmpeg.ps1"); return 1; }
Check(ff.Version.Contains("ffmpeg"), ff.Version);
var sw = Stopwatch.StartNew();
string Src(string name) => Path.Combine(srcDir, name);
async Task Gen(string name, params string[] a)
{
    if (File.Exists(Src(name))) return;
    var r = await ff.FFmpegAsync(new[] { "-y" }.Concat(a).Append(Src(name)), workDir: srcDir);
    if (!r.Ok) Console.WriteLine($"    ساختنِ {name} نشد: {r.ErrorTail}");
}
const string Grad = "nullsrc=s=320x180:r=25:d=2,geq=lum='40+180*X/W':cb=128:cr=128,format=yuv420p," +
    "drawbox=x=20:y=20:w=60:h=40:color=red:t=fill,drawbox=x=130:y=20:w=60:h=40:color=blue:t=fill,drawbox=x=240:y=20:w=60:h=40:color=green:t=fill";
string[] X264 = { "-c:v", "libx264", "-preset", "ultrafast", "-crf", "16", "-pix_fmt", "yuv420p" };
await Gen("base.mp4", new[] { "-f", "lavfi", "-i", "testsrc2=s=320x180:r=25:d=4", "-f", "lavfi", "-i", "sine=f=440:sample_rate=48000:d=4", "-af", "volume=-14dB" }
    .Concat(X264).Concat(new[] { "-c:a", "aac", "-b:a", "96k", "-shortest" }).ToArray());
await Gen("grad.mp4", new[] { "-f", "lavfi", "-i", Grad }.Concat(X264).Append("-an").ToArray());
await Gen("dark.mp4", new[] { "-f", "lavfi", "-i", Grad + ",curves=all='0/0 1/0.35'" }.Concat(X264).Append("-an").ToArray());
await Gen("cast.mp4", new[] { "-f", "lavfi", "-i", Grad + ",colorchannelmixer=rr=1.35:gg=1.0:bb=0.72" }.Concat(X264).Append("-an").ToArray());
await Gen("shaky.mp4", new[] { "-f", "lavfi", "-i", "testsrc2=s=480x270:r=25:d=3,crop=320:180:80+40*sin(n*1.9)*sin(n*0.7):45+25*cos(n*2.3)" }.Concat(X264).Append("-an").ToArray());
await Gen("hdr.mp4", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=25:d=1,format=yuv420p10le", "-c:v", "libx265", "-preset", "ultrafast",
    "-x265-params", "log-level=error:colorprim=bt2020:transfer=arib-std-b67:colormatrix=bt2020nc",
    "-color_primaries", "bt2020", "-color_trc", "arib-std-b67", "-colorspace", "bt2020nc", "-an");
await Gen("interlaced.mp4", new[] { "-f", "lavfi", "-i", "testsrc2=s=320x180:r=25:d=1,setfield=tff" }.Concat(X264).Concat(new[] { "-flags", "+ildct+ilme", "-x264-params", "interlaced=1:tff=1", "-an" }).ToArray());
if (!File.Exists(Src("rot.mp4"))) await Gen("rot.mp4", "-display_rotation", "90", "-i", Src("base.mp4"), "-c", "copy");
await Gen("quiet.wav", "-f", "lavfi", "-i", "aevalsrc='0.02*sin(2*PI*300*t)*(0.6+0.4*sin(2*PI*2*t))':s=48000:d=3");
await Gen("hum.wav", "-f", "lavfi", "-i", "aevalsrc='0.2*sin(2*PI*1000*t)*(0.5+0.5*sin(2*PI*3*t))+0.1*sin(2*PI*50*t)+0.05*sin(2*PI*100*t)+0.03*sin(2*PI*150*t)':s=48000:d=4");
await Gen("noisy.wav", "-f", "lavfi", "-i", "aevalsrc='0.25*sin(2*PI*700*t)*lt(mod(t,1),0.6)':s=48000:d=4", "-f", "lavfi", "-i", "anoisesrc=a=0.03:c=white:r=48000:d=4",
    "-filter_complex", "[0][1]amix=inputs=2:normalize=0");
await Gen("gaps.wav", "-f", "lavfi", "-i", "aevalsrc='0.3*sin(2*PI*400*t)*lt(mod(t,2),1)':s=48000:d=6");
await Gen("rumble.wav", "-f", "lavfi", "-i", "aevalsrc='0.3*sin(2*PI*40*t)+0.1*sin(2*PI*1000*t)':s=48000:d=3");
Check(Directory.GetFiles(srcDir).Length >= 13, $"{Directory.GetFiles(srcDir).Length} کلیپِ ساختگی ({sw.ElapsedMilliseconds}ms)");

var mBase = await MediaInfo.ProbeAsync(ff, Src("base.mp4"));
Check(mBase.Width == 320 && mBase.Height == 180 && Math.Abs(mBase.Fps - 25) < 0.01 && Math.Abs(mBase.Duration - 4) < 0.1 && mBase.HasAudio && mBase.SampleRate == 48000,
    "شناختِ فایل: " + mBase.Describe());
var mRot = await MediaInfo.ProbeAsync(ff, Src("rot.mp4"));
Check(mRot.Width == 180 && mRot.Height == 320 && mRot.Rotation is 90 or 270, $"ویدیوی چرخیدهٔ گوشی ⇒ {mRot.Width}×{mRot.Height} (چرخش {mRot.Rotation}°)");
var mHdr = await MediaInfo.ProbeAsync(ff, Src("hdr.mp4"));
Check(mHdr.Hdr, $"HDR شناخته شد ({mHdr.ColorTransfer}, {mHdr.PixelFormat})");
var mInt = await MediaInfo.ProbeAsync(ff, Src("interlaced.mp4"));
Check(mInt.Interlaced, $"درهم‌رفته شناخته شد (field_order={mInt.FieldOrder})");
var mWav = await MediaInfo.ProbeAsync(ff, Src("hum.wav"));
Check(!mWav.HasVideo && mWav.HasAudio && Math.Abs(mWav.Duration - 4) < 0.05, "فایلِ فقط‌صدا: " + mWav.Describe());

// ───────────── ۳. LUTِ رنگ ─────────────
Section("۳. LUTِ رنگ (همان ریاضیِ ویرایشگرِ عکس)");
{
    var id = new VideoRecipe();
    Check(!ColorLut.Needed(id) && !ColorLut.Needed(VideoRecipe.Parse("""{"adjust":{"noise":50,"sharpen":30}}""")), "بی تنظیمِ رنگ ⇒ LUT ساخته نمی‌شود (صدا و شارپ LUT نمی‌خواهند)");
    var (r1, g1, b1) = ColorLut.Apply(VideoRecipe.Parse("""{"adjust":{"exposure":1}}"""), 0.4f, 0.4f, 0.4f);
    Check(r1 > 0.5f && Math.Abs(r1 - g1) < 0.01, $"نوردهی +۱ ⇒ خاکستریِ ۰٫۴ ⇐ {r1:0.00}");
    var (r2, g2, b2) = ColorLut.Apply(VideoRecipe.Parse("""{"adjust":{"saturation":-100}}"""), 0.15f, 0.3f, 0.85f);
    Check(Math.Abs(r2 - b2) < 0.01 && r2 < 0.45f, $"اشباع −۱۰۰ ⇒ سیاه‌وسفید بر پایهٔ روشنایی ({r2:0.00}، {g2:0.00}، {b2:0.00})");
    var (r3, _, b3) = ColorLut.Apply(VideoRecipe.Parse("""{"adjust":{"temperature":50}}"""), 0.5f, 0.5f, 0.5f);
    Check(r3 > b3 + 0.1f, $"دما +۵۰ ⇒ گرم‌تر (R {r3:0.00}، B {b3:0.00})");
    var tmp = Path.Combine(outDir, "test.cube");
    var rec = VideoRecipe.Parse("""{"adjust":{"contrast":40,"vibrance":30,"shadowsSat":30},"curve":{"rgb":[[0,0],[128,150],[255,255]]}}""");
    ColorLut.Write(rec, tmp);
    var cube = CubeLut.Parse(File.ReadAllText(tmp));
    var worst = 0f;
    foreach (var c in new[] { (0.2f, 0.4f, 0.6f), (0.9f, 0.1f, 0.3f), (0.5f, 0.5f, 0.5f), (0.05f, 0.8f, 0.2f) })
    {
        var a = ColorLut.Apply(rec, c.Item1, c.Item2, c.Item3); var b = cube.Sample(c.Item1, c.Item2, c.Item3);
        worst = Math.Max(worst, Math.Max(Math.Abs(a.R - b.R), Math.Max(Math.Abs(a.G - b.G), Math.Abs(a.B - b.B))));
    }
    Check(cube.Size == 33 && worst < 0.02, $"فایلِ .cube (۳۳×۳۳×۳۳، {new FileInfo(tmp).Length / 1024}KB) همان رنگ‌ها را می‌دهد (بیشترین خطای درون‌یابی {worst:0.000})");
    var halfLook = VideoRecipe.Parse("""{"lut":{"file":"x.cube","mode":"look","amount":50}}""");
    var inv = CubeLut.Parse(Invert33());
    var (r4, _, _) = ColorLut.Apply(halfLook, 0.2f, 0.2f, 0.2f, inv);
    Check(Math.Abs(r4 - 0.5f) < 0.02, $"LUTِ کاربر (نگاتیو) با شدتِ ۵۰٪ ⇒ نیمه‌راه ({r4:0.00})");
}

// ───────────── ۴. کتابخانه و فریم‌ها ─────────────
Section("۴. کتابخانه، فریمِ پیش‌نمایش و هر ابزار روی فریم");
var data = Path.Combine(outDir, "service");
if (Directory.Exists(data)) Directory.Delete(data, true);
using var svc = new VideoService(data, ff);
async Task<VideoDoc> Add(string name) { await using var fs = File.OpenRead(Src(name)); return await svc.CreateAsync(fs, name, fs.Length); }
var dBase = await Add("base.mp4");
var dGrad = await Add("grad.mp4");
Check(svc.List().Count == 2 && dBase.Media.Width == 320, $"ثبت در کتابخانه (جریانی، بی نگه داشتن در حافظه): {dBase.Id}");
try { await using var bad = new MemoryStream(Encoding.UTF8.GetBytes("not a video at all")); await svc.CreateAsync(bad, "x.mp4"); Check(false, "فایلِ خراب رد نشد"); }
catch (InvalidDataException e) { Check(svc.List().Count == 2, "فایلِ خراب رد شد: " + e.Message[..Math.Min(60, e.Message.Length)] + "…"); }

async Task<(byte[] Rgb, int W, int H)> FrameRgb(string docId, string json, double t = 1, bool original = false, int max = 320)
{
    var (jpg, w, h) = await svc.FrameAsync(docId, VideoRecipe.Parse(json), t, max, original);
    var f = Path.Combine(outDir, "frame.jpg");
    await File.WriteAllBytesAsync(f, jpg);
    var r = await ff.FFmpegAsync(new[] { "-i", f, "-f", "rawvideo", "-pix_fmt", "rgb24", "-" }, captureStdOut: true);
    return (r.StdOut, w, h);
}
(double R, double G, double B) Mean(byte[] rgb)
{
    double r = 0, g = 0, b = 0; int n = rgb.Length / 3;
    for (int i = 0; i < n; i++) { r += rgb[i * 3]; g += rgb[i * 3 + 1]; b += rgb[i * 3 + 2]; }
    return (r / n / 255, g / n / 255, b / n / 255);
}
double Lum((double R, double G, double B) m) => 0.2126 * m.R + 0.7152 * m.G + 0.0722 * m.B;

sw.Restart();
var fOrig = await FrameRgb(dGrad.Id, "{}", original: true);
var tOrig = sw.ElapsedMilliseconds;
var fId = await FrameRgb(dGrad.Id, "{}");
double maxDiff = 0;
for (int i = 0; i < Math.Min(fOrig.Rgb.Length, fId.Rgb.Length); i++) maxDiff = Math.Max(maxDiff, Math.Abs(fOrig.Rgb[i] - fId.Rgb[i]));
Check(fOrig.W == 320 && fId.Rgb.Length == fOrig.Rgb.Length && Lum(Mean(fId.Rgb)) - Lum(Mean(fOrig.Rgb)) is > -0.01 and < 0.01,
    $"بی‌تنظیم ⇒ همان فریم (فریم در {tOrig}ms؛ اختلافِ میانگین {Math.Abs(Lum(Mean(fId.Rgb)) - Lum(Mean(fOrig.Rgb))):0.000})");
var baseLum = Lum(Mean(fOrig.Rgb));
sw.Restart();
var fExp = await FrameRgb(dGrad.Id, """{"adjust":{"exposure":1}}""");
Check(Lum(Mean(fExp.Rgb)) > baseLum * 1.25, $"نوردهی +۱ روی فریم ⇒ {baseLum:0.00} ⇐ {Lum(Mean(fExp.Rgb)):0.00} ({sw.ElapsedMilliseconds}ms با ساختنِ LUT)");
var fWarm = Mean((await FrameRgb(dGrad.Id, """{"adjust":{"temperature":50}}""")).Rgb);
var fO = Mean(fOrig.Rgb);
Check(fWarm.R / fWarm.B > fO.R / fO.B * 1.2, $"دما +۵۰ ⇒ R/B {fO.R / fO.B:0.00} ⇐ {fWarm.R / fWarm.B:0.00}");
var fBw = Mean((await FrameRgb(dGrad.Id, """{"preset":"bw"}""" )).Rgb);
var bwRaw = await FrameRgb(dGrad.Id, """{"adjust":{"saturation":-100}}""");
var satMax = 0;
for (int i = 0; i < bwRaw.Rgb.Length; i += 3) satMax = Math.Max(satMax, Math.Max(bwRaw.Rgb[i], Math.Max(bwRaw.Rgb[i + 1], bwRaw.Rgb[i + 2])) - Math.Min(bwRaw.Rgb[i], Math.Min(bwRaw.Rgb[i + 1], bwRaw.Rgb[i + 2])));
Check(satMax < 14, $"اشباع −۱۰۰ ⇒ سیاه‌وسفید (بیشترین فرقِ کانال‌ها {satMax}/255)");
var f916 = await FrameRgb(dBase.Id, """{"frame":{"aspect":"9:16","fit":"crop"}}""", max: 640);
Check(Math.Abs(f916.W / (double)f916.H - 9 / 16.0) < 0.02, $"قابِ ۹:۱۶ (بریدن) ⇒ {f916.W}×{f916.H}");
var fBlur = await FrameRgb(dBase.Id, """{"frame":{"aspect":"9:16","fit":"blur"}}""", max: 640);
Check(Math.Abs(fBlur.W / (double)fBlur.H - 9 / 16.0) < 0.02 && Lum(Mean(fBlur.Rgb)) > 0.1, $"قابِ ۹:۱۶ با زمینهٔ محو ⇒ {fBlur.W}×{fBlur.H}");
var fBlack = await FrameRgb(dBase.Id, """{"frame":{"aspect":"1:1","fit":"black"}}""", max: 320);
var topRow = Mean(fBlack.Rgb[..(fBlack.W * 3 * 8)]);
Check(fBlack.W == fBlack.H && Lum(topRow) < 0.03, $"قابِ ۱:۱ با نوارِ سیاه ⇒ {fBlack.W}×{fBlack.H}، بالا سیاه");
var fCrop = await FrameRgb(dBase.Id, """{"crop":{"x":0.25,"y":0.25,"w":0.5,"h":0.5}}""", max: 1000);
Check(fCrop.W == 160 && fCrop.H == 90, $"برشِ نصف ⇒ {fCrop.W}×{fCrop.H}");
var bad2 = new List<string>();
foreach (var json in new[] { """{"crop":{"angle":8}}""", """{"crop":{"flipH":true,"flipV":true}}""", """{"adjust":{"distortion":60}}""", """{"adjust":{"distortion":-60}}""",
             """{"adjust":{"denoise":80,"denoiseColor":80}}""", """{"adjust":{"sharpen":100,"clarity":80}}""", """{"adjust":{"clarity":-80}}""",
             """{"adjust":{"vignette":100,"grain":100}}""", """{"preset":"cinematic"}""", """{"preset":"film"}""", """{"adjust":{"redHue":50,"blueSat":-100,"greenLum":40}}""" })
{
    try
    {
        var fr = await FrameRgb(dBase.Id, json);
        if (fr.W < 10 || fr.Rgb.Length != fr.W * fr.H * 3) bad2.Add(json);
    }
    catch (Exception e) { bad2.Add(json + ": " + e.Message); }
}
Check(bad2.Count == 0, "چرخش، قرینه، لنز، نویزگیری، شارپ، وضوح، وینیت، دانه، پریست‌ها، HSL روی فریم سالم" + (bad2.Count > 0 ? ": " + string.Join(" | ", bad2) : ""));
var dHdr = await Add("hdr.mp4");
var fHdr = await FrameRgb(dHdr.Id, """{"adjust":{"contrast":10}}""");
Check(fHdr.W == 320 && Lum(Mean(fHdr.Rgb)) > 0.1, $"HDR ⇒ خودکار به SDR (روشنایی {Lum(Mean(fHdr.Rgb)):0.00})");
var dInt = await Add("interlaced.mp4");
Check((await FrameRgb(dInt.Id, "{}")).W == 320, "درهم‌رفته ⇒ باز شد (bwdif)");
var dRot = await Add("rot.mp4");
var fRot = await FrameRgb(dRot.Id, "{}", max: 320);
Check(fRot.H > fRot.W, $"ویدیوی گوشی ⇒ فریمِ عمودی {fRot.W}×{fRot.H}");
Check((await svc.ThumbAsync(dBase.Id)).Length > 1000 && (await svc.StripAsync(dBase.Id, 5)).Length > 500 && (await svc.WaveformAsync(dBase.Id))!.Length > 500,
    "عکسِ کوچک، نوارِ ۱۲ فریم و موجِ صدا");

// ───────────── ۵. خروجی‌ها ─────────────
Section("۵. خروجی (کار در پس‌زمینه با پیشرفت)");
async Task<(VideoJob Job, MediaInfo? M)> Export(string docId, string json)
{
    var job = await svc.WaitAsync(svc.StartExport(docId, VideoRecipe.Parse(json)));
    MediaInfo? m = job.State == "done" ? await MediaInfo.ProbeAsync(ff, job.FilePath!) : null;
    if (job.State != "done") Console.WriteLine($"    {json}: {job.State} {job.Error}");
    return (job, m);
}
sw.Restart();
var (e1, m1) = await Export(dBase.Id, "{}");
Check(m1 is { Width: 320, Height: 180, HasAudio: true, VideoCodec: "h264" } && Math.Abs(m1.Duration - 4) < 0.15,
    $"MP4ِ بی‌تنظیم: {m1?.Describe()} در {e1.Seconds:0.0}s، پیشرفت {e1.Progress:P0}");
var (e2, m2) = await Export(dBase.Id, """{"trim":{"start":1,"end":3}}""");
Check(m2 is not null && Math.Abs(m2.Duration - 2) < 0.12, $"بُرشِ ۱ تا ۳ ⇒ {m2?.Duration:0.00}s");
var (e3, m3) = await Export(dBase.Id, """{"cuts":[{"start":1,"end":2}]}""");
Check(m3 is not null && Math.Abs(m3.Duration - 3) < 0.15 && m3.HasAudio, $"حذفِ بازهٔ ۱ تا ۲ ⇒ {m3?.Duration:0.00}s با صدا");
var (e4, m4) = await Export(dBase.Id, """{"time":{"speed":2}}""");
Check(m4 is not null && Math.Abs(m4.Duration - 2) < 0.15 && m4.HasAudio, $"سرعتِ ۲× ⇒ {m4?.Duration:0.00}s (صدا بی تغییرِ زیر و بمی)");
var (e5, m5) = await Export(dBase.Id, """{"preset":"reels","output":{"size":180}}""");
Check(m5 is { Width: 180, Height: 320 }, $"ریلز ⇒ {m5?.Width}×{m5?.Height}");
var (e6, m6) = await Export(dBase.Id, """{"frame":{"aspect":"1:1"},"output":{"size":180,"format":"webm"}}""");
Check(m6 is { Width: 180, Height: 180, VideoCodec: "vp9", AudioCodec: "opus" }, $"مربع + WebM ⇒ {m6?.Width}×{m6?.Height} {m6?.VideoCodec}/{m6?.AudioCodec}");
var (e7, m7) = await Export(dBase.Id, """{"output":{"format":"gif","size":120}}""");
Check(m7 is { VideoCodec: "gif", HasAudio: false } && m7.Height == 120, $"GIF ⇒ {m7?.Width}×{m7?.Height}، بی‌صدا، {e7.FileSize / 1024}KB");
var (e8, m8) = await Export(dBase.Id, """{"output":{"format":"mp3"}}""");
Check(m8 is { HasVideo: false, AudioCodec: "mp3" }, $"فقط صدا ⇒ {m8?.AudioCodec}");
var (e9, m9) = await Export(dBase.Id, """{"output":{"codec":"h265","quality":"small"}}""");
Check(m9 is { VideoCodec: "hevc" }, $"H.265 ⇒ {m9?.VideoCodec} ({e9.FileSize / 1024}KB در برابرِ {e1.FileSize / 1024}KB)");
var (e10, m10) = await Export(dBase.Id, """{"time":{"fadeIn":1,"fadeOut":1},"adjust":{"exposure":0.5,"sharpen":30,"denoise":20},"audio":{"mute":true}}""");
Check(m10 is { HasAudio: false } && Math.Abs(m10.Duration - 4) < 0.15, "محو، رنگ، شارپ، نویزگیری، بی‌صدا");
var (e11, m11) = await Export(dHdr.Id, """{"output":{"size":180}}""");
Check(m11 is { ColorTransfer: "bt709" }, $"HDR ⇒ SDR با برچسبِ bt709 ({m11?.ColorTransfer}، {m11?.PixelFormat})");
var (e12, m12) = await Export(dRot.Id, """{"trim":{"end":1}}""");
Check(m12 is not null && m12.Height > m12.Width, $"ویدیوی گوشی عمودی ماند ⇒ {m12?.Width}×{m12?.Height}");
Console.WriteLine($"    ({sw.Elapsed.TotalSeconds:0.0}s برای ۱۲ خروجی)");

// تثبیت: لرزشِ فریم به فریم کم شود
{
    var dShaky = await Add("shaky.mp4");
    var (es, ms) = await Export(dShaky.Id, """{"stabilize":{"amount":70}}""");
    double Jitter(string file)
    {
        var r = ff.FFmpegAsync(new[] { "-i", file, "-vf", "scale=80:45,format=gray", "-f", "rawvideo", "-" }, captureStdOut: true).GetAwaiter().GetResult();
        var b = r.StdOut; int fs = 80 * 45, n = b.Length / fs; double sum = 0;
        for (int k = 1; k < n; k++) { double d = 0; for (int i = 0; i < fs; i++) d += Math.Abs(b[k * fs + i] - b[(k - 1) * fs + i]); sum += d / fs; }
        return sum / Math.Max(1, n - 1);
    }
    var j0 = Jitter(Src("shaky.mp4"));
    var j1 = es.FilePath is null ? j0 : Jitter(es.FilePath);
    Check(es.State == "done" && j1 < j0 * 0.75, $"تثبیت (دو پاس: تحلیل + اصلاح) ⇒ لرزشِ فریم‌به‌فریم {j0:0.0} ⇐ {j1:0.0} در {es.Seconds:0.0}s");
}
// پیش‌نمایشِ متحرک و لغو
{
    var pj = await svc.WaitAsync(svc.StartPreview(dBase.Id, VideoRecipe.Parse("""{"adjust":{"exposure":0.3}}"""), 1, 2));
    var pm = pj.FilePath is null ? null : await MediaInfo.ProbeAsync(ff, pj.FilePath);
    Check(pj.State == "done" && pm is not null && Math.Abs(pm.Duration - 2) < 0.15, $"پیش‌نمایشِ متحرکِ ۲ ثانیه ⇒ {pm?.Width}×{pm?.Height} در {pj.Seconds:0.0}s");
    var slow = svc.StartExport(dBase.Id, VideoRecipe.Parse("""{"time":{"speed":0.25,"smooth":true},"adjust":{"denoise":60}}"""));
    await Task.Delay(700);
    svc.CancelJob(slow.Id);
    await svc.WaitAsync(slow);
    Check(slow.State == "cancelled" && slow.FilePath is null, $"لغو ⇒ {slow.State}");
}

// ───────────── ۶. صدا ─────────────
Section("۶. صدا: بلندی، نویز، وزوزِ برق، غرش، مکث‌ها");
async Task<double> LoudnessOf(string file)
{
    var r = await ff.FFmpegAsync(new[] { "-i", file, "-vn", "-af", "loudnorm=print_format=json", "-f", "null", "-" });
    return LoudnessMeasure.Parse(r.StdErr)?.I ?? double.NaN;
}
float[] Pcm(string file, int sr)
{
    var r = ff.FFmpegAsync(new[] { "-i", file, "-vn", "-ac", "1", "-ar", sr.ToString(ci), "-f", "f32le", "-" }, captureStdOut: true).GetAwaiter().GetResult();
    var x = new float[r.StdOut.Length / 4];
    Buffer.BlockCopy(r.StdOut, 0, x, 0, x.Length * 4);
    return x;
}
double Power(float[] x, int sr, double f)
{
    var w = 2 * Math.PI * f / sr; double c = 2 * Math.Cos(w), s1 = 0, s2 = 0;
    for (int i = sr / 4; i < x.Length - sr / 4; i++) { var s0 = x[i] + c * s1 - s2; s2 = s1; s1 = s0; }
    return (s1 * s1 + s2 * s2 - c * s1 * s2) / x.Length;
}
{
    var dQ = await Add("quiet.wav");
    var before = await LoudnessOf(Src("quiet.wav"));
    var (eq, mq) = await Export(dQ.Id, """{"audio":{"normalize":-16},"output":{"format":"wav"}}""");
    var after = eq.FilePath is null ? double.NaN : await LoudnessOf(eq.FilePath);
    Check(Math.Abs(after + 16) < 1.5, $"هم‌سطح‌سازی (دو پاس، خطی) ⇒ {before:0.0} ⇐ {after:0.0} LUFS (هدف ‎−۱۶)");

    var dH = await Add("hum.wav");
    var sH = await svc.AnalyzeAsync(dH.Id);
    var (eh, _) = await Export(dH.Id, """{"audio":{"hum":50},"output":{"format":"wav"}}""");
    var xh0 = Pcm(Src("hum.wav"), 8000); var xh1 = Pcm(eh.FilePath!, 8000);
    var hum0 = Power(xh0, 8000, 50) + Power(xh0, 8000, 100); var hum1 = Power(xh1, 8000, 50) + Power(xh1, 8000, 100);
    var tone0 = Power(xh0, 8000, 1000); var tone1 = Power(xh1, 8000, 1000);
    Check(sH.Hum == 50, $"وزوزِ برق پیدا شد: {sH.Hum} هرتز (قدرت {sH.HumStrength:0}×)");
    Check(hum1 < hum0 / 30 && tone1 > tone0 * 0.7, $"حذفِ وزوز ⇒ ۵۰+۱۰۰ هرتز {10 * Math.Log10(hum1 / hum0):0} دسی‌بل؛ صدای اصلی ماند ({10 * Math.Log10(tone1 / tone0):0.0} دسی‌بل)");

    var dN = await Add("noisy.wav");
    var sN = await svc.AnalyzeAsync(dN.Id);
    var (en, _) = await Export(dN.Id, """{"adjust":{"noise":70},"output":{"format":"wav"}}""");
    var sN2 = await Analysis.MeasureAudioAsync(ff, en.FilePath!, await MediaInfo.ProbeAsync(ff, en.FilePath!), new VideoStats { HasAudio = true });
    Check(sN2.NoiseFloor < sN.NoiseFloor - 6, $"کاهشِ نویز ⇒ کفِ نویز {sN.NoiseFloor:0.0} ⇐ {sN2.NoiseFloor:0.0} dB");

    var dR = await Add("rumble.wav");
    var (er, _) = await Export(dR.Id, """{"adjust":{"rumble":60},"output":{"format":"wav"}}""");
    var xr0 = Pcm(Src("rumble.wav"), 8000); var xr1 = Pcm(er.FilePath!, 8000);
    Check(Power(xr1, 8000, 40) < Power(xr0, 8000, 40) / 10 && Power(xr1, 8000, 1000) > Power(xr0, 8000, 1000) * 0.8,
        $"کاهشِ غرش ⇒ ۴۰ هرتز {10 * Math.Log10(Power(xr1, 8000, 40) / Power(xr0, 8000, 40)):0} دسی‌بل؛ ۱ کیلوهرتز ماند");

    var dG = await Add("gaps.wav");
    var (sil, cuts, saved, thr) = await svc.PausesAsync(dG.Id);
    Check(sil.Count == 3 && cuts.Count == 3 && saved is > 1.8 and < 2.4, $"مکث‌ها (آستانهٔ خودکار {thr} dB) ⇒ {sil.Count} سکوت، {cuts.Count} بازهٔ پیشنهادی برای حذف ({saved:0.0} ثانیه کوتاه‌تر)");
    var (eg, mg) = await Export(dG.Id, "{\"cuts\":" + System.Text.Json.JsonSerializer.Serialize(cuts, VideoJson.Options) + ",\"output\":{\"format\":\"wav\"}}");
    Check(mg is not null && Math.Abs(mg.Duration - (6 - saved)) < 0.1, $"حذفِ مکث‌ها ⇒ {mg?.Duration:0.00}s از ۶");
}

// ───────────── ۷. خودکار ─────────────
Section("۷. تنظیمِ خودکارِ رایگان");
{
    var dD = await Add("dark.mp4");
    var aD = await svc.AutoAsync(dD.Id);
    Check(aD.Recipe.Get("exposure") > 0.3, $"فیلمِ تیره ⇒ نوردهی +{aD.Recipe.Get("exposure"):0.00}: {string.Join(" ", aD.Notes)}");
    var dC = await Add("cast.mp4");
    var aC = await svc.AutoAsync(dC.Id);
    var fixedFrame = Mean((await FrameRgb(dC.Id, aC.Recipe.ToJson())).Rgb);
    var castFrame = Mean((await FrameRgb(dC.Id, "{}", original: true)).Rgb);
    Check(aC.Recipe.Get("temperature") < -10 && Math.Abs(fixedFrame.R - fixedFrame.B) < Math.Abs(castFrame.R - castFrame.B) * 0.6,
        $"ته‌رنگِ قرمز ⇒ دما {aC.Recipe.Get("temperature"):0}؛ R−B {castFrame.R - castFrame.B:0.00} ⇐ {fixedFrame.R - fixedFrame.B:0.00}");
    var aQ = await svc.AutoAsync(svc.List().First(d => d.Name == "quiet").Id);
    Check(aQ.Recipe.Audio?.Normalize == -14, "صدای آرام ⇒ هم‌سطح‌سازیِ ‎−۱۴");
    var aH = await svc.AutoAsync(svc.List().First(d => d.Name == "hum").Id);
    Check(aH.Recipe.Audio?.Hum == 50, "وزوزِ برق ⇒ حذفِ ۵۰ هرتز");
    var aN = await svc.AutoAsync(svc.List().First(d => d.Name == "noisy").Id);
    Check(aN.Recipe.Get("noise") > 0, $"صدای پرنویز ⇒ کاهشِ نویز {aN.Recipe.Get("noise"):0}");
}

// ───────────── ۸. هوشِ مصنوعی (ساختگی) ─────────────
Section("۸. ویرایشگرِ هوشمند (بی اینترنت: سرویسِ ساختگی)");
{
    var fake = new FakeAi();
    using var svcAi = new VideoService(data, ff, new VisionAgentOptions { ApiKey = "test", Models = "fake-model", MaxRounds = 2 }, fake);
    var res = await svcAi.AiEditAsync(dBase.Id, "ریلزِ اینستاگرام", VideoRecipe.Parse("""{"trim":{"start":0.5}}"""));
    Check(res.UsedAi && res.Recipe.Get("exposure") == 3 && res.Recipe.Get("temperature") == 18 && res.Recipe.Frame?.Aspect == "9:16" &&
          res.Recipe.Trim?.Start == 0.5 && !res.Recipe.Adjust.ContainsKey("bogus") && res.Steps.Count == 2 && res.Steps[1].Done,
        $"پاسخِ نیمه‌خراب (پریست + عددِ بیرون از بازه + کلیدِ ناشناخته) ⇒ {res.Recipe.ToJson()}؛ بُرشِ کاربر ماند");
    Check(fake.Calls == 2 && fake.SawImages == 2 && fake.MaxImageKb < 80, $"۲ درخواست، هر بار یک تصویرِ ۲×۲ (بزرگ‌ترین {fake.MaxImageKb:0}KB)");
    var noKey = await svc.AiEditAsync(dBase.Id, null, new VideoRecipe());
    Check(!noKey.UsedAi && noKey.Recipe.Audio?.Normalize == -14, "بی کلید ⇒ تنظیمِ خودکارِ رایگان");
}

// ───────────── ویدیوی کاربر ─────────────
if (Arg("--video") is { } user && File.Exists(user))
{
    Section("ویدیوی شما: " + Path.GetFileName(user));
    await using var fs = File.OpenRead(user);
    var d = await svc.CreateAsync(fs, Path.GetFileName(user), fs.Length);
    var st = await svc.AnalyzeAsync(d.Id);
    Console.WriteLine(st.Describe(d.Media));
    var a = await svc.AutoAsync(d.Id);
    Console.WriteLine("    خودکار: " + string.Join(" ", a.Notes));
    var rec = a.Recipe.Clone();
    rec.Trim = new TrimSettings { Start = 0, End = Math.Min(10, d.Media.Duration) };
    var (ej, em) = await Export(d.Id, rec.ToJson());
    Check(ej.State == "done", $"خروجیِ ۱۰ ثانیهٔ اول ⇒ {ej.FilePath} ({ej.Seconds:0.0}s)");
}

svc.Delete(dBase.Id);
Check(svc.List().All(d => d.Id != dBase.Id), "پاک شد");
Console.WriteLine();
Console.ForegroundColor = fails == 0 ? ConsoleColor.Green : ConsoleColor.Red;
Console.WriteLine(fails == 0 ? "همه درست است ✓" : $"{fails} مورد نادرست ✗");
Console.ResetColor();
return fails == 0 ? 0 : 1;

static string FindRoot()
{
    foreach (var start in new[] { AppContext.BaseDirectory, Directory.GetCurrentDirectory() })
    {
        var d = new DirectoryInfo(start);
        for (int i = 0; i < 8 && d is not null; i++, d = d.Parent)
            if (Directory.Exists(Path.Combine(d.FullName, "research")) && Directory.Exists(Path.Combine(d.FullName, "src"))) return d.FullName;
    }
    return Directory.GetCurrentDirectory();
}

// LUTِ نگاتیو (۲×۲×۲ کافی است: خطی)
static string Invert33()
{
    var sb = new StringBuilder("LUT_3D_SIZE 2\n");
    for (int b = 0; b < 2; b++) for (int g = 0; g < 2; g++) for (int r = 0; r < 2; r++) sb.Append($"{1 - r} {1 - g} {1 - b}\n");
    return sb.ToString();
}

/// <summary>سرویسِ ساختگیِ سازگار با OpenAI: دورِ اول پیشنهادِ نیمه‌خراب، دورِ دوم «تمام».</summary>
sealed class FakeAi : HttpMessageHandler
{
    public int Calls, SawImages;
    public double MaxImageKb;

    protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken ct)
    {
        var body = await request.Content!.ReadAsStringAsync(ct);
        Calls++;
        var idx = body.LastIndexOf("data:image/jpeg;base64,", StringComparison.Ordinal);
        if (idx >= 0)
        {
            SawImages++;
            var end = body.IndexOf('"', idx);
            MaxImageKb = Math.Max(MaxImageKb, (end - idx) * 0.75 / 1024);
        }
        var content = Calls == 1
            ? "Here you go:\n```json\n{\"preset\":\"warm\",\"adjust\":{\"exposure\":9,\"bogus\":5},\"frame\":{\"aspect\":\"9:16\",\"fit\":\"blur\"},\"trim\":{\"start\":3},\"notes\":\"گرم‌تر و عمودی برای ریلز.\"}\n```"
            : "{\"done\": true, \"notes\": \"خوب است.\"}";
        var json = System.Text.Json.JsonSerializer.Serialize(new
        {
            model = "fake-model",
            choices = new[] { new { message = new { role = "assistant", content } } },
            usage = new { prompt_tokens = 1800, completion_tokens = 90 },
        });
        return new HttpResponseMessage(HttpStatusCode.OK) { Content = new StringContent(json, Encoding.UTF8, "application/json") };
    }
}
