import os
"""
تنظیماتِ مخصوصِ همین سرور (185.239.3.189) — روی gym/settings.py سوار می‌شود.

سرویسِ cheghar این فایل را با DJANGO_SETTINGS_MODULE=gym.settings_server بار
می‌کند (/etc/cheghar/cheghar.env). خودِ settings.py دست نخورده است.
"""
from .settings import *  # noqa: F401,F403

# ---- مسیر ----
# nginx روی پورتِ 8000 پروژه را زیرِ /chagher/ سرو می‌کند و پیشوند را پیش از
# رسیدن به gunicorn برمی‌دارد؛ جنگو باید بداند تا لینک‌ها و ریدایرکت‌های ادمین
# را با همان پیشوند بسازد.
# ⚠ nginx جنگو را روی **ریشهٔ دامنه** سرو می‌کند (location / → gunicorn)،
# پس پیشوند باید خالی باشد؛ وگرنه هر آدرسِ تولیدشده یک ری‌دایرکتِ اضافه
# می‌خورد و POSTها (مثلِ ورودِ یک‌باره) روی ۳۰۱ به GET تبدیل و خراب می‌شوند.
# لینک‌های قدیمیِ /chagher/... در nginx به ریشه هدایت می‌شوند.
FORCE_SCRIPT_NAME = os.environ.get('DJANGO_SCRIPT_NAME', '').strip() or None
STATIC_URL = '/static/'
MEDIA_URL = '/media/'

# ---- فعلاً HTTP ----
# هنوز دامنه و گواهی نداریم. با این‌ها روشن، هر درخواست به https:// می‌رفت که
# روی این سرور نیست، و کوکیِ ورودِ ادمین روی http ذخیره نمی‌شد.
# وقتی HTTPS راه افتاد این بلوک را پاک کن تا سخت‌سازیِ settings.py برگردد.
SECURE_SSL_REDIRECT = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
SECURE_HSTS_SECONDS = 0

# ---- SMS ----
# در حالت تست، کد تایید در پاسخ API برگردانده می‌شود.
# ⚠️ بعد از تست، در /etc/cheghar/cheghar.env مقدارش را 0 کن.
import os as _os
SMS_RETURN_CODE_IN_RESPONSE = _os.environ.get(
    'SMS_RETURN_CODE_IN_RESPONSE', '0'
).strip().lower() in ('1', 'true', 'yes', 'on')










