# -*- coding: utf-8 -*-
"""واردکردنِ دیتاستِ چغر به بک‌اندِ جنگوی چغر (اختیاری — وقتی لایسنسِ Gym Visual گرفته شد).

روی سرور:
    cd /www/wwwroot/Cheghar/backend/gym
    source venv/bin/activate
    python import_to_cheghar.py --json chagher-exercises.json --media media --dry-run
    python import_to_cheghar.py --json chagher-exercises.json --media media        # اجرای واقعی

چه می‌کند:
  · برای هر حرکت یک ردیف در Equipment (مدلِ فعلیِ اپ) می‌سازد یا به‌روز می‌کند — کلید: نامِ انگلیسی.
  · نامِ فارسی، دستگاه، عضله‌ها و آدرسِ گیف را در همان ردیف می‌گذارد.
  · فایل‌های گیف/عکس را در media/exercises/ کپی می‌کند.
⚠ پیش از اجرا یک بار با --dry-run ببینید چند ردیف ساخته/به‌روز می‌شود.
⚠ تا وقتی اجازهٔ Gym Visual نگرفته‌اید، مدیا را وارد نکنید (فقط --no-media).
"""
import argparse, io, json, os, shutil, sys

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--json', required=True)
    ap.add_argument('--media', default=None, help='پوشهٔ media (gif/thumb)')
    ap.add_argument('--no-media', action='store_true')
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gym.settings')
    import django
    django.setup()
    from django.conf import settings
    from app.models import Equipment

    payload = json.load(io.open(args.json, encoding='utf-8'))
    rows = payload['exercises']
    created = updated = 0
    media_root = getattr(settings, 'MEDIA_ROOT', None)
    dest_dir = os.path.join(media_root, 'exercises') if media_root else None
    if dest_dir and not args.dry_run and not args.no_media:
        os.makedirs(os.path.join(dest_dir, 'gif'), exist_ok=True)
        os.makedirs(os.path.join(dest_dir, 'thumb'), exist_ok=True)

    for r in rows:
        name = r['name_fa'] or r['name']
        desc_parts = [
            'دستگاه: %s' % (r.get('equipment_fa') or '—'),
            'عضلهٔ هدف: %s' % (r.get('target_fa') or '—'),
            'عضله‌های کمکی: %s' % ('، '.join(r.get('secondary_muscles_fa') or []) or '—'),
            'بخش بدن: %s' % (r.get('category_fa') or '—'),
            'نام انگلیسی: %s' % r['name'],
        ]
        description = ' | '.join(desc_parts)

        if args.dry_run:
            created += 1
            continue

        obj, is_new = Equipment.objects.get_or_create(
            name=name, defaults={'description': description})
        if not is_new:
            obj.description = description
            obj.save(update_fields=['description'])
            updated += 1
        else:
            created += 1

        if args.media and not args.no_media and dest_dir:
            for kind, rel in (('gif', r['gif']), ('thumb', r['thumb'])):
                src = os.path.join(args.media, os.path.basename(os.path.dirname(rel)), os.path.basename(rel))
                if os.path.exists(src):
                    shutil.copy2(src, os.path.join(dest_dir, kind, os.path.basename(rel)))

    if args.dry_run:
        print('آزمایشی: %d حرکت وارد می‌شد. هیچ چیزی نوشته نشد.' % created)
    else:
        print('ساخته‌شده: %d — به‌روزشده: %d' % (created, updated))


if __name__ == '__main__':
    main()
