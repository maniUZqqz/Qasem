# -*- coding: utf-8 -*-
"""وارد کردنِ دادهٔ «ui-ux-pro-max-skill» (مجوز MIT) به یک فایلِ JSON کوچک داخلِ مخزن.

اجرا (یک بار؛ نتیجه در مخزن هست و هنگامِ اجرای سایت لازم نیست):
    git clone --depth 1 https://github.com/nextlevelbuilder/ui-ux-pro-max-skill /tmp/uiux
    python import_uiux.py /tmp/uiux

فقط ستون‌های لازم برداشته می‌شود (بدونِ نمونه‌کدِ CSS/Tailwind و بدونِ ردیف‌های اپِ موبایل که به سایت ربطی ندارند)
و نویسندهٔ اصلی، نشانی، شناسهٔ commit و متنِ مجوز کنارِ داده می‌ماند: شرطِ مجوزِ MIT این است که اعلامِ حقِ نشر بماند.
"""
import csv
import datetime
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'dataset', 'uiux_pro_max.json')
LICENSE_OUT = os.path.join(HERE, 'dataset', 'LICENSE-ui-ux-pro-max-skill.txt')
REPO_URL = 'https://github.com/nextlevelbuilder/ui-ux-pro-max-skill'


def rows(path):
    with open(path, encoding='utf-8', newline='') as fh:
        return list(csv.DictReader(fh))


def pick(row, mapping, limit=420):
    out = {}
    for src, dst in mapping.items():
        v = (row.get(src) or '').strip()
        if v:
            out[dst] = v[:limit]
    return out


def main(repo):
    data = os.path.join(repo, 'src', 'ui-ux-pro-max', 'data')
    commit = subprocess.run(['git', '-C', repo, 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip()
    styles = []
    for r in rows(os.path.join(data, 'styles.csv')):
        s = pick(r, {'Style Category': 'name', 'Style ID': 'id', 'Type': 'type', 'Keywords': 'keywords', 'Primary Colors': 'primary_colors',
                     'Secondary Colors': 'secondary_colors', 'Effects & Animation': 'effects', 'Best For': 'best_for',
                     'Do Not Use For': 'avoid', 'Accessibility': 'accessibility', 'Mobile-Friendly': 'mobile',
                     'CSS/Technical Keywords': 'css', 'Design System Variables': 'variables', 'Implementation Checklist': 'checklist',
                     'rtl_level': 'rtl', 'Status': 'status', 'Light Mode ✓': 'light', 'Dark Mode ✓': 'dark'})
        if s.get('id') and 'mobile' not in s.get('name', '').lower().split('(')[-1:][0]:
            styles.append(s)
    colors = [pick(r, {'Product Type': 'product', 'Primary': 'primary', 'On Primary': 'on_primary', 'Secondary': 'secondary',
                       'Accent': 'accent', 'Background': 'background', 'Foreground': 'foreground', 'Card': 'card',
                       'Muted': 'muted', 'Border': 'border', 'Notes': 'notes'}, 200) for r in rows(os.path.join(data, 'colors.csv'))]
    fonts = [pick(r, {'Font Pairing Name': 'name', 'Category': 'category', 'Heading Font': 'heading', 'Body Font': 'body',
                      'Mood/Style Keywords': 'mood', 'Best For': 'best_for', 'Notes': 'notes'}, 260) for r in rows(os.path.join(data, 'typography.csv'))]
    ux = [pick(r, {'Category': 'category', 'Issue': 'issue', 'Platform': 'platform', 'Description': 'description', 'Do': 'do',
                   "Don't": 'dont', 'Severity': 'severity'}, 300) for r in rows(os.path.join(data, 'ux-guidelines.csv'))]
    landing = [pick(r, {'Pattern Name': 'name', 'Keywords': 'keywords', 'Section Order': 'sections', 'Primary CTA Placement': 'cta',
                        'Color Strategy': 'color_strategy', 'Recommended Effects': 'effects', 'Conversion Optimization': 'conversion'}, 300)
               for r in rows(os.path.join(data, 'landing.csv'))]
    motion = [pick(r, {'Category': 'category', 'Intensity Tier': 'tier', 'Keywords': 'keywords', 'Duration': 'duration', 'Easing': 'easing',
                       'Do': 'do', "Don't": 'dont'}, 220) for r in rows(os.path.join(data, 'motion.csv'))]
    out = {
        'source': REPO_URL, 'commit': commit, 'license': 'MIT', 'copyright': 'Copyright (c) 2024 Next Level Builder',
        'retrieved': datetime.date.today().isoformat(),
        'note': 'زیرمجموعه‌ای از دادهٔ مخزنِ بالا (بدونِ نمونه‌کد و بدونِ ردیف‌های اپِ موبایل)؛ متنِ انگلیسیِ اصلی دست‌نخورده است.',
        'styles': styles, 'colors': colors, 'fonts': fonts, 'ux': ux, 'landing': landing, 'motion': motion,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w', encoding='utf-8', newline='\n') as fh:
        json.dump(out, fh, ensure_ascii=False, indent=0, separators=(',', ':'))
        fh.write('\n')
    with open(os.path.join(repo, 'LICENSE'), encoding='utf-8') as src, open(LICENSE_OUT, 'w', encoding='utf-8', newline='\n') as dst:
        dst.write('Source: %s (commit %s)\n\n' % (REPO_URL, commit))
        dst.write(src.read())
    print('styles=%d colors=%d fonts=%d ux=%d landing=%d motion=%d bytes=%d' % (len(styles), len(colors), len(fonts), len(ux), len(landing), len(motion),
                                                                                os.path.getsize(OUT)))


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else '/tmp/uiux')
