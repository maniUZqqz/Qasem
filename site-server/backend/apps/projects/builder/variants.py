# -*- coding: utf-8 -*-
"""چیدمانِ بخش‌ها (section variants): هر بلوکِ آماده می‌تواند چند چیدمانِ دیگر هم داشته باشد.

· انتخاب در تنظیماتِ بلوک («چیدمانِ بخش») یا خودکار با «اعمالِ سبک روی صفحه».
· فقط یک کلاسِ `nbv-<کلید>` به بلوک اضافه می‌شود و CSSِ همان چیدمان همراهِ صفحه می‌آید؛ ساختارِ HTML و متن‌ها همان می‌مانند،
  پس ویرایشِ درجا، بازگشتِ AI (importer) و بقیهٔ رفتارها عوض نمی‌شوند.
· بلوکی که چیدمانِ ویژه ندارد (variant خالی) خروجی‌اش بایت‌به‌بایت همان قبلی است.
· CSS فقط برای چیدمان‌هایی که واقعاً در صفحه به‌کار رفته‌اند نوشته می‌شود (Renderer.use_variant).
"""

# کلید: بلوک ⇒ (کلاسِ ریشه برای انتخابگر، {کلیدِ چیدمان: (برچسب، CSS)})
VARIANTS = {
    'hero': ('nb-hero', {
        'framed': ('متن در قابِ شیشه‌ای',
                   '.nb-hero.nbv-framed .nb-hero-copy{background:rgba(255,255,255,.14);border:1px solid rgba(255,255,255,.38);border-radius:calc(var(--r,16px) + 10px);'
                   'padding:clamp(24px,5vw,52px);-webkit-backdrop-filter:blur(14px);backdrop-filter:blur(14px);box-shadow:0 24px 60px -28px rgba(0,0,0,.45)}'),
        'aurora': ('شفق (گرادیانِ متحرک)',
                   '.nb-hero.nbv-aurora{background:radial-gradient(55% 60% at 15% 20%,color-mix(in srgb,var(--brand) 70%,#fff) 0,transparent 60%),'
                   'radial-gradient(50% 55% at 85% 15%,#22d3ee 0,transparent 60%),radial-gradient(60% 60% at 70% 100%,#f472b6 0,transparent 60%),'
                   'color-mix(in srgb,var(--brand) 40%,#0b1020);background-size:140% 140%;animation:nbv-aurora 14s ease-in-out infinite alternate;color:#fff}'
                   '@keyframes nbv-aurora{from{background-position:0 0}to{background-position:100% 100%}}'
                   '@media (prefers-reduced-motion:reduce){.nb-hero.nbv-aurora{animation:none}}'),
        'start': ('تیترِ درشت و ابتدای‌خط',
                  '.nb-hero.nbv-start .nb-hero-copy.is-center{text-align:start;margin-inline:0;max-width:900px}'
                  '.nb-hero.nbv-start .nb-hero-copy.is-center .nb-actions{justify-content:flex-start}'
                  '.nb-hero.nbv-start .nb-hero-title{font-size:clamp(2.4rem,6.4vw,4.6rem);line-height:1.12}'),
        'band': ('نوارِ رنگیِ تخت',
                 '.nb-hero.nbv-band{background:var(--brand);color:var(--brand-ink,#fff);border-block:4px solid currentColor}'
                 '.nb-hero.nbv-band .nb-hero-title{font-size:clamp(2.4rem,7vw,5rem);line-height:1.1}'
                 '.nb-hero.nbv-band .nb-btn.is-filled{background:var(--brand-ink,#fff);color:var(--brand)}'),
        'minimal': ('مینیمال و بی‌زمینه',
                    '.nb-hero.nbv-minimal{background:transparent;color:var(--ink);padding-block:clamp(72px,11vw,150px)}'
                    '.nb-hero.nbv-minimal .nb-btn.is-filled{background:var(--brand);color:var(--brand-ink,#fff)}'
                    '.nb-hero.nbv-minimal .nb-btn.is-ghost{color:var(--ink)}.nb-hero.nbv-minimal .nb-eyebrow{color:var(--ink-2)}'),
    }),
    'features': ('nb-features', {
        'bento': ('بنتو (کاشیِ نامساوی)',
                  '.nb-features.nbv-bento .nb-grid{grid-template-columns:repeat(3,minmax(0,1fr));grid-auto-flow:dense;grid-auto-rows:minmax(150px,auto)}'
                  '.nb-features.nbv-bento .nb-feature:nth-child(1){grid-column:span 2;grid-row:span 2;padding:30px}'
                  '.nb-features.nbv-bento .nb-feature:nth-child(1) .nb-feature-title{font-size:1.5rem}'
                  '.nb-features.nbv-bento .nb-feature:first-child:nth-last-child(2){grid-row:auto}'
                  '.nb-features.nbv-bento .nb-feature:nth-child(4):last-child{grid-column:1/-1}'
                  '.nb-features.nbv-bento .nb-feature:nth-child(5):last-child{grid-column:span 2}'
                  '@media (max-width:1024px){.nb-features.nbv-bento .nb-grid{grid-template-columns:repeat(2,minmax(0,1fr))}'
                  '.nb-features.nbv-bento .nb-feature:nth-child(1){grid-column:1/-1;grid-row:auto}'
                  '.nb-features.nbv-bento .nb-feature:nth-child(4):last-child,.nb-features.nbv-bento .nb-feature:nth-child(5):last-child{grid-column:auto}}'
                  '@media (max-width:640px){.nb-features.nbv-bento .nb-grid{grid-template-columns:minmax(0,1fr)}}'),
        'list': ('فهرستِ ردیفی',
                 '.nb-features.nbv-list .nb-grid{grid-template-columns:minmax(0,1fr);gap:0;max-width:820px;margin-inline:auto}'
                 '.nb-features.nbv-list .nb-feature{display:grid;grid-template-columns:auto 1fr;column-gap:20px;align-items:center;background:transparent;border:0;'
                 'border-block-end:1px solid var(--line);border-radius:0;box-shadow:none;padding:20px 4px;-webkit-backdrop-filter:none;backdrop-filter:none}'
                 '.nb-features.nbv-list .nb-feature-icon{grid-row:span 2;margin:0}'
                 '.nb-features.nbv-list .nb-feature:hover{transform:none;box-shadow:none}'),
        'numbered': ('شماره‌دار',
                     '.nb-features.nbv-numbered .nb-grid{counter-reset:nbf}'
                     '.nb-features.nbv-numbered .nb-feature{counter-increment:nbf;position:relative;padding-top:58px}'
                     '.nb-features.nbv-numbered .nb-feature::before{content:"۰" counter(nbf,persian);position:absolute;inset-block-start:16px;inset-inline-start:24px;'
                     'font-weight:800;font-size:1.5rem;color:var(--brand);line-height:1}'
                     '.nb-features.nbv-numbered .nb-feature-icon{display:none}'),
        'plain': ('بی‌قاب و وسط‌چین',
                  '.nb-features.nbv-plain .nb-feature{background:transparent;border:0;box-shadow:none;text-align:center;-webkit-backdrop-filter:none;backdrop-filter:none}'
                  '.nb-features.nbv-plain .nb-feature-icon{width:64px;height:64px;margin-inline:auto}'
                  '.nb-features.nbv-plain .nb-feature:hover{transform:none;box-shadow:none}'),
    }),
    'pricing': ('nb-pricing', {
        'flat': ('تخت و ساده',
                 '.nb-pricing.nbv-flat .nb-plan{box-shadow:none;background:transparent}'
                 '.nb-pricing.nbv-flat .nb-plan.is-featured{background:var(--card);transform:none}'),
        'bold': ('ضخیم با سایهٔ سخت',
                 '.nb-pricing.nbv-bold .nb-plan{border:3px solid var(--ink);box-shadow:6px 6px 0 var(--ink)}'
                 '.nb-pricing.nbv-bold .nb-plan.is-featured{background:color-mix(in srgb,var(--brand) 16%,var(--card));transform:translate(-3px,-3px);box-shadow:9px 9px 0 var(--ink)}'),
        'glow': ('درخشانِ پیشنهادِ ویژه',
                 '.nb-pricing.nbv-glow .nb-plan.is-featured{box-shadow:0 0 0 1px var(--brand),0 24px 70px -20px var(--brand);'
                 'background:linear-gradient(180deg,color-mix(in srgb,var(--brand) 10%,var(--card)),var(--card))}'),
    }),
    'testimonials': ('nb-testimonials', {
        'marked': ('با نشانِ نقل‌قول',
                   '.nb-testimonials.nbv-marked .nb-quote{position:relative;padding-top:50px}'
                   '.nb-testimonials.nbv-marked .nb-quote::before{content:"”";position:absolute;inset-block-start:4px;inset-inline-start:22px;font-size:4.8rem;line-height:1;'
                   'color:var(--brand);opacity:.4;font-family:Georgia,serif}'),
        'big': ('نقلِ بزرگ',
                '.nb-testimonials.nbv-big .nb-grid{grid-template-columns:minmax(0,1fr);max-width:820px;margin-inline:auto}'
                '.nb-testimonials.nbv-big .nb-quote{background:transparent;border:0;border-top:1px solid var(--line);box-shadow:none;border-radius:0;padding:28px 0;'
                'text-align:center;align-items:center;-webkit-backdrop-filter:none;backdrop-filter:none}'
                '.nb-testimonials.nbv-big .nb-quote blockquote{font-size:clamp(1.2rem,2.7vw,1.7rem);line-height:1.85;font-family:var(--nb-font-head,inherit)}'),
        'plain': ('ساده با خطِ بالا',
                  '.nb-testimonials.nbv-plain .nb-quote{background:transparent;border:0;border-top:2px solid var(--ink);box-shadow:none;border-radius:0;padding-inline:0;'
                  '-webkit-backdrop-filter:none;backdrop-filter:none}'),
    }),
    'faq': ('nb-faq', {
        'plain': ('خطی',
                  '.nb-faq.nbv-plain .nb-faq-item{background:transparent;border:0;border-block-end:1px solid var(--line);border-radius:0;box-shadow:none;padding-inline:0;'
                  '-webkit-backdrop-filter:none;backdrop-filter:none}'),
        'boxed': ('قاب‌دار',
                  '.nb-faq.nbv-boxed .nb-faq-item{border-width:1.5px;padding:6px 22px;box-shadow:0 8px 24px -18px rgba(0,0,0,.3)}'),
        'columns': ('دو ستونه',
                    '.nb-faq.nbv-columns .nb-faq-list{max-width:none;grid-template-columns:repeat(2,minmax(0,1fr));align-items:start;gap:14px}'
                    '@media (max-width:760px){.nb-faq.nbv-columns .nb-faq-list{grid-template-columns:minmax(0,1fr)}}'),
    }),
    'cta': ('nb-cta', {
        'split': ('متن و دکمه کنارِ هم',
                  '.nb-cta.nbv-split .nb-cta-box{display:grid;grid-template-columns:minmax(0,1fr) auto;align-items:center;text-align:start;gap:6px 40px}'
                  '.nb-cta.nbv-split .nb-cta-box .nb-title,.nb-cta.nbv-split .nb-cta-box .nb-sub{grid-column:1;margin:0}'
                  '.nb-cta.nbv-split .nb-cta-box .nb-actions{grid-column:2;grid-row:1/span 2;margin-top:0}'
                  '@media (max-width:760px){.nb-cta.nbv-split .nb-cta-box{grid-template-columns:minmax(0,1fr);text-align:center}'
                  '.nb-cta.nbv-split .nb-cta-box .nb-actions{grid-column:1;grid-row:auto;margin-top:18px}}'),
        'outline': ('فقط حاشیه',
                    '.nb-cta.nbv-outline .nb-cta-box{background:transparent;color:var(--ink);border:2px solid var(--ink);box-shadow:none;-webkit-backdrop-filter:none;backdrop-filter:none}'
                    '.nb-cta.nbv-outline .nb-btn.is-ghost{background:var(--brand);color:var(--brand-ink,#fff);border-color:var(--brand)}'),
        'bar': ('نوارِ تمام‌عرض',
                '.nb-cta.nbv-bar{padding-block:0}.nb-cta.nbv-bar>.nb-wrap{max-width:none;padding-inline:0}'
                '.nb-cta.nbv-bar .nb-cta-box{border-radius:0;padding-inline:20px}'),
    }),
    'site_header': ('nb-header', {
        'floating': ('شناور و گرد',
                     '.nb-header.nbv-floating{margin:12px auto 0;width:min(calc(100% - 24px),var(--nb-width,1140px));border:1px solid var(--line);border-radius:999px;'
                     'top:12px;box-shadow:0 14px 40px -20px rgba(0,0,0,.4)}'
                     '.nb-header.nbv-floating .nb-header-in{min-height:58px;padding-inline:18px}'
                     '@media (max-width:760px){.nb-header.nbv-floating{border-radius:22px}}'),
        'centered': ('لوگو در وسط',
                     '.nb-header.nbv-centered .nb-header-in{justify-content:center;flex-direction:column;gap:8px;padding-block:16px}'
                     '.nb-header.nbv-centered .nb-header-extra{margin-inline-start:0}.nb-header.nbv-centered .nb-brand{font-size:1.7rem}'
                     '.nb-header.nbv-centered .nb-nav{justify-content:center}'),
        'minimal': ('شفاف و ساده',
                    '.nb-header.nbv-minimal{background:transparent;border-bottom:0;box-shadow:none;-webkit-backdrop-filter:none;backdrop-filter:none}'),
    }),
}

LABEL = '«چیدمانِ بخش»'


def has_field(btype):
    return btype in VARIANTS


def has(btype, key):
    return bool(key) and btype in VARIANTS and key in VARIANTS[btype][1]


def options(btype):
    """گزینه‌های select برای فرمِ تنظیماتِ بلوک؛ اولی «پیش‌فرض» است."""
    rows = [{'value': '', 'label': 'پیش‌فرض'}]
    rows += [{'value': k, 'label': v[0]} for k, v in VARIANTS[btype][1].items()]
    return rows


def css_for(btype, key):
    return VARIANTS[btype][1][key][1] if has(btype, key) else ''


def root_class(btype):
    return VARIANTS[btype][0]


def label_of(btype, key):
    return VARIANTS[btype][1][key][0] if has(btype, key) else ''


def used_in_html(html):
    """⇒ [(بلوک، کلید)] چیدمان‌هایی که در کلاس‌های یک HTML به‌کار رفته‌اند (برای ضمیمهٔ CSS پس از کارِ AI)."""
    import re
    found = []
    for m in re.finditer(r'class="([^"]*)"', html or ''):
        tokens = m.group(1).split()
        for btype, (root, rows) in VARIANTS.items():
            if root not in tokens:
                continue
            for t in tokens:
                if t.startswith('nbv-') and t[4:] in rows and (btype, t[4:]) not in found:
                    found.append((btype, t[4:]))
    return found


__all__ = ['VARIANTS', 'has_field', 'has', 'options', 'css_for', 'root_class', 'label_of']
