# -*- coding: utf-8 -*-
"""تشخیصِ دستگاه‌های باشگاه از روی عکسِ دوربین.

کاربر با گوشی در باشگاه می‌چرخد و چند عکس می‌فرستد. هر عکس به مدلِ بینایی داده
می‌شود، همراه با **فهرستِ وسیله‌هایی که دیتابیسِ خودمان می‌شناسد**، و از مدل
خواسته می‌شود تا جای ممکن از همان فهرست انتخاب کند.

چرا فهرست می‌دهیم؟ اگر آزاد بگذاریم، مدل هر بار یک نامِ تازه می‌سازد («قفسهٔ
سینه»، «پک دک»، «باترفلای») و فهرستِ دستگاه‌های باشگاه پر از تکراری می‌شود —
همان دوگانگی‌ای که نباید پیش بیاید.

هیچ دستگاهی خودکار ثبت نمی‌شود: خروجی فقط پیشنهاد است و در EquipmentScanItem
می‌ماند تا کاربر تأیید کند.
"""
import base64
import io as _io
import os
import json
import logging
import re

logger = logging.getLogger(__name__)

MAX_SIDE = 1024          # عکسِ گوشی ۴ هزار پیکسلی است؛ بزرگ‌تر از این فقط توکن می‌سوزاند
JPEG_QUALITY = 85

# وسیله‌های پرتکرارِ باشگاه‌های ایران که در دیتاستِ حرکت‌ها نامِ جداگانه ندارند.
# این فهرست فقط «گزینه» است، نه ثبتِ خودکار؛ هدفش یکدست‌کردنِ نام‌هاست.
COMMON_EQUIPMENT = [
    'تردمیل', 'دوچرخهٔ ثابت', 'الپتیکال', 'دستگاه قایقی (روئینگ)', 'پله‌برقی ورزشی',
    'دستگاه پرس سینه', 'دستگاه قفسهٔ سینه (پک‌دک)', 'دستگاه زیربغل (لت)',
    'دستگاه زیربغل قایقی', 'دستگاه پرس سرشانه', 'دستگاه جلو پا', 'دستگاه پشت پا',
    'دستگاه پرس پا', 'دستگاه ساق پا', 'دستگاه سرینی (باسن)', 'دستگاه شکم',
    'دستگاه فیله کمر (هایپراکستنشن)', 'دستگاه اسمیت', 'دستگاه هاگ اسکوات',
    'قفسِ اسکوات (رک)', 'میز پرس سینه', 'میز بالاسینه', 'میز زیرسینه',
    'میز جلو بازو (لاری)', 'میز شکم', 'سیم‌کش دوقرقره (کراس‌اور)', 'سیم‌کش',
    'هالتر', 'دمبل', 'صفحهٔ وزنه', 'کتل‌بل', 'وزنهٔ مچی', 'بارفیکس', 'پارالل',
    'تی‌آر‌ایکس', 'کش ورزشی', 'توپ سوئدی', 'توپ بوسو', 'فوم رولر', 'طناب ورزشی',
    'طناب جنگی (بتل‌روپ)', 'جعبهٔ پلایومتریک', 'تشک ورزشی', 'کیسهٔ بوکس',
]

MUSCLE_GROUPS = [
    'سینه', 'زیربغل', 'سرشانه', 'جلو بازو', 'پشت بازو', 'ساعد', 'شکم', 'کمر',
    'پا', 'سرینی', 'ساق', 'هوازی', 'تمامِ بدن',
]

_ARABIC_FIX = {'ي': 'ی', 'ك': 'ک', 'ۀ': 'ه', 'إ': 'ا', 'أ': 'ا'}


def norm(name):
    """نامِ وسیله را برای مقایسه ساده می‌کند (تکراری‌ها را می‌گیرد)."""
    s = (name or '').strip().lower()
    for a, b in _ARABIC_FIX.items():
        s = s.replace(a, b)
    s = s.replace('‌', ' ')
    s = re.sub(r'\(.*?\)', ' ', s)                 # «(پک‌دک)» در مقایسه دخالت نکند
    s = re.sub(r'[^0-9a-z؀-ۿ ]', ' ', s)
    s = re.sub(r'\b(دستگاه|میز|ورزشی|ثابت)\b', ' ', s)
    return ' '.join(sorted(set(s.split())))


def candidate_names(user):
    """(فهرستِ نام‌ها، نقشهٔ «نامِ ساده‌شده → ردیفِ کاتالوگ یا None»)

    گزینه‌ها از **کاتالوگِ دستگاه‌ها** می‌آیند که مدیر در جنگو ادمین ویرایشش
    می‌کند؛ تا وقتی کاتالوگ خالی باشد، از فهرستِ درون‌کد استفاده می‌شود تا
    اسکن در هیچ حالتی از کار نیفتد.
    """
    from .equipment_catalog import candidates
    from .models import Equipment

    names, by_key = candidates(user)
    if names:
        return names, by_key

    # حالتِ اضطراری: کاتالوگ خالی است (seed اجرا نشده)
    fallback = {}
    out = []
    for value in list(COMMON_EQUIPMENT) + list(
            Equipment.objects.filter(user=user).values_list('name', flat=True)):
        key = norm(value)
        if key and key not in fallback:
            fallback[key] = None
            out.append(value)
    return out, fallback


def shrink(image_bytes):
    """عکس را تا ۱۰۲۴ پیکسل کوچک می‌کند. اگر Pillow نتوانست، همان اصل را می‌فرستد."""
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
        return buf.getvalue(), 'image/jpeg'
    except Exception:
        logger.warning('کوچک‌کردنِ عکس ممکن نشد؛ اصلِ فایل فرستاده می‌شود', exc_info=True)
        return image_bytes, 'image/jpeg'


def _prompt(candidates):
    return (
        'تو کارشناسِ تجهیزاتِ باشگاه بدن‌سازی هستی. در این عکس چه وسیله یا دستگاهی '
        'دیده می‌شود؟\n\n'
        'تا جای ممکن فقط از این فهرست انتخاب کن و نامِ تازه نساز:\n'
        + '\n'.join('- ' + c for c in candidates) + '\n\n'
        'گروهِ عضلانی را هم از این فهرست بگو: ' + '، '.join(MUSCLE_GROUPS) + '\n\n'
        'قاعده‌ها:\n'
        '۱) اگر وسیله‌ای در عکس هست که در فهرست نیست، نامِ فارسیِ رایجش را بنویس و '
        '"new": true بگذار.\n'
        '۲) چیزی که مطمئن نیستی را با اطمینانِ کم بیاور، نه این‌که حذف کنی.\n'
        '۳) آدم، آینه، دیوار و کفپوش وسیله نیستند.\n'
        '۴) هر وسیله فقط یک بار.\n\n'
        'خروجی را دقیقاً به این شکل و بدونِ هیچ توضیحِ اضافه بده:\n'
        '{"items":[{"name":"...","muscle_group":"...","confidence":0.8,"new":false}]}\n'
        'اگر هیچ وسیلهٔ ورزشی در عکس نبود: {"items":[]}'
    )


def _parse_items(text):
    """JSONِ خروجیِ مدل را بیرون می‌کشد؛ مدل گاهی دورش توضیح یا ```json می‌گذارد."""
    if not text:
        return []
    raw = text.strip()
    raw = re.sub(r'^```(?:json)?|```$', '', raw, flags=re.MULTILINE).strip()
    match = re.search(r'\{.*\}', raw, flags=re.DOTALL)
    if not match:
        return []
    try:
        data = json.loads(match.group(0))
    except Exception:
        logger.warning('پاسخِ مدل JSONِ درست نبود: %s', raw[:300])
        return []
    items = data.get('items') if isinstance(data, dict) else None
    return items if isinstance(items, list) else []


def recognize_photo(image_bytes, candidates):
    """یک عکس → (فهرستِ تشخیص‌ها، متنِ خامِ پاسخ، نامِ مدل، مصرفِ مدل)."""
    from ai_engine.ai_generator import call_model

    data, mime = shrink(image_bytes)
    b64 = base64.b64encode(data).decode()
    messages = [{
        'role': 'user',
        'content': [
            {'type': 'text', 'text': _prompt(candidates)},
            {'type': 'image_url', 'image_url': {'url': 'data:%s;base64,%s' % (mime, b64)}},
        ],
    }]
    # temperature=None چون برخی مدل‌ها (از جمله همین درگاه) مقدارِ دلخواه را رد می‌کنند
    response, config = call_model(messages, 900, temperature=None)
    text = (response.choices[0].message.content or '').strip()
    usage = getattr(response, 'usage', None)
    return (
        _parse_items(text),
        text,
        config.get('model_name'),
        (getattr(usage, 'prompt_tokens', 0) or 0, getattr(usage, 'completion_tokens', 0) or 0),
        config,
    )


def run_scan(scan, photo_files, candidates=None):
    """همهٔ عکس‌های یک اسکن را بررسی می‌کند و تشخیص‌ها را ذخیره می‌کند.

    photo_files: [(EquipmentScanPhoto, bytes)]
    خروجی: (تعدادِ تشخیص، هزینهٔ مدل، خطاها)
    """
    from decimal import Decimal

    from .models import APIConfig, Equipment, EquipmentScanItem

    names, by_key = candidates or candidate_names(scan.user)
    existing = {norm(n): pk for pk, n in
                Equipment.objects.filter(user=scan.user).values_list('id', 'name')}

    found = {}          # کلیدِ ساده‌شده → دادهٔ تشخیص
    raw_parts = []
    errors = []
    ai_cost = Decimal('0')
    model_name = None

    for photo, blob in photo_files:
        try:
            items, raw, model_name, (tin, tout), config = recognize_photo(blob, names)
            raw_parts.append('--- عکس #%s ---\n%s' % (photo.pk, raw))
            try:
                ai_cost += APIConfig.estimate_cost(tin, tout, config) or Decimal('0')
            except Exception:
                pass
        except Exception as exc:
            logger.exception('تشخیصِ عکسِ #%s شکست خورد', photo.pk)
            errors.append('عکسِ #%s: %s' % (photo.pk, exc))
            continue

        for item in items:
            if not isinstance(item, dict):
                continue
            name = (item.get('name') or '').strip()
            if not name:
                continue
            key = norm(name)
            if not key:
                continue
            try:
                confidence = float(item.get('confidence') or 0)
            except (TypeError, ValueError):
                confidence = 0.0
            confidence = max(0.0, min(1.0, confidence))
            is_new = bool(item.get('new')) or key not in by_key
            catalog_row = by_key.get(key)
            if catalog_row is not None:
                # نامِ رسمیِ کاتالوگ جای نامِ مدل می‌نشیند («باترفلای» ⇒ «قفسهٔ سینه»)
                name = catalog_row.name
                key = norm(name)
            muscle = (item.get('muscle_group') or '').strip()
            previous = found.get(key)
            if previous and previous['confidence'] >= confidence:
                continue
            found[key] = {
                'name': name, 'confidence': confidence,
                'muscle_group': muscle or (catalog_row.muscle_group if catalog_row else ''),
                'in_library': not is_new, 'photo': photo, 'catalog': catalog_row,
            }

    for key, data in found.items():
        EquipmentScanItem.objects.create(
            scan=scan,
            photo=data['photo'],
            name=data['name'],
            muscle_group=data['muscle_group'] or None,
            confidence=data['confidence'],
            in_library=data['in_library'],
            already_exists=key in existing,
            equipment_id=existing.get(key),
            catalog=data.get('catalog'),
        )

    scan.raw_answer = '\n\n'.join(raw_parts)[:20000] or None
    scan.model_name = model_name
    scan.error = '\n'.join(errors) or None
    return len(found), ai_cost, errors


def confirm_items(scan, accept_ids=None, reject_ids=None):
    """تأییدِ کاربر → ساختِ دستگاه در باشگاه. تکراری ساخته نمی‌شود.

    accept_ids=None یعنی «همه را تأیید کن» (دکمهٔ «تأییدِ همه»).
    """
    from django.utils import timezone

    from .models import Equipment, EquipmentScan

    items = list(scan.items.all())
    accept = set(int(i) for i in (accept_ids or [])) if accept_ids is not None else None
    reject = set(int(i) for i in (reject_ids or []))

    created, skipped = [], []
    for item in items:
        if item.pk in reject or (accept is not None and item.pk not in accept):
            item.is_rejected = True
            item.is_confirmed = False
            item.save(update_fields=['is_rejected', 'is_confirmed'])
            continue

        item.is_confirmed = True
        item.is_rejected = False
        if item.equipment_id:
            skipped.append(item)
        else:
            # ممکن است همین حالا با نامِ دیگری ثبت شده باشد؛ دوباره چک می‌شود
            match = next(
                (pk for pk, name in Equipment.objects
                 .filter(user=scan.user).values_list('id', 'name')
                 if norm(name) == norm(item.name)),
                None,
            )
            if match:
                item.equipment_id = match
                item.already_exists = True
                skipped.append(item)
            else:
                equipment = Equipment.objects.create(
                    user=scan.user,
                    name=item.name,
                    muscle_group=item.muscle_group or None,
                    description='از اسکنِ دوربین (اسکن #%s)' % scan.pk,
                    catalog=item.catalog,
                )
                copy_catalog_image(equipment, item.catalog)
                item.equipment = equipment
                created.append(item)
        item.save(update_fields=['is_confirmed', 'is_rejected', 'equipment', 'already_exists'])

    scan.status = EquipmentScan.STATUS_CONFIRMED
    scan.confirmed_at = timezone.now()
    scan.save(update_fields=['status', 'confirmed_at'])
    return created, skipped


def copy_catalog_image(equipment, catalog):
    """عکسِ مرجعِ کاتالوگ را روی دستگاهِ تازه کپی می‌کند.

    چرا کپی و نه ارجاع: عکسِ کاتالوگ ممکن است بعداً عوض یا پاک شود، ولی عکسِ
    دستگاهِ این باشگاه باید سرِ جایش بماند. شکستش نباید ثبتِ دستگاه را خراب کند.
    """
    if catalog is None or equipment.image:
        return False
    try:
        from django.core.files.base import ContentFile
        source = catalog.image if catalog.image else (
            catalog.exercise.thumb if catalog.exercise_id and catalog.exercise
            and catalog.exercise.thumb else None)
        if source is None:
            return False
        source.open('rb')
        data = source.read()
        source.close()
        ext = os.path.splitext(source.name)[1] or '.jpg'
        equipment.image.save('eq-%s%s' % (equipment.pk, ext), ContentFile(data), save=True)
        return True
    except Exception:
        logger.warning('کپیِ عکسِ کاتالوگ روی دستگاه #%s نشد', equipment.pk, exc_info=True)
        return False
