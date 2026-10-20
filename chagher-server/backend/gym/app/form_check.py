# -*- coding: utf-8 -*-
"""بررسیِ درستیِ حرکت از روی فریمِ دوربین (سیستمِ دومِ تشخیصِ تصویر).

ورزشکار در صفحهٔ آموزشِ حرکت دکمه را می‌زند، دوربین باز می‌شود و هر چند ثانیه یک
فریم به این‌جا می‌آید. فریم همراه با **متنِ آموزشِ همان حرکت** به مدلِ بینایی داده
می‌شود و مدل می‌گوید درست است یا نه و اگر نه، چه چیزی را اصلاح کند.

سه خروجی که روی صفحهٔ دوربین نشان داده می‌شود:
    ok     → کادرِ سبز  («درست می‌زنی»)
    bad    → کادرِ قرمز («اشتباه است»)
    unsure → کادری کشیده نمی‌شود (مدل بدن را ندید یا مطمئن نیست)
و در هر سه حالت، یک خطِ **زرد** راهنمایی روی تصویر می‌آید.

چرا کادر را از مدل می‌گیریم: اگر کادر دورِ خودِ ورزشکار باشد، معنی‌دار است. مدل
جعبهٔ تقریبیِ بدن را به نسبتِ ۰ تا ۱ می‌دهد و اگر نداد، کادرِ وسطِ تصویر کشیده
می‌شود. این یک تشخیصِ تصویری است، نه سنجشِ دقیقِ زاویهٔ مفاصل؛ حرفِ آخر را مربی
می‌زند و همین در پیامِ پایانی به ورزشکار گفته می‌شود.
"""
import base64
import io as _io
import json
import logging
import re

logger = logging.getLogger(__name__)

MAX_SIDE = 640          # فریمِ دوربین؛ بزرگ‌تر از این فقط توکن می‌سوزاند و کند می‌کند
JPEG_QUALITY = 80


def shrink(image_bytes):
    """فریم را کوچک و JPEG می‌کند. اگر Pillow نتوانست، همان اصل را می‌فرستد."""
    try:
        from PIL import Image
        img = Image.open(_io.BytesIO(image_bytes))
        img = img.convert('RGB')
        if max(img.size) > MAX_SIDE:
            ratio = MAX_SIDE / float(max(img.size))
            img = img.resize((max(1, int(img.width * ratio)), max(1, int(img.height * ratio))),
                             Image.LANCZOS)
        buf = _io.BytesIO()
        img.save(buf, 'JPEG', quality=JPEG_QUALITY, optimize=True)
        return buf.getvalue()
    except Exception:
        logger.warning('کوچک‌کردنِ فریم نشد؛ اصلِ فایل فرستاده می‌شود', exc_info=True)
        return image_bytes


def _steps_text(exercise):
    steps = exercise.steps_fa or []
    if isinstance(steps, list) and steps:
        return '\n'.join('%d) %s' % (i, s) for i, s in enumerate(steps, 1))
    return (exercise.instructions_fa or exercise.instructions_en or '').strip() or 'ندارد'


def _prompt(exercise):
    return (
        'تو مربیِ باتجربهٔ بدن‌سازی هستی و این عکس، یک فریم از دوربینِ گوشیِ ورزشکار '
        'است که همین حالا دارد این حرکت را انجام می‌دهد.\n\n'
        'نامِ حرکت: %s\n'
        'وسیله: %s\n'
        'عضلهٔ هدف: %s\n'
        'روشِ درستِ اجرا:\n%s\n\n'
        'به این سه چیز نگاه کن: وضعیتِ کمر و گردن، زاویهٔ آرنج و زانو، و جای دست‌ها '
        'و پاها. بعد حکم بده:\n'
        '· "ok" اگر اجرا در کل با روشِ درست سازگار است. ایرادِ ریز و '
        'سلیقه‌ای را bad نگیر؛ قوسِ طبیعیِ کمر در پرس سینه ایراد نیست.\n'
        '· "bad" فقط وقتی ایرادِ آشکار و قابلِ دیدن هست: کمرِ گردِ واضح، '
        'آرنجِ کاملاً باز، زانوی افتاده به داخل، یا اجرای حرکتی دیگر.\n'
        '· "unsure" اگر بدنِ ورزشکار در تصویر نیست، تار است، یا از این '
        'زاویه نمی‌شود فهمید. حدس نزن.\n'
        'تصویر ممکن است عکسِ واقعی یا انیمیشنِ سه‌بعدیِ آموزشی باشد؛ در هر '
        'دو حالت همان اجرا را بسنج و از نقاشی‌بودن ایراد نگیر.\n\n'
        'در "message" **یک جملهٔ کوتاهِ فارسی** بنویس که روی صفحهٔ دوربین نشان داده '
        'می‌شود: اگر ایراد دارد بگو چه چیزی را چطور اصلاح کند؛ اگر درست است یک '
        'تأییدِ کوتاه بده. از ۱۲ کلمه بیشتر نشود.\n'
        'در "box" جعبهٔ تقریبیِ بدنِ ورزشکار را به نسبتِ ابعادِ تصویر بده '
        '(x و y گوشهٔ بالا-چپ، w و h عرض و ارتفاع، همه بینِ ۰ و ۱). اگر بدن را '
        'ندیدی، box را null بگذار.\n\n'
        'فقط همین JSON و هیچ توضیحِ دیگری:\n'
        '{"verdict":"ok|bad|unsure","confidence":0.0,"message":"...",'
        '"box":{"x":0.2,"y":0.1,"w":0.6,"h":0.8}}'
        % (
            exercise.name_fa or exercise.name,
            exercise.equipment_fa or '-',
            exercise.target_fa or '-',
            _steps_text(exercise),
        )
    )


def _parse(text):
    if not text:
        return None
    raw = re.sub(r'^```(?:json)?|```$', '', text.strip(), flags=re.MULTILINE).strip()
    match = re.search(r'\{.*\}', raw, flags=re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except Exception:
        logger.warning('پاسخِ بررسیِ حرکت JSONِ درست نبود: %s', raw[:200])
        return None


def _clean_box(box):
    """جعبه را به عددهای سالمِ بینِ ۰ و ۱ تبدیل می‌کند یا None."""
    if not isinstance(box, dict):
        return None
    try:
        out = {k: max(0.0, min(1.0, float(box.get(k)))) for k in ('x', 'y', 'w', 'h')}
    except (TypeError, ValueError):
        return None
    if out['w'] <= 0.02 or out['h'] <= 0.02:
        return None
    return out


def check_frame(exercise, image_bytes):
    """یک فریم → (حکم، پیامِ فارسی، اطمینان، جعبه، متنِ خام، نامِ مدل، مصرف، تنظیمات)"""
    from ai_engine.ai_generator import call_model

    data = shrink(image_bytes)
    b64 = base64.b64encode(data).decode()
    messages = [{'role': 'user', 'content': [
        {'type': 'text', 'text': _prompt(exercise)},
        {'type': 'image_url', 'image_url': {'url': 'data:image/jpeg;base64,' + b64}},
    ]}]
    # temperature=None چون این درگاه مقدارِ دلخواه را رد می‌کند
    response, config = call_model(messages, 500, temperature=None)
    text = (response.choices[0].message.content or '').strip()
    parsed = _parse(text) or {}

    verdict = (parsed.get('verdict') or '').strip().lower()
    if verdict not in ('ok', 'bad', 'unsure'):
        verdict = 'unsure'
    try:
        confidence = max(0.0, min(1.0, float(parsed.get('confidence') or 0)))
    except (TypeError, ValueError):
        confidence = 0.0
    message = (parsed.get('message') or '').strip()
    if not message:
        message = {'ok': 'خوب است، همین‌طور ادامه بده.',
                   'bad': 'اجرای حرکت ایراد دارد؛ آموزش را دوباره ببین.',
                   'unsure': 'بدنت کاملاً در کادر نیست؛ گوشی را دورتر بگذار.'}[verdict]

    usage = getattr(response, 'usage', None)
    return {
        'verdict': verdict,
        'message': message[:200],
        'confidence': confidence,
        'box': _clean_box(parsed.get('box')),
        'raw': text,
        'model_name': config.get('model_name'),
        'usage': ((getattr(usage, 'prompt_tokens', 0) or 0),
                  (getattr(usage, 'completion_tokens', 0) or 0)),
        'config': config,
    }
