// آزمونِ نصبِ پروژهٔ صدا — روی همین ماشین: ابزارهای متن، متن ⇒ گفتار (Piper)، گفتار ⇒ متن (Vosk)
//   dotnet run -c Release          (یا Run-SelfTest.bat)
// نمونهٔ هر صدا در data\selftestoice_*.wav
using System.Diagnostics;
using PersianAiKit;
using PersianAiKit.Asr;
using PersianAiKit.Text;
using PersianAiKit.Tts;

Console.OutputEncoding = System.Text.Encoding.UTF8;
string? Arg(string name) { var i = Array.IndexOf(args, name); return i >= 0 && i + 1 < args.Length ? args[i + 1] : null; }

var paths = VoiceModels.Find(Arg("--models"));
var outDir = Arg("--out") ?? Path.Combine(Path.GetDirectoryName(paths.Root)!, "data", "selftest");
Directory.CreateDirectory(outDir);
Console.WriteLine($"مدل‌ها: {paths.Root}");
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

// ───────────── ۱. متن ─────────────
Section("۱. ابزارهای متن");
Check(PersianText.NumberWords(25045) == "بیست و پنج هزار و چهل و پنج", "۲۵۰۴۵ ⇒ " + PersianText.NumberWords(25045));
Check(PersianText.NumberWords(1400) == "هزار و چهارصد", "۱۴۰۰ ⇒ " + PersianText.NumberWords(1400));
var sp = PersianText.ToSpeakable("ساعت 10:30 روی INJ8 مقدار 2.5 kg");
Check(sp == "ساعت ده و نیم روی آی اِن جِی هشت مقدار دو و نیم کیلوگرم", "خواندنی: " + sp);
sp = PersianText.ToSpeakable("تاریخ ۱۴۰۵/۰۷/۰۵، پیشرفت ۲۰٪، مبلغ 25,000");
Check(sp == "تاریخ پنجم مهر هزار و چهارصد و پنج، پیشرفت بیست درصد، مبلغ بیست و پنج هزار", "خواندنی: " + sp);
var wd = PersianText.WordsToDigits("کار اول صد و بیست و پنج تا زدم");
Check(wd == "کار اول 125 تا زدم", "حروف ⇒ رقم: " + wd);
var nums = PersianText.ExtractNumbers("دو هزار و پونصد تا در سه و نیم ساعت");
Check(nums.SequenceEqual(new[] { 2500d, 3.5 }), "عددها: " + string.Join("، ", nums));
Check(PersianText.ExtractNumbers("نه، نرسیدم").Count == 0, "«نه، نرسیدم» عدد ندارد");
Check(PersianText.ExtractNumbers("بیست پنج تا").SequenceEqual(new[] { 25d }), "«بیست پنج تا» (بی «و») ⇒ ۲۵");
var cmds = new[] { "روشن کن", "خاموش کن", "نه" };
Check(PersianText.FindPhrase("دستگاه را روشن کنید", cmds) == "روشن کن" && PersianText.FindPhrase("چراغ را خاموش کنی", cmds) == "خاموش کن"
      && PersianText.FindPhrase("امروز هوا گرم است", cmds) is null
      && PersianText.FindPhrase("نهار خوردم", cmds) is null, "پیدا کردنِ فرمان در متن («روشن کنید» ⇒ «روشن کن»؛ «نهار» ≠ «نه»)");

// ───────────── ۲. متن ⇒ گفتار ─────────────
Section("۲. متن ⇒ گفتار (Piper)");
var tts = new PiperTts(paths);
Check(tts.Available, $"piper و صداها: {string.Join("، ", tts.Voices())}");
byte[]? wav = null;
const string Sentence = "سلام. امروز ساعت 10:30 روی دستگاه INJ8 مقدار 250 عدد قطعه تولید کنید.";
if (tts.Available)
{
    var sw = Stopwatch.StartNew();
    wav = await tts.SpeakAsync(Sentence);
    var t1 = sw.Elapsed.TotalSeconds;
    var d1 = WavFile.Duration(wav);
    await File.WriteAllBytesAsync(Path.Combine(outDir, "tts_sample.wav"), wav);
    Check(d1 > 2, $"ساخته شد: {d1:0.0} ثانیه صدا در {t1:0.0} ثانیه ⇒ tts_sample.wav");
    // Piper هر بار کمی متفاوت می‌سازد (±۰٫۵ ثانیه) ⇒ فاصلهٔ سرعت‌ها بزرگ گرفته شد
    var slow = await tts.SpeakAsync(Sentence, speed: 1.6);
    Check(WavFile.Duration(slow) > d1 * 1.2, $"سرعتِ ۱٫۶ آرام‌تر است ({WavFile.Duration(slow):0.0} ثانیه)");
    foreach (var v in tts.Voices())
        await File.WriteAllBytesAsync(Path.Combine(outDir, $"voice_{v}.wav"), await tts.SpeakAsync("این صدای من است. عدد 1405.", v));
    Console.WriteLine($"    نمونهٔ هر صدا: voice_*.wav در {outDir}");
}

// ───────────── ۳. گفتار ⇒ متن ─────────────
Section("۳. گفتار ⇒ متن (Vosk)");
using var asr = new VoskAsr(paths);
Check(Directory.Exists(asr.ModelDir), "مدل: " + asr.ModelDir);
if (Directory.Exists(asr.ModelDir))
{
    var sw = Stopwatch.StartNew();
    var testWav = Path.Combine(asr.ModelDir, "test", "test.wav");
    if (File.Exists(testWav))
    {
        var r0 = await asr.RecognizeFileAsync(testWav);
        Console.WriteLine($"    بارِ مدل + نخستین فایل: {sw.Elapsed.TotalSeconds:0.0} ثانیه");
        var expect = File.ReadAllText(Path.Combine(asr.ModelDir, "test", "test.txt")).Trim();
        // «کارو» و «کار رو» یکی‌اند ⇒ مقایسه بی‌فاصله، نویسه‌به‌نویسه
        Check(Cer(expect, r0.Text) <= 0.15, $"فایلِ نمونهٔ مدل: «{r0.Text}» (متنِ همراهِ مدل: «{expect}»)");
    }
    if (wav is not null)
    {
        sw.Restart();
        var r = await asr.RecognizeWavAsync(wav);
        var expect = PersianText.ToSpeakable(Sentence);
        var wer = Wer(expect, r.Text);
        Check(wer <= 0.3, $"صدای Piper ⇒ متن در {sw.Elapsed.TotalSeconds:0.0} ثانیه، خطای واژه {wer:P0}:\n      شنید: «{r.Text}»\n      گفته: «{expect}»");
        Check(r.Words.Count > 0 && r.Words.All(w => w.End >= w.Start), $"زمانِ هر واژه: {string.Join(" ", r.Words.Take(4).Select(w => $"{w.Word}@{w.Start:0.0}s"))}…");
        Check(PersianText.ExtractNumbers(r.Text).Contains(250), "عددِ ۲۵۰ از متنِ شنیده درآمد: " + PersianText.WordsToDigits(r.Text));

        // جریانِ زنده: همان صدا تکه‌تکه ⇒ همان متن
        using (var stream = asr.CreateStream())
        {
            WavFile.TryReadMono(wav, out var pcm, out var rate);
            var mono16 = WavFile.Resample(pcm, rate, VoskAsr.SampleRate);
            var bytes = new byte[mono16.Length * 2];
            Buffer.BlockCopy(mono16, 0, bytes, 0, bytes.Length);
            var chunk = new byte[3200];   // ۰٫۱ ثانیه
            var partials = 0;
            for (var i = 0; i < bytes.Length; i += chunk.Length)
            {
                var n = Math.Min(chunk.Length, bytes.Length - i);
                Buffer.BlockCopy(bytes, i, chunk, 0, n);
                stream.Accept(chunk, n);
                if (stream.Partial.Length > 0) partials++;
            }
            var full = stream.Finish();
            Check(Wer(r.Text, full) <= 0.1 && partials > 0, $"جریانِ زنده (تکه‌های ۰٫۱ثانیه‌ای، {partials} متنِ نیمه‌کاره): «{full}»");
        }

        // فرمانِ صوتی: آزاد بشنو، بعد فرمان را در متن پیدا کن — حرفِ بی‌ربط به هیچ فرمانی نخورد
        var commands = new[] { "روشن کن", "خاموش کن", "بله", "نه" };
        var cmd = await asr.RecognizeWavAsync(await tts.SpeakAsync("لطفا چراغ را خاموش کنید"));
        Check(PersianText.FindPhrase(cmd.Text, commands) == "خاموش کن", $"فرمان در حرفِ آزاد: «{cmd.Text}» ⇒ {PersianText.FindPhrase(cmd.Text, commands)}");
        Check(PersianText.FindPhrase(r.Text, commands) is null, "حرفِ بی‌ربط ⇒ هیچ فرمانی");
        // حالتِ سخت‌گیر: فقط همین واژه‌ها (برای پاسخِ کوتاهِ بله/نه)
        var strict = await asr.RecognizeWavAsync(await tts.SpeakAsync("روشن کن"), commands);
        Check(strict.Text == "روشن کن", $"حالتِ سخت‌گیر: «{strict.Text}»");
    }
}

Console.WriteLine();
Console.ForegroundColor = fails == 0 ? ConsoleColor.Green : ConsoleColor.Red;
Console.WriteLine(fails == 0 ? "همه درست است ✓" : $"{fails} مورد نادرست ✗");
Console.ResetColor();
return fails == 0 ? 0 : 1;

// ─────────────────────────────────────────────

// خطای واژه و خطای نویسه (Levenshtein روی متنِ نرمال‌شده)
static double Wer(string expected, string heard) => Distance(
    PersianText.Normalize(expected).Split(' ', StringSplitOptions.RemoveEmptyEntries),
    PersianText.Normalize(heard).Split(' ', StringSplitOptions.RemoveEmptyEntries));

static double Cer(string expected, string heard) => Distance(
    PersianText.Normalize(expected).Replace(" ", "").Select(c => c.ToString()).ToArray(),
    PersianText.Normalize(heard).Replace(" ", "").Select(c => c.ToString()).ToArray());

static double Distance(string[] a, string[] b)
{
    if (a.Length == 0) return b.Length == 0 ? 0 : 1;
    var d = new int[a.Length + 1, b.Length + 1];
    for (var i = 0; i <= a.Length; i++) d[i, 0] = i;
    for (var j = 0; j <= b.Length; j++) d[0, j] = j;
    for (var i = 1; i <= a.Length; i++)
        for (var j = 1; j <= b.Length; j++)
            d[i, j] = Math.Min(Math.Min(d[i - 1, j] + 1, d[i, j - 1] + 1), d[i - 1, j - 1] + (a[i - 1] == b[j - 1] ? 0 : 1));
    return (double)d[a.Length, b.Length] / a.Length;
}
