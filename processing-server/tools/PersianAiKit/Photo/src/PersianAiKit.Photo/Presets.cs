namespace PersianAiKit.Photo;

/// <summary>یک «فیلتر» (پریست): نسخهٔ ویرایشِ آماده که روی نسخهٔ فعلی می‌نشیند.</summary>
public sealed record Preset(string Key, string Title, string Help, string Kind, Recipe Recipe);

/// <summary>
/// فیلترهای آماده — مثلِ پریست‌های لایت‌روم. «look» فقط حال‌وهوا (نور و رنگ) را عوض می‌کند؛
/// «store» خروجیِ فروشگاه (پس‌زمینه و قاب) را هم می‌چیند. همین فهرست در صفحه و در /api/tools برای هوشِ مصنوعی است.
/// </summary>
public static class Presets
{
    public static readonly IReadOnlyList<Preset> All = new[]
    {
        P("clean", "روشن و تمیز", "کمی روشن‌تر، سایه‌ها باز، رنگ کمی زنده‌تر — مناسبِ بیشترِ عکس‌ها.", "look",
            """{"adjust":{"exposure":0.15,"highlights":-20,"shadows":25,"whites":10,"vibrance":15,"clarity":8}}"""),
        P("vivid", "پرجلوه", "رنگ و کنتراستِ بیشتر، بی آن‌که پوست نارنجی شود.", "look",
            """{"adjust":{"vibrance":35,"saturation":8,"contrast":18,"clarity":15,"dehaze":8}}"""),
        P("warm", "گرم", "نورِ عصرگاهی: زردتر و دلنشین‌تر.", "look",
            """{"adjust":{"temperature":18,"tint":3,"vibrance":10,"highlightsHue":40,"highlightsSat":15}}"""),
        P("cool", "سرد", "آبی‌تر و تمیزتر، سایه‌های کمی آبی.", "look",
            """{"adjust":{"temperature":-15,"vibrance":5,"shadowsHue":220,"shadowsSat":15}}"""),
        P("bw", "سیاه‌وسفید", "سیاه‌وسفیدِ نرم با کمی کنتراست.", "look",
            """{"adjust":{"saturation":-100,"contrast":20,"clarity":10}}"""),
        P("bwContrast", "سیاه‌وسفیدِ پرکنتراست", "سیاه‌های عمیق، سفیدهای درخشان، دانهٔ فیلم.", "look",
            """{"adjust":{"saturation":-100,"contrast":45,"blacks":-15,"whites":15,"clarity":25,"redLum":15,"blueLum":-20,"grain":15}}"""),
        P("matte", "فیلمیِ مات", "سیاه‌های شسته، رنگِ ملایم و دانه — حالِ عکسِ فیلم.", "look",
            """{"adjust":{"saturation":-15,"grain":20,"shadowsHue":200,"shadowsSat":10,"highlightsHue":45,"highlightsSat":10},"curve":{"rgb":[[0,30],[64,70],[192,190],[255,242]]}}"""),
        P("vintage", "قدیمی", "گرم، کم‌رنگ، با گوشه‌های تیره و دانه.", "look",
            """{"adjust":{"temperature":15,"saturation":-25,"contrast":-10,"vignette":-25,"grain":25},"curve":{"rgb":[[0,25],[255,235]]}}"""),
        P("cinematic", "سینمایی", "سایه‌های فیروزه‌ای، روشنی‌های نارنجی (تیل و نارنجی).", "look",
            """{"adjust":{"contrast":15,"saturation":-10,"shadowsHue":190,"shadowsSat":25,"highlightsHue":35,"highlightsSat":20,"vignette":-15}}"""),
        P("portrait", "پرتره", "پوستِ نرم‌تر، سایه‌های صورت باز، رنگِ طبیعی.", "look",
            """{"adjust":{"texture":-20,"clarity":-5,"shadows":15,"vibrance":10,"orangeLum":10,"orangeSat":-5}}"""),
        P("landscape", "منظره", "آسمانِ پررنگ، مه کمتر، جزئیاتِ بیشتر.", "look",
            """{"adjust":{"dehaze":15,"vibrance":30,"clarity":20,"blueSat":15,"greenSat":10,"highlights":-30,"shadows":20}}"""),
        P("food", "غذا", "گرم و اشتهاآور، جزئیاتِ تیز.", "look",
            """{"adjust":{"temperature":10,"vibrance":25,"clarity":10,"shadows":15,"sharpen":40,"sharpenMasking":30}}"""),
        P("store", "عکسِ فروشگاهی", "پس‌زمینهٔ سفید، قابِ مربعِ ۲۰۰۰ با حاشیهٔ ۶٪، سفیدهای تمیز و شارپ — برای دیجی‌کالا، باسلام، اینستاگرام.", "store",
            """{"adjust":{"whites":15,"clarity":10,"vibrance":10,"sharpen":40,"sharpenMasking":40},"background":{"remove":true,"color":"#ffffff","shadow":25},"output":{"square":true,"padding":0.06,"longEdge":2000,"format":"jpeg","quality":92}}"""),
        P("storeTransparent", "کالا بی‌پس‌زمینه (PNG)", "کالا روی زمینهٔ شفاف، برای طراحی و بنر.", "store",
            """{"adjust":{"clarity":10,"sharpen":35},"background":{"remove":true,"color":"transparent"},"output":{"format":"png"}}"""),
    };

    public static Preset? Find(string key) => All.FirstOrDefault(p => p.Key.Equals(key, StringComparison.OrdinalIgnoreCase));

    private static Preset P(string key, string title, string help, string kind, string json) => new(key, title, help, kind, Recipe.Parse(json));
}
