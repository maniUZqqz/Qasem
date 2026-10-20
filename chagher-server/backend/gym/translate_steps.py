# -*- coding: utf-8 -*-
"""ترجمهٔ جمله‌های آموزشِ حرکت‌ها به فارسی با همان سرویسِ هوش مصنوعیِ خودِ چغر.

ورودی : steps_en.json   (فهرستِ جمله‌های یکتای انگلیسی)
خروجی : steps_fa.json   (نگاشتِ انگلیسی → فارسی) — بعد از هر بسته ذخیره می‌شود (قابلِ ادامه)
اجرا   : python translate_steps.py [batch_size] [workers] [limit]
"""
import io, json, os, sys, time, threading
from concurrent.futures import ThreadPoolExecutor

import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gym.settings')
django.setup()
from app.models import APIConfig
from openai import OpenAI

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, 'steps_en.json')
OUT = os.path.join(HERE, 'steps_fa.json')

GLOSSARY = """dumbbell=دمبل | barbell=هالتر | cable=سیم‌کش | kettlebell=کتل‌بل | smith machine=دستگاه اسمیت
band=کش | bench=میز | incline bench=میز بالا سینه | decline=زیر سینه | ez bar=هالتر لاری
rep/repetition=تکرار | set=ست | grip=گرفتن/دست | shoulder-width=به عرضِ شانه | core=مرکزِ بدن
biceps=جلو بازو | triceps=پشت بازو | lats=زیربغل | quads=چهارسر ران | hamstrings=همسترینگ
glutes=باسن | calves=ساق پا | abs=شکم | obliques=پهلو | delts=دلتوئید | traps=کول | forearms=ساعد"""

SYSTEM = """تو مترجمِ فارسیِ متن‌های تمرینِ بدن‌سازی هستی.
قواعد:
- فقط فارسیِ روان و کوتاه بنویس، همان‌طور که یک مربیِ ایرانی به شاگردش می‌گوید.
- جمله را دستوری بنویس («دمبل را بالا ببر»)، نه توصیفی.
- اصطلاح‌ها را طبقِ این واژه‌نامه ترجمه کن:
""" + GLOSSARY + """
- چیزی اضافه یا حذف نکن؛ شماره‌گذاری نکن؛ توضیح نده.
- خروجی فقط یک آرایهٔ JSON از رشته‌های فارسی، دقیقاً هم‌تعداد و هم‌ترتیبِ ورودی."""

cfg = APIConfig.objects.filter(is_active=True).first() or APIConfig.objects.first()
client = OpenAI(api_key=cfg.api_key, base_url=cfg.base_url, timeout=180)
MODEL = cfg.model_name

lock = threading.Lock()
result = {}
if os.path.exists(OUT):
    result = json.load(io.open(OUT, encoding='utf-8'))
stats = {'in': 0, 'out': 0, 'fail': 0}


def save():
    tmp = OUT + '.tmp'
    with io.open(tmp, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=0)
    os.replace(tmp, OUT)


def translate(batch):
    payload = json.dumps(batch, ensure_ascii=False)
    for attempt in range(3):
        try:
            r = client.chat.completions.create(
                model=MODEL,
                messages=[{'role': 'system', 'content': SYSTEM},
                          {'role': 'user', 'content': payload}],

            )
            txt = (r.choices[0].message.content or '').strip()
            if txt.startswith('```'):
                txt = txt.split('```')[1]
                txt = txt[4:] if txt.lower().startswith('json') else txt
            fa = json.loads(txt)
            if not isinstance(fa, list) or len(fa) != len(batch):
                raise ValueError('طولِ خروجی %s با ورودی %s یکی نیست' % (len(fa), len(batch)))
            with lock:
                for en, f in zip(batch, fa):
                    result[en] = f.strip()
                u = getattr(r, 'usage', None)
                if u:
                    stats['in'] += u.prompt_tokens or 0
                    stats['out'] += u.completion_tokens or 0
                save()
            return True
        except Exception as e:
            if attempt == 2:
                with lock:
                    stats['fail'] += len(batch)
                print('شکست:', str(e)[:160], flush=True)
            else:
                time.sleep(2 + attempt * 3)
    return False


def main():
    size = int(sys.argv[1]) if len(sys.argv) > 1 else 25
    workers = int(sys.argv[2]) if len(sys.argv) > 2 else 6
    limit = int(sys.argv[3]) if len(sys.argv) > 3 else 0

    allsteps = json.load(io.open(SRC, encoding='utf-8'))
    todo = [s for s in allsteps if s not in result]
    if limit:
        todo = todo[:limit]
    print('کل: %d | ترجمه‌شده: %d | این اجرا: %d | مدل: %s'
          % (len(allsteps), len(result), len(todo), MODEL), flush=True)

    batches = [todo[i:i + size] for i in range(0, len(todo), size)]
    t0 = time.time()
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for _ in ex.map(translate, batches):
            done += 1
            if done % 10 == 0:
                print('%d/%d بسته — %ds — توکن: %d/%d'
                      % (done, len(batches), int(time.time() - t0), stats['in'], stats['out']), flush=True)
    save()
    print('تمام: %d جمله ترجمه شد، %d ناموفق، %ds، توکنِ ورودی %d خروجی %d'
          % (len(result), stats['fail'], int(time.time() - t0), stats['in'], stats['out']))


if __name__ == '__main__':
    main()
