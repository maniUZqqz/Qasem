# صدای فارسی (PersianAiKit.Voice)

همهٔ کارهای **صدا**، آفلاین و روی CPUِ معمولی، آماده برای هر پروژهٔ دیگر. (شناختنِ چهره و مشابه‌یابِ عکس پروژهٔ جداست: پوشهٔ کناری `project Similar Image Detection`.)

| قابلیت | چه می‌کند | موتور | سرعت روی i5-4590 |
|---|---|---|---|
| **گفتار ⇒ متن** | صدای فارسی را می‌شنود و می‌نویسد؛ عددها را هم درمی‌آورد («صد و بیست و پنج تا» ⇒ 125)؛ فرمانِ صوتی | Vosk (مدلِ کوچکِ فارسی) | ~۱ ثانیه برای ۷ ثانیه صدا |
| **متن ⇒ گفتار** | متنِ فارسی را می‌خواند؛ عدد، ساعت، تاریخ، درصد و کدِ لاتین (INJ8) را درست می‌خواند | Piper (۶ صدای فارسی) | ~۲ ثانیه برای یک جمله |
| **گفتارِ طبیعی** (اختیاری) | ۹ صدای طبیعی‌تر (۳ زن، ۶ مرد) | Pocket-TTS فارسی | ~۱ تا ۱٫۵ ثانیه برای هر ثانیه صدا |
| **کلونِ صدا** (اختیاری) | صفحه جمله نشان می‌دهد، شما می‌خوانید؛ از جملهٔ اول به بعد هر متنی با صدای خودتان | Pocket-TTS فارسی | همان |
| **صدای هر چیز** (اختیاری) | «باران روی سقف حلبی»، «کمپرسور هوا»، «آژیر خطر» ⇒ صدایش | Stable Audio 3 Small-SFX | ~۵۰ تا ۷۰ ثانیه برای ۸ ثانیه صدا |

همه **آفلاین** کار می‌کنند: بی‌اینترنت، بی‌کلید، بی‌هزینه.
سه بخشِ «اختیاری» یک سرویسِ پایتونیِ جداست (`voice\`) که با `Setup-Voice.bat` نصب می‌شود و سرور خودش روشنش می‌کند: ~۱GB RAM برای گفتار و ~۳GB هنگامِ ساختنِ صدای هر چیز. همهٔ روش‌ها، مدل‌های سنگین‌تر برای سرور و سرویس‌های اینترنتی: **[VOICE-SETUP.md](VOICE-SETUP.md)**.

---

## ۱. در این پوشه چیست

```
project Voice\
├─ Run-Server.bat          ← سرویس + صفحهٔ آزمایش  (http://localhost:5600)
├─ Run-SelfTest.bat        ← آزمونِ نصب: متن، متن ⇒ گفتار، گفتار ⇒ متن
├─ Setup-Voice.bat         ← نصبِ سرویسِ صدا (گفتارِ طبیعی، کلون، صدای هر چیز): پایتون + ~۳٫۴GB مدل
├─ README.md               ← همین راهنما
├─ VOICE-SETUP.md          ← گفتارِ طبیعی، کلونِ صدا و صدای هر چیز: روش‌ها و نصب روی سرور
├─ PersianAiKit.Voice.sln  ← برای باز کردن در Visual Studio
├─ app\                    ← نسخهٔ آمادهٔ اجرا (ساخته‌شده؛ به SDK نیاز ندارد)
├─ models\                 ← مدل‌ها
│   ├─ piper\piper\piper.exe       موتورِ متن‌به‌گفتار
│   ├─ piper\voices\*.onnx         ۶ صدای فارسی: gyro (پیش‌فرض)، amir، ganji، ganji_adabi، reza_ibrahim، mana
│   ├─ vosk\vosk-model-small-fa-0.42   مدلِ گفتار‌به‌متن
│   └─ tts\ sfx\ text\ clone\      مدل‌های سرویسِ صدا (Setup-Voice.bat)
├─ src\
│   ├─ PersianAiKit.Voice\         ← کتابخانه (DLL): Tts، Asr، Text
│   ├─ PersianAiKit.Voice.Server\  ← سرویسِ HTTP + صفحهٔ آزمایش + persian-voice.js (کلاینتِ مرورگر)
│   └─ PersianAiKit.Voice.SelfTest\ ← آزمونِ نصب
├─ voice\                  ← سرویسِ صدا (پایتون): gateway.py، engines\، voices\ (۹ صدای مرجع)، واژه‌نامهٔ صداها
├─ samples\voice\          ← نمونهٔ ۹ صدای طبیعی + Piper برای مقایسه + صدای باران (README.txt کنارش)
├─ tools\Download-Models.ps1       ← دانلودِ دوبارهٔ Piper و Vosk روی کامپیوترِ تازه
├─ tools\download_voice_models.py  ← دانلودِ مدل‌های سرویسِ صدا (VOICE-SETUP.md)
├─ tools\voice-clone-script-fa.txt ← ۸۱ جمله برای خواندن در کلونِ صدا
└─ data\                   ← خودش ساخته می‌شود: کشِ صدا، صداهای کلون‌شده، گواهیِ https
```

**پیش‌نیاز:** ویندوزِ ۶۴بیتی + **.NET 8 یا بالاتر** (برای اجرا Runtime کافی است؛ برای تغییرِ کد SDK). برای بخش‌های اختیاری: پایتونِ ۳٫۱۰ تا ۳٫۱۳ (۶۴بیتی).

---

## ۲. اجرای سریع

1. **`Run-SelfTest.bat`** را اجرا کنید. آخرش باید بنویسد **«همه درست است ✓»**. نمونهٔ هر صدا را هم در `data\selftest\voice_*.wav` می‌گذارد تا گوش کنید.
2. **`Run-Server.bat`** را اجرا کنید و در مرورگر **http://localhost:5600** را باز کنید: متن بدهید تا بخواند، دکمهٔ میکروفون را بزنید و حرف بزنید. اگر `Setup-Voice.bat` را اجرا کرده باشید، بخش‌های ۳ تا ۵ (گفتارِ طبیعی، کلونِ صدا، صدای هر چیز) هم کار می‌کنند.

> پنجرهٔ سیاهِ سرور باید باز بماند؛ بستنش یعنی خاموش شدنِ سرویس (و سرویسِ پایتونیِ صدا هم با آن بسته می‌شود).

---

## ۳. استفاده در پروژهٔ دیگر — دو راه

### راهِ الف: سرویسِ HTTP (برای **هر زبانی**: PHP، Python، Node، C#، اندروید، …)

سرور را روشن نگه دارید (`Run-Server.bat`) و از پروژهٔ خودتان درخواست بفرستید.

| مسیر | ورودی | خروجی |
|---|---|---|
| `POST /api/tts` | JSON: `{"text":"…","voice":"fa_IR-gyro-medium","speed":1.0}` (یا `GET ?text=…`) | فایلِ `audio/wav` |
| `GET /api/tts/voices` | — | فهرستِ صداها |
| `POST /api/asr` | بدنه: فایلِ **WAV** (`Content-Type: audio/wav`) یا فرم با فیلدِ `file`؛ برای فرمانِ صوتی `?phrases=روشن کن\|خاموش کن` | `{"text","digits","numbers","phrase","words","seconds"}` — `phrase` = فرمانی که گفته شد یا null |
| `POST /api/text` | `{"text":"…"}` | متنِ خواندنی، نرمال‌شده، با رقم، عددها |
| `GET /api/health` | — | وضعیتِ هر بخش (+ `voice`: سرویسِ صدا روشن است؟) |
| **سرویسِ صدا** (بعد از `Setup-Voice.bat`) | | |
| `GET /api/voice/voices` | — | `{"voices":[{id,name,gender,kind:"builtin"\|"cloned"\|"piper",…}]}` |
| `POST /api/voice/tts` | `{"text":"…","voice":"mana","seed":null}` — `voice` با `piper:` ⇒ Piper | `audio/wav`؛ سرآیندهای `X-Voice-Engine`، `X-Voice-Seconds`، `X-Seed`، `X-Voice-Check` (خطای واژه با گفتار‌به‌متن، ۰ = کامل) |
| `POST /api/voice/sfx` | `{"prompt":"باران روی سقف حلبی","seconds":8,"seed":null,"promptEn":null}` | `audio/wav` (استریو ۴۴٫۱kHz)؛ `X-Prompt-En` = ترجمه‌ای که به مدل رسید |
| `POST /api/voice/sfx/translate` | `{"prompt":"…"}` | `{"en","method"}` — برای نشان دادن و درست کردنِ ترجمه پیش از ساختن |
| `POST /api/voice/clone` | `{"name","person","purpose","consent":true}` | `{"id",…}` — بی `consent: true` نمی‌شود |
| `GET /api/voice/script` | — | `{"sentences":[…]}` جمله‌هایی که باید خوانده شوند |
| `POST /api/voice/clone/clip?voice=ID&index=1&text=…` | بدنه: WAV (خواندنِ همان جمله) | `{"ok","message","heard","wer","snr","clips","minutes"}` — رد شد ⇒ `ok:false` با دلیل |
| `GET /api/voice/voices/{id}/sample` · `DELETE /api/voice/voices/{id}` | — | صدای مرجع / پاک کردنِ همهٔ ضبط‌ها |

خطا همیشه به شکلِ `{"error":"پیامِ فارسی"}` با کدِ ۴۰۰ (ورودیِ بد) یا ۵۰۳ (مدل نیست) برمی‌گردد.

**Python**
```python
import requests
B = "http://localhost:5600"

# متن ⇒ گفتار
wav = requests.post(f"{B}/api/tts", json={"text": "سفارش 1250 ساعت 14:30 آماده است"}).content
open("out.wav", "wb").write(wav)

# گفتار ⇒ متن
r = requests.post(f"{B}/api/asr", data=open("out.wav", "rb"), headers={"Content-Type": "audio/wav"}).json()
print(r["text"], r["numbers"])          # ... [1250, 14.5]

# فرمانِ صوتی: «لطفاً دستگاه را خاموش کنید» ⇒ phrase = "خاموش کن"؛ حرفِ بی‌ربط ⇒ None
r = requests.post(f"{B}/api/asr", params={"phrases": "روشن کن|خاموش کن"}, data=open("voice.wav", "rb"),
                  headers={"Content-Type": "audio/wav"}).json()
print(r["phrase"])

# گفتارِ طبیعی (بعد از Setup-Voice.bat)
wav = requests.post(f"{B}/api/voice/tts", json={"text": "خط تولید تا ظهر متوقف است.", "voice": "mana"}).content
```

**PHP**
```php
$B = 'http://localhost:5600';
file_put_contents('out.wav', file_get_contents("$B/api/tts?text=" . urlencode('سلام، خوش آمدید')));

$ch = curl_init("$B/api/asr");
curl_setopt_array($ch, [CURLOPT_POST => true, CURLOPT_POSTFIELDS => file_get_contents('voice.wav'),
    CURLOPT_HTTPHEADER => ['Content-Type: audio/wav'], CURLOPT_RETURNTRANSFER => true]);
$r = json_decode(curl_exec($ch), true);
echo $r['text'];
```

**خطِ فرمان (curl)**
```bat
curl -X POST -H "Content-Type: audio/wav" --data-binary @voice.wav http://localhost:5600/api/asr
curl -o out.wav "http://localhost:5600/api/tts?text=%D8%B3%D9%84%D8%A7%D9%85"
```

### راهِ ب: کتابخانه در پروژهٔ .NET (بی‌سرور، مستقیم در برنامهٔ خودتان)

۱. پروژهٔ کتابخانه را اضافه کنید (یا پوشهٔ `src\PersianAiKit.Voice` را کنارِ پروژه‌تان کپی کنید):
```bat
dotnet add reference "C:\Users\abaone\Desktop\PersianAiKit\project Voice\src\PersianAiKit.Voice\PersianAiKit.Voice.csproj"
```
در csprojِ پروژهٔ خودتان `<PlatformTarget>x64</PlatformTarget>` بگذارید (موتورها ۶۴بیتی‌اند).

۲. پوشهٔ `models` را به کتابخانه نشان دهید و استفاده کنید:
```csharp
using PersianAiKit;
using PersianAiKit.Asr;
using PersianAiKit.Text;
using PersianAiKit.Tts;

var models = VoiceModels.Find(@"C:\Users\abaone\Desktop\PersianAiKit\project Voice\models");

// ۱) متن ⇒ گفتار
var tts = new PiperTts(models, cacheDir: @"C:\MyApp\tts_cache");
byte[] wav = await tts.SpeakAsync("سفارش 1250 ساعت 14:30 آماده است");          // صدا و سرعتِ دلخواه: voice:, speed:
await File.WriteAllBytesAsync("out.wav", wav);

// ۲) گفتار ⇒ متن
using var asr = new VoskAsr(models);
asr.Warm();                                                                      // بارِ مدل در پس‌زمینه (چند ثانیه)
AsrResult r = await asr.RecognizeFileAsync("out.wav");
Console.WriteLine(r.Text);                                                       // «سفارش هزار و دویست و پنجاه …»
Console.WriteLine(PersianText.WordsToDigits(r.Text));                            // «سفارش 1250 …»
string? command = PersianText.FindPhrase(r.Text, new[] { "روشن کن", "خاموش کن" }); // فرمانِ صوتی؛ حرفِ بی‌ربط ⇒ null
```

۳. در **ASP.NET / Blazor** همه را یک بار بسازید و Singleton ثبت کنید (امن برای استفادهٔ هم‌زمان‌اند):
```csharp
var models = VoiceModels.Find(builder.Configuration["PersianVoice:Models"]);
builder.Services.AddSingleton(new PiperTts(models, Path.Combine(builder.Environment.ContentRootPath, "tts_cache")));
builder.Services.AddSingleton(_ => { var a = new VoskAsr(models); a.Warm(); return a; });

app.MapGet("/say", async (string text, PiperTts tts) => Results.File(await tts.SpeakAsync(text), "audio/wav"));
```

**چه چیزهایی در کتابخانه هست:**

| کلاس | کارهای مهم |
|---|---|
| `PiperTts` | `SpeakAsync(متن، صدا، سرعت)` ⇒ WAV · `SpeakToFileAsync` · `Voices()` · `SplitSentences` (متنِ بلند ⇒ جمله‌جمله) |
| `VoskAsr` | `RecognizeWavAsync` / `RecognizeFileAsync` / `RecognizePcmAsync` · `CreateStream()` (گوش دادنِ زنده: تکه‌تکه صدا بدهید، متنِ نیمه‌کاره را همان لحظه بگیرید) · `strictPhrases` (حالتِ سخت‌گیر — نکتهٔ بخشِ ۶) |
| `PersianText` | `ToSpeakable` · `NumberWords` (۲۵۰۴۵ ⇒ حروف) · `WordsToDigits` / `ExtractNumbers` (حروف ⇒ عدد) · `FindPhrase` (فرمانِ صوتی در متن) · `WordErrorRate` · `Normalize` · `ToPersianDigits` |
| `WavFile` | خواندن/ساختنِ WAV، تبدیلِ نرخ |
| `VoiceModels` | `Find()` — پوشهٔ models را پیدا می‌کند (یا متغیرِ محیطیِ `PERSIAN_VOICE_MODELS`) |

گفتارِ طبیعی، کلون و صدای هر چیز در کتابخانه نیستند (پایتون‌اند) — از راهِ HTTP (`/api/voice/*`) صدایشان بزنید.

---

## ۴. سمتِ مرورگر (`persian-voice.js`)

فایلِ `src\PersianAiKit.Voice.Server\wwwroot\persian-voice.js` را در صفحهٔ خودتان بگذارید (یا مستقیم از سرور بخوانید). ضبطِ صدا، پخش و ارسال به سرور همه در آن آماده است:

```html
<button id="talk">🎤 حرف بزن</button>
<script src="http://localhost:5600/persian-voice.js"></script>
<script>
  PersianVoice.configure({ baseUrl: 'http://localhost:5600' });        // و apiKey اگر گذاشته‌اید

  document.getElementById('talk').onclick = async () => {
    PersianVoice.unlockAudio();                                         // حتماً درونِ کلیک (برای آیفون)
    await PersianVoice.speak('سلام! بعد از بوق حرف بزن.');
    const r = await PersianVoice.listen();                              // ضبط تا سکوت ⇒ متن
    await PersianVoice.speak('شنیدم: ' + r.text);
  };
  // گفتارِ طبیعی: await PersianVoice.voice.speak('متن', { voice: 'mana' })
</script>
```
(تا پیش از جدا شدنِ پروژه‌ها نامِ این فایل `persian-ai.js` و نامِ شیء `PersianAI` بود.)

**مهم — گوشی و شبکه:** مرورگر میکروفون را فقط روی **https** یا **localhost** می‌دهد. برای گوشی:
1. در `app\appsettings.json` مقدارِ `"LanAccess": true` و یک `"ApiKey"` بگذارید.
2. پورت‌ها را یک بار در فایروال باز کنید (PowerShellِ Administrator):
   `New-NetFirewallRule -DisplayName "PersianAiKit Voice" -Direction Inbound -Protocol TCP -LocalPort 5600,5601 -Action Allow`
3. گوشی (روی همان وای‌فای) آدرسی را که سرور در شروع چاپ می‌کند باز کند: `https://IP:5601`. بارِ اول هشدارِ گواهی می‌بیند («ادامه/Proceed»)؛ بعد میکروفون کار می‌کند.
4. اگر صفحهٔ پروژهٔ شما https است، سرویس را هم با https صدا بزنید (`https://IP:5601`) — مرورگر https به http را می‌بندد.

---

## ۵. تنظیمات (`app\appsettings.json`)

| کلید | پیش‌فرض | یعنی |
|---|---|---|
| `Kit:HttpPort` / `HttpsPort` | 5600 / 5601 | پورت‌ها (`HttpsPort: 0` ⇒ بی https) |
| `Kit:LanAccess` | false | false ⇒ فقط همین کامپیوتر؛ true ⇒ همهٔ شبکه |
| `Kit:ApiKey` | خالی | پر ⇒ هر درخواست باید سرآیندِ `X-Api-Key` (یا `?key=`) داشته باشد. **روی شبکه حتماً بگذارید** |
| `Kit:ModelsDir` / `DataDir` | خودکار | جای مدل‌ها و داده‌ها |
| `Kit:Tts:Voice` / `Speed` | fa_IR-gyro-medium / 1.0 | صدای پیش‌فرض؛ سرعت: بزرگ‌تر ⇒ آرام‌تر (۱٫۱۵ برای سالنِ پرسروصدا) |
| `Kit:Asr:MaxSeconds` | 300 | بیشترین درازای یک صدا |
| `Kit:Voice:Url` | http://127.0.0.1:5620 | سرویسِ صدا؛ روی همین کامپیوتر باشد سرور خودش اجرایش می‌کند (سرورِ دیگر هم می‌شود) |
| `Kit:Voice:AutoStart` | true | false ⇒ سرویسِ صدا اجرا نمی‌شود (RAM آزاد می‌ماند) |
| `Kit:Voice:AsrCheck` | true | گفتارِ طبیعیِ ساخته‌شده با گفتار‌به‌متن وارسی و اگر جور نبود دوباره ساخته شود |
| `voice\config.json` | — | تنظیمِ خودِ سرویسِ صدا (رشته‌ها، نگه داشتنِ مدل‌ها در حافظه) — نمونه: `voice\config.example.json` |

---

## ۶. نکته‌ها و محدودیت‌ها (پیش از استفاده بخوانید)

**گفتار ⇒ متن**
- مدل کوچک است (برای CPUِ معمولی): جملهٔ کوتاه و روشن را خوب می‌فهمد، سروصدای زیاد و لهجهٔ سنگین دقت را پایین می‌آورد.
- **فرمانِ صوتی:** `phrases` بدهید (یا در C# ‏`FindPhrase`): متن آزاد شنیده می‌شود و فرمان در آن پیدا می‌شود؛ «لطفاً دستگاه را روشن کنید» ⇒ «روشن کن»، حرفِ بی‌ربط ⇒ هیچ. برای هر فرمان هم‌معنی‌ها را هم بدهید («بله|آره|بلی») — واژهٔ تک‌هجاییِ تنها (مثلِ «بله») گاهی چیزِ دیگری شنیده می‌شود.
- **حالتِ سخت‌گیر** (`?strict=` / `strictPhrases`) را فقط وقتی به کار ببرید که گوینده جز همان واژه‌ها چیزی نمی‌گوید (پاسخِ بله/نه به یک پرسش): در این حالت **هر** صدایی به یکی از آن واژه‌ها نسبت داده می‌شود — در آزمون، جملهٔ «سفارش ۱۲۵۰ آماده است» شد «خاموش روشن کن…».
- عددها را با **حروف** می‌نویسد؛ `digits` و `numbers` در پاسخ همان متن با رقم است.
- فقط **WAV** می‌پذیرد. `persian-voice.js` خودش WAV می‌سازد؛ برای mp3/ogg/webm اول با ffmpeg تبدیل کنید: `ffmpeg -i in.mp3 -ar 16000 -ac 1 out.wav`
- مسیرِ پوشهٔ مدل‌ها **حروفِ انگلیسی** داشته باشد (موتورِ Vosk مسیرِ فارسی را روی ویندوز باز نمی‌کند).

**متن ⇒ گفتار**
- فقط فارسی. عدد، ساعت (10:30)، تاریخِ شمسی (1405/07/05)، درصد و کدِ کوتاهِ لاتین (INJ8، CNC) خودکار درست خوانده می‌شوند؛ **واژهٔ انگلیسیِ بلند** (Windows) خوب خوانده نمی‌شود — فارسی بنویسید.
- هر درخواست تا ۶۰۰ نویسه؛ متنِ بلند را جمله‌جمله بفرستید (`persian-voice.js` و `SplitSentences` خودشان این کار را می‌کنند). متنِ تکراری از کش می‌آید (فوری).
- بهترین صدا در سنجش **gyro** بود (۴٪ خطا در برابرِ ۱۴٪ِ amir). بقیه را در صفحهٔ آزمایش گوش کنید.

**گفتارِ طبیعی، کلون، صدای هر چیز** (بخش‌های ۳ تا ۵ِ صفحهٔ آزمایش)
- **طبیعی‌تر، نه بی‌نقص:** در درست‌خوانی هم‌ترازِ Piper است (خطای واژه ~۸ تا ۱۲٪ با گفتار‌به‌متنِ همین پروژه)؛ فرق در طبیعی بودن است — `samples\voice` را گوش کنید. گاهی واژه‌ای را می‌اندازد یا واژه‌های صدای مرجع را می‌گوید؛ سرور خروجی را با گفتار‌به‌متن می‌شنود و تا ۲ بار دوباره می‌سازد. باز هم خراب بود: «🎲 یک نسخهٔ دیگر».
- **کلون:** یک جمله کافی است تا صدا کار کند؛ هر چه بیشتر بخوانید (پیشنهاد: ۵۰ جمله)، تمیزترین تکه مرجع می‌شود. کیفیت بیشتر به **ضبط** بستگی دارد: اتاقِ ساکت و بی‌پژواک، میکروفونِ خوب. هر جمله وارسی می‌شود (نویز، بریدگی، آرامی، و این‌که همان متن خوانده شد). ضبط‌ها در `data\voices\<نام>\` می‌مانند (برای آموزشِ صدای اختصاصی روی سرور — VOICE-SETUP.md بخشِ ۶).
- **فقط با رضایتِ صاحبِ صدا**؛ پاک کردن = همهٔ ضبط‌ها. صدای ساخته‌شده را برای فریب (تماسِ جعلی، تأییدِ هویت) به کار نبرید.
- **صدای هر چیز:** مدل فقط انگلیسی می‌فهمد؛ توصیف از واژه‌نامهٔ `voice\sfx_glossary_fa.json` و بعد ترجمهٔ ماشینی می‌گذرد («غرش شیر» را ترجمهٔ ماشینی «شیرِ خوراکی» فهمید) — متنِ انگلیسی را ببینید و درست کنید. گفتار و آواز نمی‌سازد.
- **حافظه:** صدای هر چیز ~۳GB RAM می‌خواهد. روی کامپیوترِ ۸GB با برنامه‌های باز، اگر کم بود سرویس اول مدلِ گفتار را موقتاً بیرون می‌برد و اگر باز کم بود پیامِ روشن می‌دهد. ویندوز برای جبران، فایلِ حافظهٔ مجازی را روی دیسک بزرگ می‌کند (تا چند گیگ) و تا ری‌استارت کوچک نمی‌شود.
- **مجوز:** خروجیِ گفتارِ طبیعی و کلون (Pocket) **فقط برای استفادهٔ غیرتجاری** است؛ جزوِ محصولِ فروشی نکنید.

**کارایی**
- همه روی CPU؛ هم‌زمان ۲ ساختِ صدا و ۲ شنیدن (بقیه صف می‌کشند) تا کامپیوتر برای کارهای دیگر هم جا داشته باشد.
- لینوکس آزموده نشده: `piper` و مدل‌ها همان‌اند، ولی باید نسخهٔ لینوکسیِ piper را به جای نسخهٔ ویندوز بگذارید.

---

## ۷. بردن به کامپیوترِ دیگر / روشن شدن با ویندوز

- **کلِ پوشه** را کپی کنید (با `models` و `app`). روی کامپیوترِ مقصد فقط **.NET 8 Runtime (ASP.NET Core)** یا بالاتر لازم است. بعد `Run-SelfTest.bat`.
- بی‌پوشهٔ `models` کپی کردید؟ `powershell -ExecutionPolicy Bypass -File tools\Download-Models.ps1` (اینترنت لازم است).
- **سرویسِ صدا** روی کامپیوترِ تازه: پایتونِ ۳٫۱۰ تا ۳٫۱۳ (۶۴بیتی) را نصب و `Setup-Voice.bat` را اجرا کنید (یا پوشه‌های `voice\.venv` و مدل‌ها را هم کپی کنید). برای سرورِ قوی و مدل‌های سنگین‌تر: VOICE-SETUP.md.
- **روشن شدن خودکار:** میان‌برِ `Run-Server.bat` را در پوشهٔ `shell:startup` بگذارید، یا در Start-Allِ پروژهٔ خودتان یک خط اضافه کنید:
  `start "PersianAiKit Voice" /min "C:\Users\abaone\Desktop\PersianAiKit\project Voice\Run-Server.bat"`
- تغییر در کد؟ `src\` را عوض کنید و دوباره بسازید:
  `dotnet publish src\PersianAiKit.Voice.Server -c Release -r win-x64 --self-contained false -o app`
  (برای SelfTest هم همین، با `src\PersianAiKit.Voice.SelfTest`.) یا پوشهٔ `app` را پاک کنید تا bat از روی کد اجرا کند.

---

## ۸. مجوزها

| بخش | مجوز |
|---|---|
| Piper | MIT (espeak-ngِ درونش GPL-3 است — برای استفادهٔ داخلی مشکلی نیست؛ برای فروشِ نرم‌افزار بررسی کنید) |
| صداهای فارسیِ Piper | مجوزِ هر صدا در MODEL_CARDِ آن در huggingface.co/rhasspy/piper-voices — پیش از استفادهٔ تجاری ببینید؛ Mana: MIT |
| Vosk و مدلِ فارسی | Apache-2.0 |
| Pocket-TTS فارسی (گفتارِ طبیعی، کلون) | **CC-BY-NC-4.0 — فقط غیرتجاری** (mehdi-hf/pocket-tts-farsi-v2؛ نسخهٔ ONNX: Nimaone)؛ G2P: MIT |
| Stable Audio 3 (صدای هر چیز) | Stability AI Community License (رایگان تا درآمدِ سالانهٔ ۱ میلیون دلار، با ثبت‌نام در Stability) + Gemma Terms؛ کدِ `voice\engines\sa3` از Stability: MIT |
| M2M100 (ترجمه) | MIT |
| صداهای مرجعِ `voice\voices` | مانا: CC0 (Mana-TTS)؛ آرش، بهرام، کاوه، رضا، امیر: ساخته با صداهای Piper؛ سارا، نگار، داریوش: نمونه‌های مدلِ Pocket (CC-BY-NC) — جزئیات در `voices.json` |
