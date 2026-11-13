# -*- coding: utf-8 -*-
"""قیمت و بسته‌ها (۴ قطعه). قیمت‌های پیش‌فرض نمونه‌اند؛ قیمتِ واقعی را خودت بنویس."""
from .spec import A, C, L, T, TG, ITEMS

_HEAD = [T('title', 'تیتر', 'بسته‌ها'), A('subtitle', 'توضیح', 'بسته‌ای را انتخاب کن که با کارت جور است')]
_HEADHTML = """<div class="nbc-head"><h2 class="nbc-title" data-s="title"></h2><p class="nbc-lead" data-s="subtitle|m"></p></div>"""
_PLAN = [T('name', 'نامِ بسته'), T('price', 'قیمت'), T('period', 'دوره'), A('desc', 'توضیحِ کوتاه'), A('features', 'امکانات (هر خط یکی)'),
         T('button', 'متنِ دکمه'), L('link', 'پیوندِ دکمه'), TG('highlight', 'پیشنهادِ ویژه')]
_PLANS = [{'name': 'پایه', 'price': 'قیمتِ نمونه', 'period': 'ماهانه', 'desc': 'برای شروع', 'features': 'امکانِ اول\nامکانِ دوم', 'button': 'انتخاب', 'link': '#', 'highlight': False},
          {'name': 'حرفه‌ای', 'price': 'قیمتِ نمونه', 'period': 'ماهانه', 'desc': 'محبوب‌ترین', 'features': 'همهٔ امکاناتِ پایه\nامکانِ ویژه\nپشتیبانی', 'button': 'انتخاب', 'link': '#', 'highlight': True},
          {'name': 'سازمانی', 'price': 'تماس بگیرید', 'period': '', 'desc': 'برای تیم‌های بزرگ', 'features': 'همهٔ امکانات\nمشاورهٔ اختصاصی', 'button': 'تماس', 'link': '#', 'highlight': False}]

SPECS = [
    C('price_three_tier', 'pricing', 'سه بستهٔ کنارِ هم', 'کارت‌های بسته با نام، قیمت، امکانات و دکمه؛ یکی «پیشنهادِ ویژه» می‌شود',
      _HEAD + [ITEMS('items', 'بسته‌ها', _PLAN, _PLANS, 'name', 'افزودنِ بسته')],
      _HEADHTML + """<div class="nbc-grid nbc-auto nbc-pr"><!--each:items--><article class="nbc-card nbc-pr-i" data-ifc="highlight:is-hot"><h3 class="nbc-h3" data-s="name"></h3>"""
      """<div class="nbc-pr-price"><b data-s="price"></b><small data-s="period"></small></div><p class="nbc-muted" data-s="desc|m"></p><ul class="nbc-list" data-lines="features"></ul>"""
      """<a class="nbc-btn is-alt" data-s="button" data-h="link"></a></article><!--/each--></div>""",
      """.nbc-pr{align-items:stretch}.nbc-pr-i{display:flex;flex-direction:column;gap:10px;position:relative}
.nbc-pr-price{display:flex;align-items:baseline;gap:8px;flex-wrap:wrap}.nbc-pr-price b{font-family:var(--nb-font-head,inherit);font-size:clamp(1.5rem,3vw,2rem);color:var(--brand);line-height:1.3}
.nbc-pr-price small{color:var(--ink-3)}.nbc-pr-i .nbc-list{flex:1;margin:10px 0 14px}.nbc-pr-i .nbc-btn{width:100%}
.nbc-pr-i.is-hot{border:var(--st-hl-bd,2px solid var(--brand));box-shadow:var(--st-hl-sh,0 24px 50px -28px color-mix(in srgb,var(--brand) 70%,transparent));transform:translateY(-6px)}
.nbc-pr-i.is-hot .nbc-btn{background:var(--brand);color:var(--brand-ink,#fff)}
@media (max-width:640px){.nbc-pr-i.is-hot{transform:none}}""",
      'قیمت بسته تعرفه پلن سه بسته', 'corporate-clean glassmorphism bento-grid aurora soft-pastel'),

    C('price_single_focus', 'pricing', 'یک بستهٔ برجسته', 'یک بستهٔ بزرگ با قیمتِ درشت و امکاناتِ دو ستونه؛ برای محصولِ تک‌بسته‌ای',
      _HEAD + [T('name', 'نامِ بسته', 'بستهٔ کامل'), T('price', 'قیمت', 'قیمتِ نمونه'), T('period', 'دوره', 'یک‌بار پرداخت'), A('desc', 'توضیحِ کوتاه', 'همه‌چیز در یک بسته.'),
               A('features', 'امکانات (هر خط یکی)', 'امکانِ اول\nامکانِ دوم\nامکانِ سوم\nامکانِ چهارم'), T('button', 'متنِ دکمه', 'همین حالا شروع کن'), L('link', 'پیوندِ دکمه')],
      _HEADHTML + """<div class="nbc-card nbc-sf"><div class="nbc-sf-main"><h3 class="nbc-h3" data-s="name"></h3><div class="nbc-pr-price"><b data-s="price"></b><small data-s="period"></small></div>"""
      """<p class="nbc-muted" data-s="desc|m"></p><a class="nbc-btn" data-s="button" data-h="link"></a></div><ul class="nbc-list nbc-sf-list" data-lines="features"></ul></div>""",
      """.nbc-sf{display:grid;grid-template-columns:minmax(0,.9fr) minmax(0,1.1fr);gap:clamp(24px,5vw,56px);align-items:center;max-width:900px;margin-inline:auto;padding:clamp(24px,4vw,44px)}
.nbc-sf-main{display:grid;gap:12px;justify-items:start}.nbc-sf-main .nbc-pr-price b{font-size:clamp(2rem,5vw,3rem)}
.nbc-sf-list{gap:14px}@media (max-width:760px){.nbc-sf{grid-template-columns:minmax(0,1fr)}}""",
      'قیمت تک بسته برجسته', 'minimalism corporate-clean dark-luxury editorial swiss'),

    C('price_compare_table', 'pricing', 'جدولِ مقایسهٔ بسته‌ها', 'جدولی با سه ستونِ بسته و ردیف‌های امکانات (در خانه‌ها ✓ یا — بنویس)',
      _HEAD + [T('plan1', 'نامِ بستهٔ اول', 'پایه'), T('plan2', 'نامِ بستهٔ دوم', 'حرفه‌ای'), T('plan3', 'نامِ بستهٔ سوم', 'سازمانی'),
               ITEMS('rows', 'ردیف‌ها', [T('label', 'امکان'), T('v1', 'بستهٔ اول'), T('v2', 'بستهٔ دوم'), T('v3', 'بستهٔ سوم')],
                     [{'label': 'امکانِ اول', 'v1': '✓', 'v2': '✓', 'v3': '✓'}, {'label': 'امکانِ دوم', 'v1': '—', 'v2': '✓', 'v3': '✓'},
                      {'label': 'امکانِ سوم', 'v1': '—', 'v2': '—', 'v3': '✓'}], 'label', 'افزودنِ ردیف')],
      _HEADHTML + """<div class="nbc-tbl-wrap"><table class="nbc-tbl"><thead><tr><th></th><th data-s="plan1"></th><th data-s="plan2" class="is-hot"></th><th data-s="plan3"></th></tr></thead>"""
      """<tbody><!--each:rows--><tr><th data-s="label" data-keep></th><td data-s="v1" data-keep></td><td data-s="v2" data-keep class="is-hot"></td><td data-s="v3" data-keep></td></tr><!--/each--></tbody></table></div>""",
      """.nbc-tbl-wrap{overflow-x:auto;border:var(--st-card-bd,1px solid var(--line));border-radius:var(--st-card-r,var(--r,16px));background:var(--st-card-bg,var(--card));-webkit-backdrop-filter:var(--st-bf,none);backdrop-filter:var(--st-bf,none)}
.nbc-tbl{width:100%;border-collapse:collapse;min-width:520px;color:var(--ink)}
.nbc-tbl th,.nbc-tbl td{padding:15px 18px;text-align:center;border-bottom:1px solid var(--line)}
.nbc-tbl thead th{font-family:var(--nb-font-head,inherit);font-size:1.05rem;background:color-mix(in srgb,var(--ink) 4%,transparent)}
.nbc-tbl tbody th{text-align:start;font-weight:600;color:var(--ink-2)}.nbc-tbl tr:last-child>*{border-bottom:0}
.nbc-tbl .is-hot{background:color-mix(in srgb,var(--brand) 9%,transparent);color:var(--brand);font-weight:700}""",
      'قیمت جدول مقایسه بسته ها', 'corporate-clean minimalism swiss editorial'),

    C('price_packs', 'pricing', 'بسته‌های کوچکِ شارژ', 'چهار کارتِ کوچک برای بسته‌های شارژ یا اعتبار (مقدار، قیمت و دکمه)',
      _HEAD + [ITEMS('items', 'بسته‌ها', [T('name', 'نام'), T('amount', 'مقدار'), T('price', 'قیمت'), T('note', 'یادداشت'), T('button', 'متنِ دکمه'), L('link', 'پیوندِ دکمه'), TG('highlight', 'برجسته')],
                     [{'name': 'کوچک', 'amount': 'مقدارِ نمونه', 'price': 'قیمتِ نمونه', 'note': '', 'button': 'خرید', 'link': '#', 'highlight': False},
                      {'name': 'متوسط', 'amount': 'مقدارِ نمونه', 'price': 'قیمتِ نمونه', 'note': 'محبوب', 'button': 'خرید', 'link': '#', 'highlight': True},
                      {'name': 'بزرگ', 'amount': 'مقدارِ نمونه', 'price': 'قیمتِ نمونه', 'note': '', 'button': 'خرید', 'link': '#', 'highlight': False}], 'name', 'افزودنِ بسته')],
      _HEADHTML + """<div class="nbc-grid nbc-auto nbc-pk"><!--each:items--><article class="nbc-card nbc-pk-i" data-ifc="highlight:is-hot"><span class="nbc-pill" data-s="note"></span><h3 class="nbc-h3" data-s="name"></h3>"""
      """<b class="nbc-pk-n" data-s="amount"></b><span class="nbc-pk-p" data-s="price"></span><a class="nbc-btn is-alt" data-s="button" data-h="link"></a></article><!--/each--></div>""",
      """.nbc-pk{grid-template-columns:repeat(auto-fit,minmax(min(100%,200px),1fr))}.nbc-pk-i{display:grid;justify-items:center;text-align:center;gap:8px;align-content:start}
.nbc-pk-n{font-family:var(--nb-font-head,inherit);font-size:1.7rem;color:var(--brand);line-height:1.3}.nbc-pk-p{color:var(--ink-2);margin-bottom:8px}
.nbc-pk-i .nbc-pill{color:var(--brand);margin-bottom:2px}.nbc-pk-i.is-hot{border:var(--st-hl-bd,2px solid var(--brand));box-shadow:var(--st-hl-sh,none)}.nbc-pk-i.is-hot .nbc-btn{background:var(--brand);color:var(--brand-ink,#fff)}""",
      'قیمت بسته شارژ توکن اعتبار کوچک', 'glassmorphism claymorphism soft-pastel neo-brutalism bento-grid'),

    C('price_minimal_list', 'pricing', 'فهرستِ سادهٔ بسته‌ها', 'هر بسته یک ردیف: نام و توضیح در یک سو، قیمت و دکمه در سوی دیگر',
      _HEAD + [ITEMS('items', 'بسته‌ها', [T('name', 'نام'), T('desc', 'توضیحِ کوتاه'), T('price', 'قیمت'), T('button', 'متنِ دکمه'), L('link', 'پیوندِ دکمه'), TG('highlight', 'برجسته')],
                     [{'name': 'بستهٔ اول', 'desc': 'توضیحِ کوتاهِ بسته', 'price': 'قیمت را بنویس', 'button': 'انتخاب', 'link': '#', 'highlight': False},
                      {'name': 'بستهٔ دوم', 'desc': 'توضیحِ کوتاهِ بسته', 'price': 'قیمت را بنویس', 'button': 'انتخاب', 'link': '#', 'highlight': True},
                      {'name': 'بستهٔ سوم', 'desc': 'توضیحِ کوتاهِ بسته', 'price': 'قیمت را بنویس', 'button': 'انتخاب', 'link': '#', 'highlight': False}], 'name', 'افزودنِ بسته')],
      _HEADHTML + """<div class="nbc-pml"><!--each:items--><article class="nbc-pml-i" data-ifc="highlight:is-hot"><div class="nbc-pml-n"><h3 class="nbc-h3" data-s="name"></h3><p class="nbc-text" data-s="desc"></p></div>"""
      """<b class="nbc-pml-p" data-s="price"></b><a class="nbc-btn is-alt" data-s="button" data-h="link"></a></article><!--/each--></div>""",
      """.nbc-pml{display:grid;max-width:860px;margin-inline:auto;border-top:var(--st-card-bd,1px solid var(--line))}
.nbc-pml-i{display:grid;grid-template-columns:minmax(0,1fr) auto auto;gap:14px 28px;align-items:center;padding:22px 6px;border-bottom:1px solid var(--line)}
.nbc-pml-n .nbc-h3{margin:0}.nbc-pml-n .nbc-text{margin:2px 0 0}.nbc-pml-p{font-family:var(--nb-font-head,inherit);font-size:1.25rem;color:var(--ink)}
.nbc-pml-i.is-hot{background:color-mix(in srgb,var(--brand) 7%,transparent);padding-inline:clamp(12px,2vw,22px);border-radius:var(--st-card-r,var(--r,12px))}.nbc-pml-i.is-hot .nbc-pml-p{color:var(--brand)}.nbc-pml-i.is-hot .nbc-btn{background:var(--brand);color:var(--brand-ink,#fff)}
@media (max-width:640px){.nbc-pml-i{grid-template-columns:minmax(0,1fr) auto}.nbc-pml-i .nbc-btn{grid-column:1/-1}}""",
      'قیمت فهرست ساده ردیفی بسته', 'minimalism editorial swiss dark-luxury corporate-clean neumorphism'),
]
