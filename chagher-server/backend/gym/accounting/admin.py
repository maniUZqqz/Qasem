# -*- coding: utf-8 -*-
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q, Sum
from django.http import HttpResponseNotAllowed, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils import timezone
from django.utils.html import format_html, format_html_join

from . import jalali, services, views
from .forms import (JournalEntryForm, JournalLineForm, JournalLineFormSet, ReverseForm,
                    SettingsForm)
from .models import (Account, AccountingSettings, FiscalYear, JournalEntry, JournalLine,
                     Partner, currency)
from .services import money


def _money_cell(n):
    n = int(n or 0)
    if n < 0:
        return format_html('<span style="color:#c0392b">({})</span>', format(-n, ','))
    return format(n, ',')


# ─────────────────────────────── سرفصلِ حساب‌ها ───────────────────────────────
@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    list_display = ['code_name', 'level', 'account_type', 'normal_side', 'is_cash', 'balance_col',
                    'ledger_link', 'is_active']
    list_display_links = ['code_name']
    list_filter = ['account_type', 'level', 'is_cash', 'is_active']
    search_fields = ['code', 'name']
    list_per_page = 300
    fields = ['parent', 'code', 'name', 'account_type', 'normal_side', 'is_cash',
              'card_payment_account', 'is_active', 'description', 'role_info']

    def get_queryset(self, request):
        posted = Q(lines__entry__status=JournalEntry.POSTED)
        return (super().get_queryset(request).select_related('parent', 'partner')
                .annotate(_d=Sum('lines__debit', filter=posted), _c=Sum('lines__credit', filter=posted)))

    def get_readonly_fields(self, request, obj=None):
        ro = ['role_info']
        if obj is not None:
            if obj.role or obj.partner_id:
                ro += ['parent', 'code', 'account_type']
            if obj.has_lines():
                ro += ['parent', 'account_type', 'normal_side']
        return list(dict.fromkeys(ro))

    @admin.display(description='حساب', ordering='code')
    def code_name(self, obj):
        pad = ' ' * (obj.level - 1)
        if obj.level < 3:
            return format_html('{}<b>{} — {}</b>', pad, obj.code, obj.name)
        return format_html('{}{} — {}', pad, obj.code, obj.name)

    @admin.display(description='مانده')
    def balance_col(self, obj):
        if obj.level == 3:
            d, c = obj._d or 0, obj._c or 0
        else:
            agg = JournalLine.objects.filter(entry__status=JournalEntry.POSTED,
                                             account__code__startswith=obj.code).aggregate(
                d=Sum('debit'), c=Sum('credit'))
            d, c = agg['d'] or 0, agg['c'] or 0
        if not d and not c:
            return '—'
        return _money_cell(obj.signed(d, c))

    @admin.display(description='دفتر')
    def ledger_link(self, obj):
        return format_html('<a href="{}?account={}">دفترِ حساب</a>',
                           reverse('admin:accounting_report_ledger'), obj.pk)

    @admin.display(description='نقش')
    def role_info(self, obj):
        if not obj or not obj.pk:
            return '—'
        parts = []
        if obj.role:
            parts.append('حسابِ سیستمی: %s' % obj.get_role_display())
        if obj.partner_id:
            parts.append('مالِ شریک: %s' % obj.partner)
        return '، '.join(parts) or '—'

    def has_delete_permission(self, request, obj=None):
        if obj is not None and (obj.role or obj.partner_id or obj.has_lines() or obj.children.exists()):
            return False
        return super().has_delete_permission(request, obj)


# ──────────────────────────────────── شرکا ────────────────────────────────────
@admin.register(Partner)
class PartnerAdmin(admin.ModelAdmin):
    list_display = ['name', 'share_col', 'capital_col', 'drawing_col', 'current_col', 'user', 'is_active']
    fields = ['name', 'user', 'share_percent', 'is_active', 'note', 'accounts_info']
    readonly_fields = ['accounts_info']
    autocomplete_fields = ['user']

    def _bal(self, obj, role):
        acc = obj.account(role)
        if not acc:
            return 0
        agg = acc.lines.filter(entry__status=JournalEntry.POSTED).aggregate(d=Sum('debit'), c=Sum('credit'))
        return (agg['c'] or 0) - (agg['d'] or 0)

    @admin.display(description='سهم از سود', ordering='share_percent')
    def share_col(self, obj):
        return '%s٪' % services.pct(obj.share_percent)

    @admin.display(description='سرمایه')
    def capital_col(self, obj):
        return _money_cell(self._bal(obj, 'partner_capital'))

    @admin.display(description='برداشت')
    def drawing_col(self, obj):
        return _money_cell(-self._bal(obj, 'partner_drawing'))

    @admin.display(description='جاری (طلب از شرکت)')
    def current_col(self, obj):
        return _money_cell(self._bal(obj, 'partner_current'))

    @admin.display(description='حساب‌های این شریک')
    def accounts_info(self, obj):
        if not obj or not obj.pk:
            return 'بعد از ذخیره، سه حسابِ «سرمایه»، «برداشت» و «جاری» خودکار ساخته می‌شود.'
        accs = obj.accounts.order_by('code')
        return format_html_join(
            format_html('<br>'), '<a href="{}?account={}">{} — {}</a>',
            ((reverse('admin:accounting_report_ledger'), a.pk, a.code, a.name) for a in accs))

    def _warn_shares(self, request):
        active = Partner.objects.filter(is_active=True)
        total = Partner.share_total()
        if active.exists() and total != 100:
            messages.warning(request, 'جمعِ سهمِ شرکای فعال %s٪ است؛ برای بستنِ سال باید دقیقاً ۱۰۰٪ باشد.'
                             % services.pct(total))

    def changelist_view(self, request, extra_context=None):
        if request.method == 'GET':
            self._warn_shares(request)
        return super().changelist_view(request, extra_context)

    def has_delete_permission(self, request, obj=None):
        if obj is not None and (obj.lines.exists() or
                                JournalLine.objects.filter(account__partner=obj).exists()):
            return False
        return super().has_delete_permission(request, obj)


# ──────────────────────────────────── سالِ مالی ────────────────────────────────────
@admin.register(FiscalYear)
class FiscalYearAdmin(admin.ModelAdmin):
    list_display = ['__str__', 'start_col', 'end_col', 'entries_col', 'status_col', 'close_link']
    fields = ['jalali_year', 'start_col', 'end_col', 'status_col']
    readonly_fields = ['start_col', 'end_col', 'status_col']

    def get_readonly_fields(self, request, obj=None):
        ro = list(self.readonly_fields)
        if obj is not None and (obj.is_closed or obj.entries.exists()):
            ro.insert(0, 'jalali_year')
        return ro

    @admin.display(description='آغاز', ordering='start_date')
    def start_col(self, obj):
        return obj.start_jalali if obj and obj.pk else '(خودکار: ۱ فروردین)'

    @admin.display(description='پایان')
    def end_col(self, obj):
        return obj.end_jalali if obj and obj.pk else '(خودکار: پایانِ اسفند)'

    @admin.display(description='سندهای قطعی')
    def entries_col(self, obj):
        return obj.entries.filter(status=JournalEntry.POSTED).count()

    @admin.display(description='وضعیت')
    def status_col(self, obj):
        if not obj or not obj.pk:
            return '—'
        if obj.is_closed:
            return 'بسته شد در %s به دستِ %s' % (jalali.fmt_datetime(obj.closed_at), obj.closed_by or '—')
        return 'باز'

    @admin.display(description='')
    def close_link(self, obj):
        if obj.is_closed:
            return '🔒'
        return format_html('<a href="{}">بستنِ سال…</a>',
                           reverse('admin:accounting_fiscalyear_close', args=[obj.pk]))

    def has_change_permission(self, request, obj=None):
        if obj is not None and obj.is_closed:
            return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        if obj is not None and (obj.is_closed or obj.entries.exists()):
            return False
        return super().has_delete_permission(request, obj)

    def get_urls(self):
        return [path('<path:object_id>/close/', self.admin_site.admin_view(self.close_view),
                     name='accounting_fiscalyear_close')] + super().get_urls()

    def close_view(self, request, object_id):
        if not request.user.has_perm('accounting.close_fiscalyear'):
            raise PermissionDenied
        fy = get_object_or_404(FiscalYear, pk=object_id)
        if request.method == 'POST':
            try:
                made = services.close_year(fy, request.user)
            except ValidationError as e:
                for m in e.messages:
                    messages.error(request, m)
            else:
                self.log_change(request, fy, 'بستنِ سال (%d سند)' % len(made))
                messages.success(request, '%s بسته شد و %d سندِ بستن ثبت شد.' % (fy, len(made)))
                return redirect('admin:accounting_fiscalyear_changelist')
        preview = services.closing_preview(fy)
        ctx = dict(self.admin_site.each_context(request), title='بستنِ %s' % fy, fy=fy, p=preview,
                   opts=self.model._meta, currency=currency())
        return TemplateResponse(request, 'admin/accounting/close_year.html', ctx)


# ──────────────────────────────────── سند ────────────────────────────────────
class JournalLineInline(admin.TabularInline):
    model = JournalLine
    form = JournalLineForm
    formset = JournalLineFormSet
    extra = 0
    verbose_name = 'ردیف'
    verbose_name_plural = 'ردیف‌ها — هر ردیف فقط بدهکار یا فقط بستانکار؛ جمعِ دو ستون باید برابر شود'
    POSTED_FIELDS = ['account', 'debit_col', 'credit_col', 'partner', 'note']

    def _posted(self, obj):
        return obj is not None and obj.is_posted

    def get_extra(self, request, obj=None, **kwargs):
        return 0 if self._posted(obj) else (4 if obj is None else 1)

    def get_fields(self, request, obj=None):
        if self._posted(obj):
            return self.POSTED_FIELDS
        return ['account', 'debit', 'credit', 'partner', 'note']

    def get_readonly_fields(self, request, obj=None):
        return self.POSTED_FIELDS if self._posted(obj) else []

    def has_add_permission(self, request, obj=None):
        return not self._posted(obj) and super().has_add_permission(request, obj)

    def has_change_permission(self, request, obj=None):
        return not self._posted(obj) and super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return not self._posted(obj) and super().has_delete_permission(request, obj)

    def has_view_permission(self, request, obj=None):
        return request.user.has_perm('accounting.view_journalentry')

    @admin.display(description='بدهکار')
    def debit_col(self, line):
        return money(line.debit) if line.debit else ''

    @admin.display(description='بستانکار')
    def credit_col(self, line):
        return money(line.credit) if line.credit else ''


@admin.register(JournalEntry)
class JournalEntryAdmin(admin.ModelAdmin):
    form = JournalEntryForm
    inlines = [JournalLineInline]
    list_display = ['number_col', 'date_col', 'description', 'kind', 'status_col', 'total_col',
                    'created_by', 'posted_by']
    list_display_links = ['number_col', 'description']
    list_filter = ['status', 'kind', 'fiscal_year']
    search_fields = ['description', 'lines__note', 'source_ref']
    list_select_related = ['fiscal_year', 'created_by', 'posted_by']
    list_per_page = 50
    actions = ['post_selected', 'delete_drafts']
    change_form_template = 'admin/accounting/journalentry/change_form.html'
    POSTED_FIELDS = ['number_col', 'date_col', 'description', 'kind', 'status', 'total_col',
                     'attachment', 'reversal_info', 'audit_info']

    # ── فهرست ──
    @admin.display(description='شمارهٔ سند', ordering='number')
    def number_col(self, obj):
        if obj.is_posted:
            return '%s / %s' % (obj.number, obj.fiscal_year.jalali_year)
        return 'پیش‌نویس #%s' % obj.pk

    @admin.display(description='تاریخ', ordering='date')
    def date_col(self, obj):
        return obj.jalali_date

    @admin.display(description='وضعیت', ordering='status')
    def status_col(self, obj):
        if obj.is_posted:
            if hasattr(obj, 'reversed_by'):
                return format_html('<span style="color:#8a5700">قطعی — برگشت خورده</span>')
            return format_html('<span style="color:#1b7a4b">✔ قطعی</span>')
        return format_html('<span style="color:#c0392b">پیش‌نویس</span>')

    @admin.display(description='مبلغ')
    def total_col(self, obj):
        if obj.is_posted:
            return money(obj.total)
        d, c = obj.totals()
        return money(d) if d == c else format_html('<span style="color:#c0392b">{} ≠ {}</span>',
                                                    money(d), money(c))

    @admin.display(description='برگشت')
    def reversal_info(self, obj):
        parts = []
        if obj.reversal_of_id:
            parts.append(format_html('این سند برگشتِ <a href="{}">{}</a> است.',
                                     obj.reversal_of.get_admin_url(), obj.reversal_of))
        rev = getattr(obj, 'reversed_by', None) if obj.pk else None
        if rev:
            parts.append(format_html('این سند با <a href="{}">{}</a> برگشت خورده است.',
                                     rev.get_admin_url(), rev))
        return format_html_join(format_html('<br>'), '{}', ((p,) for p in parts)) if parts else '—'

    @admin.display(description='ردپا')
    def audit_info(self, obj):
        if not obj.pk:
            return '—'
        s = format_html('ساخت: {} — {}', obj.created_by or 'سیستم', jalali.fmt_datetime(obj.created_at))
        if obj.is_posted:
            s = format_html('{}<br>ثبتِ قطعی: {} — {}', s, obj.posted_by or 'سیستم',
                            jalali.fmt_datetime(obj.posted_at))
        if obj.source_ref:
            s = format_html('{}<br>مرجعِ خودکار: {}', s, obj.source_ref)
        return s

    @admin.display(description='جمعِ ردیف‌ها')
    def totals_info(self, obj):
        d, c = obj.totals()
        ok = 'برابر ✔' if d == c and d else 'نابرابر ✘'
        return 'بدهکار %s — بستانکار %s (%s)' % (money(d), money(c), ok)

    # ── فرم ──
    def get_fields(self, request, obj=None):
        if obj is not None and obj.is_posted:
            return self.POSTED_FIELDS
        if obj is not None:
            return ['date', 'description', 'attachment', 'totals_info', 'audit_info']
        return ['date', 'description', 'attachment']

    def get_readonly_fields(self, request, obj=None):
        if obj is not None and obj.is_posted:
            return self.POSTED_FIELDS
        if obj is not None:
            return ['totals_info', 'audit_info']
        return []

    def has_change_permission(self, request, obj=None):
        if obj is not None and obj.is_posted:
            return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        if obj is not None and obj.is_posted:
            return False
        return super().has_delete_permission(request, obj)

    def has_post_permission(self, request):
        return request.user.has_perm('accounting.post_journalentry')

    def get_search_results(self, request, queryset, search_term):
        qs, dup = super().get_search_results(request, queryset, search_term)
        t = jalali.to_ascii_digits(search_term).strip()
        if t.isdigit():
            qs = qs | queryset.filter(number=int(t))
            dup = True
        return qs, dup

    def get_actions(self, request):
        actions = super().get_actions(request)
        actions.pop('delete_selected', None)
        return actions

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

    def _post_after_save(self, request, obj):
        if '_post' not in request.POST:
            return
        if not self.has_post_permission(request):
            messages.error(request, 'اجازهٔ «ثبتِ قطعی» ندارید؛ سند پیش‌نویس ماند.')
            return
        try:
            entry = services.post_entry(obj, request.user)
        except ValidationError as e:
            messages.error(request, 'ثبتِ قطعی نشد: ' + ' '.join(e.messages))
        else:
            self.log_change(request, entry, 'ثبتِ قطعی با شمارهٔ %s' % entry.number)
            messages.success(request, '%s ثبتِ قطعی شد.' % entry)

    def response_add(self, request, obj, post_url_continue=None):
        if '_post' in request.POST:
            self._post_after_save(request, obj)
            return HttpResponseRedirect(obj.get_admin_url())
        return super().response_add(request, obj, post_url_continue)

    def response_change(self, request, obj):
        if '_post' in request.POST:
            self._post_after_save(request, obj)
            return HttpResponseRedirect(obj.get_admin_url())
        return super().response_change(request, obj)

    def render_change_form(self, request, context, add=False, change=False, form_url='', obj=None):
        context.update({
            'can_post': self.has_post_permission(request),
            'can_add_entry': self.has_add_permission(request),
            'entry': obj,
            'can_reverse': bool(
                obj is not None and obj.is_posted
                and obj.kind not in (JournalEntry.KIND_REVERSAL, JournalEntry.KIND_CLOSING)
                and not hasattr(obj, 'reversed_by')
                and self.has_post_permission(request) and self.has_add_permission(request)),
        })
        return super().render_change_form(request, context, add, change, form_url, obj)

    # ── کارهای گروهی ──
    @admin.action(description='ثبتِ قطعیِ پیش‌نویس‌های انتخاب‌شده', permissions=['post'])
    def post_selected(self, request, queryset):
        ok, bad = 0, []
        for e in queryset.filter(status=JournalEntry.DRAFT).order_by('date', 'pk'):
            try:
                e = services.post_entry(e, request.user)
            except ValidationError as ex:
                bad.append('%s: %s' % (e, ' '.join(ex.messages)))
            else:
                self.log_change(request, e, 'ثبتِ قطعی با شمارهٔ %s' % e.number)
                ok += 1
        if ok:
            messages.success(request, '%d سند ثبتِ قطعی شد.' % ok)
        for b in bad:
            messages.error(request, b)

    @admin.action(description='پاک‌کردنِ پیش‌نویس‌های انتخاب‌شده (سندِ قطعی پاک نمی‌شود)',
                  permissions=['delete'])
    def delete_drafts(self, request, queryset):
        drafts = list(queryset.filter(status=JournalEntry.DRAFT))
        skipped = queryset.exclude(status=JournalEntry.DRAFT).count()
        for e in drafts:
            self.log_change(request, e, 'پیش‌نویس پاک شد')
            e.delete()
        if drafts:
            messages.success(request, '%d پیش‌نویس پاک شد.' % len(drafts))
        if skipped:
            messages.warning(request, '%d سندِ قطعی پاک نشد (قطعی‌ها فقط با سندِ برگشتی اصلاح می‌شوند).' % skipped)

    # ── صفحه‌های اضافه ──
    def get_urls(self):
        w = self.admin_site.admin_view
        return [
            path('<path:object_id>/post/', w(self.post_view), name='accounting_journalentry_post'),
            path('<path:object_id>/reverse/', w(self.reverse_view), name='accounting_journalentry_reverse'),
            path('<path:object_id>/copy/', w(self.copy_view), name='accounting_journalentry_copy'),
        ] + super().get_urls()

    def post_view(self, request, object_id):
        if request.method != 'POST':
            return HttpResponseNotAllowed(['POST'])
        if not self.has_post_permission(request):
            raise PermissionDenied
        entry = get_object_or_404(JournalEntry, pk=object_id)
        try:
            entry = services.post_entry(entry, request.user)
        except ValidationError as e:
            messages.error(request, 'ثبتِ قطعی نشد: ' + ' '.join(e.messages))
        else:
            self.log_change(request, entry, 'ثبتِ قطعی با شمارهٔ %s' % entry.number)
            messages.success(request, '%s ثبتِ قطعی شد.' % entry)
        return HttpResponseRedirect(entry.get_admin_url())

    def reverse_view(self, request, object_id):
        if not (self.has_post_permission(request) and self.has_add_permission(request)):
            raise PermissionDenied
        entry = get_object_or_404(JournalEntry, pk=object_id)
        if request.method == 'POST':
            form = ReverseForm(request.POST)
            if form.is_valid():
                try:
                    rev = services.reverse_entry(entry, request.user, date=form.cleaned_data['date'],
                                                 description=form.cleaned_data['description'])
                except ValidationError as e:
                    form.add_error(None, e)
                else:
                    self.log_addition(request, rev, 'سندِ برگشتیِ %s' % entry)
                    messages.success(request, format_html(
                        '{} ثبت شد و اثرِ <a href="{}">{}</a> را خنثی کرد.',
                        rev, entry.get_admin_url(), entry))
                    return HttpResponseRedirect(rev.get_admin_url())
        else:
            form = ReverseForm(initial={'date': max(timezone.localdate(), entry.date)})
        ctx = dict(self.admin_site.each_context(request), title='سندِ برگشتی برای %s' % entry,
                   entry=entry, form=form, opts=self.model._meta, currency=currency(),
                   lines=entry.lines.select_related('account', 'partner'))
        return TemplateResponse(request, 'admin/accounting/reverse.html', ctx)

    def copy_view(self, request, object_id):
        if request.method != 'POST':
            return HttpResponseNotAllowed(['POST'])
        if not self.has_add_permission(request):
            raise PermissionDenied
        entry = get_object_or_404(JournalEntry, pk=object_id)
        try:
            new = services.copy_as_draft(entry, request.user)
        except ValidationError as e:
            messages.error(request, 'کپی نشد: ' + ' '.join(e.messages))
            return HttpResponseRedirect(entry.get_admin_url())
        self.log_addition(request, new, 'کپی از %s' % entry)
        messages.success(request, 'پیش‌نویسِ تازه از روی %s ساخته شد؛ اصلاح کنید و ثبتِ قطعی بزنید.' % entry)
        return HttpResponseRedirect(new.get_admin_url())


# ──────────────────────────────── تنظیمات ────────────────────────────────
@admin.register(AccountingSettings)
class AccountingSettingsAdmin(admin.ModelAdmin):
    form = SettingsForm

    def has_add_permission(self, request):
        return not AccountingSettings.objects.exists() and super().has_add_permission(request)

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        obj = AccountingSettings.get()
        return redirect('admin:accounting_accountingsettings_change', obj.pk)


# ─────────────── نشانی‌های صفحه‌های حسابداری + ردیفِ «داشبورد» در صفحهٔ اولِ ادمین ───────────────
_orig_get_urls = admin.site.get_urls


def _get_urls():
    return views.urls() + _orig_get_urls()


admin.site.get_urls = _get_urls

_orig_get_app_list = admin.site.get_app_list


def _get_app_list(request, app_label=None):
    app_list = _orig_get_app_list(request, app_label)
    if app_label:
        return app_list
    try:
        prefix = reverse('admin:app_list', kwargs={'app_label': 'accounting'})
    except Exception:
        return app_list
    for app in app_list:
        models = app.get('models') or []
        if any((m.get('admin_url') or '').startswith(prefix) for m in models):
            extra = [{'name': '🏠 داشبورد، ثبتِ سریع و گزارش‌ها', 'object_name': 'AccountingDashboard',
                      'admin_url': prefix, 'add_url': None, 'view_only': True,
                      'perms': {'add': False, 'change': False, 'delete': False, 'view': True}},
                     {'name': '❔ راهنمای حسابداری', 'object_name': 'AccountingHelp',
                      'admin_url': reverse('admin:accounting_help'), 'add_url': None, 'view_only': True,
                      'perms': {'add': False, 'change': False, 'delete': False, 'view': True}}]
            app['models'] = extra + [m for m in models if m.get('object_name') not in
                                     ('AccountingDashboard', 'AccountingHelp')]
            break
    return app_list


admin.site.get_app_list = _get_app_list
