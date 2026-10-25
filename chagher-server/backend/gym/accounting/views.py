# -*- coding: utf-8 -*-
"""صفحه‌های حسابداری داخلِ جنگو ادمین: پنج فرمِ ساده، گزارش‌ها، واردکردنِ پرداخت‌ها، راهنما."""
import csv
import datetime as _dt
import mimetypes
import os

from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html

from . import jalali, reports, services
from .forms import SIMPLE_FORMS, AsOfForm, LedgerForm, PeriodForm, TrialForm
from .models import Account, FiscalYear, JournalEntry, Partner, attachment_storage, currency


def _require(request, *perms):
    if not all(request.user.has_perm(p) for p in perms):
        raise PermissionDenied


def _render(request, template, title, **ctx):
    context = dict(admin.site.each_context(request))
    context.update({'title': title, 'currency': currency(), 'app_label': 'accounting',
                    'opts': JournalEntry._meta})
    context.update(ctx)
    return TemplateResponse(request, template, context)


def _log(request, obj, message):
    from django.contrib.admin.models import ADDITION, LogEntry
    from django.contrib.contenttypes.models import ContentType
    try:
        LogEntry.objects.log_actions(
            user_id=request.user.pk, queryset=[obj], action_flag=ADDITION,
            change_message=message, single_object=True)
    except AttributeError:  # جنگوی قدیمی‌تر
        LogEntry.objects.log_action(
            user_id=request.user.pk, content_type_id=ContentType.objects.get_for_model(obj).pk,
            object_id=obj.pk, object_repr=str(obj)[:200], action_flag=ADDITION,
            change_message=message)


def entry_link(entry):
    return format_html('<a href="{}">{}</a>', entry.get_admin_url(), entry)


# ─────────────────────────────── پنج فرمِ ساده ───────────────────────────────
def simple_form_view(request, kind):
    FormCls = SIMPLE_FORMS.get(kind)
    if FormCls is None:
        raise Http404
    _require(request, 'accounting.add_journalentry')
    cur = currency()
    can_post = request.user.has_perm('accounting.post_journalentry')
    if request.method == 'POST':
        form = FormCls(request.POST, request.FILES, currency=cur)
        if form.is_valid():
            try:
                entry = form.save(user=request.user, post=can_post)
            except ValidationError as e:
                form.add_error(None, e)
            else:
                _log(request, entry, '%s از فرمِ ساده' % FormCls.title)
                if entry.is_posted:
                    messages.success(request, format_html(
                        'ثبت شد: {} — {} {}', entry_link(entry), services.money(entry.total), cur))
                else:
                    messages.warning(request, format_html(
                        'به‌صورتِ پیش‌نویس ذخیره شد ({}). کسی که اجازهٔ «ثبتِ قطعی» دارد باید قطعی‌اش کند.',
                        entry_link(entry)))
                return redirect(request.path)
    else:
        form = FormCls(currency=cur)
    others = [(k, F.title) for k, F in SIMPLE_FORMS.items()]
    return _render(request, 'admin/accounting/simple_form.html', FormCls.title,
                   form=form, intro=FormCls.intro, kind=kind, others=others, can_post=can_post,
                   no_cash=not Account.cash_accounts().exists(),
                   no_partner=kind in ('contribution', 'drawing') and not Partner.objects.filter(is_active=True).exists())


# ─────────────────────────────── گزارش‌ها ───────────────────────────────
def _default_period():
    today = timezone.localdate()
    fy = FiscalYear.for_date(today)
    start = fy.start_date if fy else jalali.year_bounds(jalali.to_jalali(today)[0])[0]
    return start, today


def _preset(request):
    today = timezone.localdate()
    p = request.GET.get('preset')
    if p == 'month':
        return jalali.month_bounds(today)[0], today
    if p == 'prev_month':
        start, _ = jalali.month_bounds(today)
        prev_end = start - _dt.timedelta(days=1)
        return jalali.month_bounds(prev_end)
    if p == 'fy':
        return _default_period()
    if p == 'all':
        return None, today
    return None


def _period(request, FormCls=PeriodForm):
    """بازهٔ گزارش: پیش‌فرض از آغازِ سالِ مالیِ جاری تا امروز؛ «از» خالی = از آغازِ دفترها."""
    d_from, d_to = _default_period()
    data = request.GET.copy()
    preset = _preset(request)
    if preset:
        d_from, d_to = preset
        data['date_from'] = jalali.fmt(d_from, '')
        data['date_to'] = jalali.fmt(d_to, '')
    else:
        if 'date_from' not in data:
            data['date_from'] = jalali.fmt(d_from, '')
        if 'date_to' not in data:
            data['date_to'] = jalali.fmt(d_to, '')
    form = FormCls(data)
    if form.is_valid():
        d_from = form.cleaned_data.get('date_from')
        d_to = form.cleaned_data.get('date_to') or d_to
    return form, d_from, d_to


def _csv(filename, header, rows):
    resp = HttpResponse(content_type='text/csv; charset=utf-8')
    resp['Content-Disposition'] = 'attachment; filename="%s"' % filename
    resp.write('﻿')
    w = csv.writer(resp)
    w.writerow(header)
    for r in rows:
        w.writerow(r)
    return resp


def _range_label(d_from, d_to):
    return 'از %s تا %s' % (jalali.fmt(d_from, 'آغاز'), jalali.fmt(d_to))


def report_pl(request):
    _require(request, 'accounting.view_reports')
    form, d_from, d_to = _period(request)
    r = reports.profit_loss(d_from, d_to)
    if request.GET.get('export') == 'csv':
        rows = [['درآمدها', '', '']]
        for sec in r['income']:
            for x in sec['rows']:
                rows.append([x['account'].code, x['account'].name, x['amount']])
        rows.append(['', 'جمعِ درآمد', r['total_income']])
        rows.append(['هزینه‌ها', '', ''])
        for sec in r['expense']:
            for x in sec['rows']:
                rows.append([x['account'].code, x['account'].name, x['amount']])
        rows.append(['', 'جمعِ هزینه', r['total_expense']])
        rows.append(['', 'سود (زیان) خالص', r['profit']])
        return _csv('profit-loss.csv', ['کد', 'حساب', 'مبلغ (%s)' % currency()], rows)
    return _render(request, 'admin/accounting/report_pl.html', 'سود و زیان', form=form, r=r,
                   range_label=_range_label(d_from, d_to))


def report_balance(request):
    _require(request, 'accounting.view_reports')
    form = AsOfForm(request.GET or None, initial={'date_to': timezone.localdate()})
    as_of = timezone.localdate()
    if request.GET and form.is_valid() and form.cleaned_data.get('date_to'):
        as_of = form.cleaned_data['date_to']
    r = reports.balance_sheet(as_of)
    if request.GET.get('export') == 'csv':
        rows = []
        for title, secs in (('دارایی‌ها', r['assets']), ('بدهی‌ها', r['liabilities']),
                            ('حقوقِ صاحبانِ سرمایه', r['equity'])):
            rows.append([title, '', ''])
            for sec in secs:
                for x in sec['rows']:
                    rows.append([x['account'].code, x['account'].name, x['amount']])
        rows.append(['', 'سود و زیانِ دورهٔ بسته‌نشده', r['unclosed_profit']])
        rows.append(['', 'جمعِ دارایی‌ها', r['total_assets']])
        rows.append(['', 'جمعِ بدهی‌ها و سرمایه', r['total_le']])
        return _csv('balance-sheet.csv', ['کد', 'حساب', 'مبلغ (%s)' % currency()], rows)
    return _render(request, 'admin/accounting/report_balance.html', 'ترازنامه', form=form, r=r,
                   as_of=jalali.fmt(as_of))


def report_trial(request):
    _require(request, 'accounting.view_reports')
    form, d_from, d_to = _period(request, TrialForm)
    level = 3
    if form.is_bound and form.is_valid() and form.cleaned_data.get('level'):
        level = form.cleaned_data['level']
    r = reports.trial_balance(d_from, d_to, level=level)
    if request.GET.get('export') == 'csv':
        rows = [[x['account'].code, x['account'].name, x['open_d'], x['open_c'], x['pd'], x['pc'],
                 x['cd'], x['cc']] for x in r['rows']]
        t = r['totals']
        rows.append(['', 'جمع', t['open_d'], t['open_c'], t['pd'], t['pc'], t['cd'], t['cc']])
        return _csv('trial-balance.csv', ['کد', 'حساب', 'ماندهٔ اول بدهکار', 'ماندهٔ اول بستانکار',
                                          'گردشِ بدهکار', 'گردشِ بستانکار', 'ماندهٔ بدهکار',
                                          'ماندهٔ بستانکار'], rows)
    return _render(request, 'admin/accounting/report_trial.html', 'ترازِ آزمایشی', form=form, r=r,
                   range_label=_range_label(d_from, d_to), level=level, keep='&level=%s' % level)


def report_ledger(request):
    _require(request, 'accounting.view_reports')
    form, d_from, d_to = _period(request, LedgerForm)
    account = None
    if form.is_bound and form.is_valid():
        account = form.cleaned_data.get('account')
    r = reports.ledger(account, d_from, d_to) if account else None
    if r and request.GET.get('export') == 'csv':
        rows = [['', 'ماندهٔ اولِ دوره', '', '', '', '', r['opening']]]
        for x in r['rows']:
            e = x['entry']
            rows.append([x['jdate'], e.number, x['line'].account.code,
                         e.description + (' — ' + x['line'].note if x['line'].note else ''),
                         x['debit'], x['credit'], x['balance']])
        rows.append(['', 'جمع', '', '', r['total_debit'], r['total_credit'], r['closing']])
        return _csv('ledger-%s.csv' % account.code,
                    ['تاریخ', 'شمارهٔ سند', 'حساب', 'شرح', 'بدهکار', 'بستانکار', 'مانده'], rows)
    return _render(request, 'admin/accounting/report_ledger.html',
                   'دفترِ حساب' + (' — %s' % account if account else ''), form=form, r=r,
                   range_label=_range_label(d_from, d_to),
                   keep=('&account=%s' % account.pk) if account else '')


def report_partners(request):
    _require(request, 'accounting.view_reports')
    form = AsOfForm(request.GET or None, initial={'date_to': timezone.localdate()})
    as_of = timezone.localdate()
    if request.GET and form.is_valid() and form.cleaned_data.get('date_to'):
        as_of = form.cleaned_data['date_to']
    r = reports.partners_status(as_of)
    if request.GET.get('export') == 'csv':
        rows = [[x['partner'].name, services.pct(x['partner'].share_percent), x['capital'], x['pocket'],
                 x['invested'], x['drawing'], x['profit'], x['est'], x['balance']] for x in r['rows']]
        return _csv('partners.csv', ['شریک', 'سهم ٪', 'آوردهٔ سرمایه', 'پرداخت از جیب (خالص)',
                                     'جمعِ آورده', 'برداشت', 'سودِ بسته‌شده', 'سهم از سودِ باز (تخمین)',
                                     'ماندهٔ شریک'], rows)
    return _render(request, 'admin/accounting/report_partners.html', 'وضعیتِ شرکا', form=form, r=r,
                   as_of=jalali.fmt(as_of), share_total=Partner.share_total())


def report_cash(request):
    _require(request, 'accounting.view_reports')
    form, d_from, d_to = _period(request)
    r = reports.cash_status(d_from, d_to)
    if request.GET.get('export') == 'csv':
        rows = [[x['account'].code, x['account'].name, x['open'], x['in'], x['out'], x['close']]
                for x in r['rows']]
        t = r['totals']
        rows.append(['', 'جمع', t['open'], t['in'], t['out'], t['close']])
        return _csv('cash.csv', ['کد', 'حساب', 'ماندهٔ اول', 'ورودی', 'خروجی', 'ماندهٔ پایان'], rows)
    return _render(request, 'admin/accounting/report_cash.html', 'موجودیِ صندوق و بانک', form=form,
                   r=r, range_label=_range_label(d_from, d_to))


# ─────────────────────────────── پرداخت‌های اپ ───────────────────────────────
def import_payments_view(request):
    _require(request, 'accounting.add_journalentry', 'accounting.post_journalentry')
    if request.method == 'POST':
        created, rows, stale = services.import_payments(user=request.user)
        for e in created:
            _log(request, e, 'واردکردنِ پرداختِ اپ')
        if created:
            messages.success(request, '%d پرداخت ثبت شد (جمع %s %s).' % (
                len(created), services.money(sum(e.total for e in created)), currency()))
        else:
            messages.info(request, 'پرداختِ تازه‌ای برای ثبت نبود.')
        return redirect(request.path)
    rows, stale = services.payment_candidates()
    ready = [r for r in rows if not r['problem']]
    blocked = [r for r in rows if r['problem']]
    return _render(request, 'admin/accounting/import_payments.html', 'واردکردنِ پرداخت‌های اپ',
                   ready=ready, blocked=blocked, stale=stale,
                   ready_total=sum(r['amount'] for r in ready),
                   imported=JournalEntry.objects.filter(source_ref__startswith='tokenpurchase:').count())


def help_view(request):
    if not request.user.is_staff:
        raise PermissionDenied
    return _render(request, 'admin/accounting/help.html', 'راهنمای حسابداری')


def attachment_view(request, name):
    _require(request, 'accounting.view_journalentry')
    if '..' in name.split('/') or name.startswith('/'):
        raise Http404
    if not JournalEntry.objects.filter(attachment=name).exists():
        raise Http404
    storage = attachment_storage()
    if not storage.exists(name):
        raise Http404
    ext = name.rsplit('.', 1)[-1].lower() if '.' in name else ''
    ctype = mimetypes.guess_type(name)[0] or 'application/octet-stream'
    inline = ext in ('pdf', 'jpg', 'jpeg', 'png', 'webp', 'gif')
    resp = FileResponse(storage.open(name, 'rb'), content_type=ctype, as_attachment=not inline,
                        filename=os.path.basename(name))
    resp['X-Content-Type-Options'] = 'nosniff'
    return resp


def urls():
    from django.urls import path
    w = admin.site.admin_view
    return [
        path('accounting/new/<slug:kind>/', w(simple_form_view), name='accounting_new'),
        path('accounting/reports/profit-loss/', w(report_pl), name='accounting_report_pl'),
        path('accounting/reports/balance-sheet/', w(report_balance), name='accounting_report_balance'),
        path('accounting/reports/trial-balance/', w(report_trial), name='accounting_report_trial'),
        path('accounting/reports/ledger/', w(report_ledger), name='accounting_report_ledger'),
        path('accounting/reports/partners/', w(report_partners), name='accounting_report_partners'),
        path('accounting/reports/cash/', w(report_cash), name='accounting_report_cash'),
        path('accounting/import-payments/', w(import_payments_view), name='accounting_import_payments'),
        path('accounting/help/', w(help_view), name='accounting_help'),
        path('accounting/attachment/<path:name>', w(attachment_view), name='accounting_attachment'),
    ]
