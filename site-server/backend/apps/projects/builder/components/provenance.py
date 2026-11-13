# -*- coding: utf-8 -*-
"""مبدأ و مجوزِ هر قطعهٔ آماده — برای هر قطعه روشن است از کجا آمده و با چه مجوزی می‌شود به‌کارش برد.

دو دسته داریم، و هیچ‌کدام ادعای بیش از واقعیت نمی‌کند:

· **adapted** — از یک قطعهٔ منتشرشده در 21st.dev که مجوزِ آن در صفحهٔ 21st.dev «mit» نوشته شده. 21st.dev کدِ ریجیستری (`/r/<نویسنده>/<قطعه>`)
  را فقط با کلیدِ API می‌دهد (بی‌کلید `403 authentication_required`، رایگان: ۲ بازیابی در روز)؛ پس کد را از مخزنِ عمومیِ همان نویسنده
  (که مجوزش MIT است) در GitHub خوانده‌ایم — همان فایلی که در 21st.dev هم هست — و ساختار و ظاهرش را به HTML/CSSِ سمتِ سرورِ سایت‌ساز و راست‌به‌چپ
  بازنویسی کرده‌ایم (React، Tailwind و framer-motion حذف شده؛ فقط CSS). مجوزِ MIT می‌خواهد اعلامِ حقِ نشر بماند؛ این‌جا و در
  `dataset/LICENSE-*.txt` مانده است.
· **original** — طراحیِ خودمان بر اساسِ الگوهای رایجِ صفحهٔ فرود؛ هیچ کدی از شخصِ ثالث ندارد. `pattern_ref` فقط نشان می‌دهد این الگو در 21st.dev
  زیرِ کدام دسته دیده می‌شود (برای مقایسه)، نه این‌که چیزی از آن‌جا برداشته شده باشد.

داده‌های «listing» (نویسنده، کتابخانه، مجوز) را import_sources.py از صفحهٔ عمومیِ `.md` ِ هر قطعه در 21st.dev خوانده و در dataset/sources_checked.json گذاشته؛
آزمون (tests_styles) سنجیده که هر قطعهٔ adapted مجوزِ مجاز دارد و حقِ نشر در متنِ مجوز هست.
"""

# مجوزهایی که اجازهٔ استفادهٔ دوباره و بازنویسی می‌دهند و می‌شود با «اعلامِ حقِ نشر» به‌کارشان برد
PERMISSIVE = {'MIT', 'Apache-2.0', 'BSD-3-Clause', 'BSD-2-Clause', 'ISC', '0BSD', 'Unlicense', 'CC0-1.0'}

LIBRARIES = {
    'magicui': {
        'name': 'Magic UI', 'author': 'Dillion Verma', 'license': 'MIT', 'copyright': 'Copyright (c) Magic UI',
        'repo': 'https://github.com/magicuidesign/magicui', 'commit': 'a4dcb912073c0ff45654c943c16e131360405c11',
        'license_file': 'dataset/LICENSE-magicui.txt', 'listing': 'https://21st.dev/@dillionverma/library/magic-ui',
        'author_page': 'https://21st.dev/@dillionverma',
    },
}


def adapted(lib, source_path, listing_slug='', note=''):
    """قطعهٔ بازنویسی‌شده از یک کتابخانهٔ MIT. listing_slug: نامِ قطعه در 21st.dev (اگر آن‌جا هست)."""
    L = LIBRARIES[lib]
    return {
        'origin': 'adapted', 'library': L['name'], 'author': L['author'], 'license': L['license'], 'copyright': L['copyright'],
        'source_url': '%s/blob/%s/%s' % (L['repo'], L['commit'], source_path), 'commit': L['commit'], 'license_file': L['license_file'],
        'listing_url': ('https://21st.dev/@dillionverma/components/%s' % listing_slug) if listing_slug else '',
        'registry_url': ('https://21st.dev/r/dillionverma/%s' % listing_slug) if listing_slug else '',
        'registry_note': 'کدِ ریجیستری فقط با کلیدِ API می‌آید؛ کد از مخزنِ MIT خودِ نویسنده خوانده شد.' if listing_slug else '',
        'note': note,
    }


# الگوهای دسته در 21st.dev (فقط برای مقایسه؛ کدی از آن‌ها برنداشته‌ایم)
PATTERN_REF = {
    'hero': 'https://21st.dev/community/components/s/hero', 'features': 'https://21st.dev/community/components/s/features',
    'pricing': 'https://21st.dev/community/components/s/pricing-section', 'testimonials': 'https://21st.dev/community/components/s/testimonials',
    'cta': 'https://21st.dev/community/components/s/cta', 'footer': 'https://21st.dev/community/components/s/footer',
    'navbar': 'https://21st.dev/community/components/s/navigation', 'cards': 'https://21st.dev/community/components/s/card',
    'gallery': 'https://21st.dev/community/components/s/marquee', 'faq': 'https://21st.dev/community/components/s/accordion',
    'steps': 'https://21st.dev/community/components/s/landing-page',
}


def original(cat):
    return {'origin': 'original', 'library': '', 'author': 'سایت‌ساز NM', 'license': 'طراحیِ خودمان (بی‌کدِ شخصِ ثالث)',
            'source_url': '', 'pattern_ref': PATTERN_REF.get(cat, ''), 'note': 'الگوی رایجِ صفحهٔ فرود؛ نوشتهٔ خودمان برای رندرِ سمتِ سرور و راست‌به‌چپ.'}


def src_of(comp):
    """مبدأ یک قطعه؛ بی‌src ⇒ original."""
    return comp.get('src') or original(comp['cat'])


def public(src):
    """آنچه به پنل می‌رود: کوتاه و بی‌حشو."""
    keys = ('origin', 'library', 'author', 'license', 'copyright', 'source_url', 'listing_url', 'pattern_ref')
    return {k: src.get(k, '') for k in keys}
