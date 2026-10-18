using System.Globalization;
using System.Text;
using System.Text.RegularExpressions;

namespace PersianAiKit.Text;

/// <summary>
/// ابزارهای متنِ فارسی که هر سه بخش لازم دارند:
///   · <see cref="ToSpeakable"/>: متن ⇒ متنی که موتورِ صدا درست بخواند (عدد، ساعت، تاریخ، درصد، کدِ لاتین، واحد).
///   · <see cref="NumberWords"/>: ۲۵۰۴۵ ⇒ «بیست و پنج هزار و چهل و پنج».
///   · <see cref="Normalize"/>: یکسان‌سازی برای مقایسه و جست‌وجو (ی/ک عربی، رقم‌ها، اعراب، نشانه‌ها).
///   · <see cref="WordsToDigits"/> و <see cref="ExtractNumbers"/>: خروجیِ گفتار‌به‌متن («صد و بیست و پنج تا») ⇒ عدد (۱۲۵).
/// </summary>
public static class PersianText
{
    // ───────────────────────── برای صدا ─────────────────────────

    /// <summary>
    /// متن ⇒ متنِ خواندنی برای موتورِ صدا. موتور (espeak) رقم و حرفِ لاتین را درست نمی‌خواند، پس همه به واژهٔ فارسی:
    /// «ساعت 10:30 روی INJ8 مقدار 2.5 kg (۲۰٪)» ⇒ «ساعت ده و نیم روی آی اِن جِی هشت مقدار دو و نیم کیلوگرم (بیست درصد)».
    /// تاریخِ شمسیِ «1405/07/05» ⇒ «پنجم مهر هزار و چهارصد و پنج».
    /// </summary>
    public static string ToSpeakable(string? text)
    {
        if (string.IsNullOrWhiteSpace(text)) return "";
        var t = LatinDigits(text);
        // جداکنندهٔ هزارگان: 25,000 و ۲۵٬۰۰۰
        t = Regex.Replace(t, @"(?<=\d)[,٬](?=\d{3}(?!\d))", "");
        // تاریخِ شمسی (۱۳۰۰ تا ۱۵۰۰)
        t = Regex.Replace(t, @"\b(1[34]\d\d)[/\-](\d{1,2})[/\-](\d{1,2})\b", m =>
        {
            int y = int.Parse(m.Groups[1].Value), mo = int.Parse(m.Groups[2].Value), d = int.Parse(m.Groups[3].Value);
            return mo is >= 1 and <= 12 && d is >= 1 and <= 31 ? $"{OrdinalWords(d)} {Months[mo - 1]} {NumberWords(y)}" : m.Value;
        });
        t = Regex.Replace(t, @"(\d+(?:\.\d+)?)\s?[%٪]", "$1 درصد");
        // واحدهای لاتین به واژه، پیش از حرف‌به‌حرف خواندنِ کدها («2.5 kg» ⇒ «دو و نیم کیلوگرم»، نه «کِی جی»)
        t = Regex.Replace(t, @"(?<=\d\s?)(kg|gr|g|mm|cm|km|m|kw|kwh|ton|l|ml)\b", m => m.Value.ToLowerInvariant() switch
        {
            "kg" => " کیلوگرم", "gr" or "g" => " گرم", "mm" => " میلی‌متر", "cm" => " سانتی‌متر", "km" => " کیلومتر", "m" => " متر",
            "kw" => " کیلووات", "kwh" => " کیلووات‌ساعت", "ton" => " تن", "l" => " لیتر", "ml" => " میلی‌لیتر", _ => m.Value,
        }, RegexOptions.IgnoreCase);
        // کدِ لاتینِ کوتاه (INJ8، WS1-LM1، PVC) حرف‌به‌حرف به فارسی
        t = Regex.Replace(t, @"\b[A-Za-z]{1,5}\d{0,3}(?:-[A-Za-z]{1,5}\d{0,3})*\b", m =>
            string.Join("، ", m.Value.Split('-').Select(SpellLatin)));
        // ساعت: 11:30 ⇒ «یازده و نیم»، 8:05 ⇒ «هشت و پنج دقیقه»
        t = Regex.Replace(t, @"\b(\d{1,2}):(\d{2})\b", m =>
        {
            var h = int.Parse(m.Groups[1].Value); var mi = int.Parse(m.Groups[2].Value);
            return mi == 0 ? NumberWords(h) : mi == 30 ? $"{NumberWords(h)} و نیم" : $"{NumberWords(h)} و {NumberWords(mi)} دقیقه";
        });
        t = Regex.Replace(t, @"\d+(?:\.\d+)?", m =>
        {
            var v = m.Value;
            var dot = v.IndexOf('.');
            if (dot < 0) return long.TryParse(v, out var n) ? NumberWords(n) : string.Join(" ", v.Select(c => NumberWords(c - '0')));
            var whole = long.TryParse(v[..dot], out var w) ? w : 0;
            var frac = v[(dot + 1)..].TrimEnd('0');
            if (frac.Length == 0) return NumberWords(whole);
            if (frac == "5") return $"{NumberWords(whole)} و نیم";
            return $"{NumberWords(whole)} ممیز {string.Join(" ", frac.Select(c => NumberWords(c - '0')))}";
        });
        return Regex.Replace(t, @"\s+", " ").Trim();
    }

    private static readonly string[] Months =
        { "فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور", "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند" };

    private static readonly Dictionary<char, string> LetterNames = new()
    {
        ['A'] = "اِی", ['B'] = "بی", ['C'] = "سی", ['D'] = "دی", ['E'] = "ای", ['F'] = "اِف", ['G'] = "جی", ['H'] = "اِچ",
        ['I'] = "آی", ['J'] = "جِی", ['K'] = "کِی", ['L'] = "اِل", ['M'] = "اِم", ['N'] = "اِن", ['O'] = "اُ", ['P'] = "پی",
        ['Q'] = "کیو", ['R'] = "آر", ['S'] = "اِس", ['T'] = "تی", ['U'] = "یو", ['V'] = "وی", ['W'] = "دابلیو", ['X'] = "اِکس",
        ['Y'] = "وای", ['Z'] = "زِد",
    };

    /// <summary>«INJ8» ⇒ «آی اِن جِی 8» (رقم را <see cref="ToSpeakable"/> بعداً به حروف می‌کند).</summary>
    public static string SpellLatin(string code)
    {
        var letters = new string(code.TakeWhile(char.IsLetter).ToArray());
        var digits = code[letters.Length..];
        var spelled = string.Join(" ", letters.ToUpperInvariant().Select(c => LetterNames.GetValueOrDefault(c, c.ToString())));
        return digits.Length > 0 ? $"{spelled} {digits}" : spelled;
    }

    private static readonly string[] Ones = { "صفر", "یک", "دو", "سه", "چهار", "پنج", "شش", "هفت", "هشت", "نه", "ده",
        "یازده", "دوازده", "سیزده", "چهارده", "پانزده", "شانزده", "هفده", "هجده", "نوزده" };
    private static readonly string[] Tens = { "", "", "بیست", "سی", "چهل", "پنجاه", "شصت", "هفتاد", "هشتاد", "نود" };
    private static readonly string[] Hundreds = { "", "صد", "دویست", "سیصد", "چهارصد", "پانصد", "ششصد", "هفتصد", "هشتصد", "نهصد" };

    /// <summary>۲۵۰۴۵ ⇒ «بیست و پنج هزار و چهل و پنج»؛ ۱۴۰۰ ⇒ «هزار و چهارصد» (نه «یک هزار»).</summary>
    public static string NumberWords(long n)
    {
        if (n < 0) return "منفی " + NumberWords(-n);
        if (n < 20) return Ones[n];
        static string Under1000(long x)
        {
            var parts = new List<string>();
            if (x >= 100) { parts.Add(Hundreds[x / 100]); x %= 100; }
            if (x >= 20) { parts.Add(Tens[x / 10]); x %= 10; }
            if (x > 0) parts.Add(Ones[x]);
            return string.Join(" و ", parts);
        }
        var groups = new List<string>();
        foreach (var (size, name) in new[] { (1_000_000_000_000L, "هزار میلیارد"), (1_000_000_000L, "میلیارد"), (1_000_000L, "میلیون"), (1_000L, "هزار") })
        {
            if (n < size) continue;
            var head = n / size;
            groups.Add(head == 1 && size == 1_000 ? name : $"{(head >= 1000 ? NumberWords(head) : Under1000(head))} {name}");
            n %= size;
        }
        if (n > 0) groups.Add(Under1000(n));
        return string.Join(" و ", groups);
    }

    /// <summary>۱ ⇒ «یکم»، ۳ ⇒ «سوم»، ۳۰ ⇒ «سی‌ام»، ۲۳ ⇒ «بیست و سوم».</summary>
    public static string OrdinalWords(long n)
    {
        var w = NumberWords(n);
        if (w.EndsWith("سه")) return w[..^2] + "سوم";
        if (w.EndsWith("ی")) return w + "‌ام";
        return w + "م";
    }

    /// <summary>«250» ⇒ «۲۵۰» برای نمایش.</summary>
    public static string ToPersianDigits(string? s)
    {
        if (string.IsNullOrEmpty(s)) return "";
        var b = new StringBuilder(s.Length);
        foreach (var c in s) b.Append(c is >= '0' and <= '9' ? (char)('۰' + (c - '0')) : c);
        return b.ToString();
    }

    /// <summary>رقم‌های فارسی و عربی ⇒ لاتین؛ «٫» ⇒ «.».</summary>
    public static string LatinDigits(string? s)
    {
        if (string.IsNullOrEmpty(s)) return "";
        return new string(s.Select(ch => ch is >= '۰' and <= '۹' ? (char)('0' + (ch - '۰'))
            : ch is >= '٠' and <= '٩' ? (char)('0' + (ch - '٠')) : ch == '٫' ? '.' : ch).ToArray());
    }

    // ───────────────────────── برای فهمِ متن ─────────────────────────

    /// <summary>
    /// یکسان‌سازی برای مقایسه و جست‌وجو (نه برای نمایش): حروفِ کوچک، رقمِ لاتین، ی/ک عربی ⇒ فارسی، بی‌اعراب،
    /// نیم‌فاصله و نشانه‌ها ⇒ فاصله، «۴۰تا» ⇒ «40 تا».
    /// </summary>
    public static string Normalize(string? text)
    {
        if (string.IsNullOrWhiteSpace(text)) return "";
        var digits = LatinDigits(text.Trim().ToLowerInvariant());
        digits = Regex.Replace(digits, @"(\d)[.](\d)", "$1\u0001$2");   // ممیز نگه داشته شود
        var sb = new StringBuilder(digits.Length);
        foreach (var ch in digits)
        {
            var c = ch switch
            {
                'ي' or 'ى' => 'ی',
                'ك' => 'ک',
                'ة' or 'ۀ' => 'ه',
                'أ' or 'إ' or 'ٱ' => 'ا',
                '‌' or '‏' or '‎' or '-' or '–' or '—' => ' ',
                '،' or ',' or '.' or '؛' or ';' or '!' or '?' or '؟' or ':' or '«' or '»' or '"' or '(' or ')' => ' ',
                _ => ch,
            };
            if (c is >= 'ً' and <= 'ْ') continue;   // اعراب
            sb.Append(c);
        }
        var s = sb.ToString().Replace('\u0001', '.');
        s = Regex.Replace(s, @"(\d)([^\d\s.])", "$1 $2");
        s = Regex.Replace(s, @"([^\d\s.])(\d)", "$1 $2");
        return Regex.Replace(s, @"\s+", " ").Trim();
    }

    private static readonly Dictionary<string, int> Units = new()
    {
        ["صفر"] = 0, ["یک"] = 1, ["یه"] = 1, ["یکی"] = 1, ["دو"] = 2, ["سه"] = 3, ["چهار"] = 4, ["چار"] = 4, ["پنج"] = 5, ["شش"] = 6, ["شیش"] = 6,
        ["هفت"] = 7, ["هشت"] = 8, ["نه"] = 9, ["ده"] = 10, ["یازده"] = 11, ["دوازده"] = 12, ["سیزده"] = 13, ["چهارده"] = 14, ["چارده"] = 14,
        ["پانزده"] = 15, ["پونزده"] = 15, ["شانزده"] = 16, ["شونزده"] = 16, ["هفده"] = 17, ["هیفده"] = 17, ["هجده"] = 18, ["هیجده"] = 18,
        ["هژده"] = 18, ["نوزده"] = 19, ["بیست"] = 20, ["سی"] = 30, ["چهل"] = 40, ["چل"] = 40, ["پنجاه"] = 50, ["پنجا"] = 50, ["شصت"] = 60,
        ["هفتاد"] = 70, ["هشتاد"] = 80, ["نود"] = 90, ["صد"] = 100, ["یکصد"] = 100, ["دویست"] = 200, ["سیصد"] = 300, ["چهارصد"] = 400,
        ["چارصد"] = 400, ["پانصد"] = 500, ["پونصد"] = 500, ["ششصد"] = 600, ["شیشصد"] = 600, ["هفتصد"] = 700, ["هشتصد"] = 800, ["نهصد"] = 900,
    };

    private static readonly Dictionary<string, long> Scales = new() { ["هزار"] = 1_000, ["میلیون"] = 1_000_000, ["میلیارد"] = 1_000_000_000 };

    /// <summary>واژه‌هایی که بعد از عدد می‌آیند — «نه/یه/یکی» فقط با یکی از این‌ها عددند («نه، نرسیدم» عدد نیست).</summary>
    private static readonly HashSet<string> CountWords = new()
    {
        "تا", "تو", "تایی", "عدد", "دونه", "دانه", "نفر", "بار", "دفعه", "ساعت", "دقیقه", "ثانیه", "روز", "هفته", "ماه", "سال",
        "کیلو", "کیلوگرم", "گرم", "متر", "سانت", "سانتی", "لیتر", "تن", "قطعه", "بسته", "کارتن", "جفت", "تومان", "تومن", "ریال", "درصد",
    };

    /// <summary>«یک کم»، «یک مقدار» عدد نیستند.</summary>
    private static readonly HashSet<string> NotAfterOne = new() { "کم", "کمی", "ذره", "خورده", "خرده", "جا", "جوری", "طوری", "مقدار", "چیزی", "کسی" };

    private static bool IsNumberStart(string[] words, int i)
    {
        var w = words[i];
        var next = i + 1 < words.Length ? words[i + 1] : "";
        if (Scales.ContainsKey(w)) return true;
        if (!Units.ContainsKey(w)) return false;
        return w switch
        {
            "نه" or "یه" => CountWords.Contains(next) || Scales.ContainsKey(next),
            "یکی" => next is "تا" or "عدد" or "دونه" or "دانه",
            "یک" => !NotAfterOne.Contains(next),
            _ => true,
        };
    }

    /// <summary>
    /// خروجیِ گفتار‌به‌متن ⇒ همان متن با عددهای رقمی (نرمال‌شده):
    /// «کار اول صد و بیست و پنج تا زدم دو و نیم ساعت» ⇒ «کار اول 125 تا زدم 2.5 ساعت».
    /// </summary>
    public static string WordsToDigits(string? text)
    {
        var words = Normalize(text).Split(' ', StringSplitOptions.RemoveEmptyEntries);
        var outp = new List<string>(words.Length);
        for (var i = 0; i < words.Length; i++)
        {
            var w = words[i];
            if (double.TryParse(w, NumberStyles.Float, CultureInfo.InvariantCulture, out var dv))
            {
                if (i + 2 < words.Length && words[i + 1] == "و" && words[i + 2] == "نیم") { outp.Add(Format(dv + 0.5)); i += 2; }
                else outp.Add(w);
                continue;
            }
            if (!IsNumberStart(words, i)) { outp.Add(w); continue; }

            long total = 0, cur = 0; var half = false; var j = i;
            while (j < words.Length)
            {
                var x = words[j];
                if (Scales.TryGetValue(x, out var scale)) { cur = (cur == 0 ? 1 : cur) * scale; total += cur; cur = 0; }
                else if (Units.TryGetValue(x, out var u)) { if (x == "صد" && cur is > 0 and < 10) cur *= 100; else cur += u; }
                else break;
                j++;
                if (j >= words.Length) break;
                var nx = words[j];
                if (nx == "و" && j + 1 < words.Length)
                {
                    var after = words[j + 1];
                    if (after == "نیم") { half = true; j += 2; break; }
                    if (Units.ContainsKey(after) || Scales.ContainsKey(after)) { j++; continue; }
                    break;
                }
                // بی «و»: «دو هزار»، «سه صد»، و «بیست پنج» / «صد بیست» (گفتار‌به‌متن گاهی «و» را نمی‌نویسد)
                if (Scales.ContainsKey(nx) || (nx == "صد" && cur is > 0 and < 10)) continue;
                if (Units.TryGetValue(nx, out var nu) && nx is not ("نه" or "یه" or "یکی")
                    && (cur % 100 == 0 && cur > 0 && nu < 100 || cur % 100 >= 20 && cur % 10 == 0 && nu < 10)) continue;
                break;
            }
            outp.Add(Format(total + cur + (half ? 0.5 : 0)));
            i = j - 1;
        }
        return string.Join(' ', outp);
    }

    /// <summary>
    /// نرخِ خطای واژه (۰ تا ۱) بینِ متنِ مرجع و متنِ شنیده‌شده — برای وارسیِ خودکارِ گفتارِ ساخته‌شده با گفتار‌به‌متن.
    /// عدد با حروف و رقم یکی است و «رو»ی گفتاری همان «را» حساب می‌شود.
    /// </summary>
    public static double WordErrorRate(string? reference, string? heard)
    {
        static string[] Words(string? s) =>
            WordsToDigits(s).Split(' ', StringSplitOptions.RemoveEmptyEntries).Select(w => w == "رو" ? "را" : w).ToArray();
        var r = Words(reference);
        var h = Words(heard);
        if (r.Length == 0) return h.Length == 0 ? 0 : 1;
        var prev = Enumerable.Range(0, h.Length + 1).ToArray();
        for (var i = 1; i <= r.Length; i++)
        {
            var cur = new int[h.Length + 1];
            cur[0] = i;
            for (var j = 1; j <= h.Length; j++)
                cur[j] = Math.Min(Math.Min(prev[j] + 1, cur[j - 1] + 1), prev[j - 1] + (r[i - 1] == h[j - 1] ? 0 : 1));
            prev = cur;
        }
        return Math.Min(1.0, prev[h.Length] / (double)r.Length);
    }

    /// <summary>همهٔ عددهای متن، چه رقمی چه با حروف، به ترتیب: «دو هزار و پونصد تا در سه و نیم ساعت» ⇒ [2500, 3.5].</summary>
    public static List<double> ExtractNumbers(string? text) =>
        Regex.Matches(WordsToDigits(text), @"(?<![\w.])\d+(?:\.\d+)?(?![\w.])")
             .Select(m => double.Parse(m.Value, CultureInfo.InvariantCulture)).ToList();

    private static string Format(double v) => v.ToString("0.##", CultureInfo.InvariantCulture);

    // ───────────────────────── فرمانِ صوتی ─────────────────────────

    /// <summary>
    /// کدام فرمان/جمله در متنِ شنیده‌شده گفته شد: «لطفاً چراغ را خاموش کن» + [«روشن کن»، «خاموش کن»] ⇒ «خاموش کن»؛ هیچ ⇒ null.
    /// روشِ پیشنهادی برای فرمانِ صوتی: صدا را آزاد بشنوید (بی فهرست) و بعد این را صدا بزنید — حرفِ بی‌ربط به هیچ فرمانی نمی‌خورد.
    /// واژه‌های فرمان باید پشتِ هم در متن باشند؛ یک حرف اختلاف در واژهٔ ۴حرفی به بالا پذیرفته است. چند فرمان ⇒ بلندترین، بعد زودترین.
    /// </summary>
    public static string? FindPhrase(string? heard, IEnumerable<string> phrases) => FindPhrases(heard, phrases).FirstOrDefault();

    /// <summary>همهٔ فرمان‌هایی که در متن گفته شد (هر کدام یک بار)، بلندترها اول و بعد به ترتیبِ گفتن.</summary>
    public static List<string> FindPhrases(string? heard, IEnumerable<string> phrases)
    {
        var words = Normalize(heard).Split(' ', StringSplitOptions.RemoveEmptyEntries);
        var found = new List<(string Phrase, int Length, int At)>();
        foreach (var p in phrases.Where(p => !string.IsNullOrWhiteSpace(p)).Distinct())
        {
            var pw = Normalize(p).Split(' ', StringSplitOptions.RemoveEmptyEntries);
            if (pw.Length == 0) continue;
            for (var i = 0; i + pw.Length <= words.Length; i++)
                if (pw.Select((w, k) => SameWord(w, words[i + k])).All(x => x)) { found.Add((p, pw.Length, i)); break; }
        }
        return found.OrderByDescending(f => f.Length).ThenBy(f => f.At).Select(f => f.Phrase).ToList();
    }

    private static readonly string[] VerbEndings = { "ید", "یم", "ین", "ند", "ه", "ی" };

    /// <summary>a واژهٔ فرمان، b واژهٔ شنیده‌شده. «کن» = «کنید/کنین/کنی/کنه»؛ یک حرف اختلاف در واژهٔ بلند.</summary>
    private static bool SameWord(string a, string b)
    {
        if (a == b) return true;
        if (a.Length >= 2 && b.Length > a.Length && b.StartsWith(a, StringComparison.Ordinal) && VerbEndings.Contains(b[a.Length..])) return true;
        if (Math.Min(a.Length, b.Length) < 4 || Math.Abs(a.Length - b.Length) > 1) return false;
        // فاصلهٔ ویرایشی ≤ ۱
        int i = 0, j = 0, edits = 0;
        while (i < a.Length && j < b.Length)
        {
            if (a[i] == b[j]) { i++; j++; continue; }
            if (++edits > 1) return false;
            if (a.Length > b.Length) i++;
            else if (b.Length > a.Length) j++;
            else { i++; j++; }
        }
        return edits + (a.Length - i) + (b.Length - j) <= 1;
    }
}
