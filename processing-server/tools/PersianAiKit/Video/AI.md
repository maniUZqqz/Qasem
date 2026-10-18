# ویرایشِ ویدیو با هوشِ مصنوعیِ بینا (کم‌هزینه)

**ایده (همان ویرایشگرِ عکس):** هوشِ مصنوعی ویدیو نمی‌سازد و فیلم هم نمی‌بیند. یک **تصویرِ ۲×۲ از چهار لحظهٔ کلیپ** (۵۱۲ پیکسل، ~۲۰KB) و چند خط عدد دربارهٔ تصویر و صدا را می‌بیند و فقط «نسخهٔ ویرایش» (همان JSONِ صفحهٔ وب) را **می‌نویسد**؛ کارِ واقعی را FFmpeg روی دستگاه، روی کلِ فیلم و در اندازهٔ اصلی انجام می‌دهد.

- **ارزان:** چند هزار توکن برای هر ویدیو، هر طولی که باشد (یک دقیقه یا یک ساعت فرقی نمی‌کند). با مدل‌های رایگان صفر.
- **امن:** خروجیِ مدل از صافیِ نسخه می‌گذرد (کلیدِ ناشناخته دور، عدد در بازه). مدل **بُرش‌ها و بازه‌های حذفیِ شما را عوض نمی‌کند** (زمان‌بندی را از چهار فریم نمی‌شود فهمید).
- **قابلِ ادامه:** نتیجه همان نسخه است ⇒ در صفحه ریزش کنید یا برگردانید.
- **حریمِ خصوصی:** فقط تصویرِ ۲×۲ و عددها بیرون می‌روند؛ صدا و فیلم نه. با مدلِ محلی (LM Studio، Ollama) هیچ‌چیز بیرون نمی‌رود.

## مراحل (`POST /api/videos/{id}/ai-edit`)

1. **سنجشِ محلی (رایگان، یک بار و ذخیره):** روشنایی، سوختگی، کنتراست، اشباع و ته‌رنگ روی ۶ فریمِ نمونه؛ نویزِ تصویر؛ بلندیِ صدا (LUFS، BS.1770)، قله، کفِ نویز، وزوزِ برق، مکث‌ها.
2. **نسخهٔ خودکار (رایگان):** همان «✦ خودکار».
3. **یک درخواست:** متنِ ثابت (فهرستِ ابزارها با بازه و معادلِ پریمیر + پریست‌ها، ~۹۶۰ توکن) + هدفِ شما + اندازه‌گیری‌ها (~۱۵۰ توکن) + نسخهٔ خودکار + **تصویرِ ۲×۲** ⇒ مدل فقط JSON برمی‌گرداند (می‌تواند یک پریست هم نام ببرد: `"preset": "voice"`).
4. **اجرا:** موتور همان چهار لحظه را با نسخه می‌سازد.
5. **یک نگاهِ دوباره (اختیاری، `MaxRounds: 2`):** مدل چهار لحظهٔ ویرایش‌شده را می‌بیند و «درست است» یا اصلاح.
6. **اگر نشد:** کلید نیست، اعتبار تمام شده، مدل جواب نداد ⇒ نسخهٔ خودکار با دلیلش. مدل‌ها به ترتیب امتحان می‌شوند.

## هزینه

| بخش | توکن (تقریبی) |
|---|---|
| متنِ ثابت | ~۹۶۰ (`Run-SelfTest.bat --prompt` دقیقش را می‌گوید) |
| هدف + اندازه‌گیری‌ها + نسخهٔ خودکار | ~۲۰۰ تا ۳۰۰ |
| تصویرِ ۲×۲ (۵۱۲ پیکسل) | ~۲۵۰ تا ۸۰۰ (بسته به مدل) |
| پاسخ (فقط JSON) | ~۱۰۰ تا ۳۰۰ |
| دورِ دوم | تقریباً دو برابرِ دورِ اول |

یعنی **۳ تا ۵ هزار توکنِ ورودی برای هر ویدیو** با دو دور. با مدلی که ۰٫۱ دلار برای هر میلیون توکنِ ورودی می‌گیرد، کمتر از یک‌دهمِ سنت. مدل‌های بیناییِ رایگانِ OpenRouter (`auto-free`) هزینه ندارند. مقایسه: فرستادنِ خودِ فیلم به یک مدلِ ویدیویی برای هر ثانیه صدها توکن می‌خواهد.

## تنظیم (`appsettings.json` ⇐ `Video:Ai`)

```json
"Ai": { "BaseUrl": "https://openrouter.ai/api/v1", "ApiKey": "sk-or-...", "Models": "auto-free", "MaxRounds": 2, "CellSide": 256 }
```

- هر سرویسِ سازگار با OpenAI که عکس می‌پذیرد. `Models` با ویرگول، به ترتیب؛ `auto-free` ⇒ مدل‌های بیناییِ رایگانِ OpenRouter.
- **مدلِ محلی:** LM Studio (`http://127.0.0.1:1234/v1`) یا Ollama (`http://127.0.0.1:11434/v1`) با یک مدلِ بینا؛ نشانیِ محلی کلید نمی‌خواهد. مدلِ بینا چند گیگابایت حافظه می‌خواهد ⇒ جایش سرور است.
- `CellSide` کوچک‌تر ⇒ ارزان‌تر؛ `MaxRounds: 1` ⇒ نصفِ هزینه.

## استفاده

در صفحه: زبانهٔ **هوشِ مصنوعی**. از برنامه (cmd):

```bat
curl -X POST -H "Content-Type: application/json" -d "{\"goal\":\"reels, clear voice\"}" http://localhost:5680/api/videos/<id>/ai-edit
```

> در Git Bash متنِ فارسی در آرگومانِ curl خراب می‌شود؛ از cmd یا فایل (`-d @goal.json`) استفاده کنید.

پاسخ: `{ recipe, notes, usedAi, error, promptTokens, completionTokens, steps: [{round, model, notes, done, seconds}] }`. نسخه ذخیره **نمی‌شود** (پیشنهاد است): با `PUT /api/videos/{id}/recipe` ذخیره و با `POST /api/videos/{id}/export` خروجی بگیرید.

## ابزارها برای عاملِ بیرونی (function calling)

`GET /api/tools/openai` پنج تابع در قالبِ `tools`ِ OpenAI می‌دهد (با بازه و توضیحِ هر لغزنده):

| تابع | به کدام مسیر |
|---|---|
| `analyze_video` | `GET /api/videos/{id}/analyze` — متنِ کوتاهِ انگلیسی + نسخهٔ خودکار |
| `look_at_video` | `GET /api/videos/{id}/sheet?edited=1` — تصویرِ ۲×۲ (اصل یا با نسخهٔ ذخیره‌شده) |
| `edit_video` | `PUT /api/videos/{id}/recipe` |
| `find_pauses` | `POST /api/videos/{id}/pauses` — بازه‌های پیشنهادی برای `cuts` |
| `export_video` | `POST /api/videos/{id}/export` ⇒ کار ⇒ `GET /api/jobs/{jobId}` تا `done` ⇒ `/api/jobs/{jobId}/file` |

```python
import requests, time
B = "http://localhost:5680"
tools = requests.get(f"{B}/api/tools/openai").json()      # به مدلِ خودتان بدهید

def run_tool(name, args):
    vid = args.pop("id")
    if name == "analyze_video":  return requests.get(f"{B}/api/videos/{vid}/analyze").json()["text"]
    if name == "look_at_video":  return requests.get(f"{B}/api/videos/{vid}/sheet", params={"edited": 1}).content   # به‌صورتِ عکس برگردانید
    if name == "edit_video":     return requests.put(f"{B}/api/videos/{vid}/recipe", json=args).json()
    if name == "find_pauses":    return requests.post(f"{B}/api/videos/{vid}/pauses").json()["cuts"]
    if name == "export_video":
        job = requests.post(f"{B}/api/videos/{vid}/export").json()
        while (job := requests.get(f"{B}/api/jobs/{job['id']}").json())["state"] not in ("done", "failed", "cancelled"):
            time.sleep(1)
        return job
```

یک عاملِ نمونه برای «از این ویدیوی حرف‌زدن یک ریلز بساز»: `analyze_video` ⇐ `find_pauses` ⇐ `edit_video` با `preset: "reels"`، `cuts` و `adjust` ⇐ `look_at_video` ⇐ (اصلاح) ⇐ `export_video`.
