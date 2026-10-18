# معماری کامل موتور تولید ویدئوی تبلیغاتی سه‌بعدی با هوش مصنوعی برای UpMarket

هدف ما ساخت یک موتور تولید ویدئو است که به‌جای تولید تک‌تک فریم‌ها با مدل‌های سنگین ویدئویی، از انسان سه‌بعدی واقع‌گرایانه، انیمیشن‌های طبیعی، محیط سه‌بعدی، صدا و کارگردانی هوشمند استفاده کند.

اما یک شرط اساسی داریم: خروجی نباید شبیه بازی کامپیوتری یا انیمیشن معمولی باشد. باید بتوانیم تبلیغی بسازیم که در آن یک انسان محصولی را برمی‌دارد، به آن نگاه می‌کند، با دوربین صحبت می‌کند، حرکت طبیعی دارد و در محیطی شبیه فروشگاه یا خانه واقعی دیده می‌شود.

برای رسیدن به این هدف، باید پروژه را مانند یک موتور تولید مجازی مبتنی بر 3D و هوش مصنوعی طراحی کنیم، نه یک اسکریپت ساده که چند انیمیشن را پشت سر هم اجرا می‌کند.

یک نکته را از ابتدا شفاف کنم: با این معماری می‌توانیم به خروجی بسیار واقع‌گرایانه برسیم، اما طبیعی بودن در حد فیلم‌برداری واقعی تضمین‌شده نیست. کیفیت نهایی به مدل انسان، ریگ، انیمیشن، نورپردازی، پوست و مو، دوربین و به‌خصوص تعامل درست دست با محصول بستگی دارد. باید این کیفیت را با تست‌های واقعی بسنجیم.

## ۱. تصمیم‌های اصلی معماری

[Incredible Realistic Girl Made with MetaHuman & Unreal Engine 5](https://images.openai.com/static-rsc-4/MNCWlSGqpgSjv07WQBoomo0irIAYnkckY3Kvk-GbKLk4Wb_w9zWmgD491kZmLRkx9Un99H1YnLWciRjGu-WqiG1_g4hWUP5o2gyc0Em9UZB_JDMsvE3r_CsovYcWyjawG06kkO9SDC5EiLDQIfT80Gi6s9H6qIr2JwM2FIlgAE4?purpose=inline)

۱. انسان سه‌بعدی واقع‌گرایانه

یک کاراکتر آماده و باکیفیت با پوست، مو، لباس، اسکلت و صورت قابل انیمیشن. در نسخه اول سراغ ساخت انسان از صفر نمی‌رویم.

[Inertial Motion Capture-Based Whole-Body Inverse Dynamics](https://images.openai.com/static-rsc-4/Zt7edrwkQOMQKum3X4J1TW-ONRzcYQuEyOvciDwGsVCfYWSkeTlM6x1ERqq5Dpjn8D2RlIv-M3uyQuhkGkmBZoRekyTjFU4PjUSMP3yWnyvjazz9xxpO3Gz5THHrCBb79tVYslvBICPbKyKV_o-fEsBRxwh80AQlzW5lBA29-ck?purpose=inline)

۲. کتابخانه حرکات انسانی

حرکت‌های واقعی Motion Capture، پاک‌سازی‌شده و دسته‌بندی‌شده، همراه با اطلاعات شروع، پایان، سرعت و امکان ترکیب.

[AI Images for E-commerce — Free Product Photo Generator | Nano Banana 2](https://images.openai.com/static-rsc-4/garKdQchpE7_6qy3DciiNWocUsT0GirlflbvjupPblh_cRqreonvlTOQyq87zJTfkf9MJr_Psr4zzfhP0qBAe2ONFZjojytLIY7erBLHi7bWUWGUUNHswTeIp5luN4BH84kImDVRxreXCW0RZOiEEFS-FYkX1Wi64MW9S-SULaY?purpose=inline)

۳. محیط و محصول سه‌بعدی

صحنه‌های آماده، نورپردازی کنترل‌شده، مدل سه‌بعدی یا تصویر محصول، جایگاه دقیق اشیا و تنظیمات دوربین.

[The Meaning Behind Gifting Perfume: Symbolism and Personal Touches  – Wani Perfumes](https://images.openai.com/static-rsc-4/mQcud3MxQSM0x8IuRMvgF_BoVmiQkoYheWwTFgibx7D4nyEPgO-BeGoqUEc1qMN19un4Dm7fvm99nGU0ZXPZ2KDUmTyLHuj6Q94tUYQ1LE3Ua-0UQCZ0B0i5aKjOnPyI7RmzngLq1FVgSqAPH1OVMQqXyX94r7PBPWckyNR2cdk?purpose=inline)

۴. کارگردان هوش مصنوعی

مدل زبانی سناریو را به صحنه‌ها، حرکت‌ها، دیالوگ، دوربین و زمان‌بندی تبدیل می‌کند؛ موتور سه‌بعدی اجرای واقعی را انجام می‌دهد.

### پشته فناوری پیشنهادی

| بخش             | انتخاب اصلی                                        | نقش                                      |
| --------------- | -------------------------------------------------- | ---------------------------------------- |
| موتور سه‌بعدی   | Blender                                            | صحنه، کاراکتر، دوربین و رندر             |
| اجرای خودکار    | Python + Blender Python API                        | ساخت و اجرای پروژه از طریق اسکریپت       |
| فرمت مدل و صحنه | FBX برای انیمیشن، glTF/GLB برای دارایی‌های مناسب   | انتقال مدل و دارایی                      |
| کاراکتر         | مدل آماده سازگار با Blender و ریگ استاندارد        | بدن، صورت و لباس                         |
| حرکت            | Mixamo برای شروع، سپس Motion Captureهای دارای مجوز | کتابخانه حرکات                           |
| ترکیب حرکت      | Blender Action/NLA و سیستم سفارشی Motion Graph     | اتصال حرکت‌ها                            |
| صداسازی         | موتور TTS با صدای طبیعی و مجوز استفاده تجاری       | دیالوگ                                   |
| هماهنگی لب      | Rhubarb Lip Sync یا ابزار سازگار با ریگ صورت       | انطباق لب با صدا                         |
| هوش مصنوعی      | LLM کم‌هزینه با خروجی ساختاریافته JSON             | برنامه‌ریزی صحنه و حرکت                  |
| پردازش ویدئو    | FFmpeg                                             | خروجی MP4، صدا، زیرنویس و تبدیل فرمت     |
| بک‌اند UpMarket | Django + Django REST Framework                     | مدیریت پروژه، صف و خروجی‌ها              |
| صف کارها        | Redis + Celery                                     | اجرای رندرهای زمان‌بر به‌صورت غیرهم‌زمان |
| ذخیره‌سازی      | فضای ذخیره‌سازی فایل + دیتابیس PostgreSQL          | دارایی‌ها، پروژه‌ها و ویدئوها            |

این انتخاب‌ها نقطه شروع هستند، نه اینکه همه را از روز اول نصب کنیم. به‌خصوص، Blender موتور اجرای صحنه است و Django فقط کارها را مدیریت می‌کند؛ درخواست وب نباید مستقیماً یک رندر سنگین را اجرا و منتظر پایان آن بماند.

## ۲. تصمیم اول: Blender یا Unreal Engine؟

هر دو قابل استفاده‌اند، اما برای این پروژه دو مسیر متفاوت داریم.

[Craft Your Signature Scent: The Rise of Bespoke Perfume](https://images.openai.com/static-rsc-4/ZoQQUxk64jmWzkA3-EWAfgiF-QYE9_qk9uJPeWuYiA4hYbBp02AdqLvY6Xs5jEM0oBBoxYFr8fW3MSWNbPP7W2MybCagjwZvn88W2bF8DaoC5P3Q-ZzGS9EW34G4-MnxCG1rPu_pP19KQbbA31MWjy2DXdn7SWTqyeE--0deO2s?purpose=inline)

مسیر A — Blender (پیشنهاد من برای MVP)

شروع کم‌هزینه

رایگان و قابل اتوماسیون با Python، مناسب ساخت صحنه، کنترل انیمیشن، رندر آفلاین و تولید ویدئو از طریق اسکریپت. مستندات رسمی آن API پایتون و اجرای رندر در پس‌زمینه را پوشش می‌دهد.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://developer.blender.org\&sz=32)

Blender Developer Documentation

+1



مناسب وقتی است که می‌خواهیم سریع یک خط تولید ویدئو بسازیم و هر فریم را با کیفیت کنترل‌شده رندر کنیم.

[Editable MetaHuman female character - Ling Xuan.With hair, no clothing included. | Fab](https://images.openai.com/static-rsc-4/IeaTd4yujZEJyRS27AYBY0-sl-QnHysb9I0STo0V0t2TTQfZQu1FOwtL_0BMRCUHXXCER_K3ZpKxrNovVbshHIlnTw_-vLsWDZgLEEDKcDTN8mW0MxUujQRPv-NSqRrVHa4by8bNqV1PSy54OeC26l-BT6Au5QmB1c2U6VqVbmg?purpose=inline)

مسیر B — Unreal Engine + MetaHuman

مناسب زمانی که انسان واقع‌گرایانه، نمایش زنده، حرکت دوربین و تعامل بلادرنگ اولویت دارند. اما مسیر راه‌اندازی و الزامات سخت‌افزاری بعضی قابلیت‌های MetaHuman بالاتر است.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://dev.epicgames.com\&sz=32)

Epic Developer Community

+1



این را برای نسخه بعدی بررسی می‌کنیم، نه اینکه هم‌زمان دو موتور را توسعه بدهیم.

تصمیم پیشنهادی: Blender را برای نسخه اول انتخاب کنیم. اگر بعداً به انیمیشن زنده، صحنه‌های تعاملی پیچیده یا تولید بلادرنگ نیاز داشتیم، آن موقع Unreal را با یک نمونه واقعی مقایسه می‌کنیم.

## ۳. سخت‌افزار و محیط اجرا

برای شروع، همان سیستم توسعه فعلی‌ات با RTX 3060 12GB می‌تواند میزبان نمونه اولیه باشد؛ به‌خصوص اگر صحنه‌ها را کنترل کنیم، رزولوشن پیش‌نمایش را پایین نگه داریم و رندر نهایی را جداگانه اجرا کنیم. این کارت حافظه ۱۲ گیگابایتی دارد، اما سرعت رندر به پیچیدگی صحنه، موتور رندر و تنظیمات وابسته است.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://www.renderjuice.com\&sz=32)

RenderJuice

+1



### محیط توسعه

- Windows برای توسعه محلی.
- Blender نسخه پایدار و سازگار با افزونه‌های انتخاب‌شده.
- Python API داخلی Blender برای اجرای اسکریپت‌های صحنه.
- FFmpeg برای مونتاژ خروجی.
- Git برای نسخه‌بندی کد.
- ذخیره‌سازی جداگانه برای مدل‌ها، تکسچرها، انیمیشن‌ها و خروجی‌ها.

نکته مهم: Python نصب‌شده در سیستم و Python داخلی Blender الزاماً نسخه یکسانی ندارند. برای اجرای اسکریپت‌های صحنه، از Python خود Blender استفاده می‌کنیم.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://developer.blender.org\&sz=32)

Blender Developer Documentation

+1



### ساختار پوشه‌های پروژه

```
upmarket-3d-engine/
│
├── apps/
│   └── api/                  # Django REST API
│
├── renderer/
│   ├── blender_runner.py     # اجرای Blender
│   ├── scene_builder.py      # ساخت صحنه
│   ├── character_loader.py   # بارگذاری کاراکتر
│   ├── motion_player.py      # اجرای حرکت‌ها
│   ├── motion_blender.py     # اتصال و ترکیب حرکت
│   ├── camera_director.py    # برنامه دوربین
│   ├── lighting.py           # نورپردازی
│   └── export_video.py       # خروجی ویدئو
│
├── planner/
│   ├── script_writer.py      # تبدیل درخواست به سناریو
│   ├── scene_planner.py      # تقسیم سناریو به صحنه
│   ├── action_planner.py     # انتخاب حرکت
│   ├── validator.py          # اعتبارسنجی برنامه
│   └── schemas.py            # قراردادهای داده
│
├── assets/
│   ├── characters/
│   ├── motions/
│   ├── environments/
│   ├── products/
│   ├── materials/
│   ├── sounds/
│   └── fonts/
│
├── templates/
│   ├── product_showcase/
│   ├── talking_presenter/
│   └── product_interaction/
│
├── pipeline/
│   ├── audio.py
│   ├── lipsync.py
│   ├── compositing.py
│   └── quality_checks.py
│
├── jobs/
├── tests/
├── configs/
└── README.md
```

این ساختار یک پیشنهاد اولیه است. لازم نیست تمام فایل‌ها را از ابتدا بسازی؛ ابتدا یک اسکریپت Blender مستقل خواهیم داشت که بتواند یک صحنه را کامل بسازد و خروجی بگیرد. بعد از موفقیت آن، منطق را به ماژول‌های بالا تقسیم می‌کنیم.

## ۴. ساخت انسان سه‌بعدی: مهم‌ترین انتخاب کل پروژه

اگر انسان از ابتدا کیفیت خوبی نداشته باشد، هیچ مقدار هوش مصنوعی و Motion Capture نمی‌تواند خروجی را کاملاً واقعی کند.

برای MVP، باید یک کاراکتر اصلی داشته باشیم، نه ده‌ها انسان متفاوت.

### مشخصات ضروری کاراکتر

بدن انسان با تناسبات واقعی و هندسه مناسب

پوست با جزئیات، Roughness و نورپردازی صحیح

مو با حجم و سایه طبیعی، نه صرفاً یک کلاهک هندسی

لباس با چین‌وچروک طبیعی و حرکت مناسب

اسکلت استاندارد و سازگار با انیمیشن‌های ورودی

ریگ صورت با Shape Keys یا کنترل‌های مشابه برای لب، چشم و ابرو

دست‌ها و انگشتان قابل کنترل برای گرفتن و نگه‌داشتن محصول

### منابع کاراکتر

سه گزینه را بررسی می‌کنیم:

1. کاراکتر آماده و واقع‌گرایانه با ریگ سازگار با Blender.
2. کاراکتر مبتنی بر MetaHuman، اگر بعداً Unreal را انتخاب کنیم.
3. کاراکتر اختصاصی که در آینده برای هویت بصری محصول خودمان ساخته می‌شود.

برای انتخاب نهایی، صرفاً به تصویر تبلیغاتی مدل نگاه نمی‌کنیم. باید مدل واقعی را دانلود یا تهیه کنیم و آن را در همان موتور، زیر همان نور و در حرکت آزمایش کنیم.

معیار انتخاب: مدل باید در نمای تمام‌قد، نمای نزدیک صورت، حرکت دست و تعامل با اشیا قابل قبول باشد. مجوز استفاده تجاری و امکان استفاده در سرویس آنلاین هم باید بررسی شود.

### چرا مدل‌های آماده بهتر از ساخت انسان از صفر هستند؟

چون ساخت یک انسان باکیفیت شامل مدل‌سازی، تکسچرینگ، ریگ بدن، ریگ صورت، مو، لباس و اصلاح تغییر شکل پوست است. این‌ها خودشان پروژه‌های جداگانه‌ای هستند. در MVP، ارزش اصلی ما موتور کارگردانی، اتصال حرکت‌ها و خط تولید ویدئو است، نه اختراع دوباره مدل‌سازی شخصیت.

## ۵. کتابخانه حرکات انسانی (Motion Database)

اینجا هسته اصلی ایده تو قرار دارد.

به‌جای اینکه هر بار یک حرکت را با مدل هوش مصنوعی تولید کنیم، یک‌بار حرکت مناسب را به دست می‌آوریم، کیفیت آن را بررسی می‌کنیم و سپس در هزاران پروژه از آن استفاده می‌کنیم.

### منابع حرکت

- Mixamo برای شروع سریع و انیمیشن‌های پایه.
- مجموعه‌های Motion Capture با مجوز مناسب برای استفاده تجاری.
- حرکت ضبط‌شده از انسان واقعی برای رفتارهای تبلیغاتی اختصاصی.
- اصلاحات دستی در Blender برای حرکت‌هایی که با مدل کاراکتر یا محصول سازگار نیستند.

Mixamo می‌تواند برای نمونه اولیه مفید باشد و Adobe استفاده از انیمیشن‌های آن را در پروژه‌های شخصی و تجاری مجاز می‌داند، اما محدودیت توزیع فایل‌های خام و شرایط فعلی سرویس باید قبل از ساخت محصول تجاری بررسی شود.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://helpx.adobe.com\&sz=32)

Creative Cloud

+1



لینک‌ها:

- [Mixamo](https://www.mixamo.com/)
- [Blender Manual](https://docs.blender.org/manual/en/latest/)
- [Blender Python API](https://docs.blender.org/api/current/)

### دسته‌بندی اولیه حرکت‌ها

A. حرکت‌های پایه بدن

Idle، تنفس، انتقال وزن، ایستادن، نشستن، بلند شدن، راه رفتن و چرخیدن.

B. حرکت‌های دست و بازو

اشاره کردن، باز کردن دست، حرکت توضیحی هنگام حرف زدن، دست تکان دادن و نشان دادن محصول.

C. تعامل با اشیا

دست دراز کردن، گرفتن، بلند کردن، نگه داشتن، چرخاندن، گذاشتن و رها کردن.

D. حرکت‌های سر و صورت

نگاه کردن، پلک زدن، لبخند، تعجب، حالت خنثی و هماهنگی با صحبت.

E. حرکت‌های مخصوص تبلیغات

نگاه به محصول، نشان دادن به دوربین، معرفی، واکنش مثبت، اشاره به قیمت و دعوت به خرید.

برای شروع، حتی ۲۰ تا ۵۰ حرکت باکیفیت کافی است؛ به شرطی که کاربردهای مشخص داشته باشند و بتوان آن‌ها را به شکل قابل اعتماد به هم متصل کرد. تعداد بیشتر، جای کیفیت و سازگاری را نمی‌گیرد.

### ساختار فایل حرکتی

هر حرکت باید یک فایل انیمیشن و یک فایل Metadata داشته باشد.

```
assets/motions/
├── idle_breathing.fbx
├── walk_normal.fbx
├── stop_walk.fbx
├── reach_forward.fbx
├── grasp_object.fbx
├── hold_object.fbx
├── present_product.fbx
├── put_down.fbx
└── gestures/
```

نمونه Metadata:

```

{
  "id": "reach_forward_v1",
  "category": "interaction",
  "file": "reach_forward.fbx",
  "duration_seconds": 1.2,
  "rig_profile": "humanoid_v1",
  "start_state": "standing_idle",
  "end_state": "arm_extended",
  "root_motion": false,
  "contact": {
    "target": "right_hand",
    "required": true
  },
  "quality": {
    "reviewed": true,
    "loopable": false
  },
  "license_id": "internal_asset_registry"
}

```

این Metadata صرفاً نمونه قرارداد داخلی است؛ نام استخوان‌ها، واحدها و اطلاعات تماس باید با انیمیشن واقعی هماهنگ شوند.

### مشکل مهم: حرکت‌های مستقل لزوماً قابل اتصال نیستند

فرض کن حرکت راه رفتن با پای چپ جلو تمام شود، اما حرکت بعدی با پای راست جلو شروع شود. اتصال ساده آن‌ها باعث پرش پا یا تغییر ناگهانی بدن می‌شود.

پس هر حرکت باید اطلاعات زیر را داشته باشد:

- وضعیت شروع و پایان اسکلت.
- جهت و سرعت حرکت.
- محل پای تکیه‌گاه.
- حالت دست‌ها.
- امکان اتصال به حرکت‌های دیگر.
- محل تماس با محصول یا محیط.
- محدودیت‌های حرکتی و نیازهای خاص.

موتور باید بتواند بین حرکت‌ها Blend انجام دهد، اما Blend به‌تنهایی کافی نیست. برای حرکت‌های تعاملی به اصلاح تماس، IK و کنترل وضعیت بدن هم نیاز داریم.

## ۶. Motion Graph و موتور ترکیب حرکت

به‌جای انتخاب تصادفی انیمیشن‌ها، یک گراف از وضعیت‌های بدن می‌سازیم.

\#chatgpt-mermaid-\_r_2gb\_{font-family:-apple-system-body,ui-sans-serif,-apple-system,system-ui,"Segoe UI",Helvetica,"Apple Color Emoji",Arial,sans-serif,"Segoe UI Emoji","Segoe UI Symbol";font-size:16px;fill:rgb(237, 237, 237);}@keyframes edge-animation-frame{from{stroke-dashoffset:0;}}@keyframes dash{to{stroke-dashoffset:0;}}#chatgpt-mermaid-\_r_2gb\_ .edge-animation-slow{stroke-dasharray:9,5!important;stroke-dashoffset:900;animation:dash 50s linear infinite;stroke-linecap:round;}#chatgpt-mermaid-\_r_2gb\_ .edge-animation-fast{stroke-dasharray:9,5!important;stroke-dashoffset:900;animation:dash 20s linear infinite;stroke-linecap:round;}#chatgpt-mermaid-\_r_2gb\_ .error-icon{fill:rgb(48, 48, 48);}#chatgpt-mermaid-\_r_2gb\_ .error-text{fill:rgb(237, 237, 237);stroke:rgb(237, 237, 237);}#chatgpt-mermaid-\_r_2gb\_ .edge-thickness-normal{stroke-width:1px;}#chatgpt-mermaid-\_r_2gb\_ .edge-thickness-thick{stroke-width:3.5px;}#chatgpt-mermaid-\_r_2gb\_ .edge-pattern-solid{stroke-dasharray:0;}#chatgpt-mermaid-\_r_2gb\_ .edge-thickness-invisible{stroke-width:0;fill:none;}#chatgpt-mermaid-\_r_2gb\_ .edge-pattern-dashed{stroke-dasharray:3;}#chatgpt-mermaid-\_r_2gb\_ .edge-pattern-dotted{stroke-dasharray:2;}#chatgpt-mermaid-\_r_2gb\_ .marker{fill:rgb(175, 175, 175);stroke:rgb(175, 175, 175);}#chatgpt-mermaid-\_r_2gb\_ .marker.cross{stroke:rgb(175, 175, 175);}#chatgpt-mermaid-\_r_2gb\_ svg{font-family:-apple-system-body,ui-sans-serif,-apple-system,system-ui,"Segoe UI",Helvetica,"Apple Color Emoji",Arial,sans-serif,"Segoe UI Emoji","Segoe UI Symbol";font-size:16px;}#chatgpt-mermaid-\_r_2gb\_ p{margin:0;}#chatgpt-mermaid-\_r_2gb\_ .label{font-family:-apple-system-body,ui-sans-serif,-apple-system,system-ui,"Segoe UI",Helvetica,"Apple Color Emoji",Arial,sans-serif,"Segoe UI Emoji","Segoe UI Symbol";color:rgb(237, 237, 237);}#chatgpt-mermaid-\_r_2gb\_ .cluster-label text{fill:rgb(237, 237, 237);}#chatgpt-mermaid-\_r_2gb\_ .cluster-label span{color:rgb(237, 237, 237);}#chatgpt-mermaid-\_r_2gb\_ .cluster-label span p{background-color:transparent;}#chatgpt-mermaid-\_r_2gb\_ .label text,#chatgpt-mermaid-\_r_2gb\_ span{fill:rgb(237, 237, 237);color:rgb(237, 237, 237);}#chatgpt-mermaid-\_r_2gb\_ .node rect,#chatgpt-mermaid-\_r_2gb\_ .node circle,#chatgpt-mermaid-\_r_2gb\_ .node ellipse,#chatgpt-mermaid-\_r_2gb\_ .node polygon,#chatgpt-mermaid-\_r_2gb\_ .node path{fill:rgb(51, 24, 37);stroke:rgb(171, 79, 122);stroke-width:1px;}#chatgpt-mermaid-\_r_2gb\_ .rough-node .label text,#chatgpt-mermaid-\_r_2gb\_ .node .label text,#chatgpt-mermaid-\_r_2gb\_ .image-shape .label,#chatgpt-mermaid-\_r_2gb\_ .icon-shape .label{text-anchor:middle;}#chatgpt-mermaid-\_r_2gb\_ .node .katex path{fill:#000;stroke:#000;stroke-width:1px;}#chatgpt-mermaid-\_r_2gb\_ .rough-node .label,#chatgpt-mermaid-\_r_2gb\_ .node .label,#chatgpt-mermaid-\_r_2gb\_ .image-shape .label,#chatgpt-mermaid-\_r_2gb\_ .icon-shape .label{text-align:center;}#chatgpt-mermaid-\_r_2gb\_ .node.clickable{cursor:pointer;}#chatgpt-mermaid-\_r_2gb\_ .root .anchor path{fill:rgb(175, 175, 175)!important;stroke-width:0;stroke:rgb(175, 175, 175);}#chatgpt-mermaid-\_r_2gb\_ .arrowheadPath{fill:rgb(175, 175, 175);}#chatgpt-mermaid-\_r_2gb\_ .edgePath .path{stroke:rgb(175, 175, 175);stroke-width:1px;}#chatgpt-mermaid-\_r_2gb\_ .flowchart-link{stroke:rgb(175, 175, 175);fill:none;}#chatgpt-mermaid-\_r_2gb\_ .edgeLabel{background-color:rgb(0, 0, 0);text-align:center;}#chatgpt-mermaid-\_r_2gb\_ .edgeLabel p{background-color:rgb(0, 0, 0);}#chatgpt-mermaid-\_r_2gb\_ .edgeLabel rect{opacity:0.5;background-color:rgb(0, 0, 0);fill:rgb(0, 0, 0);}#chatgpt-mermaid-\_r_2gb\_ .labelBkg{background-color:rgba(0, 0, 0, 0.5);}#chatgpt-mermaid-\_r_2gb\_ .cluster rect{fill:rgb(48, 48, 48);stroke:rgba(255, 255, 255, 0.15);stroke-width:1px;}#chatgpt-mermaid-\_r_2gb\_ .cluster text{fill:rgb(237, 237, 237);}#chatgpt-mermaid-\_r_2gb\_ .cluster span{color:rgb(237, 237, 237);}#chatgpt-mermaid-\_r_2gb\_ div.mermaidTooltip{position:absolute;text-align:center;max-width:200px;padding:2px;font-family:-apple-system-body,ui-sans-serif,-apple-system,system-ui,"Segoe UI",Helvetica,"Apple Color Emoji",Arial,sans-serif,"Segoe UI Emoji","Segoe UI Symbol";font-size:12px;background:rgb(48, 48, 48);border:1px solid rgba(255, 255, 255, 0.15);border-radius:2px;pointer-events:none;z-index:100;}#chatgpt-mermaid-\_r_2gb\_ .flowchartTitleText{text-anchor:middle;font-size:18px;fill:rgb(237, 237, 237);}#chatgpt-mermaid-\_r_2gb\_ rect.text{fill:none;stroke-width:0;}#chatgpt-mermaid-\_r_2gb\_ .icon-shape,#chatgpt-mermaid-\_r_2gb\_ .image-shape{background-color:rgb(0, 0, 0);text-align:center;}#chatgpt-mermaid-\_r_2gb\_ .icon-shape p,#chatgpt-mermaid-\_r_2gb\_ .image-shape p{background-color:rgb(0, 0, 0);padding:2px;}#chatgpt-mermaid-\_r_2gb\_ .icon-shape .label rect,#chatgpt-mermaid-\_r_2gb\_ .image-shape .label rect{opacity:0.5;background-color:rgb(0, 0, 0);fill:rgb(0, 0, 0);}#chatgpt-mermaid-\_r_2gb\_ .label-icon{display:inline-block;height:1em;overflow:visible;vertical-align:-0.125em;}#chatgpt-mermaid-\_r_2gb\_ .node .label-icon path{fill:currentColor;stroke:revert;stroke-width:revert;}#chatgpt-mermaid-\_r_2gb\_ .node .neo-node{stroke:rgb(171, 79, 122);}#chatgpt-mermaid-\_r_2gb\_ [data-look="neo"].node rect,#chatgpt-mermaid-\_r_2gb\_ [data-look="neo"].cluster rect,#chatgpt-mermaid-\_r_2gb\_ [data-look="neo"].node polygon{stroke:url(#chatgpt-mermaid-\_r_2gb\_-gradient);filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-\_r_2gb\_ [data-look="neo"].swimlane.cluster rect{filter:none;}#chatgpt-mermaid-\_r_2gb\_ [data-look="neo"].node path{stroke:url(#chatgpt-mermaid-\_r_2gb\_-gradient);stroke-width:1px;}#chatgpt-mermaid-\_r_2gb\_ [data-look="neo"].node .outer-path{filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-\_r_2gb\_ [data-look="neo"].node .neo-line path{stroke:rgb(171, 79, 122);filter:none;}#chatgpt-mermaid-\_r_2gb\_ [data-look="neo"].node circle{stroke:url(#chatgpt-mermaid-\_r_2gb\_-gradient);filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-\_r_2gb\_ [data-look="neo"].node circle .state-start{fill:#000000;}#chatgpt-mermaid-\_r_2gb\_ [data-look="neo"].icon-shape .icon{fill:url(#chatgpt-mermaid-\_r_2gb\_-gradient);filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-\_r_2gb\_ [data-look="neo"].icon-shape .icon-neo path{stroke:url(#chatgpt-mermaid-\_r_2gb\_-gradient);filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-\_r_2gb\_ .node text{font-size:14px;font-weight:600;letter-spacing:normal;fill:rgb(255, 186, 218);}#chatgpt-mermaid-\_r_2gb\_ .edgeLabels text{font-size:13px;font-weight:600;letter-spacing:-0.08px;fill:rgb(255, 186, 218);}#chatgpt-mermaid-\_r_2gb\_ .node tspan[font-weight="normal"],#chatgpt-mermaid-\_r_2gb\_ .edgeLabels tspan[font-weight="normal"]{font-weight:600;}#chatgpt-mermaid-\_r_2gb\_ .edgeLabel .label rect{opacity:1;rx:13px;ry:13px;fill:rgb(41, 16, 28);stroke:rgb(95, 53, 72);stroke-width:1px;}#chatgpt-mermaid-\_r_2gb\_ .node rect,#chatgpt-mermaid-\_r_2gb\_ .node circle,#chatgpt-mermaid-\_r_2gb\_ .node ellipse,#chatgpt-mermaid-\_r_2gb\_ .node polygon,#chatgpt-mermaid-\_r_2gb\_ .node path{fill:rgb(77, 31, 52);stroke:rgba(255, 255, 255, 0.1);stroke-width:1px;}#chatgpt-mermaid-\_r_2gb\_ .node rect{rx:16px;ry:16px;}#chatgpt-mermaid-\_r_2gb\_ .node.mermaid-decision .label-container{fill:rgb(41, 16, 28);stroke:rgb(95, 53, 72);stroke-dasharray:2,2;}#chatgpt-mermaid-\_r_2gb\_ .edgePaths .flowchart-link{stroke:rgb(175, 175, 175);stroke-width:1px;stroke-linecap:round;stroke-linejoin:round;}#chatgpt-mermaid-\_r_2gb\_ .marker{fill:rgb(175, 175, 175);stroke:rgb(175, 175, 175);}#chatgpt-mermaid-\_r_2gb\_ :root{--mermaid-font-family:-apple-system-body,ui-sans-serif,-apple-system,system-ui,"Segoe UI",Helvetica,"Apple Color Emoji",Arial,sans-serif,"Segoe UI Emoji","Segoe UI Symbol";}IdleWalkStopLook at ProductReachGraspHold ProductPresent ProductPut Down

هر گره یک وضعیت یا حرکت است. هر یال مشخص می‌کند چه زمانی و تحت چه شرایطی می‌توان به وضعیت بعدی رفت.

مثلاً:

```
Walk → Stop
شرط: نزدیک شدن به محل هدف

Look → Reach
شرط: محصول قابل دسترس باشد

Reach → Grasp
شرط: دست به محل گرفتن محصول برسد

Grasp → Hold
شرط: تماس دست و محصول برقرار شده باشد
```

### سه قابلیت فنی که ضروری‌اند

Motion Blending: ترکیب نرم حرکت قبلی و بعدی.

Inverse Kinematics (IK): رساندن دست به یک نقطه مشخص، بدون اینکه لازم باشد برای هر محصول انیمیشن جدا بسازیم.

Contact Constraints: حفظ تماس دست با محصول، پا با زمین و بدن با صندلی یا سطح محیط.

برای نمونه، وقتی کاراکتر بطری را برمی‌دارد، بطری باید بعد از گرفتن به دست متصل شود و هنگام حرکت دست از آن جدا نشود. این کار با تنظیم نقطه گرفتن و انتقال کنترل‌شده محصول از محل اولیه به کنترل دست انجام می‌شود.

### نکته اجرایی

در نسخه اول، به‌جای ساخت یک موتور عمومی پیچیده، سه تعامل را به‌صورت قابل اعتماد پیاده می‌کنیم:

1. گرفتن محصول از روی میز.
2. نگه داشتن و نشان دادن محصول.
3. گذاشتن محصول روی میز.

اگر همین سه تعامل طبیعی نباشند، اضافه کردن ۱۰۰ حرکت دیگر ارزش چندانی ندارد.

## ۷. محصول: سخت‌ترین بخش تبلیغات تعاملی

یک انسان واقع‌گرایانه که فقط راه می‌رود و صحبت می‌کند، نسبتاً ساده‌تر از انسانی است که محصولی را به شکل طبیعی برمی‌دارد.

برای UpMarket باید دو حالت متفاوت تعریف کنیم.

[30ml 50ml 100ml Cosmetic Airless Bottle Airless Dispensing Bottle for Skincare and Cosmetics](https://images.openai.com/static-rsc-4/uryt3Xz1QjDw3cHv1ZoLNdsdjTvlCnMOD1tnjrFOA6Nb3a8U2Ph07jj9y4yrUhcmzcrOHwx8T1VHiB6zyEMdTY71HYEJ-RE84ImggXWQG4PNQOh5VaUELqYwRntLw7biM-oEmWUboZxKIZBvXX1vGaE0iwhKV_0zv8T6YyAN4sE?purpose=inline)

حالت A — محصول بدون تعامل مستقیم

محصول در صحنه، روی میز یا کنار کاراکتر قرار می‌گیرد. می‌توانیم از عکس محصول به‌عنوان تصویر دوبعدی در ترکیب نهایی استفاده کنیم، یا آن را روی یک سطح مناسب نمایش دهیم.

سریع‌تر، ارزان‌تر و مناسب اولین نسخه تجاری.

[She EDP Women 100ml  – BEAUTIKA](https://images.openai.com/static-rsc-4/HrQoPmy6fTatZ9Q5m2U9hLZ0drC6eKwnmByKgokY-hJxL4r3ZrlzlyP6y_XkfNooKDbLyIaX7SLY2vrwzrxU-0iPd9yzWetch9bNXWEulzuajuWwMlG2wHaOoxRLR447-N6g6iNZcbu0Bc8-Wbh7pWHmW9csPJZJYaFkv_PiIjA?purpose=inline)

حالت B — محصول در دست انسان

برای تعامل واقعاً طبیعی، ترجیحاً به مدل سه‌بعدی محصول نیاز داریم. مدل باید ابعاد واقعی، شکل، جنس، نقطه گرفتن و جهت صحیح برچسب را داشته باشد.

پیچیده‌تر، اما مناسب تبلیغات نمایشی و معرفی محصول.

### تبدیل عکس محصول به مدل سه‌بعدی

در نسخه اول، تبدیل خودکار همه عکس‌ها به مدل سه‌بعدی را شرط لازم نمی‌گذاریم. این قابلیت می‌تواند از چند روش تأمین شود:

1. دریافت مدل GLB/FBX از فروشنده یا تولیدکننده.
2. ساخت مدل ساده و متناسب با شکل محصول در یک ابزار سه‌بعدی.
3. استفاده از مدل سه‌بعدی تولیدشده با ابزارهای Image-to-3D، پس از بررسی کیفیت و اصلاح.
4. استفاده از عکس واقعی محصول در شات‌های نزدیک و ترکیب تصویری، وقتی مدل سه‌بعدی کافی نداریم.

قاعده حیاتی: اگر بطری در دست کاراکتر قرار می‌گیرد، دست باید واقعاً آن را بگیرد؛ نباید محصول فقط به کف دست چسبانده شود و انگشت‌ها از بدنه عبور کنند.

برای تعامل، یک نقطه گرفتن تعریف می‌کنیم:

```
{
  "product_id": "perfume_001",
  "grasp_profile": "bottle_grip_v1",
  "grasp_anchor": "grip_center",
  "hand": "right",
  "attach_on_event": "grasp",
  "detach_on_event": "release"
}
```

در زمان تماس، موتور با IK محل دست را به نقطه گرفتن می‌رساند؛ سپس در زمان تعیین‌شده محصول به کنترل دست متصل می‌شود. برای محصول‌های مختلف می‌توانیم پروفایل‌های گرفتن جداگانه بسازیم: بطری، جعبه، گوشی، لباس و ظرف.

## ۸. محیط سه‌بعدی و نورپردازی واقع‌گرایانه

برای ساخت تبلیغ واقعی‌نما، به‌جای تولید یک محیط تازه برای هر درخواست، مجموعه‌ای از محیط‌های آماده با کیفیت بالا ایجاد می‌کنیم.

### محیط‌های نسخه اول

[Front view on bright living room interior with panoramic window](https://images.openai.com/static-rsc-4/hFHzxgjpZSlwLRZyPa3iIVZyvBiNN8ytDHb2Ez--qYQPXMvbyp5ZLmud-jhqwsSykR72qWJxNyP2TTKHnxxGlVNFnm8IzGdTVwbtkNQ2HmMi0DzrdOx6G5XosxWjPSVzk9wsfwmZQKRN3L7j4o_4zzFZeS2eaPDmC-UulEGHoX9rpXvplJRKJeZYNPGxvdl9?purpose=inline)

خانه مدرن

محصولات خانگی، زیبایی و سبک زندگی

[Premium Beauty Brands & Distribution | KOREOS GROUP](https://images.openai.com/static-rsc-4/6QkeCz0X3oMGOptd1zA7uswSYxDHv5FZwb6P8eKJl7HA8ny9jKlzx1eybBRpncEelT3Mfp9TX1E0NDYuDamQUEo_OooddSYmMIlhWjGw9KJwEY8HIDvLPkEjBGptJm1Z4Nkh-de2WnCtymcirkiMPCbLZuFQOq1RioiuIjk9KFY?purpose=inline)

فروشگاه

معرفی محصول و تعامل با قفسه

[Sérum hidratante antiarrugas Ultra Booster de La mer](https://images.openai.com/static-rsc-4/koy1QiN0z2-uOFaelLso79CXwE2u-Oc072aT1ymw8_M3r_8thDmGcYPEA40jWWJxRP0jYMTAs7_vMafw1YTETT-JNqtZjFB7sOBeu4rzlZ0ybkU_JeaTj1pOCSMPHuhcE_j8Nom4E7VJHGOTZiFX7tBGCMckhZW975CPhTln834?purpose=inline)

استودیوی تبلیغاتی

محصول‌محور و قابل کنترل

[AGL Grass - Pixelcarve Inc.](https://images.openai.com/static-rsc-4/RgDr6Yyn2cDVTnf07Mp7aqks0-H_pBSdE9D_nDceQeiTt06OtC3Nz6_6YraXXyhxQVAKCyEzEXwRbNdfPttsu0AMBx74FjPsauGZVq5xJOs6L8buV9htrtpaIOFCKOdScB7nj2ykKvNiU1vKl99q8Rb5oAO7xClo9SKthzZl0Jw?purpose=inline)

دفتر کار

لوازم دیجیتال و خدمات

### چه چیزهایی محیط را واقعی می‌کند؟

- نور اصلی، نور پرکننده و نور پشت سوژه.
- سایه تماس زیر پا و محصول.
- بازتاب‌های متناسب با جنس سطوح.
- مقیاس درست انسان، میز، صندلی و اشیا.
- عمق میدان و حرکت کنترل‌شده دوربین.
- مواد PBR برای پوست، پارچه، فلز، شیشه و پلاستیک.
- جزئیات محیط و جلوگیری از صحنه‌های بیش از حد تمیز و مصنوعی.

برای رندر نهایی می‌توانیم از Cycles با OptiX روی کارت NVIDIA استفاده کنیم؛ Blender از رندر GPU پشتیبانی می‌کند، اما محدودیت حافظه GPU و پیچیدگی صحنه مستقیماً بر امکان اجرا و سرعت اثر می‌گذارند.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://docs.blender.org\&sz=32)

Blender 5.2 LTS Manual

+1



برای پیش‌نمایش، از تنظیمات سبک‌تر و رزولوشن پایین‌تر استفاده می‌کنیم؛ سپس تنظیمات نهایی را برای هر محیط کالیبره می‌کنیم.

### حرکت دوربین

برای شروع، دوربین را به چند الگوی استاندارد محدود می‌کنیم:

- Medium Shot برای معرفی انسان.
- Close-up برای محصول.
- Slow Dolly برای نزدیک شدن آرام دوربین.
- Over-the-Shoulder برای دیدن تعامل.
- Product Hero Shot برای پایان تبلیغ.

AI فقط یکی از الگوهای معتبر را انتخاب می‌کند. دوربین نباید مستقل و بدون توجه به وضعیت دست، صورت و محصول حرکت کند.

## ۹. صدا، دیالوگ و هماهنگی لب

صدای طبیعی فقط به کیفیت TTS وابسته نیست. زمان‌بندی دیالوگ، مکث‌ها، شدت بیان و هماهنگی لب و صورت نیز اهمیت دارند.

### خط لوله صدا

\#chatgpt-mermaid-\_r_2ib\_{font-family:-apple-system-body,ui-sans-serif,-apple-system,system-ui,"Segoe UI",Helvetica,"Apple Color Emoji",Arial,sans-serif,"Segoe UI Emoji","Segoe UI Symbol";font-size:16px;fill:rgb(237, 237, 237);}@keyframes edge-animation-frame{from{stroke-dashoffset:0;}}@keyframes dash{to{stroke-dashoffset:0;}}#chatgpt-mermaid-\_r_2ib\_ .edge-animation-slow{stroke-dasharray:9,5!important;stroke-dashoffset:900;animation:dash 50s linear infinite;stroke-linecap:round;}#chatgpt-mermaid-\_r_2ib\_ .edge-animation-fast{stroke-dasharray:9,5!important;stroke-dashoffset:900;animation:dash 20s linear infinite;stroke-linecap:round;}#chatgpt-mermaid-\_r_2ib\_ .error-icon{fill:rgb(48, 48, 48);}#chatgpt-mermaid-\_r_2ib\_ .error-text{fill:rgb(237, 237, 237);stroke:rgb(237, 237, 237);}#chatgpt-mermaid-\_r_2ib\_ .edge-thickness-normal{stroke-width:1px;}#chatgpt-mermaid-\_r_2ib\_ .edge-thickness-thick{stroke-width:3.5px;}#chatgpt-mermaid-\_r_2ib\_ .edge-pattern-solid{stroke-dasharray:0;}#chatgpt-mermaid-\_r_2ib\_ .edge-thickness-invisible{stroke-width:0;fill:none;}#chatgpt-mermaid-\_r_2ib\_ .edge-pattern-dashed{stroke-dasharray:3;}#chatgpt-mermaid-\_r_2ib\_ .edge-pattern-dotted{stroke-dasharray:2;}#chatgpt-mermaid-\_r_2ib\_ .marker{fill:rgb(175, 175, 175);stroke:rgb(175, 175, 175);}#chatgpt-mermaid-\_r_2ib\_ .marker.cross{stroke:rgb(175, 175, 175);}#chatgpt-mermaid-\_r_2ib\_ svg{font-family:-apple-system-body,ui-sans-serif,-apple-system,system-ui,"Segoe UI",Helvetica,"Apple Color Emoji",Arial,sans-serif,"Segoe UI Emoji","Segoe UI Symbol";font-size:16px;}#chatgpt-mermaid-\_r_2ib\_ p{margin:0;}#chatgpt-mermaid-\_r_2ib\_ .label{font-family:-apple-system-body,ui-sans-serif,-apple-system,system-ui,"Segoe UI",Helvetica,"Apple Color Emoji",Arial,sans-serif,"Segoe UI Emoji","Segoe UI Symbol";color:rgb(237, 237, 237);}#chatgpt-mermaid-\_r_2ib\_ .cluster-label text{fill:rgb(237, 237, 237);}#chatgpt-mermaid-\_r_2ib\_ .cluster-label span{color:rgb(237, 237, 237);}#chatgpt-mermaid-\_r_2ib\_ .cluster-label span p{background-color:transparent;}#chatgpt-mermaid-\_r_2ib\_ .label text,#chatgpt-mermaid-\_r_2ib\_ span{fill:rgb(237, 237, 237);color:rgb(237, 237, 237);}#chatgpt-mermaid-\_r_2ib\_ .node rect,#chatgpt-mermaid-\_r_2ib\_ .node circle,#chatgpt-mermaid-\_r_2ib\_ .node ellipse,#chatgpt-mermaid-\_r_2ib\_ .node polygon,#chatgpt-mermaid-\_r_2ib\_ .node path{fill:rgb(51, 24, 37);stroke:rgb(171, 79, 122);stroke-width:1px;}#chatgpt-mermaid-\_r_2ib\_ .rough-node .label text,#chatgpt-mermaid-\_r_2ib\_ .node .label text,#chatgpt-mermaid-\_r_2ib\_ .image-shape .label,#chatgpt-mermaid-\_r_2ib\_ .icon-shape .label{text-anchor:middle;}#chatgpt-mermaid-\_r_2ib\_ .node .katex path{fill:#000;stroke:#000;stroke-width:1px;}#chatgpt-mermaid-\_r_2ib\_ .rough-node .label,#chatgpt-mermaid-\_r_2ib\_ .node .label,#chatgpt-mermaid-\_r_2ib\_ .image-shape .label,#chatgpt-mermaid-\_r_2ib\_ .icon-shape .label{text-align:center;}#chatgpt-mermaid-\_r_2ib\_ .node.clickable{cursor:pointer;}#chatgpt-mermaid-\_r_2ib\_ .root .anchor path{fill:rgb(175, 175, 175)!important;stroke-width:0;stroke:rgb(175, 175, 175);}#chatgpt-mermaid-\_r_2ib\_ .arrowheadPath{fill:rgb(175, 175, 175);}#chatgpt-mermaid-\_r_2ib\_ .edgePath .path{stroke:rgb(175, 175, 175);stroke-width:1px;}#chatgpt-mermaid-\_r_2ib\_ .flowchart-link{stroke:rgb(175, 175, 175);fill:none;}#chatgpt-mermaid-\_r_2ib\_ .edgeLabel{background-color:rgb(0, 0, 0);text-align:center;}#chatgpt-mermaid-\_r_2ib\_ .edgeLabel p{background-color:rgb(0, 0, 0);}#chatgpt-mermaid-\_r_2ib\_ .edgeLabel rect{opacity:0.5;background-color:rgb(0, 0, 0);fill:rgb(0, 0, 0);}#chatgpt-mermaid-\_r_2ib\_ .labelBkg{background-color:rgba(0, 0, 0, 0.5);}#chatgpt-mermaid-\_r_2ib\_ .cluster rect{fill:rgb(48, 48, 48);stroke:rgba(255, 255, 255, 0.15);stroke-width:1px;}#chatgpt-mermaid-\_r_2ib\_ .cluster text{fill:rgb(237, 237, 237);}#chatgpt-mermaid-\_r_2ib\_ .cluster span{color:rgb(237, 237, 237);}#chatgpt-mermaid-\_r_2ib\_ div.mermaidTooltip{position:absolute;text-align:center;max-width:200px;padding:2px;font-family:-apple-system-body,ui-sans-serif,-apple-system,system-ui,"Segoe UI",Helvetica,"Apple Color Emoji",Arial,sans-serif,"Segoe UI Emoji","Segoe UI Symbol";font-size:12px;background:rgb(48, 48, 48);border:1px solid rgba(255, 255, 255, 0.15);border-radius:2px;pointer-events:none;z-index:100;}#chatgpt-mermaid-\_r_2ib\_ .flowchartTitleText{text-anchor:middle;font-size:18px;fill:rgb(237, 237, 237);}#chatgpt-mermaid-\_r_2ib\_ rect.text{fill:none;stroke-width:0;}#chatgpt-mermaid-\_r_2ib\_ .icon-shape,#chatgpt-mermaid-\_r_2ib\_ .image-shape{background-color:rgb(0, 0, 0);text-align:center;}#chatgpt-mermaid-\_r_2ib\_ .icon-shape p,#chatgpt-mermaid-\_r_2ib\_ .image-shape p{background-color:rgb(0, 0, 0);padding:2px;}#chatgpt-mermaid-\_r_2ib\_ .icon-shape .label rect,#chatgpt-mermaid-\_r_2ib\_ .image-shape .label rect{opacity:0.5;background-color:rgb(0, 0, 0);fill:rgb(0, 0, 0);}#chatgpt-mermaid-\_r_2ib\_ .label-icon{display:inline-block;height:1em;overflow:visible;vertical-align:-0.125em;}#chatgpt-mermaid-\_r_2ib\_ .node .label-icon path{fill:currentColor;stroke:revert;stroke-width:revert;}#chatgpt-mermaid-\_r_2ib\_ .node .neo-node{stroke:rgb(171, 79, 122);}#chatgpt-mermaid-\_r_2ib\_ [data-look="neo"].node rect,#chatgpt-mermaid-\_r_2ib\_ [data-look="neo"].cluster rect,#chatgpt-mermaid-\_r_2ib\_ [data-look="neo"].node polygon{stroke:url(#chatgpt-mermaid-\_r_2ib\_-gradient);filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-\_r_2ib\_ [data-look="neo"].swimlane.cluster rect{filter:none;}#chatgpt-mermaid-\_r_2ib\_ [data-look="neo"].node path{stroke:url(#chatgpt-mermaid-\_r_2ib\_-gradient);stroke-width:1px;}#chatgpt-mermaid-\_r_2ib\_ [data-look="neo"].node .outer-path{filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-\_r_2ib\_ [data-look="neo"].node .neo-line path{stroke:rgb(171, 79, 122);filter:none;}#chatgpt-mermaid-\_r_2ib\_ [data-look="neo"].node circle{stroke:url(#chatgpt-mermaid-\_r_2ib\_-gradient);filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-\_r_2ib\_ [data-look="neo"].node circle .state-start{fill:#000000;}#chatgpt-mermaid-\_r_2ib\_ [data-look="neo"].icon-shape .icon{fill:url(#chatgpt-mermaid-\_r_2ib\_-gradient);filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-\_r_2ib\_ [data-look="neo"].icon-shape .icon-neo path{stroke:url(#chatgpt-mermaid-\_r_2ib\_-gradient);filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-\_r_2ib\_ .node text{font-size:14px;font-weight:600;letter-spacing:normal;fill:rgb(255, 186, 218);}#chatgpt-mermaid-\_r_2ib\_ .edgeLabels text{font-size:13px;font-weight:600;letter-spacing:-0.08px;fill:rgb(255, 186, 218);}#chatgpt-mermaid-\_r_2ib\_ .node tspan[font-weight="normal"],#chatgpt-mermaid-\_r_2ib\_ .edgeLabels tspan[font-weight="normal"]{font-weight:600;}#chatgpt-mermaid-\_r_2ib\_ .edgeLabel .label rect{opacity:1;rx:13px;ry:13px;fill:rgb(41, 16, 28);stroke:rgb(95, 53, 72);stroke-width:1px;}#chatgpt-mermaid-\_r_2ib\_ .node rect,#chatgpt-mermaid-\_r_2ib\_ .node circle,#chatgpt-mermaid-\_r_2ib\_ .node ellipse,#chatgpt-mermaid-\_r_2ib\_ .node polygon,#chatgpt-mermaid-\_r_2ib\_ .node path{fill:rgb(77, 31, 52);stroke:rgba(255, 255, 255, 0.1);stroke-width:1px;}#chatgpt-mermaid-\_r_2ib\_ .node rect{rx:16px;ry:16px;}#chatgpt-mermaid-\_r_2ib\_ .node.mermaid-decision .label-container{fill:rgb(41, 16, 28);stroke:rgb(95, 53, 72);stroke-dasharray:2,2;}#chatgpt-mermaid-\_r_2ib\_ .edgePaths .flowchart-link{stroke:rgb(175, 175, 175);stroke-width:1px;stroke-linecap:round;stroke-linejoin:round;}#chatgpt-mermaid-\_r_2ib\_ .marker{fill:rgb(175, 175, 175);stroke:rgb(175, 175, 175);}#chatgpt-mermaid-\_r_2ib\_ :root{--mermaid-font-family:-apple-system-body,ui-sans-serif,-apple-system,system-ui,"Segoe UI",Helvetica,"Apple Color Emoji",Arial,sans-serif,"Segoe UI Emoji","Segoe UI Symbol";}متن تبلیغاصلاح و تقسیم دیالوگTTSفایل صوتیاستخراج زمان گفتارهماهنگی لبحرکت صورت و سررندرمیکس صداترکیب نهایی

### پیشنهاد اجرایی

1. متن دیالوگ را کوتاه و متناسب با مدت ویدئو می‌نویسیم.
2. TTS فایل صوتی تولید می‌کند.
3. زمان‌بندی کلمات یا واج‌ها را استخراج می‌کنیم.
4. حرکت دهان را با ریگ صورت هماهنگ می‌کنیم.
5. پلک زدن، حرکت سر و حالت صورت را جداگانه اضافه می‌کنیم.
6. در پایان، صدای گفتار، موسیقی و افکت‌ها میکس می‌شوند.

برای هماهنگی لب می‌توانیم Rhubarb Lip Sync و افزونه سازگار آن را ارزیابی کنیم؛ نسخه NG برای Blender جدیدتر وجود دارد. بااین‌حال، برای زبان فارسی باید خروجی واج‌ها، شکل‌های دهان و کیفیت هم‌زمانی را آزمایش کنیم؛ سازگاری با Blender به‌تنهایی تضمین‌کننده کیفیت فارسی نیست.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://github.com\&sz=32)

GitHub

+1



توصیه: در نسخه اول یک صدای فارسی باکیفیت و یک ریگ صورت مشخص را انتخاب کن. اضافه کردن چندین صدا و چندین زبان پیش از حل هماهنگی لب، پیچیدگی غیرضروری ایجاد می‌کند.

## ۱۰. کارگردان هوش مصنوعی: از درخواست کاربر تا برنامه اجرایی

در این معماری، مدل زبانی قرار نیست مختصات استخوان‌ها یا Keyframeها را مستقیماً تولید کند. وظیفه آن تبدیل درخواست به یک برنامه محدود، قابل اعتبارسنجی و قابل اجرا است.

مثلاً کاربر در UpMarket می‌نویسد:

> برای این عطر یک تبلیغ ۱۵ ثانیه‌ای بساز. یک خانم در فروشگاه عطر را از روی میز بردارد، نشان بدهد و درباره رایحه آن صحبت کند.

موتور این درخواست را به مراحل زیر تبدیل می‌کند:

1. انتخاب قالب تبلیغاتی.
2. انتخاب محیط و کاراکتر.
3. تقسیم سناریو به شات‌ها.
4. انتخاب حرکت‌های موجود در کتابخانه.
5. تعیین زمان دیالوگ و TTS.
6. برنامه‌ریزی دوربین و نور.
7. بررسی امکان‌پذیری تعامل.
8. رندر و ارزیابی خروجی.

### قرارداد JSON برای برنامه صحنه

```

{
  "schema_version": "1.0",
  "project": {
    "duration_seconds": 15,
    "fps": 30,
    "resolution": [1080, 1920],
    "aspect_ratio": "9:16"
  },
  "character": {
    "asset_id": "presenter_female_01",
    "rig_profile": "humanoid_v1"
  },
  "environment": {
    "asset_id": "perfume_store_01"
  },
  "shots": [
    {
      "id": "shot_01",
      "start": 0,
      "end": 3,
      "camera_preset": "medium_shot",
      "actions": [
        {
          "motion_id": "idle_breathing",
          "start": 0,
          "end": 3
        }
      ]
    },
    {
      "id": "shot_02",
      "start": 3,
      "end": 7,
      "camera_preset": "product_interaction",
      "actions": [
        {
          "motion_id": "reach_forward",
          "start": 3,
          "end": 4.5
        },
        {
          "motion_id": "grasp_object",
          "start": 4.5,
          "end": 5,
          "target_id": "perfume_001"
        },
        {
          "motion_id": "hold_object",
          "start": 5,
          "end": 7,
          "target_id": "perfume_001"
        }
      ]
    }
  ]
}

```

این فقط قرارداد اولیه است؛ مقادیر زمان و شناسه حرکت‌ها تا زمانی که فایل‌های واقعی و نقاط تماس تعریف نشده‌اند، نمونه محسوب می‌شوند.

### اعتبارسنجی قبل از رندر

موتور باید پیش از اجرا بررسی کند:

- آیا تمام `motion_id`ها در دیتابیس وجود دارند؟
- آیا کاراکتر با اسکلت انیمیشن سازگار است؟
- آیا محصول در صحنه وجود دارد؟
- آیا ترتیب حرکت‌ها معتبر است؟
- آیا دست به محصول دسترسی دارد؟
- آیا شات‌ها از محدوده ویدئو خارج نمی‌شوند؟
- آیا دیالوگ با مدت شات هماهنگ است؟
- آیا برای هر حرکت تعاملی نقطه تماس تعریف شده است؟

اگر چیزی ناسازگار بود، برنامه باید اصلاح شود یا خطای قابل فهم بدهد؛ نباید به Blender اجازه دهیم یک صحنه نامعتبر را بدون هشدار رندر کند.

### مدل زبانی چقدر قدرتمند باید باشد؟

برای برنامه‌ریزی صحنه، یک مدل زبانی نسبتاً کم‌هزینه با خروجی JSON معتبر می‌تواند کافی باشد. مدل‌های سنگین تولید ویدئو در این بخش لازم نیستند. حتی می‌توانیم ابتدا یک planner مبتنی بر قوانین و قالب‌های ثابت بسازیم و بعد مدل زبانی را اضافه کنیم.

## ۱۱. ساخت خط لوله رندر

هر پروژه باید به‌صورت یک Job مستقل اجرا شود.

\#chatgpt-mermaid-\_r_2k6\_{font-family:-apple-system-body,ui-sans-serif,-apple-system,system-ui,"Segoe UI",Helvetica,"Apple Color Emoji",Arial,sans-serif,"Segoe UI Emoji","Segoe UI Symbol";font-size:16px;fill:rgb(237, 237, 237);}@keyframes edge-animation-frame{from{stroke-dashoffset:0;}}@keyframes dash{to{stroke-dashoffset:0;}}#chatgpt-mermaid-\_r_2k6\_ .edge-animation-slow{stroke-dasharray:9,5!important;stroke-dashoffset:900;animation:dash 50s linear infinite;stroke-linecap:round;}#chatgpt-mermaid-\_r_2k6\_ .edge-animation-fast{stroke-dasharray:9,5!important;stroke-dashoffset:900;animation:dash 20s linear infinite;stroke-linecap:round;}#chatgpt-mermaid-\_r_2k6\_ .error-icon{fill:rgb(48, 48, 48);}#chatgpt-mermaid-\_r_2k6\_ .error-text{fill:rgb(237, 237, 237);stroke:rgb(237, 237, 237);}#chatgpt-mermaid-\_r_2k6\_ .edge-thickness-normal{stroke-width:1px;}#chatgpt-mermaid-\_r_2k6\_ .edge-thickness-thick{stroke-width:3.5px;}#chatgpt-mermaid-\_r_2k6\_ .edge-pattern-solid{stroke-dasharray:0;}#chatgpt-mermaid-\_r_2k6\_ .edge-thickness-invisible{stroke-width:0;fill:none;}#chatgpt-mermaid-\_r_2k6\_ .edge-pattern-dashed{stroke-dasharray:3;}#chatgpt-mermaid-\_r_2k6\_ .edge-pattern-dotted{stroke-dasharray:2;}#chatgpt-mermaid-\_r_2k6\_ .marker{fill:rgb(175, 175, 175);stroke:rgb(175, 175, 175);}#chatgpt-mermaid-\_r_2k6\_ .marker.cross{stroke:rgb(175, 175, 175);}#chatgpt-mermaid-\_r_2k6\_ svg{font-family:-apple-system-body,ui-sans-serif,-apple-system,system-ui,"Segoe UI",Helvetica,"Apple Color Emoji",Arial,sans-serif,"Segoe UI Emoji","Segoe UI Symbol";font-size:16px;}#chatgpt-mermaid-\_r_2k6\_ p{margin:0;}#chatgpt-mermaid-\_r_2k6\_ .label{font-family:-apple-system-body,ui-sans-serif,-apple-system,system-ui,"Segoe UI",Helvetica,"Apple Color Emoji",Arial,sans-serif,"Segoe UI Emoji","Segoe UI Symbol";color:rgb(237, 237, 237);}#chatgpt-mermaid-\_r_2k6\_ .cluster-label text{fill:rgb(237, 237, 237);}#chatgpt-mermaid-\_r_2k6\_ .cluster-label span{color:rgb(237, 237, 237);}#chatgpt-mermaid-\_r_2k6\_ .cluster-label span p{background-color:transparent;}#chatgpt-mermaid-\_r_2k6\_ .label text,#chatgpt-mermaid-\_r_2k6\_ span{fill:rgb(237, 237, 237);color:rgb(237, 237, 237);}#chatgpt-mermaid-\_r_2k6\_ .node rect,#chatgpt-mermaid-\_r_2k6\_ .node circle,#chatgpt-mermaid-\_r_2k6\_ .node ellipse,#chatgpt-mermaid-\_r_2k6\_ .node polygon,#chatgpt-mermaid-\_r_2k6\_ .node path{fill:rgb(51, 24, 37);stroke:rgb(171, 79, 122);stroke-width:1px;}#chatgpt-mermaid-\_r_2k6\_ .rough-node .label text,#chatgpt-mermaid-\_r_2k6\_ .node .label text,#chatgpt-mermaid-\_r_2k6\_ .image-shape .label,#chatgpt-mermaid-\_r_2k6\_ .icon-shape .label{text-anchor:middle;}#chatgpt-mermaid-\_r_2k6\_ .node .katex path{fill:#000;stroke:#000;stroke-width:1px;}#chatgpt-mermaid-\_r_2k6\_ .rough-node .label,#chatgpt-mermaid-\_r_2k6\_ .node .label,#chatgpt-mermaid-\_r_2k6\_ .image-shape .label,#chatgpt-mermaid-\_r_2k6\_ .icon-shape .label{text-align:center;}#chatgpt-mermaid-\_r_2k6\_ .node.clickable{cursor:pointer;}#chatgpt-mermaid-\_r_2k6\_ .root .anchor path{fill:rgb(175, 175, 175)!important;stroke-width:0;stroke:rgb(175, 175, 175);}#chatgpt-mermaid-\_r_2k6\_ .arrowheadPath{fill:rgb(175, 175, 175);}#chatgpt-mermaid-\_r_2k6\_ .edgePath .path{stroke:rgb(175, 175, 175);stroke-width:1px;}#chatgpt-mermaid-\_r_2k6\_ .flowchart-link{stroke:rgb(175, 175, 175);fill:none;}#chatgpt-mermaid-\_r_2k6\_ .edgeLabel{background-color:rgb(0, 0, 0);text-align:center;}#chatgpt-mermaid-\_r_2k6\_ .edgeLabel p{background-color:rgb(0, 0, 0);}#chatgpt-mermaid-\_r_2k6\_ .edgeLabel rect{opacity:0.5;background-color:rgb(0, 0, 0);fill:rgb(0, 0, 0);}#chatgpt-mermaid-\_r_2k6\_ .labelBkg{background-color:rgba(0, 0, 0, 0.5);}#chatgpt-mermaid-\_r_2k6\_ .cluster rect{fill:rgb(48, 48, 48);stroke:rgba(255, 255, 255, 0.15);stroke-width:1px;}#chatgpt-mermaid-\_r_2k6\_ .cluster text{fill:rgb(237, 237, 237);}#chatgpt-mermaid-\_r_2k6\_ .cluster span{color:rgb(237, 237, 237);}#chatgpt-mermaid-\_r_2k6\_ div.mermaidTooltip{position:absolute;text-align:center;max-width:200px;padding:2px;font-family:-apple-system-body,ui-sans-serif,-apple-system,system-ui,"Segoe UI",Helvetica,"Apple Color Emoji",Arial,sans-serif,"Segoe UI Emoji","Segoe UI Symbol";font-size:12px;background:rgb(48, 48, 48);border:1px solid rgba(255, 255, 255, 0.15);border-radius:2px;pointer-events:none;z-index:100;}#chatgpt-mermaid-\_r_2k6\_ .flowchartTitleText{text-anchor:middle;font-size:18px;fill:rgb(237, 237, 237);}#chatgpt-mermaid-\_r_2k6\_ rect.text{fill:none;stroke-width:0;}#chatgpt-mermaid-\_r_2k6\_ .icon-shape,#chatgpt-mermaid-\_r_2k6\_ .image-shape{background-color:rgb(0, 0, 0);text-align:center;}#chatgpt-mermaid-\_r_2k6\_ .icon-shape p,#chatgpt-mermaid-\_r_2k6\_ .image-shape p{background-color:rgb(0, 0, 0);padding:2px;}#chatgpt-mermaid-\_r_2k6\_ .icon-shape .label rect,#chatgpt-mermaid-\_r_2k6\_ .image-shape .label rect{opacity:0.5;background-color:rgb(0, 0, 0);fill:rgb(0, 0, 0);}#chatgpt-mermaid-\_r_2k6\_ .label-icon{display:inline-block;height:1em;overflow:visible;vertical-align:-0.125em;}#chatgpt-mermaid-\_r_2k6\_ .node .label-icon path{fill:currentColor;stroke:revert;stroke-width:revert;}#chatgpt-mermaid-\_r_2k6\_ .node .neo-node{stroke:rgb(171, 79, 122);}#chatgpt-mermaid-\_r_2k6\_ [data-look="neo"].node rect,#chatgpt-mermaid-\_r_2k6\_ [data-look="neo"].cluster rect,#chatgpt-mermaid-\_r_2k6\_ [data-look="neo"].node polygon{stroke:url(#chatgpt-mermaid-\_r_2k6\_-gradient);filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-\_r_2k6\_ [data-look="neo"].swimlane.cluster rect{filter:none;}#chatgpt-mermaid-\_r_2k6\_ [data-look="neo"].node path{stroke:url(#chatgpt-mermaid-\_r_2k6\_-gradient);stroke-width:1px;}#chatgpt-mermaid-\_r_2k6\_ [data-look="neo"].node .outer-path{filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-\_r_2k6\_ [data-look="neo"].node .neo-line path{stroke:rgb(171, 79, 122);filter:none;}#chatgpt-mermaid-\_r_2k6\_ [data-look="neo"].node circle{stroke:url(#chatgpt-mermaid-\_r_2k6\_-gradient);filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-\_r_2k6\_ [data-look="neo"].node circle .state-start{fill:#000000;}#chatgpt-mermaid-\_r_2k6\_ [data-look="neo"].icon-shape .icon{fill:url(#chatgpt-mermaid-\_r_2k6\_-gradient);filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-\_r_2k6\_ [data-look="neo"].icon-shape .icon-neo path{stroke:url(#chatgpt-mermaid-\_r_2k6\_-gradient);filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-\_r_2k6\_ .node text{font-size:14px;font-weight:600;letter-spacing:normal;fill:rgb(255, 186, 218);}#chatgpt-mermaid-\_r_2k6\_ .edgeLabels text{font-size:13px;font-weight:600;letter-spacing:-0.08px;fill:rgb(255, 186, 218);}#chatgpt-mermaid-\_r_2k6\_ .node tspan[font-weight="normal"],#chatgpt-mermaid-\_r_2k6\_ .edgeLabels tspan[font-weight="normal"]{font-weight:600;}#chatgpt-mermaid-\_r_2k6\_ .edgeLabel .label rect{opacity:1;rx:13px;ry:13px;fill:rgb(41, 16, 28);stroke:rgb(95, 53, 72);stroke-width:1px;}#chatgpt-mermaid-\_r_2k6\_ .node rect,#chatgpt-mermaid-\_r_2k6\_ .node circle,#chatgpt-mermaid-\_r_2k6\_ .node ellipse,#chatgpt-mermaid-\_r_2k6\_ .node polygon,#chatgpt-mermaid-\_r_2k6\_ .node path{fill:rgb(77, 31, 52);stroke:rgba(255, 255, 255, 0.1);stroke-width:1px;}#chatgpt-mermaid-\_r_2k6\_ .node rect{rx:16px;ry:16px;}#chatgpt-mermaid-\_r_2k6\_ .node.mermaid-decision .label-container{fill:rgb(41, 16, 28);stroke:rgb(95, 53, 72);stroke-dasharray:2,2;}#chatgpt-mermaid-\_r_2k6\_ .edgePaths .flowchart-link{stroke:rgb(175, 175, 175);stroke-width:1px;stroke-linecap:round;stroke-linejoin:round;}#chatgpt-mermaid-\_r_2k6\_ .marker{fill:rgb(175, 175, 175);stroke:rgb(175, 175, 175);}#chatgpt-mermaid-\_r_2k6\_ :root{--mermaid-font-family:-apple-system-body,ui-sans-serif,-apple-system,system-ui,"Segoe UI",Helvetica,"Apple Color Emoji",Arial,sans-serif,"Segoe UI Emoji","Segoe UI Symbol";}دریافت درخواستاعتبارسنجیتولید Scene Planساخت صحنه Blenderاجرای انیمیشنرندر Previewکنترل کیفیترندر نهاییمیکس صدا و FFmpegکنترل فایل خروجیذخیره و تحویلتأییداصلاح

### مراحل اجرایی رندر

مرحله A — Preview

- رزولوشن پایین‌تر.
- تنظیمات سبک‌تر.
- تعداد فریم محدود برای بررسی.
- بررسی حرکت، تماس و کادربندی.

مرحله B — Final Render

- رزولوشن نهایی.
- نورپردازی و مواد نهایی.
- تنظیمات رندر و Denoising مناسب.
- خروجی فریم‌ها یا توالی تصویری.

مرحله C — Final Assembly

- ترکیب فریم‌ها.
- افزودن گفتار و موسیقی.
- زیرنویس، لوگو و CTA.
- تبدیل به MP4.
- کنترل مدت، رزولوشن، FPS و صدای خروجی.

Blender قابلیت اجرای رندر از طریق خط فرمان و API پایتون را دارد؛ به همین دلیل می‌توان آن را به یک Worker خودکار تبدیل کرد.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://developer.blender.org\&sz=32)

Blender Developer Documentation

+1



### رندر را چطور ارزان نگه داریم؟

- کاراکتر، محیط و نور را بین پروژه‌ها دوباره استفاده کنیم.
- از قالب‌های ثابت و دارایی‌های از پیش آماده استفاده کنیم.
- پیش‌نمایش را قبل از رندر کامل اجباری کنیم.
- برای نماهای ساده از تنظیمات سبک‌تر استفاده کنیم.
- تنها شات‌هایی را که تغییر کرده‌اند دوباره رندر کنیم.
- صف کارها را محدود کنیم تا چند رندر هم‌زمان حافظه GPU را پر نکنند.

اما یک تفاوت مهم: مدل‌های ویدئویی سنگین حذف می‌شوند، نه هزینه محاسباتی. رندر سه‌بعدی نیز هزینه دارد. مزیت ما این است که هزینه آن قابل اندازه‌گیری، کنترل و بهینه‌سازی است و دارایی‌ها و حرکت‌ها را می‌توانیم بارها استفاده کنیم.

## ۱۲. اتصال به UpMarket: بک‌اند، صف و مدیریت پروژه‌ها

برای محصول واقعی، موتور رندر نباید داخل درخواست HTTP اجرا شود. کاربر درخواست می‌دهد، پروژه ثبت می‌شود، Worker آن را اجرا می‌کند و رابط کاربری وضعیت را نمایش می‌دهد.

\#chatgpt-mermaid-\_r_2kn\_{font-family:-apple-system-body,ui-sans-serif,-apple-system,system-ui,"Segoe UI",Helvetica,"Apple Color Emoji",Arial,sans-serif,"Segoe UI Emoji","Segoe UI Symbol";font-size:16px;fill:rgb(237, 237, 237);}@keyframes edge-animation-frame{from{stroke-dashoffset:0;}}@keyframes dash{to{stroke-dashoffset:0;}}#chatgpt-mermaid-\_r_2kn\_ .edge-animation-slow{stroke-dasharray:9,5!important;stroke-dashoffset:900;animation:dash 50s linear infinite;stroke-linecap:round;}#chatgpt-mermaid-\_r_2kn\_ .edge-animation-fast{stroke-dasharray:9,5!important;stroke-dashoffset:900;animation:dash 20s linear infinite;stroke-linecap:round;}#chatgpt-mermaid-\_r_2kn\_ .error-icon{fill:rgb(48, 48, 48);}#chatgpt-mermaid-\_r_2kn\_ .error-text{fill:rgb(237, 237, 237);stroke:rgb(237, 237, 237);}#chatgpt-mermaid-\_r_2kn\_ .edge-thickness-normal{stroke-width:1px;}#chatgpt-mermaid-\_r_2kn\_ .edge-thickness-thick{stroke-width:3.5px;}#chatgpt-mermaid-\_r_2kn\_ .edge-pattern-solid{stroke-dasharray:0;}#chatgpt-mermaid-\_r_2kn\_ .edge-thickness-invisible{stroke-width:0;fill:none;}#chatgpt-mermaid-\_r_2kn\_ .edge-pattern-dashed{stroke-dasharray:3;}#chatgpt-mermaid-\_r_2kn\_ .edge-pattern-dotted{stroke-dasharray:2;}#chatgpt-mermaid-\_r_2kn\_ .marker{fill:rgb(175, 175, 175);stroke:rgb(175, 175, 175);}#chatgpt-mermaid-\_r_2kn\_ .marker.cross{stroke:rgb(175, 175, 175);}#chatgpt-mermaid-\_r_2kn\_ svg{font-family:-apple-system-body,ui-sans-serif,-apple-system,system-ui,"Segoe UI",Helvetica,"Apple Color Emoji",Arial,sans-serif,"Segoe UI Emoji","Segoe UI Symbol";font-size:16px;}#chatgpt-mermaid-\_r_2kn\_ p{margin:0;}#chatgpt-mermaid-\_r_2kn\_ .label{font-family:-apple-system-body,ui-sans-serif,-apple-system,system-ui,"Segoe UI",Helvetica,"Apple Color Emoji",Arial,sans-serif,"Segoe UI Emoji","Segoe UI Symbol";color:rgb(237, 237, 237);}#chatgpt-mermaid-\_r_2kn\_ .cluster-label text{fill:rgb(237, 237, 237);}#chatgpt-mermaid-\_r_2kn\_ .cluster-label span{color:rgb(237, 237, 237);}#chatgpt-mermaid-\_r_2kn\_ .cluster-label span p{background-color:transparent;}#chatgpt-mermaid-\_r_2kn\_ .label text,#chatgpt-mermaid-\_r_2kn\_ span{fill:rgb(237, 237, 237);color:rgb(237, 237, 237);}#chatgpt-mermaid-\_r_2kn\_ .node rect,#chatgpt-mermaid-\_r_2kn\_ .node circle,#chatgpt-mermaid-\_r_2kn\_ .node ellipse,#chatgpt-mermaid-\_r_2kn\_ .node polygon,#chatgpt-mermaid-\_r_2kn\_ .node path{fill:rgb(51, 24, 37);stroke:rgb(171, 79, 122);stroke-width:1px;}#chatgpt-mermaid-\_r_2kn\_ .rough-node .label text,#chatgpt-mermaid-\_r_2kn\_ .node .label text,#chatgpt-mermaid-\_r_2kn\_ .image-shape .label,#chatgpt-mermaid-\_r_2kn\_ .icon-shape .label{text-anchor:middle;}#chatgpt-mermaid-\_r_2kn\_ .node .katex path{fill:#000;stroke:#000;stroke-width:1px;}#chatgpt-mermaid-\_r_2kn\_ .rough-node .label,#chatgpt-mermaid-\_r_2kn\_ .node .label,#chatgpt-mermaid-\_r_2kn\_ .image-shape .label,#chatgpt-mermaid-\_r_2kn\_ .icon-shape .label{text-align:center;}#chatgpt-mermaid-\_r_2kn\_ .node.clickable{cursor:pointer;}#chatgpt-mermaid-\_r_2kn\_ .root .anchor path{fill:rgb(175, 175, 175)!important;stroke-width:0;stroke:rgb(175, 175, 175);}#chatgpt-mermaid-\_r_2kn\_ .arrowheadPath{fill:rgb(175, 175, 175);}#chatgpt-mermaid-\_r_2kn\_ .edgePath .path{stroke:rgb(175, 175, 175);stroke-width:1px;}#chatgpt-mermaid-\_r_2kn\_ .flowchart-link{stroke:rgb(175, 175, 175);fill:none;}#chatgpt-mermaid-\_r_2kn\_ .edgeLabel{background-color:rgb(0, 0, 0);text-align:center;}#chatgpt-mermaid-\_r_2kn\_ .edgeLabel p{background-color:rgb(0, 0, 0);}#chatgpt-mermaid-\_r_2kn\_ .edgeLabel rect{opacity:0.5;background-color:rgb(0, 0, 0);fill:rgb(0, 0, 0);}#chatgpt-mermaid-\_r_2kn\_ .labelBkg{background-color:rgba(0, 0, 0, 0.5);}#chatgpt-mermaid-\_r_2kn\_ .cluster rect{fill:rgb(48, 48, 48);stroke:rgba(255, 255, 255, 0.15);stroke-width:1px;}#chatgpt-mermaid-\_r_2kn\_ .cluster text{fill:rgb(237, 237, 237);}#chatgpt-mermaid-\_r_2kn\_ .cluster span{color:rgb(237, 237, 237);}#chatgpt-mermaid-\_r_2kn\_ div.mermaidTooltip{position:absolute;text-align:center;max-width:200px;padding:2px;font-family:-apple-system-body,ui-sans-serif,-apple-system,system-ui,"Segoe UI",Helvetica,"Apple Color Emoji",Arial,sans-serif,"Segoe UI Emoji","Segoe UI Symbol";font-size:12px;background:rgb(48, 48, 48);border:1px solid rgba(255, 255, 255, 0.15);border-radius:2px;pointer-events:none;z-index:100;}#chatgpt-mermaid-\_r_2kn\_ .flowchartTitleText{text-anchor:middle;font-size:18px;fill:rgb(237, 237, 237);}#chatgpt-mermaid-\_r_2kn\_ rect.text{fill:none;stroke-width:0;}#chatgpt-mermaid-\_r_2kn\_ .icon-shape,#chatgpt-mermaid-\_r_2kn\_ .image-shape{background-color:rgb(0, 0, 0);text-align:center;}#chatgpt-mermaid-\_r_2kn\_ .icon-shape p,#chatgpt-mermaid-\_r_2kn\_ .image-shape p{background-color:rgb(0, 0, 0);padding:2px;}#chatgpt-mermaid-\_r_2kn\_ .icon-shape .label rect,#chatgpt-mermaid-\_r_2kn\_ .image-shape .label rect{opacity:0.5;background-color:rgb(0, 0, 0);fill:rgb(0, 0, 0);}#chatgpt-mermaid-\_r_2kn\_ .label-icon{display:inline-block;height:1em;overflow:visible;vertical-align:-0.125em;}#chatgpt-mermaid-\_r_2kn\_ .node .label-icon path{fill:currentColor;stroke:revert;stroke-width:revert;}#chatgpt-mermaid-\_r_2kn\_ .node .neo-node{stroke:rgb(171, 79, 122);}#chatgpt-mermaid-\_r_2kn\_ [data-look="neo"].node rect,#chatgpt-mermaid-\_r_2kn\_ [data-look="neo"].cluster rect,#chatgpt-mermaid-\_r_2kn\_ [data-look="neo"].node polygon{stroke:url(#chatgpt-mermaid-\_r_2kn\_-gradient);filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-\_r_2kn\_ [data-look="neo"].swimlane.cluster rect{filter:none;}#chatgpt-mermaid-\_r_2kn\_ [data-look="neo"].node path{stroke:url(#chatgpt-mermaid-\_r_2kn\_-gradient);stroke-width:1px;}#chatgpt-mermaid-\_r_2kn\_ [data-look="neo"].node .outer-path{filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-\_r_2kn\_ [data-look="neo"].node .neo-line path{stroke:rgb(171, 79, 122);filter:none;}#chatgpt-mermaid-\_r_2kn\_ [data-look="neo"].node circle{stroke:url(#chatgpt-mermaid-\_r_2kn\_-gradient);filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-\_r_2kn\_ [data-look="neo"].node circle .state-start{fill:#000000;}#chatgpt-mermaid-\_r_2kn\_ [data-look="neo"].icon-shape .icon{fill:url(#chatgpt-mermaid-\_r_2kn\_-gradient);filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-\_r_2kn\_ [data-look="neo"].icon-shape .icon-neo path{stroke:url(#chatgpt-mermaid-\_r_2kn\_-gradient);filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-\_r_2kn\_ .node text{font-size:14px;font-weight:600;letter-spacing:normal;fill:rgb(255, 186, 218);}#chatgpt-mermaid-\_r_2kn\_ .edgeLabels text{font-size:13px;font-weight:600;letter-spacing:-0.08px;fill:rgb(255, 186, 218);}#chatgpt-mermaid-\_r_2kn\_ .node tspan[font-weight="normal"],#chatgpt-mermaid-\_r_2kn\_ .edgeLabels tspan[font-weight="normal"]{font-weight:600;}#chatgpt-mermaid-\_r_2kn\_ .edgeLabel .label rect{opacity:1;rx:13px;ry:13px;fill:rgb(41, 16, 28);stroke:rgb(95, 53, 72);stroke-width:1px;}#chatgpt-mermaid-\_r_2kn\_ .node rect,#chatgpt-mermaid-\_r_2kn\_ .node circle,#chatgpt-mermaid-\_r_2kn\_ .node ellipse,#chatgpt-mermaid-\_r_2kn\_ .node polygon,#chatgpt-mermaid-\_r_2kn\_ .node path{fill:rgb(77, 31, 52);stroke:rgba(255, 255, 255, 0.1);stroke-width:1px;}#chatgpt-mermaid-\_r_2kn\_ .node rect{rx:16px;ry:16px;}#chatgpt-mermaid-\_r_2kn\_ .node.mermaid-decision .label-container{fill:rgb(41, 16, 28);stroke:rgb(95, 53, 72);stroke-dasharray:2,2;}#chatgpt-mermaid-\_r_2kn\_ .edgePaths .flowchart-link{stroke:rgb(175, 175, 175);stroke-width:1px;stroke-linecap:round;stroke-linejoin:round;}#chatgpt-mermaid-\_r_2kn\_ .marker{fill:rgb(175, 175, 175);stroke:rgb(175, 175, 175);}#chatgpt-mermaid-\_r_2kn\_ :root{--mermaid-font-family:-apple-system-body,ui-sans-serif,-apple-system,system-ui,"Segoe UI",Helvetica,"Apple Color Emoji",Arial,sans-serif,"Segoe UI Emoji","Segoe UI Symbol";}UpMarket FrontendDjango REST APIPostgreSQLRedis QueueCelery WorkerAI PlannerBlender RendererFFmpegObject Storage

### APIهای نسخه اول

| Endpoint                                 | کاربرد                      |
| ---------------------------------------- | --------------------------- |
| `POST /api/video-projects/`              | ایجاد پروژه و ارسال درخواست |
| `GET /api/video-projects/{id}/`          | وضعیت پروژه و خطاها         |
| `POST /api/video-projects/{id}/preview/` | ساخت پیش‌نمایش              |
| `POST /api/video-projects/{id}/render/`  | شروع رندر نهایی             |
| `GET /api/video-projects/{id}/result/`   | دریافت لینک خروجی           |
| `GET /api/assets/`                       | فهرست دارایی‌های مجاز       |

وضعیت پروژه‌ها:

```
PENDING
  ↓
PLANNING
  ↓
SCENE_BUILDING
  ↓
PREVIEW_RENDERING
  ↓
QUALITY_CHECK
  ↓
FINAL_RENDERING
  ↓
ASSEMBLING
  ↓
COMPLETED
```

در صورت خطا، وضعیت `FAILED` با پیام قابل فهم و امکان اجرای مجدد ثبت می‌شود.

### نکته مهم برای سرور

برای نمونه اولیه می‌توانیم Blender را مستقیماً با `subprocess` از Python اجرا کنیم. در محیط عملیاتی، هر Job باید محدودیت زمانی، حافظه، مسیر فایل و امکان لغو داشته باشد. همچنین باید از اجرای هم‌زمان نامحدود رندرها جلوگیری کنیم.

## ۱۳. کیفیت نهایی را چگونه به سطح فیلم واقعی نزدیک کنیم؟

اینجا باید با معیارهای فنی پیش برویم، نه فقط اینکه یک فریم زیبا به نظر برسد.

[Austria Tourism Imagines Travel as Brain-Building in ‘The Austrian Synapse’ | LBBOnline](https://images.openai.com/static-rsc-4/rR_8Zjg94ylHhIdajflsYX4pLzJ5TCUf6flB6jok7f5IAIyaavi3QmxcZN21G2F9fm7CQxAJBwGeCz5m1sG39aNmUh8BmJCGxxOU_y2c7CTZSqJs6lr2jswPTWbK6d_18Nilp380inurtKfJELNUysoB-UCnaipPvFFSgVBtMjE?purpose=inline)

کیفیت ظاهری انسان

پوست، چشم، دندان، مو، لباس، سایه و جزئیات صورت باید در نمای نزدیک هم قابل قبول باشند.

[Intelligenz-Studie: Wer schneller geht, ist klüger – und altert langsamer | GALA.de](https://images.openai.com/static-rsc-4/BLB8kT34Xgr50x2gl3jmj7GU_gOKYNJLZgCCc2Pk3dNRaKDnq7pazQwZCWWkSIthSLwIhGu3uJ-alxfhlumAWDmEQ5FPcdf-vKE722aue8sPTzRpDl9k96CLmKKArCSyc_UJLmwE5ZL8C-ZRNDFwm419wr6mE9NrXRBko-CyNhQ?purpose=inline)

کیفیت حرکت

بدون لغزش پا، پرش ناگهانی بدن، تغییر غیرطبیعی سرعت، لرزش مفاصل یا انتقال وزن نامعتبر.

[Eternal Secret: fragancia floral que combina calidad y precio | Glamour](https://images.openai.com/static-rsc-4/RQfbyf4qPZBG7xRJLnUWpIwUbmFuCpZM81PCLGWspnxF5mQnx23SiD-fHoLezpEKojKdatxO6le-ZkgogS_bUc2gnIvhlBG1V0dkhbCY0jHa9yIgwRkl4vsF6o0vkAADJ43OGwVwx1J096G5cTY5H8f6G1qUvX1zdum-8h6n8bM?purpose=inline)

کیفیت تعامل

تماس صحیح انگشتان با محصول، حفظ محل گرفتن، سایه تماس و نبود نفوذ هندسی غیرطبیعی.

[AI Creative Sprints: Faster Ad Production - Hailuo AI](https://images.openai.com/static-rsc-4/POOIjQUnQKBiOxHHTogcsyUIpvCDaxxFnhwF6N_jqf9TbfIeDUaaRKK7b6iFEjIZ_YLcgv284r4gIiXh41EAVG3dtOo3kfsW2DwWnvA9KWN69A2w6Lz1gHNuY2GpljQOlW4RNPRSk1h01FunA8S-eZz25YzurliMfu_qceAy_Ek?purpose=inline)

کیفیت تصویری و کارگردانی

نور، لنز، حرکت دوربین، ترکیب‌بندی، عمق میدان و پیوستگی بصری بین شات‌ها.

### تست‌هایی که باید خودکار شوند

- بررسی برخورد پا با زمین.
- بررسی فاصله دست از نقطه گرفتن محصول.
- بررسی نفوذ انگشتان و محصول در محدوده‌های قابل کنترل.
- بررسی پرش وضعیت اسکلت هنگام اتصال دو حرکت.
- بررسی برش‌های ناخواسته در ابتدا و انتهای شات.
- بررسی هم‌زمانی گفتار و حرکت لب.
- بررسی فریم‌های سیاه، فایل ناقص و خطاهای رندر.

بخشی از این موارد را می‌توان با کد اندازه‌گیری کرد؛ اما طبیعی بودن چهره، احساسات و کیفیت تبلیغ همچنان نیاز به بازبینی انسانی و تست با بیننده دارد.

### یک اصل مهم درباره واقع‌گرایی

برای نزدیک شدن به ویدئوی واقعی، از ابتدا لازم نیست هر صحنه کاملاً تعاملی و فیزیکی باشد. بسیاری از تبلیغات حرفه‌ای از برش‌های دوربین، نماهای نزدیک محصول و ترکیب شات‌های متفاوت استفاده می‌کنند.

بنابراین می‌توانیم از این روش بهره ببریم:

- شات تمام‌قد برای معرفی انسان.
- شات متوسط برای حرکت و دیالوگ.
- شات نزدیک برای نمایش محصول.
- شات تعاملی فقط جایی که واقعاً لازم است.

این کار هم کیفیت ادراکی را بالا می‌برد و هم تعداد تعامل‌های دشوار را کاهش می‌دهد.

## ۱۴. برنامه پیاده‌سازی از صفر تا MVP

پیشنهاد من این است که پروژه را به شش مرحله تقسیم کنیم. هیچ مرحله‌ای را تا زمانی که تست قابل قبول ندارد، به مرحله بعد متصل نکنیم.

مرحله ۱ — اولین رندر قابل اجرا

اولویت اول

Blender، یک کاراکتر، یک محیط، دوربین، نور و خروجی MP4. ابتدا یک صحنه ثابت و سپس یک حرکت کوتاه را رندر می‌کنیم.

خروجی قابل قبول: یک ویدئوی مستقل که با اسکریپت ساخته شده و بدون کار دستی در محیط Blender خروجی می‌دهد.

مرحله ۲ — کتابخانه حرکات

یک پروفایل اسکلت، ۲۰ تا ۵۰ حرکت انتخاب‌شده، Metadata، Retargeting و اتصال چند حرکت.

خروجی قابل قبول: کاراکتر بدون پرش محسوس بین ایستادن، حرکت، توقف و ژست‌های دست جابه‌جا شود.

مرحله ۳ — تعامل با محصول

مدل سه‌بعدی یک محصول، نقطه گرفتن، IK، اتصال به دست و رها کردن کنترل‌شده.

خروجی قابل قبول: کاراکتر محصول را بردارد، نگه دارد و روی میز بگذارد، بدون لغزش آشکار و نفوذ غیرطبیعی.

مرحله ۴ — صدا و صورت

TTS، ریگ صورت، Lip Sync، پلک زدن و حرکت‌های طبیعی سر.

خروجی قابل قبول: یک دیالوگ فارسی کوتاه با هماهنگی قابل قبول لب، صورت و صدا.

مرحله ۵ — کارگردان هوش مصنوعی

تبدیل متن به JSON، انتخاب صحنه و حرکت، برنامه دوربین و اعتبارسنجی.

خروجی قابل قبول: درخواست متنی به یک برنامه اجرایی معتبر تبدیل شود و بتوان آن را بدون تغییر دستی کد اجرا کرد.

مرحله ۶ — اتصال به UpMarket

API، صف کارها، مدیریت وضعیت، ذخیره فایل، پیش‌نمایش، رندر نهایی و تحویل ویدئو.

خروجی قابل قبول: کاربر از طریق رابط UpMarket درخواست بدهد و ویدئو را دریافت کند، بدون اینکه مستقیماً با Blender کار کند.

زمان هر مرحله به کیفیت کاراکتر انتخابی، وضعیت سیستم، کیفیت دارایی‌های حرکتی و میزان توسعه سفارشی وابسته است؛ قبل از بررسی این موارد، تخمین زمانی دقیق قابل اعتماد نیست.

## ۱۵. تعریف دقیق MVP تجاری

نسخه اول را این‌طور محدود می‌کنم:

| قابلیت     | نسخه اول                              |
| ---------- | ------------------------------------- |
| مدت تبلیغ  | ۱۰ تا ۱۵ ثانیه                        |
| نسبت تصویر | عمودی ۹:۱۶                            |
| کاراکتر    | یک انسان واقع‌گرایانه                 |
| محیط       | یک فروشگاه یا استودیوی آماده          |
| حرکت       | ۲۰ تا ۵۰ حرکت تأییدشده                |
| تعامل      | گرفتن، نگه داشتن و نشان دادن یک محصول |
| صدا        | یک صدای فارسی                         |
| دوربین     | ۳ تا ۵ الگوی کنترل‌شده                |
| محصول      | مدل سه‌بعدی آماده یا دارایی مناسب     |
| خروجی      | MP4 با رزولوشن هدف 1080×1920          |
| تولید      | ابتدا پیش‌نمایش، سپس رندر نهایی       |

### معیار پذیرش

نسخه اول زمانی آماده آزمایش تجاری است که بتواند یک تبلیغ کامل را با متن کاربر بسازد، صحنه و حرکت‌ها را انتخاب کند، محصول را درست نمایش دهد، صدای هماهنگ داشته باشد و خروجی نهایی را بدون دخالت دستی در تایم‌لاین تولید کند.

برای ادعای «کیفیت شبیه فیلم واقعی»، علاوه بر این معیارهای عملکردی، باید ارزیابی جداگانه‌ای با نمونه‌های کور و مقایسه با تبلیغات فیلم‌برداری‌شده انجام دهیم.

## ۱۶. از همین امروز دقیقاً چه کار کنیم؟

من پیشنهاد نمی‌کنم از Django، Redis، TTS و AI Planner به‌صورت هم‌زمان شروع کنیم. اگر از همان ابتدا همه اجزا را بسازیم، ممکن است چند هفته صرف اتصال ابزارها کنیم، بدون اینکه حتی یک انسان طبیعی در حال برداشتن محصول داشته باشیم.

اول یک نمونه مستقل بسازیم.

## چک‌لیست شروع پروژه

0 از 6

نصب و آزمایش Blender

اجرای یک صحنه ساده از طریق Python و خروجی گرفتن MP4.

انتخاب یک کاراکتر واقعی‌نما

بررسی ریگ بدن، صورت، مو، لباس و مجوز استفاده تجاری.

انتخاب یک محصول سه‌بعدی

یک بطری یا جعبه با ابعاد و نقطه گرفتن مشخص.

ساخت اولین صحنه تبلیغاتی

کاراکتر کنار میز، محصول، دوربین و نور مناسب.

اجرای سه حرکت متوالی

ایستادن، دست دراز کردن و گرفتن محصول.

رندر و ارزیابی

بررسی تماس دست، حرکت بدن، کیفیت تصویر و زمان رندر.

کپی چک‌لیست

وقتی اولین صحنه را داریم، تصمیم‌های بعدی را بر اساس خروجی واقعی می‌گیریم، نه حدس.

## جمع‌بندی معماری

این پروژه از نظر فنی شدنی است، اما باید تفاوت بین «یک ویدئوی سه‌بعدی زیبا» و «یک تبلیغ انسان‌محور که بیننده آن را فیلم واقعی تصور کند» را جدی بگیریم.

مزیت اصلی ایده تو این است که حرکت‌ها، محیط‌ها، مدل‌ها و تنظیمات دوربین یک‌بار ساخته می‌شوند و بعد در پروژه‌های متعدد قابل استفاده‌اند. هوش مصنوعی نقش برنامه‌ریز و کارگردان را دارد؛ موتور سه‌بعدی وظیفه اجرای دقیق صحنه را انجام می‌دهد.

اولین هدف ما نباید ساخت یک پلتفرم عمومی عظیم باشد؛ باید یک تبلیغ ۱۵ ثانیه‌ای بسازیم که انسان آن محصول را واقعاً طبیعی بردارد و معرفی کند. اگر آن خروجی از نظر بصری قابل قبول باشد، می‌توانیم همین هسته را به موتور تولید تبلیغات، ارائه‌دهنده مجازی و بعد یک API عمومی توسعه دهیم.









مانی، به نظرم برای UpMarket باید این پروژه را به‌عنوان یک موتور اختصاصی تولید ویدئوی تبلیغاتی با هوش مصنوعی بسازیم؛ نه اینکه صرفاً چند انیمیشن را کنار هم بگذاریم.

اصل ایده‌ات این است: به‌جای اینکه برای هر تبلیغ، هوش مصنوعی میلیون‌ها محاسبه سنگین برای تولید فریم‌های ویدئو انجام دهد، ما یک‌بار دارایی‌های سه‌بعدی، حرکت‌های انسانی و محیط‌ها را آماده می‌کنیم و بعد یک مدل زبانی ارزان، مثل کارگردان، آن‌ها را با هم ترکیب می‌کند.

پیشنهاد فنی قبلی‌مان هم بر همین مبنا بود: Blender + Python + کتابخانه حرکات انسانی + کارگردان هوش مصنوعی و در مراحل بعد، اتصال آن به Django و پنل UpMarket.&#x20;

Pasted text(5).txt



اما مهم‌ترین تصمیم ما الان این است که قبل از ساخت کل سیستم، ثابت کنیم می‌توانیم با آن یک ویدئوی واقع‌گرایانه و قابل‌قبول تولید کنیم.

## ۱. نقشه راه پیاده‌سازی

[Campa - Natural Juice :: Behance](https://images.openai.com/static-rsc-4/VlXtLj0ztE-eDZtrgNcfN7SMmJd1qzA8SsoMImIcJ-61yWtUkRrWchyonbSX-2_ZcuyblUQtMPbZg-aYtkOe_NvZ9yaiP74RcdhFOgOLVj7yofM_YH5narl1UWsjmwxOCcDMjfSxQc2dhg6qO9lg5ATtnapqVVs6h_anneuOqS4?purpose=inline)

### مرحله ۱ — ساخت اولین صحنه سه‌بعدی

اولویت فعلی

یک محیط ساده، نورپردازی، دوربین، میز و محصول بسازیم و با Python از Blender خروجی ویدئویی بگیریم.

هدف: یک MP4 واقعی که با اسکریپت تولید شده باشد.

[Hans Realistic Human  3D model animated rigged | CGTrader](https://images.openai.com/static-rsc-4/T75Fd56PP_iiI5gOkHlrfnGXm8eXTy8I1ST6WnPbkcTlJt27pjN7ZYURNrf4PolAcSxorQt-keNS1N0W_AdZqKt6vBlo92UfvDCUnoNoeBvehIO7GybiK4DTC-kEnrP2PWUzg3KpKew2DMwnz5s44VBoliormnYaN03QJrrqMTg?purpose=inline)

### مرحله ۲ — انسان واقع‌گرایانه و حرکت‌ها

یک کاراکتر آماده با اسکلت مناسب وارد کنیم؛ حرکت‌های ایستادن، نگاه کردن، دست دراز کردن و معرفی محصول را به آن بدهیم.

هدف: حرکت طبیعی، بدون پرش محسوس بین انیمیشن‌ها.

[She EDP Women 100ml  – BEAUTIKA](https://images.openai.com/static-rsc-4/HrQoPmy6fTatZ9Q5m2U9hLZ0drC6eKwnmByKgokY-hJxL4r3ZrlzlyP6y_XkfNooKDbLyIaX7SLY2vrwzrxU-0iPd9yzWetch9bNXWEulzuajuWwMlG2wHaOoxRLR447-N6g6iNZcbu0Bc8-Wbh7pWHmW9csPJZJYaFkv_PiIjA?purpose=inline)

### مرحله ۳ — تعامل با محصول

کاراکتر محصول را بردارد، نگه دارد و به دوربین نشان دهد. اینجا به IK، نقاط گرفتن و کنترل تماس دست و محصول نیاز داریم.

هدف: جلوگیری از لغزش محصول و عبور انگشت‌ها از بدنه.

[KI Schauspieler Generator für Werbung online](https://images.openai.com/static-rsc-4/UhZeWZOLiEe_fymQimDwZQirti173CQHftOqZHYUAOxwzRh1glO3n8dVM05_pkqKfe_I1zjX25pUy7kCJkXa_uzlA4XU1nIMZVzt4X3ubf93sMzvXm1lHuor4tRv6-vQUxgUOVef0BdJ7UWMJsCff7eB__ogd5_TE1mYLVvKvIE?purpose=inline)

### مرحله ۴ — صدا و کارگردان هوش مصنوعی

تولید دیالوگ، صدای فارسی، هماهنگی لب، انتخاب حرکت‌ها و تبدیل متن کاربر به برنامه اجرایی صحنه.

هدف: ساخت تبلیغ از روی یک درخواست متنی.

[Chanel No5 Perfume Bottle Luxury Fragrance Advertising](https://images.openai.com/static-rsc-4/r-jStrEdsaQI_HT-WPijIZ6KiGmE5ZlOP0oth0sZ2siDxnKtAmVDE1asjez1-ZrlhTMcRAbrPdVS-dVl7sTMTW5Oss8T_A4BuXnzGGgZQ_19OEs89aPZ4IN-qmdfKxr8rGb6z9H1_Vxc9ZvQlJcVrJsWYn_m5_7KrKQBaJt9VnM?purpose=inline)

### مرحله ۵ — اتصال به UpMarket

اتصال موتور به Django REST Framework، صف پردازش، ذخیره خروجی‌ها و رابط کاربری ساخت تبلیغ.

هدف: کاربر درخواست بدهد و بعد از اتمام پردازش، ویدئوی خود را دریافت کند.

این ترتیب مهم است: تا زمانی که مرحله قبل خروجی قابل‌قبولی ندارد، نباید پیچیدگی مرحله بعد را اضافه کنیم.

## ۲. از نظر فنی دقیقاً با چه ابزارهایی شروع کنیم؟

| بخش               | انتخاب نسخه اول           | چرا؟                                      |
| ----------------- | ------------------------- | ----------------------------------------- |
| موتور سه‌بعدی     | Blender                   | رایگان، قابل اسکریپت‌نویسی و مناسب رندر   |
| زبان برنامه‌نویسی | Python داخل Blender       | ساخت خودکار صحنه و کنترل انیمیشن          |
| کاراکتر           | مدل آماده ریگ‌شده         | حذف هزینه ساخت انسان از صفر               |
| انیمیشن           | Mixamo و فایل‌های FBX     | شروع با حرکت‌های آماده                    |
| محصول             | مدل سه‌بعدی GLB/FBX       | امکان قرار دادن محصول در صحنه             |
| هوش مصنوعی        | فعلاً بدون مدل؛ بعداً LLM | ابتدا منطق اجرای صحنه را اثبات کنیم       |
| ویدئو             | رندر Blender و سپس FFmpeg | خروجی MP4                                 |
| بک‌اند            | فعلاً هیچ‌کدام            | Django را پس از اثبات موتور اضافه می‌کنیم |

این انتخاب‌ها با معماری قبلی پروژه هم‌خوان‌اند.&#x20;

Pasted text(5).txt



## ۳. برنامه اجرایی ما برای شروع

با توجه به اینکه سیستم RTX 3060 با ۱۲ گیگابایت VRAM داری، می‌توانیم نمونه اولیه را روی کامپیوتر خودت بسازیم؛ البته زمان رندر باید عملاً اندازه‌گیری شود.

## چک‌لیست شروع

0 از 5

۱. نصب Blender

نسخه پایدار را نصب و اجرای اولیه را آزمایش کن.

۲. ساخت اولین صحنه

میز، محصول ساده، نور و دوربین؛ ابتدا بدون انسان.

۳. خروجی خودکار

یک اسکریپت Python صحنه را بسازد و MP4 تحویل دهد.

۴. وارد کردن کاراکتر

یک مدل ریگ‌شده را وارد و یک حرکت آماده را اجرا کن.

۵. تست تعامل

حرکت دست تا محصول و گرفتن آن را پیاده‌سازی کن.

برای شروع، Blender را از [وب‌سایت رسمی](https://www.blender.org/download/) نصب کن.

### ساختار اولیه پروژه

فعلاً یک پوشه مستقل بساز؛ هنوز آن را داخل بک‌اند UpMarket ادغام نکن.

```
upmarket-3d-engine/
├── scene_builder.py
├── render.py
├── assets/
│   ├── characters/
│   ├── motions/
│   ├── products/
│   └── environments/
├── scenes/
├── output/
└── README.md
```

این ساختار اولیه است؛ بعداً آن را به ماژول‌های جداگانه کارگردان هوش مصنوعی، کتابخانه حرکت و خط لوله رندر گسترش می‌دهیم.

## ۴. چطور کتابخانه حرکات را بسازیم؟

از همان اول دیتابیس پیچیده یا مدل هوش مصنوعی اختصاصی لازم نداریم. ابتدا فایل‌های انیمیشن را نگه می‌داریم و برای هرکدام Metadata تعریف می‌کنیم.

مثلاً:

```
{
  "id": "present_product_v1",
  "category": "advertising",
  "file": "present_product.fbx",
  "rig_profile": "humanoid_v1",
  "start_state": "standing_idle",
  "end_state": "product_held",
  "loopable": false,
  "commercial_use_verified": false
}
```

فیلد مجوز را عمداً `false` گذاشته‌ام؛ تا زمانی که مجوز همان فایل را بررسی نکرده‌ایم، نباید استفاده تجاری آن را فرض کنیم.

در ادامه، کتابخانه را با حدود ۲۰ تا ۵۰ حرکت باکیفیت شروع می‌کنیم، نه صدها حرکت نامرتبط. مهم‌تر از تعداد، سازگاری حرکت‌ها با یک اسکلت و قابلیت اتصال طبیعی آن‌هاست.&#x20;

Pasted text(5).txt



## ۵. اولین خروجی که باید بسازیم چیست؟

اولین خروجی ما نباید یک ویدئوی ۳۰ ثانیه‌ای با ده‌ها قابلیت باشد. یک آزمایش کوتاه و مشخص کافی است:

## نمونه اولیه شماره ۱

[Seedream 5.0 Review: ByteDance's New AI Image Generator — Hailuo AI](https://images.openai.com/static-rsc-4/NMuglGvY_SFtdAJOXAeNYUrIvvE0h7uQtiS9DuEFCaYBSqheQaTBpbyoy4kkHPgWu1v1HCGXqgPVoO9nRm5Y01fVRLxDq3YzIvCocM12voJ-yqm_GEPIJkOBMwTWnzJQo8EWuhWedCDWTwk3xIaQhE0gMs47jfXeLsYC8tGqaU4?purpose=inline)

[hailuoai.video](https://hailuoai.video/pages/blog/seedream-5-review-ai-image-generator)

1. یک انسان واقعی‌نما کنار میز ایستاده است.
2. دستش را به سمت یک بطری می‌برد.
3. بطری را برمی‌دارد و رو به دوربین می‌گیرد.
4. دوربین، نور و سایه‌ها ظاهر سینمایی دارند.
5. خروجی به شکل فایل MP4 ذخیره می‌شود.

این تصویر فقط مرجع ظاهری هدف است؛ کیفیت واقعی را باید با رندر موتور خودمان بسنجیم.

وقتی این صحنه را بدون دخالت دستی در تایم‌لاین تولید کردیم، می‌توانیم سراغ صدا، هماهنگی لب، برنامه‌ریزی هوشمند و اتصال به UpMarket برویم.

## ۶. یک نکته مهم درباره واقع‌گرایی و هزینه

این روش قرار نیست تمام هزینه‌ها را حذف کند. ما هزینه تولید فریم با مدل‌های ویدئویی را با هزینه ساخت و نگهداری دارایی‌های سه‌بعدی و رندر جایگزین می‌کنیم.

سه مسئله اصلی که باید آزمایش کنیم:

- واقع‌گرایی انسان: پوست، چشم، مو، لباس و حرکت صورت.
- تعامل واقعی با محصول: تماس انگشت‌ها، گرفتن و حرکت دادن شیء.
- هزینه رندر: زمان لازم برای تولید هر ثانیه ویدئو روی سخت‌افزار موجود.

اگر حرکت‌ها طبیعی باشند اما چهره شبیه بازی شود، یا رندر آن‌قدر طول بکشد که هزینه نهایی مزیت رقابتی نداشته باشد، باید قبل از توسعه محصول مسیر را اصلاح کنیم.

## حالا از کجا شروع کنیم؟

پیشنهاد من این است که همین حالا وارد مرحله اول و پیاده‌سازی عملی Blender شویم؛ نه اینکه فعلاً بیشتر درباره معماری صحبت کنیم.

فقط یک سؤال: Blender روی ویندوزت نصب است یا باید از نصب آن شروع کنیم؟

بر اساس جوابت، قدم اول را با دستورها و کد واقعی جلو می‌بریم تا به اولین فایل MP4 برسیم.












