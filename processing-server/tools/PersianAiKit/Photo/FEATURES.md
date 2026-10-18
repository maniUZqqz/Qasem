# ابزارهای ویرایشگرِ عکس

> این فایل از روی کد ساخته می‌شود (`Run-SelfTest.bat --write-docs`) — دستی ویرایش نکنید. همان فهرست منبعِ لغزنده‌های صفحهٔ وب و ابزارهای هوشِ مصنوعی (`GET /api/tools`) است.

همهٔ این‌ها در **«نسخهٔ ویرایش» (recipe)** جمع می‌شوند؛ عکسِ اصلی دست نمی‌خورد. ترتیبِ اجرا مثلِ Camera Raw:
ترمیمِ لکه ⇐ تعادلِ سفیدی و نوردهی ⇐ مه‌زدایی ⇐ روشنی‌ها/سایه‌ها ⇐ منحنی‌ها ⇐ بافت/وضوح ⇐ رنگ ⇐ نویزگیری و شارپ ⇐ لنز، چرخش، برش ⇐ وینیت و دانه ⇐ پس‌زمینه ⇐ خروجی.

## ۱. لغزنده‌ها (`recipe.adjust`)

### نور
نوردهی، کنتراست، روشنی‌ها و سایه‌ها — بیشترِ بهتر شدنِ یک عکس از همین‌جاست.

| کلید | نام | بازه | پیش‌فرض | معادلِ فتوشاپ | کارش |
|---|---|---|---|---|---|
| `exposure` | نوردهی | -4 تا 4 EV | 0 | Exposure | روشنیِ کلی به واحدِ «استاپ» مثلِ دوربین؛ +۱ یعنی نورِ دو برابر. |
| `contrast` | کنتراست | -100 تا 100 | 0 | Brightness/Contrast، Exposure & Contrast | فاصلهٔ تیره‌ها و روشن‌ها (منحنیِ S). |
| `highlights` | روشنی‌ها | -100 تا 100 | 0 | Highlights، Shadows/Highlights | منفی ⇒ برگرداندنِ جزئیاتِ آسمان و بخش‌های سوخته (محلی و لبه‌آگاه). |
| `shadows` | سایه‌ها | -100 تا 100 | 0 | Shadows، Shadows/Highlights | مثبت ⇒ باز کردنِ سایه‌های تیره (مثلاً صورت در ضدنور) بی هاله. |
| `whites` | سفیدها | -100 تا 100 | 0 | Whites | نقطهٔ سفید: مثبت ⇒ روشن‌ترین بخش‌ها سفیدتر. |
| `blacks` | سیاه‌ها | -100 تا 100 | 0 | Blacks | نقطهٔ سیاه: منفی ⇒ سیاه‌ترها عمیق‌تر؛ مثبت ⇒ ظاهرِ مات. |
| `brightness` | روشنیِ میانه | -100 تا 100 | 0 | Brightness، Levels (gamma) | روشن یا تیره کردنِ میانه‌ها بی دست زدن به سیاه و سفیدِ کامل. |

### رنگ
تعادلِ سفیدی (ته‌رنگ) و شدتِ رنگ‌ها.

| کلید | نام | بازه | پیش‌فرض | معادلِ فتوشاپ | کارش |
|---|---|---|---|---|---|
| `temperature` | دما | -100 تا 100 | 0 | White Balance (Temp) | منفی ⇒ آبی‌تر (سردتر)، مثبت ⇒ زردتر (گرم‌تر). رفعِ زردیِ نورِ لامپ یا آبیِ هوای ابری. |
| `tint` | ته‌رنگ | -100 تا 100 | 0 | White Balance (Tint) | منفی ⇒ سبزتر، مثبت ⇒ ارغوانی‌تر. رفعِ سبزیِ نورِ مهتابی. |
| `vibrance` | وایبرنس | -100 تا 100 | 0 | Vibrance | افزایشِ هوشمندِ رنگ: رنگ‌های کم‌رنگ بیشتر، رنگِ پوست کمتر. |
| `saturation` | اشباع | -100 تا 100 | 0 | Saturation، Hue/Saturation، Desaturate | شدتِ همهٔ رنگ‌ها به یک اندازه؛ −۱۰۰ ⇒ سیاه‌وسفید. |

### رنگ‌به‌رنگ (HSL)
فام، اشباع و روشنیِ هر خانوادهٔ رنگ جداگانه.

| کلید | نام | بازه | پیش‌فرض | معادلِ فتوشاپ | کارش |
|---|---|---|---|---|---|
| `redHue` | فامِ قرمز | -100 تا 100 | 0 | HSL (Hue)، Hue/Saturation، Replace Color | چرخاندنِ رنگِ قرمز به سمتِ رنگ‌های همسایه. |
| `redSat` | اشباعِ قرمز | -100 تا 100 | 0 | HSL (Saturation)، Selective Color | شدتِ رنگِ قرمز. |
| `redLum` | روشنیِ قرمز | -100 تا 100 | 0 | HSL (Luminance)، Black & White | روشن یا تیره کردنِ قرمز (مثلاً آسمانِ آبی تیره‌تر). |
| `orangeHue` | فامِ نارنجی | -100 تا 100 | 0 | HSL (Hue)، Hue/Saturation، Replace Color | چرخاندنِ رنگِ نارنجی به سمتِ رنگ‌های همسایه. |
| `orangeSat` | اشباعِ نارنجی | -100 تا 100 | 0 | HSL (Saturation)، Selective Color | شدتِ رنگِ نارنجی. |
| `orangeLum` | روشنیِ نارنجی | -100 تا 100 | 0 | HSL (Luminance)، Black & White | روشن یا تیره کردنِ نارنجی (مثلاً آسمانِ آبی تیره‌تر). |
| `yellowHue` | فامِ زرد | -100 تا 100 | 0 | HSL (Hue)، Hue/Saturation، Replace Color | چرخاندنِ رنگِ زرد به سمتِ رنگ‌های همسایه. |
| `yellowSat` | اشباعِ زرد | -100 تا 100 | 0 | HSL (Saturation)، Selective Color | شدتِ رنگِ زرد. |
| `yellowLum` | روشنیِ زرد | -100 تا 100 | 0 | HSL (Luminance)، Black & White | روشن یا تیره کردنِ زرد (مثلاً آسمانِ آبی تیره‌تر). |
| `greenHue` | فامِ سبز | -100 تا 100 | 0 | HSL (Hue)، Hue/Saturation، Replace Color | چرخاندنِ رنگِ سبز به سمتِ رنگ‌های همسایه. |
| `greenSat` | اشباعِ سبز | -100 تا 100 | 0 | HSL (Saturation)، Selective Color | شدتِ رنگِ سبز. |
| `greenLum` | روشنیِ سبز | -100 تا 100 | 0 | HSL (Luminance)، Black & White | روشن یا تیره کردنِ سبز (مثلاً آسمانِ آبی تیره‌تر). |
| `aquaHue` | فامِ فیروزه‌ای | -100 تا 100 | 0 | HSL (Hue)، Hue/Saturation، Replace Color | چرخاندنِ رنگِ فیروزه‌ای به سمتِ رنگ‌های همسایه. |
| `aquaSat` | اشباعِ فیروزه‌ای | -100 تا 100 | 0 | HSL (Saturation)، Selective Color | شدتِ رنگِ فیروزه‌ای. |
| `aquaLum` | روشنیِ فیروزه‌ای | -100 تا 100 | 0 | HSL (Luminance)، Black & White | روشن یا تیره کردنِ فیروزه‌ای (مثلاً آسمانِ آبی تیره‌تر). |
| `blueHue` | فامِ آبی | -100 تا 100 | 0 | HSL (Hue)، Hue/Saturation، Replace Color | چرخاندنِ رنگِ آبی به سمتِ رنگ‌های همسایه. |
| `blueSat` | اشباعِ آبی | -100 تا 100 | 0 | HSL (Saturation)، Selective Color | شدتِ رنگِ آبی. |
| `blueLum` | روشنیِ آبی | -100 تا 100 | 0 | HSL (Luminance)، Black & White | روشن یا تیره کردنِ آبی (مثلاً آسمانِ آبی تیره‌تر). |
| `purpleHue` | فامِ بنفش | -100 تا 100 | 0 | HSL (Hue)، Hue/Saturation، Replace Color | چرخاندنِ رنگِ بنفش به سمتِ رنگ‌های همسایه. |
| `purpleSat` | اشباعِ بنفش | -100 تا 100 | 0 | HSL (Saturation)، Selective Color | شدتِ رنگِ بنفش. |
| `purpleLum` | روشنیِ بنفش | -100 تا 100 | 0 | HSL (Luminance)، Black & White | روشن یا تیره کردنِ بنفش (مثلاً آسمانِ آبی تیره‌تر). |
| `magentaHue` | فامِ ارغوانی | -100 تا 100 | 0 | HSL (Hue)، Hue/Saturation، Replace Color | چرخاندنِ رنگِ ارغوانی به سمتِ رنگ‌های همسایه. |
| `magentaSat` | اشباعِ ارغوانی | -100 تا 100 | 0 | HSL (Saturation)، Selective Color | شدتِ رنگِ ارغوانی. |
| `magentaLum` | روشنیِ ارغوانی | -100 تا 100 | 0 | HSL (Luminance)، Black & White | روشن یا تیره کردنِ ارغوانی (مثلاً آسمانِ آبی تیره‌تر). |

### رنگ‌دهیِ سایه و روشنی
رنگِ دلخواه در سایه‌ها و روشنی‌ها (حال‌وهوای سینمایی).

| کلید | نام | بازه | پیش‌فرض | معادلِ فتوشاپ | کارش |
|---|---|---|---|---|---|
| `shadowsHue` | فامِ سایه‌ها | 0 تا 360 ° | 220 | Color Grading، Color Balance | رنگی که به سایه‌ها افزوده می‌شود (درجه روی دایرهٔ رنگ). |
| `shadowsSat` | شدتِ رنگِ سایه‌ها | 0 تا 100 | 0 | Color Grading | ۰ ⇒ بی‌اثر. |
| `highlightsHue` | فامِ روشنی‌ها | 0 تا 360 ° | 40 | Color Grading | رنگی که به روشنی‌ها افزوده می‌شود. |
| `highlightsSat` | شدتِ رنگِ روشنی‌ها | 0 تا 100 | 0 | Color Grading | ۰ ⇒ بی‌اثر. |
| `gradingBalance` | تعادل | -100 تا 100 | 0 | Color Grading (Balance) | منفی ⇒ سهمِ سایه‌ها بیشتر، مثبت ⇒ سهمِ روشنی‌ها بیشتر. |

### سطوح (Levels)
نقطهٔ سیاه، نقطهٔ سفید و گامای میانه‌ها.

| کلید | نام | بازه | پیش‌فرض | معادلِ فتوشاپ | کارش |
|---|---|---|---|---|---|
| `levelsBlack` | سیاهِ ورودی | 0 تا 250 | 0 | Levels | هر چه تیره‌تر از این است سیاهِ کامل می‌شود. |
| `levelsWhite` | سفیدِ ورودی | 5 تا 255 | 255 | Levels | هر چه روشن‌تر از این است سفیدِ کامل می‌شود. |
| `levelsGamma` | گامای میانه | 0.2 تا 5 | 1 | Levels | بیشتر از ۱ ⇒ میانه‌ها روشن‌تر. |

### وضوح و مه
بافت، وضوح (کنتراستِ محلی) و مه‌زدایی.

| کلید | نام | بازه | پیش‌فرض | معادلِ فتوشاپ | کارش |
|---|---|---|---|---|---|
| `texture` | بافت | -100 تا 100 | 0 | Texture | جزئیاتِ ریز تا متوسط (پوست، برگ، پارچه): مثبت ⇒ پررنگ‌تر، منفی ⇒ نرم‌تر. |
| `clarity` | وضوح | -100 تا 100 | 0 | Clarity، High Pass | کنتراستِ محلیِ میانه‌ها و حسِ عمق؛ منفی ⇒ نرم و رؤیایی. |
| `dehaze` | مه‌زدایی | -100 تا 100 | 0 | Dehaze | برداشتنِ مه و غبار (منفی ⇒ مه افزودن). |

### جزئیات
شارپ و نویزگیری.

| کلید | نام | بازه | پیش‌فرض | معادلِ فتوشاپ | کارش |
|---|---|---|---|---|---|
| `sharpen` | شارپ | 0 تا 150 | 0 | Sharpening، Unsharp Mask، Smart Sharpen | تیز کردنِ لبه‌ها (ماسکِ غیرشارپ روی روشنایی، بی رنگ‌پریدگی). |
| `sharpenRadius` | شعاعِ شارپ | 0.5 تا 3 px | 1 | Sharpening (Radius) | اندازهٔ لبه‌هایی که تیز می‌شوند (پیکسل در اندازهٔ اصلی). |
| `sharpenMasking` | ماسکِ شارپ | 0 تا 100 | 0 | Sharpening (Masking)، Sharpen Edges | بیشتر ⇒ فقط لبه‌های قوی تیز می‌شوند؛ پوست و آسمان دست نمی‌خورد. |
| `noiseLuma` | نویزگیریِ روشنایی | 0 تا 100 | 0 | Noise Reduction، Reduce Noise، Despeckle | دانه‌های ریزِ روشن و تیره (عکسِ شب و ISO بالا). |
| `noiseColor` | نویزگیریِ رنگ | 0 تا 100 | 0 | Noise Reduction (Color) | لکه‌های رنگیِ ریز در سایه‌ها. |

### افکت
وینیت و دانه.

| کلید | نام | بازه | پیش‌فرض | معادلِ فتوشاپ | کارش |
|---|---|---|---|---|---|
| `vignette` | وینیت | -100 تا 100 | 0 | Vignette | منفی ⇒ گوشه‌ها تیره‌تر (تمرکز روی سوژه)، مثبت ⇒ روشن‌تر. |
| `vignetteMidpoint` | اندازهٔ وینیت | 0 تا 100 | 50 | Vignette (Midpoint) | کمتر ⇒ وینیت به وسط نزدیک‌تر. |
| `vignetteFeather` | نرمیِ وینیت | 0 تا 100 | 50 | Vignette (Feather) | بیشتر ⇒ گذارِ نرم‌تر. |
| `grain` | دانه | 0 تا 100 | 0 | Grain، Add Noise | دانهٔ فیلمی. |
| `grainSize` | اندازهٔ دانه | 0 تا 100 | 25 | Grain (Size) | درشتیِ دانه. |

### لنز
اصلاحِ اعوجاجِ لنز. برش و چرخش در ابزارِ برش است.

| کلید | نام | بازه | پیش‌فرض | معادلِ فتوشاپ | کارش |
|---|---|---|---|---|---|
| `distortion` | اعوجاجِ لنز | -100 تا 100 | 0 | Lens Corrections (Distortion) | مثبت ⇒ رفعِ حالتِ بشکه‌ای (لنزِ واید)، منفی ⇒ رفعِ حالتِ بالشتکی. |
| `lensVignette` | تاریکیِ گوشه‌های لنز | 0 تا 100 | 0 | Lens Corrections (Vignetting) | مثبت ⇒ روشن کردنِ گوشه‌هایی که لنز تیره کرده. |

## ۲. ابزارهای دیگر

| بخش | در recipe | کارش |
|---|---|---|
| منحنیِ تُن | `curve.rgb`، `curve.red/green/blue`: نقاطِ `[ورودی، خروجی]` بینِ ۰ و ۲۵۵ | منحنیِ نرم و یکنوا (Fritsch–Carlson) — Curves و Tone Curve |
| برش، چرخش، قرینه | `crop`: `x,y,w,h` (۰ تا ۱)، `angle` (−۴۵ تا ۴۵°)، `flipH`، `flipV` | چرخش خودش کمی بزرگ می‌کند تا گوشهٔ خالی نماند — Crop، Straighten، Flip |
| ترمیمِ لکه | `spots`: `[{x,y,r}]` به نسبتِ عکس | پر کردن از اطراف (inpaint) — Spot Healing، Dust & Scratches |
| حذفِ پس‌زمینه | `background`: `remove`، `method` (`auto`/`quick`/`ai`)، `color` (`#rrggbb` یا `transparent`)، `cleanup` (۰ تا ۱۰۰، −۱ = خودکار)، `shadow` | روشِ سبک بی مدل برای زمینهٔ ساده/استودیویی (زیرِ یک ثانیه) یا BiRefNet برای هر زمینه (سنگین، سرور)؛ تمیزکاریِ خودکارِ لبه با سنجشِ هاله روی رنگِ مخالف؛ قلمِ اصلاحِ ماسک در صفحه — Remove Background، Select Subject، Refine Edge، Decontaminate Colors |
| خروجی | `output`: `format` (jpeg/png/webp)، `quality`، `longEdge`، `square`، `padding`، `upscale` (۱/۲/۴)، `sharpen` | قابِ مربعِ فروشگاه (کالا وسط)، بزرگ‌نماییِ هوشمند، شارپِ نهایی — Export، Image Size، Super Resolution |
| خودکار | `POST /api/docs/{id}/auto` | رایگان و بی‌اینترنت: تعادلِ سفیدی، نوردهی، سیاه/سفید، روشنی‌ها/سایه‌ها، کنتراست، مه، وایبرنس، نویز، شارپ — Auto Tone/Contrast/Color |
| ویرایشِ هوشمند | `POST /api/docs/{id}/ai-edit` | هوشِ مصنوعیِ بینا عکس (کوچک) و اندازه‌گیری‌ها را می‌بیند و نسخه را پیشنهاد می‌دهد؛ یک بار نتیجه را می‌بیند و اصلاح می‌کند — AI.md |

## ۳. فیلترهای آماده (پریست)

در صفحه زبانهٔ «فیلتر»؛ در API کلیدِ `preset` در نسخه (اول فیلتر، بعد بقیهٔ نسخه روی آن).

| کلید | نام | کارش | نسخه |
|---|---|---|---|
| `clean` | روشن و تمیز | کمی روشن‌تر، سایه‌ها باز، رنگ کمی زنده‌تر — مناسبِ بیشترِ عکس‌ها. | `{"adjust":{"exposure":0.15,"highlights":-20,"shadows":25,"whites":10,"vibrance":15,"clarity":8}}` |
| `vivid` | پرجلوه | رنگ و کنتراستِ بیشتر، بی آن‌که پوست نارنجی شود. | `{"adjust":{"vibrance":35,"saturation":8,"contrast":18,"clarity":15,"dehaze":8}}` |
| `warm` | گرم | نورِ عصرگاهی: زردتر و دلنشین‌تر. | `{"adjust":{"temperature":18,"tint":3,"vibrance":10,"highlightsSat":15}}` |
| `cool` | سرد | آبی‌تر و تمیزتر، سایه‌های کمی آبی. | `{"adjust":{"temperature":-15,"vibrance":5,"shadowsSat":15}}` |
| `bw` | سیاه‌وسفید | سیاه‌وسفیدِ نرم با کمی کنتراست. | `{"adjust":{"saturation":-100,"contrast":20,"clarity":10}}` |
| `bwContrast` | سیاه‌وسفیدِ پرکنتراست | سیاه‌های عمیق، سفیدهای درخشان، دانهٔ فیلم. | `{"adjust":{"saturation":-100,"contrast":45,"blacks":-15,"whites":15,"clarity":25,"redLum":15,"blueLum":-20,"grain":15}}` |
| `matte` | فیلمیِ مات | سیاه‌های شسته، رنگِ ملایم و دانه — حالِ عکسِ فیلم. | `{"adjust":{"saturation":-15,"grain":20,"shadowsHue":200,"shadowsSat":10,"highlightsHue":45,"highlightsSat":10},"curve":{"rgb":[[0,30],[64,70],[192,190],[255,242]]}}` |
| `vintage` | قدیمی | گرم، کم‌رنگ، با گوشه‌های تیره و دانه. | `{"adjust":{"temperature":15,"saturation":-25,"contrast":-10,"vignette":-25,"grain":25},"curve":{"rgb":[[0,25],[255,235]]}}` |
| `cinematic` | سینمایی | سایه‌های فیروزه‌ای، روشنی‌های نارنجی (تیل و نارنجی). | `{"adjust":{"contrast":15,"saturation":-10,"shadowsHue":190,"shadowsSat":25,"highlightsHue":35,"highlightsSat":20,"vignette":-15}}` |
| `portrait` | پرتره | پوستِ نرم‌تر، سایه‌های صورت باز، رنگِ طبیعی. | `{"adjust":{"texture":-20,"clarity":-5,"shadows":15,"vibrance":10,"orangeLum":10,"orangeSat":-5}}` |
| `landscape` | منظره | آسمانِ پررنگ، مه کمتر، جزئیاتِ بیشتر. | `{"adjust":{"dehaze":15,"vibrance":30,"clarity":20,"blueSat":15,"greenSat":10,"highlights":-30,"shadows":20}}` |
| `food` | غذا | گرم و اشتهاآور، جزئیاتِ تیز. | `{"adjust":{"temperature":10,"vibrance":25,"clarity":10,"shadows":15,"sharpen":40,"sharpenMasking":30}}` |
| `store` | عکسِ فروشگاهی | پس‌زمینهٔ سفید، قابِ مربعِ ۲۰۰۰ با حاشیهٔ ۶٪، سفیدهای تمیز و شارپ — برای دیجی‌کالا، باسلام، اینستاگرام. | `{"adjust":{"whites":15,"clarity":10,"vibrance":10,"sharpen":40,"sharpenMasking":40},"background":{"remove":true,"method":"auto","color":"#ffffff","cleanup":-1,"shadow":25},"output":{"format":"jpeg","quality":92,"longEdge":2000,"square":true,"padding":0.06,"upscale":1,"sharpen":0}}` |
| `storeTransparent` | کالا بی‌پس‌زمینه (PNG) | کالا روی زمینهٔ شفاف، برای طراحی و بنر. | `{"adjust":{"clarity":10,"sharpen":35},"background":{"remove":true,"method":"auto","color":"transparent","cleanup":-1,"shadow":0},"output":{"format":"png","quality":90,"longEdge":0,"square":false,"padding":0.06,"upscale":1,"sharpen":0}}` |

## ۴. پوششِ ۶۲ قابلیتِ «ارتقای کیفیت»ِ فتوشاپ

از `research/Photoshop_Features_FA.xlsx` (ستونِ «ارتقای کیفیت»). ✓ ساخته شده · ◐ بخشی · ⏳ در برنامه · ✗ نه.

| ردیف | قابلیت | وضعیت | این‌جا |
|---|---|---|---|
| 60 | Brightness/Contrast | ✓ | brightness، contrast |
| 61 | Levels | ✓ | levelsBlack، levelsWhite، levelsGamma |
| 62 | Curves | ✓ | curve (rgb و هر کانال) |
| 63 | Exposure | ✓ | exposure (در فضای خطی) |
| 64 | Light (لایهٔ جدید) | ✓ | exposure، contrast، highlights، shadows، whites، blacks |
| 65 | Color and Vibrance | ✓ | temperature، tint، vibrance، saturation |
| 67 | Color Balance | ◐ | رنگ‌دهیِ سایه و روشنی (shadowsHue/Sat، highlightsHue/Sat)؛ میانه‌ها جدا نه |
| 77 | Shadows/Highlights | ✓ | highlights، shadows (لبه‌آگاه، فیلترِ هدایت‌شده) |
| 83 | Auto Tone | ✓ | «خودکار» (رایگان، قاعده‌ای) |
| 84 | Auto Contrast | ✓ | «خودکار»: whites/blacks تا دو سرِ هیستوگرام |
| 85 | Auto Color | ✓ | «خودکار»: تعادلِ سفیدی از رنگ‌های خنثی |
| 86 | Clarity and Dehaze | ✓ | clarity، dehaze |
| 91 | Camera Raw | ◐ | همان ترتیب و ابزارها؛ فایلِ RAWِ دوربین نه (JPEG، PNG، WebP، TIFF ۸ و ۱۶ بیتی) |
| 93 | White Balance | ✓ | temperature، tint |
| 94 | Exposure & Contrast | ✓ | exposure، contrast |
| 95 | Highlights & Shadows | ✓ | highlights، shadows |
| 96 | Whites & Blacks | ✓ | whites، blacks |
| 97 | Texture | ✓ | texture |
| 98 | Clarity | ✓ | clarity |
| 99 | Dehaze | ✓ | dehaze (پیشینِ کانالِ تیره) |
| 100 | Vibrance & Saturation | ✓ | vibrance (با محافظتِ پوست)، saturation |
| 101 | Tone Curve | ✓ | curve |
| 105 | Sharpening | ✓ | sharpen، sharpenRadius، sharpenMasking |
| 106 | Noise Reduction (manual) | ✓ | noiseLuma، noiseColor |
| 107 | Denoise (AI) | ◐ | noiseLuma با Non-Local Means (بی هوشِ مصنوعی)؛ مدلِ نویزگیری در برنامه |
| 108 | Raw Details | ✗ | به فایلِ RAW نیاز دارد |
| 109 | Super Resolution | ✓ | output.upscale ×۲ و ×۴ (Real-ESRGAN) |
| 110 | Lens Profile Corrections | ◐ | distortion و lensVignette دستی؛ پایگاهِ پروفایلِ لنز نه |
| 111 | Chromatic Aberration & Defringe | ⏳ | برنامه |
| 112 | Manual Distortion & Vignetting | ✓ | distortion، lensVignette |
| 113 | Geometry / Upright | ◐ | چرخش و صاف کردن دستی (crop.angle)؛ آپ‌رایتِ خودکار در برنامه |
| 128 | Distraction Removal | ◐ | ترمیمِ لکهٔ کوچک (spots)؛ حذفِ چیزِ بزرگ با مدلِ LaMa در برنامه |
| 131 | Auto (Camera Raw) | ✓ | «خودکار» + «ویرایشِ هوشمند» (هوشِ مصنوعیِ بینا) |
| 133 | Photo Merge (HDR / Panorama) | ⏳ | برنامه (چند عکس) |
| 176 | Remove Reflections | ✗ | مدلِ بزرگ لازم است |
| 231 | Resample: Preserve Details | ✓ | خروجی با Lanczos4 |
| 232 | Preserve Details 2.0 | ✓ | output.upscale (Real-ESRGAN) |
| 247 | Lens Correction Filter | ◐ | مثلِ ۱۱۰ و ۱۱۲ |
| 248 | Adaptive Wide Angle | ⏳ | برنامه |
| 256 | Auto-Blend: Stack Images (focus) | ⏳ | برنامه (چند عکس) |
| 257 | Merge to HDR Pro | ⏳ | برنامه (چند عکس) |
| 259 | Stack Mode: Median | ⏳ | برنامه (چند عکس: حذفِ رهگذر و نویز) |
| 260 | Stack Mode: Mean | ⏳ | برنامه (چند عکس) |
| 282 | Sharpen / Sharpen More | ✓ | sharpen |
| 283 | Sharpen Edges | ✓ | sharpenMasking |
| 284 | Smart Sharpen | ◐ | ماسکِ غیرشارپ با ماسکِ لبه؛ رفعِ تاریِ حرکت نه |
| 285 | Unsharp Mask | ✓ | sharpen، sharpenRadius |
| 286 | AI Sharpen / AI Denoise | ◐ | output.upscale (Real-ESRGAN جزئیات را هم بازسازی می‌کند) |
| 287 | Shake Reduction | ✗ | در خودِ فتوشاپ هم حذف شده |
| 289 | Despeckle | ✓ | noiseLuma |
| 290 | Dust & Scratches | ◐ | spots (ترمیمِ نقطه‌ای) |
| 291 | Median | ◐ | noiseLuma |
| 292 | Reduce Noise | ✓ | noiseLuma، noiseColor |
| 327 | High Pass | ✓ | clarity، texture |
| 389 | Colorize (Neural) | ✗ | مدلِ رنگی‌کردن لازم است |
| 390 | Super Zoom | ✓ | output.upscale |
| 392 | JPEG Artifacts Removal | ◐ | Real-ESRGAN (مدلِ general برای عکسِ فشرده آموزش دیده) + noiseLuma |
| 393 | Photo Restoration | ⏳ | برنامه |
| 400 | Enhance Detail | ◐ | texture + output.upscale |
| 404 | Generative Upscale | ◐ | Real-ESRGAN (نه مولد) |
| 435 | Bit Depth (8/16/32) | ◐ | ورودیِ ۱۶ بیتی با دقتِ اعشاری پردازش می‌شود؛ خروجی ۸ بیتی |
| 469 | Color Cast Removal (Average) | ✓ | «خودکار» (میانگینِ رنگ‌های خنثی) |

جمع: **35 ساخته شده، 15 بخشی، 8 در برنامه، 4 نه** (از 62).
