# ابزارهای ویرایشگرِ ویدیو

> این فایل از روی کد ساخته می‌شود (`Run-SelfTest.bat --write-docs`) — دستی ویرایش نکنید. همان فهرست منبعِ لغزنده‌های صفحهٔ وب و ابزارهای هوشِ مصنوعی (`GET /api/tools`) است.

همهٔ این‌ها در **«نسخهٔ ویرایش» (recipe)** جمع می‌شوند؛ فایلِ اصلی دست نمی‌خورد. رنگ و نور همان ریاضیِ ویرایشگرِ عکس است و در یک LUTِ سه‌بعدی خلاصه می‌شود (مثلِ لومتری).

ترتیبِ تصویر: درهم‌رفتگی ⇐ HDR به SDR ⇐ تثبیت ⇐ حذفِ بازه‌ها ⇐ سرعت ⇐ لنز ⇐ چرخش، برش، قرینه ⇐ نویزگیری ⇐ LUTِ رنگ ⇐ وضوح ⇐ شارپ ⇐ وینیت، دانه ⇐ قاب ⇐ اندازه ⇐ محدودهٔ پخش ⇐ محو.

ترتیبِ صدا: حذفِ بازه‌ها ⇐ سرعت ⇐ غرش ⇐ وزوزِ برق ⇐ کلیک ⇐ نویز ⇐ سین ⇐ اکولایزر ⇐ کمپرسور ⇐ بلندی ⇐ هم‌سطح‌سازی ⇐ محو.

## ۱. لغزنده‌ها (`recipe.adjust`)

### نور
نوردهی، کنتراست، روشنی‌ها و سایه‌ها — بخشِ Basicِ لومتری.

| کلید | نام | بازه | پیش‌فرض | معادلِ پریمیر | کارش |
|---|---|---|---|---|---|
| `exposure` | نوردهی | -3 تا 3 EV | 0 | Lumetri: Exposure | روشنیِ کلی به واحدِ «استاپ»؛ +۱ یعنی نورِ دو برابر. |
| `contrast` | کنتراست | -100 تا 100 | 0 | Lumetri: Contrast، Brightness & Contrast | فاصلهٔ تیره‌ها و روشن‌ها (منحنیِ S). |
| `highlights` | روشنی‌ها | -100 تا 100 | 0 | Lumetri: Highlights | منفی ⇒ برگرداندنِ جزئیاتِ آسمان و بخش‌های سوخته. |
| `shadows` | سایه‌ها | -100 تا 100 | 0 | Lumetri: Shadows | مثبت ⇒ باز کردنِ سایه‌های تیره (صورت در ضدنور). |
| `whites` | سفیدها | -100 تا 100 | 0 | Lumetri: Whites | نقطهٔ سفید: مثبت ⇒ روشن‌ترین بخش‌ها سفیدتر. |
| `blacks` | سیاه‌ها | -100 تا 100 | 0 | Lumetri: Blacks، Faded Film | نقطهٔ سیاه: منفی ⇒ سیاه‌ترها عمیق‌تر؛ مثبت ⇒ ظاهرِ مات (Faded Film). |
| `brightness` | روشنیِ میانه | -100 تا 100 | 0 | Brightness، Gamma Correction | روشن یا تیره کردنِ میانه‌ها بی دست زدن به سیاه و سفیدِ کامل. |

### رنگ
تعادلِ سفیدی و شدتِ رنگ‌ها.

| کلید | نام | بازه | پیش‌فرض | معادلِ پریمیر | کارش |
|---|---|---|---|---|---|
| `temperature` | دما | -100 تا 100 | 0 | Lumetri: White Balance (Temperature) | منفی ⇒ آبی‌تر (سردتر)، مثبت ⇒ زردتر (گرم‌تر). رفعِ زردیِ لامپ یا آبیِ هوای ابری. |
| `tint` | ته‌رنگ | -100 تا 100 | 0 | Lumetri: White Balance (Tint) | منفی ⇒ سبزتر، مثبت ⇒ ارغوانی‌تر. رفعِ سبزیِ نورِ مهتابی. |
| `vibrance` | وایبرنس | -100 تا 100 | 0 | Lumetri: Vibrance | افزایشِ هوشمندِ رنگ: رنگ‌های کم‌رنگ بیشتر، رنگِ پوست کمتر. |
| `saturation` | اشباع | -100 تا 100 | 0 | Lumetri: Saturation، Black & White | شدتِ همهٔ رنگ‌ها؛ −۱۰۰ ⇒ سیاه‌وسفید. |

### رنگ‌به‌رنگ (HSL)
فام، اشباع و روشنیِ هر خانوادهٔ رنگ جداگانه (HSL Secondary).

| کلید | نام | بازه | پیش‌فرض | معادلِ پریمیر | کارش |
|---|---|---|---|---|---|
| `redHue` | فامِ قرمز | -100 تا 100 | 0 | HSL Secondary، Change Color | چرخاندنِ رنگِ قرمز به سمتِ رنگ‌های همسایه. |
| `redSat` | اشباعِ قرمز | -100 تا 100 | 0 | HSL Secondary، Hue vs Sat | شدتِ رنگِ قرمز. |
| `redLum` | روشنیِ قرمز | -100 تا 100 | 0 | HSL Secondary، Hue vs Luma | روشن یا تیره کردنِ قرمز (مثلاً آسمانِ آبی تیره‌تر). |
| `orangeHue` | فامِ نارنجی | -100 تا 100 | 0 | HSL Secondary، Change Color | چرخاندنِ رنگِ نارنجی به سمتِ رنگ‌های همسایه. |
| `orangeSat` | اشباعِ نارنجی | -100 تا 100 | 0 | HSL Secondary، Hue vs Sat | شدتِ رنگِ نارنجی. |
| `orangeLum` | روشنیِ نارنجی | -100 تا 100 | 0 | HSL Secondary، Hue vs Luma | روشن یا تیره کردنِ نارنجی (مثلاً آسمانِ آبی تیره‌تر). |
| `yellowHue` | فامِ زرد | -100 تا 100 | 0 | HSL Secondary، Change Color | چرخاندنِ رنگِ زرد به سمتِ رنگ‌های همسایه. |
| `yellowSat` | اشباعِ زرد | -100 تا 100 | 0 | HSL Secondary، Hue vs Sat | شدتِ رنگِ زرد. |
| `yellowLum` | روشنیِ زرد | -100 تا 100 | 0 | HSL Secondary، Hue vs Luma | روشن یا تیره کردنِ زرد (مثلاً آسمانِ آبی تیره‌تر). |
| `greenHue` | فامِ سبز | -100 تا 100 | 0 | HSL Secondary، Change Color | چرخاندنِ رنگِ سبز به سمتِ رنگ‌های همسایه. |
| `greenSat` | اشباعِ سبز | -100 تا 100 | 0 | HSL Secondary، Hue vs Sat | شدتِ رنگِ سبز. |
| `greenLum` | روشنیِ سبز | -100 تا 100 | 0 | HSL Secondary، Hue vs Luma | روشن یا تیره کردنِ سبز (مثلاً آسمانِ آبی تیره‌تر). |
| `aquaHue` | فامِ فیروزه‌ای | -100 تا 100 | 0 | HSL Secondary، Change Color | چرخاندنِ رنگِ فیروزه‌ای به سمتِ رنگ‌های همسایه. |
| `aquaSat` | اشباعِ فیروزه‌ای | -100 تا 100 | 0 | HSL Secondary، Hue vs Sat | شدتِ رنگِ فیروزه‌ای. |
| `aquaLum` | روشنیِ فیروزه‌ای | -100 تا 100 | 0 | HSL Secondary، Hue vs Luma | روشن یا تیره کردنِ فیروزه‌ای (مثلاً آسمانِ آبی تیره‌تر). |
| `blueHue` | فامِ آبی | -100 تا 100 | 0 | HSL Secondary، Change Color | چرخاندنِ رنگِ آبی به سمتِ رنگ‌های همسایه. |
| `blueSat` | اشباعِ آبی | -100 تا 100 | 0 | HSL Secondary، Hue vs Sat | شدتِ رنگِ آبی. |
| `blueLum` | روشنیِ آبی | -100 تا 100 | 0 | HSL Secondary، Hue vs Luma | روشن یا تیره کردنِ آبی (مثلاً آسمانِ آبی تیره‌تر). |
| `purpleHue` | فامِ بنفش | -100 تا 100 | 0 | HSL Secondary، Change Color | چرخاندنِ رنگِ بنفش به سمتِ رنگ‌های همسایه. |
| `purpleSat` | اشباعِ بنفش | -100 تا 100 | 0 | HSL Secondary، Hue vs Sat | شدتِ رنگِ بنفش. |
| `purpleLum` | روشنیِ بنفش | -100 تا 100 | 0 | HSL Secondary، Hue vs Luma | روشن یا تیره کردنِ بنفش (مثلاً آسمانِ آبی تیره‌تر). |
| `magentaHue` | فامِ ارغوانی | -100 تا 100 | 0 | HSL Secondary، Change Color | چرخاندنِ رنگِ ارغوانی به سمتِ رنگ‌های همسایه. |
| `magentaSat` | اشباعِ ارغوانی | -100 تا 100 | 0 | HSL Secondary، Hue vs Sat | شدتِ رنگِ ارغوانی. |
| `magentaLum` | روشنیِ ارغوانی | -100 تا 100 | 0 | HSL Secondary، Hue vs Luma | روشن یا تیره کردنِ ارغوانی (مثلاً آسمانِ آبی تیره‌تر). |

### رنگ‌دهیِ سایه و روشنی
رنگِ دلخواه در سایه‌ها و روشنی‌ها (Creative و چرخ‌های رنگ).

| کلید | نام | بازه | پیش‌فرض | معادلِ پریمیر | کارش |
|---|---|---|---|---|---|
| `shadowsHue` | فامِ سایه‌ها | 0 تا 360 ° | 220 | Lumetri: Shadow Tint، Color Wheels | رنگی که به سایه‌ها افزوده می‌شود (درجه روی دایرهٔ رنگ). |
| `shadowsSat` | شدتِ رنگِ سایه‌ها | 0 تا 100 | 0 | Lumetri: Shadow Tint | ۰ ⇒ بی‌اثر. |
| `highlightsHue` | فامِ روشنی‌ها | 0 تا 360 ° | 40 | Lumetri: Highlight Tint | رنگی که به روشنی‌ها افزوده می‌شود. |
| `highlightsSat` | شدتِ رنگِ روشنی‌ها | 0 تا 100 | 0 | Lumetri: Highlight Tint | ۰ ⇒ بی‌اثر. |
| `gradingBalance` | تعادل | -100 تا 100 | 0 | Lumetri: Tint Balance | منفی ⇒ سهمِ سایه‌ها بیشتر، مثبت ⇒ سهمِ روشنی‌ها بیشتر. |

### سطوح و گاما
نقطهٔ سیاه، نقطهٔ سفید و گامای میانه‌ها.

| کلید | نام | بازه | پیش‌فرض | معادلِ پریمیر | کارش |
|---|---|---|---|---|---|
| `levelsBlack` | سیاهِ ورودی | 0 تا 250 | 0 | Levels | هر چه تیره‌تر از این است سیاهِ کامل می‌شود. |
| `levelsWhite` | سفیدِ ورودی | 5 تا 255 | 255 | Levels | هر چه روشن‌تر از این است سفیدِ کامل می‌شود. |
| `levelsGamma` | گامای میانه | 0.2 تا 5 | 1 | Levels، Gamma Correction | بیشتر از ۱ ⇒ میانه‌ها روشن‌تر. |

### جزئیات
شارپ، وضوح و نویزگیریِ تصویر.

| کلید | نام | بازه | پیش‌فرض | معادلِ پریمیر | کارش |
|---|---|---|---|---|---|
| `sharpen` | شارپ | 0 تا 100 | 0 | Lumetri: Sharpen، Sharpen، Unsharp Mask | تیز کردنِ لبه‌ها (شارپِ تطبیقی: لبهٔ قوی کمتر، تا هاله نیفتد). |
| `clarity` | وضوح | -100 تا 100 | 0 | Unsharp Mask (شعاعِ بزرگ) | کنتراستِ محلیِ درشت و حسِ عمق؛ منفی ⇒ نرم و رؤیایی. |
| `denoise` | نویزگیری | 0 تا 100 | 0 | Median، Noise (پلاگین) | دانه‌های روشن و تیره (فیلمِ شب و نورِ کم) — مکانی و زمانی. |
| `denoiseColor` | نویزگیریِ رنگ | 0 تا 100 | 0 | Noise (پلاگین) | لکه‌های رنگیِ ریز در سایه‌ها. |

### افکت
وینیت و دانهٔ فیلم.

| کلید | نام | بازه | پیش‌فرض | معادلِ پریمیر | کارش |
|---|---|---|---|---|---|
| `vignette` | وینیت | 0 تا 100 | 0 | Lumetri: Vignette | تیره کردنِ گوشه‌ها برای تمرکز روی سوژه. |
| `grain` | دانهٔ فیلم | 0 تا 100 | 0 | Noise، Film look | دانهٔ ریزِ متحرک، حسِ فیلم. |

### لنز
اصلاحِ اعوجاجِ لنزِ واید (بشکه‌ای).

| کلید | نام | بازه | پیش‌فرض | معادلِ پریمیر | کارش |
|---|---|---|---|---|---|
| `distortion` | اعوجاجِ لنز | -100 تا 100 | 0 | Lens Distortion | مثبت ⇒ رفعِ حالتِ بشکه‌ای (لنزِ واید، اکشن‌کم)، منفی ⇒ رفعِ حالتِ بالشتکی. |

### صدا
بلندی، کاهشِ نویز و غرش و کلیک، سین‌گیر، اکولایزر و کمپرسور — مثلِ Essential Sound.

| کلید | نام | بازه | پیش‌فرض | معادلِ پریمیر | کارش |
|---|---|---|---|---|---|
| `volume` | بلندی | -20 تا 20 dB | 0 | Audio Gain | افزایش یا کاهشِ صدا (دسی‌بل). برای بلندیِ استانداردِ پخش، «هم‌سطح‌سازی» را روشن کنید. |
| `rumble` | کاهشِ غرش | 0 تا 100 | 0 | Reduce Rumble (Essential Sound) | بریدنِ صداهای خیلی بم: باد، لرزشِ میز، کولر. |
| `noise` | کاهشِ نویز | 0 تا 100 | 0 | Reduce Noise، DeNoise، Adaptive Noise Reduction | هیس و نویزِ ثابتِ پس‌زمینه (تطبیقی: نویز را دنبال می‌کند). |
| `declick` | حذفِ کلیک | 0 تا 100 | 0 | Automatic Click Remover | تق‌تق و خش‌های کوتاه. |
| `deess` | سین‌گیر | 0 تا 100 | 0 | DeEss، DeEsser | نرم کردنِ «س» و «ش»ِ تیز در گفتار. |
| `bass` | بم | -12 تا 12 dB | 0 | Parametric Equalizer | صداهای بم (زیرِ ۱۵۰ هرتز). |
| `presence` | وضوحِ گفتار | -12 تا 12 dB | 0 | Vocal Enhancer، Clarity (EQ) | محدودهٔ ۳ کیلوهرتز: مثبت ⇒ گفتار واضح‌تر و جلوتر. |
| `air` | درخشش | -12 تا 12 dB | 0 | Parametric Equalizer | صداهای زیر (بالای ۹ کیلوهرتز). |
| `compress` | یکدست کردنِ بلندی | 0 تا 100 | 0 | Dynamics، Single-band Compressor، Clarity | کمپرسور: فاصلهٔ آرام و بلند کمتر ⇒ گفتار یکنواخت‌تر. |

## ۲. بخش‌های دیگرِ نسخه

| بخش | در recipe | کارش |
|---|---|---|
| بُرشِ سر و ته | `trim`: `start`، `end` (ثانیه) | In/Out |
| حذفِ بازه‌ها | `cuts`: `[{start,end}]` | Lift/Extract، Ripple Delete؛ «یافتنِ مکث‌ها» پیشنهادش را می‌سازد (مثلِ تشخیصِ مکث در تدوینِ متن‌محور) |
| سرعت و محو | `time`: `speed` (۰٫۲۵ تا ۴)، `smooth` (جریانِ نوری)، `fadeIn`، `fadeOut` | Speed/Duration، Optical Flow، Dip to Black |
| منحنی | `curve.rgb`، `curve.red/green/blue`: نقاطِ `[ورودی، خروجی]` | RGB Curves |
| LUT | `lut`: `file` (.cubeِ بارگذاری‌شده)، `mode` (`input`/`look`)، `amount` | Input LUT، Look |
| برش و صاف کردن | `crop`: `x,y,w,h` (۰ تا ۱)، `angle` (±۴۵°)، `flipH`، `flipV` | Crop، Transform، Flip |
| قابِ خروجی | `frame`: `aspect` (`9:16`، `1:1`، `4:5`، `16:9`)، `fit` (`crop`/`blur`/`black`)، `focusX`، `focusY` | Auto Reframe (دستی)، زمینهٔ محو برای ریلز |
| تثبیت | `stabilize`: `amount` (۰ تا ۱۰۰) | Warp Stabilizer |
| صدا | `audio`: `normalize` (LUFS)، `hum` (۵۰/۶۰)، `mute` | Loudness Normalization، DeHum، Mute |
| خروجی | `output`: `format` (mp4/webm/gif/mp3/wav)، `codec` (h264/h265)، `size` (ضلعِ کوچک)، `fps`، `quality`، `broadcastSafe` | Export Settings، Video Limiter |

## ۳. پریست‌ها

در صفحه زبانهٔ «پریست»؛ در API کلیدِ `preset` در نسخه (اول پریست، بعد بقیهٔ نسخه روی آن).

| کلید | نام | نوع | کارش | نسخه |
|---|---|---|---|---|
| `clean` | روشن و تمیز | look | کمی روشن‌تر، سایه‌ها باز، رنگ کمی زنده‌تر. | `{"adjust":{"exposure":0.15,"highlights":-20,"shadows":20,"whites":10,"vibrance":15}}` |
| `vivid` | پرجلوه | look | رنگ و کنتراستِ بیشتر، بی نارنجی شدنِ پوست. | `{"adjust":{"vibrance":35,"saturation":8,"contrast":18,"clarity":15}}` |
| `warm` | گرم | look | نورِ عصرگاهی. | `{"adjust":{"temperature":18,"tint":3,"vibrance":10,"highlightsSat":15}}` |
| `cool` | سرد | look | آبی‌تر و تمیزتر. | `{"adjust":{"temperature":-15,"vibrance":5,"shadowsSat":15}}` |
| `bw` | سیاه‌وسفید | look | سیاه‌وسفیدِ نرم با کمی کنتراست. | `{"adjust":{"saturation":-100,"contrast":20}}` |
| `cinematic` | سینمایی | look | سایه‌های فیروزه‌ای، روشنی‌های نارنجی (تیل و نارنجی)، گوشه‌های تیره. | `{"adjust":{"contrast":15,"saturation":-10,"shadowsHue":190,"shadowsSat":25,"highlightsHue":35,"highlightsSat":20,"vignette":25}}` |
| `film` | فیلمیِ مات | look | سیاه‌های شسته، رنگِ ملایم و دانه — Faded Film. | `{"adjust":{"saturation":-15,"grain":20,"shadowsHue":200,"shadowsSat":10},"curve":{"rgb":[[0,30],[64,70],[192,190],[255,242]]}}` |
| `vintage` | قدیمی | look | گرم، کم‌رنگ، با گوشه‌های تیره و دانه. | `{"adjust":{"temperature":15,"saturation":-25,"contrast":-10,"vignette":35,"grain":25},"curve":{"rgb":[[0,25],[255,235]]}}` |
| `night` | شب و نورِ کم | look | نویزگیری، سایه‌های بازتر، رنگِ طبیعی‌تر. | `{"adjust":{"denoise":55,"denoiseColor":50,"shadows":25,"blacks":-10,"vibrance":10}}` |
| `voice` | پاک‌سازیِ گفتار | audio | زنجیرهٔ تمیزکاریِ دیالوگ: غرش، نویز، سین، وضوح، کمپرسور و بلندیِ ‎−۱۶. | `{"adjust":{"rumble":40,"noise":40,"deess":30,"presence":3,"compress":40},"audio":{"mute":false,"normalize":-16,"hum":0}}` |
| `voiceStrong` | گفتار در محیطِ پرسروصدا | audio | مثلِ «پاک‌سازیِ گفتار» ولی نویزگیریِ قوی‌تر (خیابان، کولر، باد). | `{"adjust":{"rumble":70,"noise":75,"declick":30,"deess":35,"presence":4,"compress":50},"audio":{"mute":false,"normalize":-16,"hum":0}}` |
| `music` | موسیقی | audio | فقط هم‌سطح‌سازیِ بلندی، بی دست زدن به صدای ساز. | `{"adjust":{},"audio":{"mute":false,"normalize":-14,"hum":0}}` |
| `reels` | ریلز / استوری | output | قابِ عمودیِ ۹:۱۶ (۱۰۸۰×۱۹۲۰) با زمینهٔ محو، بلندیِ ‎−۱۴، MP4. | `{"adjust":{},"frame":{"aspect":"9:16","fit":"blur","focusX":0.5,"focusY":0.5},"audio":{"mute":false,"normalize":-14,"hum":0},"output":{"format":"mp4","codec":"h264","size":1080,"fps":0,"quality":"standard","broadcastSafe":false}}` |
| `square` | پستِ مربع | output | قابِ ۱:۱ (۱۰۸۰×۱۰۸۰)، وسطِ تصویر. | `{"adjust":{},"frame":{"aspect":"1:1","fit":"crop","focusX":0.5,"focusY":0.5},"audio":{"mute":false,"normalize":-14,"hum":0},"output":{"format":"mp4","codec":"h264","size":1080,"fps":0,"quality":"standard","broadcastSafe":false}}` |
| `youtube` | یوتیوب | output | ۱۶:۹، ۱۰۸۰p، کیفیتِ بالا، بلندیِ ‎−۱۴. | `{"adjust":{},"frame":{"aspect":"16:9","fit":"black","focusX":0.5,"focusY":0.5},"audio":{"mute":false,"normalize":-14,"hum":0},"output":{"format":"mp4","codec":"h264","size":1080,"fps":0,"quality":"high","broadcastSafe":false}}` |
| `telegram` | تلگرام و واتس‌اپ (سبک) | output | ۷۲۰p با حجمِ کم برای فرستادن. | `{"adjust":{},"audio":{"mute":false,"normalize":-16,"hum":0},"output":{"format":"mp4","codec":"h264","size":720,"fps":0,"quality":"small","broadcastSafe":false}}` |
| `gif` | GIF | output | گیفِ بی‌صدا، ۴۸۰ پیکسل، ۱۲ فریم در ثانیه. | `{"adjust":{},"output":{"format":"gif","codec":"","size":480,"fps":12,"quality":"standard","broadcastSafe":false}}` |
| `podcast` | فقط صدا (پادکست) | output | MP3 با پاک‌سازیِ گفتار و بلندیِ ‎−۱۶. | `{"adjust":{"rumble":40,"noise":40,"deess":30,"presence":3,"compress":40},"audio":{"mute":false,"normalize":-16,"hum":0},"output":{"format":"mp3","codec":"","size":0,"fps":0,"quality":"standard","broadcastSafe":false}}` |

## ۴. پوششِ ۴۷ قابلیتِ «ارتقای کیفیت»ِ پریمیر

از `research/Premiere_Features_FA.xlsx` (ستونِ «ارتقای کیفیت»). ✓ ساخته شده · ◐ بخشی · ⏳ در برنامه · ✗ نه.

| ردیف | قابلیت | وضعیت | این‌جا |
|---|---|---|---|
| 77 | Optical Flow | ◐ | time.smooth (minterpolate با جبرانِ حرکت) برای آهسته‌نمایی — سنگین؛ فقط سرعتِ کمتر از ۱ |
| 102 | Warp Stabilizer (Analysis) | ✓ | stabilize: پاسِ اول vidstabdetect (ردیابیِ نقاط) |
| 103 | Warp Stabilizer (Method & Framing) | ◐ | vidstabtransform با نرمیِ مسیر و بزرگ‌نماییِ خودکار؛ Subspace Warp و Synthesize Edges نه |
| 104 | Rolling Shutter Repair | ⏳ | برنامه |
| 105 | Lens Distortion | ✓ | adjust.distortion (lenscorrection + بزرگ‌نمایی تا گوشه سیاه نشود) |
| 106 | Reduce Interlace Flicker | ✓ | خودکار: ویدیوی درهم‌رفته با bwdif باز می‌شود |
| 108 | Input LUT | ✓ | lut: {file, mode: "input"} (.cube، پیش از همهٔ رنگ‌ها) |
| 109 | White Balance (Lumetri) | ✓ | temperature، tint (در فضای خطی) |
| 110 | Tone (Lumetri) | ✓ | exposure، contrast، highlights، shadows، whites، blacks |
| 111 | Auto (Lumetri) | ✓ | «خودکار» (رایگان، از روی چند فریمِ نمونه) + «ویرایش با هوشِ مصنوعی» |
| 115 | Sharpen (Lumetri) | ✓ | sharpen (شارپِ تطبیقیِ CAS) |
| 118 | RGB Curves | ✓ | curve.rgb و هر کانال |
| 121 | Color Match | ⏳ | برنامه (هم‌رنگ کردنِ دو کلیپ از آماره‌های رنگ) |
| 127 | Color Management | ◐ | HDR (PQ/HLG) خودکار به SDRِ bt709 با تُن‌مپینگ؛ مدیریتِ کاملِ فضای رنگ نه |
| 139 | Levels (effect) | ✓ | levelsBlack، levelsWhite، levelsGamma |
| 142 | Brightness & Contrast | ✓ | brightness، contrast |
| 146 | Video Limiter | ✓ | output.broadcastSafe (روشنایی ۱۶–۲۳۵، رنگ ۱۶–۲۴۰) |
| 151 | Gamma Correction | ✓ | levelsGamma، brightness |
| 157 | Sharpen (effect) | ✓ | sharpen |
| 158 | Unsharp Mask (effect) | ✓ | clarity (ماسکِ غیرشارپ با شعاعِ بزرگ) |
| 242 | Audio Gain & Normalize | ✓ | volume، audio.normalize |
| 253 | Loudness Meter | ✓ | سنجش: بلندیِ یکپارچه (LUFS)، محدودهٔ بلندی، قلهٔ واقعی (BS.1770) |
| 254 | Auto-Match Loudness | ✓ | audio.normalize (دو پاس، خطی) |
| 258 | Enhance Speech | ◐ | پریستِ «پاک‌سازیِ گفتار» (DSP)؛ مدلِ عصبی (arnndn) در برنامه |
| 259 | Reduce Noise | ✓ | noise (afftdn، تطبیقی) |
| 260 | Reduce Rumble | ✓ | rumble (بالاگذر) |
| 261 | DeHum | ✓ | audio.hum = ۵۰ یا ۶۰ (فیلترِ شکافی روی پایه و سه هماهنگ) + تشخیصِ خودکار |
| 262 | DeEss | ✓ | deess |
| 263 | Reduce Reverb | ✗ | فیلترِ خوبی در FFmpeg نیست؛ مدلِ عصبی لازم است |
| 264 | Clarity: Dynamics & EQ | ✓ | compress + presence |
| 271 | Dynamics | ✓ | compress |
| 273 | Single-band Compressor | ✓ | compress (acompressor) |
| 274 | Multiband Compressor | ⏳ | برنامه |
| 276 | Hard Limiter | ✓ | خودکار بعد از بلند کردنِ صدا (alimiter) و قلهٔ ‎−۱٫۵ dBTP در هم‌سطح‌سازی |
| 277 | DeEsser (effect) | ✓ | deess |
| 280 | Parametric Equalizer | ◐ | سه باند: bass، presence، air |
| 283 | Notch Filter | ✓ | audio.hum |
| 287 | DeNoise | ✓ | noise |
| 288 | Adaptive Noise Reduction | ✓ | noise (نویز را در طولِ زمان دنبال می‌کند) |
| 289 | Automatic Click Remover | ✓ | declick |
| 290 | DeHummer | ✓ | audio.hum |
| 291 | DeReverb | ✗ | مثلِ ۲۶۳ |
| 295 | Mastering | ◐ | پریستِ «موسیقی»: هم‌سطح‌سازی + لیمیتر |
| 296 | Vocal Enhancer | ✓ | presence + پریستِ «پاک‌سازیِ گفتار» |
| 351 | Maximum Render Quality & Maximum Depth | ✓ | تغییرِ اندازه با lanczos، رنگ با LUTِ ۳۳ و درون‌یابیِ چهاروجهی |
| 353 | Loudness Normalization (Export) | ✓ | audio.normalize با قلهٔ واقعیِ ‎−۱٫۵ |
| 367 | Dialogue Cleanup Chain | ✓ | پریستِ «پاک‌سازیِ گفتار»: غرش ⇐ نویز ⇐ سین ⇐ اکولایزر ⇐ کمپرسور ⇐ بلندی |

جمع: **36 ساخته شده، 6 بخشی، 3 در برنامه، 2 نه** (از 47).
