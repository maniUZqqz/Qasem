namespace PersianAiKit.Video;

/// <summary>یک «پریست»: نسخهٔ آماده که روی نسخهٔ فعلی می‌نشیند.</summary>
public sealed record Preset(string Key, string Title, string Help, string Kind, VideoRecipe Recipe);

/// <summary>
/// پریست‌های آماده. look = حال‌وهوای رنگ (مثلِ لوک‌های لومتری)، audio = صدا (مثلِ Essential Sound)،
/// output = قاب و خروجی برای هر جا (ریلز، یوتیوب، تلگرام، …). همین فهرست در صفحه و در /api/tools است.
/// </summary>
public static class Presets
{
    public static readonly IReadOnlyList<Preset> All = new[]
    {
        // ── رنگ ──
        P("clean", "روشن و تمیز", "کمی روشن‌تر، سایه‌ها باز، رنگ کمی زنده‌تر.", "look",
            """{"adjust":{"exposure":0.15,"highlights":-20,"shadows":20,"whites":10,"vibrance":15}}"""),
        P("vivid", "پرجلوه", "رنگ و کنتراستِ بیشتر، بی نارنجی شدنِ پوست.", "look",
            """{"adjust":{"vibrance":35,"saturation":8,"contrast":18,"clarity":15}}"""),
        P("warm", "گرم", "نورِ عصرگاهی.", "look",
            """{"adjust":{"temperature":18,"tint":3,"vibrance":10,"highlightsHue":40,"highlightsSat":15}}"""),
        P("cool", "سرد", "آبی‌تر و تمیزتر.", "look",
            """{"adjust":{"temperature":-15,"vibrance":5,"shadowsHue":220,"shadowsSat":15}}"""),
        P("bw", "سیاه‌وسفید", "سیاه‌وسفیدِ نرم با کمی کنتراست.", "look",
            """{"adjust":{"saturation":-100,"contrast":20}}"""),
        P("cinematic", "سینمایی", "سایه‌های فیروزه‌ای، روشنی‌های نارنجی (تیل و نارنجی)، گوشه‌های تیره.", "look",
            """{"adjust":{"contrast":15,"saturation":-10,"shadowsHue":190,"shadowsSat":25,"highlightsHue":35,"highlightsSat":20,"vignette":25}}"""),
        P("film", "فیلمیِ مات", "سیاه‌های شسته، رنگِ ملایم و دانه — Faded Film.", "look",
            """{"adjust":{"saturation":-15,"grain":20,"shadowsHue":200,"shadowsSat":10},"curve":{"rgb":[[0,30],[64,70],[192,190],[255,242]]}}"""),
        P("vintage", "قدیمی", "گرم، کم‌رنگ، با گوشه‌های تیره و دانه.", "look",
            """{"adjust":{"temperature":15,"saturation":-25,"contrast":-10,"vignette":35,"grain":25},"curve":{"rgb":[[0,25],[255,235]]}}"""),
        P("night", "شب و نورِ کم", "نویزگیری، سایه‌های بازتر، رنگِ طبیعی‌تر.", "look",
            """{"adjust":{"denoise":55,"denoiseColor":50,"shadows":25,"blacks":-10,"vibrance":10}}"""),
        // ── صدا ──
        P("voice", "پاک‌سازیِ گفتار", "زنجیرهٔ تمیزکاریِ دیالوگ: غرش، نویز، سین، وضوح، کمپرسور و بلندیِ ‎−۱۶.", "audio",
            """{"adjust":{"rumble":40,"noise":40,"deess":30,"presence":3,"compress":40},"audio":{"normalize":-16}}"""),
        P("voiceStrong", "گفتار در محیطِ پرسروصدا", "مثلِ «پاک‌سازیِ گفتار» ولی نویزگیریِ قوی‌تر (خیابان، کولر، باد).", "audio",
            """{"adjust":{"rumble":70,"noise":75,"declick":30,"deess":35,"presence":4,"compress":50},"audio":{"normalize":-16}}"""),
        P("music", "موسیقی", "فقط هم‌سطح‌سازیِ بلندی، بی دست زدن به صدای ساز.", "audio",
            """{"audio":{"normalize":-14}}"""),
        // ── قاب و خروجی ──
        P("reels", "ریلز / استوری", "قابِ عمودیِ ۹:۱۶ (۱۰۸۰×۱۹۲۰) با زمینهٔ محو، بلندیِ ‎−۱۴، MP4.", "output",
            """{"frame":{"aspect":"9:16","fit":"blur"},"audio":{"normalize":-14},"output":{"format":"mp4","size":1080,"quality":"standard"}}"""),
        P("square", "پستِ مربع", "قابِ ۱:۱ (۱۰۸۰×۱۰۸۰)، وسطِ تصویر.", "output",
            """{"frame":{"aspect":"1:1","fit":"crop"},"audio":{"normalize":-14},"output":{"format":"mp4","size":1080}}"""),
        P("youtube", "یوتیوب", "۱۶:۹، ۱۰۸۰p، کیفیتِ بالا، بلندیِ ‎−۱۴.", "output",
            """{"frame":{"aspect":"16:9","fit":"black"},"audio":{"normalize":-14},"output":{"format":"mp4","size":1080,"quality":"high"}}"""),
        P("telegram", "تلگرام و واتس‌اپ (سبک)", "۷۲۰p با حجمِ کم برای فرستادن.", "output",
            """{"audio":{"normalize":-16},"output":{"format":"mp4","size":720,"quality":"small"}}"""),
        P("gif", "GIF", "گیفِ بی‌صدا، ۴۸۰ پیکسل، ۱۲ فریم در ثانیه.", "output",
            """{"output":{"format":"gif","size":480,"fps":12}}"""),
        P("podcast", "فقط صدا (پادکست)", "MP3 با پاک‌سازیِ گفتار و بلندیِ ‎−۱۶.", "output",
            """{"adjust":{"rumble":40,"noise":40,"deess":30,"presence":3,"compress":40},"audio":{"normalize":-16},"output":{"format":"mp3"}}"""),
    };

    public static Preset? Find(string key) => All.FirstOrDefault(p => p.Key.Equals(key, StringComparison.OrdinalIgnoreCase));

    private static Preset P(string key, string title, string help, string kind, string json) => new(key, title, help, kind, VideoRecipe.Parse(json));
}
