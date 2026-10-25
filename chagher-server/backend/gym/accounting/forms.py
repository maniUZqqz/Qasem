# -*- coding: utf-8 -*-
import datetime as _dt

from django import forms
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.forms.models import BaseInlineFormSet
from django.utils import timezone

from . import jalali, services
from .models import (ATTACHMENT_EXTENSIONS, Account, AccountingSettings, JournalEntry,
                     JournalLine, Partner, validate_attachment_size)


# ─────────────────────────────── فیلدهای پایه ───────────────────────────────
class JalaliDateWidget(forms.TextInput):
    def __init__(self, attrs=None):
        base = {'placeholder': '۱۴۰۵/۰۸/۰۳', 'dir': 'ltr', 'size': 11,
                'autocomplete': 'off', 'class': 'acc-date'}
        base.update(attrs or {})
        super().__init__(base)

    def format_value(self, value):
        if isinstance(value, _dt.date):
            return jalali.fmt(value)
        return super().format_value(value)


class JalaliDateField(forms.Field):
    widget = JalaliDateWidget
    default_error_messages = {'invalid': 'تاریخ را به شکلِ ۱۴۰۵/۰۸/۰۳ بنویسید.'}

    def to_python(self, value):
        if value in (None, ''):
            return None
        if isinstance(value, _dt.datetime):
            return value.date()
        if isinstance(value, _dt.date):
            return value
        try:
            return jalali.parse(value)
        except ValueError as e:
            raise ValidationError(str(e), code='invalid')

    def prepare_value(self, value):
        if isinstance(value, _dt.date):
            return jalali.fmt(value)
        return value


class AmountWidget(forms.TextInput):
    def __init__(self, attrs=None):
        base = {'dir': 'ltr', 'inputmode': 'numeric', 'autocomplete': 'off',
                'class': 'acc-amount', 'size': 16}
        base.update(attrs or {})
        super().__init__(base)

    def format_value(self, value):
        if value in (None, '', 0, '0'):
            return None
        if isinstance(value, int):
            return format(value, ',')
        return super().format_value(value)


class AmountField(forms.Field):
    """مبلغِ صحیح؛ رقمِ فارسی و جداکنندهٔ هزارگان را می‌پذیرد."""
    widget = AmountWidget

    def __init__(self, *args, min_value=1, empty_value=None, **kwargs):
        self.min_value = min_value
        self.empty_value = empty_value
        super().__init__(*args, **kwargs)

    def to_python(self, value):
        if value in (None, ''):
            return self.empty_value
        if isinstance(value, int):
            return value
        s = jalali.to_ascii_digits(value)
        for ch in (',', '٬', '،', ' ', '_', '‌'):
            s = s.replace(ch, '')
        if not s:
            return self.empty_value
        if not s.isdigit():
            raise ValidationError('مبلغ را فقط با رقم و بی‌اعشار بنویسید.')
        return int(s)

    def validate(self, value):
        super().validate(value)
        if value is None:
            return
        if value < self.min_value:
            raise ValidationError('مبلغ باید بزرگ‌تر از صفر باشد.' if self.min_value == 1
                                  else 'مبلغِ منفی مجاز نیست.')
        if value > 10 ** 15:
            raise ValidationError('مبلغ بیش از اندازه بزرگ است.')

    def prepare_value(self, value):
        return value

    def has_changed(self, initial, data):
        # ردیفِ خالیِ فرم‌ستِ ادمین نباید «تغییرکرده» حساب شود (None و '' و ۰ یکی‌اند)
        try:
            return (self.to_python(initial) or 0) != (self.to_python(data) or 0)
        except ValidationError:
            return True


def _attachment_field():
    return forms.FileField(
        label='فاکتور یا رسید (اختیاری)', required=False,
        validators=[FileExtensionValidator(ATTACHMENT_EXTENSIONS), validate_attachment_size],
        help_text='عکس یا PDF — حداکثر ۱۰ مگابایت.')


def _cash_choices():
    return [(a.pk, '%s — %s' % (a.code, a.name)) for a in Account.cash_accounts()]


def _source_choices(partner_label):
    cash = [('a:%s' % a.pk, '%s — %s' % (a.code, a.name)) for a in Account.cash_accounts()]
    partners = [('p:%s' % p.pk, partner_label % p.name)
                for p in Partner.objects.filter(is_active=True).order_by('name')]
    choices = [('', '— انتخاب کنید —'), ('صندوق و بانکِ چغر', cash)]
    if partners:
        choices.append(('شرکا (با پولِ شخصی)', partners))
    return choices


def _parse_source(value):
    kind, _, pk = (value or '').partition(':')
    if kind == 'a':
        acc = Account.cash_accounts().filter(pk=pk).first()
        if acc:
            return acc, None
    if kind == 'p':
        partner = Partner.objects.filter(pk=pk, is_active=True).first()
        if partner:
            return None, partner
    raise ValidationError('یکی از گزینه‌ها را انتخاب کنید.')


# ─────────────────────────────── پنج فرمِ ساده ───────────────────────────────
class _SimpleForm(forms.Form):
    date = JalaliDateField(label='تاریخ')
    amount = AmountField(label='مبلغ')

    title = ''
    intro = ''

    def __init__(self, *args, currency='تومان', **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['amount'].label = 'مبلغ (%s)' % currency
        if not self.is_bound:
            self.fields['date'].initial = timezone.localdate()
        self.order_fields(['date', 'amount'])

    def clean_date(self):
        d = self.cleaned_data['date']
        services.open_year_for(d)
        return d

    def save(self, user, post=True):  # pragma: no cover - هر فرم خودش دارد
        raise NotImplementedError


class ExpenseForm(_SimpleForm):
    title = 'ثبتِ هزینه'
    intro = ('هر پولی که برای چغر خرج شد: سرور، دامنه، شارژِ API، پیامک، تبلیغ، حقوق… '
             'اگر یکی از شرکا از جیبِ خودش داد، همان را در «از کجا پرداخت شد» انتخاب کنید '
             'تا طلبش در حسابِ جاری‌اش بماند.')
    expense_account = forms.ModelChoiceField(queryset=Account.objects.none(), label='نوعِ هزینه')
    paid_from = forms.ChoiceField(label='از کجا پرداخت شد؟')
    description = forms.CharField(label='شرح (اختیاری)', required=False, max_length=300)
    attachment = _attachment_field()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['expense_account'].queryset = Account.postable().filter(account_type=Account.EXPENSE)
        self.fields['paid_from'].choices = _source_choices('%s از جیبِ خودش پرداخت کرد')

    def clean_paid_from(self):
        return _parse_source(self.cleaned_data['paid_from'])

    def save(self, user, post=True):
        cd = self.cleaned_data
        acc, partner = cd['paid_from']
        return services.record_expense(
            date=cd['date'], amount=cd['amount'], expense_account=cd['expense_account'],
            paid_from=acc, partner=partner, description=cd['description'], user=user,
            attachment=cd.get('attachment'), post=post)


class IncomeForm(_SimpleForm):
    title = 'ثبتِ درآمد'
    intro = ('پولی که از فروش به دستِ چغر رسید و خودکار از اپ نیامده (مثلاً قرارداد با باشگاه یا '
             'اشتراکی که دستی تمدید شد). پرداخت‌های درون‌اپ را با «واردکردنِ پرداخت‌های اپ» بیاورید.')
    income_account = forms.ModelChoiceField(queryset=Account.objects.none(), label='نوعِ درآمد')
    received_in = forms.ChoiceField(label='پول کجا واریز شد؟')
    description = forms.CharField(label='شرح (اختیاری)', required=False, max_length=300)
    attachment = _attachment_field()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['income_account'].queryset = Account.postable().filter(account_type=Account.INCOME)
        self.fields['received_in'].choices = _source_choices('به کارت/حسابِ شخصیِ %s واریز شد')

    def clean_received_in(self):
        return _parse_source(self.cleaned_data['received_in'])

    def save(self, user, post=True):
        cd = self.cleaned_data
        acc, partner = cd['received_in']
        return services.record_income(
            date=cd['date'], amount=cd['amount'], income_account=cd['income_account'],
            received_in=acc, partner=partner, description=cd['description'], user=user,
            attachment=cd.get('attachment'), post=post)


class _PartnerForm(_SimpleForm):
    partner = forms.ModelChoiceField(queryset=Partner.objects.none(), label='شریک')
    description = forms.CharField(label='شرح (اختیاری)', required=False, max_length=300)
    attachment = _attachment_field()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['partner'].queryset = Partner.objects.filter(is_active=True).order_by('name')


class ContributionForm(_PartnerForm):
    title = 'آوردهٔ شریک'
    intro = 'شریک پولی به صندوق یا حسابِ بانکیِ چغر ریخت تا سرمایه‌اش بیشتر شود.'
    cash = forms.TypedChoiceField(label='به کدام صندوق/بانک ریخت؟', coerce=int)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['cash'].choices = [('', '— انتخاب کنید —')] + _cash_choices()

    def save(self, user, post=True):
        cd = self.cleaned_data
        return services.record_contribution(
            date=cd['date'], amount=cd['amount'], partner=cd['partner'],
            into=Account.objects.get(pk=cd['cash']), description=cd['description'], user=user,
            attachment=cd.get('attachment'), post=post)


class DrawingForm(_PartnerForm):
    title = 'برداشتِ شریک'
    intro = 'شریک برای خودش پولی از صندوق یا بانکِ چغر برداشت (از سهمِ سود یا سرمایه‌اش کم می‌شود).'
    cash = forms.TypedChoiceField(label='از کدام صندوق/بانک برداشت؟', coerce=int)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['cash'].choices = [('', '— انتخاب کنید —')] + _cash_choices()

    def save(self, user, post=True):
        cd = self.cleaned_data
        return services.record_drawing(
            date=cd['date'], amount=cd['amount'], partner=cd['partner'],
            from_account=Account.objects.get(pk=cd['cash']), description=cd['description'],
            user=user, attachment=cd.get('attachment'), post=post)


class TransferForm(_SimpleForm):
    title = 'انتقال بینِ صندوق و بانک'
    intro = 'جابه‌جاییِ پول بینِ حساب‌های خودِ چغر (مثلاً برداشتِ نقد از بانک یا واریزِ صندوق به بانک). سود و زیان را عوض نمی‌کند.'
    from_account = forms.TypedChoiceField(label='از', coerce=int)
    to_account = forms.TypedChoiceField(label='به', coerce=int)
    description = forms.CharField(label='شرح (اختیاری)', required=False, max_length=300)
    attachment = _attachment_field()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        ch = [('', '— انتخاب کنید —')] + _cash_choices()
        self.fields['from_account'].choices = ch
        self.fields['to_account'].choices = ch

    def clean(self):
        cd = super().clean()
        if cd.get('from_account') and cd.get('from_account') == cd.get('to_account'):
            raise ValidationError('مبدأ و مقصد یکی است.')
        return cd

    def save(self, user, post=True):
        cd = self.cleaned_data
        return services.record_transfer(
            date=cd['date'], amount=cd['amount'],
            from_account=Account.objects.get(pk=cd['from_account']),
            to_account=Account.objects.get(pk=cd['to_account']),
            description=cd['description'], user=user, attachment=cd.get('attachment'), post=post)


SIMPLE_FORMS = {
    'expense': ExpenseForm,
    'income': IncomeForm,
    'contribution': ContributionForm,
    'drawing': DrawingForm,
    'transfer': TransferForm,
}


# ─────────────────────────────── سندِ دستی در ادمین ───────────────────────────────
class JournalEntryForm(forms.ModelForm):
    date = JalaliDateField(label='تاریخ')

    class Meta:
        model = JournalEntry
        fields = ['date', 'description', 'attachment']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.pk and not self.is_bound:
            self.fields['date'].initial = timezone.localdate()

    def clean_date(self):
        d = self.cleaned_data['date']
        services.open_year_for(d)
        return d


class JournalLineForm(forms.ModelForm):
    debit = AmountField(label='بدهکار', required=False, min_value=0, empty_value=0)
    credit = AmountField(label='بستانکار', required=False, min_value=0, empty_value=0)

    class Meta:
        model = JournalLine
        fields = ['account', 'debit', 'credit', 'partner', 'note']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if 'partner' in self.fields:
            self.fields['partner'].queryset = Partner.objects.filter(is_active=True)
            self.fields['partner'].required = False


class JournalLineFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()
        if any(self.errors):
            return
        lines = []
        for f in self.forms:
            cd = getattr(f, 'cleaned_data', None)
            if not cd or cd.get('DELETE'):
                continue
            if not cd.get('account') and not cd.get('debit') and not cd.get('credit'):
                continue
            lines.append(services.Line(cd.get('account'), cd.get('debit') or 0, cd.get('credit') or 0,
                                       cd.get('partner'), cd.get('note') or ''))
        services.check_lines(lines)


class SettingsForm(forms.ModelForm):
    import_from_date = JalaliDateField(label='واردکردنِ پرداخت‌ها از تاریخ', required=False,
                                       help_text='خالی = همهٔ پرداخت‌هایی که سالِ مالیِ باز دارند.')

    class Meta:
        model = AccountingSettings
        fields = ['currency_label', 'gateway_account', 'card_account', 'token_income_account',
                  'import_from_date']


# ─────────────────────────────── فیلترِ گزارش‌ها ───────────────────────────────
class PeriodForm(forms.Form):
    date_from = JalaliDateField(label='از', required=False)
    date_to = JalaliDateField(label='تا', required=False)


class AsOfForm(forms.Form):
    date_to = JalaliDateField(label='تا تاریخِ', required=False)


class LedgerForm(PeriodForm):
    account = forms.ModelChoiceField(queryset=Account.objects.all().order_by('code'), label='حساب',
                                     required=False)


class TrialForm(PeriodForm):
    level = forms.TypedChoiceField(label='سطح', coerce=int, required=False,
                                   choices=[(3, 'معین'), (2, 'کل'), (1, 'گروه')])


class ReverseForm(forms.Form):
    date = JalaliDateField(label='تاریخِ سندِ برگشتی')
    description = forms.CharField(label='شرح (اختیاری)', required=False, max_length=300)

    def clean_date(self):
        d = self.cleaned_data['date']
        services.open_year_for(d)
        return d
