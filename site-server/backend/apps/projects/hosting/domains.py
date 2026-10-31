# -*- coding: utf-8 -*-
"""دامنهٔ سفارشی: پاک‌سازیِ ورودی، سایت‌های ممنوع، بررسیِ DNS و متنِ راهنمای فارسی."""
import re
from urllib.parse import urlsplit

from . import sysops

# ثبت‌شده‌های دوبخشی که «ریشهٔ دامنه» را سه‌بخشی می‌کنند
TWO_LEVEL = {'co.ir', 'ac.ir', 'org.ir', 'net.ir', 'gov.ir', 'id.ir', 'sch.ir', 'co.uk', 'org.uk', 'com.tr', 'com.au', 'co.in'}
# علاوه بر vhost‌های موجود: حتی اگر vhost ِ این‌ها روزی عوض شود، این‌جا باز هم پذیرفته نمی‌شوند
RESERVED = {'chagher.ir', 'tamouzstudio.com', 'tamouz.studio', 'nmarketing.ir', 'upmarket.ir'}


class DomainError(ValueError):
    """متنش مستقیم به مالک نشان داده می‌شود."""


def registrable(name):
    parts = name.split('.')
    k = 3 if len(parts) >= 3 and '.'.join(parts[-2:]) in TWO_LEVEL else 2
    return '.'.join(parts[-k:])


def is_apex(name):
    return registrable(name) == name


def normalize(raw):
    """هر چیزی که مالک بچسباند (https://www.Example.com/shop) ⇐ example.com"""
    text = str(raw or '').strip().lower().replace('‌', '').replace('‏', '').replace('‎', '')
    if not text:
        raise DomainError('نامِ دامنه را بنویس؛ مثلاً example.ir')
    if len(text) > 300 or re.search(r'[\s\x00-\x1f"\'<>\\;{}$`|&]', text):
        raise DomainError('این نامِ دامنه درست نیست. فقط نامِ دامنه را بنویس؛ مثلاً example.ir')
    if '//' in text:
        text = urlsplit(text).netloc or text
    text = text.split('/')[0].split('?')[0].split('#')[0]
    if '@' in text:
        raise DomainError('این نامِ دامنه درست نیست. فقط نامِ دامنه را بنویس؛ مثلاً example.ir')
    text = text.split(':')[0].rstrip('.')
    if text.startswith('www.'):
        text = text[4:]
    if re.fullmatch(r'[\d.]+', text):
        raise DomainError('این یک IP است، نه دامنه. نامِ دامنه را بنویس؛ مثلاً example.ir')
    if not text.isascii():
        try:
            text = text.encode('idna').decode('ascii')
        except UnicodeError:
            raise DomainError('این نامِ دامنه درست نیست؛ مثلاً example.ir')
    if not sysops.DOMAIN_RE.match(text):
        raise DomainError('این نامِ دامنه درست نیست؛ مثلاً example.ir')
    return text


def check_allowed(name, key):
    """دامنهٔ سایت‌های دیگرِ این سرور هرگز پذیرفته نمی‌شود، نه خودش و نه زیردامنه‌هایش."""
    foreign, own = sysops.foreign_server_names()
    base = registrable(name)
    bases = {registrable(f) for f in foreign} | {registrable(r) for r in RESERVED}
    if name in foreign or name in RESERVED or base in bases:
        raise DomainError('این دامنه مالِ سایتِ دیگری روی همین سرور است و نمی‌شود از آن استفاده کرد.')
    for other, names in own.items():
        if other != key and (name in names or 'www.' + name in names):
            raise DomainError('این دامنه الان به سایتِ دیگری از همین پنل وصل است؛ اول از آن‌جا جدایش کن.')


def names_for(name):
    return [name, 'www.' + name] if is_apex(name) else [name]


def records_for(name):
    """رکوردهایی که مالک باید در پنلِ دامنه‌اش بگذارد."""
    ip = sysops.public_ip()
    if is_apex(name):
        return [{'type': 'A', 'name': '@', 'host': name, 'value': ip}, {'type': 'A', 'name': 'www', 'host': 'www.' + name, 'value': ip}]
    host = name[:-len(registrable(name)) - 1]
    return [{'type': 'A', 'name': host, 'host': name, 'value': ip}]


def instruction(name):
    rows = records_for(name)
    lines = ['وارد پنلِ جایی شو که دامنه‌ات را از آن خریده‌ای (مثلاً نیک ایران، ایران‌سرور یا پارس‌پک) و بخشِ «مدیریتِ DNS» را باز کن.',
             'این %s را اضافه کن:' % ('دو رکورد' if len(rows) == 2 else 'رکورد')]
    for r in rows:
        lines.append('نوع: A — نام: %s — مقدار: %s' % (r['name'], r['value']))
    lines.append('اگر رکوردِ A ِ دیگری با همین نام هست، پاکش کن. اگر از کلادفلر استفاده می‌کنی، ابرِ نارنجی را خاموش کن.')
    lines.append('تغییر معمولاً چند دقیقه طول می‌کشد (گاهی تا چند ساعت). بعد این‌جا «بررسی و وصل کردن» را بزن.')
    return lines


def check_dns(name):
    """⇒ {'ready', 'names': نام‌هایی که درست‌اند، 'problems': [متنِ فارسی]}"""
    ip = sysops.public_ip()
    good, problems = [], []
    for host in names_for(name):
        found = sysops.dig_a(host)
        if not found:
            problems.append('«%s» هنوز رکوردی ندارد (یا تغییرت هنوز پخش نشده). رکوردِ A را با مقدارِ %s بگذار و چند دقیقه بعد دوباره بزن.' % (host, ip))
        elif ip not in found:
            problems.append('«%s» الان به %s اشاره می‌کند، نه به این سرور (%s). مقدارِ رکوردِ A را عوض کن. اگر از کلادفلر استفاده می‌کنی ابرِ نارنجی را خاموش کن.' % (host, '، '.join(found[:3]), ip))
        elif len(found) > 1:
            problems.append('«%s» چند رکورد دارد (%s). فقط رکوردِ %s باید بماند؛ بقیه را پاک کن.' % (host, '، '.join(found[:3]), ip))
        else:
            aaaa = sysops.dig_a(host, 'AAAA')
            if aaaa:
                problems.append('«%s» رکوردِ AAAA هم دارد (%s) که به این سرور نمی‌رسد و گواهی را خراب می‌کند. رکوردِ AAAA را پاک کن.' % (host, aaaa[0]))
            else:
                good.append(host)
    return {'ready': name in good, 'names': good, 'problems': problems}


def explain_cert_failure(out):
    """خطای certbot ⇐ توضیحِ فارسی و کارِ بعدی."""
    low = (out or '').lower()
    if 'too many' in low or 'ratelimit' in low or 'rate limit' in low:
        return 'صادرکنندهٔ گواهی (Let\'s Encrypt) موقتاً برای این دامنه سهمیه‌اش تمام شده. چند ساعت یا تا یک هفتهٔ دیگر دوباره «بررسی و وصل کردن» را بزن. سایت تا آن موقع بدون قفل (http) کار می‌کند.'
    if 'nxdomain' in low or 'no valid a records' in low or 'dns problem' in low or 'servfail' in low:
        return 'صادرکنندهٔ گواهی هنوز رکوردِ DNS را نمی‌بیند. کمی صبر کن تا تغییرت پخش شود و دوباره «بررسی و وصل کردن» را بزن. سایت تا آن موقع بدون قفل (http) کار می‌کند.'
    if 'caa' in low:
        return 'رکوردِ CAA ِ دامنه‌ات به Let\'s Encrypt اجازهٔ صدورِ گواهی نمی‌دهد. رکوردِ CAA را پاک کن یا letsencrypt.org را به آن اضافه کن و دوباره بزن.'
    if 'timeout' in low or 'connection' in low or 'unauthorized' in low or 'invalid response' in low or '404' in low:
        return 'صادرکنندهٔ گواهی نتوانست از بیرون به این دامنه برسد. مطمئن شو رکوردِ A دقیقاً به این سرور اشاره می‌کند و چیزی (مثلِ کلادفلر) جلویش نیست، بعد دوباره «بررسی و وصل کردن» را بزن. ممکن است دسترسیِ سرورهای خارج از ایران به این سرور هم موقتاً قطع شده باشد. سایت تا آن موقع بدون قفل (http) کار می‌کند.'
    return 'گواهی گرفته نشد. چند دقیقه بعد دوباره «بررسی و وصل کردن» را بزن. سایت تا آن موقع بدون قفل (http) کار می‌کند.'
