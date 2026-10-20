# -*- coding: utf-8 -*-
"""آوردنِ عکسِ دستگاه‌ها از منابعِ آزادِ اینترنت — با وارسیِ مدلِ بینایی.

ترتیبِ منابع:
۱) **Openverse با فیلترِ CC0/مالکیتِ عمومی** — بی‌تعهدِ ذکرِ منبع.
۲) **ویکی‌مدیا کامنز** — اگر چیزی پیدا نشد؛ عکاس و پروانه در «یادداشت» ذخیره می‌شود.

⚠ درسِ گران: جست‌وجوی متنیِ کامنز شُل است. بارِ اول برای «میز زیرسینه» عکسِ
سنگ‌قبرِ آرلینگتون و برای «پارالل» عکسِ **گودیِ جاده** آورد. پس هر عکس قبل از
ذخیره به **مدلِ بینایی** نشان داده می‌شود: «آیا در این عکس <دستگاه> دیده می‌شود؟»
و تا تأیید نشود ذخیره نمی‌شود. عکسِ غلطِ مرجع از بی‌عکسی بدتر است، چون هم کاربر
را گمراه می‌کند و هم تشخیصِ اسکن را.

اجرا:
    python fetch_catalog_images.py                 # بی‌عکس‌ها را پر کن
    python fetch_catalog_images.py --verify-existing  # عکس‌های موجود را بازبینی کن
    python fetch_catalog_images.py --only "تردمیل" --force
"""
import argparse
import base64
import io
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gym.settings')
sys.path.insert(0, '/www/wwwroot/Cheghar/backend/gym')
import django  # noqa: E402
django.setup()

from django.core.files.base import ContentFile  # noqa: E402
from app.models import EquipmentCatalog  # noqa: E402

UA = 'ChagherGymBot/1.0 python-urllib'
MAX_CANDIDATES = 6          # بیشتر از این، هم کند است هم بی‌فایده

QUERIES = {
    'تردمیل': 'treadmill',
    'الپتیکال': 'elliptical trainer machine',
    'دستگاه الپتیکال': 'elliptical cross trainer gym',
    'دستگاه قایقی (روئینگ)': 'indoor rowing machine concept2',
    'دستگاه زیربغل قایقی': 'seated cable row machine',
    'دستگاه سرینی (باسن)': 'hip thrust glute bridge machine',
    'میز بالاسینه': 'incline bench press gym bench',
    'میز زیرسینه': 'decline bench gym weight bench adjustable',
    'پارالل': 'parallel bars calisthenics outdoor gym',
    'توپ سوئدی': 'stability ball yoga ball large',
    'توپ بوسو': 'bosu balance trainer',
    'فوم رولر': 'foam roller fitness',
    'غلتک': 'foam roller massage fitness',
    'جعبهٔ پلایومتریک': 'wooden plyometric jump box crossfit',
    'تشک ورزشی': 'yoga mat gym floor',
    'کیسهٔ بوکس': 'heavy punching bag boxing gym',
    'ارگومتر بالاتنه': 'arm crank ergometer handcycle',
    'دستگاه پله': 'stepper stairmaster exercise machine',
    'دستگاه شکم': 'abdominal crunch machine gym',
    'دستگاه فیله کمر (هایپراکستنشن)': 'roman chair hyperextension bench',
    'قفسِ اسکوات (رک)': 'squat power rack gym',
    'طناب جنگی (بتل‌روپ)': 'battle ropes training',
    'تی‌آر‌ایکس': 'suspension trainer straps TRX',
    'کش ورزشی': 'resistance bands fitness',
    'وزنهٔ مچی': 'ankle weights fitness',
    'دستگاه پرس سینه': 'chest press machine gym',
    'دستگاه قفسهٔ سینه (پک‌دک)': 'pec deck butterfly machine gym',
    'دستگاه زیربغل (لت)': 'lat pulldown machine gym',
    'دستگاه پرس سرشانه': 'shoulder press machine gym',
    'دستگاه جلو پا': 'leg extension machine gym',
    'دستگاه پشت پا': 'leg curl machine gym',
    'دستگاه پرس پا': 'leg press machine gym',
    'دستگاه ساق پا': 'calf raise machine gym',
    'دستگاه اسمیت': 'smith machine gym',
    'دستگاه هاگ اسکوات': 'hack squat machine gym',
    'میز پرس سینه': 'flat weight bench gym',
    'میز جلو بازو (لاری)': 'preacher curl bench',
    'میز شکم': 'sit up bench abdominal',
    'سیم‌کش دوقرقره (کراس‌اور)': 'cable crossover machine gym',
    'دوچرخهٔ ثابت': 'stationary exercise bike',
    'بارفیکس': 'pull up bar',
    'کیسه بوکس': 'heavy punching bag boxing',
}


# دسته‌بندیِ دقیقِ کامنز برای چیزهایی که جست‌وجوی متنی پیدایشان نمی‌کند.
# فایل‌های داخلِ یک دسته را آدم دسته‌بندی کرده، پس به‌جای حدس‌زدن از شرحِ عکس،
# می‌رویم سرِ همان دسته.
CATEGORY_HINTS = {
    'تشک ورزشی': ['Category:Yoga mats', 'Category:Exercise mats', 'Category:Gym mats'],
    'میز زیرسینه': ['Category:Weight benches'],
    'دستگاه سرینی (باسن)': ['Category:Weight training machines', 'Category:Exercise machines'],
    'جعبهٔ پلایومتریک': ['Category:Plyometrics', 'Category:Jumping exercises'],
    'دستگاه پله': ['Category:Stairclimbers', 'Category:Exercise machines'],
}


def get_json(url):
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': 'application/json'})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode('utf-8', 'replace'))


def get_bytes(url):
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def openverse_candidates(query):
    url = ('https://api.openverse.org/v1/images/?q=%s&license=cc0,pdm'
           '&page_size=%d&mature=false' % (urllib.parse.quote(query), MAX_CANDIDATES))
    try:
        data = get_json(url)
    except Exception as exc:
        # درخواستِ مهمان محدود است؛ ۴۰۳ یعنی «کمی صبر کن»، نه «نیست»
        print('    openverse خطا:', exc)
        time.sleep(3)
        try:
            data = get_json(url)
        except Exception:
            return
    for row in data.get('results') or []:
        link = row.get('url')
        if not link:
            continue
        try:
            blob = get_bytes(link)
        except Exception:
            continue
        if len(blob) < 8000:
            continue
        yield blob, 'منبع: Openverse · %s · پروانه: %s · %s' % (
            row.get('title') or '-', (row.get('license') or '').upper(),
            row.get('foreign_landing_url') or link)


def commons_candidates(query):
    search = ('https://commons.wikimedia.org/w/api.php?action=query&format=json'
              '&generator=search&gsrnamespace=6&gsrlimit=%d&gsrsearch=%s'
              '&prop=imageinfo&iiprop=url|size|mime|extmetadata&iiurlwidth=800'
              % (MAX_CANDIDATES, urllib.parse.quote(query + ' filetype:bitmap')))
    try:
        data = get_json(search)
    except Exception as exc:
        print('    commons خطا:', exc)
        return
    for page in ((data.get('query') or {}).get('pages') or {}).values():
        info = (page.get('imageinfo') or [{}])[0]
        if info.get('mime') not in ('image/jpeg', 'image/png'):
            continue
        if (info.get('width') or 0) < 500:
            continue
        link = info.get('thumburl') or info.get('url')
        if not link:
            continue
        try:
            blob = get_bytes(link)
        except Exception:
            continue
        meta = info.get('extmetadata') or {}
        author = re.sub(r'<[^>]+>', '', (meta.get('Artist') or {}).get('value', '-'))[:80]
        yield blob, 'منبع: Wikimedia Commons · %s · عکاس: %s · پروانه: %s · %s' % (
            page.get('title', '-'), author,
            (meta.get('LicenseShortName') or {}).get('value', '-'),
            info.get('descriptionurl', ''))


def commons_category_files(category):
    """فایل‌های یک دستهٔ مشخصِ کامنز (مثلِ Category:Yoga mats)."""
    try:
        members = get_json('https://commons.wikimedia.org/w/api.php?action=query&format=json'
                           '&list=categorymembers&cmtype=file&cmlimit=10&cmtitle=%s'
                           % urllib.parse.quote(category))
    except Exception as exc:
        print('    دستهٔ %s خطا: %s' % (category, exc))
        return
    files = [row['title'] for row in
             ((members.get('query') or {}).get('categorymembers') or [])]
    if not files:
        return
    try:
        info = get_json('https://commons.wikimedia.org/w/api.php?action=query&format=json'
                        '&prop=imageinfo&iiprop=url|size|mime|extmetadata&iiurlwidth=800'
                        '&titles=%s' % urllib.parse.quote('|'.join(files)))
    except Exception:
        return
    for page in ((info.get('query') or {}).get('pages') or {}).values():
        ii = (page.get('imageinfo') or [{}])[0]
        if ii.get('mime') not in ('image/jpeg', 'image/png'):
            continue
        if (ii.get('width') or 0) < 400:
            continue
        link = ii.get('thumburl') or ii.get('url')
        if not link:
            continue
        try:
            blob = get_bytes(link)
        except Exception:
            continue
        meta = ii.get('extmetadata') or {}
        author = re.sub(r'<[^>]+>', '', (meta.get('Artist') or {}).get('value', '-'))[:80]
        yield blob, 'منبع: Wikimedia Commons · %s · دسته: %s · عکاس: %s · پروانه: %s · %s' % (
            page.get('title', '-'), category, author,
            (meta.get('LicenseShortName') or {}).get('value', '-'),
            ii.get('descriptionurl', ''))


def commons_files_from_categories(query):
    """فایل‌های داخلِ دسته‌بندی‌های کامنز.

    جست‌وجوی متنیِ کامنز هر فایلی را می‌آورد که واژه در شرحش باشد («dip in the
    road» برای «dip bars»!). ولی دسته‌بندی‌ها را آدم ساخته است: فایل‌های داخلِ
    «Category:Exercise balls» واقعاً توپِ ورزشی‌اند. پس اول دسته را پیدا می‌کنیم.
    """
    try:
        cats = get_json('https://commons.wikimedia.org/w/api.php?action=query&format=json'
                        '&list=search&srnamespace=14&srlimit=3&srsearch=%s'
                        % urllib.parse.quote(query))
    except Exception as exc:
        print('    دستهٔ کامنز خطا:', exc)
        return
    titles = [row['title'] for row in ((cats.get('query') or {}).get('search') or [])]
    for title in titles:
        try:
            members = get_json('https://commons.wikimedia.org/w/api.php?action=query&format=json'
                               '&list=categorymembers&cmtype=file&cmlimit=8&cmtitle=%s'
                               % urllib.parse.quote(title))
        except Exception:
            continue
        files = [row['title'] for row in
                 ((members.get('query') or {}).get('categorymembers') or [])]
        if not files:
            continue
        try:
            info = get_json('https://commons.wikimedia.org/w/api.php?action=query&format=json'
                            '&prop=imageinfo&iiprop=url|size|mime|extmetadata&iiurlwidth=800'
                            '&titles=%s' % urllib.parse.quote('|'.join(files[:8])))
        except Exception:
            continue
        for page in ((info.get('query') or {}).get('pages') or {}).values():
            ii = (page.get('imageinfo') or [{}])[0]
            if ii.get('mime') not in ('image/jpeg', 'image/png'):
                continue
            if (ii.get('width') or 0) < 400:
                continue
            link = ii.get('thumburl') or ii.get('url')
            if not link:
                continue
            try:
                blob = get_bytes(link)
            except Exception:
                continue
            meta = ii.get('extmetadata') or {}
            author = re.sub(r'<[^>]+>', '', (meta.get('Artist') or {}).get('value', '-'))[:80]
            yield blob, 'منبع: Wikimedia Commons · %s · دسته: %s · عکاس: %s · پروانه: %s · %s' % (
                page.get('title', '-'), title, author,
                (meta.get('LicenseShortName') or {}).get('value', '-'),
                ii.get('descriptionurl', ''))


def to_jpeg(blob, max_side=800):
    from PIL import Image
    img = Image.open(io.BytesIO(blob))
    if img.mode not in ('RGB', 'L'):
        img = img.convert('RGB')
    if max(img.size) > max_side:
        ratio = max_side / float(max(img.size))
        img = img.resize((int(img.width * ratio), int(img.height * ratio)), Image.LANCZOS)
    buf = io.BytesIO()
    img.convert('RGB').save(buf, 'JPEG', quality=88, optimize=True)
    return buf.getvalue()


def verify(jpeg, fa_name, en_query):
    """(تأیید؟، توضیحِ مدل) — عکس را به مدلِ بینایی نشان می‌دهد."""
    from ai_engine.ai_generator import call_model
    small = to_jpeg(jpeg, 512)
    b64 = base64.b64encode(small).decode()
    prompt = (
        'در این عکس چه چیزی دیده می‌شود؟ سؤالِ من مشخص است: آیا این عکس، '
        '«%s» (به انگلیسی: %s) را نشان می‌دهد؟\n'
        'سخت‌گیر باش: اگر عکس چیزِ دیگری است (منظره، آدم بی‌دستگاه، شیءِ نامربوط) '
        'جوابت no است. اگر دستگاه در عکس هست — حتی اگر کسی هم روی آن باشد — yes.\n'
        'فقط همین JSON: {"match": true/false, "confidence": 0.0-1.0, "seen": "چه دیدی"}'
        % (fa_name, en_query)
    )
    messages = [{'role': 'user', 'content': [
        {'type': 'text', 'text': prompt},
        {'type': 'image_url', 'image_url': {'url': 'data:image/jpeg;base64,' + b64}},
    ]}]
    try:
        response, _ = call_model(messages, 300, temperature=None)
        text = (response.choices[0].message.content or '').strip()
    except Exception as exc:
        return None, 'خطای مدل: %s' % exc
    raw = re.sub(r'^```(?:json)?|```$', '', text, flags=re.MULTILINE).strip()
    m = re.search(r'\{.*\}', raw, flags=re.DOTALL)
    if not m:
        return None, text[:120]
    try:
        data = json.loads(m.group(0))
    except Exception:
        return None, text[:120]
    ok = bool(data.get('match')) and float(data.get('confidence') or 0) >= 0.7
    return ok, '%s (اطمینان %s)' % (data.get('seen') or '-', data.get('confidence'))


def query_for(row):
    return QUERIES.get(row.name) or QUERIES.get(row.name.replace('ٔ', '')) or None


def fill(row, dry_run=False):
    query = query_for(row)
    if not query:
        print('؟ واژهٔ جست‌وجو ندارد:', row.name)
        return False
    print('• %s  ←  %s' % (row.name, query))
    tried = 0
    hinted = []
    for cat in CATEGORY_HINTS.get(row.name, []):
        hinted += list(commons_category_files(cat))
    sources = (hinted
               + list(openverse_candidates(query))
               + list(commons_files_from_categories(query))
               + list(commons_candidates(query)))
    for blob, note in sources:
        tried += 1
        try:
            jpeg = to_jpeg(blob)
        except Exception:
            continue
        ok, seen = verify(jpeg, row.name, query)
        if not ok:
            print('    ✗ رد شد: %s | %s' % (seen, note[:60]))
            continue
        print('    ✓ %s | %s (%d کیلوبایت)' % (seen, note[:70], len(jpeg) // 1024))
        if not dry_run:
            row.image.save('cat-%s.jpg' % row.pk, ContentFile(jpeg), save=False)
            row.notes = ((row.notes or '').strip() + '\n' + note).strip()
            row.save(update_fields=['image', 'notes', 'updated_at'])
        return True
    print('    هیچ‌کدام از %d گزینه تأیید نشد' % tried)
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--only', default=None)
    ap.add_argument('--force', action='store_true')
    ap.add_argument('--verify-existing', action='store_true',
                    help='عکس‌های آپلودشده را بازبینی کن و غلط‌ها را پاک کن')
    args = ap.parse_args()

    rows = EquipmentCatalog.objects.all()
    if args.only:
        rows = rows.filter(name=args.only)

    if args.verify_existing:
        bad = kept = 0
        for row in rows.exclude(image=''):
            if not row.image:
                continue
            row.image.open('rb')
            blob = row.image.read()
            row.image.close()
            ok, seen = verify(blob, row.name, query_for(row) or row.name)
            if ok:
                kept += 1
                print('✓ %s — %s' % (row.name, seen))
            else:
                bad += 1
                print('✗ %s — %s  ⇒ پاک شد' % (row.name, seen))
                if not args.dry_run:
                    row.image.delete(save=False)
                    row.image = None
                    row.notes = ((row.notes or '') + '\nعکسِ قبلی با وارسیِ بینایی رد شد.').strip()
                    row.save(update_fields=['image', 'notes', 'updated_at'])
            time.sleep(0.5)
        print('\nسالم: %d | پاک‌شده: %d' % (kept, bad))
        return

    done = failed = skipped = 0
    for row in rows:
        if not args.force and (row.image or row.display_image_url()):
            skipped += 1
            continue
        if fill(row, args.dry_run):
            done += 1
        else:
            failed += 1
        time.sleep(1)
    print('\nگرفته شد: %d | نشد: %d | از قبل داشت: %d' % (done, failed, skipped))


if __name__ == '__main__':
    main()
