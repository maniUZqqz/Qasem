# -*- coding: utf-8 -*-
"""وارد کردنِ «کاملِ» مخزنِ ui-ux-pro-max-skill (مجوز MIT) به فایل‌های JSONِ داخلِ مخزنِ ما.

مخزن را یک‌جا روی سرور آینه کرده‌ایم (``deploy/nm/uiux-mirror.sh`` ⇒ /opt/nm-mirror/ui-ux-pro-max-skill؛ ‏git clone کامل با تاریخچه)؛ این ابزار از همان آینه می‌خواند:

    cd backend && ../venv/bin/python -m apps.projects.builder.styles.import_uiux_full [/opt/nm-mirror/ui-ux-pro-max-skill]

خروجی: ``dataset/uiux/<نوع>.json`` برای هر نوعِ داده و ``dataset/uiux/index.json`` (شمارش، مبدأ، commit و مجوز)؛ ``dataset/uiux_pro_max.json`` دیگر نیست.
**همهٔ ردیف‌ها و همهٔ ستون‌ها** می‌آیند (حتی ردیف‌های اپِ موبایل و ردیف‌های منسوخ؛ با ستونِ ``status``)، پس صفحهٔ «منبع‌های طراحی» همه را نشان می‌دهد.
متنِ انگلیسیِ اصلی دست‌نخورده می‌ماند. فقط این‌ها کنار گذاشته می‌شوند (و علتشان در ``index.json`` در کلیدِ ``skipped`` ثبت می‌شود):
دادهٔ خامِ آیکونِ Phosphor (۸۰۰ کیلوبایتِ ابرداده‌ای که فقط ``icons.csv`` از آن ساخته شده)، متنِ مجوزِ تک‌تکِ قلم‌های گوگل (۴۳۰ کیلوبایت؛ مجوزِ قلم‌هایی که
خودمان می‌فرستیم کنارِ فایلشان هست)، دادهٔ آزمونِ خودِ مخزن و قالب‌های افزونهٔ ویرایشگرها.
"""
import csv
import datetime
import hashlib
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, 'dataset', 'uiux')
LICENSE_OUT = os.path.join(HERE, 'dataset', 'LICENSE-ui-ux-pro-max-skill.txt')
REPO_URL = 'https://github.com/nextlevelbuilder/ui-ux-pro-max-skill'
MIRROR = '/opt/nm-mirror/ui-ux-pro-max-skill'
MAX_CELL = 6000

csv.field_size_limit(10_000_000)

# ستون‌های هر فایل ⇒ کلیدِ کوتاه. (کلیدهای شش نوعِ قدیمی همان‌اند که کدِ پیشین می‌شناخت.)
MAPS = {
    'styles': {'No': 'n', 'Style Category': 'name', 'Type': 'type', 'Keywords': 'keywords', 'Primary Colors': 'primary_colors',
               'Secondary Colors': 'secondary_colors', 'Effects & Animation': 'effects', 'Best For': 'best_for', 'Do Not Use For': 'avoid',
               'Light Mode ✓': 'light', 'Dark Mode ✓': 'dark', 'Performance': 'performance', 'Accessibility': 'accessibility',
               'Mobile-Friendly': 'mobile', 'Conversion-Focused': 'conversion', 'Framework Compatibility': 'frameworks', 'Era/Origin': 'era',
               'Complexity': 'complexity', 'AI Prompt Keywords': 'ai_prompt', 'CSS/Technical Keywords': 'css', 'Implementation Checklist': 'checklist',
               'Design System Variables': 'variables', 'Style ID': 'id', 'Aliases': 'aliases', 'Status': 'status', 'Parent Style ID': 'parent',
               'Replacement Domain': 'replacement_domain', 'Replacement ID': 'replacement_id', 'Preferred Mode': 'preferred_mode', 'rtl_level': 'rtl'},
    'colors': {'No': 'n', 'Product Type': 'product', 'Primary': 'primary', 'On Primary': 'on_primary', 'Secondary': 'secondary', 'On Secondary': 'on_secondary',
               'Accent': 'accent', 'On Accent': 'on_accent', 'Background': 'background', 'Foreground': 'foreground', 'Card': 'card',
               'Card Foreground': 'card_foreground', 'Muted': 'muted', 'Muted Foreground': 'muted_foreground', 'Border': 'border',
               'Destructive': 'destructive', 'On Destructive': 'on_destructive', 'Ring': 'ring', 'Notes': 'notes'},
    'fonts': {'No': 'n', 'Font Pairing Name': 'name', 'Category': 'category', 'Heading Font': 'heading', 'Body Font': 'body', 'Mood/Style Keywords': 'mood',
              'Best For': 'best_for', 'Google Fonts URL': 'google_url', 'CSS Import': 'css_import', 'Tailwind Config': 'tailwind', 'Notes': 'notes'},
    'ux': {'No': 'n', 'Category': 'category', 'Issue': 'issue', 'Platform': 'platform', 'Description': 'description', 'Do': 'do', "Don't": 'dont',
           'Code Example Good': 'code_good', 'Code Example Bad': 'code_bad', 'Severity': 'severity'},
    'landing': {'No': 'n', 'Pattern Name': 'name', 'Keywords': 'keywords', 'Section Order': 'sections', 'Primary CTA Placement': 'cta',
                'Color Strategy': 'color_strategy', 'Recommended Effects': 'effects', 'Conversion Optimization': 'conversion', 'Pattern ID': 'id',
                'Aliases': 'aliases'},
    'motion': {'No': 'n', 'Category': 'category', 'Intensity Tier': 'tier', 'Keywords': 'keywords', 'Trigger': 'trigger', 'Duration': 'duration',
               'Easing': 'easing', 'GSAP Snippet': 'gsap', 'Framework Notes': 'frameworks', 'Do': 'do', "Don't": 'dont', 'Performance Notes': 'performance'},
    'charts': {'No': 'n', 'Data Type': 'data_type', 'Keywords': 'keywords', 'Best Chart Type': 'best', 'Secondary Options': 'secondary', 'When to Use': 'when',
               'When NOT to Use': 'when_not', 'Data Volume Threshold': 'volume', 'Color Guidance': 'color', 'Accessibility Grade': 'a11y_grade',
               'Accessibility Risk': 'a11y_risk', 'Accessibility Notes': 'a11y_notes', 'A11y Fallback': 'a11y_fallback', 'Library Recommendation': 'library',
               'Interactive Level': 'interactive'},
    'products': {'No': 'n', 'Product Type': 'product', 'Keywords': 'keywords', 'Primary Style Recommendation': 'primary_style', 'Secondary Styles': 'secondary_styles',
                 'Landing Page Pattern': 'landing', 'Dashboard Style (if applicable)': 'dashboard', 'Color Palette Focus': 'palette',
                 'Key Considerations': 'notes', 'rtl_level': 'rtl'},
    'reasoning': {'No': 'n', 'UI_Category': 'category', 'Recommended_Pattern': 'pattern', 'Style_Priority': 'style_priority', 'Color_Mood': 'color_mood',
                  'Typography_Mood': 'typography_mood', 'Key_Effects': 'effects', 'Decision_Rules': 'rules', 'Anti_Patterns': 'anti', 'Severity': 'severity',
                  'Reasoning': 'reasoning', 'Confidence': 'confidence'},
    'icons': {'No': 'n', 'Category': 'category', 'Icon Name': 'name', 'Keywords': 'keywords', 'Library': 'library', 'Import Code': 'import_code', 'Usage': 'usage',
              'Best For': 'best_for', 'Style': 'style', 'Semantic Role': 'role', 'Allowed Contexts': 'contexts'},
    'app': {'No': 'n', 'Category': 'category', 'Issue': 'issue', 'Keywords': 'keywords', 'Platform': 'platform', 'Description': 'description', 'Do': 'do', "Don't": 'dont',
            'Code Example Good': 'code_good', 'Code Example Bad': 'code_bad', 'Severity': 'severity'},
    'react': {'No': 'n', 'Category': 'category', 'Issue': 'issue', 'Keywords': 'keywords', 'Platform': 'platform', 'Description': 'description', 'Do': 'do', "Don't": 'dont',
              'Code Example Good': 'code_good', 'Code Example Bad': 'code_bad', 'Severity': 'severity'},
    'stacks': {'No': 'n', 'Category': 'category', 'Guideline': 'guideline', 'Description': 'description', 'Do': 'do', "Don't": 'dont', 'Code Good': 'code_good',
               'Code Bad': 'code_bad', 'Severity': 'severity', 'Docs URL': 'docs_url', 'Applies To': 'applies_to', 'Status': 'status', 'Verified At': 'verified_at'},
}
CORE_FILES = {'styles': 'styles.csv', 'colors': 'colors.csv', 'fonts': 'typography.csv', 'ux': 'ux-guidelines.csv', 'landing': 'landing.csv', 'motion': 'motion.csv',
              'charts': 'charts.csv', 'products': 'products.csv', 'reasoning': 'ui-reasoning.csv', 'icons': 'icons.csv', 'app': 'app-interface.csv',
              'react': 'react-performance.csv'}
SKIPPED = {
    'phosphor-icons-upstream.json': 'ابرداده‌ای خامِ آیکون‌های Phosphor (۸۰۰ کیلوبایت)؛ icons.csv از آن ساخته شده و همان آمده است',
    'google-font-licenses.json': 'متنِ مجوزِ تک‌تکِ قلم‌های گوگل (۴۳۰ کیلوبایت)؛ مجوزِ قلم‌هایی که خودمان می‌فرستیم (OFL) کنارِ فایلشان در builder/assets/fonts است',
    'data-provenance.json': 'گزارشِ منشأِ ردیف‌ها (برای نگه‌دارانِ مخزن)؛ در آینه هست',
    'catalog-summary.json': 'شمارشِ خودِ مخزن؛ این‌جا شمارشِ خودمان در index.json است',
    'sanitized': 'نامِ برندِ یک شرکتِ نرم‌افزاریِ بزرگ (قاعدهٔ رابطِ سایت‌ساز: نامِ آن شرکت در هیچ جا نیاید) از متنِ چند ردیفِ سبک‌ها حذف شد؛ بقیهٔ متن دست‌نخورده است',
    'scripts/tests, templates/platforms': 'آزمون‌ها و قالب‌های افزونهٔ ویرایشگرهای کد (به سایت‌ساز ربطی ندارند)',
}


_BRAND = [(re.compile(r'Adobe-adjacent', re.I), 'creative-suite-adjacent'), (re.compile(r'Adobe-style', re.I), 'pro-creative-style'), (re.compile(r',\s*adobe\b', re.I), ''),
          (re.compile(r'\badobe\b[- ]?', re.I), '')]


def clean_text(text):
    """قاعدهٔ سایت‌ساز: نامِ برندهای ادوبی (Adobe/Photoshop/Premiere) در هیچ جای رابط نیاید؛ این‌جا فقط یک ردیف دارد («Adobe Spectrum» ⇒ «Spectrum»)."""
    for rx, to in _BRAND:
        text = rx.sub(to, text)
    return re.sub(r'^[\s,;]+', '', text)


def slug(h):
    return re.sub(r'[^a-z0-9]+', '_', h.lower()).strip('_') or 'col'


def read_csv(path):
    with open(path, encoding='utf-8', newline='') as fh:
        return list(csv.DictReader(fh))


def convert(rows, mapping):
    out = []
    for r in rows:
        row = {}
        for col, val in r.items():
            if col is None:
                continue
            v = (val or '').strip()
            if not v:
                continue
            row[mapping.get(col) or slug(col)] = clean_text(v[:MAX_CELL])
        if row:
            out.append(row)
    return out


def dump(name, data):
    path = os.path.join(OUT_DIR, name + '.json')
    with open(path, 'w', encoding='utf-8', newline='\n') as fh:
        json.dump(data, fh, ensure_ascii=False, separators=(',', ':'))
        fh.write('\n')
    return os.path.getsize(path)


def md_docs(repo):
    """مستندهای markdownِ مخزن (مرجع‌های مهارت‌ها و قالبِ پایه)؛ تکراری‌ها (همان متن در چند پوشه) یک بار."""
    seen, docs = {}, []
    roots = [('.claude/skills', 'skill'), ('src/ui-ux-pro-max/templates/base', 'skill'), ('docs', 'repo')]
    for base, area in roots:
        top = os.path.join(repo, base)
        for dirpath, dirnames, files in os.walk(top):
            dirnames[:] = [d for d in dirnames if d not in ('node_modules', '.git', 'journals')]
            for f in sorted(files):
                if not f.endswith('.md'):
                    continue
                path = os.path.join(dirpath, f)
                rel = os.path.relpath(path, repo).replace('\\', '/')
                if not re.fullmatch(r'[A-Za-z0-9_./ -]+', rel):          # نام‌های غیرِ لاتین (مستنداتِ چینی) این‌جا نمی‌آیند
                    continue
                with open(path, encoding='utf-8') as fh:
                    text = fh.read()
                h = hashlib.sha1(text.encode('utf-8')).hexdigest()
                if h in seen:
                    docs[seen[h]].setdefault('also', []).append(rel)
                    continue
                seen[h] = len(docs)
                title = re.search(r'^#\s+(.+)$', text, re.M)
                parts = rel.split('/')
                skill = parts[2] if rel.startswith('.claude/skills/') and len(parts) > 2 else ('ui-ux-pro-max' if 'ui-ux-pro-max' in rel else 'repo')
                docs.append({'path': rel, 'skill': skill, 'area': area, 'title': (title.group(1).strip() if title else f)[:160], 'chars': len(text),
                             'text': text})
    docs.sort(key=lambda d: (d['skill'], d['path']))
    return docs


def main(repo=MIRROR):
    repo = os.path.abspath(repo)
    data = os.path.join(repo, 'src', 'ui-ux-pro-max', 'data')
    if not os.path.isdir(data):
        sys.exit('مخزن این‌جا نیست: %s (اول deploy/nm/uiux-mirror.sh را اجرا کنید)' % repo)
    commit = subprocess.run(['git', '-C', repo, 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip()
    commit_date = subprocess.run(['git', '-C', repo, 'log', '-1', '--format=%cI'], capture_output=True, text=True).stdout.strip()
    os.makedirs(OUT_DIR, exist_ok=True)
    counts, sizes = {}, {}
    for kind, fname in CORE_FILES.items():
        rows = convert(read_csv(os.path.join(data, fname)), MAPS[kind])
        counts[kind], sizes[kind] = len(rows), dump(kind, rows)
    # فایل‌های stack (۲۲ پشته): هر ردیف نامِ پشته‌اش را دارد
    stacks = []
    for f in sorted(os.listdir(os.path.join(data, 'stacks'))):
        if f.endswith('.csv'):
            for r in convert(read_csv(os.path.join(data, 'stacks', f)), MAPS['stacks']):
                r['stack'] = f[:-4]
                stacks.append(r)
    counts['stacks'], sizes['stacks'] = len(stacks), dump('stacks', stacks)
    # قلم‌های گوگل: همهٔ ردیف‌ها، ستون‌های کوتاه؛ «arabic» یعنی زیرمجموعهٔ عربی/فارسی دارد
    gf = []
    for r in read_csv(os.path.join(data, 'google-fonts.csv')):
        subsets = (r.get('Subsets') or '').lower()
        row = {'family': r.get('Family', ''), 'category': r.get('Category', ''), 'stroke': r.get('Stroke', ''), 'classes': (r.get('Classifications') or '')[:100],
               'arabic': 'arabic' in subsets, 'rank': r.get('Popularity Rank', '')}
        if row['arabic']:                                  # قلم‌های عربی/فارسی‌پذیر: ردیفِ کامل (برای نگاشتِ قلمِ فارسی)
            row.update(keywords=(r.get('Keywords') or '')[:160], axes=(r.get('Variable Axes') or '')[:80], subsets=r.get('Subsets', '')[:200],
                       is_noto=r.get('Is Noto', ''), styles=(r.get('Styles') or '')[:120])
        gf.append(row)
    counts['google_fonts'], sizes['google_fonts'] = len(gf), dump('google_fonts', gf)
    # اسلاید و هویتِ برند (فایل‌های مهارت‌های design-system و design)
    for kind, base in (('slides', '.claude/skills/design-system/data'), ('brand', '.claude/skills/design/data')):
        rows = []
        top = os.path.join(repo, base)
        for dirpath, _d, files in os.walk(top):
            for f in sorted(files):
                if f.endswith('.csv'):
                    sub = os.path.relpath(os.path.join(dirpath, f), top).replace('\\', '/')
                    for r in convert(read_csv(os.path.join(dirpath, f)), {}):
                        r['file'] = sub[:-4]
                        rows.append(r)
        counts[kind], sizes[kind] = len(rows), dump(kind, rows)
    docs = md_docs(repo)
    counts['docs'], sizes['docs'] = len(docs), dump('docs', docs)
    index = {
        'source': REPO_URL, 'commit': commit, 'commit_date': commit_date, 'license': 'MIT', 'copyright': 'Copyright (c) 2024 Next Level Builder',
        'retrieved': datetime.date.today().isoformat(), 'mirror': MIRROR,
        'note': 'کلِ داده‌های مخزنِ ui-ux-pro-max-skill؛ همهٔ ردیف‌ها و ستون‌ها، متنِ انگلیسیِ اصلی دست‌نخورده.',
        'counts': counts, 'bytes': sizes, 'skipped': SKIPPED,
    }
    dump('index', index)
    old = os.path.join(HERE, 'dataset', 'uiux_pro_max.json')
    if os.path.exists(old):
        os.remove(old)
    with open(os.path.join(repo, 'LICENSE'), encoding='utf-8') as src, open(LICENSE_OUT, 'w', encoding='utf-8', newline='\n') as dst:
        dst.write('Source: %s (commit %s)\n\n' % (REPO_URL, commit))
        dst.write(src.read())
    print(json.dumps({'counts': counts, 'bytes': sum(sizes.values()), 'commit': commit}, ensure_ascii=False))


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else MIRROR)
