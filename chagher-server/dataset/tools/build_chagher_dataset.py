# -*- coding: utf-8 -*-
"""ساختِ دیتاستِ فارسیِ چغر از روی دیتاستِ انگلیسیِ exercises-dataset.

ورودی : ../exercises-dataset/data/exercises.json  (۱۳۲۴ حرکت، انگلیسی)
         terms_fa.json                            (واژه‌نامهٔ فارسی — قابلِ ویرایش)
خروجی : chagher-exercises.json                    (همان حرکت‌ها + فیلدهای فارسی + برچسبِ چغر)
         unknown_terms.txt                        (واژه‌هایی که ترجمه نشدند، به ترتیبِ تکرار)
         report.txt                               (کیفیتِ ترجمهٔ نام‌ها)

نامِ فارسی چطور ساخته می‌شود:
   «<نامِ حرکت> <قیدها> با <وسیله>»   مثال: barbell bench press → «پرس سینه با هالتر»
طولانی‌ترین عبارت اول تطبیق داده می‌شود؛ هر چه به terms_fa.json اضافه کنید، خروجی بهتر می‌شود.
اجرا:  python build_chagher_dataset.py
"""
import io, json, os, re, collections

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, '..', 'exercises-dataset', 'data', 'exercises.json')
TERMS = os.path.join(HERE, 'terms_fa.json')
OUT = os.path.join(HERE, 'chagher-exercises.json')

BRAND = 'چغر'
BRAND_EN = 'Chagher'

terms = json.load(io.open(TERMS, encoding='utf-8'))
EQ_FA = terms['equipment']
CAT_FA = terms['category']
MUS_FA = terms['muscle']
PHRASE = terms['phrase']
MODIF = terms['modifier']
WORD = terms['word']

# عبارت‌ها: اول حرکت‌ها، بعد قیدها؛ در هر گروه طولانی‌ترین اول
PHRASES = sorted(PHRASE.items(), key=lambda kv: -len(kv[0]))
MODIFS = sorted(MODIF.items(), key=lambda kv: -len(kv[0]))

unknown = collections.Counter()


def normalize(s):
    s = s.lower().strip()
    s = s.replace('(', ' ( ').replace(')', ' ) ')
    s = re.sub(r'\s+', ' ', s)
    return s


# نویسه‌های خرابِ منبع (مثلِ «45в°» که همان «۴۵ درجه» است) و واژه‌های چسبیده
CLEAN_FA = [('45в°', '۴۵ درجه'),
            ('в°', ' درجه'),
            ('row_shoulder', 'پارویی شانه')]


def clean_fa(s):
    for a, b in CLEAN_FA:
        s = s.replace(a, b)
    return s


def translate_name(name, equipment):
    """نامِ فارسی + کیفیت ('good' | 'partial' | 'weak')."""
    s = normalize(name)
    eq_fa = EQ_FA.get(equipment, equipment)

    # نامِ وسیله داخلِ نامِ حرکت تکرار نشود (آخرش با «با …» می‌آید)
    if equipment and equipment != 'body weight':
        s = s.replace(equipment, ' ')
    s = re.sub(r'\s+', ' ', s).strip(' ()')

    movement = None
    mods = []
    rest = s

    # ۱) نامِ حرکت (طولانی‌ترین تطابق)
    for en, fa in PHRASES:
        if re.search(r'(^|\s)' + re.escape(en) + r'($|\s)', rest):
            movement = fa
            rest = re.sub(r'(^|\s)' + re.escape(en) + r'($|\s)', ' ', rest, count=1)
            break

    # ۲) قیدها و حالت‌ها (هر چه بود)
    changed = True
    while changed:
        changed = False
        for en, fa in MODIFS:
            if re.search(r'(^|\s)' + re.escape(en) + r'($|\s)', rest):
                if fa and fa not in mods:
                    mods.append(fa)
                rest = re.sub(r'(^|\s)' + re.escape(en) + r'($|\s)', ' ', rest, count=1)
                changed = True
                break

    # ۳) واژه‌های تکِ باقی‌مانده
    leftovers = []
    for w in rest.split():
        w = w.strip('()،.')
        if not w:
            continue
        if w in WORD:
            if WORD[w]:
                leftovers.append(WORD[w])
        elif re.fullmatch(r'[0-9۰-۹]+', w) or w in {'v.', '-'}:
            continue
        else:
            unknown[w] += 1
            leftovers.append(w)          # انگلیسی می‌ماند تا معلوم باشد ترجمه نشده

    parts = []
    if movement:
        parts.append(movement)
    parts += leftovers + mods
    fa = ' '.join(p for p in parts if p).strip()
    if equipment and equipment != 'body weight':
        fa = (fa + ' با ' + eq_fa).strip()
    elif equipment == 'body weight' and 'وزن بدن' not in fa:
        fa = (fa + ' با وزن بدن').strip()

    has_en = any(re.search(r'[a-z]', p) for p in leftovers)
    quality = 'good' if movement and not has_en else ('partial' if movement else 'weak')
    return clean_fa(re.sub(r'\s+', ' ', fa).strip()), quality


def main():
    data = json.load(io.open(SRC, encoding='utf-8'))
    out = []
    qual = collections.Counter()

    # ترجمهٔ فارسیِ جمله‌های آموزش (steps_fa.json — ساختهٔ translate_steps.py با هوش مصنوعیِ خودِ چغر)
    fa_map = {}
    fa_path = os.path.join(HERE, 'steps_fa.json')
    if os.path.exists(fa_path):
        fa_map = json.load(io.open(fa_path, encoding='utf-8'))
    missing_steps = 0

    for x in data:
        name_fa, q = translate_name(x['name'], x.get('equipment') or '')
        qual[q] += 1
        en_steps = (x.get('instruction_steps') or {}).get('en') or []
        fa_steps = []
        for st in en_steps:
            t = fa_map.get(st.strip())
            if t:
                fa_steps.append(t)
            else:
                missing_steps += 1
        fa_text = ' '.join(fa_steps)
        rec = {
            'id': x['id'],
            'name': x['name'],
            'name_fa': name_fa,
            'name_fa_quality': q,          # good = مطمئن · partial = نیمه · weak = بازبینی لازم دارد
            'category': x.get('category'),
            'category_fa': CAT_FA.get(x.get('category'), x.get('category')),
            'body_part': x.get('body_part'),
            'body_part_fa': CAT_FA.get(x.get('body_part'), x.get('body_part')),
            'equipment': x.get('equipment'),
            'equipment_fa': EQ_FA.get(x.get('equipment'), x.get('equipment')),
            'target': x.get('target'),
            'target_fa': MUS_FA.get(x.get('target'), x.get('target')),
            'muscle_group': x.get('muscle_group'),
            'muscle_group_fa': MUS_FA.get(x.get('muscle_group'), x.get('muscle_group')),
            'secondary_muscles': x.get('secondary_muscles') or [],
            'secondary_muscles_fa': [MUS_FA.get(m, m) for m in (x.get('secondary_muscles') or [])],
            'instructions_en': (x.get('instructions') or {}).get('en'),
            'instruction_steps_en': (x.get('instruction_steps') or {}).get('en') or [],
            'instructions_fa': fa_text,
            'instruction_steps_fa': fa_steps,
            'gif': 'media_hq/gif/%s.gif' % x['id'],
            'thumb': 'media_hq/thumb/%s.jpg' % x['id'],
            'gif_source': x.get('gif_url'),
            'thumb_source': x.get('image'),
            'media_id': x.get('media_id'),
            'brand': BRAND,
            'brand_en': BRAND_EN,
            'media_attribution': x.get('attribution'),
        }
        out.append(rec)

    payload = {
        'dataset': 'Chagher Exercise Dataset',
        'dataset_fa': 'دیتاست حرکت‌های ورزشی چغر',
        'brand': BRAND,
        'brand_en': BRAND_EN,
        'count': len(out),
        'language': ['fa', 'en'],
        'media_note': 'گیف و عکس‌ها © Gym visual — https://gymvisual.com/ ؛ با لوگوی چغر نشانه‌گذاری شده‌اند.',
        'exercises': out,
    }
    with io.open(OUT, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)

    with io.open(os.path.join(HERE, 'unknown_terms.txt'), 'w', encoding='utf-8') as f:
        f.write('# واژه‌هایی که در terms_fa.json نبودند (تکرار ← واژه). هر کدام را اضافه کنید، دوباره اجرا کنید.\n')
        for w, c in unknown.most_common():
            f.write('%5d  %s\n' % (c, w))

    report = [
        'حرکت‌ها: %d' % len(out),
        'نامِ فارسیِ مطمئن (good): %d' % qual['good'],
        'نیمه (partial — چند واژه انگلیسی مانده): %d' % qual['partial'],
        'ضعیف (weak — نامِ حرکت در واژه‌نامه نبود): %d' % qual['weak'],
        'واژه‌های ترجمه‌نشده: %d (در unknown_terms.txt)' % len(unknown),
        'جمله‌های آموزشِ ترجمه‌شده: %d یکتا' % len(fa_map),
        'جمله‌های بدونِ ترجمه: %d' % missing_steps,
    ]
    with io.open(os.path.join(HERE, 'report.txt'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(report) + '\n')
    print('\n'.join(report))
    print('خروجی:', OUT)


if __name__ == '__main__':
    main()
