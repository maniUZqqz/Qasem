// آزمونِ نصبِ ویرایشگرِ عکس — روی همین ماشین، سبک (زیرِ ۱GB حافظه):
//   dotnet run -c Release                       همهٔ ابزارها روی عکس‌های ساختگی + نمونه‌ها + حذفِ سبکِ پس‌زمینه + فیلترها + هوشِ مصنوعیِ ساختگی
//   dotnet run -c Release -- --photos D:\pics   + تنظیمِ خودکار روی عکس‌های خودتان (نتیجه در data\selftest\auto_*.jpg)
//   dotnet run -c Release -- --heavy            + مدل‌های سنگین (BiRefNet ~۶٫۵GB حافظه، Real-ESRGAN) — فقط روی سرور؛ حافظه کم باشد خودش رد می‌شود
//   dotnet run -c Release -- --write-docs       FEATURES.md را از روی فهرستِ ابزارها دوباره می‌سازد
using System.Diagnostics;
using System.Net;
using System.Text;
using OpenCvSharp;
using PersianAiKit.Photo;
using PersianAiKit.Photo.Ai;
using PersianAiKit.Photo.Engine;

Console.OutputEncoding = Encoding.UTF8;
string? Arg(string name) { var i = Array.IndexOf(args, name); return i >= 0 && i + 1 < args.Length ? args[i + 1] : null; }
var heavy = args.Contains("--heavy");

var models = PhotoModels.Find(Arg("--models"));
var root = Path.GetDirectoryName(models.Root)!;
var outDir = Arg("--out") ?? Path.Combine(root, "data", "selftest");
Directory.CreateDirectory(outDir);
if (args.Contains("--write-docs"))
{
    var f = Path.Combine(root, "FEATURES.md");
    File.WriteAllText(f, FeatureDoc.Build(), new UTF8Encoding(false));
    Console.WriteLine("نوشته شد: " + f);
    return 0;
}
if (args.Contains("--prompt"))
{
    // همان متنی که برای هوشِ مصنوعی فرستاده می‌شود (برای برآوردِ هزینه)
    var sp = VisionAgent.SystemPrompt();
    Console.WriteLine(sp);
    Console.WriteLine($"— {sp.Length} نویسه، حدودِ {sp.Length / 4} توکن");
    return 0;
}
Console.WriteLine($"مدل‌ها: {models.Root}");
Console.WriteLine($"خروجی: {outDir}\n");
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
void Save(PhotoImage img, string name) => File.WriteAllBytes(Path.Combine(outDir, name), PhotoIO.Encode(img, name.EndsWith(".png") ? "png" : "jpeg", 90));

// ───────────── ۱. فهرستِ ابزارها و نسخهٔ ویرایش ─────────────
Section("۱. فهرستِ ابزارها و «نسخهٔ ویرایش»");
var keys = ToolCatalog.Params.Select(p => p.Key).ToList();
Check(keys.Distinct(StringComparer.OrdinalIgnoreCase).Count() == keys.Count, $"{keys.Count} لغزنده، کلیدِ تکراری ندارد");
Check(ToolCatalog.Params.All(p => p.Default >= p.Min && p.Default <= p.Max && ToolCatalog.Groups.Any(g => g.Key == p.Group)), "پیش‌فرضِ همه در بازه و گروه‌ها معلوم");
var raw = Recipe.Parse("""{ "adjust": { "exposure": 9, "contrast": "25", "nope": 3, "shadows": 0 }, "crop": { "x": -1, "w": 0.5 }, "background": { "remove": true, "color": "blue?" } }""");
Check(raw.Adjust.Count == 2 && raw.Get("exposure") == 4 && raw.Get("contrast") == 25 && raw.Crop!.X == 0 && raw.Background!.Color == "#ffffff",
    "ورودیِ خراب امن می‌شود: " + raw.ToJson());
Check(Recipe.Parse(raw.ToJson()).ToJson() == raw.ToJson(), "JSON رفت‌وبرگشت یکسان است");

// ───────────── ۲. موتور روی عکسِ ساختگی ─────────────
Section("۲. ابزارها روی عکسِ ساختگی (جوابِ درست معلوم)");
using var synth = Synthetic(600, 400);
double Lum(Mat m) { var s = Cv2.Mean(m); return 0.0722 * s.Val0 + 0.7152 * s.Val1 + 0.2126 * s.Val2; }
double Std(Mat m) { using var g = new Mat(); Cv2.CvtColor(m, g, ColorConversionCodes.BGR2GRAY); Cv2.MeanStdDev(g, out _, out var sd); return sd.Val0; }
double LapVar(Mat m) { using var g = new Mat(); Cv2.CvtColor(m, g, ColorConversionCodes.BGR2GRAY); using var l = new Mat(); Cv2.Laplacian(g, l, MatType.CV_32F); Cv2.MeanStdDev(l, out _, out var sd); return sd.Val0 * sd.Val0; }
PhotoImage R(PhotoImage src, string json, double scale = 1) => PhotoEngine.Render(src, Recipe.Parse(json), scale);

using (var id = R(synth, "{}"))
{
    using var diff = new Mat(); Cv2.Absdiff(id.Color, synth.Color, diff);
    Cv2.MinMaxLoc(diff.Reshape(1), out _, out double mx);
    Check(mx < 0.004, $"بی‌تنظیم ⇒ همان عکس (بیشترین تفاوت {mx:0.0000})");
}
var baseLum = Lum(synth.Color);
using (var e = R(synth, """{"adjust":{"exposure":1}}""")) Check(Lum(e.Color) > baseLum * 1.25, $"نوردهی +۱ ⇒ روشن‌تر ({baseLum:0.00} ⇒ {Lum(e.Color):0.00})");
using (var e = R(synth, """{"adjust":{"contrast":60}}""")) Check(Std(e.Color) > Std(synth.Color) * 1.08, $"کنتراست +۶۰ ⇒ پراکندگی بیشتر ({Std(synth.Color):0.000} ⇒ {Std(e.Color):0.000})");
using (var e = R(synth, """{"adjust":{"saturation":-100}}"""))
{
    var ch = Cv2.Split(e.Color);
    using var d1 = new Mat(); Cv2.Absdiff(ch[0], ch[2], d1);
    Cv2.MinMaxLoc(d1, out _, out double mx);
    foreach (var c in ch) c.Dispose();
    Check(mx < 0.01, $"اشباع −۱۰۰ ⇒ سیاه‌وسفید (بیشترین فرقِ کانال‌ها {mx:0.000})");
}
using (var e = R(synth, """{"adjust":{"temperature":50}}"""))
{
    var m0 = Cv2.Mean(synth.Color); var m1 = Cv2.Mean(e.Color);
    Check(m1.Val2 / m1.Val0 > m0.Val2 / m0.Val0 * 1.15, $"دما +۵۰ ⇒ گرم‌تر (R/B {m0.Val2 / m0.Val0:0.00} ⇒ {m1.Val2 / m1.Val0:0.00})");
}
using (var e = R(synth, """{"curve":{"rgb":[[0,0],[128,170],[255,255]]}}""")) Check(Lum(e.Color) > baseLum * 1.1, "منحنیِ رو به بالا ⇒ میانه‌ها روشن‌تر");
using (var e = R(synth, """{"adjust":{"blueSat":-100}}"""))
{
    // خانهٔ آبیِ عکسِ ساختگی بی‌رنگ و بقیه دست‌نخورده
    var blue = e.Color.At<Vec3f>(50, 475); var red = e.Color.At<Vec3f>(50, 75);
    // فامِ این خانه ۲۲۷° است (بینِ فیروزه‌ای و آبی) ⇒ مثلِ لایت‌روم بیشترِ رنگش می‌رود، نه همه‌اش
    Check(blue.Item0 - blue.Item2 < 0.7 * 0.35 && red.Item2 - red.Item0 > 0.4, $"اشباعِ آبی −۱۰۰ ⇒ آبی کم‌رنگ شد، قرمز ماند (آبی B−R {0.7:0.00} ⇒ {blue.Item0 - blue.Item2:0.00}، قرمز {red.Item2:0.00})");
}
using (var e = R(synth, """{"crop":{"x":0.25,"y":0.25,"w":0.5,"h":0.5}}""")) Check(e.Width == 300 && e.Height == 200, $"برشِ نصف ⇒ {e.Width}×{e.Height}");
using (var e = R(synth, """{"crop":{"angle":10}}""")) Check(e.Width == 600 && e.Height == 400 && Lum(e.Color) > 0.05, "چرخش ۱۰° ⇒ همان اندازه، بی گوشهٔ سیاه");
using (var e = R(synth, """{"crop":{"flipH":true}}"""))
{
    var a = synth.Color.At<Vec3f>(50, 75); var b = e.Color.At<Vec3f>(50, 600 - 1 - 75);
    Check(Math.Abs(a.Item2 - b.Item2) < 0.01, "قرینهٔ افقی");
}
using (var e = R(synth, """{"adjust":{"vignette":-80}}""")) Check(e.Color.At<Vec3f>(399, 0).Item1 < synth.Color.At<Vec3f>(399, 0).Item1 * 0.6, "وینیت −۸۰ ⇒ گوشه تیره‌تر");
using (var blurry = new PhotoImage(Blur(synth.Color, 2)))
using (var e = R(blurry, """{"adjust":{"sharpen":100,"sharpenRadius":1.5}}""")) Check(LapVar(e.Color) > LapVar(blurry.Color) * 1.5, $"شارپ ⇒ لبه تیزتر (واریانسِ لاپلاسین {LapVar(blurry.Color):0.0000} ⇒ {LapVar(e.Color):0.0000})");
using (var noisy = Noisy(synth, 0.05))
using (var e = R(noisy, """{"adjust":{"noiseLuma":70,"noiseColor":60}}"""))
{
    var n0 = Analysis.Measure(noisy).Noise; var n1 = Analysis.Measure(e).Noise;
    Check(n1 < n0 * 0.6, $"نویزگیری ⇒ نویزِ سنجیده {n0:0.0} ⇒ {n1:0.0}");
}
using (var hazy = Hazy(synth))
using (var e = R(hazy, """{"adjust":{"dehaze":80}}""")) Check(Std(e.Color) > Std(hazy.Color) * 1.3, $"مه‌زدایی ⇒ کنتراست {Std(hazy.Color):0.000} ⇒ {Std(e.Color):0.000}");
using (var dot = synth.Clone())
{
    Cv2.Circle(dot.Color, new Point(500, 200), 6, new Scalar(0, 0, 0), -1);
    using var e = R(dot, """{"spots":[{"x":0.8347,"y":0.5013,"r":0.03}]}""");
    var v = e.Color.At<Vec3f>(200, 500); var around = synth.Color.At<Vec3f>(200, 500);
    Check(Math.Abs(v.Item1 - around.Item1) < 0.12, $"ترمیمِ لکه ⇒ نقطهٔ سیاه پاک شد ({v.Item1:0.00} در برابرِ {around.Item1:0.00})");
}
// همهٔ لغزنده‌ها در دو سر: خطا نمی‌دهد، عدد معتبر، اندازه درست
var bad = new List<string>();
foreach (var p in ToolCatalog.Params)
    foreach (var v in new[] { p.Min, p.Max })
    {
        var rr = new Recipe(); rr.Adjust[p.Key] = v;
        try
        {
            using var o = PhotoEngine.Render(synth, rr);
            Cv2.MinMaxLoc(o.Color.Reshape(1), out double mn, out double mx);
            if (o.Width != 600 || double.IsNaN(mn) || mn < 0 || mx > 1) bad.Add($"{p.Key}={v}");
        }
        catch (Exception ex) { bad.Add($"{p.Key}={v}: {ex.Message}"); }
    }
Check(bad.Count == 0, $"همهٔ {ToolCatalog.Params.Count} لغزنده در کمینه و بیشینه سالم" + (bad.Count > 0 ? ": " + string.Join("، ", bad) : ""));
using (var e = R(synth, """{"adjust":{"saturation":-100}}"""))
{
    // سیاه‌وسفیدِ درست: خانهٔ آبیِ پررنگ باید تیره بماند (روشنایی)، نه روشن مثلِ V
    var blue = e.Color.At<Vec3f>(50, 475);
    Check(blue.Item1 < 0.45, $"اشباع −۱۰۰ بر پایهٔ روشنایی (خانهٔ آبی ⇒ {blue.Item1:0.00}؛ با V می‌شد ۰٫۸۵)");
}
var badPresets = new List<string>();
foreach (var ps in Presets.All)
{
    try
    {
        using var o = PhotoEngine.Render(synth, ps.Recipe);
        Cv2.MinMaxLoc(o.Color.Reshape(1), out double mn, out double mx);
        if (double.IsNaN(mn) || mn < 0 || mx > 1 || ps.Recipe.Adjust.Count == 0) badPresets.Add(ps.Key);
    }
    catch (Exception ex) { badPresets.Add($"{ps.Key}: {ex.Message}"); }
}
Check(badPresets.Count == 0, $"{Presets.All.Count} فیلترِ آماده سالم ({string.Join("، ", Presets.All.Select(p => p.Title))})" + (badPresets.Count > 0 ? " — خراب: " + string.Join("، ", badPresets) : ""));

// ───────────── ۳. خودکار ─────────────
Section("۳. تنظیمِ خودکارِ رایگان");
using (var dark = Darkened(synth, 2.4))
{
    var a = Analysis.Auto(Analysis.Measure(dark));
    using var fixedImg = PhotoEngine.Render(dark, a.Recipe);
    Check(a.Recipe.Get("exposure") > 0.3 && Lum(fixedImg.Color) > Lum(dark.Color) * 1.4,
        $"عکسِ تیره ⇒ نوردهی +{a.Recipe.Get("exposure"):0.00} (روشنایی {Lum(dark.Color):0.00} ⇒ {Lum(fixedImg.Color):0.00})");
}
using (var cast = Cast(synth, 1.35, 1.0, 0.75))
{
    var a = Analysis.Auto(Analysis.Measure(cast));
    using var fixedImg = PhotoEngine.Render(cast, a.Recipe);
    var g0 = cast.Color.At<Vec3f>(300, 450); var g1 = fixedImg.Color.At<Vec3f>(300, 450);
    Check(Math.Abs(g1.Item2 - g1.Item0) < Math.Abs(g0.Item2 - g0.Item0) * 0.5,
        $"ته‌رنگِ قرمز ⇒ دما {a.Recipe.Get("temperature"):0}؛ خاکستری R−B {g0.Item2 - g0.Item0:0.00} ⇒ {g1.Item2 - g1.Item0:0.00}");
}

// ───────────── ۴. عکس‌های نمونه ─────────────
Section("۴. عکس‌های نمونه (samples)");
var samples = Path.Combine(root, "samples");
PhotoImage? pliers = null;
foreach (var f in Directory.Exists(samples) ? Directory.GetFiles(samples, "*.jpg") : Array.Empty<string>())
{
    using var img = PhotoIO.Decode(File.ReadAllBytes(f));
    var sw = Stopwatch.StartNew();
    var st = Analysis.Measure(img);
    var a = Analysis.Auto(st);
    var tMeasure = sw.ElapsedMilliseconds;
    using var prev = img.Downscaled(1600);
    sw.Restart();
    using var p1 = PhotoEngine.Render(prev, a.Recipe, prev.Width / (double)img.Width);
    var tPrev = sw.ElapsedMilliseconds;
    sw.Restart();
    using var full = PhotoEngine.Render(img, a.Recipe);
    var tFull = sw.ElapsedMilliseconds;
    Save(full, "auto_" + Path.GetFileNameWithoutExtension(f) + ".jpg");
    Check(true, $"{Path.GetFileName(f)} {img.Width}×{img.Height}: سنجش {tMeasure}ms، پیش‌نمایش {tPrev}ms، اندازهٔ اصلی {tFull}ms — {string.Join(" ", a.Notes)}");
    // همهٔ ابزارها با هم (بدترین حالتِ پیش‌نمایش)
    var allTools = Recipe.Parse("""{"adjust":{"exposure":0.3,"highlights":-40,"shadows":40,"clarity":30,"texture":20,"dehaze":20,"vibrance":20,"noiseLuma":30,"noiseColor":30,"sharpen":50,"sharpenMasking":30,"vignette":-20,"grain":20,"distortion":10,"redSat":10},"crop":{"angle":2}}""");
    sw.Restart();
    using var h1 = PhotoEngine.Render(prev, allTools, prev.Width / (double)img.Width);
    Check(sw.ElapsedMilliseconds < 4000, $"   همهٔ ابزارها با هم روی پیش‌نمایشِ {prev.Width}px: {sw.ElapsedMilliseconds}ms");
    if (Path.GetFileName(f) == "pliers.jpg") pliers = img.Clone();
}
foreach (var f in Arg("--photos") is { } dir && Directory.Exists(dir) ? Directory.GetFiles(dir) : Array.Empty<string>())
{
    try
    {
        using var img = PhotoIO.Decode(File.ReadAllBytes(f));
        var a = Analysis.Auto(Analysis.Measure(img));
        using var full = PhotoEngine.Render(img, a.Recipe);
        Save(full, "auto_" + Path.GetFileNameWithoutExtension(f) + ".jpg");
        Console.WriteLine($"    {Path.GetFileName(f)}: {string.Join(" ", a.Notes)}");
    }
    catch (InvalidDataException) { }
}

// ───────────── ۵. حذفِ پس‌زمینه ─────────────
Section("۵. حذفِ پس‌زمینه: روشِ سبک (بی مدل) و تمیزیِ لبه");
{
    // دایرهٔ آبی روی سفید: ماسکِ دقیق ⇒ بی هاله؛ ماسکِ گشاد (سفید دورش مانده) ⇒ هاله، و تمیزکاری کمش می‌کند
    using var disc = new Mat(300, 300, MatType.CV_32FC3, Scalar.All(1));
    Cv2.Circle(disc, new Point(150, 150), 80, new Scalar(0.8, 0.3, 0.1), -1, LineTypes.AntiAlias);
    using var exact = new Mat(300, 300, MatType.CV_32FC1, Scalar.All(0));
    Cv2.Circle(exact, new Point(150, 150), 80, Scalar.All(1), -1, LineTypes.AntiAlias);
    using var loose0 = new Mat(300, 300, MatType.CV_32FC1, Scalar.All(0));
    Cv2.Circle(loose0, new Point(150, 150), 84, Scalar.All(1), -1, LineTypes.AntiAlias);
    using var loose = new Mat(); Cv2.GaussianBlur(loose0, loose, new Size(0, 0), 3);
    var good = Matte.Report(disc, exact, 0);
    var dirty = Matte.Report(disc, loose, 0);
    var auto = Matte.AutoCleanup(disc, loose);
    Check(good.HaloPercent < 3, $"ماسکِ دقیق ⇒ هاله {good.HaloPercent:0.0}%");
    Check(dirty.HaloPercent > 10 && auto.HaloPercent < dirty.HaloPercent / 2,
        $"ماسکِ گشاد ⇒ هاله {dirty.HaloPercent:0.0}%؛ تمیزکاریِ خودکار ({auto.Cleanup:0}) ⇒ {auto.HaloPercent:0.0}%");
}
{
    // سه کالا روی زمینهٔ استودیوییِ شیب‌دار با سایهٔ نرم: بطریِ آبی، حلقهٔ قرمز (سوراخ دارد)، جعبهٔ خاکستری
    var (img, truth) = Studio(900, 700);
    var mem0 = Mem();
    var sw = Stopwatch.StartNew();
    var q = QuickMatte.Mask(img);
    var t = sw.ElapsedMilliseconds;
    var iou = IoU(q.Alpha, truth);
    Check(q.PlainBackground && q.Confidence >= 0.6 && iou > 0.95,
        $"زمینهٔ شیب‌دار ⇒ هم‌پوشانی با جوابِ درست {iou:P1}، اطمینان {q.Confidence:0.00}، {t}ms، حافظه +{Math.Max(0, Mem() - mem0)}MB");
    using (var sh = new Mat(q.Alpha, new Rect(160, 556, 180, 40)))
        Check(Cv2.Mean(sh).Val0 < 0.25, $"سایهٔ نرمِ زیرِ بطری جزوِ کالا نشد (ماسک در سایه {Cv2.Mean(sh).Val0:0.00})");
    Check(q.Alpha.At<float>(300, 620) < 0.2, $"سوراخِ حلقه زمینه ماند ({q.Alpha.At<float>(300, 620):0.00})");
    using (var box = new Mat(q.Alpha, new Rect(520, 500, 200, 60)))
        Check(Cv2.Mean(box).Val0 > 0.9, $"جعبهٔ خاکستری (هم‌رنگِ سایه) کالا ماند ({Cv2.Mean(box).Val0:0.00})");
    using var both = new PhotoImage(img.Clone(), q.Alpha.Clone());
    using var onBlack = Output.Finalize(both, Recipe.Parse("""{"background":{"remove":true,"color":"#000000"}}"""), null, false);
    Save(onBlack, "studio_quick_on_black.jpg");
    q.Alpha.Dispose(); img.Dispose(); truth.Dispose();
}
{
    // زمینهٔ شلوغ ⇒ روشِ سبک خودش می‌گوید مطمئن نیست (تا auto سراغِ مدل برود)
    using var busy = new Mat(500, 500, MatType.CV_32FC3);
    Cv2.Randu(busy, Scalar.All(0), Scalar.All(1));
    using var busyB = Blur(busy, 4);
    Cv2.Normalize(busyB, busyB, 0, 1, NormTypes.MinMax);
    Cv2.Circle(busyB, new Point(250, 250), 120, new Scalar(0.1, 0.2, 0.9), -1);
    var q = QuickMatte.Mask(busyB);
    Check(!q.PlainBackground && q.Confidence < 0.6, $"زمینهٔ شلوغ ⇒ «ساده نیست»، اطمینان {q.Confidence:0.00} — {q.Note}");
    q.Alpha.Dispose();
}
if (pliers is not null)
{
    var mem0 = Mem();
    var sw = Stopwatch.StartNew();
    var q = QuickMatte.Mask(pliers.Color);
    var t = sw.ElapsedMilliseconds;
    var refFile = Path.Combine(samples, "pliers.mask-birefnet.png");
    var iouText = "";
    double iou = 1;
    if (File.Exists(refFile))
    {
        using var r8 = Cv2.ImRead(refFile, ImreadModes.Grayscale);
        using var rf = new Mat(); r8.ConvertTo(rf, MatType.CV_32FC1, 1 / 255.0);
        iou = IoU(q.Alpha, rf);
        iouText = $"، هم‌پوشانی با ماسکِ BiRefNet (ذخیره‌شده) {iou:P1}";
    }
    Check(q.PlainBackground && iou > 0.9, $"انبردست (کروم روی سفید، روشِ سبک): {t}ms، حافظه +{Math.Max(0, Mem() - mem0)}MB، اطمینان {q.Confidence:0.00}{iouText}");
    using var m8 = new Mat(); q.Alpha.ConvertTo(m8, MatType.CV_8UC1, 255);
    Cv2.ImWrite(Path.Combine(outDir, "pliers_quick_mask.png"), m8);
    var edge = Matte.AutoCleanup(pliers.Color, q.Alpha);
    Check(edge.Clean, $"لبه روی رنگِ مخالف: هاله {edge.HaloPercent:0.0}% (تمیزکاری {edge.Cleanup:0})؛ امتحان‌شده: {string.Join("، ", edge.Tried.Select(x => $"{x.Cleanup:0}⇒{x.Halo:0.0}%"))}");
    // روی سیاه و سفید (روشِ وارسیِ لبه: سفید بوده ⇒ روی سیاه هاله پیدا است)
    foreach (var (name, col) in new[] { ("black", "#000000"), ("white", "#ffffff") })
    {
        using var withMask = new PhotoImage(pliers.Color.Clone(), q.Alpha.Clone());
        var rr = Recipe.Parse("{\"background\":{\"remove\":true,\"color\":\"" + col + "\"},\"output\":{\"square\":true,\"padding\":0.08,\"longEdge\":800}}");
        using var o = Output.Finalize(withMask, rr, null, false);
        Save(o, $"pliers_on_{name}.jpg");
        Check(o.Width == 800 && o.Height == 800 && o.Alpha is null, $"روی {(name == "black" ? "سیاه" : "سفید")}، قابِ مربعِ ۸۰۰ ⇒ pliers_on_{name}.jpg");
    }
    using (var withMask = new PhotoImage(pliers.Color.Clone(), q.Alpha.Clone()))
    using (var o = Output.Finalize(withMask, Recipe.Parse("""{"background":{"remove":true,"color":"transparent"},"output":{"format":"png"}}"""), null, false))
    {
        Save(o, "pliers_transparent.png");
        Check(o.Alpha is not null, "بی‌پس‌زمینه (شفاف) ⇒ pliers_transparent.png");
    }
    q.Alpha.Dispose();
}
using (var remover = new BackgroundRemover(models.Background) { RequiredMemoryMB = int.MaxValue })
    Check(!remover.CanRun(out var why) && why.Length > 0, "نگهبانِ حافظه: مدلِ سنگین با حافظهٔ کم اجرا نمی‌شود — «" + why + "»");
if (heavy)
{
    using var remover = new BackgroundRemover(models.Background);
    if (!remover.CanRun(out var why)) Console.WriteLine("  – BiRefNet اجرا نشد: " + why);
    else if (pliers is not null)
    {
        using var mask = remover.Mask(pliers.Color);
        var cover = Cv2.Mean(mask).Val0;
        Check(cover is > 0.03 and < 0.7, $"BiRefNet: ماسکِ انبردست در {remover.LastSeconds:0.0} ثانیه، {cover:P0} از عکس");
    }
}
else Console.WriteLine("  – مدلِ سنگینِ BiRefNet اجرا نشد (فقط با --heavy و روی سرورِ پرحافظه).");

// ───────────── ۶. بزرگ‌نمایی ─────────────
Section("۶. بزرگ‌نماییِ هوشمند (Real-ESRGAN)");
using var up = new Upscaler(models.Upscale);
Check(up.Available, "مدل: " + models.Upscale);
if (heavy && up.Available && pliers is not null)
{
    using var crop = new Mat(pliers.Color, new Rect(pliers.Width / 2 - 100, pliers.Height / 2 - 75, 200, 150)).Clone();
    using var x4 = up.Upscale(crop, 4);
    Check(x4.Cols == 800 && x4.Rows == 600, $"×۴: ۲۰۰×۱۵۰ ⇒ {x4.Cols}×{x4.Rows} در {up.LastSeconds:0.0} ثانیه");
    using var x2 = up.Upscale(crop, 2);
    Check(x2.Cols == 400 && x2.Rows == 300, $"×۲: ⇒ {x2.Cols}×{x2.Rows}");
    using var lanczos = new Mat(); Cv2.Resize(crop, lanczos, new Size(800, 600), 0, 0, InterpolationFlags.Lanczos4);
    Check(LapVar(x4) > LapVar(lanczos), $"تیزتر از بزرگ‌نماییِ معمولی (لاپلاسین {LapVar(lanczos):0.00000} ⇒ {LapVar(x4):0.00000})");
    File.WriteAllBytes(Path.Combine(outDir, "upscale_x4.jpg"), PhotoIO.Encode(new PhotoImage(x4.Clone()), "jpeg", 92));
    File.WriteAllBytes(Path.Combine(outDir, "upscale_lanczos.jpg"), PhotoIO.Encode(new PhotoImage(lanczos.Clone()), "jpeg", 92));
}
else Console.WriteLine("  – اجرا نشد (پردازنده را چند ثانیه کامل می‌گیرد؛ با --heavy).");

// ───────────── ۷. ویرایشگرِ هوشمند (سرویسِ ساختگی) ─────────────
Section("۷. ویرایشگرِ هوشمند (بی اینترنت: سرویسِ ساختگی)");
{
    var fake = new FakeAi();
    var agent = new VisionAgent(new VisionAgentOptions { ApiKey = "test", Models = "fake-model", MaxRounds = 2 }, fake);
    using var work = synth.Downscaled(512);
    var st = Analysis.Measure(synth);
    var res = await agent.EditAsync(work, st, Analysis.Auto(st), "عکسِ کالا برای فروشگاه", new Recipe(), r => PhotoEngine.Render(work, r));
    Check(res.UsedAi && res.Recipe.Get("exposure") == 4 && res.Recipe.Get("shadows") == 20 && !res.Recipe.Adjust.ContainsKey("bogus")
          && res.Recipe.Background is { Remove: true } && res.Steps.Count == 2 && res.Steps[1].Done,
        $"پاسخِ نیمه‌خراب (متن دورِ JSON، عددِ بیرون از بازه، کلیدِ ناشناخته) ⇒ {res.Recipe.ToJson()}؛ دورِ دوم: «تمام»؛ توکن {res.PromptTokens}+{res.CompletionTokens}");
    Check(fake.Calls == 2 && fake.SawImages == 2 && fake.MaxImageKb < 120, $"۲ درخواست، هر بار یک عکسِ کوچک (بزرگ‌ترین {fake.MaxImageKb:0}KB)");
    var noKey = new VisionAgent(new VisionAgentOptions { ApiKey = "" });
    var fb = await noKey.EditAsync(work, st, Analysis.Auto(st), null, new Recipe(), r => PhotoEngine.Render(work, r));
    Check(!fb.UsedAi && fb.Recipe.Adjust.Count > 0, "بی کلید ⇒ تنظیمِ خودکارِ رایگان: " + fb.Notes[..Math.Min(70, fb.Notes.Length)] + "…");
}

// ───────────── ۸. کتابخانهٔ عکس و خروجی ─────────────
Section("۸. کتابخانهٔ عکس، پیش‌نمایش و خروجی (PhotoService)");
{
    var data = Path.Combine(outDir, "service");
    if (Directory.Exists(data)) Directory.Delete(data, true);
    using var svc = new PhotoService(data, models);
    var sample = Path.Combine(samples, "desk.jpg");
    if (File.Exists(sample))
    {
        var doc = svc.Create(File.ReadAllBytes(sample), "desk.jpg");
        var rec = Recipe.Parse("""{"adjust":{"exposure":0.2,"clarity":20},"output":{"longEdge":640,"format":"webp","quality":85}}""");
        svc.SaveRecipe(doc.Id, rec);
        Check(svc.LoadRecipe(doc.Id).ToJson() == rec.ToJson(), $"عکس ثبت شد ({doc.Width}×{doc.Height})، نسخه ذخیره و خوانده شد");
        var sw = Stopwatch.StartNew();
        using (var p = svc.RenderPreview(doc.Id, rec)) Check(Math.Max(p.Width, p.Height) <= 1600, $"پیش‌نمایش {p.Width}×{p.Height} در {sw.ElapsedMilliseconds}ms");
        var (bytes, fmt) = svc.Export(doc.Id, rec);
        using var back = PhotoIO.Decode(bytes);
        Check(fmt == "webp" && Math.Max(back.Width, back.Height) == 640, $"خروجی {fmt} {back.Width}×{back.Height} ({bytes.Length / 1024}KB)");
        svc.Delete(doc.Id);
        Check(svc.List().Count == 0, "پاک شد");
    }
    var pl = Path.Combine(samples, "pliers.jpg");
    if (File.Exists(pl))
    {
        var doc = svc.Create(File.ReadAllBytes(pl), "pliers.jpg");
        var sw = Stopwatch.StartNew();
        var (edge, mask, secs, computed) = svc.PrepareBackground(doc.Id);
        Check(computed && mask.Method == "quick" && svc.Get(doc.Id).HasMask,
            $"حذفِ پس‌زمینه (auto) ⇒ روشِ {mask.Method} در {secs:0.00}s، نمرهٔ لبه {edge.Score:0}، «{mask.Note}»");
        var store = Presets.Find("store")!.Recipe.Clone();
        store.Output!.LongEdge = 800;
        sw.Restart();
        using (var p = svc.RenderPreview(doc.Id, store, 900)) Check(p.Width == p.Height && p.Alpha is null, $"پیش‌نمایشِ «عکسِ فروشگاهی» {p.Width}×{p.Height} در {sw.ElapsedMilliseconds}ms");
        var (bytes, fmt) = svc.Export(doc.Id, store);
        using var back = PhotoIO.Decode(bytes);
        File.WriteAllBytes(Path.Combine(outDir, "pliers_store.jpg"), bytes);
        Check(fmt == "jpeg" && back.Width == 800 && back.Height == 800, $"خروجیِ فروشگاهی {back.Width}×{back.Height} {fmt} ⇒ pliers_store.jpg");
        Check(svc.Thumbnail(doc.Id).Length > 1000, "عکسِ کوچکِ فهرست");
        svc.DeleteMask(doc.Id);
        Check(!svc.Get(doc.Id).HasMask, "ماسک پاک شد");
        svc.Delete(doc.Id);
    }
}

Console.WriteLine();
Console.ForegroundColor = fails == 0 ? ConsoleColor.Green : ConsoleColor.Red;
Console.WriteLine(fails == 0 ? "همه درست است ✓" : $"{fails} مورد نادرست ✗");
Console.ResetColor();
return fails == 0 ? 0 : 1;

// ───────────── عکس‌های ساختگی ─────────────

// شیبِ خاکستری + شش خانهٔ رنگی (قرمز، سبز، آبی بالا؛ زرد، ارغوانی، خاکستری پایین) + متن و لبه
static PhotoImage Synthetic(int w, int h)
{
    var m = new Mat(h, w, MatType.CV_32FC3);
    for (int y = 0; y < h; y++)
        for (int x = 0; x < w; x++)
        {
            var g = 0.15f + 0.7f * x / w;
            m.Set(y, x, new Vec3f(g, g, g));
        }
    var cols = new[] { new Scalar(0.15, 0.15, 0.8), new Scalar(0.2, 0.7, 0.2), new Scalar(0.85, 0.3, 0.15),
                       new Scalar(0.1, 0.8, 0.85), new Scalar(0.7, 0.2, 0.7), new Scalar(0.5, 0.5, 0.5) };
    for (int i = 0; i < 6; i++)
    {
        int cx = i % 3 * 150 + 75 + (i % 3) * 50, cy = i / 3 * 250 + 50;
        Cv2.Rectangle(m, new Rect(cx - 50, cy - 30, 100, 60), cols[i], -1);
    }
    Cv2.PutText(m, "PersianAiKit", new Point(170, 200), HersheyFonts.HersheySimplex, 1.2, new Scalar(0.95, 0.95, 0.95), 3);
    return new PhotoImage(m);
}

static Mat Blur(Mat m, double sigma) { var d = new Mat(); Cv2.GaussianBlur(m, d, new Size(0, 0), sigma); return d; }

static double IoU(Mat a, Mat b)
{
    using var ma = new Mat(); Cv2.Threshold(a, ma, 0.5, 1, ThresholdTypes.Binary);
    using var mb = new Mat(); Cv2.Threshold(b, mb, 0.5, 1, ThresholdTypes.Binary);
    using var i = new Mat(); Cv2.Min(ma, mb, i);
    using var u = new Mat(); Cv2.Max(ma, mb, u);
    var su = Cv2.Sum(u).Val0;
    return su < 1 ? 1 : Cv2.Sum(i).Val0 / su;
}

static long Mem() => Process.GetCurrentProcess().PrivateMemorySize64 / 1048576;

// زمینهٔ استودیویی (روشن بالا، کمی تیره‌تر پایین و کناره‌ها) + سایهٔ نرم + بطریِ آبی، حلقهٔ قرمز، جعبهٔ خاکستری؛ و جوابِ درست
static (Mat Img, Mat Truth) Studio(int w, int h)
{
    var img = new Mat(h, w, MatType.CV_32FC3);
    for (int y = 0; y < h; y++)
        for (int x = 0; x < w; x++)
        {
            var nx = (x - w / 2.0) / (w / 2.0);
            var v = (float)(0.97 - 0.09 * y / h - 0.03 * nx * nx);
            img.Set(y, x, new Vec3f(v + 0.004f, v, v - 0.004f));
        }
    using (var sh = new Mat(h, w, MatType.CV_32FC1, Scalar.All(0)))
    {
        Cv2.Ellipse(sh, new Point(250, 578), new Size(120, 22), 0, 0, 360, Scalar.All(0.3), -1, LineTypes.AntiAlias);
        using var shb = Blur(sh, 10);
        using var k = new Mat(); Cv2.Subtract(Scalar.All(1), shb, k);
        using var k3 = new Mat(); Cv2.Merge(new[] { k, k, k }, k3);
        Cv2.Multiply(img, k3, img);
    }
    var truth = new Mat(h, w, MatType.CV_32FC1, Scalar.All(0));
    Cv2.Rectangle(img, new Rect(160, 150, 180, 410), new Scalar(0.75, 0.35, 0.1), -1);
    Cv2.Rectangle(truth, new Rect(160, 150, 180, 410), Scalar.All(1), -1);
    Cv2.Rectangle(img, new Rect(200, 170, 20, 370), new Scalar(0.95, 0.7, 0.5), -1);
    Cv2.Circle(img, new Point(620, 300), 87, new Scalar(0.12, 0.12, 0.8), 65, LineTypes.AntiAlias);
    Cv2.Circle(truth, new Point(620, 300), 87, Scalar.All(1), 65, LineTypes.AntiAlias);
    Cv2.Rectangle(img, new Rect(510, 490, 220, 80), Scalar.All(0.5), -1);
    Cv2.Rectangle(truth, new Rect(510, 490, 220, 80), Scalar.All(1), -1);
    using var n = new Mat(img.Size(), MatType.CV_32FC3);
    Cv2.Randn(n, Scalar.All(0), Scalar.All(0.008));
    Cv2.Add(img, n, img);
    Cv2.Max(img, Scalar.All(0), img); Cv2.Min(img, Scalar.All(1), img);
    return (img, truth);
}

static PhotoImage Noisy(PhotoImage src, double sigma)
{
    var n = new Mat(src.Color.Size(), MatType.CV_32FC3);
    Cv2.Randn(n, Scalar.All(0), Scalar.All(sigma));
    var d = new Mat(); Cv2.Add(src.Color, n, d); n.Dispose();
    Cv2.Max(d, Scalar.All(0), d); Cv2.Min(d, Scalar.All(1), d);
    return new PhotoImage(d);
}

static PhotoImage Hazy(PhotoImage src)
{
    var d = new Mat(); Cv2.AddWeighted(src.Color, 0.45, new Mat(src.Color.Size(), MatType.CV_32FC3, Scalar.All(0.85)), 0.55, 0, d);
    return new PhotoImage(d);
}

static PhotoImage Darkened(PhotoImage src, double gamma)
{
    var d = new Mat(); Cv2.Pow(src.Color, gamma, d);
    return new PhotoImage(d);
}

static PhotoImage Cast(PhotoImage src, double r, double g, double b)
{
    var d = new Mat(); Cv2.Multiply(src.Color, new Scalar(b, g, r), d);
    Cv2.Min(d, Scalar.All(1), d);
    return new PhotoImage(d);
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
            ? "Sure! Here is the recipe:\n```json\n{\"adjust\":{\"exposure\":7,\"shadows\":20,\"bogus\":5},\"background\":{\"remove\":true,\"color\":\"#ffffff\"},\"notes\":\"نور بیشتر و پس‌زمینهٔ سفید.\"}\n```"
            : "{\"done\": true, \"notes\": \"خوب است.\"}";
        var json = System.Text.Json.JsonSerializer.Serialize(new
        {
            model = "fake-model",
            choices = new[] { new { message = new { role = "assistant", content } } },
            usage = new { prompt_tokens = 1500, completion_tokens = 80 },
        });
        return new HttpResponseMessage(HttpStatusCode.OK) { Content = new StringContent(json, Encoding.UTF8, "application/json") };
    }
}
