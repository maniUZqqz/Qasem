# -*- coding: utf-8 -*-
import datetime as dt
import shutil
import tempfile
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.db import DatabaseError, transaction
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounting import jalali, reports, services
from accounting.models import (Account, AccountingSettings, FiscalYear, JournalEntry,
                               JournalLine, Partner)
from accounting.seed import seed_all
from accounting.services import Cr, Dr

User = get_user_model()
J = jalali.parse


class JalaliTests(SimpleTestCase):
    def test_known_dates(self):
        self.assertEqual(jalali.to_jalali(dt.date(2026, 3, 21)), (1405, 1, 1))
        self.assertEqual(jalali.to_jalali(dt.date(2025, 3, 20)), (1403, 12, 30))
        self.assertEqual(jalali.to_jalali(dt.date(2026, 10, 25)), (1405, 8, 3))
        self.assertEqual(jalali.to_gregorian(1357, 11, 22), dt.date(1979, 2, 11))
        self.assertTrue(jalali.is_leap(1403))
        self.assertFalse(jalali.is_leap(1404))

    def test_round_trip(self):
        d = dt.date(2000, 1, 1)
        while d < dt.date(2040, 1, 1):
            self.assertEqual(jalali.to_gregorian(*jalali.to_jalali(d)), d)
            d += dt.timedelta(days=1)

    def test_parse(self):
        self.assertEqual(J('۱۴۰۵/۸/۳'), dt.date(2026, 10, 25))
        self.assertEqual(J('1405-08-03'), dt.date(2026, 10, 25))
        for bad in ('1405/13/01', '1404/12/30', '05/08/03', 'abc', ''):
            with self.assertRaises(ValueError):
                J(bad)


class Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_all(Account, FiscalYear, AccountingSettings, timezone.localdate())
        for y in (1404, 1405):
            if not FiscalYear.objects.filter(jalali_year=y).exists():
                FiscalYear.objects.create(jalali_year=y)
        cls.fy1404 = FiscalYear.objects.get(jalali_year=1404)
        cls.fy1405 = FiscalYear.objects.get(jalali_year=1405)
        cls.user = User.objects.create_superuser(phone_number='09990000001', password='x')
        acc = {a.code: a for a in Account.objects.all()}
        cls.acc = acc
        cls.cash, cls.bank = acc['1101'], acc['1102']
        cls.server, cls.ai, cls.sms = acc['5101'], acc['5103'], acc['5104']
        cls.tokens, cls.services_inc = acc['4101'], acc['4103']

    def entry(self, date, lines, post=True, **kw):
        return services.create_entry(date=J(date) if isinstance(date, str) else date,
                                     description=kw.pop('description', 'آزمون'), lines=lines,
                                     user=self.user, post=post, **kw)

    def partners(self, a=60, b=40):
        pa = Partner.objects.create(name='علی', share_percent=a)
        pb = Partner.objects.create(name='رضا', share_percent=b)
        return pa, pb


class ChartTests(Base):
    def test_seed_is_idempotent_and_sane(self):
        n = Account.objects.count()
        seed_all(Account, FiscalYear, AccountingSettings, timezone.localdate())
        self.assertEqual(Account.objects.count(), n)
        self.assertEqual(self.bank.level, 3)
        self.assertEqual(self.bank.account_type, Account.ASSET)
        self.assertEqual(Account.objects.get(code='32').normal_side, Account.DEBIT)
        self.assertEqual(self.tokens.normal_side, Account.CREDIT)
        s = AccountingSettings.get()
        self.assertEqual(s.currency_label, 'تومان')
        self.assertEqual(s.token_income_account, self.tokens)

    def test_partner_gets_three_accounts(self):
        pa, _ = self.partners()
        self.assertEqual(pa.capital_account.code, '3101')
        self.assertEqual(pa.drawing_account.code, '3201')
        self.assertEqual(pa.current_account.code, '3301')
        self.assertEqual(pa.drawing_account.normal_side, Account.DEBIT)
        pa.name = 'علی‌رضا'
        pa.save()
        self.assertEqual(pa.capital_account.name, 'سرمایهٔ علی‌رضا')
        self.assertEqual(Account.objects.filter(partner=pa).count(), 3)


class EntryRuleTests(Base):
    def test_balanced_entries_get_sequential_numbers_per_year(self):
        e1 = self.entry('1404/02/01', [Dr(self.server, 100), Cr(self.bank, 100)])
        e2 = self.entry('1404/02/02', [Dr(self.server, 50), Cr(self.cash, 50)])
        e3 = self.entry('1405/02/02', [Dr(self.server, 70), Cr(self.cash, 70)])
        self.assertEqual((e1.number, e2.number, e3.number), (1, 2, 1))
        self.assertEqual(e1.fiscal_year, self.fy1404)
        self.assertEqual(e3.fiscal_year, self.fy1405)
        self.assertEqual(e1.total, 100)
        self.assertTrue(all(e.status == JournalEntry.POSTED for e in (e1, e2, e3)))

    def test_rules_rejected(self):
        cases = [
            [Dr(self.server, 100), Cr(self.bank, 90)],                      # نابرابر
            [Dr(self.server, 100)],                                          # یک ردیف
            [Dr(self.server, 0), Cr(self.bank, 0)],                          # صفر
            [services.Line(self.server, 100, 100), Cr(self.bank, 0)],        # دو طرف
            [Dr(Account.objects.get(code='51'), 100), Cr(self.bank, 100)],   # حسابِ کل
        ]
        for lines in cases:
            with self.assertRaises(ValidationError):
                self.entry('1405/02/01', lines)
        self.assertEqual(JournalEntry.objects.count(), 0)

    def test_inactive_account_and_missing_year(self):
        self.ai.is_active = False
        self.ai.save()
        with self.assertRaises(ValidationError):
            self.entry('1405/02/01', [Dr(self.ai, 10), Cr(self.bank, 10)])
        with self.assertRaises(ValidationError):
            self.entry('1399/02/01', [Dr(self.server, 10), Cr(self.bank, 10)])

    def test_posted_is_immutable_in_model(self):
        e = self.entry('1405/02/01', [Dr(self.server, 100), Cr(self.bank, 100)])
        e.description = 'دست‌کاری'
        with self.assertRaises(ValidationError):
            e.save()
        with self.assertRaises(ValidationError):
            e.delete()
        line = e.lines.first()
        line.debit = 5
        with self.assertRaises(ValidationError):
            line.save()
        with self.assertRaises(ValidationError):
            line.delete()
        with self.assertRaises(ValidationError):
            JournalLine(entry=e, account=self.cash, debit=1).save()

    def test_posted_is_immutable_in_database(self):
        e = self.entry('1405/02/01', [Dr(self.server, 100), Cr(self.bank, 100)])
        attempts = [
            lambda: JournalEntry.objects.filter(pk=e.pk).update(description='x'),
            lambda: JournalEntry.objects.filter(pk=e.pk).delete(),
            lambda: JournalLine.objects.filter(entry=e).update(debit=1),
            lambda: JournalLine.objects.filter(entry=e).delete(),
            lambda: JournalLine.objects.bulk_create([JournalLine(entry=e, account=self.cash, debit=5)]),
        ]
        for fn in attempts:
            with self.assertRaises(DatabaseError):
                with transaction.atomic():
                    fn()
        e.refresh_from_db()
        self.assertEqual(e.description, 'آزمون')
        self.assertEqual(e.totals(), (100, 100))

    def test_database_refuses_posting_unbalanced(self):
        d = self.entry('1405/02/01', [Dr(self.server, 100), Cr(self.bank, 100)], post=False)
        with transaction.atomic():
            JournalLine.objects.filter(entry=d, credit__gt=0).update(credit=90)
        with self.assertRaises(ValidationError):
            services.post_entry(d, self.user)
        with self.assertRaises(DatabaseError):
            with transaction.atomic():
                JournalEntry.objects.filter(pk=d.pk).update(status='posted', number=99)

    def test_no_gaps_when_drafts_are_deleted(self):
        draft = self.entry('1405/03/01', [Dr(self.server, 10), Cr(self.bank, 10)], post=False)
        self.assertIsNone(draft.number)
        a = self.entry('1405/03/02', [Dr(self.server, 20), Cr(self.bank, 20)])
        draft.delete()
        b = self.entry('1405/03/03', [Dr(self.server, 30), Cr(self.bank, 30)])
        nums = list(JournalEntry.objects.filter(status='posted', fiscal_year=self.fy1405)
                    .order_by('number').values_list('number', flat=True))
        self.assertEqual(nums, [1, 2])
        self.assertEqual((a.number, b.number), (1, 2))

    def test_post_draft_later(self):
        d = self.entry('1405/03/01', [Dr(self.server, 10), Cr(self.bank, 10)], post=False)
        d.description = 'ویرایشِ پیش‌نویس مجاز است'
        d.save()
        p = services.post_entry(d, self.user)
        self.assertEqual(p.number, 1)
        self.assertEqual(p.posted_by, self.user)
        with self.assertRaises(ValidationError):
            services.post_entry(p, self.user)


class ReversalTests(Base):
    def test_reversal(self):
        e = self.entry('1405/04/01', [Dr(self.server, 500), Cr(self.bank, 500)])
        r = services.reverse_entry(e, self.user, date=J('1405/04/05'))
        self.assertEqual(r.kind, JournalEntry.KIND_REVERSAL)
        self.assertEqual(r.reversal_of, e)
        self.assertEqual(r.number, 2)
        lines = {(l.account_id, l.debit, l.credit) for l in r.lines.all()}
        self.assertEqual(lines, {(self.server.pk, 0, 500), (self.bank.pk, 500, 0)})
        inc, exp, profit = reports.income_expense(J('1405/01/01'), J('1405/12/29'))
        self.assertEqual((inc, exp, profit), (0, 0, 0))
        self.assertEqual(reports.cash_status(None, J('1405/12/29'))['totals']['close'], 0)
        with self.assertRaises(ValidationError):
            services.reverse_entry(e, self.user)
        with self.assertRaises(ValidationError):
            services.reverse_entry(r, self.user)

    def test_reversal_guards(self):
        draft = self.entry('1405/04/01', [Dr(self.server, 5), Cr(self.bank, 5)], post=False)
        with self.assertRaises(ValidationError):
            services.reverse_entry(draft, self.user)
        e = self.entry('1405/04/10', [Dr(self.server, 5), Cr(self.bank, 5)])
        with self.assertRaises(ValidationError):
            services.reverse_entry(e, self.user, date=J('1405/04/09'))

    def test_copy_as_draft(self):
        e = self.entry('1405/04/01', [Dr(self.server, 5), Cr(self.bank, 5)])
        c = services.copy_as_draft(e, self.user, date=J('1405/04/02'))
        self.assertEqual(c.status, JournalEntry.DRAFT)
        self.assertEqual(c.totals(), (5, 5))


class ClosingTests(Base):
    def _year_activity(self, pa, pb):
        services.record_contribution(date=J('1404/01/10'), amount=1_000_000, partner=pa, into=self.bank, user=self.user)
        services.record_contribution(date=J('1404/01/10'), amount=500_000, partner=pb, into=self.bank, user=self.user)
        services.record_income(date=J('1404/05/01'), amount=1_000_001, income_account=self.tokens,
                               received_in=self.bank, user=self.user)
        services.record_expense(date=J('1404/06/01'), amount=200_000, expense_account=self.server,
                                paid_from=self.bank, user=self.user)
        services.record_expense(date=J('1404/06/02'), amount=100_000, expense_account=self.sms,
                                partner=pb, user=self.user)

    def test_close_year_moves_profit_to_partners(self):
        pa, pb = self.partners(60, 40)
        self._year_activity(pa, pb)
        made = services.close_year(self.fy1404, self.user)
        self.assertEqual(len(made), 2)
        self.assertTrue(all(e.kind == JournalEntry.KIND_CLOSING and e.is_posted for e in made))
        self.fy1404.refresh_from_db()
        self.assertTrue(self.fy1404.is_closed)
        # سود = ۱٬۰۰۰٬۰۰۱ − ۳۰۰٬۰۰۰ = ۷۰۰٬۰۰۱ ⇒ ۶۰٪ = ۴۲۰٬۰۰۰٫۶ و ۴۰٪ = ۲۸۰٬۰۰۰٫۴ ⇒ ۴۲۰٬۰۰۱ و ۲۸۰٬۰۰۰
        end = self.fy1404.end_date
        st = {r['partner'].name: r for r in reports.partners_status(end)['rows']}
        self.assertEqual(st['علی']['profit'], 420_001)
        self.assertEqual(st['رضا']['profit'], 280_000)
        self.assertEqual(st['رضا']['pocket'], 100_000)
        self.assertEqual(st['علی']['capital'], 1_000_000)
        # سود و زیانِ سال (بی‌سندِ بستن) هنوز سود را نشان می‌دهد
        pl = reports.profit_loss(self.fy1404.start_date, end)
        self.assertEqual((pl['total_income'], pl['total_expense'], pl['profit']), (1_000_001, 300_000, 700_001))
        # بعد از بستن: درآمد/هزینه و خلاصهٔ سود و زیان صفر، ترازنامه تراز
        bs = reports.balance_sheet(end)
        self.assertTrue(bs['balanced'])
        self.assertEqual(bs['unclosed_profit'], 0)
        self.assertEqual(bs['total_assets'], 1_000_000 + 500_000 + 1_000_001 - 200_000)
        tb = reports.trial_balance(None, end)
        summary = Account.by_role('pl_summary')
        self.assertFalse([r for r in tb['rows'] if r['account'] == summary and (r['cd'] or r['cc'])])
        self.assertTrue(tb['totals']['balanced'])
        # سالِ بسته سند نمی‌گیرد
        with self.assertRaises(ValidationError):
            self.entry('1404/07/01', [Dr(self.server, 1), Cr(self.bank, 1)])
        with self.assertRaises(ValidationError):
            services.close_year(self.fy1404, self.user)

    def test_close_loss(self):
        pa, pb = self.partners(50, 50)
        services.record_expense(date=J('1404/06/01'), amount=1001, expense_account=self.server,
                                paid_from=self.bank, user=self.user)
        services.close_year(self.fy1404, self.user)
        st = {r['partner'].name: r['profit'] for r in reports.partners_status(self.fy1404.end_date)['rows']}
        self.assertEqual(sorted(st.values()), [-501, -500])

    def test_close_guards(self):
        pa, pb = self.partners(60, 30)
        self._year_activity(pa, pb)
        p = services.closing_preview(self.fy1404)
        self.assertTrue(any('۱۰۰' in x for x in p['problems']))
        with self.assertRaises(ValidationError):
            services.close_year(self.fy1404, self.user)
        pb.share_percent = 40
        pb.save()
        self.entry('1404/08/01', [Dr(self.server, 1), Cr(self.bank, 1)], post=False)
        self.assertTrue(any('پیش‌نویس' in x for x in services.closing_preview(self.fy1404)['problems']))
        # سالِ جاری هنوز تمام نشده
        self.assertTrue(any('تمام نشده' in x for x in
                            services.closing_preview(self.fy1405, today=J('1405/08/03'))['problems']))
        # سالِ قبلیِ باز
        FiscalYear.objects.create(jalali_year=1403)
        self.assertTrue(any('پیشین' in x for x in services.closing_preview(self.fy1404)['problems']))

    def test_close_without_partners_goes_to_retained(self):
        services.record_income(date=J('1404/05/01'), amount=900, income_account=self.tokens,
                               received_in=self.cash, user=self.user)
        services.close_year(self.fy1404, self.user)
        retained = Account.by_role('retained')
        bs = reports.balance_sheet(self.fy1404.end_date)
        rows = {x['account'].pk: x['amount'] for sec in bs['equity'] for x in sec['rows']}
        self.assertEqual(rows[retained.pk], 900)
        self.assertTrue(bs['balanced'])

    def test_split_by_share_exact(self):
        parts = services.split_by_share(100, [('a', Decimal('33.33')), ('b', Decimal('33.33')), ('c', Decimal('33.34'))])
        self.assertEqual(sum(x for _, x in parts), 100)
        self.assertEqual(dict(parts)['c'], 34)


class SimpleFormTests(Base):
    def setUp(self):
        self.client.force_login(self.user)
        self.pa, self.pb = self.partners()
        self.media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.media, True)

    def post(self, kind, data, files=None):
        data = dict(data)
        if files:
            data.update(files)
        return self.client.post(reverse('admin:accounting_new', args=[kind]), data)

    def last(self):
        return JournalEntry.objects.order_by('-pk').first()

    def lines(self, e):
        return {(l.account.code, l.debit, l.credit, l.partner_id) for l in e.lines.select_related('account')}

    def test_expense_from_bank_with_receipt(self):
        with override_settings(PRIVATE_MEDIA_ROOT=self.media):
            pdf = SimpleUploadedFile('invoice.pdf', b'%PDF-1.4 test', content_type='application/pdf')
            r = self.post('expense', {'date': '۱۴۰۵/۰۲/۱۰', 'amount': '۱۲٬۰۰۰', 'expense_account': self.server.pk,
                                      'paid_from': 'a:%s' % self.bank.pk, 'description': ''}, {'attachment': pdf})
            self.assertEqual(r.status_code, 302, getattr(r, 'context', None) and r.context['form'].errors)
            e = self.last()
            self.assertEqual(e.kind, JournalEntry.KIND_EXPENSE)
            self.assertTrue(e.is_posted)
            self.assertEqual(self.lines(e), {('5101', 12000, 0, None), ('1102', 0, 12000, None)})
            self.assertTrue(e.attachment.name.endswith('.pdf'))
            got = self.client.get(e.attachment.url)
            self.assertEqual(got.status_code, 200)
            self.assertEqual(b''.join(got.streaming_content), b'%PDF-1.4 test')

    def test_expense_paid_by_partner_pocket(self):
        r = self.post('expense', {'date': '1405/02/10', 'amount': '3000', 'expense_account': self.sms.pk,
                                  'paid_from': 'p:%s' % self.pb.pk})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.lines(self.last()), {('5104', 3000, 0, None), ('3302', 0, 3000, self.pb.pk)})

    def test_income_to_cash_and_to_partner_card(self):
        self.post('income', {'date': '1405/02/10', 'amount': '7000', 'income_account': self.services_inc.pk,
                             'received_in': 'a:%s' % self.cash.pk})
        self.assertEqual(self.lines(self.last()), {('1101', 7000, 0, None), ('4103', 0, 7000, None)})
        self.post('income', {'date': '1405/02/11', 'amount': '8000', 'income_account': self.tokens.pk,
                             'received_in': 'p:%s' % self.pa.pk})
        self.assertEqual(self.lines(self.last()), {('3301', 8000, 0, self.pa.pk), ('4101', 0, 8000, None)})

    def test_contribution_drawing_transfer(self):
        self.post('contribution', {'date': '1405/01/05', 'amount': '100000', 'partner': self.pa.pk, 'cash': self.bank.pk})
        self.assertEqual(self.lines(self.last()), {('1102', 100000, 0, None), ('3101', 0, 100000, self.pa.pk)})
        self.post('drawing', {'date': '1405/01/06', 'amount': '4000', 'partner': self.pa.pk, 'cash': self.bank.pk})
        self.assertEqual(self.lines(self.last()), {('3201', 4000, 0, self.pa.pk), ('1102', 0, 4000, None)})
        self.post('transfer', {'date': '1405/01/07', 'amount': '3000', 'from_account': self.bank.pk,
                               'to_account': self.cash.pk})
        e = self.last()
        self.assertEqual(e.kind, JournalEntry.KIND_TRANSFER)
        self.assertEqual(self.lines(e), {('1101', 3000, 0, None), ('1102', 0, 3000, None)})
        n = JournalEntry.objects.count()
        r = self.post('transfer', {'date': '1405/01/07', 'amount': '3000', 'from_account': self.bank.pk,
                                   'to_account': self.bank.pk})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(JournalEntry.objects.count(), n)

    def test_invalid_input_creates_nothing(self):
        for data in ({'date': '1405/13/01', 'amount': '10', 'expense_account': self.server.pk, 'paid_from': 'a:%s' % self.bank.pk},
                     {'date': '1405/02/01', 'amount': '-10', 'expense_account': self.server.pk, 'paid_from': 'a:%s' % self.bank.pk},
                     {'date': '1405/02/01', 'amount': '10', 'expense_account': self.tokens.pk, 'paid_from': 'a:%s' % self.bank.pk},
                     {'date': '1399/02/01', 'amount': '10', 'expense_account': self.server.pk, 'paid_from': 'a:%s' % self.bank.pk}):
            r = self.post('expense', data)
            self.assertEqual(r.status_code, 200)
        self.assertEqual(JournalEntry.objects.count(), 0)

    def test_user_without_post_permission_makes_draft(self):
        clerk = User.objects.create_user(phone_number='09990000002', password='x', is_staff=True)
        from django.contrib.auth.models import Permission
        clerk.user_permissions.add(Permission.objects.get(codename='add_journalentry'),
                                   Permission.objects.get(codename='view_journalentry'))
        self.client.force_login(clerk)
        self.post('expense', {'date': '1405/02/10', 'amount': '5', 'expense_account': self.server.pk,
                              'paid_from': 'a:%s' % self.bank.pk})
        e = self.last()
        self.assertEqual(e.status, JournalEntry.DRAFT)
        self.assertIsNone(e.number)
        self.assertEqual(self.client.get(reverse('admin:accounting_report_pl')).status_code, 403)


class PaymentImportTests(Base):
    def setUp(self):
        from app.models import TokenPurchase
        self.TP = TokenPurchase
        self.customer = User.objects.create_user(phone_number='09990000009', password='x')

    def purchase(self, price, method='gateway', status='paid', **kw):
        return self.TP.objects.create(user=self.customer, token_amount=100, original_price=Decimal(price),
                                      final_price=Decimal(price), status=status, payment_method=method, **kw)

    def test_import_is_idempotent(self):
        p1 = self.purchase('150000.00')
        self.purchase('99000', status='under_review')
        created, rows, stale = services.import_payments(user=None)
        self.assertEqual(len(created), 1)
        e = created[0]
        self.assertEqual(e.source_ref, 'tokenpurchase:%s' % p1.pk)
        self.assertEqual(e.kind, JournalEntry.KIND_PAYMENT)
        self.assertEqual({(l.account.code, l.debit, l.credit) for l in e.lines.all()},
                         {('1102', 150000, 0), ('4101', 0, 150000)})
        created2, _, _ = services.import_payments(user=None)
        self.assertEqual(created2, [])
        call_command('accounting_import_payments', stdout=_Null())
        self.assertEqual(JournalEntry.objects.filter(kind=JournalEntry.KIND_PAYMENT).count(), 1)
        with self.assertRaises(Exception):
            with transaction.atomic():
                services.create_entry(date=e.date, description='x', source_ref=e.source_ref,
                                      lines=[Dr(self.bank, 1), Cr(self.tokens, 1)])

    def test_card_payment_goes_to_linked_account_and_stale_is_reported(self):
        from app.models import CardPaymentAccount
        pa, _ = self.partners()
        card = CardPaymentAccount.objects.create(title='کارتِ علی', card_number='6037991111111111', card_holder='علی')
        cur = pa.current_account
        cur.card_payment_account = card
        cur.save()
        p = self.purchase('5000', method='card', card_account=card)
        free = self.purchase('0')
        created, rows, _ = services.import_payments()
        self.assertEqual(len(created), 1)
        self.assertEqual({(l.account.code, l.debit, l.partner_id) for l in created[0].lines.filter(debit__gt=0)},
                         {('3301', 5000, pa.pk)})
        self.assertTrue(any(r['purchase'].pk == free.pk and r['problem'] for r in rows))
        self.TP.objects.filter(pk=p.pk).update(status='rejected')
        _, stale = services.payment_candidates()
        self.assertEqual([s['purchase_id'] for s in stale], [p.pk])

    def test_import_page(self):
        self.client.force_login(self.user)
        self.purchase('1000')
        url = reverse('admin:accounting_import_payments')
        self.assertContains(self.client.get(url), 'ثبتِ 1 پرداخت')
        self.assertEqual(self.client.post(url).status_code, 302)
        self.assertEqual(JournalEntry.objects.filter(kind='payment').count(), 1)
        self.client.post(url)
        self.assertEqual(JournalEntry.objects.filter(kind='payment').count(), 1)


class _Null:
    def write(self, *a, **k):
        pass

    def flush(self):
        pass


class ReportAndAdminTests(Base):
    def setUp(self):
        self.client.force_login(self.user)
        self.pa, self.pb = self.partners(60, 40)
        u = self.user
        services.record_contribution(date=J('1405/01/05'), amount=100_000_000, partner=self.pa, into=self.bank, user=u)
        services.record_contribution(date=J('1405/01/05'), amount=50_000_000, partner=self.pb, into=self.bank, user=u)
        services.record_expense(date=J('1405/02/01'), amount=10_000_000, expense_account=self.server, paid_from=self.bank, user=u)
        services.record_expense(date=J('1405/02/02'), amount=2_000_000, expense_account=self.sms, partner=self.pb, user=u)
        services.record_expense(date=J('1405/02/03'), amount=8_000_000, expense_account=self.ai, paid_from=self.bank, user=u)
        services.record_income(date=J('1405/03/01'), amount=40_000_000, income_account=self.tokens, received_in=self.bank, user=u)
        services.record_income(date=J('1405/03/02'), amount=5_000_000, income_account=self.services_inc, received_in=self.cash, user=u)
        services.record_transfer(date=J('1405/03/03'), amount=3_000_000, from_account=self.bank, to_account=self.cash, user=u)
        services.record_drawing(date=J('1405/03/04'), amount=4_000_000, partner=self.pa, from_account=self.bank, user=u)
        wrong = services.record_expense(date=J('1405/03/05'), amount=1_000_000, expense_account=self.server, paid_from=self.bank, user=u)
        services.reverse_entry(wrong, u, date=J('1405/03/06'))
        self.to = J('1405/06/31')

    def test_numbers(self):
        pl = reports.profit_loss(J('1405/01/01'), self.to)
        self.assertEqual((pl['total_income'], pl['total_expense'], pl['profit']), (45_000_000, 20_000_000, 25_000_000))
        self.assertEqual([(s['partner'].name, s['amount']) for s in pl['shares']],
                         [('رضا', 10_000_000), ('علی', 15_000_000)])
        bs = reports.balance_sheet(self.to)
        self.assertTrue(bs['balanced'])
        self.assertEqual(bs['total_assets'], 173_000_000)
        self.assertEqual(bs['unclosed_profit'], 25_000_000)
        cash = {r['account'].code: r['close'] for r in reports.cash_status(None, self.to)['rows']}
        self.assertEqual((cash['1102'], cash['1101']), (165_000_000, 8_000_000))
        tb = reports.trial_balance(J('1405/01/01'), self.to)
        self.assertTrue(tb['totals']['balanced'])
        self.assertEqual(tb['totals']['pd'], tb['totals']['pc'])
        led = reports.ledger(self.bank, J('1405/03/01'), self.to)
        self.assertEqual(led['opening'], 150_000_000 - 18_000_000)
        self.assertEqual(led['closing'], 165_000_000)
        self.assertEqual(led['rows'][-1]['balance'], 165_000_000)
        st = {r['partner'].name: r for r in reports.partners_status(self.to)['rows']}
        self.assertEqual((st['علی']['capital'], st['علی']['drawing'], st['علی']['est']), (100_000_000, 4_000_000, 15_000_000))
        self.assertEqual((st['رضا']['pocket'], st['رضا']['invested'], st['رضا']['balance']), (2_000_000, 52_000_000, 62_000_000))
        self.assertEqual(st['علی']['balance'] + st['رضا']['balance'], bs['total_equity'])
        group = reports.ledger(Account.objects.get(code='51'), None, self.to)
        self.assertEqual(group['closing'], 20_000_000)
        d = reports.dashboard(today=J('1405/03/10'))
        self.assertEqual(d['month']['income'], 45_000_000)
        self.assertEqual(d['year']['profit'], 25_000_000)

    def test_pages_render(self):
        e = JournalEntry.objects.filter(status='posted').first()
        draft = self.entry('1405/03/10', [Dr(self.server, 5), Cr(self.bank, 5)], post=False)
        urls = [reverse('admin:index'), reverse('admin:app_list', args=['accounting']),
                reverse('admin:accounting_help'), reverse('admin:accounting_import_payments')]
        for kind in ('expense', 'income', 'contribution', 'drawing', 'transfer'):
            urls.append(reverse('admin:accounting_new', args=[kind]))
        for name in ('pl', 'balance', 'trial', 'ledger', 'partners', 'cash'):
            u = reverse('admin:accounting_report_%s' % name)
            urls += [u, u + '?preset=month', u + '?date_from=1405/01/01&date_to=1405/06/31&account=%s' % self.bank.pk]
        urls.append(reverse('admin:accounting_report_trial') + '?level=1')
        for m in ('account', 'partner', 'fiscalyear', 'journalentry', 'accountingsettings'):
            urls.append(reverse('admin:accounting_%s_changelist' % m))
        for m in ('account', 'partner', 'fiscalyear', 'journalentry'):
            urls.append(reverse('admin:accounting_%s_add' % m))
        urls += [reverse('admin:accounting_journalentry_change', args=[e.pk]),
                 reverse('admin:accounting_journalentry_change', args=[draft.pk]),
                 reverse('admin:accounting_journalentry_reverse', args=[e.pk]),
                 reverse('admin:accounting_account_change', args=[self.bank.pk]),
                 reverse('admin:accounting_partner_change', args=[self.pa.pk]),
                 reverse('admin:accounting_fiscalyear_change', args=[self.fy1405.pk]),
                 reverse('admin:accounting_fiscalyear_close', args=[self.fy1404.pk]),
                 reverse('admin:accounting_journalentry_changelist') + '?q=1']
        for u in urls:
            r = self.client.get(u, follow=True)
            self.assertEqual(r.status_code, 200, u)
        idx = self.client.get(reverse('admin:app_list', args=['accounting']))
        self.assertContains(idx, 'آوردهٔ هر شریک')
        self.assertContains(idx, '25,000,000')
        self.assertContains(self.client.get(reverse('admin:index')), 'داشبورد، ثبتِ سریع و گزارش‌ها')
        for name in ('pl', 'balance', 'trial', 'partners', 'cash'):
            r = self.client.get(reverse('admin:accounting_report_%s' % name) + '?export=csv')
            self.assertEqual(r['Content-Type'], 'text/csv; charset=utf-8')
        r = self.client.get(reverse('admin:accounting_report_ledger') + '?account=%s&export=csv' % self.bank.pk)
        self.assertIn('165000000', r.content.decode('utf-8'))

    def test_manual_entry_in_admin(self):
        url = reverse('admin:accounting_journalentry_add')
        base = {'date': '1405/04/01', 'description': 'بدهی به فروشندهٔ هاست',
                'lines-TOTAL_FORMS': '4', 'lines-INITIAL_FORMS': '0',
                'lines-MIN_NUM_FORMS': '0', 'lines-MAX_NUM_FORMS': '1000'}
        payable = Account.by_role('payable')
        bad = dict(base, **{'lines-0-account': self.server.pk, 'lines-0-debit': '1,000',
                            'lines-1-account': payable.pk, 'lines-1-credit': '900', '_post': '1'})
        r = self.client.post(url, bad)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'برابر نیست')
        n = JournalEntry.objects.count()
        good = dict(bad, **{'lines-1-credit': '۱٬۰۰۰'})
        r = self.client.post(url, good)
        self.assertEqual(r.status_code, 302)
        e = JournalEntry.objects.order_by('-pk').first()
        self.assertEqual(JournalEntry.objects.count(), n + 1)
        self.assertTrue(e.is_posted)
        self.assertEqual(e.created_by, self.user)
        self.assertEqual(e.totals(), (1000, 1000))
        # قطعی دیگر از ادمین عوض نمی‌شود
        r = self.client.post(reverse('admin:accounting_journalentry_change', args=[e.pk]),
                             dict(good, description='دست‌کاری'))
        self.assertIn(r.status_code, (302, 403))
        e.refresh_from_db()
        self.assertEqual(e.description, 'بدهی به فروشندهٔ هاست')
        r = self.client.post(reverse('admin:accounting_journalentry_delete', args=[e.pk]), {'post': 'yes'})
        self.assertEqual(r.status_code, 403)
        self.assertTrue(JournalEntry.objects.filter(pk=e.pk).exists())
        # برگشت از راهِ ادمین
        r = self.client.post(reverse('admin:accounting_journalentry_reverse', args=[e.pk]),
                             {'date': '1405/04/02', 'description': ''})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(JournalEntry.objects.filter(reversal_of=e).exists())

    def test_close_year_from_admin(self):
        services.record_income(date=J('1404/05/01'), amount=1000, income_account=self.tokens,
                               received_in=self.cash, user=self.user)
        r = self.client.post(reverse('admin:accounting_fiscalyear_close', args=[self.fy1404.pk]))
        self.assertEqual(r.status_code, 302)
        self.fy1404.refresh_from_db()
        self.assertTrue(self.fy1404.is_closed)
        self.assertEqual(self.fy1404.closed_by, self.user)

    def test_accounting_group(self):
        g = Group.objects.get(name='حسابداری')
        self.assertTrue(g.permissions.filter(codename='post_journalentry').exists())
        self.assertTrue(g.permissions.filter(codename='close_fiscalyear').exists())
        staff = User.objects.create_user(phone_number='09990000003', password='x', is_staff=True)
        self.client.force_login(staff)
        self.assertEqual(self.client.get(reverse('admin:accounting_report_pl')).status_code, 403)
        staff.groups.add(g)
        self.assertEqual(self.client.get(reverse('admin:accounting_report_pl')).status_code, 200)
        self.assertEqual(self.client.get(reverse('admin:accounting_new', args=['expense'])).status_code, 200)
