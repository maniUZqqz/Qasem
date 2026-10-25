# -*- coding: utf-8 -*-
"""قفلِ پایگاه‌داده‌ایِ سندِ قطعی (تریگرِ SQLite).

مدل‌ها و ادمین هم جلوی ویرایش/حذف را می‌گیرند، ولی این تریگرها حتی جلوی
queryset.update()/delete() و SQLِ دستی را هم می‌گیرند. چون بازسازیِ جدول در
مایگریشن‌های آیندهٔ SQLite تریگرها را پاک می‌کند، بعد از هر migrate دوباره
ساخته می‌شوند (apps.py ⇐ post_migrate).
"""

TRIGGERS = {
    'acc_entry_no_insert_posted': """
CREATE TRIGGER IF NOT EXISTS acc_entry_no_insert_posted
BEFORE INSERT ON accounting_journalentry
FOR EACH ROW WHEN NEW.status = 'posted'
BEGIN SELECT RAISE(ABORT, 'accounting: entries are created as draft and then posted'); END""",

    'acc_entry_posted_immutable': """
CREATE TRIGGER IF NOT EXISTS acc_entry_posted_immutable
BEFORE UPDATE ON accounting_journalentry
FOR EACH ROW WHEN OLD.status = 'posted'
BEGIN SELECT RAISE(ABORT, 'accounting: posted journal entry is immutable'); END""",

    'acc_entry_posted_no_delete': """
CREATE TRIGGER IF NOT EXISTS acc_entry_posted_no_delete
BEFORE DELETE ON accounting_journalentry
FOR EACH ROW WHEN OLD.status = 'posted'
BEGIN SELECT RAISE(ABORT, 'accounting: posted journal entry cannot be deleted'); END""",

    'acc_entry_post_balanced': """
CREATE TRIGGER IF NOT EXISTS acc_entry_post_balanced
BEFORE UPDATE ON accounting_journalentry
FOR EACH ROW WHEN NEW.status = 'posted' AND (
    (SELECT COUNT(*) FROM accounting_journalline WHERE entry_id = NEW.id) < 2
    OR (SELECT COALESCE(SUM(debit), 0) FROM accounting_journalline WHERE entry_id = NEW.id)
       <> (SELECT COALESCE(SUM(credit), 0) FROM accounting_journalline WHERE entry_id = NEW.id)
    OR NEW.number IS NULL)
BEGIN SELECT RAISE(ABORT, 'accounting: only a balanced entry with two or more lines can be posted'); END""",

    'acc_line_no_insert_posted': """
CREATE TRIGGER IF NOT EXISTS acc_line_no_insert_posted
BEFORE INSERT ON accounting_journalline
FOR EACH ROW WHEN (SELECT status FROM accounting_journalentry WHERE id = NEW.entry_id) = 'posted'
BEGIN SELECT RAISE(ABORT, 'accounting: lines of a posted entry are immutable'); END""",

    'acc_line_posted_immutable': """
CREATE TRIGGER IF NOT EXISTS acc_line_posted_immutable
BEFORE UPDATE ON accounting_journalline
FOR EACH ROW WHEN (SELECT status FROM accounting_journalentry WHERE id = OLD.entry_id) = 'posted'
               OR (SELECT status FROM accounting_journalentry WHERE id = NEW.entry_id) = 'posted'
BEGIN SELECT RAISE(ABORT, 'accounting: lines of a posted entry are immutable'); END""",

    'acc_line_posted_no_delete': """
CREATE TRIGGER IF NOT EXISTS acc_line_posted_no_delete
BEFORE DELETE ON accounting_journalline
FOR EACH ROW WHEN (SELECT status FROM accounting_journalentry WHERE id = OLD.entry_id) = 'posted'
BEGIN SELECT RAISE(ABORT, 'accounting: lines of a posted entry cannot be deleted'); END""",
}


def ensure_triggers(connection):
    if connection.vendor != 'sqlite':
        return 0
    tables = set(connection.introspection.table_names())
    if not {'accounting_journalentry', 'accounting_journalline'} <= tables:
        return 0
    with connection.cursor() as cur:
        for sql in TRIGGERS.values():
            cur.execute(sql)
    return len(TRIGGERS)


def drop_triggers(connection):
    if connection.vendor != 'sqlite':
        return
    with connection.cursor() as cur:
        for name in TRIGGERS:
            cur.execute('DROP TRIGGER IF EXISTS %s' % name)
