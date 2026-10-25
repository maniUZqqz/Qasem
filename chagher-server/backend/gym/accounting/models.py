# -*- coding: utf-8 -*-
"""حسابداریِ دوطرفهٔ چغر — کوچک، ولی با قاعده‌های واقعیِ حسابداری.

- کدینگ سه‌سطحی: گروه (۱ رقم) ⇐ کل (۲ رقم) ⇐ معین (۴ رقم). سند فقط روی معین.
- سند: پیش‌نویس ⇐ ثبتِ قطعی. سندِ قطعی تغییرناپذیر است (هم در مدل، هم با
  تریگرِ SQLite)؛ اصلاح فقط با «سندِ برگشتی».
- شمارهٔ سند هنگامِ ثبتِ قطعی، پشتِ هم و بی‌فاصله در هر سالِ مالی داده می‌شود.
- بستنِ سال: درآمد/هزینه ⇐ خلاصهٔ سود و زیان ⇐ حسابِ جاریِ شرکا به نسبتِ سهم.
- مبلغ‌ها عددِ صحیح‌اند (واحد: AccountingSettings.currency_label، پیش‌فرض تومان).
"""
import os

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.storage import FileSystemStorage
from django.core.validators import (FileExtensionValidator, MaxValueValidator,
                                    MinValueValidator)
from django.db import models
from django.db.models import Q, Sum
from django.urls import reverse

from . import jalali


# ─────────────────────────── فایلِ پیوستِ سند (خصوصی) ───────────────────────────
class AttachmentStorage(FileSystemStorage):
    """پیوستِ اسناد (فاکتور/رسید) بیرون از media ِ عمومی؛ فقط از راهِ ادمین."""

    @property
    def base_location(self):
        root = getattr(settings, 'PRIVATE_MEDIA_ROOT', None) or os.path.join(
            settings.BASE_DIR, 'private_media')
        return os.path.join(root, 'accounting')

    @property
    def location(self):
        return os.path.abspath(self.base_location)

    @property
    def base_url(self):
        return None

    @base_url.setter
    def base_url(self, value):
        pass

    def url(self, name):
        return reverse('admin:accounting_attachment', args=[name])


def attachment_storage():
    return AttachmentStorage()


ATTACHMENT_EXTENSIONS = ['pdf', 'jpg', 'jpeg', 'png', 'webp', 'gif', 'heic',
                         'xlsx', 'xls', 'csv', 'doc', 'docx', 'txt', 'zip']


def validate_attachment_size(f):
    if f and getattr(f, 'size', 0) > 10 * 1024 * 1024:
        raise ValidationError('حجمِ فایل باید کمتر از ۱۰ مگابایت باشد.')


# ──────────────────────────────── سرفصلِ حساب‌ها ────────────────────────────────
class Account(models.Model):
    ASSET, LIABILITY, EQUITY, INCOME, EXPENSE = 'asset', 'liability', 'equity', 'income', 'expense'
    TYPE_CHOICES = [
        (ASSET, 'دارایی'),
        (LIABILITY, 'بدهی'),
        (EQUITY, 'سرمایه (حقوقِ صاحبانِ سرمایه)'),
        (INCOME, 'درآمد'),
        (EXPENSE, 'هزینه'),
    ]
    DEBIT, CREDIT = 'debit', 'credit'
    SIDE_CHOICES = [(DEBIT, 'بدهکار'), (CREDIT, 'بستانکار')]
    LEVEL_GROUP, LEVEL_LEDGER, LEVEL_SUB = 1, 2, 3
    LEVEL_CHOICES = [(1, 'گروه'), (2, 'کل'), (3, 'معین')]
    DEFAULT_SIDE = {ASSET: DEBIT, EXPENSE: DEBIT, LIABILITY: CREDIT, EQUITY: CREDIT, INCOME: CREDIT}

    # نقش‌های سیستمی: برنامه این حساب‌ها را با نقش پیدا می‌کند، نه با نام
    ROLE_CHOICES = [
        ('', '—'),
        ('cash', 'صندوق'),
        ('bank', 'بانک'),
        ('gateway', 'درگاهِ پرداختِ اینترنتی'),
        ('receivable', 'حساب‌های دریافتنی'),
        ('payable', 'حساب‌های پرداختنی'),
        ('capital_parent', 'سرمایهٔ شرکا (کل)'),
        ('drawing_parent', 'برداشتِ شرکا (کل)'),
        ('current_parent', 'جاریِ شرکا (کل)'),
        ('partner_capital', 'سرمایهٔ یک شریک'),
        ('partner_drawing', 'برداشتِ یک شریک'),
        ('partner_current', 'جاریِ یک شریک'),
        ('retained', 'سود و زیانِ انباشته'),
        ('pl_summary', 'خلاصهٔ سود و زیان'),
        ('token_income', 'درآمدِ فروشِ توکن'),
    ]

    code = models.CharField('کد', max_length=10, unique=True,
                            help_text='گروه ۱ رقم، کل ۲ رقم، معین ۴ رقم — و با کدِ والد شروع شود.')
    name = models.CharField('نامِ حساب', max_length=120)
    parent = models.ForeignKey('self', on_delete=models.PROTECT, null=True, blank=True,
                               related_name='children', verbose_name='حسابِ بالادست',
                               limit_choices_to={'level__lt': 3})
    level = models.PositiveSmallIntegerField('سطح', choices=LEVEL_CHOICES, editable=False, default=1)
    account_type = models.CharField('ماهیت', max_length=10, choices=TYPE_CHOICES, blank=True,
                                    help_text='برای زیرحساب‌ها خودکار از والد می‌آید.')
    normal_side = models.CharField('ماندهٔ عادی', max_length=6, choices=SIDE_CHOICES, blank=True,
                                   help_text='خالی بماند تا از والد/ماهیت بیاید.')
    is_cash = models.BooleanField('نقد و بانک', default=False,
                                  help_text='در فرم‌ها به‌عنوانِ «از کجا پرداخت شد / کجا واریز شد» می‌آید.')
    role = models.CharField('نقشِ سیستمی', max_length=20, choices=ROLE_CHOICES, blank=True,
                            db_index=True, editable=False)
    partner = models.ForeignKey('Partner', on_delete=models.CASCADE, null=True, blank=True,
                                related_name='accounts', verbose_name='شریک', editable=False)
    card_payment_account = models.OneToOneField(
        'app.CardPaymentAccount', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='accounting_account', verbose_name='کارتِ کارت‌به‌کارتِ اپ',
        help_text='اگر پرداختِ کارت‌به‌کارتِ کاربران به این کارت می‌رسد، این‌جا وصلش کنید تا '
                  'واردکردنِ پرداخت‌ها پول را به همین حساب ببرد (مثلاً جاریِ شریکی که کارت مالِ اوست).')
    is_active = models.BooleanField('فعال', default=True)
    description = models.CharField('توضیح', max_length=300, blank=True)

    class Meta:
        ordering = ['code']
        verbose_name = 'حساب'
        verbose_name_plural = 'کدینگِ حساب‌ها'

    def __str__(self):
        return '%s — %s' % (self.code, self.name)

    @property
    def is_postable(self):
        return self.level == self.LEVEL_SUB and self.is_active

    def resolved_side(self):
        return self.normal_side or self.DEFAULT_SIDE.get(self.account_type, self.DEBIT)

    def signed(self, debit, credit):
        """مانده به جهتِ ماندهٔ عادیِ حساب (مثبت = طبیعی)."""
        return (debit - credit) if self.resolved_side() == self.DEBIT else (credit - debit)

    def has_lines(self):
        return self.pk is not None and JournalLine.objects.filter(account=self).exists()

    def clean(self):
        code = jalali.to_ascii_digits(self.code).strip()
        self.code = code
        if not code.isdigit():
            raise ValidationError({'code': 'کد فقط رقم باشد.'})
        if self.parent_id:
            parent = self.parent
            if parent.level >= 3:
                raise ValidationError({'parent': 'زیرِ حسابِ معین حسابِ دیگری ساخته نمی‌شود.'})
            if not code.startswith(parent.code) or len(code) <= len(parent.code):
                raise ValidationError({'code': 'کد باید با کدِ والد (%s) شروع شود و بلندتر از آن باشد.' % parent.code})
            if self.account_type and self.account_type != parent.account_type:
                raise ValidationError({'account_type': 'ماهیتِ زیرحساب باید با والد یکی باشد.'})
        elif not self.account_type:
            raise ValidationError({'account_type': 'برای حسابِ گروه، ماهیت را انتخاب کنید.'})
        if self.pk:
            old = Account.objects.filter(pk=self.pk).values(
                'parent_id', 'account_type', 'normal_side').first()
            if old and self.has_lines():
                if (old['parent_id'] != self.parent_id
                        or old['account_type'] != (self.account_type or old['account_type'])
                        or old['normal_side'] != (self.normal_side or old['normal_side'])):
                    raise ValidationError('این حساب سند خورده است؛ والد، ماهیت و ماندهٔ عادی‌اش عوض نمی‌شود.')
            if self.children.exists() and self.parent_id and self.parent.level >= 2:
                raise ValidationError('این حساب زیرحساب دارد و نمی‌تواند معین شود.')
        if self.card_payment_account_id:
            if not (self.is_cash or self.role == 'partner_current'):
                raise ValidationError({'card_payment_account':
                                       'کارت فقط به حسابِ نقد/بانک یا جاریِ یک شریک وصل می‌شود.'})

    def save(self, *args, **kwargs):
        self.code = jalali.to_ascii_digits(self.code).strip()
        if self.parent_id:
            parent = self.parent
            self.level = min(parent.level + 1, 3)
            self.account_type = parent.account_type
            if not self.normal_side:
                self.normal_side = parent.resolved_side()
        else:
            self.level = 1
            if not self.normal_side:
                self.normal_side = self.DEFAULT_SIDE.get(self.account_type, self.DEBIT)
        super().save(*args, **kwargs)

    @classmethod
    def by_role(cls, role):
        return cls.objects.filter(role=role).order_by('code').first()

    @classmethod
    def postable(cls):
        return cls.objects.filter(level=cls.LEVEL_SUB, is_active=True).order_by('code')

    @classmethod
    def cash_accounts(cls):
        return cls.postable().filter(is_cash=True)

    def descendants_ids(self):
        """خودِ حساب + همهٔ زیرحساب‌ها (برای دفترِ حسابِ کل/گروه)."""
        ids = [self.pk]
        frontier = [self.pk]
        while frontier:
            frontier = list(Account.objects.filter(parent_id__in=frontier).values_list('pk', flat=True))
            ids.extend(frontier)
        return ids


# ──────────────────────────────────── شرکا ────────────────────────────────────
class Partner(models.Model):
    name = models.CharField('نامِ شریک', max_length=100)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
                             blank=True, related_name='accounting_partners',
                             verbose_name='کاربرِ مرتبط (اختیاری)')
    share_percent = models.DecimalField(
        'درصدِ سهم از سود', max_digits=5, decimal_places=2, default=0,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text='جمعِ سهمِ شریکانِ فعال باید ۱۰۰ باشد (هنگامِ بستنِ سال سنجیده می‌شود).')
    is_active = models.BooleanField('فعال', default=True)
    note = models.CharField('یادداشت', max_length=300, blank=True)
    created_at = models.DateTimeField('ساخته‌شده', auto_now_add=True)

    ACCOUNT_SPECS = [
        # (نقشِ والد، نقشِ حسابِ شریک، پیشوندِ نام)
        ('capital_parent', 'partner_capital', 'سرمایهٔ'),
        ('drawing_parent', 'partner_drawing', 'برداشتِ'),
        ('current_parent', 'partner_current', 'جاریِ'),
    ]

    class Meta:
        ordering = ['-is_active', 'name']
        verbose_name = 'شریک'
        verbose_name_plural = 'شرکا'

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        self.ensure_accounts()

    def ensure_accounts(self):
        """هر شریک سه حسابِ معین دارد: سرمایه، برداشت، جاری."""
        for parent_role, role, prefix in self.ACCOUNT_SPECS:
            name = '%s %s' % (prefix, self.name)
            acc = Account.objects.filter(partner=self, role=role).first()
            if acc:
                if acc.name != name:
                    Account.objects.filter(pk=acc.pk).update(name=name)
                continue
            parent = Account.by_role(parent_role)
            if parent is None:
                raise ValidationError('حسابِ کلِ «%s» در کدینگ نیست.' % dict(Account.ROLE_CHOICES)[parent_role])
            used = [int(c[len(parent.code):]) for c in
                    Account.objects.filter(parent=parent).values_list('code', flat=True)
                    if c[len(parent.code):].isdigit()]
            nxt = (max(used) + 1) if used else 1
            if nxt > 99:
                raise ValidationError('جای خالی برای حسابِ تازه زیرِ %s نیست.' % parent.code)
            Account.objects.create(code='%s%02d' % (parent.code, nxt), name=name, parent=parent,
                                   role=role, partner=self, normal_side=parent.resolved_side())

    def account(self, role):
        return Account.objects.filter(partner=self, role=role).first()

    @property
    def capital_account(self):
        return self.account('partner_capital')

    @property
    def drawing_account(self):
        return self.account('partner_drawing')

    @property
    def current_account(self):
        return self.account('partner_current')

    @classmethod
    def share_total(cls):
        return cls.objects.filter(is_active=True).aggregate(s=Sum('share_percent'))['s'] or 0


# ──────────────────────────────────── سالِ مالی ────────────────────────────────────
class FiscalYear(models.Model):
    jalali_year = models.PositiveSmallIntegerField(
        'سالِ جلالی', unique=True, validators=[MinValueValidator(1390), MaxValueValidator(1499)],
        help_text='مثلاً ۱۴۰۵ — آغاز و پایان خودکار ۱ فروردین تا پایانِ اسفند می‌شود.')
    start_date = models.DateField('آغاز', editable=False)
    end_date = models.DateField('پایان', editable=False)
    is_closed = models.BooleanField('بسته شده', default=False, editable=False)
    closed_at = models.DateTimeField('زمانِ بستن', null=True, blank=True, editable=False)
    closed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True,
                                  blank=True, related_name='+', editable=False,
                                  verbose_name='بسته‌شده به دستِ')

    class Meta:
        ordering = ['-start_date']
        verbose_name = 'سالِ مالی'
        verbose_name_plural = 'سال‌های مالی'
        permissions = [('close_fiscalyear', 'بستنِ سالِ مالی')]

    def __str__(self):
        return 'سالِ مالیِ %s' % self.jalali_year

    def save(self, *args, **kwargs):
        if not self.start_date or not self.end_date:
            self.start_date, self.end_date = jalali.year_bounds(int(self.jalali_year))
        super().save(*args, **kwargs)

    def clean(self):
        if self.jalali_year:
            try:
                start, end = jalali.year_bounds(int(self.jalali_year))
            except (TypeError, ValueError):
                raise ValidationError({'jalali_year': 'سالِ جلالیِ نامعتبر است.'})
            if self.pk:
                old = FiscalYear.objects.filter(pk=self.pk).first()
                if old and old.jalali_year != self.jalali_year and old.entries.exists():
                    raise ValidationError('این سال سند دارد و سالش عوض نمی‌شود.')
            clash = FiscalYear.objects.filter(start_date__lte=end, end_date__gte=start)
            if self.pk:
                clash = clash.exclude(pk=self.pk)
            if clash.exists():
                raise ValidationError('این بازه با سالِ مالیِ دیگری هم‌پوشانی دارد.')

    @classmethod
    def for_date(cls, d):
        return cls.objects.filter(start_date__lte=d, end_date__gte=d).first()

    @property
    def start_jalali(self):
        return jalali.fmt(self.start_date)

    @property
    def end_jalali(self):
        return jalali.fmt(self.end_date)


# ──────────────────────────────────── سند ────────────────────────────────────
class JournalEntry(models.Model):
    DRAFT, POSTED = 'draft', 'posted'
    STATUS_CHOICES = [(DRAFT, 'پیش‌نویس'), (POSTED, 'ثبتِ قطعی')]

    KIND_MANUAL = 'manual'
    KIND_EXPENSE = 'expense'
    KIND_INCOME = 'income'
    KIND_CONTRIBUTION = 'contribution'
    KIND_DRAWING = 'drawing'
    KIND_TRANSFER = 'transfer'
    KIND_PAYMENT = 'payment'
    KIND_REVERSAL = 'reversal'
    KIND_CLOSING = 'closing'
    KIND_CHOICES = [
        (KIND_MANUAL, 'سندِ دستی'),
        (KIND_EXPENSE, 'هزینه'),
        (KIND_INCOME, 'درآمد'),
        (KIND_CONTRIBUTION, 'آوردهٔ شریک'),
        (KIND_DRAWING, 'برداشتِ شریک'),
        (KIND_TRANSFER, 'انتقالِ وجه'),
        (KIND_PAYMENT, 'پرداختِ کاربرانِ اپ'),
        (KIND_REVERSAL, 'سندِ برگشتی'),
        (KIND_CLOSING, 'بستنِ سال'),
    ]

    fiscal_year = models.ForeignKey(FiscalYear, on_delete=models.PROTECT, related_name='entries',
                                    verbose_name='سالِ مالی', editable=False)
    number = models.PositiveIntegerField('شمارهٔ سند', null=True, blank=True, editable=False)
    date = models.DateField('تاریخ')
    description = models.CharField('شرح', max_length=300)
    kind = models.CharField('نوع', max_length=15, choices=KIND_CHOICES, default=KIND_MANUAL,
                            editable=False, db_index=True)
    status = models.CharField('وضعیت', max_length=10, choices=STATUS_CHOICES, default=DRAFT,
                              editable=False, db_index=True)
    attachment = models.FileField(
        'پیوست (فاکتور/رسید)', storage=attachment_storage, upload_to='%Y/%m/', blank=True,
        validators=[FileExtensionValidator(ATTACHMENT_EXTENSIONS), validate_attachment_size])
    reversal_of = models.OneToOneField('self', on_delete=models.PROTECT, null=True, blank=True,
                                       related_name='reversed_by', editable=False,
                                       verbose_name='برگشتِ سندِ')
    source_ref = models.CharField('مرجعِ خودکار', max_length=64, null=True, blank=True,
                                  unique=True, editable=False,
                                  help_text='برای جلوگیری از ثبتِ دوباره؛ مثلاً tokenpurchase:12')
    total = models.PositiveBigIntegerField('مبلغِ سند', default=0, editable=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True,
                                   blank=True, related_name='+', editable=False,
                                   verbose_name='ساخته‌شده به دستِ')
    created_at = models.DateTimeField('زمانِ ساخت', auto_now_add=True)
    posted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True,
                                  blank=True, related_name='+', editable=False,
                                  verbose_name='ثبتِ قطعی به دستِ')
    posted_at = models.DateTimeField('زمانِ ثبتِ قطعی', null=True, blank=True, editable=False)

    class Meta:
        ordering = ['-date', '-number', '-id']
        verbose_name = 'سندِ حسابداری'
        verbose_name_plural = 'اسنادِ حسابداری'
        constraints = [
            models.UniqueConstraint(fields=['fiscal_year', 'number'], name='acc_entry_unique_number'),
            models.CheckConstraint(condition=Q(status='draft') | Q(number__isnull=False),
                                   name='acc_entry_posted_has_number'),
        ]
        permissions = [
            ('post_journalentry', 'ثبتِ قطعی و برگشتِ سند'),
            ('view_reports', 'دیدنِ گزارش‌های مالی'),
        ]

    def __str__(self):
        if self.status == self.POSTED:
            return 'سندِ %s (%s)' % (self.number, self.fiscal_year.jalali_year)
        return 'پیش‌نویسِ #%s' % (self.pk or 'تازه')

    @property
    def is_posted(self):
        return self.status == self.POSTED

    @property
    def jalali_date(self):
        return jalali.fmt(self.date)

    def _stored_status(self):
        if self.pk is None:
            return None
        return JournalEntry.objects.filter(pk=self.pk).values_list('status', flat=True).first()

    def save(self, *args, **kwargs):
        if self._stored_status() == self.POSTED:
            raise ValidationError('سندِ ثبتِ قطعی‌شده تغییر نمی‌کند؛ برای اصلاح «سندِ برگشتی» بزنید.')
        if self.status == self.POSTED and not getattr(self, '_posting', False):
            raise ValidationError('ثبتِ قطعی فقط از راهِ «ثبتِ قطعی» انجام می‌شود.')
        if self.date and (self.status == self.DRAFT or not self.fiscal_year_id):
            fy = FiscalYear.for_date(self.date)
            if fy is None:
                raise ValidationError('برای تاریخِ %s سالِ مالی تعریف نشده است.' % jalali.fmt(self.date))
            self.fiscal_year = fy
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self._stored_status() == self.POSTED:
            raise ValidationError('سندِ ثبتِ قطعی‌شده پاک نمی‌شود؛ برای اصلاح «سندِ برگشتی» بزنید.')
        return super().delete(*args, **kwargs)

    def totals(self):
        agg = self.lines.aggregate(d=Sum('debit'), c=Sum('credit'))
        return agg['d'] or 0, agg['c'] or 0

    def get_admin_url(self):
        return reverse('admin:accounting_journalentry_change', args=[self.pk])


class JournalLine(models.Model):
    entry = models.ForeignKey(JournalEntry, on_delete=models.CASCADE, related_name='lines',
                              verbose_name='سند')
    account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name='lines',
                                verbose_name='حساب', limit_choices_to={'level': 3, 'is_active': True})
    debit = models.PositiveBigIntegerField('بدهکار', default=0)
    credit = models.PositiveBigIntegerField('بستانکار', default=0)
    partner = models.ForeignKey(Partner, on_delete=models.PROTECT, null=True, blank=True,
                                related_name='lines', verbose_name='شریک')
    note = models.CharField('توضیحِ ردیف', max_length=200, blank=True)

    class Meta:
        ordering = ['id']
        verbose_name = 'ردیفِ سند'
        verbose_name_plural = 'ردیف‌های سند'
        constraints = [
            models.CheckConstraint(
                condition=(Q(debit__gt=0, credit=0) | Q(credit__gt=0, debit=0)),
                name='acc_line_one_side',
                violation_error_message='هر ردیف فقط یک طرف دارد — یا بدهکار یا بستانکار — '
                                        'و مبلغش بزرگ‌تر از صفر است.'),
        ]

    def __str__(self):
        return '%s: %s / %s' % (self.account, self.debit, self.credit)

    def _entry_posted(self):
        if not self.entry_id:
            return False
        return JournalEntry.objects.filter(pk=self.entry_id, status=JournalEntry.POSTED).exists()

    def save(self, *args, **kwargs):
        if self._entry_posted():
            raise ValidationError('ردیفِ سندِ ثبتِ قطعی‌شده تغییر نمی‌کند.')
        if self.account_id and self.account.partner_id and not self.partner_id:
            self.partner_id = self.account.partner_id
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self._entry_posted():
            raise ValidationError('ردیفِ سندِ ثبتِ قطعی‌شده پاک نمی‌شود.')
        return super().delete(*args, **kwargs)


# ──────────────────────────────── تنظیمات ────────────────────────────────
class AccountingSettings(models.Model):
    currency_label = models.CharField('واحدِ پول', max_length=20, default='تومان',
                                      help_text='همهٔ مبلغ‌ها عددِ صحیح به همین واحد ثبت می‌شوند.')
    gateway_account = models.ForeignKey(
        Account, on_delete=models.PROTECT, null=True, blank=True, related_name='+',
        verbose_name='پرداخت‌های درگاهِ اینترنتی به این حساب می‌رود',
        limit_choices_to={'level': 3, 'is_cash': True})
    card_account = models.ForeignKey(
        Account, on_delete=models.PROTECT, null=True, blank=True, related_name='+',
        verbose_name='حسابِ پیش‌فرضِ کارت‌به‌کارت',
        help_text='اگر کارتِ مقصد در کدینگ به حسابی وصل نشده باشد، پول به این حساب می‌رود.',
        limit_choices_to={'level': 3})
    token_income_account = models.ForeignKey(
        Account, on_delete=models.PROTECT, null=True, blank=True, related_name='+',
        verbose_name='حسابِ درآمدِ فروشِ توکن',
        limit_choices_to={'level': 3, 'account_type': 'income'})
    import_from_date = models.DateField(
        'واردکردنِ پرداخت‌ها از تاریخ', null=True, blank=True,
        help_text='پرداخت‌های پیش از این تاریخ وارد نمی‌شوند (خالی = از آغازِ نخستین سالِ مالی).')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'تنظیماتِ حسابداری'
        verbose_name_plural = 'تنظیماتِ حسابداری'

    def __str__(self):
        return 'تنظیماتِ حسابداری'

    @classmethod
    def get(cls):
        obj = cls.objects.order_by('pk').first()
        if obj is None:
            obj = cls.objects.create()
        return obj


def currency():
    try:
        return AccountingSettings.objects.values_list('currency_label', flat=True).first() or 'تومان'
    except Exception:
        return 'تومان'
