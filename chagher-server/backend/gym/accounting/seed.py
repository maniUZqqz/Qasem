# -*- coding: utf-8 -*-
"""کدینگِ پیش‌فرضِ چغر (کسب‌وکارِ آنلاین: فروشِ توکن/اشتراک، هزینهٔ سرور و API و پیامک).

هم مایگریشن (با مدل‌های تاریخی) و هم تست‌ها صدایش می‌زنند؛ تکرارش بی‌خطر است:
حسابی که کدش هست دست نمی‌خورد (شاید مالک نامش را عوض کرده باشد).
"""
from . import jalali

# (کد، نام، ماهیت [فقط گروه]، نقش، نقد/بانک، ماندهٔ عادی [اگر خلافِ ماهیت])
CHART = [
    ('1', 'دارایی‌ها', 'asset', '', False, ''),
    ('11', 'موجودیِ نقد و بانک', None, '', False, ''),
    ('1101', 'صندوق', None, 'cash', True, ''),
    ('1102', 'بانک', None, 'bank', True, ''),
    ('12', 'حساب‌ها و اسنادِ دریافتنی', None, '', False, ''),
    ('1201', 'حساب‌های دریافتنی', None, 'receivable', False, ''),

    ('2', 'بدهی‌ها', 'liability', '', False, ''),
    ('21', 'حساب‌ها و اسنادِ پرداختنی', None, '', False, ''),
    ('2101', 'حساب‌های پرداختنی', None, 'payable', False, ''),

    ('3', 'حقوقِ صاحبانِ سرمایه', 'equity', '', False, ''),
    ('31', 'سرمایهٔ شرکا', None, 'capital_parent', False, ''),
    ('32', 'برداشتِ شرکا', None, 'drawing_parent', False, 'debit'),
    ('33', 'جاریِ شرکا', None, 'current_parent', False, ''),
    ('34', 'سود و زیان', None, '', False, ''),
    ('3401', 'سود و زیانِ انباشته', None, 'retained', False, ''),
    ('3402', 'خلاصهٔ سود و زیان (بستنِ سال)', None, 'pl_summary', False, ''),

    ('4', 'درآمدها', 'income', '', False, ''),
    ('41', 'درآمدهای عملیاتی', None, '', False, ''),
    ('4101', 'فروشِ توکن در اپ', None, 'token_income', False, ''),
    ('4102', 'اشتراکِ برنامهٔ دستی', None, '', False, ''),
    ('4103', 'سایرِ خدمات (قرارداد با باشگاه‌ها و …)', None, '', False, ''),
    ('42', 'سایرِ درآمدها', None, '', False, ''),
    ('4201', 'سایرِ درآمدها (سودِ بانکی و …)', None, '', False, ''),

    ('5', 'هزینه‌ها', 'expense', '', False, ''),
    ('51', 'هزینه‌های عملیاتی', None, '', False, ''),
    ('5101', 'سرور و هاست', None, '', False, ''),
    ('5102', 'دامنه و گواهی', None, '', False, ''),
    ('5103', 'API هوش مصنوعی', None, '', False, ''),
    ('5104', 'پیامک', None, '', False, ''),
    ('5105', 'کارمزدِ درگاه و بانک', None, '', False, ''),
    ('5106', 'کمیسیونِ کدِ تخفیف (معرف‌ها)', None, '', False, ''),
    ('5107', 'تبلیغات و بازاریابی', None, '', False, ''),
    ('5108', 'حقوق و دستمزد', None, '', False, ''),
    ('5199', 'سایرِ هزینه‌ها', None, '', False, ''),
]

_DEFAULT_SIDE = {'asset': 'debit', 'expense': 'debit',
                 'liability': 'credit', 'equity': 'credit', 'income': 'credit'}


def seed_chart(Account):
    by_code = {a.code: a for a in Account.objects.all()}
    for code, name, typ, role, is_cash, side in CHART:
        if code in by_code:
            continue
        parent = None
        for plen in (2, 1):
            if len(code) > plen and code[:plen] in by_code:
                parent = by_code[code[:plen]]
                break
        level = 1 if parent is None else min(parent.level + 1, 3)
        account_type = typ if parent is None else parent.account_type
        normal_side = side or (parent.normal_side if parent is not None else _DEFAULT_SIDE[account_type])
        by_code[code] = Account.objects.create(
            code=code, name=name, parent=parent, level=level, account_type=account_type,
            normal_side=normal_side, role=role, is_cash=is_cash)
    return by_code


def seed_fiscal_year(FiscalYear, today):
    jy = jalali.to_jalali(today)[0]
    if not FiscalYear.objects.filter(jalali_year=jy).exists():
        start, end = jalali.year_bounds(jy)
        FiscalYear.objects.create(jalali_year=jy, start_date=start, end_date=end)


def seed_settings(AccountingSettings, by_code):
    if AccountingSettings.objects.exists():
        return
    AccountingSettings.objects.create(
        currency_label='تومان',
        gateway_account=by_code.get('1102'),
        card_account=by_code.get('1102'),
        token_income_account=by_code.get('4101'),
    )


def seed_all(Account, FiscalYear, AccountingSettings, today):
    by_code = seed_chart(Account)
    seed_fiscal_year(FiscalYear, today)
    seed_settings(AccountingSettings, by_code)
