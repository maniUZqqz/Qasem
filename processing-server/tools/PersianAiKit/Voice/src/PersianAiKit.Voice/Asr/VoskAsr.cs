using System.Reflection;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.Encodings.Web;
using System.Text.Json;
using Vosk;

namespace PersianAiKit.Asr;

/// <param name="Text">متنِ شنیده‌شده (بی‌نقطه‌گذاری؛ عددها با حروف — برای رقم <see cref="Text.PersianText.WordsToDigits"/>).</param>
/// <param name="Seconds">درازای صدا.</param>
/// <param name="Words">هر واژه با زمانِ شروع/پایان و اطمینان (۰ تا ۱).</param>
public sealed record AsrResult(string Text, double Seconds, IReadOnlyList<AsrWord> Words)
{
    public bool IsEmpty => string.IsNullOrWhiteSpace(Text);
}

public sealed record AsrWord(string Word, double Start, double End, double Confidence);

/// <summary>
/// گفتار ⇒ متنِ فارسی، آفلاین، با Vosk (https://alphacephei.com/vosk، Apache-2.0) و مدلِ کوچکِ فارسی
/// vosk-model-small-fa-0.42 (~۵۰MB). ورودی: WAVِ PCMِ ۱۶بیتی با هر نرخ و هر تعداد کانال (خودش تک‌کاناله و ۱۶kHz می‌کند).
/// بارِ مدل چند ثانیه است — <see cref="Warm"/> را در شروعِ برنامه صدا بزنید. امن برای استفادهٔ هم‌زمان (singleton).
/// </summary>
public sealed class VoskAsr : IDisposable
{
    public const int SampleRate = 16000;
    private readonly string _modelDir;
    private readonly Action<string>? _log;
    private readonly SemaphoreSlim _gate;
    private readonly object _loadLock = new();
    private Model? _model;
    private string? _loadError;

    public VoskAsr(string modelDir, int maxConcurrent = 2, Action<string>? log = null)
    {
        _modelDir = Path.GetFullPath(modelDir);
        _log = log;
        _gate = new SemaphoreSlim(Math.Max(1, maxConcurrent));
    }

    public VoskAsr(VoiceModels paths, int maxConcurrent = 2, Action<string>? log = null) : this(paths.VoskModelDir, maxConcurrent, log) { }

    public string ModelDir => _modelDir;

    public bool Available => Directory.Exists(_modelDir) && _loadError is null;

    /// <summary>بارِ مدل در پس‌زمینه تا نخستین درخواست منتظر نماند.</summary>
    public void Warm() => _ = Task.Run(() => { try { Load(); } catch { } });

    private Model Load()
    {
        if (_model is not null) return _model;
        lock (_loadLock)
        {
            if (_model is not null) return _model;
            if (!Directory.Exists(_modelDir)) throw new DirectoryNotFoundException("مدلِ Vosk نیست: " + _modelDir);
            try
            {
                Vosk.Vosk.SetLogLevel(-1);
                _model = new Model(_modelDir);
                _log?.Invoke("مدلِ گفتار‌به‌متن آماده شد: " + _modelDir);
                return _model;
            }
            catch (Exception ex)
            {
                _loadError = ex.Message;
                throw new InvalidOperationException("مدلِ Vosk بار نشد: " + ex.Message, ex);
            }
        }
    }

    /// <summary>WAV ⇒ متن.</summary>
    /// <param name="strictPhrases">
    /// حالتِ سخت‌گیر (اختیاری): هر صدایی به یکی از همین واژه‌ها/جمله‌ها نسبت داده می‌شود — حتی حرفِ بی‌ربط (آزمون: «سفارش ۱۲۵۰ آماده است»
    /// با فهرستِ «بله/نه/روشن کن/خاموش کن» شد «خاموش روشن کن…»). فقط وقتی گوینده جز این‌ها چیزی نمی‌گوید (پاسخِ بله/نه به یک پرسش).
    /// برای فرمان در میانِ حرفِ آزاد: بی این پارامتر بشنوید و <see cref="Text.PersianText.FindPhrase"/> را روی متن صدا بزنید.
    /// </param>
    /// <exception cref="ArgumentException">فایل WAVِ PCMِ ۱۶بیتی نیست.</exception>
    public Task<AsrResult> RecognizeWavAsync(byte[] wav, IEnumerable<string>? strictPhrases = null, CancellationToken ct = default)
    {
        if (!WavFile.TryReadMono(wav, out var pcm, out var rate))
            throw new ArgumentException("فقط WAVِ PCMِ ۱۶بیتی پذیرفته است (mp3/ogg/webm را اول با ffmpeg به WAV کنید).", nameof(wav));
        return RecognizePcmAsync(pcm, rate, strictPhrases, ct);
    }

    public async Task<AsrResult> RecognizeFileAsync(string wavPath, IEnumerable<string>? strictPhrases = null, CancellationToken ct = default) =>
        await RecognizeWavAsync(await File.ReadAllBytesAsync(wavPath, ct), strictPhrases, ct);

    /// <summary>نمونه‌های تک‌کاناله (هر نرخی) ⇒ متن.</summary>
    public async Task<AsrResult> RecognizePcmAsync(short[] mono, int sampleRate, IEnumerable<string>? strictPhrases = null, CancellationToken ct = default)
    {
        var grammar = GrammarJson(strictPhrases);
        await _gate.WaitAsync(ct);
        try
        {
            return await Task.Run(() =>
            {
                var samples = sampleRate == SampleRate ? mono : WavFile.Resample(mono, sampleRate, SampleRate);
                using var rec = NewRecognizer(grammar);
                var bytes = new byte[samples.Length * 2];
                Buffer.BlockCopy(samples, 0, bytes, 0, bytes.Length);
                var chunk = new byte[8000];
                for (var i = 0; i < bytes.Length; i += chunk.Length)
                {
                    ct.ThrowIfCancellationRequested();
                    var n = Math.Min(chunk.Length, bytes.Length - i);
                    Buffer.BlockCopy(bytes, i, chunk, 0, n);
                    rec.AcceptWaveform(chunk, n);
                }
                return Parse(rec.FinalResult(), samples.Length / (double)SampleRate);
            }, ct);
        }
        finally
        {
            _gate.Release();
        }
    }

    /// <summary>
    /// گوش دادنِ پیوسته (زیرنویسِ زنده، فرمانِ صوتی): تکه‌تکه صدا بدهید، متنِ نیمه‌کاره را همان لحظه بگیرید.
    /// هر جریان یک شناساگرِ جداست؛ بعد از کار Dispose کنید.
    /// </summary>
    public AsrStream CreateStream(IEnumerable<string>? strictPhrases = null) => new(NewRecognizer(GrammarJson(strictPhrases)));

    private VoskRecognizer NewRecognizer(string? grammar)
    {
        var model = Load();
        var rec = grammar is null ? new VoskRecognizer(model, SampleRate) : NewGrammarRecognizer(model, grammar);
        rec.SetWords(true);
        return rec;
    }

    // ⚠ سازندهٔ VoskRecognizer(model, rate, grammar) در بسته‌ی C# متن را ANSI می‌فرستد ⇒ روی ویندوز هر حرفِ فارسی «?» می‌شد و
    //   Vosk همهٔ واژه‌ها را «نیست در واژه‌نامه» رد می‌کرد (آزمون گرفت). پس همان تابعِ بومی با بایت‌های UTF-8 صدا زده می‌شود.
    [DllImport("libvosk", EntryPoint = "vosk_recognizer_new_grm", CallingConvention = CallingConvention.Cdecl)]
    private static extern IntPtr NativeNewGrammarRecognizer(HandleRef model, float sampleRate, byte[] grammarUtf8);

    private static readonly MethodInfo ModelHandle =
        typeof(Model).GetMethod("getCPtr", BindingFlags.NonPublic | BindingFlags.Static) ?? throw new MissingMethodException("Vosk.Model.getCPtr");

    private static VoskRecognizer NewGrammarRecognizer(Model model, string grammar)
    {
        var ptr = NativeNewGrammarRecognizer((HandleRef)ModelHandle.Invoke(null, new object[] { model })!, SampleRate,
            Encoding.UTF8.GetBytes(grammar + "\0"));
        if (ptr == IntPtr.Zero) throw new InvalidOperationException("شناساگرِ Vosk با فهرستِ واژه‌ها ساخته نشد.");
        return (VoskRecognizer)Activator.CreateInstance(typeof(VoskRecognizer), BindingFlags.NonPublic | BindingFlags.Instance,
            null, new object[] { ptr }, null)!;
    }

    private static string? GrammarJson(IEnumerable<string>? phrases)
    {
        var list = phrases?.Select(p => p?.Trim()).Where(p => !string.IsNullOrEmpty(p)).Distinct().ToList();
        if (list is null || list.Count == 0) return null;
        list.Add("[unk]");
        // بی این Encoder واژه‌های فارسی به شکلِ ر… نوشته می‌شوند و Vosk آن‌ها را نمی‌شناسد
        return JsonSerializer.Serialize(list, new JsonSerializerOptions { Encoder = JavaScriptEncoder.UnsafeRelaxedJsonEscaping });
    }

    internal static AsrResult Parse(string json, double seconds)
    {
        using var doc = JsonDocument.Parse(json);
        var root = doc.RootElement;
        var words = new List<AsrWord>();
        if (root.TryGetProperty("result", out var arr) && arr.ValueKind == JsonValueKind.Array)
            foreach (var w in arr.EnumerateArray())
            {
                var word = w.TryGetProperty("word", out var x) ? x.GetString() ?? "" : "";
                if (word == "[unk]" || word.Length == 0) continue;
                words.Add(new AsrWord(word,
                    w.TryGetProperty("start", out var s) ? s.GetDouble() : 0,
                    w.TryGetProperty("end", out var e) ? e.GetDouble() : 0,
                    w.TryGetProperty("conf", out var c) ? c.GetDouble() : 1));
            }
        var text = root.TryGetProperty("text", out var t) ? t.GetString() ?? "" : "";
        text = string.Join(' ', text.Split(' ', StringSplitOptions.RemoveEmptyEntries).Where(w => w != "[unk]"));
        return new AsrResult(text, Math.Round(seconds, 2), words);
    }

    public void Dispose()
    {
        _model?.Dispose();
        _model = null;
    }
}

/// <summary>جریانِ گوش دادن. <see cref="Accept"/> با تکه‌های PCMِ ۱۶بیتیِ ۱۶kHz تک‌کاناله.</summary>
public sealed class AsrStream : IDisposable
{
    private readonly VoskRecognizer _rec;
    private readonly List<string> _done = new();
    private long _bytes;

    internal AsrStream(VoskRecognizer rec) => _rec = rec;

    /// <summary>
    /// یک تکه صدا. برمی‌گرداند: جمله‌ای که همین حالا تمام شد (بعد از مکث)، یا null. متنِ نیمه‌کاره در <see cref="Partial"/>.
    /// </summary>
    public string? Accept(byte[] pcm16, int count)
    {
        _bytes += count;
        if (!_rec.AcceptWaveform(pcm16, count)) return null;
        var r = VoskAsr.Parse(_rec.Result(), 0).Text;
        if (r.Length == 0) return null;
        _done.Add(r);
        return r;
    }

    /// <summary>متنِ جملهٔ در حالِ گفتن (هنوز تمام نشده).</summary>
    public string Partial
    {
        get
        {
            using var doc = JsonDocument.Parse(_rec.PartialResult());
            return doc.RootElement.TryGetProperty("partial", out var p) ? p.GetString() ?? "" : "";
        }
    }

    /// <summary>پایان: کلِ متن (همهٔ جمله‌ها).</summary>
    public string Finish()
    {
        var last = VoskAsr.Parse(_rec.FinalResult(), 0).Text;
        if (last.Length > 0) _done.Add(last);
        return string.Join(' ', _done);
    }

    public double Seconds => _bytes / 2.0 / VoskAsr.SampleRate;

    public void Dispose() => _rec.Dispose();
}
