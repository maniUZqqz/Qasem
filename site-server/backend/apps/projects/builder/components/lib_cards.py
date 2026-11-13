# -*- coding: utf-8 -*-
"""کارت‌ها (۵ قطعه) و گالری و نوارِ نشان‌ها (۴ قطعه)."""
from . import provenance as PV
from .spec import A, C, IM, ITEMS, L, SHARED, T

_HEAD = [T('title', 'تیتر', ''), A('subtitle', 'توضیح', '')]
_HEADHTML = """<div class="nbc-head"><h2 class="nbc-title" data-s="title"></h2><p class="nbc-lead" data-s="subtitle|m"></p></div>"""
_CARD_F = [T('title', 'عنوان'), A('text', 'توضیح'), T('link_text', 'متنِ پیوند'), L('link', 'نشانیِ پیوند')]
_CARD_ROWS = [{'title': 'عنوانِ کارت', 'text': 'توضیحِ کوتاهِ کارت؛ یکی دو جمله.', 'link_text': 'بیشتر بدانید', 'link': '#'},
              {'title': 'عنوانِ کارتِ دوم', 'text': 'توضیحِ کوتاهِ کارتِ دوم.', 'link_text': 'بیشتر بدانید', 'link': '#'},
              {'title': 'عنوانِ کارتِ سوم', 'text': 'توضیحِ کوتاهِ کارتِ سوم.', 'link_text': 'بیشتر بدانید', 'link': '#'}]

SPECS = [
    C('card_neon_gradient', 'cards', 'کارت‌های با حاشیهٔ نئونیِ متحرک', 'کارت‌هایی که دورشان یک گرادیانِ درخشان آرام می‌گردد؛ برای برجسته‌کردنِ چند مورد',
      [T('title', 'تیتر', 'ویژه‌ها'), A('subtitle', 'توضیح', ''), ITEMS('items', 'کارت‌ها', _CARD_F, _CARD_ROWS[:2], 'title', 'افزودنِ کارت')],
      _HEADHTML + """<div class="nbc-grid nbc-auto nbc-ng"><!--each:items--><div class="nbc-ng-card"><article class="nbc-ng-in"><h3 class="nbc-h3" data-s="title"></h3><p class="nbc-text" data-s="text|m"></p>"""
      """<a class="nbc-link nbc-arrow" data-s="link_text" data-h="link"></a></article></div><!--/each--></div>""",
      r""".nbc-ng{gap:clamp(18px,3vw,30px)}.nbc-ng-card{position:relative;z-index:0;isolation:isolate;border-radius:var(--st-card-r,20px);--ng1:var(--brand);--ng2:color-mix(in srgb,var(--brand) 30%,#00f5e0)}
.nbc-ng-card::before,.nbc-ng-card::after{content:"";position:absolute;inset:-2px;z-index:-1;border-radius:inherit;background:linear-gradient(0deg,var(--ng1),var(--ng2));background-size:100% 220%;animation:nbc-ng-spin 3.2s ease infinite alternate}
.nbc-ng-card::after{inset:-1px;filter:blur(16px);opacity:.65}
.nbc-ng-in{height:100%;display:grid;gap:8px;align-content:start;padding:clamp(20px,3vw,30px);border-radius:calc(var(--st-card-r,20px) - 2px);background:var(--card);color:var(--ink)}
.nbc-arrow{font-weight:700;color:var(--brand);opacity:1;justify-self:start;margin-top:6px}.nbc-arrow::after{content:"\2190";margin-inline-start:8px}
@keyframes nbc-ng-spin{from{background-position:50% 0}to{background-position:50% 100%}}
@media (prefers-reduced-motion:reduce){.nbc-ng-card::before,.nbc-ng-card::after{animation:none}}""",
      'کارت نئون گرادیان حاشیه درخشان متحرک', 'aurora dark-luxury retro-y2k glassmorphism neo-brutalism',
      src=PV.adapted('magicui', 'apps/www/registry/magicui/neon-gradient-card.tsx', '',
                     'حاشیهٔ گرادیانیِ پشتِ کارت با دو لایهٔ ::before و ::after (یکی تیز، یکی محو) و چرخشِ background-position از NeonGradientCard؛ بی‌جاوااسکریپتِ اندازه‌گیری؛ رنگ‌ها از رنگِ اصلیِ پوسته')),

    C('card_spotlight', 'cards', 'کارت‌های با نورِ لبه', 'کارت‌هایی که هنگامِ رفتنِ ماوس روی آن‌ها لبه‌شان نور می‌گیرد',
      [T('title', 'تیتر', ''), A('subtitle', 'توضیح', ''), ITEMS('items', 'کارت‌ها', _CARD_F, _CARD_ROWS, 'title', 'افزودنِ کارت')],
      _HEADHTML + """<div class="nbc-grid nbc-auto nbc-sp"><!--each:items--><article class="nbc-sp-i"><h3 class="nbc-h3" data-s="title"></h3><p class="nbc-text" data-s="text|m"></p>"""
      """<a class="nbc-link nbc-arrow" data-s="link_text" data-h="link"></a></article><!--/each--></div>""",
      r""".nbc-sp-i{--sx:100%;--sy:0%;position:relative;overflow:hidden;display:grid;gap:8px;align-content:start;padding:clamp(20px,2.6vw,28px);color:var(--ink);
background:var(--st-card-bg,var(--card));border:var(--st-card-bd,1px solid var(--line));border-radius:var(--st-card-r,var(--r,16px));box-shadow:var(--st-card-sh,none)}
.nbc-sp-i:nth-child(3n+2){--sx:0%;--sy:0%}.nbc-sp-i:nth-child(3n+3){--sx:50%;--sy:100%}
.nbc-sp-i::before,.nbc-sp-i::after{content:"";position:absolute;inset:0;border-radius:inherit;pointer-events:none;opacity:0;transition:opacity .28s ease}
.nbc-sp-i::before{background:radial-gradient(240px circle at var(--sx) var(--sy),color-mix(in srgb,var(--brand) 22%,transparent),transparent 70%)}
.nbc-sp-i::after{padding:1px;background:radial-gradient(200px circle at var(--sx) var(--sy),var(--brand),transparent 70%);-webkit-mask:linear-gradient(#000 0 0) content-box,linear-gradient(#000 0 0);-webkit-mask-composite:xor;mask:linear-gradient(#000 0 0) content-box exclude,linear-gradient(#000 0 0)}
.nbc-sp-i:hover::before,.nbc-sp-i:hover::after,.nbc-sp-i:focus-within::before,.nbc-sp-i:focus-within::after{opacity:1}
.nbc-sp-i>*{position:relative}.nbc-arrow{font-weight:700;color:var(--brand);opacity:1;justify-self:start;margin-top:6px}.nbc-arrow::after{content:"\2190";margin-inline-start:8px}""",
      'کارت نور لبه اسپات لایت هاور', 'aurora dark-luxury glassmorphism bento-grid corporate-clean',
      src=PV.adapted('magicui', 'apps/www/registry/magicui/magic-card.tsx', 'magic-card',
                     'نورِ شعاعی روی لبه و درونِ کارت از MagicCard؛ ردگیریِ ماوس (framer-motion) برداشته شد و نور در گوشهٔ ثابتی از هر کارت می‌نشیند و با hover/focus پدیدار می‌شود')),

    C('cards_team', 'cards', 'کارت‌های تیم', 'عکسِ گردِ هر نفر با نام، سمت و یک جمله',
      _HEAD + [ITEMS('items', 'افراد', [IM('image', 'عکس'), T('name', 'نام'), T('role', 'سمت'), A('text', 'یک جمله')],
                     [{'image': '', 'name': 'نامِ نفر', 'role': 'سمت', 'text': 'یک جملهٔ کوتاه دربارهٔ او.'}, {'image': '', 'name': 'نامِ نفر', 'role': 'سمت', 'text': ''},
                      {'image': '', 'name': 'نامِ نفر', 'role': 'سمت', 'text': ''}, {'image': '', 'name': 'نامِ نفر', 'role': 'سمت', 'text': ''}], 'name', 'افزودنِ نفر')],
      _HEADHTML.replace('data-s="title"', 'data-s="title"') + """<div class="nbc-grid nbc-auto nbc-tm4"><!--each:items--><article class="nbc-card nbc-tm4-i"><img class="nbc-tm4-ph" data-i="image" data-alt="name">"""
      """<h3 class="nbc-h3" data-s="name"></h3><b class="nbc-tm4-r" data-s="role"></b><p class="nbc-text" data-s="text|m"></p></article><!--/each--></div>""",
      """.nbc-tm4{grid-template-columns:repeat(auto-fit,minmax(min(100%,220px),1fr))}.nbc-tm4-i{display:grid;justify-items:center;text-align:center;gap:4px}
.nbc-tm4-ph{width:112px;height:112px;border-radius:50%;object-fit:cover;margin-bottom:10px;box-shadow:0 0 0 4px color-mix(in srgb,var(--brand) 18%,transparent)}
.nbc-tm4-r{font-size:.86rem;color:var(--brand);font-weight:700;margin-bottom:6px}""",
      'کارت تیم افراد اعضا مربی', 'corporate-clean soft-pastel claymorphism organic bento-grid'),

    C('cards_blog', 'cards', 'کارت‌های نوشته', 'تصویر، تاریخ، عنوان و چند خطِ اول؛ برای وبلاگ و خبر',
      _HEAD + [ITEMS('items', 'نوشته‌ها', [IM('image', 'تصویر'), T('date', 'تاریخ'), T('title', 'عنوان'), A('text', 'چند خطِ اول'), T('link_text', 'متنِ پیوند'), L('link', 'نشانیِ پیوند')],
                     [{'image': '', 'date': '', 'title': 'عنوانِ نوشته', 'text': 'چند خطِ اولِ نوشته که خواننده را به خواندنِ ادامه دعوت می‌کند.', 'link_text': 'ادامه', 'link': '#'},
                      {'image': '', 'date': '', 'title': 'عنوانِ نوشتهٔ دوم', 'text': 'چند خطِ اولِ نوشتهٔ دوم.', 'link_text': 'ادامه', 'link': '#'},
                      {'image': '', 'date': '', 'title': 'عنوانِ نوشتهٔ سوم', 'text': 'چند خطِ اولِ نوشتهٔ سوم.', 'link_text': 'ادامه', 'link': '#'}], 'title', 'افزودنِ نوشته')],
      _HEADHTML + """<div class="nbc-grid nbc-auto nbc-bl"><!--each:items--><article class="nbc-card nbc-bl-i"><img class="nbc-bl-img" data-i="image" data-alt="title"><div class="nbc-bl-b">"""
      """<time class="nbc-muted" data-s="date"></time><h3 class="nbc-h3" data-s="title"></h3><p class="nbc-text" data-s="text|m"></p><a class="nbc-link nbc-arrow" data-s="link_text" data-h="link"></a></div></article><!--/each--></div>""",
      r""".nbc-bl-i{padding:0;overflow:hidden;display:grid;align-content:start}.nbc-bl-img{width:100%;aspect-ratio:16/10;object-fit:cover;display:block}
.nbc-bl-b{display:grid;gap:6px;padding:clamp(16px,2.2vw,24px);align-content:start}.nbc-bl-b time:empty{display:none}
.nbc-bl-i .nbc-arrow{font-weight:700;color:var(--brand);opacity:1;justify-self:start}.nbc-bl-i .nbc-arrow::after{content:"\2190";margin-inline-start:8px}""",
      'کارت نوشته مقاله وبلاگ خبر', 'editorial corporate-clean minimalism soft-pastel organic bento-grid'),

    C('cards_product', 'cards', 'کارت‌های محصول', 'عکس، نام، قیمت و دکمهٔ هر محصول (قیمت‌ها را خودت بنویس)',
      _HEAD + [ITEMS('items', 'محصولات', [IM('image', 'عکس'), T('name', 'نام'), T('note', 'نشان (مثلاً «جدید»)'), T('price', 'قیمت'), T('button', 'متنِ دکمه'), L('link', 'نشانیِ دکمه')],
                     [{'image': '', 'name': 'نامِ محصول', 'note': 'جدید', 'price': 'قیمت را بنویس', 'button': 'مشاهده', 'link': '#'},
                      {'image': '', 'name': 'نامِ محصولِ دوم', 'note': '', 'price': 'قیمت را بنویس', 'button': 'مشاهده', 'link': '#'},
                      {'image': '', 'name': 'نامِ محصولِ سوم', 'note': '', 'price': 'قیمت را بنویس', 'button': 'مشاهده', 'link': '#'}], 'name', 'افزودنِ محصول')],
      _HEADHTML + """<div class="nbc-grid nbc-auto nbc-pd"><!--each:items--><article class="nbc-card nbc-pd-i"><div class="nbc-pd-m"><img class="nbc-pd-img" data-i="image" data-alt="name"><span class="nbc-pill nbc-pd-tag" data-s="note"></span></div>"""
      """<h3 class="nbc-h3" data-s="name"></h3><b class="nbc-pd-p" data-s="price"></b><a class="nbc-btn is-alt" data-s="button" data-h="link"></a></article><!--/each--></div>""",
      """.nbc-pd-i{padding:0;overflow:hidden;display:grid;gap:6px;align-content:start;padding-bottom:clamp(16px,2vw,22px)}.nbc-pd-i>*:not(.nbc-pd-m){margin-inline:clamp(16px,2vw,22px)}
.nbc-pd-m{position:relative;background:color-mix(in srgb,var(--ink) 5%,var(--card));margin-bottom:8px}.nbc-pd-img{width:100%;aspect-ratio:1/1;object-fit:cover;display:block;border-radius:0}
.nbc-pd-tag{position:absolute;inset-block-start:12px;inset-inline-start:12px;background:var(--brand);color:var(--brand-ink,#fff);font-size:.76rem}.nbc-pd-tag:empty{display:none}
.nbc-pd-p{color:var(--brand);font-size:1.1rem;margin-bottom:8px}""",
      'کارت محصول فروشگاه قیمت خرید', 'bento-grid soft-pastel claymorphism corporate-clean minimalism organic'),

    # ─────────────── گالری و نشان‌ها
    C('gallery_masonry', 'gallery', 'گالریِ آجری', 'عکس‌ها با اندازه‌های طبیعیِ خودشان در چند ستونِ آجری',
      _HEAD + [ITEMS('items', 'تصویرها', [IM('image', 'تصویر'), T('alt', 'توضیحِ تصویر')], [{'image': '', 'alt': ''}] * 6, 'alt', 'افزودنِ تصویر')],
      _HEADHTML + """<div class="nbc-gm"><!--each:items--><figure class="nbc-gm-i" data-req="image"><img class="nbc-img" data-i="image" data-alt="alt"></figure><!--/each--></div>""",
      """.nbc-gm{column-width:240px;column-gap:var(--st-gap,14px)}.nbc-gm-i{margin:0 0 var(--st-gap,14px);break-inside:avoid;overflow:hidden;border-radius:var(--st-card-r,var(--r,16px));
border:var(--st-card-bd,0 solid transparent);box-shadow:var(--st-card-sh,none)}.nbc-gm-i img{border-radius:0;transition:transform .35s ease}.nbc-gm-i:hover img{transform:scale(1.03)}
@media (prefers-reduced-motion:reduce){.nbc-gm-i:hover img{transform:none}}""",
      'گالری عکس آجری مازونری نمونه کار', 'bento-grid soft-pastel organic claymorphism minimalism editorial'),

    C('gallery_captioned', 'gallery', 'گالریِ شبکه‌ای با زیرنویس', 'عکس‌های هم‌اندازه با عنوانی که روی تصویر می‌نشیند',
      _HEAD + [ITEMS('items', 'تصویرها', [IM('image', 'تصویر'), T('caption', 'زیرنویس'), T('alt', 'توضیحِ تصویر')], [{'image': '', 'caption': 'زیرنویس', 'alt': ''}] * 6, 'caption', 'افزودنِ تصویر')],
      _HEADHTML + """<div class="nbc-grid nbc-auto nbc-gc"><!--each:items--><figure class="nbc-gc-i" data-req="image"><img class="nbc-img" data-i="image" data-alt="alt"><figcaption data-s="caption"></figcaption></figure><!--/each--></div>""",
      """.nbc-gc{grid-template-columns:repeat(auto-fit,minmax(min(100%,260px),1fr))}.nbc-gc-i{margin:0;position:relative;overflow:hidden;border-radius:var(--st-card-r,var(--r,16px));
border:var(--st-card-bd,0 solid transparent);box-shadow:var(--st-card-sh,none)}.nbc-gc-i img{aspect-ratio:4/3;border-radius:0;transition:transform .35s}.nbc-gc-i:hover img{transform:scale(1.04)}
.nbc-gc-i figcaption{position:absolute;inset-inline:0;inset-block-end:0;padding:30px 16px 14px;color:#fff;font-weight:700;background:linear-gradient(0deg,rgba(0,0,0,.72),transparent)}
.nbc-gc-i figcaption:empty{display:none}@media (prefers-reduced-motion:reduce){.nbc-gc-i:hover img{transform:none}}""",
      'گالری عکس شبکه ای زیرنویس نمونه کار', 'corporate-clean bento-grid glassmorphism minimalism swiss'),

    C('logos_marquee', 'gallery', 'نوارِ متحرکِ نشان‌ها', 'لوگوی مشتری‌ها، همکارها یا رسانه‌ها که آرام می‌لغزند؛ اگر لوگو نداری نام بنویس',
      [T('title', 'تیتر', 'همراهانِ ما'), ITEMS('items', 'نشان‌ها', [IM('image', 'لوگو'), T('name', 'نام')], [{'image': '', 'name': 'نامِ اول'}, {'image': '', 'name': 'نامِ دوم'}, {'image': '', 'name': 'نامِ سوم'},
                                                                                                       {'image': '', 'name': 'نامِ چهارم'}, {'image': '', 'name': 'نامِ پنجم'}], 'name', 'افزودنِ نشان')],
      """<p class="nbc-lg-t" data-s="title"></p><div class="nbc-mq nbc-lg"><div class="nbc-mq-track"><!--each:items--><figure class="nbc-lg-i"><img data-i="image" data-alt="name"><figcaption data-s="name"></figcaption></figure><!--/each--></div>"""
      """<div class="nbc-mq-track" aria-hidden="true"><!--each:items.dup--><figure class="nbc-lg-i"><img data-i="image" data-alt="name"><figcaption data-s="name"></figcaption></figure><!--/each--></div></div>""",
      """.nbc-logos-marquee{padding-block:clamp(28px,4vw,48px)}.nbc-lg-t{text-align:center;color:var(--ink-3);font-weight:600;margin:0 0 20px}
.nbc-lg{--gap:48px;-webkit-mask-image:linear-gradient(90deg,transparent,#000 12%,#000 88%,transparent);mask-image:linear-gradient(90deg,transparent,#000 12%,#000 88%,transparent)}
.nbc-lg-i{margin:0;display:flex;align-items:center;gap:8px;white-space:nowrap;color:var(--ink-2);font-weight:700;font-family:var(--nb-font-head,inherit);font-size:1.15rem;opacity:.75;transition:opacity .2s}
.nbc-lg-i:hover{opacity:1}.nbc-lg-i img{height:34px;width:auto;max-width:150px;object-fit:contain;filter:grayscale(1)}.nbc-lg-i:hover img{filter:none}
.nbc-lg-i:has(img) figcaption{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0)}""",
      'نوار لوگو نشان همکاران مشتریان متحرک مارکی', 'minimalism corporate-clean aurora dark-luxury swiss bento-grid', uses='mq',
      src=PV.adapted('magicui', 'apps/www/registry/example/marquee-logos.tsx', 'marquee',
                     'ردیفِ لوگوها در Marquee (دو نسخهٔ هم‌جهت، --gap بزرگ‌تر، محوشدنِ دو سر با mask)؛ برای RTL جهتِ حرکت برعکس و با reduced-motion متوقف')),

    C('gallery_before_after', 'gallery', 'قبل و بعد', 'هر ردیف دو عکسِ کنارِ هم با برچسبِ «قبل» و «بعد»؛ برای نشان‌دادنِ نتیجه',
      _HEAD + [ITEMS('items', 'ردیف‌ها', [IM('before', 'عکسِ قبل'), IM('after', 'عکسِ بعد'), T('before_label', 'برچسبِ قبل', 'قبل'), T('after_label', 'برچسبِ بعد', 'بعد'), T('caption', 'زیرنویس'), T('alt', 'توضیحِ عکس‌ها')],
                     [{'before': '', 'after': '', 'before_label': 'قبل', 'after_label': 'بعد', 'caption': '', 'alt': ''}, {'before': '', 'after': '', 'before_label': 'قبل', 'after_label': 'بعد', 'caption': '', 'alt': ''}],
                     'caption', 'افزودنِ ردیف')],
      _HEADHTML + """<div class="nbc-grid nbc-c2 nbc-ba"><!--each:items--><figure class="nbc-card nbc-ba-i"><div class="nbc-ba-pair"><div><img class="nbc-img" data-i="before" data-alt="alt"><span class="nbc-pill" data-s="before_label"></span></div>"""
      """<div><img class="nbc-img" data-i="after" data-alt="alt"><span class="nbc-pill is-hot" data-s="after_label"></span></div></div><figcaption class="nbc-muted" data-s="caption"></figcaption></figure><!--/each--></div>""",
      """.nbc-ba-i{margin:0;display:grid;gap:12px}.nbc-ba-pair{display:grid;grid-template-columns:1fr 1fr;gap:8px}.nbc-ba-pair>div{position:relative;overflow:hidden;border-radius:calc(var(--st-card-r,var(--r,16px)) - 4px);background:color-mix(in srgb,var(--ink) 6%,var(--card));min-height:120px}
.nbc-ba-pair img{aspect-ratio:3/4;border-radius:0}.nbc-ba-pair .nbc-pill{position:absolute;inset-block-start:10px;inset-inline-start:10px;background:rgba(0,0,0,.6);color:#fff;font-size:.78rem}
.nbc-ba-pair .nbc-pill.is-hot{background:var(--brand);color:var(--brand-ink,#fff)}.nbc-ba-i figcaption:empty{display:none}.nbc-ba-i figcaption{text-align:center}""",
      'گالری قبل و بعد نتیجه تحول مقایسه عکس', 'corporate-clean soft-pastel bento-grid organic minimalism'),
]
