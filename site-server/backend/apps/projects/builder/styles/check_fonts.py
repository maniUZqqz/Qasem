# -*- coding: utf-8 -*-
"""گزارشِ پوششِ حروفِ فارسی در قلم‌های سایت‌ساز → `assets/fonts/coverage.json`.

چرا فایلِ گزارش؟ خواندنِ woff2 با fontTools به بسته‌ٔ brotli نیاز دارد که روی سرورِ سایت نصب نیست (و بی‌دلیل نصب نمی‌کنیم). پس این ابزار را یک بار
جایی که brotli هست اجرا می‌کنی؛ گزارش (با sha256 ِ هر فایل) کنارِ قلم‌ها می‌ماند و آزمون (tests_styles.test_fonts_have_persian_glyphs) می‌سنجد
که هر فایل هنوز همان است که سنجیده شده و هیچ حرفِ فارسی کم نیست. اگر brotli باشد آزمون خودش هم دوباره می‌سنجد.

اجرا (از پوشهٔ backend، با fonttools و brotli):
    python -m apps.projects.builder.styles.check_fonts
"""
import hashlib
import json
import os
import sys

PROBE = 'پچژگکیء۰۱۲۳۴۵۶۷۸۹'


def compute():
    from fontTools.ttLib import TTFont
    from apps.projects.builder import theme as T
    out = {'probe': PROBE, 'fonts': {}}
    for key, f in T.FONTS.items():
        files, covered = [], set()
        for e in f['files']:
            path = os.path.join(T.FONT_DIR, e[0])
            with open(path, 'rb') as fh:
                data = fh.read()
            cmap = set(TTFont(path).getBestCmap())
            covered |= {ch for ch in PROBE if ord(ch) in cmap}
            files.append({'file': e[0], 'sha256': hashlib.sha256(data).hexdigest()})
        out['fonts'][key] = {'family': f['family'], 'files': files, 'missing': ''.join(ch for ch in PROBE if ch not in covered)}
    return out


def main():
    from apps.projects.builder import theme as T
    data = compute()
    path = os.path.join(T.FONT_DIR, 'coverage.json')
    with open(path, 'w', encoding='utf-8', newline='\n') as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1, sort_keys=True)
        fh.write('\n')
    bad = {k: v['missing'] for k, v in data['fonts'].items() if v['missing']}
    print('fonts=%d missing=%s' % (len(data['fonts']), bad or 'none'))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
