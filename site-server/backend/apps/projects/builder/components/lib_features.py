# -*- coding: utf-8 -*-
"""ویژگی‌ها (۶ قطعه)، گام‌ها و روند (۲ قطعه) و پرسش‌های پرتکرار (۱ قطعه)."""
from . import provenance as PV
from .spec import A, C, IC, IM, ITEMS, L, T

_HEAD = [T('title', 'تیتر', 'چرا ما؟'), A('subtitle', 'توضیح', 'چند دلیل برای این‌که با خیالِ راحت انتخابمان کنی')]
_HEADHTML = """<div class="nbc-head"><h2 class="nbc-title" data-s="title"></h2><p class="nbc-lead" data-s="subtitle|m"></p></div>"""
_FEAT = [IC('icon', 'نماد', 'zap'), T('title', 'عنوان'), A('text', 'توضیح')]
_FEAT_ROWS = [{'icon': 'zap', 'title': 'سریع', 'text': 'کارت را در کم‌ترین زمان انجام می‌دهیم.'},
              {'icon': 'shield', 'title': 'مطمئن', 'text': 'کیفیت را حفظ می‌کنیم و کنارت می‌مانیم.'},
              {'icon': 'heart', 'title': 'با حوصله', 'text': 'به هر پرسشی با دقت جواب می‌دهیم.'}]

SPECS = [
    C('feat_icon_grid', 'features', 'کارت‌های نماد‌دار', 'شبکهٔ کارت‌ها با نماد، عنوان و توضیحِ کوتاه',
      _HEAD + [ITEMS('items', 'کارت‌ها', _FEAT, _FEAT_ROWS, 'title', 'افزودنِ کارت')],
      _HEADHTML + """<div class="nbc-grid nbc-auto"><!--each:items--><article class="nbc-card nbc-fig-i"><span class="nbc-ic" data-ic="icon"></span><h3 class="nbc-h3" data-s="title"></h3><p class="nbc-text" data-s="text|m"></p></article><!--/each--></div>""",
      """.nbc-fig-i{display:grid;gap:4px;align-content:start;transition:transform .18s,box-shadow .18s}.nbc-fig-i .nbc-ic{margin-bottom:12px}
.nbc-fig-i:hover{transform:translateY(-3px)}""",
      'ویژگی مزیت کارت نماد چرا ما', 'glassmorphism claymorphism soft-pastel bento-grid corporate-clean organic'),

    C('feat_alternating', 'features', 'ردیف‌های تصویر و متنِ متناوب', 'هر ویژگی یک ردیف: یک بار تصویر کنارِ متن، بار بعد برعکس',
      _HEAD + [ITEMS('items', 'ردیف‌ها', [T('title', 'عنوان', 'عنوانِ ویژگی'), A('text', 'توضیح', 'توضیحِ کامل‌تر دربارهٔ این ویژگی و سودی که برای مشتری دارد.'),
                                          T('link_text', 'متنِ پیوند', 'بیشتر بخوان'), L('link', 'نشانیِ پیوند'), IM('image', 'تصویر'), T('image_alt', 'توضیحِ تصویر')],
                     [{'title': 'ویژگیِ اول', 'text': 'توضیحِ کامل‌تر دربارهٔ این ویژگی و سودی که برای مشتری دارد.', 'link_text': 'بیشتر بخوان', 'link': '#', 'image': '', 'image_alt': ''},
                      {'title': 'ویژگیِ دوم', 'text': 'توضیحِ کامل‌تر دربارهٔ این ویژگی و سودی که برای مشتری دارد.', 'link_text': 'بیشتر بخوان', 'link': '#', 'image': '', 'image_alt': ''}],
                     'title', 'افزودنِ ردیف')],
      _HEADHTML + """<div class="nbc-alt"><!--each:items--><article class="nbc-split nbc-alt-row"><div class="nbc-alt-copy"><h3 class="nbc-title nbc-alt-t" data-s="title"></h3><p class="nbc-lead" data-s="text|m"></p>"""
      """<a class="nbc-link nbc-arrow" data-s="link_text" data-h="link"></a></div><div class="nbc-alt-media"><img class="nbc-img" data-i="image" data-alt="image_alt"></div></article><!--/each--></div>""",
      r""".nbc-alt{display:grid;gap:clamp(36px,6vw,80px)}.nbc-alt-t{font-size:clamp(1.4rem,3vw,2rem)}
.nbc-alt-row:nth-child(even) .nbc-alt-copy{order:2}.nbc-alt-media img{aspect-ratio:4/3}
.nbc-alt-media:empty{display:none}.nbc-alt-row:has(.nbc-alt-media:empty){grid-template-columns:minmax(0,1fr)}
.nbc-arrow{font-weight:700;color:var(--brand);opacity:1}.nbc-arrow::after{content:"\2190";margin-inline-start:8px}
@media (max-width:760px){.nbc-alt-row:nth-child(even) .nbc-alt-copy{order:0}}""",
      'ویژگی ردیف تصویر متن متناوب', 'corporate-clean minimalism editorial organic'),

    C('feat_checklist_split', 'features', 'متن و فهرستِ تیک‌دار', 'تیتر و دکمه در یک سو و فهرستِ تیک‌دارِ مزیت‌ها در قابی در سوی دیگر',
      [T('kicker', 'نوشتهٔ کوچکِ بالا', 'مزیت‌ها'), T('title', 'تیتر', 'آنچه می‌گیری'), A('subtitle', 'توضیح', 'یک توضیحِ کوتاه دربارهٔ فهرستِ کنارش.'),
       T('btn', 'متنِ دکمه', 'شروع کنید'), L('btn_link', 'پیوندِ دکمه'),
       ITEMS('items', 'مزیت‌ها', [IC('icon', 'نماد', 'check'), T('text', 'متن')],
             [{'icon': 'check', 'text': 'مزیتِ اول'}, {'icon': 'check', 'text': 'مزیتِ دوم'}, {'icon': 'check', 'text': 'مزیتِ سوم'}, {'icon': 'check', 'text': 'مزیتِ چهارم'}],
             'text', 'افزودنِ مزیت')],
      """<div class="nbc-split nbc-fcs"><div><span class="nbc-kicker" data-s="kicker"></span><h2 class="nbc-title" data-s="title"></h2><p class="nbc-lead" data-s="subtitle|m"></p>"""
      """<a class="nbc-btn" data-s="btn" data-h="btn_link"></a></div><div class="nbc-card nbc-fcs-box"><ul class="nbc-list"><!--each:items--><li><span class="nbc-check" data-ic="icon"></span><span data-s="text"></span></li><!--/each--></ul></div></div>""",
      """.nbc-fcs-box .nbc-list{gap:16px}.nbc-fcs-box li{font-size:1.02rem;padding-bottom:14px;border-bottom:1px dashed var(--line)}.nbc-fcs-box li:last-child{border:0;padding:0}""",
      'ویژگی فهرست تیک مزیت', 'corporate-clean glassmorphism bento-grid soft-pastel'),

    C('feat_bento_mosaic', 'features', 'موزاییکِ بنتو', 'کاشی‌هایی با اندازهٔ نامساوی؛ اولی بزرگ‌تر است (۳ تا ۶ مورد)',
      _HEAD + [ITEMS('items', 'کاشی‌ها', _FEAT, _FEAT_ROWS + [{'icon': 'star', 'title': 'ویژگیِ چهارم', 'text': 'توضیحِ کوتاه.'}], 'title', 'افزودنِ کاشی')],
      _HEADHTML + """<div class="nbc-bm"><!--each:items--><article class="nbc-bm-t"><span class="nbc-ic" data-ic="icon"></span><h3 class="nbc-h3" data-s="title"></h3><p class="nbc-text" data-s="text|m"></p></article><!--/each--></div>""",
      """.nbc-bm{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));grid-auto-flow:dense;gap:var(--st-gap,16px)}
.nbc-bm-t{display:grid;gap:6px;align-content:end;min-height:190px;padding:clamp(20px,2.6vw,30px);border-radius:var(--st-card-r,calc(var(--r,16px) + 8px));background:var(--st-card-bg,var(--card));color:var(--ink);
border:var(--st-card-bd,1px solid var(--line));box-shadow:var(--st-card-sh,none);-webkit-backdrop-filter:var(--st-bf,none);backdrop-filter:var(--st-bf,none);transition:transform .2s}
.nbc-bm-t:hover{transform:translateY(-3px)}.nbc-bm-t .nbc-ic{margin-bottom:auto;justify-self:start}
.nbc-bm-t:nth-child(1){grid-column:span 2;grid-row:span 2;background:linear-gradient(150deg,color-mix(in srgb,var(--brand) 18%,var(--card)),var(--card))}.nbc-bm-t:nth-child(1) .nbc-h3{font-size:1.6rem}
.nbc-bm-t:nth-child(4):last-child{grid-column:1/-1}.nbc-bm-t:nth-child(5):last-child{grid-column:span 2}
.nbc-bm-t:first-child:nth-last-child(2){grid-row:auto}
@media (max-width:900px){.nbc-bm{grid-template-columns:repeat(2,minmax(0,1fr))}.nbc-bm-t:nth-child(1){grid-column:1/-1;grid-row:auto}.nbc-bm-t:nth-child(4):last-child,.nbc-bm-t:nth-child(5):last-child{grid-column:auto}}
@media (max-width:560px){.nbc-bm{grid-template-columns:minmax(0,1fr)}}""",
      'ویژگی بنتو موزاییک کاشی شبکه', 'bento-grid aurora glassmorphism corporate-clean'),

    C('feat_stat_cards', 'features', 'کارت‌های عددی', 'چند عددِ درشت با عنوان و توضیحِ کوتاه (عددها را خودت بنویس)',
      _HEAD + [ITEMS('items', 'عددها', [T('value', 'عدد', '۰۰'), T('title', 'عنوان'), A('text', 'توضیح')],
                     [{'value': '۰۰', 'title': 'عنوانِ اول', 'text': 'توضیحِ کوتاه'}, {'value': '۰۰', 'title': 'عنوانِ دوم', 'text': 'توضیحِ کوتاه'},
                      {'value': '۰۰', 'title': 'عنوانِ سوم', 'text': 'توضیحِ کوتاه'}], 'title', 'افزودنِ عدد')],
      _HEADHTML + """<div class="nbc-grid nbc-auto"><!--each:items--><article class="nbc-card nbc-sc-i"><b class="nbc-sc-n" data-s="value"></b><h3 class="nbc-h3" data-s="title"></h3><p class="nbc-text" data-s="text|m"></p></article><!--/each--></div>""",
      """.nbc-sc-i{display:grid;gap:2px;align-content:start}.nbc-sc-n{font-family:var(--nb-font-head,inherit);font-size:clamp(2.2rem,5vw,3.4rem);line-height:1.15;color:var(--brand);margin-bottom:8px}""",
      'ویژگی آمار عدد کارت', 'corporate-clean swiss minimalism bento-grid'),

    C('feat_icon_rows', 'features', 'ردیف‌های نماد‌دارِ دو ستونه', 'ویژگی‌ها بی‌قاب و دو ستونه، نماد در ابتدای هر ردیف',
      _HEAD + [ITEMS('items', 'ویژگی‌ها', _FEAT, _FEAT_ROWS + [{'icon': 'star', 'title': 'ویژگیِ چهارم', 'text': 'توضیحِ کوتاه.'}], 'title', 'افزودنِ ویژگی')],
      _HEADHTML + """<div class="nbc-grid nbc-c2 nbc-fir"><!--each:items--><div class="nbc-fir-i"><span class="nbc-ic" data-ic="icon"></span><div><h3 class="nbc-h3" data-s="title"></h3><p class="nbc-text" data-s="text|m"></p></div></div><!--/each--></div>""",
      """.nbc-fir{gap:clamp(24px,4vw,44px) clamp(24px,5vw,64px)}.nbc-fir-i{display:flex;gap:16px;align-items:flex-start}""",
      'ویژگی ردیف نماد دو ستون', 'minimalism editorial swiss corporate-clean organic dark-luxury'),

    C('steps_horizontal', 'steps', 'گام‌های شماره‌دارِ افقی', 'روندِ کار در چند گام با شمارهٔ درشت و خطِ اتصال',
      [T('title', 'تیتر', 'چطور کار می‌کند؟'), A('subtitle', 'توضیح', 'در چند گامِ ساده شروع کن'),
       ITEMS('items', 'گام‌ها', [T('title', 'عنوان'), A('text', 'توضیح')],
             [{'title': 'گامِ اول', 'text': 'توضیحِ کوتاهِ گامِ اول.'}, {'title': 'گامِ دوم', 'text': 'توضیحِ کوتاهِ گامِ دوم.'}, {'title': 'گامِ سوم', 'text': 'توضیحِ کوتاهِ گامِ سوم.'}],
             'title', 'افزودنِ گام')],
      _HEADHTML + """<ol class="nbc-stp"><!--each:items--><li><span class="nbc-stp-n">{{n}}</span><h3 class="nbc-h3" data-s="title"></h3><p class="nbc-text" data-s="text|m"></p></li><!--/each--></ol>""",
      """.nbc-stp{list-style:none;margin:0;padding:0;display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,210px),1fr));gap:30px;position:relative;counter-reset:s}
.nbc-stp::before{content:"";position:absolute;inset-inline:6%;top:27px;border-top:2px dashed var(--line)}
.nbc-stp li{position:relative;text-align:center;display:grid;justify-items:center;gap:4px}
.nbc-stp-n{display:grid;place-items:center;width:56px;height:56px;border-radius:50%;background:var(--brand);color:var(--brand-ink,#fff);font-weight:800;font-size:1.3rem;margin-bottom:12px;position:relative;box-shadow:0 0 0 8px var(--bg)}
@media (max-width:640px){.nbc-stp::before{display:none}}""",
      'گام مرحله روند چگونه کار می کند شماره', 'corporate-clean bento-grid minimalism glassmorphism soft-pastel'),

    C('steps_timeline', 'steps', 'خطِ زمانیِ عمودی', 'گام‌ها زیرِ هم روی یک خطِ عمودی؛ مناسبِ روندِ طولانی‌تر',
      [T('title', 'تیتر', 'روندِ کار'), A('subtitle', 'توضیح', 'از اولین پیام تا تحویل'),
       ITEMS('items', 'گام‌ها', [T('title', 'عنوان'), A('text', 'توضیح')],
             [{'title': 'گامِ اول', 'text': 'توضیحِ گامِ اول.'}, {'title': 'گامِ دوم', 'text': 'توضیحِ گامِ دوم.'}, {'title': 'گامِ سوم', 'text': 'توضیحِ گامِ سوم.'},
              {'title': 'گامِ چهارم', 'text': 'توضیحِ گامِ چهارم.'}], 'title', 'افزودنِ گام')],
      _HEADHTML + """<ol class="nbc-tl"><!--each:items--><li><span class="nbc-tl-n">{{n}}</span><div class="nbc-tl-b"><h3 class="nbc-h3" data-s="title"></h3><p class="nbc-text" data-s="text|m"></p></div></li><!--/each--></ol>""",
      """.nbc-tl{list-style:none;margin:0 auto;padding:0;max-width:720px;position:relative;display:grid;gap:26px}
.nbc-tl::before{content:"";position:absolute;inset-block:8px;inset-inline-start:22px;border-inline-start:2px solid var(--line)}
.nbc-tl li{display:flex;gap:20px;align-items:flex-start;position:relative}
.nbc-tl-n{display:grid;place-items:center;flex:none;width:46px;height:46px;border-radius:50%;background:var(--brand);color:var(--brand-ink,#fff);font-weight:800;box-shadow:0 0 0 6px var(--bg);position:relative}
.nbc-tl-b{padding-top:6px}""",
      'گام مرحله روند خط زمانی تایم لاین', 'corporate-clean editorial minimalism swiss organic'),

    C('faq_two_col', 'faq', 'پرسش‌ها با ستونِ معرفی', 'تیتر و دکمهٔ تماس در یک سو و فهرستِ بازشونده در سوی دیگر',
      [T('title', 'تیتر', 'پرسش‌های پرتکرار'), A('subtitle', 'توضیح', 'جوابِ پرسشِ تو این‌جا نبود؟ بنویس تا کمکت کنیم.'),
       T('btn', 'متنِ دکمه', 'تماس با ما'), L('btn_link', 'پیوندِ دکمه'),
       ITEMS('items', 'پرسش‌ها', [T('q', 'پرسش'), A('a', 'پاسخ')],
             [{'q': 'چطور شروع کنم؟', 'a': 'از دکمهٔ تماس پیام بفرست تا راهنمایی‌ات کنیم.'}, {'q': 'زمانِ تحویل چقدر است؟', 'a': 'بسته به نوعِ کار؛ در پیام می‌گوییم.'},
              {'q': 'پشتیبانی دارید؟', 'a': 'بله؛ بعد از تحویل هم کنارت هستیم.'}], 'q', 'افزودنِ پرسش')],
      """<div class="nbc-split nbc-fq"><div><h2 class="nbc-title" data-s="title"></h2><p class="nbc-lead" data-s="subtitle|m"></p><a class="nbc-btn is-alt" data-s="btn" data-h="btn_link"></a></div>"""
      """<div class="nbc-fq-list"><!--each:items--><details class="nbc-fq-i" data-co><summary data-s="q"></summary><p class="nbc-text" data-s="a|m"></p></details><!--/each--></div></div>""",
      """.nbc-fq{align-items:start}.nbc-fq-list{display:grid;gap:10px}
.nbc-fq-i{background:var(--st-card-bg,var(--card));border:var(--st-card-bd,1px solid var(--line));border-radius:calc(var(--r,16px) - 4px);padding:4px 20px;color:var(--ink)}
.nbc-fq-i summary{cursor:pointer;font-weight:700;padding:14px 0;list-style:none;display:flex;justify-content:space-between;gap:12px;align-items:center}
.nbc-fq-i summary::-webkit-details-marker{display:none}.nbc-fq-i summary::after{content:"+";font-size:1.4rem;line-height:1;color:var(--brand);transition:transform .15s}
.nbc-fq-i[open] summary::after{transform:rotate(45deg)}.nbc-fq-i p{padding-bottom:16px}""",
      'پرسش پرتکرار سوالات متداول', 'corporate-clean minimalism bento-grid swiss editorial'),

    C('feat_bento_showcase', 'features', 'بنتوی با پیوندِ نمایشی', 'کاشی‌های بزرگ با نماد، عنوان و توضیح؛ با رفتنِ ماوس پیوند بالا می‌آید و نماد کوچک می‌شود',
      _HEAD + [ITEMS('items', 'کاشی‌ها', _FEAT + [T('link_text', 'متنِ پیوند', 'بیشتر بدانید'), L('link', 'نشانیِ پیوند')],
                     [dict(r, link_text='بیشتر بدانید', link='#') for r in (_FEAT_ROWS + [{'icon': 'star', 'title': 'ویژگیِ چهارم', 'text': 'توضیحِ کوتاه.'}])], 'title', 'افزودنِ کاشی')],
      _HEADHTML + """<div class="nbc-bs"><!--each:items--><article class="nbc-bs-i"><div class="nbc-bs-b"><span class="nbc-ic" data-ic="icon"></span><h3 class="nbc-h3" data-s="title"></h3><p class="nbc-text" data-s="text|m"></p></div>"""
      """<a class="nbc-link nbc-arrow nbc-bs-l" data-s="link_text" data-h="link"></a></article><!--/each--></div>""",
      r""".nbc-bs{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:var(--st-gap,16px);grid-auto-rows:minmax(230px,auto)}
.nbc-bs-i{position:relative;overflow:hidden;display:flex;flex-direction:column;justify-content:space-between;padding:clamp(20px,2.6vw,28px);background:var(--st-card-bg,var(--card));color:var(--ink);
border:var(--st-card-bd,1px solid var(--line));border-radius:var(--st-card-r,calc(var(--r,16px) + 6px));box-shadow:var(--st-card-sh,0 1px 2px rgba(0,0,0,.04),0 12px 30px -20px rgba(0,0,0,.25));-webkit-backdrop-filter:var(--st-bf,none);backdrop-filter:var(--st-bf,none)}
.nbc-bs-i:nth-child(1){grid-column:span 2}.nbc-bs-i:nth-child(4){grid-column:span 2}.nbc-bs-i:nth-child(n+5):nth-child(odd){grid-column:span 2}
.nbc-bs-b{display:grid;gap:6px;transition:transform .3s ease}.nbc-bs-b .nbc-ic{margin-bottom:10px;transform-origin:left center;transition:transform .3s ease}[dir=rtl] .nbc-bs-b .nbc-ic{transform-origin:right center}
.nbc-bs-l{margin-top:14px;font-weight:700;color:var(--brand);opacity:1;justify-self:start;transition:transform .3s ease,opacity .3s ease}.nbc-bs-l::after{content:"\2190";margin-inline-start:8px}
@media (hover:hover) and (min-width:1025px){.nbc a.nbc-link.nbc-bs-l{position:absolute;inset-inline-start:clamp(20px,2.6vw,28px);inset-block-end:18px;transform:translateY(34px);opacity:0}.nbc .nbc-bs-i:hover a.nbc-link.nbc-bs-l,.nbc .nbc-bs-i:focus-within a.nbc-link.nbc-bs-l{transform:none;opacity:1}
.nbc-bs-i:hover .nbc-bs-b{transform:translateY(-26px)}.nbc-bs-i:hover .nbc-bs-b .nbc-ic{transform:scale(.78)}}
@media (max-width:1024px){.nbc-bs{grid-template-columns:repeat(2,minmax(0,1fr))}.nbc .nbc-bs .nbc-bs-i:nth-child(n){grid-column:auto}.nbc .nbc-bs .nbc-bs-i:nth-child(1){grid-column:1/-1}}@media (max-width:620px){.nbc-bs{grid-template-columns:minmax(0,1fr)}.nbc .nbc-bs .nbc-bs-i:nth-child(n){grid-column:auto}}
@media (prefers-reduced-motion:reduce){.nbc-bs-b,.nbc-bs-l,.nbc-bs-b .nbc-ic{transition:none!important}}""",
      'ویژگی بنتو شبکه کاشی هاور پیوند', 'bento-grid aurora glassmorphism corporate-clean dark-luxury',
      src=PV.adapted('magicui', 'apps/www/registry/magicui/bento-grid.tsx', 'bento-grid',
                     'BentoGrid و BentoCard: شبکهٔ سه‌ستونه با کاشی‌های دوستونه، نمادی که با hover کوچک می‌شود، پیوندی که از پایین بالا می‌آید و سایهٔ لایه‌ای؛ بدونِ پس‌زمینهٔ متحرکِ هر کاشی؛ در گوشی همیشه پیدا')),

    C('faq_cards_grid', 'faq', 'پرسش‌ها در کارت‌های دوستونه', 'پرسش و پاسخ بدونِ بازشدن، در کارت‌هایی کنارِ هم؛ برای پاسخ‌های کوتاه',
      [T('title', 'تیتر', 'پرسش‌های پرتکرار'), A('subtitle', 'توضیح', ''),
       ITEMS('items', 'پرسش‌ها', [T('q', 'پرسش'), A('a', 'پاسخ')],
             [{'q': 'پرسشِ اول؟', 'a': 'پاسخِ کوتاه.'}, {'q': 'پرسشِ دوم؟', 'a': 'پاسخِ کوتاه.'}, {'q': 'پرسشِ سوم؟', 'a': 'پاسخِ کوتاه.'}, {'q': 'پرسشِ چهارم؟', 'a': 'پاسخِ کوتاه.'}], 'q', 'افزودنِ پرسش')],
      _HEADHTML + """<div class="nbc-grid nbc-c2 nbc-fg"><!--each:items--><article class="nbc-card nbc-fg-i"><h3 class="nbc-h3" data-s="q"></h3><p class="nbc-text" data-s="a|m"></p></article><!--/each--></div>""",
      """.nbc-fg-i{display:grid;gap:6px;align-content:start}.nbc-fg-i .nbc-h3::before{content:"؟";display:inline-grid;place-items:center;width:28px;height:28px;margin-inline-end:10px;border-radius:50%;background:var(--st-ic-bg,color-mix(in srgb,var(--brand) 14%,transparent));color:var(--brand);font-size:.95rem}""",
      'پرسش پرتکرار سوالات کارت دو ستون', 'bento-grid soft-pastel claymorphism neo-brutalism glassmorphism'),
]
