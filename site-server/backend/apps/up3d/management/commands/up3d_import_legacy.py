"""واردکردنِ داده‌های پنلِ مستقلِ قدیمیِ UpMarket 3D (data/up3d.sqlite3) به جدول‌های up3d_* ِ همین دیتابیس.

    python manage.py up3d_import_legacy --db /var/www/NM/_retired/3D/data/up3d.sqlite3

ستون‌ها یکی‌اند (همان مدل‌ها)؛ شناسه‌ها حفظ می‌شوند؛ مالکِ پروژه‌ها خالی می‌ماند (کاربرانِ قدیمی وارد نمی‌شوند).
فایل‌های کارها (jobs/<uid>/…) و آپلودها باید در UP3D_DATA_DIR باشند (پوشهٔ data ی قدیمی را همان‌جا بگذارید)."""
import sqlite3

from django.core.management.base import BaseCommand
from django.db import connection, transaction

TABLES = ['aisettings', 'worker', 'project', 'sceneversion', 'job', 'upload']
DROP_COLUMNS = {'project': {'owner_id'}, 'upload': {'owner_id'}}


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument('--db', required=True)

    def handle(self, *a, **o):
        old = sqlite3.connect(o['db'])
        old.row_factory = sqlite3.Row
        with transaction.atomic(), connection.cursor() as cur:
            cur.execute('PRAGMA foreign_keys=OFF')
            for t in TABLES:
                src, dst = 'studio_' + t, 'up3d_' + t
                try:
                    rows = old.execute('SELECT * FROM %s' % src).fetchall()
                except sqlite3.OperationalError as e:
                    self.stdout.write('skip %s: %s' % (src, e))
                    continue
                if not rows:
                    continue
                cur.execute('PRAGMA table_info(%s)' % dst)
                new_cols = [r[1] for r in cur.fetchall()]
                cols = [c for c in rows[0].keys() if c in new_cols and c not in DROP_COLUMNS.get(t, set())]
                n = 0
                for r in rows:
                    cur.execute('INSERT OR IGNORE INTO %s (%s) VALUES (%s)' % (dst, ','.join(cols), ','.join('%s' for _ in cols)),
                                [r[c] for c in cols])
                    n += cur.rowcount
                self.stdout.write('%s: %d/%d rows' % (dst, n, len(rows)))
            cur.execute('PRAGMA foreign_keys=ON')
