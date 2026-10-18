"""چرا کار نمی‌کند؟ — یک گزارش از همه‌چیزِ این سیستم، در یک اجرا.

    python manage.py doctor              گزارش کامل روی صفحه و در logs/doctor.txt
    python manage.py doctor --quiet      فقط سطرهای مشکل‌دار

On the main machine "nothing works" can mean six different things — Redis
down, no worker, Ollama on another port, ComfyUI missing, the website built
while the backend was still starting, or the panel talking to the wrong
address. Each one has its own fix and they look identical from the outside,
so this command checks them all in one pass and writes the result to
`logs/doctor.txt` — a file that can be sent as-is.

Read-only: it starts nothing, stops nothing and writes only that log.
"""
from __future__ import annotations

import os

import json
import socket
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

OK, WARN, BAD, INFO = "سالم", "هشدار", "خراب", "اطلاع"
MARK = {OK: "[ OK ]", WARN: "[WARN]", BAD: "[BAD ]", INFO: "[ .. ]"}


def _port_open(host: str, port: int, timeout: float = 0.8) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _get(url: str, timeout: float = 6.0):
    """(status, body) or (None, error text)."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")[:400]
    except Exception as exc:  # noqa: BLE001
        return None, str(exc)[:200]


class Command(BaseCommand):
    help = "بررسی کامل سرویس‌ها، صف، مدل‌ها، سایت عمومی و محتوای منتشرشده"

    def add_arguments(self, parser):
        parser.add_argument("--quiet", action="store_true", help="فقط موارد مشکل‌دار")

    def handle(self, *args, **options):
        self.rows: list[tuple[str, str, str]] = []
        self.quiet = options["quiet"]

        self.services()
        self.queue()
        self.database()
        self.public_site()
        self.ai_engines()
        self.media_tools()

        lines = ["گزارش سلامت آپ‌مارکت — " + timezone.localtime().strftime("%Y-%m-%d %H:%M"), ""]
        for state, title, detail in self.rows:
            lines.append(f"{MARK[state]} {title}")
            if detail:
                lines.append(f"        {detail}")
        bad = [r for r in self.rows if r[0] == BAD]
        warn = [r for r in self.rows if r[0] == WARN]
        lines += ["", f"خلاصه: {len(bad)} خراب، {len(warn)} هشدار، "
                      f"{len([r for r in self.rows if r[0] == OK])} سالم"]
        if bad or warn:
            lines += ["", "کارهایی که باید انجام شود:"]
            for state, title, detail in bad + warn:
                lines.append(f"  - {title}: {detail}")
        report = "\n".join(lines)

        log = Path(settings.BASE_DIR).parent / "logs" / "doctor.txt"
        try:
            log.parent.mkdir(parents=True, exist_ok=True)
            log.write_text(report, encoding="utf-8")
        except OSError as exc:
            report += f"\n(ننوشتن گزارش در فایل: {exc})"
        else:
            report += f"\n\nاین گزارش در {log} هم ذخیره شد — همین فایل را بفرستید."
        self.stdout.write(report)

    # ------------------------------------------------------------ helpers

    def add(self, state: str, title: str, detail: str = ""):
        if self.quiet and state == OK:
            return
        self.rows.append((state, title, detail))

    # ------------------------------------------------------------ checks

    def services(self):
        # روی سرورِ مستقرشده همه پشتِ nginx هستند؛ نشانی‌ها از .env می‌آیند (DOCTOR_*)، پیش‌فرض همان چیدمانِ توسعه
        backend = os.getenv("DOCTOR_BACKEND_URL", "http://127.0.0.1:8000").rstrip("/")
        panel = os.getenv("DOCTOR_PANEL_URL", "http://127.0.0.1:5173/")
        website = os.getenv("DOCTOR_WEBSITE_URL", "http://127.0.0.1:3001/")
        for label, url, needed in (
            ("بک‌اند جنگو", backend + "/healthz", True),
            ("داشبورد (پنل)", panel, True),
            ("سایت عمومی", website, False),
        ):
            status, body = _get(url, timeout=5)
            if status and 200 <= status < 400:
                self.add(OK, f"{label} بالا است", url)
            else:
                self.add(BAD if needed else WARN, f"{label} جواب نمی‌دهد",
                         f"{url} — {body}. با start.bat بالا بیاورید.")

    def queue(self):
        from apps.jobs.services import broker_reachable, eager_mode, workers_online

        parsed = urlparse(settings.CELERY_BROKER_URL or "")
        host, port = parsed.hostname or "127.0.0.1", parsed.port or 6379
        if not _port_open(host, port):
            self.add(BAD, "Redis روشن نیست",
                     f"{host}:{port} جواب نمی‌دهد. تولید ویدیو بدون آن کار نمی‌کند؛ "
                     "start.bat آن را نصب و روشن می‌کند.")
        else:
            self.add(OK, "Redis روشن است", f"{host}:{port}")
            if workers_online(force=True):
                self.add(OK, "کارگر صف روشن است", "کارها روی صف اجرا می‌شوند")
            else:
                self.add(BAD, "کارگر صف روشن نیست",
                         "Redis هست ولی هیچ‌کس کارها را برنمی‌دارد — پنجره‌ی "
                         "«UpMarket — Celery» را ببینید یا start.bat را دوباره اجرا کنید.")
        self.add(INFO, "حالت اجرا",
                 ("داخل درخواست وب (بدون صف)" if eager_mode() else "روی صف") +
                 f" · تنظیم: {getattr(settings, 'CELERY_MODE_SOURCE', '?')}"
                 f" · Redis: {'بله' if broker_reachable(force=True) else 'خیر'}")

    def database(self):
        from django.db import connection
        from django.db.migrations.executor import MigrationExecutor

        try:
            executor = MigrationExecutor(connection)
            pending = executor.migration_plan(executor.loader.graph.leaf_nodes())
            if pending:
                self.add(BAD, f"{len(pending)} مایگریشن اجرا نشده",
                         "python manage.py migrate را اجرا کنید (start.bat خودش می‌زند)")
            else:
                self.add(OK, "دیتابیس به‌روز است", str(connection.settings_dict.get("NAME")))
        except Exception as exc:  # noqa: BLE001
            self.add(BAD, "دیتابیس خوانده نشد", str(exc)[:200])

    def public_site(self):
        """What the public site asks for, and whether the answer is empty."""
        from apps.cms.models import Article

        base = os.getenv("DOCTOR_BACKEND_URL", "http://127.0.0.1:8000").rstrip("/") + "/api/v1"
        wanted = {
            "/blog/articles/": "مطلب‌های وبلاگ",
            "/blog/categories/": "دسته‌های وبلاگ",
            "/site/settings/": "تنظیمات سایت",
            "/site/showcase/": "نمونه‌کارها",
            "/plans/": "پلن‌ها و تعرفه",
        }
        for path, label in wanted.items():
            status, body = _get(base + path)
            if status != 200:
                self.add(BAD, f"API «{label}» جواب نداد", f"{path} — {status} {body[:120]}")
                continue
            try:
                data = json.loads(body)
            except ValueError:
                self.add(BAD, f"API «{label}» خروجی نامعتبر داد", path)
                continue
            count = len(data) if isinstance(data, list) else len(data.get("results", data) or [])
            if isinstance(data, dict) and not isinstance(data.get("results"), list):
                count = 1 if data else 0
            if count:
                self.add(OK, f"API «{label}»", f"{count} مورد")
            else:
                self.add(WARN, f"API «{label}» خالی است",
                         f"{path} چیزی برنگرداند — در جنگو ادمین وضعیت «منتشرشده» را چک کنید")

        live = Article.objects.filter(status="PUBLISHED", published_at__lte=timezone.now()).count()
        drafts = Article.objects.exclude(status="PUBLISHED").count()
        future = Article.objects.filter(status="PUBLISHED", published_at__gt=timezone.now()).count()
        if drafts or future:
            self.add(WARN, "بعضی مطلب‌ها روی سایت دیده نمی‌شوند",
                     f"{live} منتشرشده · {drafts} پیش‌نویس · {future} با تاریخ انتشار در آینده")
        else:
            self.add(OK, "همه‌ی مطلب‌ها منتشر شده‌اند", f"{live} مطلب")

        # Does the RUNNING site show what the database says? The newest
        # article's title is the marker: present = live data, absent = the
        # site is serving the copy inside the repo (or an old build).
        newest = Article.objects.filter(status="PUBLISHED").order_by("-published_at").first()
        status, body = _get("http://127.0.0.1:3001/fa/blog", timeout=8)
        if status != 200:
            self.add(WARN, "صفحه‌ی وبلاگ سایت خوانده نشد", str(body)[:160])
        elif newest and newest.title[:25] in body:
            self.add(OK, "سایت عمومی داده‌ی زنده‌ی جنگو را نشان می‌دهد", newest.title[:40])
        elif newest:
            self.add(BAD, "سایت عمومی داده‌ی جنگو را نشان نمی‌دهد",
                     f"«{newest.title[:40]}» در صفحه نبود — سایت از متن داخل ریپو استفاده می‌کند. "
                     "سایت را دوباره بیلد کنید (start.bat) در حالی که بک‌اند بالاست.")
        build = Path(settings.BASE_DIR).parent / "website" / ".next" / "BUILD_ID"
        if build.exists():
            when = timezone.datetime.fromtimestamp(build.stat().st_mtime, timezone.get_current_timezone())
            newest_edit = Article.objects.order_by("-updated_at").values_list("updated_at", flat=True).first()
            detail = f"آخرین بیلد سایت: {when:%Y-%m-%d %H:%M}"
            if newest_edit and newest_edit > when:
                self.add(WARN, "سایت بعد از آخرین ویرایش محتوا دوباره بیلد نشده",
                         detail + f" · آخرین ویرایش محتوا: {timezone.localtime(newest_edit):%Y-%m-%d %H:%M}"
                         " (صفحه‌های ساکن تا ۲ دقیقه بعد از بازدید تازه می‌شوند؛ "
                         "اگر نشد یک بار start.bat را دوباره اجرا کنید)")
            else:
                self.add(OK, "بیلد سایت تازه‌تر از محتواست", detail)
        else:
            self.add(WARN, "سایت هنوز بیلد نشده", "start.bat خودش بیلد می‌کند")

        self.revalidate_key()

    def revalidate_key(self):
        """آیا ویرایش در جنگو ادمین بلافاصله روی سایت می‌نشیند؟

        بدون این کلید، صفحه تا ۲ دقیقه نسخه‌ی کهنه را نشان می‌دهد و کسی که
        همان لحظه رفرش می‌کند فکر می‌کند ادمین اصلاً به سایت وصل نیست.
        """
        secret = (settings.UPMARKET_AI.get("WEBSITE_REVALIDATE_SECRET") or "").strip()
        site = (settings.UPMARKET_AI.get("WEBSITE_URL") or "").strip().rstrip("/")
        if not secret or not site:
            self.add(WARN, "کلید تازه‌سازی سایت تنظیم نشده",
                     "ویرایش‌های جنگو ادمین تا ۲ دقیقه بعد روی سایت می‌نشینند. "
                     "یک بار start.bat را اجرا کنید تا کلید ساخته شود.")
            return
        try:
            request = urllib.request.Request(
                f"{site}/api/revalidate",
                data=b'{"tags":[]}',
                headers={"Content-Type": "application/json", "x-revalidate-secret": secret},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=5) as response:
                ok = response.status < 400
        except urllib.error.HTTPError as exc:
            self.add(BAD, "سایت کلید تازه‌سازی را نپذیرفت",
                     f"HTTP {exc.code} — کلید دو طرف یکی نیست. "
                     "website/.env.production.local را پاک کنید و start.bat را دوباره بزنید.")
            return
        except Exception as exc:  # noqa: BLE001
            self.add(WARN, "تازه‌سازی سایت بررسی نشد", f"سایت جواب نداد: {exc}")
            return
        if ok:
            self.add(OK, "ویرایش‌های جنگو ادمین بلافاصله روی سایت می‌نشینند", site)

    def ai_engines(self):
        conf = settings.UPMARKET_AI
        for label, url, extra in (
            ("Ollama (متن و بینایی)", conf.get("OLLAMA_BASE_URL", ""), "/api/tags"),
            ("ComfyUI (تصویر و ویدیو)", conf.get("COMFYUI_BASE_URL", ""), "/system_stats"),
        ):
            if not url:
                self.add(WARN, f"آدرس {label} تنظیم نشده", "")
                continue
            parsed = urlparse(url)
            host, port = parsed.hostname or "127.0.0.1", parsed.port or (80 if parsed.scheme == "http" else 443)
            if not _port_open(host, port):
                self.add(WARN, f"{label} در دسترس نیست", (
                    f"{url} — اگر روی این سیستم آدرس دیگری دارد، آن را در "
                    "backend/.env.local بنویسید (این فایل مخصوص همین سیستم است و "
                    "با گیت جابه‌جا نمی‌شود)."
                ))
                continue
            status, body = _get(url.rstrip("/") + extra, timeout=6)
            detail = url
            if label.startswith("Ollama") and status == 200:
                try:
                    models = [m.get("name") for m in json.loads(body).get("models", [])]
                    detail = f"{url} · مدل‌ها: {', '.join(models[:6]) or 'هیچ مدلی نصب نیست'}"
                    wanted = {conf.get("OLLAMA_MODEL_REASONING"), conf.get("OLLAMA_MODEL_VISION")}
                    missing = [w for w in wanted if w and not any(w.split(":")[0] in (m or "") for m in models)]
                    if missing:
                        self.add(WARN, "مدل‌های خواسته‌شده در Ollama نیستند",
                                 f"{', '.join(missing)} — با ollama pull نصب کنید یا نام‌ها را در .env.local عوض کنید")
                except ValueError:
                    pass
            self.add(OK if status else WARN, f"{label} در دسترس است", detail)

        mode = {k: conf.get(k) for k in ("AI_MODE_TEXT", "AI_MODE_IMAGE", "AI_MODE_VIDEO")}
        self.add(INFO, "حالت هوش مصنوعی", str(mode))

    def media_tools(self):
        import shutil
        import subprocess

        # The same resolution the code itself uses: a stale absolute pin in
        # .env is ignored in favour of the copy bundled with the project.
        from services.video.ffmpeg import FFMPEG as binary

        if not binary or not (Path(binary).is_file() or shutil.which(str(binary))):
            self.add(BAD, "ffmpeg پیدا نشد", "بدون آن ویدیو، صدا و زیرنویس کار نمی‌کند (start.bat نصبش می‌کند)")
            return
        try:
            out = subprocess.run([str(binary), "-version"], capture_output=True, text=True, timeout=20)
            self.add(OK, "ffmpeg هست", out.stdout.splitlines()[0][:80] if out.stdout else str(binary))
        except Exception as exc:  # noqa: BLE001
            self.add(BAD, "ffmpeg اجرا نشد", str(exc)[:160])

        from apps.ai.management.commands.audio_setup import Command as AudioSetup

        missing = AudioSetup().missing()
        if missing:
            self.add(WARN, "بخشی از موتورهای صدای آفلاین آماده نیست",
                     " · ".join(m.replace("[MISSING] ", "") for m in missing)[:300])
        else:
            self.add(OK, "موتورهای صدای آفلاین آماده‌اند", "صدا، حذف نویز و کتابخانه")
