# -*- coding: utf-8 -*-
"""گزارش‌ها — فقط از سندهای «ثبتِ قطعی». پیش‌نویس در هیچ عددی نمی‌آید."""
from collections import OrderedDict

from django.db.models import Sum
from django.utils import timezone

from . import jalali
from .models import Account, FiscalYear, JournalEntry, JournalLine, Partner

POSTED = JournalEntry.POSTED
CLOSING = JournalEntry.KIND_CLOSING


def _lines(date_from=None, date_to=None, before=None, exclude_closing=False, only_closing=False):
    qs = JournalLine.objects.filter(entry__status=POSTED)
    if date_from:
        qs = qs.filter(entry__date__gte=date_from)
    if date_to:
        qs = qs.filter(entry__date__lte=date_to)
    if before:
        qs = qs.filter(entry__date__lt=before)
    if exclude_closing:
        qs = qs.exclude(entry__kind=CLOSING)
    if only_closing:
        qs = qs.filter(entry__kind=CLOSING)
    return qs


def sums(**kw):
    """{account_id: (جمعِ بدهکار، جمعِ بستانکار)}"""
    rows = _lines(**kw).values('account_id').annotate(d=Sum('debit'), c=Sum('credit')).order_by()
    return {r['account_id']: (r['d'] or 0, r['c'] or 0) for r in rows}


def _accounts():
    return list(Account.objects.all().order_by('code'))


def income_expense(date_from=None, date_to=None):
    """(درآمد، هزینه، سود) بی‌سندِ بستنِ سال."""
    rows = (_lines(date_from=date_from, date_to=date_to, exclude_closing=True)
            .filter(account__account_type__in=[Account.INCOME, Account.EXPENSE])
            .values('account__account_type').annotate(d=Sum('debit'), c=Sum('credit')).order_by())
    inc = exp = 0
    for r in rows:
        d, c = r['d'] or 0, r['c'] or 0
        if r['account__account_type'] == Account.INCOME:
            inc += c - d
        else:
            exp += d - c
    return inc, exp, inc - exp


def unclosed_profit(as_of=None):
    """سودِ دوره‌هایی که هنوز بسته نشده‌اند (با سندِ بستن، سودِ سال‌های بسته صفر می‌شود)."""
    rows = (_lines(date_to=as_of)
            .filter(account__account_type__in=[Account.INCOME, Account.EXPENSE])
            .values('account__account_type').annotate(d=Sum('debit'), c=Sum('credit')).order_by())
    total = 0
    for r in rows:
        d, c = r['d'] or 0, r['c'] or 0
        total += (c - d) if r['account__account_type'] == Account.INCOME else -(d - c)
    return total


def _sections(accounts, values, types):
    """گروه‌بندیِ ردیف‌های معین زیرِ حسابِ کل."""
    by_id = {a.pk: a for a in accounts}
    out = OrderedDict()
    for a in accounts:
        if a.level != 3 or a.account_type not in types:
            continue
        v = values.get(a.pk, 0)
        if not v:
            continue
        parent = by_id.get(a.parent_id)
        key = parent.pk if parent else 0
        sec = out.setdefault(key, {'account': parent, 'rows': [], 'total': 0})
        sec['rows'].append({'account': a, 'amount': v})
        sec['total'] += v
    return list(out.values())


# ─────────────────────────────── سود و زیان ───────────────────────────────
def profit_loss(date_from, date_to):
    s = sums(date_from=date_from, date_to=date_to, exclude_closing=True)
    accounts = _accounts()
    inc_vals, exp_vals = {}, {}
    for a in accounts:
        d, c = s.get(a.pk, (0, 0))
        if a.account_type == Account.INCOME:
            inc_vals[a.pk] = c - d
        elif a.account_type == Account.EXPENSE:
            exp_vals[a.pk] = d - c
    income = _sections(accounts, inc_vals, [Account.INCOME])
    expense = _sections(accounts, exp_vals, [Account.EXPENSE])
    ti = sum(x['total'] for x in income)
    te = sum(x['total'] for x in expense)
    return {'income': income, 'expense': expense, 'total_income': ti, 'total_expense': te,
            'profit': ti - te, 'shares': partner_shares(ti - te)}


def partner_shares(profit):
    partners = list(Partner.objects.filter(is_active=True).order_by('name'))
    total = sum(p.share_percent for p in partners)
    if not partners or total != 100 or not profit:
        return []
    from .services import split_by_share
    split = split_by_share(abs(profit), [(p, p.share_percent) for p in partners])
    sign = 1 if profit > 0 else -1
    return [{'partner': p, 'percent': p.share_percent, 'amount': sign * amt} for p, amt in split]


# ─────────────────────────────── ترازنامه ───────────────────────────────
def balance_sheet(as_of):
    s = sums(date_to=as_of)
    accounts = _accounts()
    asset, liab, equity = {}, {}, {}
    for a in accounts:
        d, c = s.get(a.pk, (0, 0))
        if a.account_type == Account.ASSET:
            asset[a.pk] = d - c
        elif a.account_type == Account.LIABILITY:
            liab[a.pk] = c - d
        elif a.account_type == Account.EQUITY:
            equity[a.pk] = c - d          # برداشت‌ها منفی می‌آیند
    a_sec = _sections(accounts, asset, [Account.ASSET])
    l_sec = _sections(accounts, liab, [Account.LIABILITY])
    e_sec = _sections(accounts, equity, [Account.EQUITY])
    profit = unclosed_profit(as_of)
    ta = sum(x['total'] for x in a_sec)
    tl = sum(x['total'] for x in l_sec)
    te = sum(x['total'] for x in e_sec) + profit
    return {'assets': a_sec, 'liabilities': l_sec, 'equity': e_sec, 'unclosed_profit': profit,
            'total_assets': ta, 'total_liabilities': tl, 'total_equity': te,
            'total_le': tl + te, 'balanced': ta == tl + te}


# ─────────────────────────────── ترازِ آزمایشی ───────────────────────────────
def trial_balance(date_from, date_to, level=3):
    opening = sums(before=date_from) if date_from else {}
    period = sums(date_from=date_from, date_to=date_to)
    accounts = _accounts()
    by_id = {a.pk: a for a in accounts}

    def target(a):
        while a.level > level and a.parent_id in by_id:
            a = by_id[a.parent_id]
        return a

    agg = OrderedDict()
    for a in accounts:
        if a.level != 3:
            continue
        od, oc = opening.get(a.pk, (0, 0))
        pd, pc = period.get(a.pk, (0, 0))
        if not (od or oc or pd or pc):
            continue
        t = target(a)
        r = agg.setdefault(t.pk, {'account': t, 'open': 0, 'pd': 0, 'pc': 0})
        r['open'] += od - oc
        r['pd'] += pd
        r['pc'] += pc
    rows = sorted(agg.values(), key=lambda r: r['account'].code)
    tot = {'open_d': 0, 'open_c': 0, 'pd': 0, 'pc': 0, 'cd': 0, 'cc': 0}
    for r in rows:
        close = r['open'] + r['pd'] - r['pc']
        r['open_d'], r['open_c'] = max(r['open'], 0), max(-r['open'], 0)
        r['cd'], r['cc'] = max(close, 0), max(-close, 0)
        for k in tot:
            tot[k] += r[k]
    tot['balanced'] = tot['pd'] == tot['pc'] and tot['cd'] == tot['cc'] and tot['open_d'] == tot['open_c']
    return {'rows': rows, 'totals': tot}


# ─────────────────────────────── دفترِ حساب ───────────────────────────────
def ledger(account, date_from, date_to):
    ids = account.descendants_ids()
    side = account.resolved_side()

    def signed(d, c):
        return (d - c) if side == Account.DEBIT else (c - d)

    opening = 0
    if date_from:
        agg = _lines(before=date_from).filter(account_id__in=ids).aggregate(d=Sum('debit'), c=Sum('credit'))
        opening = signed(agg['d'] or 0, agg['c'] or 0)
    qs = (_lines(date_from=date_from, date_to=date_to).filter(account_id__in=ids)
          .select_related('entry', 'entry__fiscal_year', 'account', 'partner')
          .order_by('entry__date', 'entry__fiscal_year__start_date', 'entry__number', 'id'))
    bal = opening
    rows = []
    td = tc = 0
    for ln in qs:
        bal += signed(ln.debit, ln.credit)
        td += ln.debit
        tc += ln.credit
        rows.append({'line': ln, 'entry': ln.entry, 'jdate': jalali.fmt(ln.entry.date),
                     'debit': ln.debit, 'credit': ln.credit, 'balance': bal})
    return {'account': account, 'side': side, 'opening': opening, 'rows': rows,
            'total_debit': td, 'total_credit': tc, 'closing': bal}


# ─────────────────────────────── وضعیتِ شرکا ───────────────────────────────
def partners_status(as_of):
    s = sums(date_to=as_of)
    closing = sums(date_to=as_of, only_closing=True)
    profit = unclosed_profit(as_of)
    partners = list(Partner.objects.all().order_by('-is_active', 'name'))
    share_ok = sum(p.share_percent for p in partners if p.is_active) == 100
    est = {x['partner'].pk: x['amount'] for x in partner_shares(profit)} if share_ok else {}
    accs = {}
    for a in Account.objects.filter(partner__isnull=False):
        accs[(a.partner_id, a.role)] = a
    rows = []
    tot = {k: 0 for k in ('capital', 'pocket', 'drawing', 'profit', 'est', 'balance', 'invested')}
    for p in partners:
        def bal(role, src=s):
            a = accs.get((p.pk, role))
            if not a:
                return 0
            d, c = src.get(a.pk, (0, 0))
            return c - d
        capital = bal('partner_capital')
        drawing = -bal('partner_drawing')
        current = bal('partner_current')
        profit_done = bal('partner_current', closing)
        pocket = current - profit_done
        est_share = est.get(p.pk, 0)
        r = {'partner': p, 'capital': capital, 'pocket': pocket, 'drawing': drawing,
             'profit': profit_done, 'est': est_share,
             'invested': capital + pocket,
             'balance': capital - drawing + current + est_share,
             'accounts': [accs.get((p.pk, r)) for r in ('partner_capital', 'partner_drawing', 'partner_current')]}
        rows.append(r)
        for k in tot:
            tot[k] += r[k]
    return {'rows': rows, 'totals': tot, 'unclosed_profit': profit, 'share_ok': share_ok}


# ─────────────────────────────── صندوق و بانک ───────────────────────────────
def cash_status(date_from, date_to):
    accs = list(Account.objects.filter(is_cash=True, level=3).order_by('code'))
    opening = sums(before=date_from) if date_from else {}
    period = sums(date_from=date_from, date_to=date_to)
    rows = []
    tot = {'open': 0, 'in': 0, 'out': 0, 'close': 0}
    for a in accs:
        od, oc = opening.get(a.pk, (0, 0))
        pd, pc = period.get(a.pk, (0, 0))
        r = {'account': a, 'open': od - oc, 'in': pd, 'out': pc, 'close': od - oc + pd - pc}
        rows.append(r)
        for k in tot:
            tot[k] += r[k]
    return {'rows': rows, 'totals': tot}


# ─────────────────────────────── داشبورد ───────────────────────────────
def dashboard(today=None):
    today = today or timezone.localdate()
    m_from, m_to = jalali.month_bounds(today)
    fy = FiscalYear.for_date(today)
    jy = jalali.to_jalali(today)[0]
    y_from = fy.start_date if fy else jalali.year_bounds(jy)[0]
    mi, me, mp = income_expense(m_from, today)
    yi, ye, yp = income_expense(y_from, today)
    cash = cash_status(None, today)['totals']['close']
    ps = partners_status(today)
    return {
        'today': jalali.fmt(today),
        'month_title': jalali.month_title(*jalali.to_jalali(today)[:2]),
        'year_title': str(fy) if fy else 'سالِ %s' % jy,
        'month': {'income': mi, 'expense': me, 'profit': mp},
        'year': {'income': yi, 'expense': ye, 'profit': yp},
        'cash': cash,
        'partners': ps['rows'],
        'share_ok': ps['share_ok'],
        'has_partners': bool(ps['rows']),
        'drafts': JournalEntry.objects.filter(status=JournalEntry.DRAFT).count(),
        'fiscal_year': fy,
    }
