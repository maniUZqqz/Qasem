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
                   '.nb-hero.nbv-aurora{background:linear-gradient(rgba(5,8,20,.2),rgba(5,8,20,.2)),radial-gradient(55% 60% at 15% 20%,color-mix(in srgb,var(--brand) 55%,#0b1020) 0,transparent 60%),'
                   'radial-gradient(50% 55% at 85% 15%,#0e7490 0,transparent 60%),radial-gradient(60% 60% at 70% 100%,#9d174d 0,transparent 60%),'
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
        'orb': ('ابتدای‌خط با هالهٔ تزئینی',
                '.nb-hero.nbv-orb{position:relative;overflow:hidden}'
                '.nb-hero.nbv-orb .nb-hero-copy.is-center{text-align:start;margin-inline:0;max-width:680px;position:relative;z-index:1}'
                '.nb-hero.nbv-orb .nb-hero-copy.is-center .nb-actions{justify-content:flex-start}'
                '.nb-hero.nbv-orb::after{content:"";position:absolute;inset-block:14%;inset-inline-end:5%;width:min(32vw,360px);aspect-ratio:1;border-radius:50%;'
                'background:radial-gradient(circle at 32% 30%,rgba(255,255,255,.34),rgba(255,255,255,.06) 62%,transparent 72%);border:1px solid rgba(255,255,255,.3);pointer-events:none}'
                '@media (max-width:860px){.nb-hero.nbv-orb::after{display:none}}'),
        'card': ('کارتِ روشن روی زمینهٔ هیرو',
                 '.nb-hero.nbv-card .nb-hero-copy.is-center{background:var(--card,#fff);color:var(--ink,#111827);border-radius:calc(var(--r,16px) + 8px);'
                 'padding:clamp(24px,5vw,56px);box-shadow:0 30px 70px -34px rgba(0,0,0,.55);max-width:820px}'
                 '.nb-hero.nbv-card .nb-hero-title{color:var(--ink,#111827)}.nb-hero.nbv-card .nb-sub{color:var(--ink-2,#374151)}'
                 '.nb-hero.nbv-card .nb-eyebrow{color:var(--brand-fg,var(--brand))}'
                 '.nb-hero.nbv-card .nb-btn.is-filled{background:var(--brand);color:var(--brand-ink,#fff);box-shadow:none}'
                 '.nb-hero.nbv-card .nb-btn.is-ghost{color:var(--ink,#111827);border-color:var(--line,#e5e7eb)}'),
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


# ───────────────────────────── چیدمانِ «قطعه‌های آماده» (c_*)
# بازبینیِ دورِ ۴: چیدمان‌های بالا فقط به بلوکِ پایهٔ «hero/faq/cta/…» می‌رسید؛ صفحهٔ واقعیِ چغر از قطعه‌های آماده (c_hero_center_glow، c_cta_center_box، c_faq_two_col) ساخته شده
# و با هر ۸۹ سبک سربرگ همیشه وسط‌چین می‌ماند. این‌جا همان کلیدهای چیدمان برای این قطعه‌ها هم هست (CSSِ جدا چون HTMLِ قطعه فرق دارد)؛ «چیدمانِ بخش‌ها هم جور شود»
# از ستونِ ``sections`` ِ همان سبکِ بلوکِ پایه (hero → c_hero_*) می‌خواند.
PART_BASE = {'c_hero_center_glow': 'hero', 'c_hero_stats_bar': 'hero', 'c_cta_center_box': 'cta', 'c_faq_two_col': 'faq', 'c_faq_cards_grid': 'faq'}

_HERO_PART = {
    'framed': ('متن در قابِ شیشه‌ای',
               '@R@.nbv-framed @W@{background:color-mix(in srgb,var(--card,#fff) 58%,transparent);border:1px solid var(--line);border-radius:calc(var(--r,16px) + 10px);'
               'padding:clamp(24px,5vw,52px);-webkit-backdrop-filter:blur(14px);backdrop-filter:blur(14px);box-shadow:0 24px 60px -28px rgba(0,0,0,.35)}'),
    'aurora': ('شفق (گرادیانِ تیره)',
               '@R@.nbv-aurora{background:linear-gradient(rgba(5,8,20,.2),rgba(5,8,20,.2)),radial-gradient(55% 60% at 15% 20%,color-mix(in srgb,var(--brand) 55%,#0b1020) 0,transparent 60%),'
               'radial-gradient(50% 55% at 85% 15%,#0e7490 0,transparent 60%),radial-gradient(60% 60% at 70% 100%,#9d174d 0,transparent 60%),color-mix(in srgb,var(--brand) 40%,#0b1020);color:#fff}'
               '@R@.nbv-aurora::before{display:none}'
               '@R@.nbv-aurora .nbc-title,@R@.nbv-aurora .nbc-lead,@R@.nbv-aurora .nbc-muted,@R@.nbv-aurora .nbc-kicker{color:#fff}'
               '@R@.nbv-aurora .nbc-lead{opacity:.92}@R@.nbv-aurora .nbc-pill{background:rgba(255,255,255,.16);color:#fff}'
               '@R@.nbv-aurora .nbc-btn{background:#fff;color:#0b1020;border-color:transparent;box-shadow:none}'
               '@R@.nbv-aurora .nbc-btn.is-alt{background:transparent;color:#fff;border-color:rgba(255,255,255,.6)}'
               '@R@.nbv-aurora .nbc-hsb-stats{border-top-color:rgba(255,255,255,.3)}@R@.nbv-aurora .nbc-hsb-stats b,@R@.nbv-aurora .nbc-hsb-stats span{color:#fff}'),
    'start': ('تیترِ درشت و ابتدای‌خط',
              '@R@.nbv-start @W@{text-align:start;margin-inline:0;max-width:900px}'
              '@R@.nbv-start @W@ .nbc-lead{margin-inline:0}@R@.nbv-start @W@ .nbc-btns{justify-content:flex-start}'
              '@R@.nbv-start .nbc-title{font-size:clamp(2.4rem,6.4vw,4.6rem);line-height:1.12}'),
    'band': ('نوارِ رنگیِ تخت',
             '@R@.nbv-band{background:var(--brand);color:var(--brand-ink,#fff);border-block:4px solid currentColor}@R@.nbv-band::before{display:none}'
             '@R@.nbv-band .nbc-title,@R@.nbv-band .nbc-lead,@R@.nbv-band .nbc-muted,@R@.nbv-band .nbc-kicker,@R@.nbv-band .nbc-hsb-stats b,@R@.nbv-band .nbc-hsb-stats span{color:inherit}'
             '@R@.nbv-band .nbc-title{font-size:clamp(2.4rem,7vw,5rem);line-height:1.1}'
             '@R@.nbv-band .nbc-btn{background:var(--brand-ink,#fff);color:var(--brand);box-shadow:none}'
             '@R@.nbv-band .nbc-btn.is-alt{background:transparent;color:inherit;border-color:currentColor}'
             '@R@.nbv-band .nbc-pill{background:transparent;color:inherit;box-shadow:inset 0 0 0 1px currentColor}@R@.nbv-band .nbc-hsb-stats{border-top-color:currentColor}'),
    'minimal': ('مینیمال و بی‌زمینه',
                '@R@.nbv-minimal{background:transparent;color:var(--ink);padding-block:clamp(72px,11vw,150px)}@R@.nbv-minimal::before{display:none}'
                '@R@.nbv-minimal .nbc-pill{background:transparent;padding-inline:0}'),
    'orb': ('ابتدای‌خط با هالهٔ تزئینی',
            '@R@.nbv-orb{overflow:hidden}'
            '@R@.nbv-orb @W@{text-align:start;margin-inline:0;max-width:680px}'
            '@R@.nbv-orb @W@ .nbc-lead{margin-inline:0}@R@.nbv-orb @W@ .nbc-btns{justify-content:flex-start}'
            '@R@.nbv-orb::after{content:"";position:absolute;inset-block:14%;inset-inline-end:5%;width:min(32vw,360px);aspect-ratio:1;border-radius:50%;'
            'background:radial-gradient(circle at 32% 30%,color-mix(in srgb,var(--brand) 28%,transparent),transparent 70%);border:1px solid color-mix(in srgb,var(--brand) 34%,transparent);pointer-events:none}'
            '@media (max-width:860px){@R@.nbv-orb::after{display:none}}'),
    'card': ('کارتِ روشن روی زمینهٔ هیرو',
             '@R@.nbv-card @W@{background:var(--card,#fff);color:var(--ink,#111827);border:var(--st-card-bd,1px solid var(--line));border-radius:calc(var(--r,16px) + 8px);'
             'padding:clamp(24px,5vw,56px);box-shadow:0 30px 70px -34px rgba(0,0,0,.55);max-width:820px}'),
}


def _part_css(table, root, wrap):
    """قالبِ CSS (با «@R@» = کلاسِ ریشهٔ قطعه و «@W@» = پوشهٔ متن) ⇒ {کلید: (برچسب، CSS)}."""
    return {k: (label, css.replace('@R@', root).replace('@W@', wrap)) for k, (label, css) in table.items()}


VARIANTS['c_hero_center_glow'] = ('nbc-hero-center-glow', _part_css(_HERO_PART, '.nbc-hero-center-glow', '.nbc-hcg'))
VARIANTS['c_hero_stats_bar'] = ('nbc-hero-stats-bar', _part_css(_HERO_PART, '.nbc-hero-stats-bar', '.nbc-hsb'))
VARIANTS['c_cta_center_box'] = ('nbc-cta-center-box', {
    'split': ('متن و دکمه کنارِ هم',
              '.nbc-cta-center-box.nbv-split .nbc-cb{display:grid;grid-template-columns:minmax(0,1fr) auto;align-items:center;text-align:start;gap:6px 40px}'
              '.nbc-cta-center-box.nbv-split .nbc-cb .nbc-title,.nbc-cta-center-box.nbv-split .nbc-cb .nbc-lead{grid-column:1;margin:0}'
              '.nbc-cta-center-box.nbv-split .nbc-cb .nbc-btns{grid-column:2;grid-row:1/span 2;margin-top:0;justify-content:flex-start}'
              '@media (max-width:760px){.nbc-cta-center-box.nbv-split .nbc-cb{grid-template-columns:minmax(0,1fr);text-align:center}'
              '.nbc-cta-center-box.nbv-split .nbc-cb .nbc-btns{grid-column:1;grid-row:auto;margin-top:18px;justify-content:center}}'),
    'outline': ('فقط حاشیه',
                '.nbc-cta-center-box.nbv-outline .nbc-cb{background:transparent;color:var(--ink);border:2px solid var(--ink);box-shadow:none}'
                '.nbc-cta-center-box.nbv-outline .nbc-btn.is-light{background:var(--brand);color:var(--brand-ink,#fff)}'
                '.nbc-cta-center-box.nbv-outline .nbc-btn.is-ghost{color:var(--ink)}'),
    'bar': ('نوارِ تمام‌عرض',
            '.nbc-cta-center-box.nbv-bar{padding-block:0}.nbc-cta-center-box.nbv-bar>.nb-wrap{max-width:none;padding-inline:0}'
            '.nbc-cta-center-box.nbv-bar .nbc-cb{border-radius:0;padding-inline:20px}'),
})
_FAQ_PART = {
    'plain': ('خطی',
              '@R@.nbv-plain @I@{background:transparent;border:0;border-block-end:1px solid var(--line);border-radius:0;box-shadow:none;padding-inline:0;'
              '-webkit-backdrop-filter:none;backdrop-filter:none}'),
    'boxed': ('قاب‌دار',
              '@R@.nbv-boxed @I@{border-width:1.5px;box-shadow:0 8px 24px -18px rgba(0,0,0,.3)}'),
    'columns': ('ستون‌بندیِ دیگر', '@C@'),
}
VARIANTS['c_faq_two_col'] = ('nbc-faq-two-col', {k: (lab, css.replace('@R@', '.nbc-faq-two-col').replace('@I@', '.nbc-fq-i').replace(
    '@C@', '.nbc-faq-two-col.nbv-columns .nbc-fq.nbc-split{grid-template-columns:minmax(0,1fr)}'
           '.nbc-faq-two-col.nbv-columns .nbc-fq-list{grid-template-columns:repeat(2,minmax(0,1fr));align-items:start;gap:14px}'
           '@media (max-width:760px){.nbc-faq-two-col.nbv-columns .nbc-fq-list{grid-template-columns:minmax(0,1fr)}}')) for k, (lab, css) in _FAQ_PART.items()})
VARIANTS['c_faq_cards_grid'] = ('nbc-faq-cards-grid', {k: (lab, css.replace('@R@', '.nbc-faq-cards-grid').replace('@I@', '.nbc-fg-i').replace(
    '@C@', '.nbc-faq-cards-grid.nbv-columns .nbc-fg{grid-template-columns:repeat(3,minmax(0,1fr))}'
           '@media (max-width:1024px){.nbc-faq-cards-grid.nbv-columns .nbc-fg{grid-template-columns:repeat(2,minmax(0,1fr))}}'
           '@media (max-width:640px){.nbc-faq-cards-grid.nbv-columns .nbc-fg{grid-template-columns:minmax(0,1fr)}}')) for k, (lab, css) in _FAQ_PART.items()})


def base_of(btype):
    """نوعِ بلوک ⇒ بلوکِ پایه که ستونِ ``sections`` ِ سبک برایش نوشته شده (c_hero_center_glow ⇒ hero)."""
    return PART_BASE.get(btype, btype)


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


__all__ = ['VARIANTS', 'PART_BASE', 'base_of', 'has_field', 'has', 'options', 'css_for', 'root_class', 'label_of']
