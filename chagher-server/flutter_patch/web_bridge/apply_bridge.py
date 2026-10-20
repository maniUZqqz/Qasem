# -*- coding: utf-8 -*-
"""گذاشتنِ «پلِ چغر» داخلِ بیلدِ فلاتر (index.html).

چرا این‌طور: سورسِ فلاتر در دسترس نیست و فقط بیلد روی سرور است. تنها جایی که
می‌شود بی‌خطر دست زد، **صفحهٔ میزبان** (index.html) است — خودِ main.dart.js
دست نمی‌خورد. اسکریپت به‌صورتِ **درون‌خطی** تزریق می‌شود، نه فایلِ جدا، تا
کشِ مرورگر و سروریس‌ورکر دردسر نسازند.

این اسکریپت **بی‌خطر و تکرارشدنی** است: اگر پل از قبل باشد، فقط نسخهٔ تازه
جایش می‌نشیند. بعد از هر بیلدِ تازهٔ فلاتر، یک‌بار اجرایش کنید:

    python /www/wwwroot/Cheghar/flutter_patch/web_bridge/apply_bridge.py
    python ... apply_bridge.py --remove      # برداشتنِ پل
"""
import argparse
import io
import os
import shutil
import time

WEB = '/www/wwwroot/Cheghar/frontend/web'
INDEX = os.path.join(WEB, 'index.html')
BRIDGE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'chagher-bridge.js')

START = '<!-- CHAGHER-BRIDGE:START (ساختهٔ apply_bridge.py — دستی ویرایش نکنید) -->'
END = '<!-- CHAGHER-BRIDGE:END -->'


def current_block():
    source = io.open(BRIDGE, encoding='utf-8').read()
    return '%s\n<script>\n%s\n</script>\n%s' % (START, source.strip(), END)


def strip_old(html):
    if START not in html:
        return html, False
    head, rest = html.split(START, 1)
    if END not in rest:
        return html, False
    _, tail = rest.split(END, 1)
    return head + tail, True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--remove', action='store_true', help='پل را بردار')
    args = parser.parse_args()

    html = io.open(INDEX, encoding='utf-8').read()
    backup = '%s.bak-%s' % (INDEX, time.strftime('%Y%m%d-%H%M%S'))
    shutil.copy2(INDEX, backup)

    html, had_old = strip_old(html)
    if args.remove:
        io.open(INDEX, 'w', encoding='utf-8', newline='').write(html)
        print('پل برداشته شد.' if had_old else 'پلی نبود.')
        print('بکاپ:', backup)
        return

    assert '</body>' in html, 'index.html تگِ </body> ندارد؛ دستی بررسی کنید.'
    html = html.replace('</body>', current_block() + '\n\n</body>', 1)
    io.open(INDEX, 'w', encoding='utf-8', newline='').write(html)
    print('پل %s شد.' % ('به‌روز' if had_old else 'گذاشته'))
    print('بکاپ:', backup)
    print('حجمِ index.html:', len(html), 'بایت')


if __name__ == '__main__':
    main()
