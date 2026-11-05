# فونت‌های فارسیِ ادیتور عکس

همه با مجوزِ **SIL Open Font License 1.1** (آزاد؛ استفادهٔ تجاری و جاسازی در برنامه و تصویر مجاز است؛ فقط خودِ فونت را جداگانه نمی‌شود فروخت). متنِ کاملِ مجوزها کنارِ هر فونت در همین پوشه است.

| کلید | نام | وزن‌ها | نقش | مجوز | منبع |
|---|---|---|---|---|---|
| `vazirmatn` | وزیرمتن | ۳۰۰ تا ۸۰۰ | متنِ اصلی (از قبل بود) | OFL 1.1 | سیستم / `services/imaging/fonts` |
| `estedad` | استعداد | ۳۰۰ تا ۸۰۰ | تیتر و متن، مدرن | OFL 1.1 (`Estedad-OFL.txt`) | github.com/aminabedi68/Estedad |
| `lalezar` | لاله‌زار | ۱ وزن | تیترِ درشت و پرجلوه | OFL 1.1 (`Lalezar-OFL.txt`) | github.com/google/fonts (ofl/lalezar) |
| `shabnam` | شبنم | ۳۰۰، ۴۰۰، ۵۰۰، ۷۰۰ | متنِ کوچکِ خوانا | OFL 1.1 (`Shabnam-LICENSE.txt`) | github.com/rastikerdar/shabnam-font |
| `sahel` | ساحل | ۳۰۰، ۴۰۰، ۶۰۰، ۷۰۰، ۸۰۰ (سیاه) | گرم و گرد | OFL 1.1 (`Sahel-LICENSE.txt`) | github.com/rastikerdar/sahel-font |
| `samim` | صمیم | ۴۰۰، ۵۰۰، ۷۰۰ | رسمی و آرام | OFL 1.1 (`Samim-LICENSE.txt`) | github.com/rastikerdar/samim-font |

* فایل‌های `*.ttf` همین‌جا برای سرور (Pillow + raqm) است؛ نسخهٔ سبکِ مرورگر (WOFF، زیرمجموعهٔ عربی/فارسی + لاتین، حدودِ ۳۵ تا ۸۰ کیلوبایت هر وزن) در `frontend/src/features/content/photo/fonts/` است و فقط وقتی لایه‌ای از آن فونت استفاده کند بارگیری می‌شود.
* پوشش: همهٔ حروفِ فارسی (پ چ ژ گ ک ی)، رقم‌های فارسی و لاتین، «٪ ٬ ، ؟»؛ نیم‌فاصلهٔ لاله‌زار در خودِ فونت نیست و (مثلِ همیشه) نادیده/بدونِ فاصله کشیده می‌شود.
* فونتِ تازه اضافه‌کردن: فایل را بگذارید، یک ردیف به `fontreg.py` (سرور) و یک `@font-face` به `pro/fonts.css` و یک نام به `FONT_FAMILIES` در `pro/gl/raster.ts` اضافه کنید.
