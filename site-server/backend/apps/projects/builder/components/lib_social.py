# -*- coding: utf-8 -*-
"""نظرِ مشتریان (۵ قطعه) و دعوت به اقدام (۴ قطعه). متن‌های پیش‌فرض نمونه‌اند؛ هیچ نامِ واقعی، آمار یا قیمتی در آن‌ها نیست."""
from . import provenance as PV
from .spec import A, C, IC, IM, ITEMS, L, SHARED, T

_HEAD = [T('title', 'تیتر', 'مشتریان چه می‌گویند'), A('subtitle', 'توضیح', '')]
_HEADHTML = """<div class="nbc-head"><h2 class="nbc-title" data-s="title"></h2><p class="nbc-lead" data-s="subtitle|m"></p></div>"""
_QUOTE_ROWS = [{'text': 'متنِ نظرِ مشتری این‌جا می‌آید؛ کوتاه و صادقانه.', 'name': 'نامِ مشتری', 'role': 'سمت یا شهر', 'avatar': ''},
               {'text': 'نظرِ دوم را این‌جا بنویس. بهتر است از مشتریِ واقعی و با اجازهٔ خودش باشد.', 'name': 'نامِ مشتری', 'role': 'سمت یا شهر', 'avatar': ''},
               {'text': 'نظرِ سوم؛ یکی دو جمله کافی است.', 'name': 'نامِ مشتری', 'role': 'سمت یا شهر', 'avatar': ''}]
_QUOTE_F = [A('text', 'متنِ نظر'), T('name', 'نام'), T('role', 'سمت یا شهر'), IM('avatar', 'تصویر')]
_SOC_ROWS = [{'name': 'نامِ کاربر', 'handle': 'username', 'text': 'متنِ پیامی که کاربر نوشته؛ مثلِ یک نظرِ کوتاه زیرِ پست.', 'platform': 'اینستاگرام', 'date': '', 'avatar': ''},
             {'name': 'نامِ کاربر', 'handle': 'username', 'text': 'یک پیامِ دیگر؛ کوتاه یا بلند، هر دو در کارت جا می‌شوند و کارت‌ها زیرِ هم می‌چینند.', 'platform': 'تلگرام', 'date': '', 'avatar': ''},
             {'name': 'نامِ کاربر', 'handle': 'username', 'text': 'پیامِ سوم.', 'platform': 'اینستاگرام', 'date': '', 'avatar': ''},
             {'name': 'نامِ کاربر', 'handle': 'username', 'text': 'پیامِ چهارم؛ کارت‌ها به‌صورتِ آجری کنارِ هم می‌نشینند.', 'platform': 'تلگرام', 'date': '', 'avatar': ''}]
_SOC_F = [T('name', 'نام'), T('handle', 'شناسه (بدونِ @)', dir='ltr'), A('text', 'متنِ پیام'), T('platform', 'کجا نوشته شده'), T('date', 'تاریخ'), IM('avatar', 'تصویر')]

SHARED['mq'] = (""".nbc-mq{--gap:16px;--dur:42s;display:flex;overflow:hidden;gap:var(--gap);padding-block:6px}
.nbc-mq-track{display:flex;flex:none;gap:var(--gap);min-width:100%;align-items:stretch;justify-content:space-around;animation:nbc-mq-l var(--dur) linear infinite}
[dir=rtl] .nbc-mq-track{animation-name:nbc-mq-r}.nbc-mq:hover .nbc-mq-track{animation-play-state:paused}
.nbc-mq.is-rev .nbc-mq-track{animation-direction:reverse}
@keyframes nbc-mq-l{to{transform:translateX(calc(-100% - var(--gap)))}}@keyframes nbc-mq-r{to{transform:translateX(calc(100% + var(--gap)))}}
@media (prefers-reduced-motion:reduce){.nbc-mq{overflow-x:auto}.nbc-mq-track{animation:none}.nbc-mq-track[aria-hidden]{display:none}}""")

SPECS = [
    C('testi_cards_grid', 'testimonials', 'کارت‌های نظر', 'نظرها در کارت‌هایی کنارِ هم با نام و سمتِ نویسنده',
      _HEAD + [ITEMS('items', 'نظرها', _QUOTE_F, _QUOTE_ROWS, 'name', 'افزودنِ نظر')],
      _HEADHTML + """<div class="nbc-grid nbc-auto nbc-tg"><!--each:items--><figure class="nbc-card nbc-tg-i"><blockquote class="nbc-tg-q" data-s="text|m"></blockquote>"""
      """<figcaption class="nbc-tg-by"><img class="nbc-avatar" data-i="avatar" data-alt="name"><span><b data-s="name"></b><small data-s="role"></small></span></figcaption></figure><!--/each--></div>""",
      """.nbc-tg-i{margin:0;display:grid;gap:18px;align-content:space-between}.nbc-tg-q{margin:0;position:relative;color:var(--ink-2);line-height:2}
.nbc-tg-q::before{content:"\\201D";display:block;font:700 3.4rem/1 Georgia,serif;color:var(--brand);opacity:.45;margin-bottom:-6px}
.nbc-tg-by{display:flex;align-items:center;gap:12px}.nbc-tg-by span{display:grid;line-height:1.5}.nbc-tg-by small{color:var(--ink-3)}""",
      'نظر مشتری کارت نقل قول', 'corporate-clean glassmorphism soft-pastel bento-grid claymorphism organic'),

    C('testi_big_quote', 'testimonials', 'یک نقلِ بزرگ', 'یک نظرِ درشت و وسط‌چین با عکس و نامِ نویسنده؛ برای برجسته‌کردنِ بهترین نظر',
      [A('text', 'متنِ نظر', 'یک نظرِ خوب که حالِ مشتری را بعد از استفاده توصیف می‌کند.'), T('name', 'نام', 'نامِ مشتری'), T('role', 'سمت یا شهر', 'سمت یا شهر'), IM('avatar', 'تصویر')],
      """<figure class="nbc-bq"><img class="nbc-avatar nbc-bq-av" data-i="avatar" data-alt="name"><blockquote class="nbc-bq-q" data-s="text|m"></blockquote>"""
      """<figcaption><b data-s="name"></b><small data-s="role"></small></figcaption></figure>""",
      """.nbc-testi-big-quote{padding-block:clamp(56px,9vw,112px)}.nbc-bq{margin:0 auto;max-width:860px;text-align:center;display:grid;justify-items:center;gap:20px}
.nbc-bq-av{width:72px;height:72px}.nbc-bq-q{margin:0;font-family:var(--nb-font-head,inherit);font-size:clamp(1.35rem,3.2vw,2.1rem);line-height:1.85;font-weight:var(--st-head-w,700)}
.nbc-bq-q::before{content:"\\201C";color:var(--brand)}.nbc-bq-q::after{content:"\\201D";color:var(--brand)}
.nbc-bq figcaption{display:grid;gap:2px}.nbc-bq small{color:var(--ink-3)}""",
      'نظر مشتری نقل قول بزرگ تک', 'dark-luxury editorial minimalism swiss organic'),

    C('testi_social_cards', 'testimonials', 'پیام‌های کاربران (آجری)', 'نظرها شبیهِ پیامِ شبکهٔ اجتماعی: عکس، نام، شناسه و متن؛ کارت‌ها آجری می‌چینند',
      _HEAD + [ITEMS('items', 'پیام‌ها', _SOC_F, _SOC_ROWS, 'name', 'افزودنِ پیام')],
      _HEADHTML + """<div class="nbc-sw"><!--each:items--><article class="nbc-card nbc-sw-i"><header class="nbc-sw-h"><img class="nbc-avatar" data-i="avatar" data-alt="name">"""
      """<span class="nbc-sw-id"><b data-s="name"></b><small dir="ltr" data-s="handle"></small></span><span class="nbc-pill nbc-sw-pf" data-s="platform"></span></header>"""
      """<p class="nbc-sw-t" data-s="text|m"></p><time class="nbc-muted" data-s="date"></time></article><!--/each--></div>""",
      """.nbc-sw{column-width:260px;column-gap:var(--st-gap,18px)}.nbc-sw-i{break-inside:avoid;display:grid;gap:12px;margin-bottom:var(--st-gap,18px);transition:box-shadow .2s,border-color .2s}
.nbc-sw-i:hover{border-color:color-mix(in srgb,var(--brand) 40%,var(--line))}
.nbc-sw-h{display:flex;align-items:center;gap:10px}.nbc-sw-id{display:grid;line-height:1.45;min-width:0}.nbc-sw-id small{color:var(--ink-3);text-align:end}
.nbc-sw-pf{margin-inline-start:auto;font-size:.74rem;padding:3px 10px;color:var(--ink-2)}.nbc-sw-t{margin:0;line-height:1.95;color:var(--ink)}
.nbc-sw-i time:empty{display:none}""",
      'نظر مشتری پیام شبکه اجتماعی توییت کامنت آجری', 'glassmorphism claymorphism soft-pastel bento-grid aurora neo-brutalism',
      src=PV.adapted('magicui', 'apps/www/registry/magicui/tweet-card.tsx', 'tweet-card',
                     'ساختارِ کارت (سرآیند: عکس، نام، شناسه، نشانِ شبکه؛ متن؛ زمان) و چینشِ آجری از tweet-card و بخشِ testimonials؛ بی‌react-tweet و بی‌اتصال به X')),

    C('testi_marquee', 'testimonials', 'نوارِ متحرکِ نظرها', 'دو ردیفِ نظر که آرام می‌لغزند و با نگه‌داشتنِ ماوس می‌ایستند',
      _HEAD + [ITEMS('items', 'نظرها', _QUOTE_F, _QUOTE_ROWS + [{'text': 'نظرِ چهارم؛ برای پرشدنِ نوار کم‌کم چند نظر دیگر هم اضافه کن.', 'name': 'نامِ مشتری', 'role': 'سمت یا شهر', 'avatar': ''}], 'name', 'افزودنِ نظر')],
      _HEADHTML + """<div class="nbc-mq nbc-tm"><div class="nbc-mq-track"><!--each:items--><figure class="nbc-card nbc-tm-i"><blockquote data-s="text|m"></blockquote>"""
      """<figcaption><img class="nbc-avatar" data-i="avatar" data-alt="name"><span><b data-s="name"></b><small data-s="role"></small></span></figcaption></figure><!--/each--></div>"""
      """<div class="nbc-mq-track" aria-hidden="true"><!--each:items.dup--><figure class="nbc-card nbc-tm-i"><blockquote data-s="text|m"></blockquote>"""
      """<figcaption><img class="nbc-avatar" data-i="avatar" data-alt="name"><span><b data-s="name"></b><small data-s="role"></small></span></figcaption></figure><!--/each--></div></div>""",
      """.nbc-testi-marquee .nb-wrap{max-width:none;padding-inline:0}.nbc-testi-marquee .nbc-head{padding-inline:20px}
.nbc-tm{-webkit-mask-image:linear-gradient(90deg,transparent,#000 8%,#000 92%,transparent);mask-image:linear-gradient(90deg,transparent,#000 8%,#000 92%,transparent)}
.nbc-tm-i{margin:0;width:min(320px,78vw);display:grid;gap:14px;align-content:space-between}.nbc-tm-i blockquote{margin:0;color:var(--ink-2);line-height:1.9;font-size:.95rem}
.nbc-tm-i figcaption{display:flex;align-items:center;gap:10px}.nbc-tm-i figcaption span{display:grid;line-height:1.45}.nbc-tm-i small{color:var(--ink-3)}""",
      'نظر مشتری نوار متحرک مارکی اسلایدر', 'aurora glassmorphism bento-grid corporate-clean dark-luxury', uses='mq',
      src=PV.adapted('magicui', 'apps/www/registry/magicui/marquee.tsx', 'marquee',
                     'سازوکارِ نوار (دو نسخهٔ همان ردیف، انیمیشنِ translateX با --gap و --duration، ایستادن با hover) از Marquee؛ در راست‌به‌چپ جهت برعکس می‌شود و با reduced-motion می‌ایستد')),

    C('testi_snap_carousel', 'testimonials', 'نظرها در لغزندهٔ افقی', 'کارت‌های نظر که با کشیدنِ انگشت یا غلتکِ ماوس کنارِ هم حرکت می‌کنند (بی‌جاوااسکریپت)',
      _HEAD + [ITEMS('items', 'نظرها', _QUOTE_F, _QUOTE_ROWS + _QUOTE_ROWS[:2], 'name', 'افزودنِ نظر')],
      _HEADHTML + """<div class="nbc-sc" tabindex="0" role="region" aria-label="نظرها"><!--each:items--><figure class="nbc-card nbc-sc-i"><blockquote data-s="text|m"></blockquote>"""
      """<figcaption><img class="nbc-avatar" data-i="avatar" data-alt="name"><span><b data-s="name"></b><small data-s="role"></small></span></figcaption></figure><!--/each--></div>""",
      """.nbc-sc{display:flex;gap:var(--st-gap,18px);overflow-x:auto;scroll-snap-type:x mandatory;padding:6px 4px 18px;scrollbar-width:thin;outline-offset:4px}
.nbc-sc-i{margin:0;flex:0 0 min(340px,84%);scroll-snap-align:start;display:grid;gap:16px;align-content:space-between}
.nbc-sc-i blockquote{margin:0;color:var(--ink-2);line-height:1.95}.nbc-sc-i figcaption{display:flex;align-items:center;gap:10px}
.nbc-sc-i figcaption span{display:grid;line-height:1.45}.nbc-sc-i small{color:var(--ink-3)}""",
      'نظر مشتری لغزنده اسلایدر کاروسل افقی', 'bento-grid soft-pastel claymorphism corporate-clean organic'),

    # ───────────── دعوت به اقدام
    C('cta_center_box', 'cta', 'جعبهٔ گرادیانیِ وسط‌چین', 'قابِ رنگیِ گرد با تیتر، توضیح و دو دکمه',
      [T('title', 'تیتر', 'آماده‌ای شروع کنیم؟'), A('text', 'توضیح', 'یک جمله که مشتری را به قدمِ بعدی دعوت می‌کند.'), T('btn1', 'دکمهٔ اول', 'شروع کنید'), L('btn1_link', 'پیوندِ دکمهٔ اول'),
       T('btn2', 'دکمهٔ دوم', 'بیشتر بدانید'), L('btn2_link', 'پیوندِ دکمهٔ دوم')],
      """<div class="nbc-cb"><h2 class="nbc-title" data-s="title"></h2><p class="nbc-lead" data-s="text|m"></p>"""
      """<div class="nbc-btns"><a class="nbc-btn is-light" data-s="btn1" data-h="btn1_link"></a><a class="nbc-btn is-ghost" data-s="btn2" data-h="btn2_link"></a></div></div>""",
      """.nbc-cta-center-box{padding-block:clamp(34px,5vw,64px)}.nbc-cb{text-align:center;color:var(--st-cta-fg,var(--brand-ink,#fff));padding:clamp(36px,6vw,80px) clamp(20px,5vw,64px);
background:var(--st-cta-bg,linear-gradient(135deg,var(--brand),color-mix(in srgb,var(--brand) 55%,#0b1020)));border:var(--st-cta-bd,0 solid transparent);box-shadow:var(--st-cta-sh,none);border-radius:var(--st-cta-r,calc(var(--r,16px) + 10px))}
.nbc-cb .nbc-title,.nbc-cb .nbc-lead{color:inherit}.nbc-cb .nbc-lead{margin-inline:auto;opacity:.92}.nbc-cb .nbc-btns{justify-content:center}""",
      'دعوت به اقدام سی تی ای جعبه گرادیان وسط', 'glassmorphism aurora soft-pastel retro-y2k claymorphism bento-grid corporate-clean'),

    C('cta_split_image', 'cta', 'متن و تصویرِ کنارِ هم', 'کارتی با تیتر و دکمه در یک سو و تصویر در سوی دیگر',
      [T('title', 'تیتر', 'یک قدم تا شروع'), A('text', 'توضیح', 'توضیحِ کوتاه دربارهٔ چیزی که بعد از کلیک می‌بینند.'), T('btn', 'متنِ دکمه', 'شروع کنید'), L('btn_link', 'پیوندِ دکمه'),
       T('note', 'یادداشتِ زیرِ دکمه', ''), IM('image', 'تصویر'), T('image_alt', 'توضیحِ تصویر')],
      """<div class="nbc-card nbc-split nbc-csi"><div><h2 class="nbc-title" data-s="title"></h2><p class="nbc-lead" data-s="text|m"></p><div class="nbc-btns"><a class="nbc-btn" data-s="btn" data-h="btn_link"></a>"""
      """<span class="nbc-muted" data-s="note"></span></div></div><div class="nbc-csi-m"><img class="nbc-img" data-i="image" data-alt="image_alt"></div></div>""",
      """.nbc-csi{padding:clamp(24px,4vw,48px);overflow:hidden}.nbc-csi-m img{aspect-ratio:4/3;border-radius:calc(var(--st-card-r,var(--r,16px)) - 4px)}
.nbc-csi-m:empty{display:none}.nbc-csi:has(.nbc-csi-m:empty){grid-template-columns:minmax(0,1fr)}""",
      'دعوت به اقدام تصویر کنار متن', 'corporate-clean minimalism organic bento-grid editorial'),

    C('cta_strip', 'cta', 'نوارِ باریکِ دعوت', 'یک خط: متن در یک سو و دکمه در سوی دیگر؛ برای پایانِ صفحه',
      [T('text', 'متن', 'سؤالی داری؟ همین حالا بپرس.'), T('btn', 'متنِ دکمه', 'تماس با ما'), L('btn_link', 'پیوندِ دکمه')],
      """<div class="nbc-cs"><p class="nbc-cs-t" data-s="text"></p><a class="nbc-btn" data-s="btn" data-h="btn_link"></a></div>""",
      """.nbc-cta-strip{padding-block:clamp(22px,3vw,34px)}.nbc-cs{display:flex;flex-wrap:wrap;gap:16px 28px;align-items:center;justify-content:space-between;
padding:18px clamp(18px,3vw,34px);border:var(--st-card-bd,1px solid var(--line));border-radius:var(--st-card-r,var(--r,16px));background:var(--st-card-bg,var(--card))}
.nbc-cs-t{margin:0;font-family:var(--nb-font-head,inherit);font-weight:var(--st-head-w,700);font-size:1.2rem}""",
      'دعوت به اقدام نوار باریک خطی', 'minimalism swiss editorial corporate-clean dark-luxury neumorphism'),

    C('cta_app_download', 'cta', 'دانلودِ اپ', 'تیتر و دو دکمهٔ دانلود در یک سو و تصویرِ اپ در سوی دیگر',
      [T('title', 'تیتر', 'اپ را نصب کن'), A('text', 'توضیح', 'توضیحِ کوتاه دربارهٔ اپ و کاری که با آن می‌شود کرد.'), T('btn1', 'دکمهٔ اول', 'دانلودِ مستقیم'), L('btn1_link', 'پیوندِ دکمهٔ اول'),
       T('btn2', 'دکمهٔ دوم', 'نصب از فروشگاه'), L('btn2_link', 'پیوندِ دکمهٔ دوم'), IM('image', 'تصویرِ اپ'), T('image_alt', 'توضیحِ تصویر')],
      """<div class="nbc-split nbc-cad"><div class="nbc-cad-c"><h2 class="nbc-title" data-s="title"></h2><p class="nbc-lead" data-s="text|m"></p>"""
      """<div class="nbc-btns"><a class="nbc-btn" data-s="btn1" data-h="btn1_link"></a><a class="nbc-btn is-alt" data-s="btn2" data-h="btn2_link"></a></div></div>"""
      """<div class="nbc-cad-m"><img class="nbc-img" data-i="image" data-alt="image_alt"></div></div>""",
      """.nbc-cad{padding:clamp(26px,5vw,60px);border-radius:var(--st-cta-r,calc(var(--r,16px) + 10px));background:var(--st-cta-bg,linear-gradient(135deg,var(--brand),color-mix(in srgb,var(--brand) 55%,#0b1020)));
color:var(--st-cta-fg,var(--brand-ink,#fff));border:var(--st-cta-bd,0 solid transparent);box-shadow:var(--st-cta-sh,none)}
.nbc-cad .nbc-title,.nbc-cad .nbc-lead{color:inherit}.nbc-cad .nbc-btn{background:var(--brand-ink,#fff);color:var(--brand);border-color:transparent}.nbc-cad .nbc-btn.is-alt{background:transparent;color:inherit;border-color:currentColor}
.nbc-cad-m{justify-self:center}.nbc-cad-m img{max-height:380px;width:auto;border-radius:calc(var(--r,16px) + 6px);box-shadow:0 30px 60px -30px rgba(0,0,0,.6)}
.nbc-cad-m:empty{display:none}.nbc-cad:has(.nbc-cad-m:empty){grid-template-columns:minmax(0,1fr);text-align:center}.nbc-cad:has(.nbc-cad-m:empty) .nbc-btns{justify-content:center}""",
      'دعوت به اقدام دانلود اپ موبایل نصب', 'aurora glassmorphism soft-pastel claymorphism corporate-clean bento-grid retro-y2k'),
]
