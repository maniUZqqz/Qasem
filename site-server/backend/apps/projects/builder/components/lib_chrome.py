# -*- coding: utf-8 -*-
"""سربرگ‌های سایت (۴ قطعه، فقط در «سربرگ») و پابرگ‌ها (۴ قطعه، فقط در «پابرگ»).

منوی سایت و نامِ سایت از خودِ پروژه می‌آیند ([[MENU]] و [[TITLE]]) پس با افزودنِ صفحه، منو خودکار به‌روز می‌شود.
سربرگ‌ها همان کلاس‌های `nb-header` و `nb-nav` و دکمهٔ همبرگریِ بی‌جاوااسکریپتِ سربرگِ قبلی را دارند؛ در گوشی منو با یک تیک باز می‌شود.
"""
from .spec import A, C, IM, L, SEL, T, TG

_NAV_BRAND = ("""<a class="nb-brand" href="/"><!--if:logo--><img class="nb-logo" data-i="logo" data-alt="logo_alt"><!--/if--><span>[[TITLE]]</span></a>""")
_NAV_MENU = ("""<input class="nb-nav-toggle" type="checkbox" id="nb-nav-[[ID]]" aria-label="باز و بسته کردنِ منو"><label class="nb-burger" for="nb-nav-[[ID]]" aria-hidden="true"><i></i><i></i><i></i></label>"""
             """<nav class="nb-nav" aria-label="منوی اصلی">[[MENU]]</nav>""")
_NAV_BTN = """<div class="nb-header-extra"><a class="nb-btn is-filled is-sm" data-s="btn" data-h="btn_link"></a></div>"""
_NAV_SLOTS = [IM('logo', 'نشان (لوگو)'), T('logo_alt', 'توضیحِ نشان', ''), T('btn', 'دکمهٔ کنارِ منو', 'تماس با ما'), L('btn_link', 'پیوندِ دکمه'),
              TG('sticky', 'هنگامِ پایین‌رفتن بالای صفحه بماند', True)]
_NAV_IN = '<div class="nb-wrap nb-header-in">' + _NAV_BRAND + _NAV_MENU + _NAV_BTN + '</div>'

_FT_SLOTS = [T('copy', 'نوشتهٔ پایانی', 'همهٔ حقوق محفوظ است.')]
_FT_COPY = """<p class="nbc-fc-copy">© [[TITLE]]<!--if:copy--> — <span data-s="copy"></span><!--/if--></p>"""

SPECS = [
    # ─────────────── سربرگ‌ها
    C('nav_classic', 'navbar', 'سربرگِ ساده', 'نشان در یک سو، منو وسط و یک دکمه در سوی دیگر؛ در گوشی با همبرگر',
      _NAV_SLOTS, _NAV_IN,
      """.nbc-nav-classic .nb-header-in{min-height:70px}.nbc-nav-classic .nb-brand{font-family:var(--nb-font-head,inherit)}
.nbc-nav-classic .nb-nav{margin-inline-start:12px}""",
      'سربرگ منو هدر ناوبار ساده', 'corporate-clean minimalism bento-grid swiss', root='header'),

    C('nav_centered_logo', 'navbar', 'سربرگِ نشانِ وسط', 'نشان یا نام در وسط و منو زیرِ آن؛ برای برندهای باوقار',
      [IM('logo', 'نشان (لوگو)'), T('logo_alt', 'توضیحِ نشان', ''), TG('sticky', 'هنگامِ پایین‌رفتن بالای صفحه بماند', False)],
      '<div class="nb-wrap nb-header-in">' + _NAV_BRAND + _NAV_MENU + '</div>',
      """.nbc-nav-centered-logo .nb-header-in{flex-direction:column;justify-content:center;gap:6px;padding-block:18px}
.nbc-nav-centered-logo .nb-brand{font-family:var(--nb-font-head,inherit);font-size:1.8rem}.nbc-nav-centered-logo .nb-nav{justify-content:center}
.nbc-nav-centered-logo{border-bottom:var(--st-hd-bd,1px solid var(--line))}
@media (max-width:760px){.nbc-nav-centered-logo .nb-header-in{flex-direction:row;justify-content:space-between}}""",
      'سربرگ منو هدر نشان وسط مجله ای', 'editorial dark-luxury minimalism organic swiss', root='header'),

    C('nav_floating_pill', 'navbar', 'سربرگِ شناورِ گرد', 'نواری گرد و شناور که روی صفحه می‌ماند؛ مناسبِ سبک‌های شیشه‌ای و روشن',
      _NAV_SLOTS, _NAV_IN,
      """.nbc-nav-floating-pill{background:transparent;border:0;margin-block-start:12px;top:12px}
.nbc-nav-floating-pill .nb-header-in{max-width:min(var(--nb-width,1140px),calc(100% - 24px));padding-inline:22px;min-height:60px;border-radius:999px;
border:var(--st-card-bd,1px solid var(--line));background:var(--st-hd-bg,var(--card));-webkit-backdrop-filter:var(--st-hd-bf,blur(12px));backdrop-filter:var(--st-hd-bf,blur(12px));box-shadow:0 16px 44px -22px rgba(0,0,0,.45)}
@media (max-width:760px){.nbc-nav-floating-pill .nb-header-in{border-radius:26px}}""",
      'سربرگ منو هدر شناور گرد شیشه ای', 'glassmorphism aurora soft-pastel claymorphism retro-y2k', root='header'),

    C('nav_announce', 'navbar', 'سربرگِ همراهِ نوارِ اعلان', 'یک نوارِ باریکِ اعلان در بالا و زیرش سربرگِ تمیز',
      [T('announce', 'متنِ اعلان', 'یک خبرِ کوتاه یا پیشنهادِ ویژه'), T('announce_btn', 'پیوندِ اعلان', 'بیشتر'), L('announce_link', 'نشانیِ پیوندِ اعلان')] + _NAV_SLOTS,
      """<div class="nbc-ann"><div class="nb-wrap"><span data-s="announce"></span><a class="nbc-link" data-s="announce_btn" data-h="announce_link"></a></div></div>""" + _NAV_IN,
      """.nbc-ann{background:var(--brand);color:var(--brand-ink,#fff);font-size:.88rem;font-weight:600}.nbc-ann .nb-wrap{display:flex;gap:12px;justify-content:center;align-items:center;padding-block:7px;flex-wrap:wrap;text-align:center}
.nbc-ann .nbc-link{color:inherit;text-decoration:underline;text-underline-offset:3px;opacity:1}""",
      'سربرگ منو هدر نوار اعلان بنر بالا', 'corporate-clean bento-grid soft-pastel neo-brutalism retro-y2k', root='header'),

    # ─────────────── پابرگ‌ها
    C('footer_columns', 'footer', 'پابرگِ چندستونه', 'معرفیِ کوتاه و شبکه‌ها، منوی سایت، یک فهرستِ پیوند و تماس',
      [A('about', 'معرفیِ کوتاه', 'یکی دو جمله دربارهٔ کسب‌وکارت.'), A('social', 'شبکه‌های اجتماعی (هر خط: نام | نشانی)', ''), T('menu_title', 'تیترِ ستونِ منو', 'دسترسیِ سریع'),
       T('col2_title', 'تیترِ ستونِ پیوندها', 'منابع'), A('col2_links', 'پیوندها (هر خط: متن | نشانی)', 'پرسش‌های پرتکرار | #\nقوانین | #\nحریمِ خصوصی | #'),
       T('col3_title', 'تیترِ ستونِ تماس', 'تماس'), A('col3_text', 'تماس', 'راه‌های ارتباطی را این‌جا بنویس.')] + _FT_SLOTS,
      """<div class="nbc-fc"><div class="nbc-fc-about"><b class="nbc-fc-brand">[[TITLE]]</b><p class="nbc-text" data-s="about|m"></p><ul class="nbc-fc-social" data-links="social"></ul></div>"""
      """<nav class="nbc-fc-col"><h4 class="nbc-h3" data-s="menu_title"></h4>[[MENU]]</nav>"""
      """<div class="nbc-fc-col"><h4 class="nbc-h3" data-s="col2_title"></h4><ul class="nbc-links" data-links="col2_links"></ul></div>"""
      """<div class="nbc-fc-col"><h4 class="nbc-h3" data-s="col3_title"></h4><p class="nbc-text" data-s="col3_text|m"></p></div></div>""" + _FT_COPY,
      """.nbc-footer-columns{padding-block:clamp(34px,5vw,60px) 22px;background:var(--st-hd-bg,var(--card));color:var(--ink);border-top:var(--st-hd-bd,1px solid var(--line))}
.nbc-fc{display:grid;grid-template-columns:1.5fr repeat(3,1fr);gap:clamp(22px,4vw,56px);padding-bottom:30px}
.nbc-fc-brand{display:block;font-family:var(--nb-font-head,inherit);font-size:1.35rem;color:var(--brand);margin-bottom:10px}
.nbc-fc-col{display:grid;gap:9px;align-content:start}.nbc-fc-col .nbc-h3{font-size:1rem;margin-bottom:4px}
.nbc-fc-col>a{color:var(--ink-2);text-decoration:none;opacity:.9}.nbc-fc-col>a:hover{color:var(--brand)}
.nbc-fc-social{list-style:none;margin:14px 0 0;padding:0;display:flex;gap:8px;flex-wrap:wrap}.nbc-fc-social:empty{display:none}
.nbc-fc-social a{display:inline-block;padding:5px 13px;border-radius:999px;border:1px solid var(--line);color:var(--ink-2);text-decoration:none;font-size:.86rem}.nbc-fc-social a:hover{border-color:var(--brand);color:var(--brand)}
.nbc-fc-copy{margin:0;padding-top:18px;border-top:1px solid var(--line);color:var(--ink-3);font-size:.88rem}
@media (max-width:900px){.nbc-fc{grid-template-columns:repeat(2,minmax(0,1fr))}.nbc-fc-about{grid-column:1/-1}}@media (max-width:520px){.nbc-fc{grid-template-columns:minmax(0,1fr)}}""",
      'پابرگ فوتر چند ستون', 'corporate-clean bento-grid glassmorphism soft-pastel organic', root='footer'),

    C('footer_minimal', 'footer', 'پابرگِ مینیمال', 'نام و منو در یک خط و نوشتهٔ پایانی؛ بی‌تزیین',
      _FT_SLOTS,
      """<div class="nbc-fm"><b class="nbc-fc-brand">[[TITLE]]</b><nav class="nbc-fm-nav">[[MENU]]</nav></div>""" + _FT_COPY,
      """.nbc-footer-minimal{padding-block:30px 22px;background:var(--st-hd-bg,var(--bg));color:var(--ink);border-top:var(--st-hd-bd,1px solid var(--line))}
.nbc-fm{display:flex;flex-wrap:wrap;gap:14px 30px;align-items:center;justify-content:space-between;padding-bottom:18px}
.nbc-fm .nbc-fc-brand{margin:0}.nbc-fm-nav{display:flex;flex-wrap:wrap;gap:6px 22px}.nbc-fm-nav a{color:var(--ink-2);text-decoration:none}.nbc-fm-nav a:hover{color:var(--brand)}
.nbc-footer-minimal .nbc-fc-copy{border-top:1px solid var(--line);color:var(--ink-3);font-size:.88rem;margin:0;padding-top:16px}
.nbc-fc-brand{display:block;font-family:var(--nb-font-head,inherit);font-size:1.25rem;color:var(--brand)}""",
      'پابرگ فوتر مینیمال ساده', 'minimalism swiss editorial neumorphism dark-luxury', root='footer'),

    C('footer_centered_social', 'footer', 'پابرگِ وسط‌چین با شبکه‌ها', 'نام، یک جملهٔ معرفی، دکمه‌های شبکه‌های اجتماعی و منو، همه وسط‌چین',
      [A('about', 'یک جمله', 'یک جملهٔ معرفی که برندت را خلاصه می‌کند.'), A('social', 'شبکه‌های اجتماعی (هر خط: نام | نشانی)', 'اینستاگرام | #\nتلگرام | #')] + _FT_SLOTS,
      """<div class="nbc-fcs"><b class="nbc-fc-brand">[[TITLE]]</b><p class="nbc-text" data-s="about|m"></p><ul class="nbc-fc-social" data-links="social"></ul><nav class="nbc-fm-nav">[[MENU]]</nav></div>""" + _FT_COPY,
      """.nbc-footer-centered-social{padding-block:clamp(34px,5vw,56px) 22px;background:var(--st-hd-bg,var(--card));color:var(--ink);border-top:var(--st-hd-bd,1px solid var(--line))}
.nbc-fcs{display:grid;justify-items:center;text-align:center;gap:14px;padding-bottom:26px}.nbc-fcs .nbc-text{max-width:52ch}
.nbc-fcs .nbc-fc-social{justify-content:center;margin:2px 0}.nbc-fcs .nbc-fm-nav{justify-content:center}.nbc-fcs .nbc-fm-nav a{color:var(--ink-2);text-decoration:none}.nbc-fcs .nbc-fm-nav a:hover{color:var(--brand)}
.nbc-footer-centered-social .nbc-fc-copy{text-align:center;border-top:1px solid var(--line);margin:0;padding-top:16px;color:var(--ink-3);font-size:.88rem}
.nbc-fc-brand{display:block;font-family:var(--nb-font-head,inherit);font-size:1.5rem;color:var(--brand)}
.nbc-fc-social{list-style:none;margin:0;padding:0;display:flex;gap:8px;flex-wrap:wrap}.nbc-fc-social:empty{display:none}
.nbc-fc-social a{display:inline-block;padding:6px 16px;border-radius:999px;border:1px solid var(--line);color:var(--ink-2);text-decoration:none;font-size:.88rem}.nbc-fc-social a:hover{border-color:var(--brand);color:var(--brand)}""",
      'پابرگ فوتر وسط چین شبکه اجتماعی', 'soft-pastel claymorphism glassmorphism organic aurora retro-y2k', root='footer'),

    C('footer_big_cta', 'footer', 'پابرگِ با دعوتِ بزرگ', 'نواری رنگی با تیتر و دکمه در بالا و زیرش ستون‌های پیوند',
      [T('cta_title', 'تیترِ دعوت', 'آماده‌ای شروع کنیم؟'), A('cta_text', 'توضیحِ دعوت', ''), T('cta_btn', 'دکمهٔ دعوت', 'تماس با ما'), L('cta_link', 'پیوندِ دعوت'),
       T('menu_title', 'تیترِ ستونِ منو', 'دسترسیِ سریع'), T('col2_title', 'تیترِ ستونِ تماس', 'تماس'), A('col2_text', 'تماس', 'راه‌های ارتباطی را این‌جا بنویس.')] + _FT_SLOTS,
      """<div class="nbc-fb"><div class="nbc-fb-cta"><div><h3 class="nbc-title" data-s="cta_title"></h3><p class="nbc-lead" data-s="cta_text|m"></p></div><a class="nbc-btn is-light" data-s="cta_btn" data-h="cta_link"></a></div>"""
      """<div class="nbc-fb-cols"><div><b class="nbc-fc-brand">[[TITLE]]</b></div><nav class="nbc-fc-col"><h4 class="nbc-h3" data-s="menu_title"></h4>[[MENU]]</nav>"""
      """<div class="nbc-fc-col"><h4 class="nbc-h3" data-s="col2_title"></h4><p class="nbc-text" data-s="col2_text|m"></p></div></div></div>""" + _FT_COPY,
      """.nbc-footer-big-cta{padding-block:clamp(30px,5vw,56px) 22px;background:var(--st-hd-bg,var(--card));color:var(--ink);border-top:var(--st-hd-bd,1px solid var(--line))}
.nbc-fb-cta{display:flex;flex-wrap:wrap;gap:18px 32px;align-items:center;justify-content:space-between;padding:clamp(22px,4vw,40px);margin-bottom:32px;color:var(--st-cta-fg,var(--brand-ink,#fff));
background:var(--st-cta-bg,linear-gradient(135deg,var(--brand),color-mix(in srgb,var(--brand) 55%,#0b1020)));border-radius:var(--st-cta-r,calc(var(--r,16px) + 6px));border:var(--st-cta-bd,0 solid transparent);box-shadow:var(--st-cta-sh,none)}
.nbc-fb-cta .nbc-title,.nbc-fb-cta .nbc-lead{color:inherit;margin:0}.nbc-fb-cta .nbc-title{font-size:clamp(1.3rem,3vw,1.9rem)}.nbc-fb-cta .nbc-lead{margin-top:6px;opacity:.92}
.nbc-fb-cols{display:grid;grid-template-columns:1.4fr 1fr 1fr;gap:clamp(22px,4vw,56px);padding-bottom:26px}
.nbc-fc-brand{display:block;font-family:var(--nb-font-head,inherit);font-size:1.35rem;color:var(--brand)}
.nbc-fc-col{display:grid;gap:9px;align-content:start}.nbc-fc-col .nbc-h3{font-size:1rem}.nbc-fc-col>a{color:var(--ink-2);text-decoration:none}.nbc-fc-col>a:hover{color:var(--brand)}
.nbc-footer-big-cta .nbc-fc-copy{margin:0;border-top:1px solid var(--line);padding-top:16px;color:var(--ink-3);font-size:.88rem}
@media (max-width:760px){.nbc-fb-cols{grid-template-columns:minmax(0,1fr)}}""",
      'پابرگ فوتر دعوت به اقدام بزرگ', 'aurora glassmorphism corporate-clean bento-grid soft-pastel', root='footer'),
]
