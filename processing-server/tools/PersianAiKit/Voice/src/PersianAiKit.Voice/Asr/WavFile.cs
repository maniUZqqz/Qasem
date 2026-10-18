using System.Text;

namespace PersianAiKit.Asr;

/// <summary>خواندن و ساختنِ WAVِ PCMِ ۱۶بیتی — بی‌کتابخانه.</summary>
public static class WavFile
{
    /// <summary>RIFF/WAVE با fmt=PCMِ ۱۶بیت (هر نرخ، هر تعداد کانال) ⇒ نمونه‌های تک‌کاناله (میانگینِ کانال‌ها).</summary>
    public static bool TryReadMono(byte[] b, out short[] mono, out int rate)
    {
        mono = Array.Empty<short>(); rate = 0;
        if (b is null || b.Length < 44 || Encoding.ASCII.GetString(b, 0, 4) != "RIFF" || Encoding.ASCII.GetString(b, 8, 4) != "WAVE") return false;
        int channels = 0, bits = 0, pos = 12;
        while (pos + 8 <= b.Length)
        {
            var id = Encoding.ASCII.GetString(b, pos, 4);
            var size = BitConverter.ToInt32(b, pos + 4);
            var body = pos + 8;
            if (size < 0 || body + size > b.Length) size = b.Length - body;
            if (id == "fmt ")
            {
                if (size < 16 || BitConverter.ToInt16(b, body) != 1) return false;           // فقط PCM
                channels = BitConverter.ToInt16(b, body + 2);
                rate = BitConverter.ToInt32(b, body + 4);
                bits = BitConverter.ToInt16(b, body + 14);
            }
            else if (id == "data")
            {
                if (bits != 16 || channels < 1 || rate < 8000) return false;
                var n = size / 2 / channels;
                mono = new short[n];
                for (var i = 0; i < n; i++)
                {
                    var sum = 0;
                    for (var c = 0; c < channels; c++) sum += BitConverter.ToInt16(b, body + (i * channels + c) * 2);
                    mono[i] = (short)(sum / channels);
                }
                return true;
            }
            pos = body + size + (size & 1);
        }
        return false;
    }

    /// <summary>تبدیلِ نرخ با درون‌یابیِ خطی (کاهشِ نرخ با میانگینِ پنجره) — برای گفتار کافی است.</summary>
    public static short[] Resample(short[] src, int from, int to)
    {
        if (src.Length == 0 || from == to) return src;
        var n = (int)((long)src.Length * to / from);
        var dst = new short[n];
        var step = (double)from / to;
        for (var i = 0; i < n; i++)
        {
            if (step > 1)
            {
                // پایین‌گذرِ ساده: میانگینِ نمونه‌های همین پنجره
                int a = (int)(i * step), z = Math.Min(src.Length, (int)((i + 1) * step));
                long s = 0; for (var j = a; j < z; j++) s += src[j];
                dst[i] = (short)(z > a ? s / (z - a) : src[Math.Min(a, src.Length - 1)]);
            }
            else
            {
                var x = i * step; var j = (int)x; var f = x - j;
                var p = src[Math.Min(j, src.Length - 1)]; var q = src[Math.Min(j + 1, src.Length - 1)];
                dst[i] = (short)(p + (q - p) * f);
            }
        }
        return dst;
    }

    /// <summary>نمونه‌ها ⇒ فایلِ WAVِ PCMِ ۱۶بیتیِ تک‌کاناله.</summary>
    public static byte[] Write(short[] mono, int rate)
    {
        var data = mono.Length * 2;
        var b = new byte[44 + data];
        void Str(int off, string s) => Encoding.ASCII.GetBytes(s).CopyTo(b, off);
        Str(0, "RIFF"); BitConverter.GetBytes(36 + data).CopyTo(b, 4); Str(8, "WAVE"); Str(12, "fmt ");
        BitConverter.GetBytes(16).CopyTo(b, 16); BitConverter.GetBytes((short)1).CopyTo(b, 20); BitConverter.GetBytes((short)1).CopyTo(b, 22);
        BitConverter.GetBytes(rate).CopyTo(b, 24); BitConverter.GetBytes(rate * 2).CopyTo(b, 28);
        BitConverter.GetBytes((short)2).CopyTo(b, 32); BitConverter.GetBytes((short)16).CopyTo(b, 34);
        Str(36, "data"); BitConverter.GetBytes(data).CopyTo(b, 40);
        Buffer.BlockCopy(mono, 0, b, 44, data);
        return b;
    }

    /// <summary>درازای WAV به ثانیه (۰ اگر خوانده نشد).</summary>
    public static double Duration(byte[] wav) => TryReadMono(wav, out var m, out var r) && r > 0 ? m.Length / (double)r : 0;
}
