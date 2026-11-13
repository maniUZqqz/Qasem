# -*- coding: utf-8 -*-
"""سربرگ‌های بزرگِ ابتدای صفحه (۶ قطعه). متن‌های پیش‌فرض نمونه‌اند و باید با متنِ واقعی عوض شوند."""
from . import provenance as PV
from .spec import A, C, IC, IM, ITEMS, L, T

_BTNS2 = """<div class="nbc-btns"><a class="nbc-btn" data-s="btn1" data-h="btn1_link"></a><a class="nbc-btn is-alt" data-s="btn2" data-h="btn2_link"></a></div>"""
_COPY = [T('title', 'تیتر', 'تیترِ اصلیِ صفحه را این‌جا بنویس'), A('subtitle', 'توضیح', 'در یکی دو جمله بگو چه می‌کنی و مشتری چه سودی می‌برد.'),
         T('btn1', 'دکمهٔ اول', 'شروع کنید'), L('btn1_link', 'پیوندِ دکمهٔ اول'), T('btn2', 'دکمهٔ دوم', 'بیشتر بدانید'), L('btn2_link', 'پیوندِ دکمهٔ دوم')]

SPECS = [
    C('hero_center_glow', 'hero', 'سربرگِ وسط‌چین با درخششِ پس‌زمینه', 'تیترِ بزرگِ وسط، دو دکمه و هالهٔ نورانی از رنگِ اصلی',
      [T('kicker', 'نوشتهٔ کوچکِ بالا', 'تازه‌ترین نسخه')] + _COPY + [T('note', 'یادداشتِ زیرِ دکمه‌ها', 'بدونِ نیاز به کارتِ اعتباری')],
      """<div class="nbc-hcg"><span class="nbc-pill" data-s="kicker"></span><h1 class="nbc-title" data-s="title"></h1><p class="nbc-lead" data-s="subtitle|m"></p>"""
      + _BTNS2 + """<p class="nbc-muted" data-s="note"></p></div>""",
      """.nbc-hero-center-glow{overflow:hidden;padding-block:clamp(70px,11vw,140px)}
.nbc-hero-center-glow::before{content:"";position:absolute;inset:-25% 8% auto;height:75%;background:radial-gradient(closest-side,color-mix(in srgb,var(--brand) 36%,transparent),transparent 72%);filter:blur(12px);pointer-events:none}
.nbc-hcg{position:relative;max-width:800px;margin-inline:auto;text-align:center}
.nbc-hcg .nbc-title{font-size:clamp(2.1rem,6vw,3.9rem);line-height:1.2}
.nbc-hcg .nbc-lead{margin-inline:auto}.nbc-hcg .nbc-btns{justify-content:center}.nbc-hcg .nbc-muted{margin-top:16px}
.nbc-hcg .nbc-pill{margin-bottom:18px;color:var(--brand)}""",
      'سربرگ هیرو بالای صفحه وسط درخشش', 'glassmorphism aurora bento-grid corporate-clean soft-pastel'),

    C('hero_split_media', 'hero', 'سربرگِ متن و تصویر', 'متن و فهرستِ مزیت‌ها در یک سو، تصویر در سوی دیگر',
      [T('kicker', 'نوشتهٔ کوچکِ بالا', 'معرفی')] + _COPY + [
          ITEMS('bullets', 'مزیت‌ها', [IC('icon', 'نماد', 'check'), T('text', 'متن')],
                [{'icon': 'check', 'text': 'مزیتِ اولِ کوتاه'}, {'icon': 'check', 'text': 'مزیتِ دوم'}, {'icon': 'check', 'text': 'مزیتِ سوم'}], 'text', 'افزودنِ مزیت'),
          IM('image', 'تصویر'), T('image_alt', 'توضیحِ تصویر')],
      """<div class="nbc-split nbc-hsm"><div class="nbc-hsm-copy"><span class="nbc-kicker" data-s="kicker"></span><h1 class="nbc-title" data-s="title"></h1><p class="nbc-lead" data-s="subtitle|m"></p>"""
      """<ul class="nbc-list"><!--each:bullets--><li><span class="nbc-check" data-ic="icon"></span><span data-s="text"></span></li><!--/each--></ul>"""
      """<div class="nbc-btns nbc-hsm-btns"><a class="nbc-btn" data-s="btn1" data-h="btn1_link"></a><a class="nbc-btn is-alt" data-s="btn2" data-h="btn2_link"></a></div></div>"""
      """<div class="nbc-hsm-media"><img class="nbc-img" data-i="image" data-alt="image_alt"></div></div>""",
      """.nbc-hero-split-media{padding-block:clamp(56px,8vw,110px)}
.nbc-hsm-btns{margin-top:26px}.nbc-hsm .nbc-lead{margin-bottom:18px}
.nbc-hsm-media img{aspect-ratio:5/4;box-shadow:var(--st-card-sh,0 30px 70px -34px rgba(0,0,0,.5))}
.nbc-hsm-media:empty{display:none}.nbc-hsm:has(.nbc-hsm-media:empty){grid-template-columns:minmax(0,1fr)}""",
      'سربرگ هیرو تصویر کنار متن', 'bento-grid corporate-clean soft-pastel organic claymorphism'),

    C('hero_media_frame', 'hero', 'سربرگِ وسط‌چین با قابِ پنجره', 'متنِ وسط و زیرش تصویر یا نمایی از محصول در قابِ پنجره',
      [T('kicker', 'نوشتهٔ کوچکِ بالا', 'محصولِ ما')] + _COPY + [IM('image', 'تصویرِ محصول'), T('image_alt', 'توضیحِ تصویر')],
      """<div class="nbc-hmf"><div class="nbc-hmf-copy"><span class="nbc-pill" data-s="kicker"></span><h1 class="nbc-title" data-s="title"></h1><p class="nbc-lead" data-s="subtitle|m"></p>"""
      + _BTNS2 + """</div><div class="nbc-hmf-frame"><div class="nbc-hmf-bar"><i></i><i></i><i></i></div><img class="nbc-img" data-i="image" data-alt="image_alt"></div></div>""",
      """.nbc-hero-media-frame{padding-block:clamp(60px,9vw,120px)}
.nbc-hmf-copy{max-width:760px;margin:0 auto;text-align:center}.nbc-hmf-copy .nbc-lead{margin-inline:auto}.nbc-hmf-copy .nbc-btns{justify-content:center}
.nbc-hmf-copy .nbc-pill{margin-bottom:16px;color:var(--brand)}
.nbc-hmf-frame{max-width:980px;margin:clamp(34px,5vw,56px) auto 0;border:var(--st-card-bd,1px solid var(--line));border-radius:calc(var(--r,16px) + 4px);overflow:hidden;background:var(--card);box-shadow:0 40px 90px -40px rgba(0,0,0,.5)}
.nbc-hmf-bar{display:flex;gap:6px;padding:11px 14px;background:color-mix(in srgb,var(--ink) 6%,var(--card));border-bottom:1px solid var(--line)}
.nbc-hmf-bar i{width:10px;height:10px;border-radius:50%;background:color-mix(in srgb,var(--ink) 22%,transparent)}
.nbc-hmf-frame .nbc-img{border-radius:0;aspect-ratio:16/9}.nbc-hmf-frame:not(:has(img)) .nbc-hmf-bar{border-bottom:0}""",
      'سربرگ هیرو قاب پنجره مرورگر محصول اپ', 'glassmorphism aurora bento-grid corporate-clean'),

    C('hero_minimal_type', 'hero', 'سربرگِ تایپوگرافیِ درشت', 'تیترِ بسیار درشت و ابتدای‌خط، با خطِ جداکننده؛ بدونِ تصویر',
      [T('kicker', 'نوشتهٔ کوچکِ بالا', 'استودیو'), A('title', 'تیتر', 'ایده‌های ساده\nنتیجه‌های بزرگ'),
       A('subtitle', 'توضیح', 'یک پاراگرافِ کوتاه دربارهٔ کار و نگاهِ تو.'), T('btn', 'پیوند', 'دیدنِ نمونه‌کارها'), L('btn_link', 'نشانیِ پیوند')],
      """<div class="nbc-hmt"><span class="nbc-kicker" data-s="kicker"></span><h1 class="nbc-hmt-title" data-s="title|m"></h1>"""
      """<div class="nbc-hmt-row"><p class="nbc-lead" data-s="subtitle|m"></p><a class="nbc-link nbc-hmt-link" data-s="btn" data-h="btn_link"></a></div></div>""",
      r""".nbc-hero-minimal-type{padding-block:clamp(70px,11vw,150px)}
.nbc-hmt-title{font-family:var(--nb-font-head,inherit);font-size:clamp(2.6rem,9vw,6.4rem);font-weight:var(--st-head-w,800);line-height:1.08;letter-spacing:-.02em;margin:0 0 clamp(26px,4vw,44px)}
.nbc-hmt-row{display:flex;flex-wrap:wrap;gap:20px 48px;align-items:end;justify-content:space-between;border-top:2px solid var(--ink);padding-top:22px}
.nbc-hmt-row .nbc-lead{margin:0;max-width:46ch}
.nbc-hmt-link{font-weight:700;font-size:1.05rem;opacity:1;white-space:nowrap}.nbc-hmt-link::after{content:"\2190";margin-inline-start:10px}""",
      'سربرگ هیرو مینیمال تیتر درشت تایپوگرافی', 'minimalism swiss editorial dark-luxury'),

    C('hero_stats_bar', 'hero', 'سربرگِ وسط‌چین با نوارِ آمار', 'تیتر و دکمه‌ها، و زیرشان نوارِ چند عدد (عددها را خودت بنویس)',
      _COPY + [ITEMS('stats', 'عددها', [T('value', 'عدد', '۰۰'), T('label', 'عنوان', 'عنوانِ آمار')],
                     [{'value': '۰۰', 'label': 'عنوانِ آمارِ اول'}, {'value': '۰۰', 'label': 'عنوانِ آمارِ دوم'}, {'value': '۰۰', 'label': 'عنوانِ آمارِ سوم'}],
                     'label', 'افزودنِ عدد')],
      """<div class="nbc-hsb"><h1 class="nbc-title" data-s="title"></h1><p class="nbc-lead" data-s="subtitle|m"></p>""" + _BTNS2
      + """<ul class="nbc-hsb-stats"><!--each:stats--><li><b data-s="value"></b><span data-s="label"></span></li><!--/each--></ul></div>""",
      """.nbc-hero-stats-bar{padding-block:clamp(64px,10vw,124px)}
.nbc-hsb{max-width:860px;margin-inline:auto;text-align:center}.nbc-hsb .nbc-lead{margin-inline:auto}.nbc-hsb .nbc-btns{justify-content:center}
.nbc-hsb-stats{list-style:none;margin:clamp(34px,5vw,56px) 0 0;padding:22px 10px;display:flex;flex-wrap:wrap;justify-content:center;gap:18px 8px;border-top:1px solid var(--line)}
.nbc-hsb-stats li{flex:1 1 150px;display:grid;gap:4px}.nbc-hsb-stats b{font-family:var(--nb-font-head,inherit);font-size:clamp(1.8rem,4vw,2.6rem);color:var(--brand);line-height:1.2}
.nbc-hsb-stats span{color:var(--ink-3);font-size:.9rem}""",
      'سربرگ هیرو آمار عدد نوار', 'corporate-clean minimalism bento-grid swiss'),

    C('hero_gradient_banner', 'hero', 'بنرِ گرادیانیِ گرد با نشان‌ها', 'قابِ بزرگِ گرادیانی با تیتر، دو دکمه و چند نشانِ کوچک',
      _COPY + [ITEMS('badges', 'نشان‌ها', [T('text', 'متن')], [{'text': 'ویژگیِ اول'}, {'text': 'ویژگیِ دوم'}, {'text': 'ویژگیِ سوم'}], 'text', 'افزودنِ نشان')],
      """<div class="nbc-hgb"><h1 class="nbc-title" data-s="title"></h1><p class="nbc-lead" data-s="subtitle|m"></p>"""
      """<div class="nbc-btns"><a class="nbc-btn is-light" data-s="btn1" data-h="btn1_link"></a><a class="nbc-btn is-ghost" data-s="btn2" data-h="btn2_link"></a></div>"""
      """<ul class="nbc-hgb-badges"><!--each:badges--><li class="nbc-pill" data-s="text"></li><!--/each--></ul></div>""",
      """.nbc-hero-gradient-banner{padding-block:clamp(34px,5vw,64px)}
.nbc-hgb{position:relative;overflow:hidden;text-align:center;color:var(--brand-ink,#fff);padding:clamp(40px,7vw,96px) clamp(20px,5vw,64px);border-radius:calc(var(--r,16px) + 14px);
background:radial-gradient(60% 80% at 85% 0,color-mix(in srgb,var(--brand) 40%,#fff) 0,transparent 60%),linear-gradient(135deg,var(--brand),color-mix(in srgb,var(--brand) 50%,#0b1020))}
.nbc-hgb .nbc-lead{color:inherit;opacity:.9;margin-inline:auto}.nbc-hgb .nbc-btns{justify-content:center}
.nbc-hgb-badges{list-style:none;margin:30px 0 0;padding:0;display:flex;flex-wrap:wrap;gap:10px;justify-content:center}
.nbc-hgb .nbc-pill{background:rgba(255,255,255,.16);color:inherit}""",
      'سربرگ هیرو بنر گرادیان نشان', 'aurora glassmorphism soft-pastel retro-y2k claymorphism'),

    C('hero_video_thumb', 'hero', 'سربرگِ وسط‌چین با تصویرِ ویدیو', 'متنِ وسط و زیرش تصویرِ ویدیو با دکمهٔ پخش؛ با کلیک ویدیو (آپارات، یوتیوب یا فایل) باز می‌شود',
      [T('kicker', 'نوشتهٔ کوچکِ بالا', 'ویدیوی معرفی')] + _COPY + [IM('image', 'تصویرِ روی ویدیو'), T('image_alt', 'توضیحِ تصویر'), L('video_link', 'نشانیِ ویدیو'), T('play_label', 'نوشتهٔ دکمهٔ پخش', 'پخشِ ویدیو')],
      """<div class="nbc-hvt"><div class="nbc-hvt-copy"><span class="nbc-pill" data-s="kicker"></span><h1 class="nbc-title" data-s="title"></h1><p class="nbc-lead" data-s="subtitle|m"></p>"""
      + _BTNS2 + """</div><a class="nbc-hvt-media" data-href="video_link"><img class="nbc-img" data-i="image" data-alt="image_alt"><span class="nbc-hvt-play" aria-hidden="true"><i></i></span>"""
      """<span class="nbc-hvt-label" data-s="play_label"></span></a></div>""",
      """.nbc-hero-video-thumb{padding-block:clamp(56px,9vw,112px)}.nbc-hvt-copy{max-width:780px;margin:0 auto clamp(28px,5vw,52px);text-align:center}
.nbc-hvt-copy .nbc-lead{margin-inline:auto}.nbc-hvt-copy .nbc-btns{justify-content:center}.nbc-hvt-copy .nbc-pill{margin-bottom:16px;color:var(--brand)}.nbc-hvt-copy .nbc-title{font-size:clamp(2rem,5.4vw,3.5rem);line-height:1.22}
.nbc-hvt-media{position:relative;display:block;max-width:960px;margin-inline:auto;border-radius:var(--st-card-r,var(--r,16px));overflow:hidden;text-decoration:none;color:#fff;
background:linear-gradient(135deg,color-mix(in srgb,var(--brand) 70%,#000),color-mix(in srgb,var(--brand) 30%,#000));aspect-ratio:16/9;border:var(--st-card-bd,1px solid var(--line));box-shadow:var(--st-card-sh,0 30px 70px -34px rgba(0,0,0,.55))}
.nbc-hvt-media img{position:absolute;inset:0;width:100%;height:100%;border-radius:0;object-fit:cover;transition:filter .2s}.nbc-hvt-media:hover img{filter:brightness(.8)}
.nbc-hvt-play{position:absolute;inset:0;display:grid;place-items:center;transition:transform .2s}.nbc-hvt-media:hover .nbc-hvt-play{transform:scale(1.07)}
.nbc-hvt-play::before{content:"";width:104px;height:104px;border-radius:50%;background:rgba(255,255,255,.14);-webkit-backdrop-filter:blur(10px);backdrop-filter:blur(10px)}
.nbc-hvt-play i{position:absolute;width:72px;height:72px;border-radius:50%;background:linear-gradient(180deg,color-mix(in srgb,var(--brand) 70%,#fff),var(--brand));box-shadow:0 12px 28px -8px rgba(0,0,0,.5)}
.nbc-hvt-play i::after{content:"";position:absolute;top:23px;left:29px;border-block:13px solid transparent;border-left:21px solid #fff}
.nbc-hvt-label{position:absolute;inset-inline:0;inset-block-end:14px;text-align:center;font-weight:700;text-shadow:0 1px 8px rgba(0,0,0,.6)}.nbc-hvt-label:empty{display:none}""",
      'سربرگ هیرو ویدیو پخش دکمه پلی تصویر', 'glassmorphism aurora corporate-clean bento-grid dark-luxury',
      src=PV.adapted('magicui', 'apps/www/registry/magicui/hero-video-dialog.tsx', 'hero-video-dialog',
                     'تصویرِ بندانگشتی با دکمهٔ پخشِ شیشه‌ای و تیره‌شدن در hover از HeroVideoDialog؛ پنجرهٔ بازشونده (framer-motion) برداشته شد و کلیک پیوندِ ویدیو را باز می‌کند')),
]
