"""آزمون‌ها در /tmp هیچ ردپایی نگذارند.

مشکل (۱۴۰۵/۰۸/۲۳): حدود ۶۰ ماژولِ آزمون در لحظهٔ import (بالای فایل) `tempfile.mkdtemp()` می‌زدند و هیچ‌کدام پاک‌اش نمی‌کردند؛
هر اجرا — حتی فقط «پیدا کردنِ آزمون‌ها» — پوشه‌ای به‌جا می‌گذاشت. نتیجه: ۳۰۲۴ پوشه و ۳ گیگابایت در /tmp روی دیسکی که ۵ گیگ جا داشت
(نمونه‌اش ۵۴۶ پوشهٔ `nm-test-data-*` که هر کدام ۱۱۳ مگابایت از پوشهٔ motion را برمی‌داشتند).

راهِ درست‌تر از دست‌زدن به ۶۰ فایل (که بقیهٔ تیم‌ها هم هم‌زمان ویرایششان می‌کنند): این رانر یک پوشهٔ مخصوصِ هر اجرا می‌سازد
(`<tmp>/nm-testrun-<pid>-<تصادفی>`)، `tempfile.tempdir` و `TMPDIR` را روی آن می‌گذارد — پیش از آنکه آزمون‌ها import شوند —
و آخرِ اجرا (و با atexit اگر اجرا وسط بمیرد) همه‌اش را پاک می‌کند. هر `mkdtemp()` در هر آزمونی، حتی در زمانِ import، همان‌جا می‌افتد.
اجراهایی که با kill -9 مردند را اجرای بعدی (و `nm-tmp-sweep` شبانه) پاک می‌کند.

ماندنِ پوشه برای عیب‌یابی:  NM_KEEP_TEST_TMP=1 python manage.py test ...
"""
from __future__ import annotations

import atexit
import os
import shutil
import stat
import tempfile
from pathlib import Path

from django.test.runner import DiscoverRunner

RUN_PREFIX = "nm-testrun-"


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # پروسه هست ولی مالِ کسِ دیگر است
    except OSError:
        return False
    return True


def _rmtree(path: str | Path) -> None:
    """حذفِ پوشه حتی اگر فایل‌های فقط‌خواندنی دارد (npm/git)."""

    def onerror(func, p, _exc):
        try:
            os.chmod(p, stat.S_IWRITE | stat.S_IREAD | stat.S_IEXEC)
            func(p)
        except OSError:
            pass

    shutil.rmtree(path, onerror=onerror)


def sweep_stale(base: str | Path | None = None) -> int:
    """پوشه‌های اجراهای مرده (pid دیگر نیست) را پاک می‌کند؛ شمارِ پاک‌شده را برمی‌گرداند."""
    base = Path(base or tempfile.gettempdir())
    removed = 0
    try:
        entries = list(base.iterdir())
    except OSError:
        return 0
    for entry in entries:
        name = entry.name
        if not name.startswith(RUN_PREFIX) or entry.is_symlink() or not entry.is_dir():
            continue
        pid_text = name[len(RUN_PREFIX):].split("-", 1)[0]
        if pid_text.isdigit() and _pid_alive(int(pid_text)):
            continue
        _rmtree(entry)
        removed += 1
    return removed


class NMTestRunner(DiscoverRunner):
    """DiscoverRunner + پوشهٔ موقتِ اختصاصیِ هر اجرا که آخرش پاک می‌شود."""

    _run_dir: str | None = None
    _saved_tempdir = None
    _saved_tmpdir_env: str | None = None
    _atexit_registered = False

    def _enter_tmp(self) -> str:
        if self._run_dir:
            return self._run_dir
        base = tempfile.gettempdir()
        sweep_stale(base)
        self._saved_tempdir = tempfile.tempdir
        self._saved_tmpdir_env = os.environ.get("TMPDIR")
        self._run_dir = tempfile.mkdtemp(prefix=f"{RUN_PREFIX}{os.getpid()}-", dir=base)
        tempfile.tempdir = self._run_dir
        os.environ["TMPDIR"] = self._run_dir  # زیرپروسه‌ها (ffmpeg، node، agent) هم همین‌جا بنویسند
        if not self._atexit_registered:
            atexit.register(self._leave_tmp)
            self._atexit_registered = True
        return self._run_dir

    def _leave_tmp(self) -> None:
        run_dir, self._run_dir = self._run_dir, None
        if not run_dir:
            return
        tempfile.tempdir = self._saved_tempdir
        if self._saved_tmpdir_env is None:
            os.environ.pop("TMPDIR", None)
        else:
            os.environ["TMPDIR"] = self._saved_tmpdir_env
        if os.environ.get("NM_KEEP_TEST_TMP") == "1":
            print(f"\n[nm-test-runner] پوشهٔ موقت نگه داشته شد: {run_dir}")
            return
        _rmtree(run_dir)
        # ریشهٔ دادهٔ آزمون (settings: NM_DATA_DIR/MEDIA_ROOT/NM_LOG_DIR وقتی صادر نشده‌اند) کنارِ پوشهٔ اجرا می‌افتد
        root = Path(os.path.dirname(run_dir)) / f"{RUN_PREFIX}{os.getpid()}-root"
        if root.is_dir() and not root.is_symlink():
            _rmtree(root)

    def run_tests(self, test_labels, **kwargs):
        self._enter_tmp()  # پیش از کشفِ آزمون‌ها: کدِ سطحِ ماژول (mkdtemp در import) همین‌جا می‌افتد
        try:
            return super().run_tests(test_labels, **kwargs)
        finally:
            self._cleanup_test_db_sidecars()
            self._leave_tmp()

    @staticmethod
    def _cleanup_test_db_sidecars() -> None:
        """فایلِ آزمونِ SQLite را Django پاک می‌کند ولی -wal/-shm ِ بازمانده را نه."""
        try:
            from django.conf import settings

            name = settings.DATABASES["default"].get("TEST", {}).get("NAME")
        except Exception:  # noqa: BLE001
            return
        if not name:
            return
        for suffix in ("", "-wal", "-shm", "-journal"):
            try:
                os.remove(f"{name}{suffix}")
            except OSError:
                pass
