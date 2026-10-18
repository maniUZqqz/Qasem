using System.Diagnostics;
using Microsoft.ML.OnnxRuntime;
using Microsoft.ML.OnnxRuntime.Tensors;
using OpenCvSharp;

namespace PersianAiKit.Photo.Ai;

/// <summary>پایهٔ مدل‌های ONNX: بارِ تنبل (اولین استفاده)، یک اجرا در هر لحظه.</summary>
public abstract class OnnxModel : IDisposable
{
    private readonly string _path;
    private InferenceSession? _session;
    protected readonly object RunLock = new();

    protected OnnxModel(string path) => _path = path;

    public string ModelPath => _path;
    public bool Available => File.Exists(_path);

    /// <summary>هسته‌های پردازنده برای مدل؛ پیش‌فرض نصفِ هسته‌ها تا کامپیوتر هنگامِ کار قابلِ استفاده بماند.</summary>
    public int Threads { get; set; } = Math.Max(1, Environment.ProcessorCount / 2);

    /// <summary>false ⇒ بعد از هر اجرا مدل از حافظه بیرون می‌رود (برای مدلِ بزرگ روی کامپیوترِ کم‌حافظه).</summary>
    public bool KeepLoaded { get; set; } = true;

    protected InferenceSession Session()
    {
        if (_session is not null) return _session;
        if (!Available) throw new InvalidOperationException($"مدل نصب نیست: {_path} — tools\\Download-Models.ps1 را اجرا کنید.");
        var o = new SessionOptions
        {
            IntraOpNumThreads = Math.Max(1, Threads),
            GraphOptimizationLevel = GraphOptimizationLevel.ORT_ENABLE_ALL,
            // بی «استخرِ حافظه»: هر لایه حافظه‌اش را پس می‌دهد. با استخر، BiRefNet روی ۱۰۲۴ پیکسل ~۹GB می‌گرفت
            // (روی کامپیوترِ ۸GB یعنی جابه‌جایی با دیسک و ۶ دقیقه به‌جای چند ثانیه)
            EnableCpuMemArena = false,
            EnableMemoryPattern = false,
        };
        _session = new InferenceSession(_path, o);
        return _session;
    }

    /// <summary>بعد از اجرا: اگر نباید بماند، از حافظه بیرون.</summary>
    protected void AfterRun()
    {
        if (KeepLoaded) return;
        _session?.Dispose();
        _session = null;
        GC.Collect();
    }

    public void Dispose() => _session?.Dispose();
}

/// <summary>
/// حذفِ پس‌زمینه با BiRefNet-lite (MIT): عکس ⇒ ماسکِ کالا (۰ تا ۱) به اندازهٔ خودِ عکس.
/// سنگین است: روی ۱۰۲۴×۱۰۲۴ کار می‌کند و روی CPU حدودِ ۶٫۳GB حافظه و ~۷۰ ثانیه (i5-4590) می‌خواهد ⇒ جایش روی سرور است.
/// پیش از اجرا حافظهٔ آزاد وارسی می‌شود؛ کم باشد اجرا نمی‌شود (به‌جایش <see cref="Engine.QuickMatte"/>).
/// </summary>
public sealed class BackgroundRemover : OnnxModel
{
    private const int Side = 1024;
    private static readonly float[] Mean = { 0.485f, 0.456f, 0.406f }, Std = { 0.229f, 0.224f, 0.225f };

    public BackgroundRemover(string path) : base(path) => KeepLoaded = false;

    public double LastSeconds { get; private set; }

    /// <summary>false ⇒ هرگز اجرا نمی‌شود (تنظیمِ سرور).</summary>
    public bool Enabled { get; set; } = true;

    /// <summary>حافظهٔ آزادِ لازم (MB) — اندازه‌گیری‌شده: اوجِ ۶۲۷۳MB با استخرِ حافظهٔ خاموش.</summary>
    public int RequiredMemoryMB { get; set; } = 6500;

    /// <summary>می‌شود الان اجرا کرد؟ نه ⇒ دلیلِ فارسی.</summary>
    public bool CanRun(out string reason)
    {
        reason = "";
        if (!Enabled) { reason = "حذفِ پس‌زمینه با هوشِ مصنوعی در تنظیمات خاموش است"; return false; }
        if (!Available) { reason = "مدلِ حذفِ پس‌زمینه نصب نیست (tools\\Download-Models.ps1)"; return false; }
        var free = SystemMemory.AvailableMB();
        if (free is { } f && f < RequiredMemoryMB)
        {
            reason = $"حافظهٔ آزاد {f:N0}MB است و مدلِ هوشِ مصنوعی حدودِ {RequiredMemoryMB:N0}MB می‌خواهد — روی سرورِ پرحافظه اجرا کنید";
            return false;
        }
        return true;
    }

    public unsafe Mat Mask(Mat bgr01)
    {
        if (!CanRun(out var why)) throw new InvalidOperationException(why);
        var sw = Stopwatch.StartNew();
        using var small = new Mat();
        Cv2.Resize(bgr01, small, new Size(Side, Side), 0, 0, InterpolationFlags.Area);
        var input = new DenseTensor<float>(new[] { 1, 3, Side, Side });
        var span = input.Buffer.Span;
        int plane = Side * Side;
        for (int y = 0; y < Side; y++)
        {
            float* p = (float*)small.Ptr(y);
            for (int x = 0; x < Side; x++, p += 3)
            {
                int i = y * Side + x;
                span[i] = (Math.Clamp(p[2], 0f, 1f) - Mean[0]) / Std[0];
                span[plane + i] = (Math.Clamp(p[1], 0f, 1f) - Mean[1]) / Std[1];
                span[2 * plane + i] = (Math.Clamp(p[0], 0f, 1f) - Mean[2]) / Std[2];
            }
        }
        float[] outData;
        int oh, ow;
        lock (RunLock)
        {
            var s = Session();
            var name = s.InputMetadata.Keys.First();
            using var res = s.Run(new[] { NamedOnnxValue.CreateFromTensor(name, input) });
            // خروجیِ نهایی: آخرین خروجیِ ۱×۱×H×W
            var t = res.Last(r => r.Value is Tensor<float> tt && tt.Dimensions.Length == 4 && tt.Dimensions[1] == 1).AsTensor<float>();
            oh = t.Dimensions[2]; ow = t.Dimensions[3];
            outData = t.ToArray();
            AfterRun();
        }
        // بعضی خروجی‌ها logit‌اند (بیرون از ۰ تا ۱) ⇒ سیگموید
        float min = float.MaxValue, max = float.MinValue;
        foreach (var v in outData) { if (v < min) min = v; if (v > max) max = v; }
        bool logits = min < -0.01f || max > 1.01f;
        using var m = new Mat(oh, ow, MatType.CV_32FC1);
        for (int y = 0; y < oh; y++)
        {
            float* p = (float*)m.Ptr(y);
            for (int x = 0; x < ow; x++)
            {
                var v = outData[y * ow + x];
                p[x] = logits ? 1 / (1 + MathF.Exp(-v)) : Math.Clamp(v, 0f, 1f);
            }
        }
        var full = new Mat();
        Cv2.Resize(m, full, bgr01.Size(), 0, 0, InterpolationFlags.Linear);
        Cv2.Max(full, Scalar.All(0), full);
        Cv2.Min(full, Scalar.All(1), full);
        LastSeconds = sw.Elapsed.TotalSeconds;
        return full;
    }
}

/// <summary>
/// بزرگ‌نمایی و بهبودِ جزئیات با Real-ESRGAN general-x4v3 (BSD-3): ×۴ (برای ×۲ بعد کوچک می‌شود). تکه‌تکه (کاشی) تا حافظه کم بماند.
/// </summary>
public sealed class Upscaler : OnnxModel
{
    private const int Tile = 192, Pad = 12, Native = 4;

    public Upscaler(string path) : base(path) { }

    public double LastSeconds { get; private set; }

    /// <summary>بیشترین ضلعِ خروجی (حافظه): بزرگ‌تر از این خواسته شود، ورودی اول کوچک می‌شود. ۴۰۹۶ ⇒ حدودِ ۶۰۰MB.</summary>
    public int MaxOutputSide { get; set; } = 4096;

    public unsafe Mat Upscale(Mat bgr01, int factor)
    {
        var sw = Stopwatch.StartNew();
        factor = factor >= 4 ? 4 : 2;
        int w = bgr01.Cols, h = bgr01.Rows;
        // ورودیِ خیلی بزرگ ⇒ اول کوچک، تا خروجی از سقف نگذرد
        var srcScale = Math.Min(1.0, MaxOutputSide / (double)(Math.Max(w, h) * factor));
        using var src = new Mat();
        if (srcScale < 1) Cv2.Resize(bgr01, src, new Size((int)(w * srcScale), (int)(h * srcScale)), 0, 0, InterpolationFlags.Area);
        else bgr01.CopyTo(src);
        w = src.Cols; h = src.Rows;
        var big = new Mat(h * Native, w * Native, MatType.CV_32FC3, Scalar.All(0));
        lock (RunLock)
        {
            var s = Session();
            var name = s.InputMetadata.Keys.First();
            for (int ty = 0; ty < h; ty += Tile)
            for (int tx = 0; tx < w; tx += Tile)
            {
                int x0 = Math.Max(0, tx - Pad), y0 = Math.Max(0, ty - Pad);
                int x1 = Math.Min(w, tx + Tile + Pad), y1 = Math.Min(h, ty + Tile + Pad);
                int tw = x1 - x0, th = y1 - y0;
                var input = new DenseTensor<float>(new[] { 1, 3, th, tw });
                var span = input.Buffer.Span;
                int plane = tw * th;
                for (int y = 0; y < th; y++)
                {
                    float* p = (float*)src.Ptr(y0 + y) + x0 * 3;
                    for (int x = 0; x < tw; x++, p += 3)
                    {
                        int i = y * tw + x;
                        span[i] = Math.Clamp(p[2], 0f, 1f);
                        span[plane + i] = Math.Clamp(p[1], 0f, 1f);
                        span[2 * plane + i] = Math.Clamp(p[0], 0f, 1f);
                    }
                }
                using var res = s.Run(new[] { NamedOnnxValue.CreateFromTensor(name, input) });
                var o = res.First().AsTensor<float>();
                int oh = o.Dimensions[2], ow = o.Dimensions[3];
                var data = o.ToArray();
                int oplane = oh * ow;
                // فقط وسطِ کاشی (بی حاشیه) کپی می‌شود ⇒ درز دیده نمی‌شود
                int cx0 = (tx - x0) * Native, cy0 = (ty - y0) * Native;
                int cw = Math.Min(Tile, w - tx) * Native, ch = Math.Min(Tile, h - ty) * Native;
                for (int y = 0; y < ch; y++)
                {
                    float* d = (float*)big.Ptr(ty * Native + y) + tx * Native * 3;
                    int sy = cy0 + y;
                    for (int x = 0; x < cw; x++, d += 3)
                    {
                        int i = sy * ow + cx0 + x;
                        d[2] = Math.Clamp(data[i], 0f, 1f);
                        d[1] = Math.Clamp(data[oplane + i], 0f, 1f);
                        d[0] = Math.Clamp(data[2 * oplane + i], 0f, 1f);
                    }
                }
            }
        }
        if (factor == Native) { LastSeconds = sw.Elapsed.TotalSeconds; return big; }
        var outM = new Mat();
        Cv2.Resize(big, outM, new Size(w * factor, h * factor), 0, 0, InterpolationFlags.Area);
        big.Dispose();
        LastSeconds = sw.Elapsed.TotalSeconds;
        return outM;
    }
}
