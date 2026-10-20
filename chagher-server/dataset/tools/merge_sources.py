# -*- coding: utf-8 -*-
"""افزودنِ حرکت‌های تازه از یک منبعِ دیگر به دیتاستِ چغر، بدونِ تکراری‌شدن.

برای وقتی که بستهٔ خریداری‌شده از Gym Visual (یا هر منبعِ دیگری) رسید:

    python merge_sources.py --src "D:\\GymVisual" --style 3d
    python merge_sources.py --src ..\\free-exercise-db --style photo

منبع چه شکلی باشد؟ یکی از این دو:
  الف) یک فایل JSON (آرایه‌ای از حرکت‌ها) + پوشهٔ گیف/عکس کنارش
  ب) پوشه‌ای از فایل‌های gif/jpg که نامِ فایل همان نامِ حرکت است
اسکریپت خودش هر دو حالت را تشخیص می‌دهد.

چطور تکراری تشخیص داده می‌شود: نامِ حرکت ساده می‌شود (حروفِ کوچک، حذفِ پرانتز و «v. 2»،
مرتب‌کردنِ واژه‌ها) و با همهٔ نام‌های موجود مقایسه می‌شود؛ هم‌نام‌ها رد می‌شوند و در
merge_report.txt فهرست می‌شوند تا خودتان ببینید چه چیزی رد شد.

خروجی: chagher-exercises.json به‌روز می‌شود (نسخهٔ قبلی با پسوندِ .bak نگه داشته می‌شود)
و فایل‌های مدیا با شناسهٔ تازه در media_hq/ کپی می‌شوند.
"""
import argparse, io, json, os, re, shutil, sys

HERE = os.path.dirname(os.path.abspath(__file__))
DATASET = os.path.join(HERE, 'chagher-exercises.json')
MEDIA = os.path.join(HERE, 'media_hq')


def norm(name):
    s = (name or '').lower()
    s = re.sub(r'\(.*?\)', ' ', s)
    s = re.sub(r'\bv\.?\s*\d+\b', ' ', s)
    s = re.sub(r'[^a-z0-9\u0600-\u06FF ]', ' ', s)
    return ' '.join(sorted(set(s.split())))


def load_terms():
    sys.path.insert(0, HERE)
    import build_chagher_dataset as b          # از همان واژه‌نامه و همان قاعدهٔ نام استفاده می‌کنیم
    return b


def find_source_records(src):
    """رکوردهای منبع را برمی‌گرداند: [{name, equipment, target, muscles, steps, gif, thumb}]"""
    recs = []
    jsons = []
    for root, _, files in os.walk(src):
        for f in files:
            if f.lower().endswith('.json'):
                jsons.append(os.path.join(root, f))

    for jp in jsons:
        try:
            data = json.load(io.open(jp, encoding='utf-8'))
        except Exception:
            continue
        rows = data if isinstance(data, list) else (data.get('exercises') or data.get('data') or [])
        if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
            continue
        base = os.path.dirname(jp)
        for r in rows:
            name = r.get('name') or r.get('title') or r.get('exercise')
            if not name:
                continue
            gif = r.get('gif_url') or r.get('gif') or r.get('animation') or ''
            img = r.get('image') or (r.get('images') or [''])[0] if r.get('images') else r.get('image') or ''
            recs.append({
                'name': name,
                'equipment': r.get('equipment') or r.get('equipments') or '',
                'target': r.get('target') or (r.get('primaryMuscles') or [''])[0],
                'category': r.get('category') or r.get('bodyPart') or r.get('body_part') or '',
                'secondary': r.get('secondaryMuscles') or r.get('secondary_muscles') or [],
                'steps': r.get('instructions') if isinstance(r.get('instructions'), list)
                         else ((r.get('instruction_steps') or {}).get('en') if isinstance(r.get('instruction_steps'), dict) else []),
                'gif': os.path.join(base, gif.replace('/', os.sep)) if gif else '',
                'thumb': os.path.join(base, img.replace('/', os.sep)) if img else '',
            })
        if recs:
            return recs

    # حالتِ «پوشهٔ فایل‌ها»: نامِ فایل = نامِ حرکت
    for root, _, files in os.walk(src):
        for f in files:
            if f.lower().endswith(('.gif', '.webp')):
                nm = os.path.splitext(f)[0].replace('_', ' ').replace('-', ' ')
                recs.append({'name': nm, 'equipment': '', 'target': '', 'category': '',
                             'secondary': [], 'steps': [],
                             'gif': os.path.join(root, f), 'thumb': ''})
    return recs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--src', required=True, help='پوشهٔ منبع')
    ap.add_argument('--style', default='3d', choices=['3d', 'photo'], help='سبکِ مدیا')
    ap.add_argument('--source-name', default=None, help='نامِ منبع برای ثبت در هر رکورد')
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    b = load_terms()
    payload = json.load(io.open(DATASET, encoding='utf-8'))
    rows = payload['exercises']
    have = {norm(r['name']) for r in rows}
    max_id = max(int(r['id']) for r in rows if r['id'].isdigit())

    src_recs = find_source_records(args.src)
    print('رکوردهای منبع:', len(src_recs))

    added, dup = [], []
    os.makedirs(os.path.join(MEDIA, 'gif'), exist_ok=True)
    os.makedirs(os.path.join(MEDIA, 'thumb'), exist_ok=True)

    for r in src_recs:
        key = norm(r['name'])
        if not key or key in have:
            dup.append(r['name'])
            continue
        have.add(key)
        max_id += 1
        new_id = '%04d' % max_id
        name_fa, q = b.translate_name(r['name'], r['equipment'] or '')
        rec = {
            'id': new_id,
            'name': r['name'],
            'name_fa': name_fa,
            'name_fa_quality': q,
            'category': r['category'], 'category_fa': b.CAT_FA.get(r['category'], r['category']),
            'body_part': r['category'], 'body_part_fa': b.CAT_FA.get(r['category'], r['category']),
            'equipment': r['equipment'], 'equipment_fa': b.EQ_FA.get(r['equipment'], r['equipment']),
            'target': r['target'], 'target_fa': b.MUS_FA.get(r['target'], r['target']),
            'muscle_group': r['target'], 'muscle_group_fa': b.MUS_FA.get(r['target'], r['target']),
            'secondary_muscles': r['secondary'],
            'secondary_muscles_fa': [b.MUS_FA.get(m, m) for m in r['secondary']],
            'instructions_en': ' '.join(r['steps'] or []),
            'instruction_steps_en': r['steps'] or [],
            'instructions_fa': None,
            'instruction_steps_fa': [],
            'gif': 'media_hq/gif/%s.gif' % new_id,
            'thumb': 'media_hq/thumb/%s.jpg' % new_id,
            'media_style': args.style,
            'brand': 'چغر', 'brand_en': 'Chagher',
            'source': args.source_name or os.path.basename(args.src.rstrip('\\/')),
        }
        if not args.dry_run:
            if r['gif'] and os.path.exists(r['gif']):
                shutil.copy2(r['gif'], os.path.join(MEDIA, 'gif', new_id + '.gif'))
            if r['thumb'] and os.path.exists(r['thumb']):
                shutil.copy2(r['thumb'], os.path.join(MEDIA, 'thumb', new_id + '.jpg'))
        added.append(rec)

    print('تازه: %d | تکراری (رد شد): %d' % (len(added), len(dup)))
    with io.open(os.path.join(HERE, 'merge_report.txt'), 'w', encoding='utf-8') as f:
        f.write('منبع: %s\nتازه: %d\nتکراری: %d\n\n--- تازه‌ها ---\n' % (args.src, len(added), len(dup)))
        for r in added:
            f.write('%s  %s  →  %s\n' % (r['id'], r['name'], r['name_fa']))
        f.write('\n--- تکراری‌ها (اضافه نشدند) ---\n')
        for n in dup:
            f.write('%s\n' % n)

    if args.dry_run:
        print('آزمایشی بود — چیزی نوشته نشد. گزارش: merge_report.txt')
        return

    shutil.copy2(DATASET, DATASET + '.bak')
    payload['exercises'] = rows + added
    payload['count'] = len(payload['exercises'])
    json.dump(payload, io.open(DATASET, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('دیتاست به‌روز شد: %d حرکت (نسخهٔ قبلی: %s)' % (payload['count'], os.path.basename(DATASET) + '.bak'))
    print('⚠ برای ترجمهٔ متنِ آموزشِ حرکت‌های تازه، steps_en.json را دوباره بسازید و translate_steps.py را اجرا کنید.')


if __name__ == '__main__':
    main()
