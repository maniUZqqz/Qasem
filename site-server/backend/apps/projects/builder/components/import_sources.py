# -*- coding: utf-8 -*-
"""سنجشِ مبدأ و مجوزِ قطعه‌های «adapted» — فقط چند درخواستِ سبکِ عمومی، نه خزیدنِ سایت.

اجرا (از پوشهٔ backend؛ شبکه لازم است و فقط برای تازه‌کردنِ گزارش):
    python -m apps.projects.builder.components.import_sources

چه می‌کند:
  ۱. برای هر قطعه‌ای که در 21st.dev فهرست شده، صفحهٔ عمومیِ `.md` ِ همان قطعه را می‌خواند (نویسنده، کتابخانه، مجوز؛ 21st.dev این صفحه‌ها را برای عامل‌ها
     باز گذاشته: «ai-input=yes») و در dataset/sources_checked.json می‌گذارد؛ مجوز باید یکی از PERMISSIVE باشد، وگرنه خطا.
  ۲. وجودِ فایلِ مبدأ در شناسهٔ commit ِ مخزنِ نویسنده را می‌سنجد و متنِ مجوزِ مخزن را در dataset/LICENSE-*.txt می‌نویسد (شرطِ MIT: اعلامِ حقِ نشر بماند).
  ۳. یک بار می‌سنجد ریجیستریِ `https://21st.dev/r/<نویسنده>/<قطعه>` بی‌کلید چه جواب می‌دهد (۴۰۳ authentication_required) تا ثبت شود چرا کد از GitHub آمد.

اگر کلیدِ API دارید (`API_KEY_21ST`)، می‌شود قطعهٔ تازه را با `npx shadcn@latest add "https://21st.dev/r/<نویسنده>/<قطعه>?api_key=$API_KEY_21ST"` گرفت،
در provenance.adapted ثبت کرد و همین ابزار را دوباره اجرا کرد؛ تبدیلِ React/Tailwind به قالبِ سمتِ سرور کارِ دستی است (نگاه کنید به docs/site-styles-and-components.md).
"""
import datetime
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

from . import COMPONENTS, provenance as PV

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, 'dataset')
UA = 'NM-site-builder-source-check/1.0 (+license verification; ~10 requests)'


def get(url, timeout=30):
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': 'text/markdown,text/plain,application/json,*/*'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode('utf-8', 'replace')
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode('utf-8', 'replace')


def parse_listing(md):
    def field(name):
        m = re.search(r'^- %s:\s*(.+)$' % re.escape(name), md, re.M)
        return m.group(1).strip() if m else ''
    link = lambda s: (re.match(r'\[([^\]]+)\]', s) or [None, s])[1]
    title = re.search(r'^#\s+(.+)$', md, re.M)
    return {'title': title.group(1).strip() if title else '', 'author': link(field('Author')), 'library': link(field('Library')),
            'license': field('License'), 'tags': field('Tags'), 'npm': field('npm dependencies')}


def main():
    os.makedirs(DATA, exist_ok=True)
    rows, files, errors = [], [], []
    libs_done = set()
    for key, comp in COMPONENTS.items():
        src = PV.src_of(comp)
        if src['origin'] != 'adapted':
            continue
        lib = next(k for k, v in PV.LIBRARIES.items() if v['name'] == src['library'])
        L = PV.LIBRARIES[lib]
        path = src['source_url'].split('/blob/%s/' % src['commit'])[1]
        raw = 'https://raw.githubusercontent.com/%s/%s/%s' % (L['repo'].split('github.com/')[1], src['commit'], path)
        status, _ = get(raw)
        files.append({'component': key, 'path': path, 'commit': src['commit'], 'http': status})
        if status != 200:
            errors.append('%s: فایلِ مبدأ در commit پیدا نشد (%s)' % (key, status))
        time.sleep(0.6)
        if lib not in libs_done:
            libs_done.add(lib)
            st, text = get('https://raw.githubusercontent.com/%s/%s/LICENSE.md' % (L['repo'].split('github.com/')[1], src['commit']))
            if st != 200:
                st, text = get('https://raw.githubusercontent.com/%s/%s/LICENSE' % (L['repo'].split('github.com/')[1], src['commit']))
            if st == 200 and 'MIT License' in text:
                with open(os.path.join(HERE, L['license_file']), 'w', encoding='utf-8', newline='\n') as fh:
                    fh.write('Source: %s (commit %s)\n\n%s' % (L['repo'], src['commit'], text))
            else:
                errors.append('%s: متنِ مجوز خوانده نشد' % lib)
        if src['listing_url']:
            st, md = get(src['listing_url'] + '.md')
            time.sleep(0.8)
            row = parse_listing(md) if st == 200 else {}
            row.update({'component': key, 'listing': src['listing_url'], 'http': st})
            rows.append(row)
            if st != 200 or row.get('license', '').lower() not in {x.lower() for x in PV.PERMISSIVE}:
                errors.append('%s: مجوزِ listing «%s» مجاز نیست یا صفحه نیامد (%s)' % (key, row.get('license'), st))
    # ریجیستری بی‌کلید (فقط ثبتِ وضعیت؛ برای اثبات این‌که کد از ریجیستری نیامد)
    st, body = get('https://21st.dev/r/shadcn/button')
    reason = ''
    try:
        reason = json.loads(body).get('reason', '')
    except ValueError:
        pass
    out = {'checked_at': datetime.date.today().isoformat(), 'tool': 'apps.projects.builder.components.import_sources',
           'registry': {'url': 'https://21st.dev/r/shadcn/button', 'http': st, 'reason': reason,
                        'note': 'بی‌کلیدِ API کدِ ریجیستری داده نمی‌شود؛ کدِ قطعه‌های adapted از مخزنِ MIT خودِ نویسنده خوانده شد.'},
           'rows': rows, 'files': files, 'errors': errors}
    with open(os.path.join(DATA, 'sources_checked.json'), 'w', encoding='utf-8', newline='\n') as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
        fh.write('\n')
    print('rows=%d files=%d errors=%d registry=%s/%s' % (len(rows), len(files), len(errors), st, reason))
    for e in errors:
        print('ERROR', e)
    return 1 if errors else 0


if __name__ == '__main__':
    sys.exit(main())
