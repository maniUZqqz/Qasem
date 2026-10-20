# -*- coding: utf-8 -*-
"""پنلِ وبِ چغر — همان قابلیت‌های تازه، با مرورگرِ گوشی.

چرا وجود دارد: اپِ فلاتر فقط به‌صورتِ **بیلدشده** روی سرور است (main.dart.js
بدونِ سورس)، پس تا رسیدنِ سورس نمی‌شود صفحه‌ای به آن اضافه کرد. این صفحه‌ها
دقیقاً همان APIهایی را صدا می‌زنند که اپ باید صدا بزند؛ وقتی سورس رسید، فقط
همین فراخوانی‌ها در فلاتر تکرار می‌شوند و این‌جا دست‌نخورده باقی می‌ماند.

ورود: با شمارهٔ موبایل و رمزِ همان حسابِ اپ. برای فراخوانیِ APIها، توکنِ DRF
در نشست (session) نگه داشته می‌شود — تنظیماتِ احرازِ هویتِ DRF دست نمی‌خورد.
"""
import json
from functools import wraps

from django.contrib.auth import authenticate, login, logout
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import redirect, render
from django.urls import reverse, reverse_lazy
from rest_framework.authtoken.models import Token

LOGIN_URL = reverse_lazy('panel-login')
LOGIN_REDIRECT = reverse_lazy('panel-home')


def _ensure_app_session(request):
    """اگر کاربر از اپ خارج شده باشد، نشستِ وب هم باید بسته شود.

    نشستی که از اپ باز شده، کلیدِ توکنش را در خودش دارد. وقتی کاربر در اپ
    «خروج» بزند، آن توکن روی سرور پاک می‌شود؛ پس این نشست هم دیگر معتبر نیست.
    برای نشستِ عادی (ورود با رمز در مرورگر) این چک اتفاق نمی‌افتد.
    """
    key = request.session.get('app_token')
    if not key:
        return True
    from rest_framework.authtoken.models import Token
    if Token.objects.filter(key=key, user=request.user).exists():
        return True
    logout(request)
    return False


def panel_view(view):
    """ورودِ لازم + چکِ زندهٔ نشستِ اپ، برای همهٔ صفحه‌های پنل."""
    @wraps(view)
    @login_required(login_url=LOGIN_URL)
    def inner(request, *args, **kwargs):
        if not _ensure_app_session(request):
            return redirect('%s?next=%s' % (reverse('panel-login'), request.path))
        return view(request, *args, **kwargs)
    return inner


def _api_base():
    """آدرسِ پایهٔ API با همان پیشوندی که سایت زیرش بالا آمده (/chagher/api/)."""
    return reverse('my-status').rsplit('me/status/', 1)[0]


def _ctx(request, **extra):
    token, _ = Token.objects.get_or_create(user=request.user)
    data = {
        'api_base': _api_base(),
        'api_token': token.key,
        'account_type': request.user.account_type,
        'is_coach': request.user.is_coach,
    }
    data.update(extra)
    return data


def panel_login(request):
    """ورود به پنلِ وب با شماره و رمزِ همان حسابِ اپ."""
    if request.user.is_authenticated:
        return redirect('panel-home')
    error = None
    if request.method == 'POST':
        phone = (request.POST.get('phone_number') or '').strip()
        password = request.POST.get('password') or ''
        user = authenticate(request, username=phone, password=password)
        if user is None:
            error = 'شماره یا رمز درست نیست.'
        elif not user.is_active:
            error = 'این حساب غیرفعال است.'
        else:
            login(request, user)
            Token.objects.get_or_create(user=user)
            return redirect(request.GET.get('next') or 'panel-home')
    return render(request, 'app/panel/login.html', {
        'error': error,
        'phone': (request.POST.get('phone_number') or '') if request.method == 'POST' else '',
        'next': request.GET.get('next') or '',
        'landing_url': _landing_url(request),
    })


# ══════════════════════ ثبت‌نامِ ورزشکار (B2C) ══════════════════════
# چرا لازم شد: API ثبت‌نامِ کاربرِ شخصی از قبل بود، ولی هیچ صفحهٔ وبی نداشت.
# یعنی دکمهٔ «شروع کن — رایگان» در لندینگ، کاربرِ تازه را به فرمِ ورود می‌برد
# و آن‌جا هیچ راهی برای ساختنِ حساب نبود — قیفِ B2C بن‌بست داشت.
#
# ⚠ این‌جا فقط حسابِ «کاربرِ شخصی» ساخته می‌شود. ورزشکارِ باشگاه را باشگاهش
#   اضافه می‌کند و مربی از اپ ثبت‌نام می‌کند — دو دنیا قاطی نمی‌شوند.

_DIGIT_MAP = str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩', '01234567890123456789')
SIGNUP_RESEND_COOLDOWN = 60   # ثانیه


def _normalize_phone(raw):
    """۰۹۱۲… را از هر شکلی (فارسی، با فاصله، +۹۸) به 09xxxxxxxxx می‌رساند."""
    import re
    s = (raw or '').strip().translate(_DIGIT_MAP)
    s = re.sub(r'[^0-9+]', '', s)
    if s.startswith('+98'):
        s = '0' + s[3:]
    elif s.startswith('0098'):
        s = '0' + s[4:]
    elif s.startswith('98') and len(s) == 12:
        s = '0' + s[2:]
    return s


def _landing_url(request):
    """صفحهٔ اصلیِ همین دنیا — روی میزبانِ B2C، هوم‌پیجِ ورزشکار."""
    if getattr(request, 'is_b2c', False):
        host = getattr(request, 'b2c_host', '') or 'app.chagher.ir'
        return 'https://%s/' % host
    return '/'


def panel_signup(request):
    """ثبت‌نامِ دو مرحله‌ای: شماره ← کدِ پیامکی + رمز."""
    import re
    import time
    from django.contrib.auth import get_user_model
    from .models import PlatformSettings
    from .serializers import PersonalRegisterSerializer
    from .sms_hook import issue_registration_code, queue_registration_code

    if request.user.is_authenticated:
        return redirect('panel-me')

    User = get_user_model()
    error = None
    sent = False
    step = request.session.get('signup_step') or 'phone'
    phone = request.session.get('signup_phone') or ''
    full_name = ''

    def _send(to):
        code = issue_registration_code(to)
        queue_registration_code(to, code)
        request.session['signup_sent_at'] = time.time()

    if request.method == 'POST':
        action = request.POST.get('action') or 'phone'

        if action == 'restart':
            for k in ('signup_step', 'signup_phone', 'signup_sent_at'):
                request.session.pop(k, None)
            return redirect('panel-signup')

        if action == 'phone':
            phone = _normalize_phone(request.POST.get('phone_number'))
            if not re.fullmatch(r'09\d{9}', phone):
                error = 'شمارهٔ موبایل درست نیست. مثلِ 09123456789 بنویس.'
            elif User.objects.filter(phone_number=phone).exists():
                error = 'این شماره از قبل حساب دارد — از همین‌جا وارد شو.'
            else:
                try:
                    _send(phone)
                except Exception:
                    error = 'فرستادنِ پیامک نشد. چند لحظه بعد دوباره امتحان کن.'
                else:
                    request.session['signup_phone'] = phone
                    request.session['signup_step'] = step = 'verify'
                    sent = True

        elif action == 'resend':
            if not phone:
                return redirect('panel-signup')
            waited = time.time() - (request.session.get('signup_sent_at') or 0)
            if waited < SIGNUP_RESEND_COOLDOWN:
                error = 'چند ثانیه صبر کن؛ کد تازه فرستاده شده است.'
            else:
                try:
                    _send(phone)
                except Exception:
                    error = 'فرستادنِ پیامک نشد. چند لحظه بعد دوباره امتحان کن.'
                else:
                    sent = True
            step = 'verify'

        elif action == 'verify':
            step = 'verify'
            full_name = (request.POST.get('full_name') or '').strip()
            password = request.POST.get('password') or ''
            data = {
                'phone_number': phone,
                'password': password,
                'password_confirm': request.POST.get('password_confirm') or '',
                'verification_code': (request.POST.get('verification_code') or '').strip().translate(_DIGIT_MAP),
                'full_name': full_name,
            }
            if not phone:
                return redirect('panel-signup')
            serializer = PersonalRegisterSerializer(data=data)
            if serializer.is_valid():
                user = serializer.save()
                for k in ('signup_step', 'signup_phone', 'signup_sent_at'):
                    request.session.pop(k, None)
                authed = authenticate(request, username=phone, password=password)
                if authed is not None:
                    login(request, authed)
                    Token.objects.get_or_create(user=authed)
                    return redirect(request.GET.get('next') or 'panel-me')
                # اگر به هر دلیل ورودِ خودکار نشد، حساب ساخته شده — به ورود برو
                return redirect('panel-login')
            # اولین پیامِ خطا، به زبانِ آدمیزاد
            flat = []
            for value in serializer.errors.values():
                flat.extend(value if isinstance(value, (list, tuple)) else [value])
            error = str(flat[0]) if flat else 'اطلاعات کامل نیست.'

    try:
        free = PlatformSettings.get_solo().ai_free_programs
    except Exception:
        free = None

    return render(request, 'app/panel/signup.html', {
        'step': step,
        'phone': phone,
        'full_name': full_name,
        'error': error,
        'sent': sent,
        'ai_free_programs': free,
        'landing_url': _landing_url(request),
    })


def panel_logout(request):
    logout(request)
    return redirect('panel-login')


@panel_view
def panel_home(request):
    return render(request, 'app/panel/home.html', _ctx(request, page='home'))


@panel_view
def panel_manual_program(request):
    return render(request, 'app/panel/manual_program.html', _ctx(request, page='manual'))


@panel_view
def panel_scan(request):
    return render(request, 'app/panel/scan.html', _ctx(request, page='scan'))


@panel_view
def panel_me(request):
    return render(request, 'app/panel/me.html', _ctx(request, page='me'))


@panel_view
def form_check_page(request, external_id):
    """صفحهٔ دوربینِ «بررسیِ درستیِ حرکت».

    اگر مدیر این قابلیت را خاموش کرده باشد، صفحه ۴۰۴ می‌دهد — همان‌طور که
    دکمه‌اش هم در صفحهٔ آموزش دیده نمی‌شود. یعنی قابلیت کاملاً ناپدید می‌شود.
    """
    from .models import ExerciseLibrary, PlatformSettings
    if not PlatformSettings.get_solo().form_check_enabled:
        raise Http404('غیرفعال است')
    ex = get_object_or_404(ExerciseLibrary, external_id=external_id, is_active=True)
    return render(request, 'app/form_check.html', _ctx(request, page='formcheck', ex=ex))


@csrf_exempt
def panel_sso(request):
    """ورودِ یک‌باره از اپِ فلاتر به صفحه‌های جنگو.

    اپ توکنِ DRFِ همان کاربر را می‌فرستد و این‌جا نشستِ جنگو باز می‌شود؛ پس
    کاربر **هیچ فرمِ ورودی نمی‌بیند** و حس نمی‌کند به سایتِ دیگری رفته است.

    چرا csrf_exempt: رازِ این درخواست خودِ توکن است، نه کوکی. بدونِ توکن هیچ
    کاری نمی‌شود کرد، و توکن هم همان چیزی است که اپ برای بقیهٔ APIها می‌فرستد.

    POST (ترجیح‌داده‌شده): بدنهٔ JSON یا فرم با کلیدِ token → پاسخِ JSON.
    GET: برای حالتی که اپ نتواند fetch بزند؛ مستقیم redirect می‌کند.
    """
    from rest_framework.authtoken.models import Token

    # بدنهٔ JSON (اپ) و فرم (مرورگر) هر دو پشتیبانی می‌شوند
    payload = {}
    if request.body:
        try:
            payload = json.loads(request.body.decode('utf-8')) or {}
        except Exception:
            payload = {}
    if not isinstance(payload, dict):
        payload = {}

    token_key = (request.POST.get('token') or payload.get('token')
                 or request.GET.get('token') or '').strip()
    target = (request.POST.get('next') or payload.get('next')
              or request.GET.get('next') or '').strip()
    # فقط مسیرِ داخلیِ خودمان؛ جلوی بازگشاییِ آدرسِ بیرونی گرفته می‌شود
    if not target.startswith('/') or target.startswith('//'):
        target = str(LOGIN_REDIRECT)

    token = None
    if 20 <= len(token_key) <= 64:
        token = Token.objects.select_related('user').filter(key=token_key).first()

    if token is None or not token.user.is_active:
        if request.method == 'GET':
            return redirect('%s?next=%s' % (reverse('panel-login'), target))
        return JsonResponse({'ok': False, 'error': 'توکن معتبر نیست.'}, status=401)

    login(request, token.user)
    request.session['from_app'] = True          # ⇒ سربرگِ سایت نمایش داده نشود
    # نشست به همین توکن گره می‌خورد: خروج از اپ ⇒ بسته‌شدنِ این نشست
    request.session['app_token'] = token.key

    if request.method == 'GET':
        return redirect(target)
    return JsonResponse({
        'ok': True,
        'next': target,
        'phone_number': token.user.phone_number,
        'account_type': token.user.account_type,
    })


# ══════════════════ پوششِ داده: چه داریم و چه نداریم ══════════════════
# خواستِ مالک (۱۴۰۵/۰۷/۱۵): «می‌خواهم یک لینک باشد که همهٔ حرکت‌ها و همهٔ
# دستگاه‌های دیتابیس را نشان دهد و بگوید کدام عکس و آموزش دارد و کدام ندارد —
# چون می‌خواهم توسعه بدهم و باید بدانم کدام‌ها را ندارم.»
#
# پیش‌فرضِ صفحه «فقط ناقص‌ها» است، چون همان چیزی است که برای کار لازم است؛
# با یک کلیک می‌شود همه را دید. خروجیِ CSV هم دارد تا بشود آفلاین کار کرد.

def _cov_flag(value):
    return bool(value) and bool(str(value).strip())


@staff_member_required
def data_coverage(request):
    from django.core.paginator import Paginator
    from .models import ExerciseLibrary, EquipmentCatalog, Equipment

    kind = request.GET.get('kind') or 'exercise'
    show = request.GET.get('show') or 'missing'
    q = (request.GET.get('q') or '').strip()

    ex_qs = ExerciseLibrary.objects.all().order_by('external_id')
    cat_qs = EquipmentCatalog.objects.all().order_by('name')

    # ── شمارشِ خلاصه (همیشه روی کلِ داده، نه صفحهٔ جاری) ──
    def miss(qs, field):
        from django.db.models import Q
        return qs.filter(Q(**{field: ''}) | Q(**{field + '__isnull': True})).count()

    summary = {
        'ex_total': ex_qs.count(),
        'ex_no_thumb': miss(ex_qs, 'thumb'),
        'ex_no_gif': miss(ex_qs, 'gif'),
        'ex_no_steps': miss(ex_qs, 'steps_fa'),
        'ex_no_name_fa': ex_qs.filter(name_fa='').count(),
        'ex_owned': ex_qs.exclude(owner__isnull=True).count(),
        'cat_total': cat_qs.count(),
        'cat_no_image': miss(cat_qs, 'image'),
        'gym_total': Equipment.objects.count(),
    }
    try:
        summary['gym_unlinked'] = Equipment.objects.filter(catalog__isnull=True).count()
    except Exception:
        summary['gym_unlinked'] = None

    rows = []
    if kind == 'unmatched':
        # نام‌هایی که هوش مصنوعی در برنامه‌ها نوشته ولی به کتابخانه وصل نشدند.
        # این دقیقاً «چه چیزی کم داریم» است: یا حرکت نیست، یا نامش را نمی‌شناسیم.
        import re as _re
        from collections import Counter
        from .models import ClientProgram
        from .exercise_match import find_exercise
        seen = Counter()
        for prog in (ClientProgram.objects
                     .exclude(generated_workout='')
                     .exclude(generated_workout__isnull=True)
                     .only('generated_workout')[:400]):
            for ln in (prog.generated_workout or '').split(chr(10)):
                ln = ln.strip()
                if not ln or ln.startswith('#'):
                    continue
                m = _re.match(r'^\d+[.)]\s*(.+)$', ln)
                if not m:
                    continue
                name = _re.sub(r'\s*—.*$', '', m.group(1)).strip()
                if not name:
                    continue
                if find_exercise(m.group(1).strip()) is None:
                    seen[name] += 1
        for name, cnt in seen.most_common():
            if q and q not in name:
                continue
            rows.append({
                'id': 0, 'code': '%d بار' % cnt, 'name': name,
                'extra': 'در برنامه‌های ساخته‌شده دیده شد',
                'image_url': '', 'flags': [('در کتابخانه', False)], 'ok': False,
                'admin': '/admin/app/exerciselibrary/add/',
            })
    elif kind == 'equipment':
        qs = cat_qs
        if q:
            qs = qs.filter(name__icontains=q)
        for c in qs:
            has_img = _cov_flag(getattr(c, 'image', None))
            if show == 'missing' and has_img:
                continue
            rows.append({
                'id': c.pk,
                'code': c.pk,
                'name': c.name,
                'extra': (c.muscle_group or '') or '—',
                'image_url': (c.image.url if has_img else ''),
                'flags': [('عکس', has_img)],
                'ok': has_img,
                'admin': '/admin/app/equipmentcatalog/%d/change/' % c.pk,
            })
    else:
        qs = ex_qs
        if q:
            from django.db.models import Q
            qs = qs.filter(Q(name_fa__icontains=q) | Q(name__icontains=q)
                           | Q(external_id__icontains=q))
        for e in qs:
            has_thumb = _cov_flag(getattr(e, 'thumb', None))
            has_gif = _cov_flag(getattr(e, 'gif', None))
            has_steps = _cov_flag(e.steps_fa)
            has_fa = _cov_flag(e.name_fa)
            ok = has_thumb and has_gif and has_steps and has_fa
            if show == 'missing' and ok:
                continue
            rows.append({
                'id': e.pk,
                'code': e.external_id,
                'name': e.name_fa or e.name,
                'extra': (e.equipment_fa or e.body_part_fa or '') or '—',
                'image_url': (e.thumb.url if has_thumb else ''),
                'flags': [('عکس', has_thumb), ('آموزشِ ویدیویی', has_gif),
                          ('مراحلِ فارسی', has_steps), ('نامِ فارسی', has_fa)],
                'ok': ok,
                'admin': '/admin/app/exerciselibrary/%d/change/' % e.pk,
            })

    if request.GET.get('format') == 'csv':
        import csv
        from django.http import HttpResponse
        resp = HttpResponse(content_type='text/csv; charset=utf-8')
        resp['Content-Disposition'] = 'attachment; filename="coverage-%s.csv"' % kind
        resp.write('\ufeff')          # تا اکسلِ ویندوز فارسی را درست بخواند
        w = csv.writer(resp)
        head = ['کد', 'نام', 'توضیح'] + [f[0] for f in (rows[0]['flags'] if rows else [])]
        w.writerow(head)
        for r in rows:
            w.writerow([r['code'], r['name'], r['extra']]
                       + ['دارد' if f[1] else 'ندارد' for f in r['flags']])
        return resp

    page = Paginator(rows, 60).get_page(request.GET.get('page'))
    return render(request, 'app/panel/coverage.html', {
        'page_obj': page,
        'rows': page.object_list,
        'summary': summary,
        'kind': kind,
        'show': show,
        'q': q,
        'total_rows': len(rows),
    })
