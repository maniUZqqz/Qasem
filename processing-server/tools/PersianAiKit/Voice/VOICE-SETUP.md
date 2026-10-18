# راهنمای صدا: گفتارِ طبیعی، کلونِ صدا و صدای هر چیز

راهنمای پیاده‌سازی و نصب روی سرورِ شرکت. سه خواسته:

1. **چند صدای فارسیِ طبیعی**، طوری که تا جای ممکن معلوم نباشد ماشین است.
2. **کلونِ صدا**: کسی چند جمله بخواند و از آن به بعد هر متنی با صدای خودش گفته شود؛ طبیعی و باکیفیت.
3. **صدای هر چیز**: بنویسید «باران روی سقفِ حلبی» یا «موتورِ کمپرسور» و همان صدا ساخته شود.

هر خواسته **چند روش** دارد در سه سطح: **داخلیِ سبک** (روی کامپیوترِ معمولی، بی اینترنت)، **داخلیِ سنگین** (روی سرورِ قوی، بی اینترنت) و **بیرونی** (سرویسِ اینترنتی، اختیاری).

> **وضعیت (۱۴۰۵/۰۷/۰۶ — ۲۰۲۶-۰۹-۲۸):**
> - **ساخته و آزموده (سطحِ سبک، روی i5-4590 با ۸GB):** سرویسِ صدا `voice/gateway.py` + پلِ کیت (`/api/voice/*`) + بخش‌های ۳، ۴ و ۵ِ صفحهٔ آزمایش (http://localhost:5600):
>   گفتارِ طبیعی با Pocket (۹ صدا)، کلونِ صدا با ضبطِ جمله‌به‌جمله و وارسیِ خودکار، صدای هر چیز با Stable Audio 3 Small-SFX، ترجمهٔ توصیف (واژه‌نامه + M2M100)، وارسیِ گفتارِ ساخته‌شده با گفتار‌به‌متنِ کیت. آزمونِ مرورگر ۱۸ از ۱۸. نصب: `Setup-Voice.bat`.
> - **سنجیده:** گفتار ~۱ تا ۱٫۵ ثانیه برای هر ثانیه صدا؛ خطای واژه با گفتار‌به‌متنِ کیت ۰ تا ۲۴٪ (بیشترِ صداها ۸ تا ۱۲٪؛ Piper ۱۲ تا ۳۲٪) — درست‌خوانی هم‌تراز یا بهتر از Piper، طبیعی بودن را فقط گوش می‌سنجد (`samples/voice`). صدای هر چیز: ۵۰ تا ۷۰ ثانیه برای ۴ تا ۸ ثانیه صدا، ~۳GB RAM.
> - **هنوز ساخته نشده:** کارگرهای سنگین (OmniVoice، Chatterbox، …)، سرویس‌های بیرونی، kNN-VC/OpenVoice، فونم‌سازِ اضافه برای Piper، اسکریپتِ یک‌دکمه‌ایِ آموزشِ Piper. برای این‌ها این سند نقشه و دستورِ نصب است؛ زمان‌های «تخمین» باید روی خودِ سرور سنجیده شوند (بخشِ ۸).

---

## ۰. چه چیزی شدنی است (به زبانِ ساده)

| خواسته | شدنی؟ | داخلیِ سبک (CPU) | داخلیِ سنگین (سرور با GPU) | بیرونی (اینترنت) |
|---|---|---|---|---|
| **۱. چند صدای طبیعی** | **بله.** «کاملاً مثلِ انسان» فقط در سطحِ سنگین و در جمله‌های معمولی نزدیک می‌شود | Pocket-TTS-Farsi: بهتر از Piperِ فعلی، هر تعداد صدا؛ هنوز گاهی ماشینی | OmniVoice یا Chatterbox-فارسی: طبیعی‌ترین مدل‌های بازِ فارسی | آواشو، Talkbot (ایرانی)؛ ElevenLabs از ایران بسته است |
| **۲. کلونِ صدا** | **بله.** کیفیت بیشتر به **کیفیتِ ضبط** بستگی دارد تا مدل | از روی ۵ ثانیه (Pocket): شبیه، نه یکسان | از ۳ تا ۱۰ ثانیه (OmniVoice): خیلی شبیه. **بهترین:** آموزشِ مدلِ اختصاصی با ۳۰ تا ۶۰ دقیقه خواندن | آواشو: صدای اختصاصی با ~۱۰ دقیقه صدا (قراردادی) |
| **۳. صدای هر چیز** | **بله** برای صدای محیط، دستگاه، حیوان، طبیعت. **نه** برای گفتار یا آواز | Stable Audio 3 Small-SFX: خوب؛ ۵ ثانیه صدا در چند ثانیه | همان مدل روی GPU (زیرِ یک ثانیه) + Medium برای موسیقی و فضاسازیِ بلند | سرویسِ ایرانی پیدا نشد؛ خارجی‌ها بسته‌اند ⇒ **داخلی بماند** |

**رک و راست:**
- هیچ مدلِ فارسی‌ای در سنجش‌های منتشرشده هنوز **هم‌پای صدای واقعی** نیست. بهترین‌ها: OmniVoice با خطای حرفِ ۱٫۹۰٪ در برابرِ ۱٫۵۷٪ِ صدای واقعیِ انسان، و ParsVoice-XTTS با امتیازِ طبیعی‌بودنِ ۳٫۶ از ۵. در جملهٔ کوتاه و معمولی کمتر کسی فرق را می‌فهمد؛ در متنِ بلند، نامِ خاص، عدد و واژهٔ کمیاب گاهی لو می‌رود.
- **مجوز مهم است:** بیشترِ مدل‌های طبیعیِ فارسی (Pocket، OmniVoice، Chatterbox-فارسی، ParsVoice) **فقط برای کارِ غیرتجاری** آزادند. اگر این صداها جزوِ محصولی می‌شوند که فروخته می‌شود، فقط ستونِ «تجاری ✓» در بخشِ ۲٫۵ را بردارید.
- کلونِ صدای کسی **فقط با رضایتِ کتبیِ خودش** (بخشِ ۶٫۱).

---

## ۱. سه سطح؛ کِی کدام

| سطح | یعنی | کِی |
|---|---|---|
| **داخلیِ سبک** | روی CPUِ معمولی (مثلِ کامپیوترِ فعلی: i5-4590، ۸GB RAM)، بی اینترنت | کامپیوترهای سالن و دفتر؛ وقتی سرور در دسترس نیست |
| **داخلیِ سنگین** | روی سرورِ قوی با کارتِ گرافیکِ NVIDIA (یا CPUِ پرهسته)، بی اینترنت | بهترین کیفیت؛ آموزشِ صدای اختصاصی |
| **بیرونی** | سرویسِ اینترنتی با کلیدِ API | فقط اگر لازم شد؛ **متن و صدای شما از شرکت بیرون می‌رود** — پیش‌فرض خاموش |

هر درخواست می‌تواند موتور را خودش انتخاب کند (`engine`)؛ اگر نکند، فهرستِ پیش‌فرضِ تنظیمات به ترتیب امتحان می‌شود (مثلاً `omnivoice ← pocket-fa ← piper`): اولین موتوری که روشن و آماده است.

---

## ۲. موتورها

### ۲٫۱ گفتار (چند صدا)

| شناسه | سطح | صداها | کلون | شاهدِ کیفیت | سرعت (یک جملهٔ ~۱۰ واژه‌ای) | حجم | مجوز |
|---|---|---|---|---|---|---|---|
| `piper` (فعلی) + `ezafe-albert` | سبک | ۵ صدای فعلی + Mana | ✗ | MOS ۲٫۴۱ ⇒ **۳٫۱۴** با کسرهٔ اضافهٔ درست ([مقاله](https://arxiv.org/html/2512.08006v1)) | **۳–۴ ثانیه (سنجیده روی i5-4590)** با بالا آمدنِ برنامه؛ ~۰٫۵ ثانیه اگر بالا بماند | ۶۴ + ۴۴ MB | MIT؛ مدلِ اضافه: مجوز ننوشته |
| `pocket-fa` ✓ | سبک | بی‌نهایت (هر صدای ۵ثانیه‌ای) + ۹ صدای آماده | ✓ از ≤۵ ثانیه | UTMOS ۳٫۱۱، شباهتِ گوینده ۰٫۸۵۹؛ ۹۷۳ ساعت دادهٔ فارسی از ~۳۰۰۰ گوینده؛ **این‌جا:** خطای واژه ۰ تا ۲۴٪ (Piper ۱۲ تا ۳۲٪) | **~۱ تا ۱٫۵ ثانیه برای هر ثانیه صدا** (سنجیده، i5-4590)؛ بارِ اول ۷ تا ۱۵ ثانیه | ۴۹۰ MB؛ ~۱GB RAM | **CC-BY-NC** |
| `omnivoice` | سنگین | بی‌نهایت + «طراحیِ صدا» | ✓ از ۳–۱۰ ثانیه | خطای حرفِ فارسی ۱٫۹۰٪ (صدای واقعی ۱٫۵۷٪) — [مقاله](https://arxiv.org/html/2604.00688) | زیرِ ۱ ثانیه روی GPUِ قوی | ۳٫۳ GB؛ VRAM ~۳–۶ GB (تخمین) | **CC-BY-NC** (کد Apache) |
| `chatterbox-fa` | سنگین | بی‌نهایت + ۱ پیش‌فرض | ✓ از ۳–۱۰ ثانیه | فقط نمونه‌صدا، سنجش منتشر نشده | ~۱–۳ ثانیه روی GPU (تخمین) | ۳٫۲ GB | **CC-BY-NC**، gated؛ نشانِ پنهان (Perth) در خروجی |
| `parsvoice-xtts` | سنگین | بی‌نهایت | ✓ از ۶–۱۵ ثانیه | **MOS ۳٫۶، شباهت ۴٫۰** — ۲۲۰۰ ساعت فارسی ([مقاله](https://arxiv.org/abs/2510.10774)) | ~۱–۳ ثانیه روی GPU (تخمین) | ۵٫۷ GB | **غیرتجاری (CPML)**، gated |
| `moss-realtime-fa` | سنگین | بی‌نهایت | ✓ از ۱۰–۳۰ ثانیه | سنجش منتشر نشده | GPU، ~۱۲ GB VRAM (تخمین) | ۱۱٫۸ GB | **Apache-2.0 — تجاری ✓** |
| `omnivoice-gguf` | سنگینِ بی‌GPU | مثلِ omnivoice | ✓ | همان | سنجیده نشده | ۰٫۹ GB | CC-BY-NC |

مدل‌هایی که بررسی و **کنار گذاشته شدند**: Aava (۷٫۶GB، بی‌کلون، کند)، VibeVoice-Persian (۱۰٫۸GB، کدِ پایه برداشته شد)، F5 فارسی (ورودیِ IPA، غیرتجاری)، Fish S2 و Higgs (غیرتجاری، فارسی در ردهٔ پایین)، XTTS/Chatterbox/Qwen3-TTS/CosyVoice/IndexTTS رسمی (فارسی ندارند).

### ۲٫۲ کلونِ صدا

| روش | صدای لازم | سطح | کیفیت | مجوز |
|---|---|---|---|---|
| **بی‌آموزش با Pocket** | ۵ ثانیه | سبک | شبیه؛ لحن از مدل | CC-BY-NC |
| **بی‌آموزش با OmniVoice / Chatterbox-fa / ParsVoice** | ۳ تا ۱۵ ثانیه + متنِ همان تکه | سنگین | خیلی شبیه | غیرتجاری |
| **بی‌آموزش با MOSS-fa** | ۱۰ تا ۳۰ ثانیه | سنگین | سنجیده نشده | **تجاری ✓** |
| **تبدیلِ صدا با kNN-VC** روی خروجیِ هر موتور | ۵ تا ۱۰ دقیقه | سبک (CPU) | رنگِ صدا خیلی شبیه؛ خروجی ۱۶kHz؛ در یک مقایسه طبیعی‌بودنِ پایین (NMOS ۱٫۹۴) ⇒ **حتماً با گوش امتحان شود** | MIT |
| **تبدیلِ صدا با OpenVoice v2** | ۱ تا چند دقیقه | سبک | ارزان و سریع؛ شباهتِ کمتر | MIT |
| **آموزشِ صدای Piperِ اختصاصی** | **۳۰ تا ۶۰ دقیقه** | آموزش روی GPU، اجرا **روی هر کامپیوتر** (۶۳MB) | صدای خودِ شخص با لحنِ خودش؛ سریع‌ترین اجرا | MIT (پایه) — **تجاری ✓** |
| **آموزشِ Applio (RVC)** روی خروجیِ هر موتور | ۱۰ تا ۳۰ دقیقه | آموزش روی GPU، اجرا روی CPU هم | رنگِ صدای بسیار نزدیک | MIT — **تجاری ✓** |
| آموزشِ ParsVoice-XTTS یا LoRAِ Chatterbox-fa | ۵ تا ۳۰ دقیقه | GPU | احتمالاً بهترین شباهت (سنجیده نشده) | غیرتجاری |

**پیشنهاد:** (۱) همه‌جا اول **بی‌آموزش** (فوری، از روی یکی از جمله‌های خوانده‌شده). (۲) برای صدایی که زیاد استفاده می‌شود، روی سرور **Piperِ اختصاصی** آموزش دهید؛ نتیجه روی همین کامپیوترهای ضعیف هم تند اجرا می‌شود. (۳) اگر شباهت کم بود، Applio را رویش بگذارید.

### ۲٫۳ صدای هر چیز

| شناسه | سطح | چه می‌سازد | سرعت | حجم | مجوز |
|---|---|---|---|---|---|
| `sa3-small-sfx` (TFLite) ✓ | سبک | صدای محیط، دستگاه، حیوان، طبیعت؛ ۴۴٫۱kHz استریو؛ تا ۴۷ ثانیه در این سرویس | **۴ تا ۸ ثانیه صدا در ۵۰ تا ۷۰ ثانیه** (سنجیده، با بارِ مدل)؛ مدل در حافظه ⇒ ~۱۴ ثانیه | ۱٫۱ GB؛ ~۳GB RAM هنگامِ ساخت | Stability Community (رایگان تا درآمدِ سالانهٔ ۱M$؛ ثبت‌نام در Stability) |
| `sa3-small-sfx` (PyTorch) | سنگین | همان | زیرِ ۱ ثانیه روی GPU | ۳٫۵ GB؛ VRAM ~۲ GB | همان، gated |
| `sa3-medium` | سنگین | کیفیتِ بالاتر، بیشتر موسیقی و فضاسازی؛ تا ۳۸۰ ثانیه | زیرِ ۱ ثانیه روی H200؛ روی 3090/4090 چند ثانیه (تخمین) | ۱۰٫۴ GB؛ VRAM ۵–۶٫۵ GB | همان، gated؛ **Flash-Attention 2 لازم** (لینوکس) |
| `m2m100-ct2` (کمکی) | سبک | ترجمهٔ توصیفِ فارسی به انگلیسی (مدل‌های صدا فقط انگلیسی می‌فهمند) | زیرِ ۱ ثانیه | ۰٫۵ GB | MIT |

- **متنِ توصیف:** اول از یک واژه‌نامهٔ کوچکِ فارسی⇐انگلیسیِ صداها (باران⇐rain، غژغژِ در⇐door creaking، کمپرسور⇐air compressor humming)، بعد ترجمهٔ ماشینی. **متنِ انگلیسی به کاربر نشان داده شود تا بتواند درستش کند.**
- گزینه‌های دیگر: MOSS-SoundEffect v2 (Apache، ولی یک بخشش مجوزِ Tencent دارد)، MMAudio و TangoFlux (غیرتجاری). SA3 بهترین توازن بود.

### ۲٫۴ سرویس‌های بیرونی

از شبکهٔ همین شرکت در ۲۰۲۶-۰۹-۲۸ امتحان شد:

| سرویس | فارسی | کلون | صدای هر چیز | از ایران |
|---|---|---|---|---|
| **آواشو** (پارت، از راهِ ویرا/سحاب) — [api.ivira.ai](https://api.ivira.ai/partai/TextToSpeech) | ✓ صدای زن و مرد | ✓ صدای اختصاصی با ~۱۰ دقیقه صدا (قراردادی) | ✗ | **✓ در دسترس** |
| **Talkbot** — [talkbot.ir](https://talkbot.ir/text-to-speech-api) | ✓ ۵ صدای خودش + دو صدای Azure | ✗ | ✗ | ✓ پرداختِ ریالی؛ API در بسته‌های طلایی/الماس |
| **آریانا** (عصر گویش‌پرداز) — [asr-gooyesh.com](https://asr-gooyesh.com/fa/portfolio/ariana-service/) | ✓ | «صدای خودتان» به‌شکلِ پروژه | ✗ | ✓ **روی سرورِ ویندوزیِ خودِ شرکت نصب می‌شود** (داخلیِ تجاری) |
| **AvalAI** — [docs.avalai.ir](https://docs.avalai.ir/en/providers/elevenlabs) | ✓ ElevenLabs v3 و OpenAI (بازفروش) | مستند نیست | مستند نیست | ✓ پرداختِ تومانی — **ریسکِ تحریم و قوانینِ فروشندهٔ اصلی** |
| `edge-tts` (غیررسمی) | ✓ دو صدای Azure (Dilara، Farid) — **امروز امتحان شد و کار کرد** | ✗ | ✗ | ✓ رایگان؛ غیررسمی، ممکن است هر روز بسته شود؛ استفادهٔ تجاری خلافِ قوانینِ مایکروسافت |
| ElevenLabs (v3) | ✓ بهترین کیفیت | ✓ از زیرِ یک دقیقه | ✓ | **✗ بسته (۴۰۳)** |
| Google Gemini TTS | احتمالاً | ✓ | ✗ | **✗ بسته (۴۰۳)** |
| OpenAI، Azure | ✓ (لهجه‌دار / دو صدا) | ✗ برای فارسی | ✗ | در دسترس ولی **قوانینشان ایران را استثنا کرده** |

**پیشنهاد:** بیرونی فقط **آواشو** یا **Talkbot** (قانونی و در دسترس)، و `edge-tts` فقط برای آزمایش. صدای هر چیز **داخلی بماند**. برای کلون، فرستادنِ صدای کارمند به سرویسِ بیرونی را فقط با رضایتِ صریحِ خودش انجام دهید.

### ۲٫۵ مجوزها در یک نگاه

| تجاری ✓ (فروش در محصول هم آزاد) | فقط غیرتجاری ✗ |
|---|---|
| Piper و صداهایش، Mana، **Piperِ اختصاصیِ آموزش‌دیده**، kNN-VC، OpenVoice v2، **Applio**، **MOSS-realtime-fa**، M2M100، Stable Audio 3 (تا ۱M$ درآمد، با ثبت‌نام) | Pocket-TTS-Farsi، OmniVoice، Chatterbox-fa، ParsVoice-XTTS، F5 فارسی، MMAudio، TangoFlux |

«غیرتجاری» یعنی نمی‌شود آن را جزوِ محصول یا خدمتی کرد که پول می‌گیرد. استفادهٔ داخلیِ شرکت هم منطقهٔ خاکستری است؛ اگر مطمئن نیستید، ستونِ چپ را بردارید یا از صاحبِ مدل مجوز بگیرید.

---

## ۳. سخت‌افزار و نرم‌افزار

| سطح | CPU | RAM | GPU | دیسک (SSD) | سیستم‌عامل |
|---|---|---|---|---|---|
| **سبک** | ۴ هسته (مثلِ i5-4590) | ۸ GB (۱۶ بهتر) | لازم نیست | **~۶ GB آزاد** (۴ مدل + ۲ حاشیه) | ویندوز ۱۰/۱۱ یا لینوکس |
| **سنگین با GPU** | ۸ هسته به بالا | ۳۲ GB به بالا | NVIDIA با **۱۶–۲۴ GB VRAM** (RTX 3090/4090، RTX A5000/A6000، L4، …)، درایورِ CUDA 12.8 | **۱۰۰ GB** (مدل‌ها ~۴۰ + محیط‌های پایتون ~۳۰) | **لینوکس Ubuntu 22.04/24.04 پیشنهادی** (آموزشِ Piper و Flash-Attention فقط لینوکس/WSL2) |
| **سنگین بی GPU** | ۱۶–۳۲ هسته (ترجیحاً Xeonِ نسل ۴ به بالا با AMX) | ۶۴ GB | — | ۵۰ GB | ویندوز یا لینوکس — سرعت‌ها سنجیده نشده |

نرم‌افزار: **.NET 8** (کیتِ فعلی)، **Python 3.11** (برای MOSS: 3.12)، `ffmpeg`، `espeak-ng` (لینوکس، برای آموزشِ Piper)، `git`.

> ⚠ درسِ کامپیوترِ فعلی: وقتی RAM پر شود، ویندوز فایلِ حافظهٔ مجازی را روی دیسک بزرگ می‌کند (این‌جا تا ۱۲GB) و جای دیسک ناگهان تمام می‌شود. روی سرور RAMِ کافی بگذارید و اندازهٔ pagefile را ثابت کنید.

---

## ۴. معماری

```
برنامهٔ شما (PHP، Python، C#، مرورگر، صفحهٔ آزمایش)
        │ HTTP
        ▼
PersianAiKit.Voice.Server (.NET، پورتِ 5600)  ← کلیدِ API، ToSpeakable (عدد/تاریخ/کد ⇒ واژه)
        │ /api/voice/*  (پراکسی)
        ▼
voice-gateway (پایتون، پورتِ 5620، فقط localhost؛ کیت خودش اجرایش می‌کند و با بسته شدنِ کیت بسته می‌شود)
   ├─ موتورهای سبک درونِ خودش: pocket ✓ · sa3-small-sfx ✓ (در فرآیندِ جدا) · m2m100 ✓ · knn-vc · openvoice
   ├─ موتورهای سنگین: هر کدام یک «کارگر» جدا با محیطِ پایتونِ خودش (ساخته نشده)
   │     omnivoice :5631 · chatterbox-fa :5632 · parsvoice-xtts :5633 · moss-fa :5634 · sa3 :5635
   └─ موتورهای بیرونی: آواشو · Talkbot · OpenAI-سازگار (AvalAI) · edge-tts (ساخته نشده)
```

**آنچه ساخته شد (کد):** `voice/gateway.py` (HTTP با کتابخانهٔ استانداردِ پایتون، بی FastAPI)، `voice/engines/pocket.py` (موتورِ Pocket از روی manifest؛ تکه‌بندیِ برنامه‌ریزیِ پویا، ساختِ جریانی با رمزگشا برای توقفِ زود، وارسی و دوباره‌سازیِ هر تکه)، `voice/engines/textfa.py` (یکدست‌سازی، عدد، لاتین)، `voice/engines/sfx.py` + `engines/sa3/` (از کدِ MITِ Stability)، `voice/engines/wavio.py` (WAV و تغییرِ نرخ فقط با numpy)، در کیت: `src/PersianAiKit.Voice.Server/VoiceGateway.cs` و مسیرهای `/api/voice/*` در `Program.cs`، `PersianText.WordErrorRate`.

**درس‌های پیاده‌سازی (سنجیده):**
- **صدای مرجع** مهم‌ترین چیز است: مدل ادامهٔ همان صدا را می‌سازد ⇒ سکوتِ آغاز/پایانِ مرجع را هم ادامه می‌دهد (تا ۳ ثانیه سکوت پیش از هر تکه) و گاهی **واژه‌های خودِ مرجع** را می‌گوید (با یک مرجعِ ساخته‌شده از Piper، ۷۲٪ خطا). مرجع پیش از استفاده بریده، مکث‌هایش کوتاه و تقهٔ آغازش حذف می‌شود.
- **تکهٔ کمتر از ۶ توکن** («سلام،» تنها) را بد می‌خواند ⇒ به عبارتِ بعدی چسبانده می‌شود (دوباره‌سازی‌ها از ۱ تا ۲ برای هر صدا به صفر رسید).
- نشانِ «پایان» گاهی پیش از هجای آخر می‌آید ⇒ رمزگشا هم‌پای ساخت اجرا و توقف وقتی است که صدا واقعاً خاموش شد.
- Stable Audio در یک فرآیند با Pocket جا نشد (خطای تخصیصِ حافظه بی پیام) ⇒ روی کامپیوترِ کم‌حافظه هر ساخت در فرآیندی جدا و اگر لازم باشد Pocket موقتاً از حافظه بیرون می‌رود.

**چرا کارگرِ جدا برای هر موتورِ سنگین؟** هر کدام نسخهٔ خودش از PyTorch و transformers را می‌خواهد (OmniVoice: torch 2.8؛ Stable Audio 3: torch 2.7.1؛ MOSS: torch 2.9 و transformers 5؛ Chatterbox: transformers 4.46). در یک محیط با هم نصب نمی‌شوند.

**پوشه‌ها:**

```
PersianAiKit\
├─ Setup-Voice.bat            نصب: voice\.venv + requirements + مدل‌های سبک
├─ voice\                     سرویسِ صدا
│   ├─ gateway.py             HTTP: مسیرها، صف، کش، صداها، کلون ✓
│   ├─ engines\               pocket.py ✓، sfx.py ✓ (+ sa3\)، textfa.py ✓، wavio.py ✓ — بعداً: omnivoice.py، avasho.py، …
│   ├─ workers\               سرورِ کوچکِ هر موتورِ سنگین (ساخته نشده)
│   ├─ voices\                ۹ صدای مرجع + voices.json (نام، جنسیت، منبع، مجوز)
│   ├─ sfx_glossary_fa.json   واژه‌نامهٔ صداها (فارسی ⇒ انگلیسی) ✓
│   ├─ requirements.txt ✓  ·  config.example.json ✓
├─ models\                    tools/download_voice_models.py این‌ها را پر می‌کند
│   ├─ piper\ tts\ clone\ sfx\ text\ train\
│   └─ hf-cache\              فقط برای Stable Audio 3 با PyTorch (بخشِ ۵٫۳)
└─ data\
    ├─ voice_cache\           خروجی‌های گفتار (همان متن + صدا + بذر ⇒ فوری)
    └─ voices\<نام>\          هر صدای کلون‌شده ✓
        ├─ voice.json         نام، صاحبِ صدا، کاربرد، رضایت، تاریخ
        ├─ clips\NNN.wav + clips.json + metadata.csv   (۲۲۰۵۰ هرتز تک‌کاناله؛ NNN.wav|متن — آمادهٔ آموزشِ Piper)
        └─ ref.wav + ref.txt  تمیزترین تکهٔ ۳ تا ۱۰ ثانیه‌ای (برای موتورهای بی‌آموزش)
```

**config.json** — آنچه الان خوانده می‌شود در `voice/config.example.json` است (رشته‌ها، `warm`، `keepLoaded`، `isolate`). طرحِ کاملِ آینده (موتورهای سنگین و بیرونی):

```json
{
  "Port": 5620,
  "KitUrl": "http://127.0.0.1:5600",
  "ModelsDir": "../models",
  "VoicesDir": "../data/voices",
  "Defaults": {
    "tts":   ["omnivoice", "pocket-fa", "piper"],
    "clone": ["omnivoice", "pocket-fa"],
    "sfx":   ["sa3-small-sfx"]
  },
  "AllowExternal": false,
  "Engines": {
    "piper":         { "enabled": true },
    "pocket-fa":     { "enabled": true, "threads": 4 },
    "knn-vc":        { "enabled": false },
    "sa3-small-sfx": { "enabled": true, "threads": 4, "runtime": "tflite" },
    "omnivoice":     { "enabled": false, "worker": "http://127.0.0.1:5631" },
    "chatterbox-fa": { "enabled": false, "worker": "http://127.0.0.1:5632" },
    "sa3":           { "enabled": false, "worker": "http://127.0.0.1:5635" },
    "avasho":        { "enabled": false, "token": "" },
    "talkbot":       { "enabled": false, "token": "" },
    "openai-compat": { "enabled": false, "baseUrl": "https://api.avalai.ir/v1", "apiKey": "", "model": "gpt-4o-mini-tts" },
    "edge-tts":      { "enabled": false }
  }
}
```

---

## ۵. نصب روی سرور، گام‌به‌گام

### ۵٫۱ پیش‌نیازها

**لینوکس (Ubuntu 24.04):**
```bash
sudo apt-get update
sudo apt-get install -y git ffmpeg espeak-ng build-essential cmake ninja-build python3.11 python3.11-venv
# GPU: درایورِ NVIDIA (۵۷۰ به بالا برای CUDA 12.8) — بعد از نصب:
nvidia-smi
# .NET 8 برای کیت
sudo apt-get install -y dotnet-runtime-8.0 aspnetcore-runtime-8.0
```

**ویندوز:** Python 3.11 از python.org (تیکِ «Add to PATH»)، ffmpeg (مثلاً `winget install Gyan.FFmpeg`)، Git، **ASP.NET Core Runtime 8**، و برای GPU درایورِ NVIDIA. برای آموزشِ Piper و Stable Audio 3 Medium از **WSL2 (Ubuntu)** استفاده کنید.

### ۵٫۲ کیتِ فعلی

کلِ پوشهٔ `PersianAiKit` را کپی کنید (بی `models` هم می‌شود) و مدل‌های پایه را بگیرید:
```bat
powershell -ExecutionPolicy Bypass -File tools\Download-Models.ps1
Run-SelfTest.bat
```
روی لینوکس پوشهٔ `app` (ساختهٔ ویندوز) کار نمی‌کند: از روی `src` با `dotnet publish src/PersianAiKit.Voice.Server -c Release -r linux-x64 --self-contained false -o app` بسازید و نسخهٔ لینوکسیِ piper را بگذارید (README بخشِ ۶ — لینوکس هنوز آزموده نشده). ساده‌تر: کیت روی ویندوز بماند و فقط سرویسِ صدا روی سرورِ لینوکسی باشد (`Kit:Voice:Url` به آن اشاره کند).

### ۵٫۳ دانلودِ مدل‌ها

```bash
python tools/download_voice_models.py --list                 # همه، با حجم و مجوز
python tools/download_voice_models.py --tier light --dry-run # فقط وارسی: لینک‌ها و جای دیسک
python tools/download_voice_models.py --tier light           # همهٔ سبک‌ها (~۳٫۶ GB)
python tools/download_voice_models.py --only omnivoice,piper-train-base
```

- **فقط کتابخانهٔ استانداردِ پایتون** لازم است. دانلودِ قطع‌شده از همان‌جا ادامه می‌یابد؛ هر فایل با اندازه و SHA-256ِ خودِ Hugging Face وارسی می‌شود؛ پیش از شروع جای دیسک سنجیده می‌شود.
- **مدل‌های gated** (`chatterbox-fa`، `parsvoice-xtts`، Stable Audio 3 با PyTorch): اول در صفحهٔ مدل در huggingface.co وارد شوید و شرایط را بپذیرید؛ بعد یک توکن (Settings ⇒ Access Tokens، نوعِ Read) بسازید و `--token hf_…` بدهید (یا متغیرِ `HF_TOKEN`).
- **Hugging Face باز نمی‌شود؟** `--hf-endpoint https://hf-mirror.com` (یا `HF_ENDPOINT`). از این شبکه در ۲۰۲۶-۰۹-۲۸ هر دو باز بودند.
- **سرور اینترنت ندارد؟** روی یک کامپیوترِ دیگر `--dest D:\kit-models` بگیرید و پوشه را به `models` سرور کپی کنید.

**Stable Audio 3 با PyTorch** (سطحِ سنگین) از کشِ Hugging Face بار می‌شود، نه از پوشهٔ معمولی:
```bash
export HF_HOME=/srv/PersianAiKit/models/hf-cache    # ویندوز: set HF_HOME=...
pip install -U huggingface_hub
hf auth login                                        # همان توکن
hf download stabilityai/stable-audio-3-small-sfx     # ۳٫۵ GB
hf download stabilityai/stable-audio-3-medium        # ۱۰٫۴ GB (اختیاری)
# یک بار با اینترنت اجرا کنید (بخشِ ۵٫۴)؛ بعد برای کارِ بی‌اینترنت:
export HF_HUB_OFFLINE=1
```

| شناسه | سطح | حجم | برای |
|---|---|---|---|
| `piper-mana`، `ezafe-albert` | سبک | ۶۴ + ۴۴ MB | گفتار |
| `pocket-fa` | سبک | ۴۹۰ MB | گفتار + کلون |
| `knn-vc`، `openvoice-v2` | سبک | ۱٫۳ GB، ۱۳۱ MB | کلون |
| `sa3-small-sfx`، `m2m100-ct2` | سبک | ۱٫۳ GB، ۰٫۵ GB | صدای هر چیز |
| `omnivoice` (یا `omnivoice-gguf` بی GPU) | سنگین | ۳٫۳ (۰٫۹) GB | گفتار + کلون |
| `chatterbox-fa`، `parsvoice-xtts` | سنگین | ۳٫۲، ۵٫۷ GB | گفتار + کلون |
| `moss-realtime-fa` | سنگین | ۱۱٫۸ GB | گفتار + کلون (تجاری) |
| `piper-train-base` (Mana)، `piper-train-base-gyro` | سنگین | ۰٫۸۵ GB هر کدام | آموزشِ صدای اختصاصی |
| Stable Audio 3 small-sfx / medium (با `hf download`) | سنگین | ۳٫۵ / ۱۰٫۴ GB | صدای هر چیز |

### ۵٫۴ محیط‌های پایتون

**سبک** (یک محیط، بی GPU) — **ویندوز: فقط `Setup-Voice.bat`** (محیط، بسته‌ها، مدل‌ها؛ اجرای دوباره از همان‌جا ادامه می‌دهد). دستی یا لینوکس:
```bash
python3.11 -m venv voice/.venv && source voice/.venv/bin/activate      # ویندوز: voice\.venv\Scripts\activate
pip install -r voice/requirements.txt          # numpy، onnxruntime، sentencepiece، ai-edge-litert، ctranslate2 — بی torch، ~۲۰۰MB
python tools/download_voice_models.py --only pocket-fa,sa3-small-sfx,m2m100-ct2
python voice/gateway.py --port 5620            # کیت خودش همین را اجرا می‌کند؛ دستی فقط برای سرورِ جدا
# فقط برای knn-vc و openvoice (هنوز وصل نشده‌اند):
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu
```
- ⚠ `requirements.txt` باید ASCII بماند: pipِ قدیمی روی ویندوز آن را با کدپیجِ سیستم می‌خواند و با نوشتهٔ فارسی خطا می‌دهد.
- **pocket:** بی torch؛ موتور (`voice/engines/pocket.py`) از روی `manifest.json` نوشته شده (کدِ persian_tts مجوز ندارد). رقم را خودِ مدل نمی‌خواند ⇒ کیت متن را از ToSpeakable می‌گذراند و `textfa` هم پشتیبان است.
- **sa3-small-sfx (TFLite):** توکن‌ساز ⇐ T5Gemma ⇐ DiT در ۸ گام ⇐ رمزگشای SAME-S (w8a8) ⇐ WAV؛ کدِ `voice/engines/sa3` برگرفته از [اجراکنندهٔ رسمی](https://github.com/Stability-AI/stable-audio-3/tree/main/optimized/tflite) (MIT). بارِ اولِ هر مدل ~۱۰ ثانیه آماده‌سازیِ XNNPACK دارد ⇒ روی سرور `keepLoaded: true` (~۱۴ ثانیه برای ۸ ثانیه صدا، ~۳GB RAMِ دائمی).
- **knn-vc:** [github.com/bshall/knn-vc](https://github.com/bshall/knn-vc)؛ WavLM تا لایهٔ ۶ کافی است. همهٔ تکه‌های ضبط‌شدهٔ شخص «مجموعهٔ تطبیق» است؛ k≈۲۰ برای ۱۰ دقیقه صدا.

**سنگین** — هر کدام محیطِ جدا (`python3.11 -m venv workers/<نام>/.venv`):

| موتور | نصب | اجرا (خلاصه) |
|---|---|---|
| **omnivoice** | `pip install torch==2.8.0+cu128 torchaudio==2.8.0+cu128 --extra-index-url https://download.pytorch.org/whl/cu128` و `pip install omnivoice` | `OmniVoice.from_pretrained("models/tts/omnivoice", device_map="cuda:0", dtype=torch.float16)` ⇐ `model.generate(text=..., ref_audio="ref.wav", ref_text="...")` (۲۴kHz). **`ref_text` را حتماً بدهید** وگرنه Whisper (۱٫۶GB) برای نوشتنِ متنِ نمونه دانلود می‌شود. |
| **chatterbox-fa** | Python 3.11، `pip install chatterbox-tts` (فضای نمونه `transformers==4.46.3` را ثابت کرده) | `ChatterboxMultilingualTTS.from_local("models/tts/chatterbox-fa", device="cuda", t3_model="t3_fa.safetensors")` ⇐ `m.generate(text, language_id=None, audio_prompt_path="ref.wav")` |
| **parsvoice-xtts** | `pip install coqui-tts` | الگوی رسمیِ XTTS: `XttsConfig().load_json(".../config.json")`، `Xtts.init_from_config`، `load_checkpoint(config, checkpoint_dir="models/tts/parsvoice-xtts")`، `synthesize(text, config, speaker_wav="ref.wav", language="fa")` — سنجیده نشده |
| **moss-realtime-fa** | Python 3.12، torch 2.9 cu128، `transformers>=5`، `peft`؛ `git clone https://github.com/OpenMOSS/MOSS-TTS` | نمونه‌کدِ [کارتِ LoRA](https://huggingface.co/hamidfzm/MOSS-TTS-Realtime-Persian-lora) با مسیرهای `models/tts/moss-realtime-fa/{base,lora,codec}`. نکته‌های کارت: همیشه نمونه‌صدای فارسی بدهید؛ اولِ هر جمله «، » بگذارید؛ رقم را به واژه کنید؛ جمله‌ها ~۱۲ ثانیه. |
| **omnivoice-gguf** (بی GPU) | [omnivoice.cpp](https://github.com/ServeurpersoCom/omnivoice.cpp) را بسازید | سرورِ `tts-server`ِ خودش (سازگار با OpenAI) ⇒ در gateway مثلِ یک موتورِ `openai-compat` داخلی |
| **sa3** (PyTorch) | `git clone https://github.com/Stability-AI/stable-audio-3 && cd stable-audio-3 && uv sync`؛ **Flash-Attention 2** از [چرخ‌های آماده](https://github.com/mjun0812/flash-attention-prebuild-wheels) با نسخهٔ CUDA/torch/Python، بعد `uv sync --inexact` | `stable-audio --model small-sfx -p "rain on a tin roof" --duration 10 -o out.wav` یا `StableAudioModel.from_pretrained("small-sfx").generate(prompt=..., duration=10)`. **بی Flash-Attention، Medium فقط خش‌خش می‌سازد.** |

### ۵٫۵ اجرا به‌شکلِ سرویس (روشن شدن با سرور)

**لینوکس — systemd** (برای هر کارگر یک فایل شبیهِ همین):
```ini
# /etc/systemd/system/persianai-voice.service
[Unit]
Description=PersianAiKit voice gateway
After=network.target

[Service]
WorkingDirectory=/srv/PersianAiKit/voice
Environment=HF_HOME=/srv/PersianAiKit/models/hf-cache
Environment=HF_HUB_OFFLINE=1
ExecStart=/srv/PersianAiKit/voice/.venv/bin/python -m uvicorn gateway:app --host 127.0.0.1 --port 5620
Restart=always
User=persianai

[Install]
WantedBy=multi-user.target
```
```bash
sudo systemctl enable --now persianai-voice
journalctl -u persianai-voice -f      # گزارش‌ها
```

**ویندوز:** Task Scheduler ⇐ «When the computer starts» ⇐ `voice\.venv\Scripts\python.exe -m uvicorn gateway:app --host 127.0.0.1 --port 5620` (یا ابزارِ NSSM برای سرویسِ ویندوز). کیت همان `Run-Server.bat` است (README بخشِ ۷).

### ۵٫۶ شبکه و امنیت

- gateway و کارگرها فقط روی `127.0.0.1`. تنها درِ ورود **کیت** است با `Kit:ApiKey` (README بخشِ ۵).
- کلیدهای سرویس‌های بیرونی فقط در `voice/config.json` روی سرور؛ هیچ‌وقت در صفحهٔ مرورگر.
- پوشهٔ `data/voices` صدای آدم‌هاست (دادهٔ شخصی): پشتیبان‌گیری رمزدار، دسترسیِ محدود.
- ایرادهای بازِ کیت پیش از باز کردن روی شبکه درست شوند: CORSِ باز برای همه، و JSONِ خراب ⇒ خطای ۵۰۰.

---

## ۶. کلونِ صدا: رضایت، ضبط، آموزش

### ۶٫۱ رضایت (پیش از هر چیز)

- فقط صدای کسی که **کتباً رضایت داده**، برای کاری که در رضایت‌نامه آمده. در `consent.json`: نام، تاریخ، کاربرد، مدتِ نگهداری، امضا یا تأییدِ صوتی («من … رضایت می‌دهم صدایم برای … ساخته شود»).
- هر وقت خودش خواست: `DELETE /api/voice/voices/{id}` همه‌چیز (ضبط‌ها، مدلِ آموزش‌دیده، کش) را پاک کند.
- صدای ساخته‌شده **برای فریب** (تلفن، تأییدِ هویت، پیامِ جعلی از زبانِ کسی) به کار نرود. صفحه کنارِ صدای کلون‌شده برچسبِ «ساختهٔ ماشین» نشان دهد.

### ۶٫۲ ضبط

- **متن:** `tools/voice-clone-script-fa.txt`؛ ۸۱ جمله، همهٔ صداهای فارسی، ۶ تا ۸ دقیقه. برای آموزش (۳۰ تا ۶۰ دقیقه) دو سه بار با حالت‌های مختلف بخوانید و متن‌های کاریِ خودتان را هم اضافه کنید.
- **جا:** اتاقِ ساکت و **بی‌پژواک** (پرده، فرش، کمد پر از لباس)؛ پنکه، کولر و کامپیوترِ پرسروصدا خاموش. پژواک بدترین دشمن است و بعداً پاک نمی‌شود.
- **میکروفون:** هدستِ خوب یا میکروفونِ یقه‌ای، ۱۵ تا ۲۰ سانتی‌متر، همیشه همان فاصله و همان جا؛ صدای بلند و واضح ولی بی‌فریاد.
- **قالب:** WAVِ ۴۴٫۱ یا ۴۸ کیلوهرتز، ۱۶بیت، تک‌کاناله؛ هر جمله یک فایل با متنش. صفحهٔ ضبط (بخشِ ۷) خودش این کار را می‌کند.
- **وارسیِ خودکارِ هر تکه:** ۱٫۵ تا ۱۵ ثانیه؛ بی بریدگیِ صدا (قله زیرِ ۰٫۹۹)؛ نویزِ زمینه کم (فاصلهٔ سیگنال و نویز بالای ۲۵dB)؛ **گفتار‌به‌متنِ کیت متن را تأیید کند** (خطای واژه زیرِ ۳۰٪) — وگرنه «دوباره بخوانید».

### ۶٫۳ بی‌آموزش (فوری)

- **ref.wav:** بهترین تکهٔ ۵ تا ۱۰ ثانیه‌ای (کم‌نویزترین، با تأییدِ گفتار‌به‌متن) + متنش در `ref.txt`. Pocket فقط ۵ ثانیهٔ اولش را می‌خواهد؛ OmniVoice و Chatterbox تا ۱۰ ثانیه؛ MOSS ۱۰ تا ۳۰ ثانیه (چند تکهٔ پشتِ هم).
- **kNN-VC:** همهٔ تکه‌ها ⇐ ویژگی‌ها یک بار حساب و در `cache/` نگه داشته می‌شوند.

### ۶٫۴ با آموزش (روی GPU، یک بار برای هر صدا)

**الف) صدای Piperِ اختصاصی** — تجاری ✓، اجرای نتیجه روی هر کامپیوتر:
```bash
git clone https://github.com/OHF-voice/piper1-gpl.git && cd piper1-gpl
python3 -m venv .venv && source .venv/bin/activate
pip install "torch==2.8.*" --index-url https://download.pytorch.org/whl/cu128   # torch 2.9 خروجیِ ONNX را خراب می‌کند
pip install -e '.[train]'
./build_monotonic_align.sh && python3 setup.py build_ext --inplace

V=/srv/PersianAiKit/data/voices/ali              # metadata.csv:  001.wav|متنِ جمله  (WAVها ۲۲۰۵۰ هرتز، تک‌کاناله)
python3 -m piper.train fit \
  --data.voice_name fa_IR-ali \
  --data.csv_path $V/metadata.csv --data.audio_dir $V/clips \
  --model.sample_rate 22050 --data.espeak_voice fa \
  --data.cache_dir /srv/piper-cache/ali \
  --data.config_path /srv/PersianAiKit/models/piper/voices/fa_IR-ali-medium.onnx.json \
  --data.batch_size 32 \
  --model.warmstart_ckpt /srv/PersianAiKit/models/train/piper-gyro/1145-last.ckpt

python3 -m piper.train.export_onnx --checkpoint lightning_logs/version_0/checkpoints/<آخرین>.ckpt \
  --output-file /srv/PersianAiKit/models/piper/voices/fa_IR-ali-medium.onnx
```
- **نقطهٔ شروع:** ckptهای فارسیِ موجود قدیمی‌اند و با `--ckpt_path` بار نمی‌شوند (خطای `weights_only` / `sample_bytes`)؛ `--model.warmstart_ckpt` در نسخهٔ فعلیِ piper1-gpl همین را حل می‌کند ولی **روی ckptِ فارسی امتحان نشده**. اول gyro (فونم‌های espeak)؛ اگر نشد Mana (`models/train/piper-mana/ckpt/…`؛ پیکربندی‌اش «custom phonemes» نوشته — ممکن است فونم‌سازِ دیگری بخواهد).
- **مقدار و زمان:** ۳۰ تا ۶۰ دقیقه صدای تمیز؛ حدودِ ۱۰۰۰ دور (epoch) از نقطهٔ شروع؛ چند ساعت تا ۱–۲ روز GPU (تخمین). حداقل ۸GB VRAM؛ batch 32 روی ۲۴GB جا می‌شود.
- **نتیجه:** دو فایل (`.onnx` ۶۳MB + `.onnx.json`) در `models/piper/voices` ⇐ کیتِ فعلی بی هیچ تغییری آن را نشان می‌دهد و می‌خواند؛ با `ezafe-albert` بهتر.

**ب) Applio (RVC)** — تجاری ✓؛ لایهٔ «رنگِ صدا» روی خروجیِ هر موتور:
```bash
git clone https://github.com/IAHispano/Applio && cd Applio
./run-install.sh                      # ویندوز: run-install.bat (پایتونِ ۳٫۱۲ و torch cu128 را خودش نصب می‌کند)
python core.py preprocess --model-name ali --dataset-path /srv/PersianAiKit/data/voices/ali/clips --sample-rate 40000
python core.py extract    --model-name ali --f0-method rmvpe --embedder-model contentvec
python core.py train      --model-name ali --total-epoch 300 --batch-size 8 --sample-rate 40000
python core.py index      --model-name ali
python core.py infer --input-path tts.wav --output-path out.wav --pth-path <ali.pth> --index-path <ali.index>
```
۱۰ تا ۳۰ دقیقه صدا، ۲۰۰ تا ۴۰۰ دور. اجرای `infer` روی CPU هم می‌شود. متنِ «شرایطِ استفاده»ِ Applio را بخوانید.

**ج) غیرتجاری، شاید باکیفیت‌ترین:** آموزشِ ParsVoice-XTTS با ۵ تا ۳۰ دقیقه (coqui-tts، `recipes/ljspeech/xtts_v2/train_gpt_xtts.py`؛ ۱۲GB+ VRAM) یا LoRA روی Chatterbox-fa با ۳۰ دقیقه به بالا ([chatterbox-finetuning](https://github.com/gokhaneraslan/chatterbox-finetuning)). با گوش مقایسه کنید.

---

## ۷. رابطِ سرویسِ صدا (ساخته‌شده)

همه از راهِ کیت: `http://سرور:5600/api/voice/...` — کیت کلید را وارسی می‌کند، متن را از ToSpeakable می‌گذراند، ضبطِ کلون را با گفتار‌به‌متنِ خودش می‌شنود و گفتارِ ساخته‌شده را وارسی می‌کند؛ بعد به gateway (`Kit:Voice:Url`، پیش‌فرض `http://127.0.0.1:5620`؛ می‌تواند سرورِ دیگری باشد) می‌فرستد. فهرستِ کاملِ مسیرها در **README بخشِ ۳** است. خطا مثلِ بقیهٔ کیت: `{"error":"پیامِ فارسی"}` با ۴۰۰ (ورودیِ بد)، ۴۰۴ (صدا نیست)، ۴۰۹ (صدای کلون هنوز ضبط ندارد)، ۴۲۹ (صف پر است)، ۵۰۳ (مدل یا حافظه نیست).

**رفتارِ ساخته‌شده:**
- **گفتار:** جمله‌ها و عبارت‌ها (ویرگول) ⇐ آوا ⇐ تکه‌های ≤۲۰ توکن (عبارتِ کمتر از ۶ توکن به بعدی می‌چسبد) ⇐ ۲ تکه هم‌زمان ⇐ هر تکه وارسی (بلندی، پایان یافتن، طول نسبت به آواها، مکثِ بی‌جا) و تا ۳ بار ساخت ⇐ هم‌بلندی و چسباندن با مکث‌های ثابت (جمله ۰٫۴۲، ویرگول ۰٫۱۶ ثانیه). بذرِ پیش‌فرض از خودِ متن ⇒ همان متن همان صدا و از کش (`data/voice_cache`)؛ `seed` دیگر ⇒ نسخهٔ دیگر.
- **وارسیِ کیت:** خروجی ⇐ گفتار‌به‌متن ⇐ `PersianText.WordErrorRate`؛ بالای ۰٫۴۵ ⇒ تا ۲ بار با بذرِ دیگر و بهترین برمی‌گردد (`X-Voice-Check`). خاموش: `Kit:Voice:AsrCheck=false`.
- **کلون:** هر جمله: ۱٫۲ تا ۲۵ ثانیه، بلندیِ گفتار بالای ۳۸- dB، بریدگی زیرِ ۰٫۲٪، نسبتِ گفتار به نویز بالای ۱۸ dB، خطای واژه (اگر کیت شنید) زیرِ ۴۵٪. پذیرفته ⇒ `clips/NNN.wav` (۲۲۰۵۰ هرتز) + `metadata.csv` و انتخابِ دوبارهٔ `ref.wav` (بیشترین نسبتِ گفتار به نویز، ۳ تا ۱۰ ثانیه).
- **صدای هر چیز:** ۱ تا ۴۷ ثانیه؛ بلندیِ خروجی یکسان (~۲۰- dB، قله ۱- dB)؛ یک ساخت در هر لحظه، صفِ بیشتر از ۴ ⇒ ۴۲۹.
- **هم‌زمانی:** هر موتور یک کار در هر لحظه (RAM)؛ Pocket درونِ خودش ۲ تکه را هم‌زمان می‌سازد.

**ساخته نشده (طرح):** `engine` برای موتورهای سنگین و بیرونی؛ `GET /api/voice/health` جدا (فعلاً در `/api/health`)؛ بیرونی فقط وقتی `AllowExternal=true` و خودِ درخواست `engine` بیرونی را نام ببرد — هیچ‌وقت خودکار.

---

## ۸. آزمون و پذیرش (روی خودِ سرور)

| چه | چطور | پذیرش |
|---|---|---|
| **طبیعی‌بودن** | ۱۰ جملهٔ ثابت (کاری + روزمره + عدد) × هر موتور؛ ۳ تا ۵ نفر **بی‌آنکه بدانند کدام موتور است** از ۱ تا ۵ نمره بدهند؛ یک صدای واقعیِ انسان هم لابه‌لایش | میانگین ≥ ۴ برای «طبیعی» |
| **درست‌خوانی** | رفت‌وبرگشت: صدای ساخته‌شده ⇐ `/api/asr` کیت ⇐ خطای واژه (الان خودکار در هر درخواست: `X-Voice-Check`) | ≤ Piperِ فعلی (۱۱ تا ۳۲٪ بسته به صدا و جمله؛ Pocket روی این کامپیوتر ۰ تا ۲۴٪، بیشتر ۸ تا ۱۲٪) |
| **شباهتِ کلون** | ۵ همکاری که صاحبِ صدا را می‌شناسند: «این صدای فلانی است؟» (صدای واقعی و ساختگی مخلوط) | ≥ ۷۰٪ «بله» برای ساختگی |
| **سرعت** | ثانیه برای هر جمله، اولین تکه و کلِ پاراگراف | گفتگو: اولین تکه زیرِ ۲ ثانیه |
| **صدای هر چیز** | ۲۰ توصیف (کارخانه، طبیعت، شهر، حیوان) | ≥ ۱۵ «همان است» |
| **پایداری** | ۱۰۰۰ درخواستِ پشتِ هم؛ RAM و VRAM | بی نشت و بی خطای ۵۰۰ |

SelfTestِ کیت هم برای هر موتورِ روشن یک جمله بسازد و رفت‌وبرگشتش را وارسی کند.

---

## ۹. ترتیبِ پیاده‌سازی

1. ✓ **پایه:** `voice/gateway.py` + فهرستِ موتورها + Piperِ کیت در همان فهرست + پلِ `/api/voice/*` در کیت.
2. ✓ **pocket** (گفتار + کلون از یک جمله) — روی همین کامپیوترهای سبک.
3. ✓ **ضبطِ کلون:** `/script`، `/clone/clip` با وارسیِ خودکار، صفحهٔ ضبط، `data/voices`، رضایت.
4. ✓ **sa3-small-sfx** + واژه‌نامه + m2m100.
5. **سرور:** کارگرِ `omnivoice` ⇐ `chatterbox-fa` ⇐ `sa3` (PyTorch) ⇐ بقیه.
6. **آموزش:** اسکریپتِ یک‌دکمه‌ای «از `data/voices/ali` صدای Piper بساز» + Applio.
7. **بیرونی:** آواشو، Talkbot، OpenAI-سازگار، edge-tts (پیش‌فرض خاموش).
8. **آزمون‌های بخشِ ۸** و به‌روز کردنِ README.

---

## ۱۰. منابع

- گفتار: [Pocket-TTS-Farsi v2 ONNX](https://huggingface.co/Nimaone/pocket-tts-farsi-v2-onnx) · [OmniVoice](https://github.com/k2-fsa/OmniVoice) · [Chatterbox](https://github.com/resemble-ai/chatterbox) + [فارسی](https://huggingface.co/Thomcles/Chatterbox-TTS-Persian-Farsi) · [ParsVoice-XTTS](https://huggingface.co/MohammadJRanjbar/ParsVoice-XTTS) · [MOSS فارسی](https://huggingface.co/hamidfzm/MOSS-TTS-Realtime-Persian-lora) · [کسرهٔ اضافه برای Piper](https://github.com/MahtaFetrat/Piper-with-LCA-Phonemizer) · [Mana](https://huggingface.co/MahtaFetrat/Mana-Persian-Piper)
- کلون: [piper1-gpl آموزش](https://github.com/OHF-Voice/piper1-gpl/blob/main/docs/TRAINING.md) · [Applio](https://github.com/IAHispano/Applio) · [kNN-VC](https://github.com/bshall/knn-vc) · [OpenVoice](https://github.com/myshell-ai/OpenVoice)
- صدای هر چیز: [Stable Audio 3](https://github.com/Stability-AI/stable-audio-3) · [نسخهٔ بهینه (TFLite/ONNX)](https://huggingface.co/stabilityai/stable-audio-3-optimized) · [M2M100 int8](https://huggingface.co/jncraton/m2m100_418M-ct2-int8)
- داده برای آموزشِ مدلِ خودتان: PersianVox (۲۴۰۰ ساعت، CC-BY-4.0)، Mana-TTS (۸۶ ساعت، CC0)
