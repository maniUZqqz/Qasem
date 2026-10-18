# -*- coding: utf-8 -*-
"""متن‌های ثابتِ پروژهٔ تولیدشده: قالب‌ها، CSS، اپِ سبد، README.

جدا از generator.py تا منطقِ موتور و متنِ خروجی قاطی نشوند.
"""

MANAGE_TPL = '''#!/usr/bin/env python
"""%(name)s — خروجیِ Django Commerce Studio."""
import os
import sys

if __name__ == '__main__':
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    from django.core.management import execute_from_command_line
    execute_from_command_line(sys.argv)
'''

APP_CONFIG_TPL = '''from django.apps import AppConfig


class %(cls)sConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = '%(pkg)s'
    label = '%(name)s'
    verbose_name = '%(fa)s'
'''

WSGI_TPL = '''import os
from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
application = get_wsgi_application()
'''

CONTEXT_TPL = '''# -*- coding: utf-8 -*-
"""متغیرهای مشترکِ قالب‌ها — ساختهٔ استودیو."""
from django.conf import settings

MENU = [%(menu)s]


def site(request):
    return {
        'SITE_TITLE': getattr(settings, 'SITE_TITLE', ''),
        'MENU': MENU,
        'CURRENT_PATH': request.path,
    }
'''



PRODUCT_EXTRAS = '''

def _fmt_price(v):
    try:
        return '{:,.0f}'.format(float(v))
    except (TypeError, ValueError):
        return str(v)


def _product_price_display(self):
    """قیمت با جداکنندهٔ هزارگان — برای قالب."""
    return _fmt_price(self.price)


def _product_absolute_url(self):
    from django.urls import reverse
    return reverse('product_detail', kwargs={'slug': self.slug})


Product.price_display = property(_product_price_display)
Product.get_absolute_url = _product_absolute_url
'''

# ── اپِ سبدِ خرید ─────────────────────────────────────────────────
CART_PY = '''# -*- coding: utf-8 -*-
"""سبدِ خرید روی session — بی‌نیاز به ورود. ساختهٔ استودیو."""
from decimal import Decimal

from apps.catalog.models import Product

KEY = 'cart'


class Cart:
    def __init__(self, request):
        self.session = request.session
        self.data = self.session.get(KEY) or {}

    def _save(self):
        self.session[KEY] = self.data
        self.session.modified = True

    def add(self, product, qty=1):
        pid = str(product.pk)
        row = self.data.get(pid) or {'qty': 0, 'price': str(product.price)}
        row['qty'] = max(1, row['qty'] + int(qty))
        row['price'] = str(product.price)
        self.data[pid] = row
        self._save()

    def set(self, product_id, qty):
        pid = str(product_id)
        if pid in self.data:
            if int(qty) <= 0:
                del self.data[pid]
            else:
                self.data[pid]['qty'] = int(qty)
            self._save()

    def remove(self, product_id):
        self.data.pop(str(product_id), None)
        self._save()

    def clear(self):
        self.data = {}
        self._save()

    def __iter__(self):
        ids = [int(k) for k in self.data]
        products = {p.pk: p for p in Product.objects.filter(pk__in=ids)}
        for pid, row in self.data.items():
            p = products.get(int(pid))
            if not p:
                continue
            price = Decimal(row['price'])
            yield {'product': p, 'qty': row['qty'], 'price': price,
                   'total': price * row['qty']}

    def __len__(self):
        return sum(r['qty'] for r in self.data.values())

    @property
    def total(self):
        return sum((Decimal(r['price']) * r['qty'] for r in self.data.values()), Decimal('0'))

    @property
    def total_display(self):
        return '{:,.0f}'.format(float(self.total))
'''

CART_CP = '''# -*- coding: utf-8 -*-
from .cart import Cart


def cart(request):
    return {'cart': Cart(request)}
'''

CART_FORMS = '''# -*- coding: utf-8 -*-
from django import forms


class CheckoutForm(forms.Form):
    customer_name = forms.CharField(label='نام و نام خانوادگی', max_length=120)
    phone = forms.CharField(label='شمارهٔ تماس', max_length=20)
    address = forms.CharField(label='نشانی', widget=forms.Textarea(attrs={'rows': 3}))
'''

CART_VIEWS = '''# -*- coding: utf-8 -*-
"""سبدِ خرید و تسویه‌حساب — ساختهٔ استودیو."""
from django.contrib import messages
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.catalog.models import Product
from apps.orders.models import Order, OrderItem

from .cart import Cart
from .forms import CheckoutForm


def detail(request):
    return render(request, 'pages/cart.html', {'page_title': 'سبد خرید'})


@require_POST
def add(request, pk):
    product = get_object_or_404(Product, pk=pk, is_active=True)
    Cart(request).add(product, request.POST.get('qty') or 1)
    messages.success(request, '«%s» به سبد اضافه شد.' % product.name)
    return redirect(request.POST.get('next') or 'cart_detail')


@require_POST
def update(request, pk):
    Cart(request).set(pk, request.POST.get('qty') or 0)
    return redirect('cart_detail')


@require_POST
def remove(request, pk):
    Cart(request).remove(pk)
    return redirect('cart_detail')


def checkout(request):
    cart = Cart(request)
    if len(cart) == 0:
        messages.info(request, 'سبدِ خرید خالی است.')
        return redirect('cart_detail')
    form = CheckoutForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            order = Order.objects.create(
                customer_name=form.cleaned_data['customer_name'],
                phone=form.cleaned_data['phone'],
                address=form.cleaned_data['address'],
                total=cart.total,
            )
            for row in cart:
                OrderItem.objects.create(order=order, product=row['product'],
                                         quantity=row['qty'], unit_price=row['price'])
        cart.clear()
        return render(request, 'pages/order_done.html', {'order': order, 'page_title': 'سفارش ثبت شد'})
    return render(request, 'pages/checkout.html', {'form': form, 'page_title': 'تسویه‌حساب'})
'''

CART_URLS = '''# -*- coding: utf-8 -*-
from django.urls import path

from . import views

urlpatterns = [
    path('', views.detail, name='cart_detail'),
    path('add/<int:pk>/', views.add, name='cart_add'),
    path('update/<int:pk>/', views.update, name='cart_update'),
    path('remove/<int:pk>/', views.remove, name='cart_remove'),
    path('checkout/', views.checkout, name='checkout'),
]
'''

# ── قالب‌ها ───────────────────────────────────────────────────────
BASE_TPL = '''<!doctype html>
<html lang="fa" dir="rtl">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{%% block title %%}%(title)s{%% endblock %%}</title>
  {%% load static %%}
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/rastikerdar/vazirmatn@v33.003/Vazirmatn-font-face.css">
  <link rel="stylesheet" href="{%% static 'css/base.css' %%}">
  {%% block extra_css %%}{%% endblock %%}
</head>
<body>
  {%% include "components/header.html" %%}

  {%% if messages %%}
  <div class="wrap flashes">
    {%% for m in messages %%}<div class="flash {{ m.tags }}">{{ m }}</div>{%% endfor %%}
  </div>
  {%% endif %%}

  <main id="page-body">
    {%% block content %%}{%% endblock %%}
  </main>

  {%% include "components/footer.html" %%}
  {%% block extra_js %%}{%% endblock %%}
</body>
</html>
'''

PAGE_TPL = '''{%% extends "base.html" %%}
{%% load static %%}

{%% block title %%}%(title)s · {{ SITE_TITLE }}{%% endblock %%}

{%% block extra_css %%}
<link rel="stylesheet" href="{%% static 'css/pages/%(css)s.css' %%}">
{%% endblock %%}

{%% block content %%}
%(body)s
{%% endblock %%}
'''

PRODUCT_CARD_TPL = '''{# کارتِ محصول — مشترک بین صفحه‌ها #}
<article class="card product">
  <a class="thumb" href="{{ p.get_absolute_url }}">
    {% if p.image %}<img src="{{ p.image.url }}" alt="{{ p.name }}" loading="lazy">
    {% else %}<span class="ph">{{ p.name|slice:":1" }}</span>{% endif %}
  </a>
  <div class="body">
    {% if p.category %}<span class="cat">{{ p.category.name }}</span>{% endif %}
    <h3><a href="{{ p.get_absolute_url }}">{{ p.name }}</a></h3>
    <div class="row">
      <span class="price">{{ p.price_display }} <small>تومان</small></span>
      <form method="post" action="{% url 'cart_add' p.pk %}">{% csrf_token %}
        <input type="hidden" name="next" value="{{ request.path }}">
        <button class="btn sm" {% if p.stock <= 0 %}disabled{% endif %}>{% if p.stock > 0 %}افزودن{% else %}ناموجود{% endif %}</button>
      </form>
    </div>
  </div>
</article>
'''

DEFAULT_BODY = '''<section class="section">
  <h1>%(title)s</h1>
  <p>این بخش را می‌توانی از استودیو ویرایش کنی.</p>
</section>'''

DEFAULT_BODIES = {
    'home': '''<section class="hero">
  <div class="wrap">
    <span class="eyebrow">تازه‌ها</span>
    <h1>به {{ SITE_TITLE }} خوش آمدید</h1>
    <p>محصولاتِ منتخب با قیمتِ منصفانه و ارسالِ سریع.</p>
    <a class="btn lg" href="/products/">دیدنِ محصولات</a>
  </div>
</section>

{% if categories %}
<section class="section">
  <div class="cats">
    {% for c in categories %}<a class="cat-chip" href="/products/?cat={{ c.slug }}">{{ c.name }}</a>{% endfor %}
  </div>
</section>
{% endif %}

<section class="section">
  <div class="section-h"><h2>محصولاتِ تازه</h2><a href="/products/">همه ←</a></div>
  <div class="grid">
    {% for p in products %}{% include "components/product_card.html" %}
    {% empty %}<p class="muted">هنوز محصولی ثبت نشده — از <a href="/admin/">پنلِ مدیریت</a> اضافه کن.</p>{% endfor %}
  </div>
</section>''',

    'product_list': '''<section class="section">
  <div class="section-h">
    <h1>محصولات</h1>
    <form class="search" method="get">
      <input name="q" value="{{ q }}" placeholder="جست‌وجو…">
      {% if cat %}<input type="hidden" name="cat" value="{{ cat }}">{% endif %}
      <button class="btn sm">بگرد</button>
    </form>
  </div>
  {% if categories %}
  <div class="cats">
    <a class="cat-chip {% if not cat %}on{% endif %}" href="/products/">همه</a>
    {% for c in categories %}<a class="cat-chip {% if cat == c.slug %}on{% endif %}" href="/products/?cat={{ c.slug }}">{{ c.name }}</a>{% endfor %}
  </div>
  {% endif %}
  <div class="grid">
    {% for p in products %}{% include "components/product_card.html" %}
    {% empty %}<p class="muted">محصولی پیدا نشد.</p>{% endfor %}
  </div>
</section>''',

    'product_detail': '''<section class="section product-detail">
  <nav class="crumbs"><a href="/">خانه</a> › <a href="/products/">محصولات</a>{% if product.category %} › <a href="/products/?cat={{ product.category.slug }}">{{ product.category.name }}</a>{% endif %}</nav>
  <div class="pd">
    <div class="pd-media">
      {% if product.image %}<img src="{{ product.image.url }}" alt="{{ product.name }}">
      {% else %}<span class="ph">{{ product.name|slice:":1" }}</span>{% endif %}
    </div>
    <div class="pd-info">
      <h1>{{ product.name }}</h1>
      <div class="price big">{{ product.price_display }} <small>تومان</small></div>
      <p class="stock {% if product.stock > 0 %}ok{% else %}no{% endif %}">
        {% if product.stock > 0 %}موجود — {{ product.stock }} عدد{% else %}ناموجود{% endif %}</p>
      <form method="post" action="{% url 'cart_add' product.pk %}" class="add-form">{% csrf_token %}
        <input type="number" name="qty" value="1" min="1" max="{{ product.stock|default:1 }}">
        <button class="btn lg" {% if product.stock <= 0 %}disabled{% endif %}>افزودن به سبد</button>
      </form>
      <div class="desc">{{ product.description|linebreaks }}</div>
    </div>
  </div>
  {% if related %}
  <h2 style="margin-top:36px">محصولاتِ مرتبط</h2>
  <div class="grid">{% for p in related %}{% include "components/product_card.html" %}{% endfor %}</div>
  {% endif %}
</section>''',

    'cart': '''<section class="section">
  <h1>سبد خرید</h1>
  {% if cart|length %}
  <div class="cart-table">
    <table>
      <thead><tr><th>محصول</th><th>قیمت</th><th>تعداد</th><th>جمع</th><th></th></tr></thead>
      <tbody>
      {% for row in cart %}
      <tr>
        <td><a href="{{ row.product.get_absolute_url }}">{{ row.product.name }}</a></td>
        <td>{{ row.product.price_display }}</td>
        <td>
          <form method="post" action="{% url 'cart_update' row.product.pk %}" class="qty">{% csrf_token %}
            <input type="number" name="qty" value="{{ row.qty }}" min="0">
            <button class="btn sm ghost">به‌روز</button>
          </form>
        </td>
        <td class="price">{{ row.total|floatformat:0 }}</td>
        <td><form method="post" action="{% url 'cart_remove' row.product.pk %}">{% csrf_token %}<button class="link danger">حذف</button></form></td>
      </tr>
      {% endfor %}
      </tbody>
    </table>
  </div>
  <div class="cart-foot">
    <div class="total">جمعِ کل: <b>{{ cart.total_display }}</b> تومان</div>
    <a class="btn lg" href="{% url 'checkout' %}">ادامه و تسویه‌حساب</a>
  </div>
  {% else %}
  <div class="empty">سبدِ خرید خالی است. <a href="/products/">برو سراغِ محصولات</a></div>
  {% endif %}
</section>''',

    'checkout': '''<section class="section">
  <h1>تسویه‌حساب</h1>
  <div class="checkout">
    <form method="post" class="co-form">{% csrf_token %}
      {{ form.non_field_errors }}
      {% for f in form %}
        <label>{{ f.label }}</label>{{ f }}{% if f.errors %}<div class="err">{{ f.errors.0 }}</div>{% endif %}
      {% endfor %}
      <button class="btn lg">ثبتِ سفارش</button>
    </form>
    <aside class="co-sum">
      <h3>خلاصهٔ سفارش</h3>
      {% for row in cart %}
        <div class="line"><span>{{ row.product.name }} × {{ row.qty }}</span><span>{{ row.total|floatformat:0 }}</span></div>
      {% endfor %}
      <div class="line total"><span>جمعِ کل</span><span>{{ cart.total_display }} تومان</span></div>
    </aside>
  </div>
</section>''',
}

ORDER_DONE_TPL = '''{% extends "base.html" %}
{% block title %}سفارش ثبت شد · {{ SITE_TITLE }}{% endblock %}
{% block content %}
<section class="section done">
  <div class="done-box">
    <div class="tick">✓</div>
    <h1>سفارشِ شما ثبت شد</h1>
    <p>شمارهٔ سفارش: <b>#{{ order.pk }}</b> · مبلغ: <b>{{ order.total|floatformat:0 }}</b> تومان</p>
    <p class="muted">به‌زودی برای هماهنگی با شمارهٔ {{ order.phone }} تماس می‌گیریم.</p>
    <a class="btn" href="/">بازگشت به خانه</a>
  </div>
</section>
{% endblock %}
'''

DEFAULT_HEADER = '''<header class="site-header">
  <div class="wrap">
    <a class="brand" href="/">{{ SITE_TITLE }}</a>
    <nav class="main-nav">
      {% for title, href in MENU %}<a href="{{ href }}" class="{% if CURRENT_PATH == href %}on{% endif %}">{{ title }}</a>{% endfor %}
    </nav>
    <a class="cart-link" href="/cart/">
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="9" cy="21" r="1"/><circle cx="20" cy="21" r="1"/><path d="M1 1h4l2.7 13.4a2 2 0 0 0 2 1.6h9.7a2 2 0 0 0 2-1.6L23 6H6"/></svg>
      سبد{% if cart|length %}<span class="badge">{{ cart|length }}</span>{% endif %}
    </a>
  </div>
</header>
'''

DEFAULT_FOOTER = '''<footer class="site-footer">
  <div class="wrap">
    <div class="cols">
      <div><b class="brand">{{ SITE_TITLE }}</b><p>فروشگاهِ آنلاین — ارسال به سراسرِ کشور.</p></div>
      <div><b>دسترسی سریع</b>{% for title, href in MENU %}<a href="{{ href }}">{{ title }}</a>{% endfor %}</div>
      <div><b>تماس</b><a href="tel:">تلفن</a><a href="mailto:">ایمیل</a></div>
    </div>
    <p class="copy">© {{ SITE_TITLE }} — همهٔ حقوق محفوظ است.</p>
  </div>
</footer>
'''

BASE_CSS = ''':root {
  --brand: %(brand)s;
  --brand-ink: #ffffff;
  --ink: #111827; --ink-2: #374151; --ink-3: #6b7280;
  --line: #e5e7eb; --bg: #f7f8fa; --card: #ffffff;
  --r: 16px; --r-sm: 10px;
  --sh: 0 1px 2px rgba(0,0,0,.04), 0 8px 24px -16px rgba(0,0,0,.18);
}
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body {
  margin: 0; background: var(--bg); color: var(--ink);
  font-family: Vazirmatn, "Segoe UI", Tahoma, sans-serif; line-height: 1.85; font-size: 15px;
}
a { color: var(--brand); text-decoration: none; }
img { max-width: 100%%; display: block; }
h1, h2, h3 { margin: 0 0 10px; line-height: 1.35; font-weight: 800; }
h1 { font-size: 1.9rem; } h2 { font-size: 1.35rem; } h3 { font-size: 1rem; }
.wrap { max-width: 1140px; margin: 0 auto; padding: 0 18px; }
.muted { color: var(--ink-3); }
.btn {
  display: inline-flex; align-items: center; gap: 6px; background: var(--brand); color: var(--brand-ink);
  border: 0; border-radius: 999px; padding: 10px 20px; font: inherit; font-weight: 700; cursor: pointer;
  transition: .15s; box-shadow: 0 8px 20px -10px var(--brand);
}
.btn:hover { filter: brightness(1.08); transform: translateY(-1px); }
.btn.lg { padding: 13px 28px; font-size: 1.02rem; }
.btn.sm { padding: 6px 14px; font-size: .86rem; box-shadow: none; }
.btn.ghost { background: #fff; color: var(--ink-2); border: 1px solid var(--line); box-shadow: none; }
.btn[disabled] { opacity: .45; pointer-events: none; }
.link { background: none; border: 0; font: inherit; cursor: pointer; color: var(--brand); padding: 0; }
.link.danger { color: #dc2626; }

/* هدر */
.site-header { background: #fff; border-bottom: 1px solid var(--line); position: sticky; top: 0; z-index: 30; }
.site-header .wrap { display: flex; align-items: center; gap: 18px; padding: 13px 18px; }
.site-header .brand { font-weight: 900; font-size: 1.2rem; color: var(--brand); }
.main-nav { display: flex; gap: 6px; margin-inline-start: auto; }
.main-nav a { color: var(--ink-2); padding: 6px 12px; border-radius: 999px; font-size: .95rem; }
.main-nav a:hover, .main-nav a.on { background: color-mix(in srgb, var(--brand) 12%%, #fff); color: var(--brand); }
.cart-link { display: inline-flex; align-items: center; gap: 6px; color: var(--ink-2); font-weight: 700;
  padding: 6px 12px; border: 1px solid var(--line); border-radius: 999px; background: #fff; }
.cart-link .badge { background: var(--brand); color: #fff; border-radius: 999px; padding: 0 7px;
  font-size: .75rem; min-width: 20px; text-align: center; }
@media (max-width: 720px) { .main-nav { display: none; } }

/* پیام‌ها */
.flashes { padding-top: 12px; }
.flash { padding: 10px 14px; border-radius: var(--r-sm); margin-bottom: 8px; font-size: .92rem;
  background: #ecfdf5; border: 1px solid #a7f3d0; color: #065f46; }
.flash.info { background: #eff6ff; border-color: #bfdbfe; color: #1e3a8a; }
.flash.error { background: #fef2f2; border-color: #fecaca; color: #991b1b; }

/* بدنه */
#page-body { min-height: 60vh; }
.section { max-width: 1140px; margin: 0 auto; padding: 34px 18px; }
.section-h { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 16px; flex-wrap: wrap; }
.hero { background: linear-gradient(135deg, var(--brand), color-mix(in srgb, var(--brand) 55%%, #111827));
  color: #fff; padding: 64px 0; text-align: center; }
.hero h1 { color: #fff; font-size: 2.3rem; }
.hero p { opacity: .92; font-size: 1.05rem; max-width: 640px; margin: 0 auto 20px; }
.hero .eyebrow { display: inline-block; background: rgba(255,255,255,.18); border-radius: 999px;
  padding: 3px 12px; font-size: .82rem; margin-bottom: 12px; }
.hero .btn { background: #fff; color: var(--brand); box-shadow: 0 10px 30px -10px rgba(0,0,0,.4); }
.cats { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 18px; }
.cat-chip { border: 1px solid var(--line); background: #fff; border-radius: 999px; padding: 6px 14px;
  color: var(--ink-2); font-size: .9rem; }
.cat-chip:hover, .cat-chip.on { border-color: var(--brand); color: var(--brand); background: color-mix(in srgb, var(--brand) 8%%, #fff); }
.search { display: flex; gap: 6px; }
.search input { border: 1px solid var(--line); border-radius: 999px; padding: 8px 14px; font: inherit; min-width: 220px; }

/* کارت‌ها */
.grid { display: grid; gap: 18px; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); }
.card { background: var(--card); border: 1px solid var(--line); border-radius: var(--r); box-shadow: var(--sh); overflow: hidden; }
.card.product { display: flex; flex-direction: column; transition: .15s; }
.card.product:hover { transform: translateY(-3px); box-shadow: 0 16px 36px -18px rgba(0,0,0,.3); }
.card .thumb { display: block; aspect-ratio: 1 / 1; background: color-mix(in srgb, var(--brand) 10%%, #fff); overflow: hidden; }
.card .thumb img { width: 100%%; height: 100%%; object-fit: cover; }
.card .thumb .ph, .pd-media .ph { display: grid; place-items: center; width: 100%%; height: 100%%;
  font-size: 3rem; font-weight: 900; color: var(--brand); opacity: .55; }
.card .body { padding: 12px 14px 14px; display: flex; flex-direction: column; gap: 4px; flex: 1; }
.card .cat { font-size: .76rem; color: var(--ink-3); }
.card h3 a { color: var(--ink); }
.card .row { display: flex; align-items: center; justify-content: space-between; margin-top: auto; padding-top: 6px; }
.price { color: var(--brand); font-weight: 800; }
.price small { font-weight: 400; color: var(--ink-3); font-size: .78rem; }
.price.big { font-size: 1.6rem; }

/* محصول */
.crumbs { font-size: .86rem; color: var(--ink-3); margin-bottom: 16px; }
.pd { display: grid; grid-template-columns: 1fr 1.2fr; gap: 28px; align-items: start; }
.pd-media { aspect-ratio: 1/1; border-radius: var(--r); overflow: hidden; background: color-mix(in srgb, var(--brand) 10%%, #fff); border: 1px solid var(--line); }
.pd-media img { width: 100%%; height: 100%%; object-fit: cover; }
.stock.ok { color: #059669; } .stock.no { color: #dc2626; }
.add-form { display: flex; gap: 10px; align-items: center; margin: 14px 0 20px; }
.add-form input { width: 80px; border: 1px solid var(--line); border-radius: var(--r-sm); padding: 10px; font: inherit; text-align: center; }
.desc { color: var(--ink-2); }
@media (max-width: 760px) { .pd { grid-template-columns: 1fr; } }

/* سبد و تسویه */
.cart-table { background: #fff; border: 1px solid var(--line); border-radius: var(--r); overflow: auto; }
table { width: 100%%; border-collapse: collapse; }
th, td { padding: 12px 14px; text-align: right; border-bottom: 1px solid var(--line); }
th { background: #f9fafb; font-size: .84rem; color: var(--ink-3); }
.qty { display: flex; gap: 6px; align-items: center; }
.qty input { width: 64px; border: 1px solid var(--line); border-radius: 8px; padding: 6px; text-align: center; font: inherit; }
.cart-foot { display: flex; justify-content: space-between; align-items: center; margin-top: 18px; flex-wrap: wrap; gap: 12px; }
.total { font-size: 1.1rem; }
.empty { background: #fff; border: 1px dashed var(--line); border-radius: var(--r); padding: 36px; text-align: center; color: var(--ink-3); }
.checkout { display: grid; grid-template-columns: 1.3fr 1fr; gap: 24px; align-items: start; }
.co-form, .co-sum { background: #fff; border: 1px solid var(--line); border-radius: var(--r); padding: 20px; }
.co-form label { display: block; font-size: .88rem; color: var(--ink-3); margin: 12px 0 4px; }
.co-form input, .co-form textarea { width: 100%%; border: 1px solid var(--line); border-radius: var(--r-sm); padding: 10px 12px; font: inherit; }
.co-form .btn { margin-top: 16px; width: 100%%; justify-content: center; }
.co-form .err { color: #dc2626; font-size: .82rem; }
.co-sum .line { display: flex; justify-content: space-between; padding: 7px 0; border-bottom: 1px dashed var(--line); font-size: .92rem; }
.co-sum .line.total { border: 0; font-weight: 800; font-size: 1rem; margin-top: 6px; }
@media (max-width: 760px) { .checkout { grid-template-columns: 1fr; } }
.done .done-box { max-width: 520px; margin: 20px auto; background: #fff; border: 1px solid var(--line); border-radius: var(--r); padding: 36px; text-align: center; }
.done .tick { width: 64px; height: 64px; border-radius: 50%%; background: #ecfdf5; color: #059669; display: grid; place-items: center; font-size: 2rem; margin: 0 auto 12px; font-weight: 900; }

/* فوتر */
.site-footer { background: #fff; border-top: 1px solid var(--line); margin-top: 48px; padding: 30px 0 18px; color: var(--ink-3); font-size: .92rem; }
.site-footer .cols { display: grid; gap: 20px; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); }
.site-footer b { display: block; color: var(--ink); margin-bottom: 6px; }
.site-footer b.brand { color: var(--brand); font-size: 1.1rem; }
.site-footer a { display: block; color: var(--ink-2); padding: 2px 0; }
.site-footer .copy { border-top: 1px solid var(--line); margin-top: 20px; padding-top: 14px; font-size: .84rem; }
'''

README_TPL = '''# %(name)s

%(desc)s

> ساختهٔ **Django Commerce Studio** — %(when)s
> این یک پروژهٔ کاملاً استانداردِ جنگوست و برای اجرا به استودیو نیازی ندارد.

## اجرا

```bash
python3 -m venv venv
venv/bin/pip install -r requirements.txt
venv/bin/python manage.py migrate
venv/bin/python manage.py createsuperuser
venv/bin/python manage.py runserver
```

ویندوز:

```bat
py -3 -m venv venv
venv\\Scripts\\python -m pip install -r requirements.txt
venv\\Scripts\\python manage.py migrate
venv\\Scripts\\python manage.py createsuperuser
venv\\Scripts\\python manage.py runserver
```

## ساختار

```
config/      تنظیمات، نشانی‌ها و ویوهای صفحه‌ها
apps/        اپ‌های پروژه (هر کدام models/admin/views)
templates/   base.html + components/{header,footer,product_card} + pages/*
static/css/  base.css + pages/<page>.css
```

قالب‌ها سه‌بخشی‌اند: **هدر** و **فوتر** مشترک‌اند و فقط **بدنهٔ** هر صفحه
جداگانه ویرایش می‌شود.

سبدِ خرید: %(cart)s
'''
