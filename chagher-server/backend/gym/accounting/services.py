# -*- coding: utf-8 -*-
"""همهٔ نوشتن‌های حسابداری از همین‌جا می‌گذرد (فرم‌ها، ادمین، دستورِ واردکردن، تست‌ها).

قاعده‌ها:
- سند دست‌کم دو ردیف؛ هر ردیف فقط یک طرف و > ۰؛ جمعِ بدهکار = جمعِ بستانکار.
- فقط حسابِ معینِ فعال؛ تاریخ باید در سالِ مالیِ باز باشد.
- شماره هنگامِ ثبتِ قطعی: بزرگ‌ترین شمارهٔ قطعیِ همان سال + ۱ (سندِ قطعی پاک نمی‌شود ⇒ بی‌فاصله).
- سندِ قطعی فقط با «سندِ برگشتی» اصلاح می‌شود (هر سند یک بار).
"""
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Max, Sum
from django.utils import timezone

from . import jalali
from .models import (Account, AccountingSettings, FiscalYear, JournalEntry,
                     JournalLine, Partner)


def pct(d):
    """۶۰.۰۰ ⇒ 60 ، ۳۳.۵۰ ⇒ 33.5"""
    s = '%.2f' % Decimal(str(d or 0))
    return s.rstrip('0').rstrip('.')


def money(n):
    n = int(n or 0)
    return '(%s)' % format(-n, ',') if n < 0 else format(n, ',')


class Line:
    """ردیفِ سندِ در حالِ ساخت."""

    def __init__(self, account, debit=0, credit=0, partner=None, note=''):
        self.account = account
        self.debit = int(debit or 0)
        self.credit = int(credit or 0)
        self.partner = partner
        self.note = note or ''

    @property
    def partner_id(self):
        return self.partner.pk if self.partner is not None else None


def Dr(account, amount, partner=None, note=''):
    return Line(account, debit=amount, partner=partner, note=note)


def Cr(account, amount, partner=None, note=''):
    return Line(account, credit=amount, partner=partner, note=note)


def _user(user):
    return user if (user is not None and getattr(user, 'pk', None)) else None


# ─────────────────────────────── سنجشِ سند ───────────────────────────────
def check_lines(lines):
    """قاعده‌های سند؛ خطا ⇒ ValidationError با همهٔ پیام‌ها. خروجی: جمعِ سند."""
    lines = list(lines)
    errors = []
    if len(lines) < 2:
        errors.append('سند دست‌کم دو ردیف لازم دارد (یکی بدهکار، یکی بستانکار).')
    td = tc = 0
    for i, ln in enumerate(lines, 1):
        d, c = int(ln.debit or 0), int(ln.credit or 0)
        if d < 0 or c < 0:
            errors.append('ردیفِ %d: مبلغِ منفی مجاز نیست.' % i)
            continue
        if (d > 0) == (c > 0):
            errors.append('ردیفِ %d: هر ردیف فقط یک طرف دارد — یا بدهکار یا بستانکار — و مبلغش بزرگ‌تر از صفر است.' % i)
        acc = ln.account
        if acc is None:
            errors.append('ردیفِ %d: حساب انتخاب نشده است.' % i)
        elif not acc.is_postable:
            errors.append('ردیفِ %d: «%s» حسابِ معینِ فعال نیست؛ سند فقط روی حسابِ معین (۴ رقمی) می‌نشیند.' % (i, acc))
        elif acc.partner_id and ln.partner_id and ln.partner_id != acc.partner_id:
            errors.append('ردیفِ %d: شریکِ ردیف با صاحبِ حسابِ «%s» یکی نیست.' % (i, acc))
        td += d
        tc += c
    if td != tc:
        errors.append('جمعِ بدهکار (%s) با جمعِ بستانکار (%s) برابر نیست؛ اختلاف %s.'
                      % (money(td), money(tc), money(abs(td - tc))))
    elif lines and td == 0:
        errors.append('مبلغِ سند صفر است.')
    if errors:
        raise ValidationError(errors)
    return td


def open_year_for(d):
    if d is None:
        raise ValidationError('تاریخ لازم است.')
    fy = FiscalYear.for_date(d)
    if fy is None:
        raise ValidationError('برای تاریخِ %s سالِ مالی تعریف نشده است؛ اول در «سال‌های مالی» بسازیدش.'
                              % jalali.fmt(d))
    if fy.is_closed:
        raise ValidationError('%s بسته شده است؛ در آن سند ثبت نمی‌شود.' % fy)
    return fy


# ─────────────────────────────── ساخت و ثبتِ قطعی ───────────────────────────────
@transaction.atomic
def post_entry(entry, user):
    entry = JournalEntry.objects.select_for_update().get(pk=entry.pk)
    if entry.status == JournalEntry.POSTED:
        raise ValidationError('این سند قبلاً ثبتِ قطعی شده است.')
    fy = open_year_for(entry.date)
    lines = list(entry.lines.select_related('account'))
    total = check_lines(lines)
    last = (JournalEntry.objects.filter(fiscal_year=fy, status=JournalEntry.POSTED)
            .aggregate(m=Max('number'))['m'] or 0)
    entry.fiscal_year = fy
    entry.number = last + 1
    entry.status = JournalEntry.POSTED
    entry.total = total
    entry.posted_by = _user(user)
    entry.posted_at = timezone.now()
    entry._posting = True
    entry.save(update_fields=['fiscal_year', 'number', 'status', 'total', 'posted_by', 'posted_at'])
    return entry


@transaction.atomic
def create_entry(*, date, description, lines, user=None, kind=JournalEntry.KIND_MANUAL,
                 post=True, attachment=None, source_ref=None, reversal_of=None):
    open_year_for(date)
    lines = list(lines)
    total = check_lines(lines)
    entry = JournalEntry(date=date, description=(description or '')[:300] or '—', kind=kind,
                         created_by=_user(user), source_ref=source_ref, reversal_of=reversal_of,
                         total=total)
    if attachment:
        entry.attachment = attachment
    entry.save()
    JournalLine.objects.bulk_create([
        JournalLine(entry=entry, account=ln.account, debit=ln.debit, credit=ln.credit,
                    partner_id=ln.partner_id or ln.account.partner_id, note=ln.note[:200])
        for ln in lines
    ])
    if post:
        entry = post_entry(entry, user)
    return entry


@transaction.atomic
def reverse_entry(entry, user, date=None, description=''):
    entry = JournalEntry.objects.select_for_update().get(pk=entry.pk)
    if entry.status != JournalEntry.POSTED:
        raise ValidationError('فقط سندِ ثبتِ قطعی برگشت می‌خورد؛ پیش‌نویس را ویرایش یا پاک کنید.')
    if entry.kind == JournalEntry.KIND_REVERSAL:
        raise ValidationError('سندِ برگشتی خودش برگشت نمی‌خورد؛ اگر لازم است سندِ تازه بزنید.')
    if entry.kind == JournalEntry.KIND_CLOSING:
        raise ValidationError('سندِ بستنِ سال برگشت نمی‌خورد.')
    done = JournalEntry.objects.filter(reversal_of=entry).first()
    if done:
        raise ValidationError('این سند قبلاً با «%s» برگشت خورده است.' % done)
    date = date or timezone.localdate()
    if date < entry.date:
        raise ValidationError('تاریخِ سندِ برگشتی نمی‌تواند پیش از تاریخِ خودِ سند (%s) باشد.' % entry.jalali_date)
    lines = [Line(l.account, debit=l.credit, credit=l.debit, partner=l.partner, note=l.note)
             for l in entry.lines.select_related('account', 'partner')]
    desc = description or ('برگشتِ سندِ %s (%s): %s' % (entry.number, entry.fiscal_year.jalali_year,
                                                         entry.description))
    return create_entry(date=date, description=desc, lines=lines, user=user,
                        kind=JournalEntry.KIND_REVERSAL, reversal_of=entry, post=True)


@transaction.atomic
def copy_as_draft(entry, user, date=None):
    """کپیِ یک سند به پیش‌نویسِ تازه (برای اصلاح پس از برگشت)."""
    lines = [Line(l.account, debit=l.debit, credit=l.credit, partner=l.partner, note=l.note)
             for l in entry.lines.select_related('account', 'partner')]
    return create_entry(date=date or timezone.localdate(),
                        description=('کپیِ %s: %s' % (entry, entry.description))[:300],
                        lines=lines, user=user, kind=JournalEntry.KIND_MANUAL, post=False)


# ─────────────────────────────── فرم‌های ساده ───────────────────────────────
def _need(cond, msg):
    if not cond:
        raise ValidationError(msg)


def _cash(acc):
    _need(acc is not None and acc.is_cash and acc.is_postable, 'حسابِ نقد/بانکِ معتبر انتخاب کنید.')
    return acc


def _partner_acc(partner, role):
    _need(partner is not None, 'شریک را انتخاب کنید.')
    acc = partner.account(role)
    _need(acc is not None, 'حساب‌های شریکِ «%s» ساخته نشده است.' % partner)
    return acc


def record_expense(*, date, amount, expense_account, paid_from=None, partner=None,
                   description='', user=None, attachment=None, post=True):
    _need(expense_account is not None and expense_account.account_type == Account.EXPENSE,
          'نوعِ هزینه باید یک حسابِ هزینه باشد.')
    if partner is not None:
        src = _partner_acc(partner, 'partner_current')
        note = 'پرداخت از جیبِ %s' % partner
    else:
        src, note = _cash(paid_from), ''
    return create_entry(
        date=date, description=description or 'هزینه: %s' % expense_account.name,
        lines=[Dr(expense_account, amount), Cr(src, amount, partner=partner, note=note)],
        user=user, kind=JournalEntry.KIND_EXPENSE, post=post, attachment=attachment)


def record_income(*, date, amount, income_account, received_in=None, partner=None,
                  description='', user=None, attachment=None, post=True):
    _need(income_account is not None and income_account.account_type == Account.INCOME,
          'نوعِ درآمد باید یک حسابِ درآمد باشد.')
    if partner is not None:
        dst = _partner_acc(partner, 'partner_current')
        note = 'به کارت/حسابِ شخصیِ %s واریز شد' % partner
    else:
        dst, note = _cash(received_in), ''
    return create_entry(
        date=date, description=description or 'درآمد: %s' % income_account.name,
        lines=[Dr(dst, amount, partner=partner, note=note), Cr(income_account, amount)],
        user=user, kind=JournalEntry.KIND_INCOME, post=post, attachment=attachment)


def record_contribution(*, date, amount, partner, into, description='', user=None,
                        attachment=None, post=True):
    cap = _partner_acc(partner, 'partner_capital')
    return create_entry(
        date=date, description=description or 'آوردهٔ سرمایهٔ %s' % partner,
        lines=[Dr(_cash(into), amount), Cr(cap, amount, partner=partner)],
        user=user, kind=JournalEntry.KIND_CONTRIBUTION, post=post, attachment=attachment)


def record_drawing(*, date, amount, partner, from_account, description='', user=None,
                   attachment=None, post=True):
    drw = _partner_acc(partner, 'partner_drawing')
    return create_entry(
        date=date, description=description or 'برداشتِ %s' % partner,
        lines=[Dr(drw, amount, partner=partner), Cr(_cash(from_account), amount)],
        user=user, kind=JournalEntry.KIND_DRAWING, post=post, attachment=attachment)


def record_transfer(*, date, amount, from_account, to_account, description='', user=None,
                    attachment=None, post=True):
    _cash(from_account)
    _cash(to_account)
    _need(from_account.pk != to_account.pk, 'مبدأ و مقصد یکی است.')
    return create_entry(
        date=date, description=description or 'انتقال از %s به %s' % (from_account.name, to_account.name),
        lines=[Dr(to_account, amount), Cr(from_account, amount)],
        user=user, kind=JournalEntry.KIND_TRANSFER, post=post, attachment=attachment)


# ─────────────────────────────── بستنِ سال ───────────────────────────────
def split_by_share(amount, shares):
    """amount (صحیح، مثبت) را به نسبتِ درصدها بخش می‌کند؛ جمعِ خروجی دقیقاً amount است
    (روشِ بزرگ‌ترین باقی‌مانده). shares: [(key, percent)]"""
    total = sum(Decimal(str(p)) for _, p in shares)
    if total <= 0:
        raise ValidationError('جمعِ سهم‌ها صفر است.')
    parts = []
    for i, (key, pct) in enumerate(shares):
        raw = Decimal(amount) * Decimal(str(pct)) / total
        base = int(raw.to_integral_value(rounding=ROUND_FLOOR))
        parts.append([key, base, raw - base, Decimal(str(pct)), i])
    rest = amount - sum(p[1] for p in parts)
    for p in sorted(parts, key=lambda p: (-p[2], -p[3], p[4]))[:rest]:
        p[1] += 1
    return [(p[0], p[1]) for p in parts]


def _year_income_expense(fy):
    rows = (JournalLine.objects
            .filter(entry__status=JournalEntry.POSTED, entry__fiscal_year=fy,
                    account__account_type__in=[Account.INCOME, Account.EXPENSE])
            .exclude(entry__kind=JournalEntry.KIND_CLOSING)
            .values('account').annotate(d=Sum('debit'), c=Sum('credit')).order_by())
    accs = Account.objects.in_bulk([r['account'] for r in rows])
    incomes, expenses = [], []
    for r in rows:
        acc = accs[r['account']]
        d, c = r['d'] or 0, r['c'] or 0
        if acc.account_type == Account.INCOME:
            incomes.append((acc, c - d))
        else:
            expenses.append((acc, d - c))
    incomes.sort(key=lambda x: x[0].code)
    expenses.sort(key=lambda x: x[0].code)
    return incomes, expenses


def closing_preview(fy, today=None):
    today = today or timezone.localdate()
    problems = []
    if fy.is_closed:
        problems.append('این سال قبلاً بسته شده است.')
    if fy.end_date >= today:
        problems.append('سال هنوز تمام نشده (پایان: %s)؛ سال را بعد از پایانش می‌بندیم.' % fy.end_jalali)
    if FiscalYear.objects.filter(start_date__lt=fy.start_date, is_closed=False).exists():
        problems.append('سال‌های مالیِ پیشین هنوز باز است؛ اول آن‌ها را به ترتیب ببندید.')
    drafts = JournalEntry.objects.filter(status=JournalEntry.DRAFT,
                                         date__gte=fy.start_date, date__lte=fy.end_date).count()
    if drafts:
        problems.append('%d پیش‌نویس در این سال مانده؛ اول ثبتِ قطعی یا پاکشان کنید.' % drafts)
    for role in ('pl_summary', 'retained'):
        if Account.by_role(role) is None:
            problems.append('حسابِ «%s» در کدینگ نیست.' % dict(Account.ROLE_CHOICES)[role])

    incomes, expenses = _year_income_expense(fy)
    total_income = sum(a for _, a in incomes)
    total_expense = sum(a for _, a in expenses)
    profit = total_income - total_expense

    partners = list(Partner.objects.filter(is_active=True).order_by('name'))
    distribution = []
    if partners:
        share_total = sum(p.share_percent for p in partners)
        if share_total != 100:
            problems.append('جمعِ سهمِ شرکای فعال %s٪ است؛ باید دقیقاً ۱۰۰٪ باشد.' % pct(share_total))
        elif profit:
            split = split_by_share(abs(profit), [(p, p.share_percent) for p in partners])
            distribution = [(p, p.share_percent, amt) for p, amt in split]
        else:
            distribution = [(p, p.share_percent, 0) for p in partners]
    return {
        'fiscal_year': fy, 'incomes': incomes, 'expenses': expenses,
        'total_income': total_income, 'total_expense': total_expense, 'profit': profit,
        'distribution': distribution, 'to_retained': not partners, 'problems': problems,
    }


@transaction.atomic
def close_year(fy, user, today=None):
    fy = FiscalYear.objects.select_for_update().get(pk=fy.pk)
    p = closing_preview(fy, today=today)
    if p['problems']:
        raise ValidationError(p['problems'])
    summary = Account.by_role('pl_summary')
    profit = p['profit']
    made = []

    lines = []
    for acc, amt in p['incomes']:
        if amt > 0:
            lines.append(Dr(acc, amt))
        elif amt < 0:
            lines.append(Cr(acc, -amt))
    for acc, amt in p['expenses']:
        if amt > 0:
            lines.append(Cr(acc, amt))
        elif amt < 0:
            lines.append(Dr(acc, -amt))
    if profit > 0:
        lines.append(Cr(summary, profit))
    elif profit < 0:
        lines.append(Dr(summary, -profit))
    if lines:
        made.append(create_entry(
            date=fy.end_date, lines=lines, user=user, kind=JournalEntry.KIND_CLOSING,
            description='بستنِ حساب‌های درآمد و هزینهٔ %s به خلاصهٔ سود و زیان' % fy,
            source_ref='close:%s:pl' % fy.jalali_year))

    if profit:
        amt = abs(profit)
        dist = [Dr(summary, amt) if profit > 0 else Cr(summary, amt)]
        if p['to_retained']:
            ret = Account.by_role('retained')
            dist.append(Cr(ret, amt) if profit > 0 else Dr(ret, amt))
            who = 'سود و زیانِ انباشته'
        else:
            for partner, pct_, share in p['distribution']:
                if share:
                    acc = partner.current_account
                    note = '%s٪ سهم' % pct(pct_)
                    dist.append(Cr(acc, share, partner, note) if profit > 0 else Dr(acc, share, partner, note))
            who = 'حسابِ جاریِ شرکا به نسبتِ سهم'
        made.append(create_entry(
            date=fy.end_date, lines=dist, user=user, kind=JournalEntry.KIND_CLOSING,
            description='%s %s (%s) ⇐ %s' % ('سودِ' if profit > 0 else 'زیانِ', fy, money(amt), who),
            source_ref='close:%s:split' % fy.jalali_year))

    fy.is_closed = True
    fy.closed_at = timezone.now()
    fy.closed_by = _user(user)
    fy.save(update_fields=['is_closed', 'closed_at', 'closed_by'])
    return made


# ─────────────────────────────── پرداخت‌های کاربرانِ اپ ───────────────────────────────
PAYMENT_REF = 'tokenpurchase:%s'


def _paid_at(purchase):
    from app.models import LedgerEntry
    t = (LedgerEntry.objects.filter(entry_type='purchase', reference='purchase#%s' % purchase.pk)
         .order_by('created_at').values_list('created_at', flat=True).first())
    return t or purchase.reviewed_at or purchase.updated_at or purchase.created_at


def _receiving_account(purchase, conf):
    if purchase.payment_method == 'card':
        if purchase.card_account_id:
            acc = Account.objects.filter(card_payment_account_id=purchase.card_account_id,
                                         level=3, is_active=True).first()
            if acc:
                return acc
        return conf.card_account
    return conf.gateway_account


def payment_candidates():
    """خریدهای پرداخت‌شده‌ای که هنوز سند ندارند + سندهایی که خریدشان دیگر «پرداخت‌شده» نیست."""
    from app.models import TokenPurchase
    conf = AccountingSettings.get()
    done = dict(JournalEntry.objects.filter(source_ref__startswith='tokenpurchase:')
                .values_list('source_ref', 'pk'))
    rows = []
    paid_ids = set()
    for p in (TokenPurchase.objects.filter(status='paid')
              .select_related('card_account').order_by('pk')):
        ref = PAYMENT_REF % p.pk
        paid_ids.add(p.pk)
        if ref in done:
            continue
        d = timezone.localtime(_paid_at(p)).date()
        amount = int(Decimal(p.final_price or 0).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
        acc = _receiving_account(p, conf)
        problem = ''
        fy = FiscalYear.for_date(d)
        if amount <= 0:
            problem = 'مبلغِ پرداخت‌شده صفر است (تخفیفِ کامل) — سند لازم ندارد.'
        elif conf.import_from_date and d < conf.import_from_date:
            problem = 'پیش از «واردکردن از تاریخِ» تنظیمات.'
        elif fy is None:
            problem = 'برای این تاریخ سالِ مالی تعریف نشده.'
        elif fy.is_closed:
            problem = 'سالِ مالیِ این تاریخ بسته است.'
        elif acc is None or not acc.is_postable:
            problem = 'حسابِ دریافت در «تنظیماتِ حسابداری» مشخص نیست.'
        elif conf.token_income_account is None or not conf.token_income_account.is_postable:
            problem = 'حسابِ درآمدِ فروشِ توکن در «تنظیماتِ حسابداری» مشخص نیست.'
        rows.append({'purchase': p, 'ref': ref, 'date': d, 'jdate': jalali.fmt(d), 'amount': amount,
                     'account': acc, 'problem': problem})
    stale = []
    for ref, pk in done.items():
        pid = int(ref.split(':', 1)[1])
        if pid not in paid_ids:
            stale.append({'purchase_id': pid, 'entry_id': pk})
    return rows, stale


def import_payments(user=None, dry_run=False):
    """هر خریدِ پرداخت‌شده ⇐ یک سندِ درآمد. هرگز دو بار (source_ref یکتا)."""
    conf = AccountingSettings.get()
    rows, stale = payment_candidates()
    created = []
    for r in rows:
        if r['problem'] or dry_run:
            continue
        p = r['purchase']
        method = 'کارت‌به‌کارت' if p.payment_method == 'card' else 'درگاه'
        try:
            with transaction.atomic():
                e = create_entry(
                    date=r['date'], user=user, kind=JournalEntry.KIND_PAYMENT, source_ref=r['ref'],
                    description='فروشِ %s توکن — خریدِ #%s (%s)' % (p.token_amount, p.pk, method),
                    lines=[Dr(r['account'], r['amount'], partner=r['account'].partner),
                           Cr(conf.token_income_account, r['amount'])])
        except IntegrityError:
            continue  # هم‌زمان ثبت شد
        created.append(e)
    return created, rows, stale
