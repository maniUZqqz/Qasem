"""کمکِ ابزارِ `nm-domain.sh` که به جنگو نیاز دارد (خودِ ابزار بی جنگو هم کار می‌کند):

  python manage.py nm_domain report --domain example.ir   ⇒ یک خطِ JSON: نشانیِ عمومی/میزبانِ مجاز/CSRF/پروکسیِ SSL و نمونهٔ وب‌هوک و ویجت
  python manage.py nm_domain hooks [--dry-run|--rollback] ⇒ وب‌هوک‌های «ثبت‌شده» را روی نشانیِ تازه دوباره ثبت می‌کند

وب‌هوکِ هر کانال وقتی ثبت می‌شود که نشانیِ عمومی همان لحظه نوشته می‌شود؛ پس بعد از عوض‌شدنِ دامنه، آنچه قبلاً ثبت شده به نشانیِ قدیمی می‌رود.
"""
import json
from urllib.parse import urlsplit

from django.conf import settings
from django.core.management.base import BaseCommand
from django.http import HttpRequest
from django.test import RequestFactory


def _request(host: str, secure: bool = True) -> HttpRequest:
    extra = {"HTTP_HOST": host}
    if secure:
        extra["HTTP_X_FORWARDED_PROTO"] = "https"
    return RequestFactory().get("/", **extra)


class Command(BaseCommand):
    help = "ابزارِ کمکیِ nm-domain.sh: گزارشِ تنظیماتِ دامنه و ثبتِ دوبارهٔ وب‌هوک‌ها"

    def add_arguments(self, parser):
        sub = parser.add_subparsers(dest="action")
        sub.required = True
        rep = sub.add_parser("report")
        rep.add_argument("--domain", required=True)
        hk = sub.add_parser("hooks")
        hk.add_argument("--dry-run", action="store_true")
        hk.add_argument("--rollback", action="store_true")

    def handle(self, *args, **opts):
        if opts["action"] == "report":
            self._report(opts["domain"])
        else:
            self._hooks(dry=opts["dry_run"], rollback=opts["rollback"])

    # ------------------------------------------------------------- report
    def _report(self, domain: str) -> None:
        from apps.inbox import publicurl
        from apps.inbox.models import InboxSettings

        # فقط فروشگاهی که همین حالا ردیفِ تنظیماتِ صندوق دارد (publicurl.resolve با get_or_create ردیفِ تازه می‌سازد؛ گزارش نباید چیزی بنویسد)
        row = InboxSettings.objects.select_related("store").order_by("id").first()
        store = row.store if row else None
        req = _request(domain)
        host_allowed = True
        try:
            req.get_host()
        except Exception:  # noqa: BLE001 - DisallowedHost
            host_allowed = False
        resolved = publicurl.resolve(req, store) if host_allowed else {"url": "", "secure": False}
        base = f"https://{domain}"
        hook = publicurl.build(req, store, "/api/v1/inbox/hook/bale/EXAMPLE/") if host_allowed else ""
        widget = publicurl.build(req, store, "/api/v1/widget/EXAMPLE.js") if host_allowed else ""
        pub = settings.UPMARKET_PUBLISHING.get("PUBLIC_BASE_URL", "")
        out = {
            "public_url": resolved["url"],
            "secure": bool(resolved.get("secure")),
            "source": resolved.get("source", ""),
            "host_allowed": host_allowed,
            "csrf_ok": base in list(settings.CSRF_TRUSTED_ORIGINS),
            "proxy_ssl": bool(getattr(settings, "SECURE_PROXY_SSL_HEADER", None)) and req.is_secure(),
            "env_public_base_url": pub,
            "env_panel_url": settings.UPMARKET_PAYMENT.get("PANEL_URL", ""),
            "env_payment_callback": settings.UPMARKET_PAYMENT.get("CALLBACK_BASE", ""),
            "webhook_sample": hook,
            "widget_sample": widget,
            "samples_ok": hook.startswith(base + "/") and widget.startswith(base + "/"),
        }
        self.stdout.write(json.dumps(out, ensure_ascii=False))

    # -------------------------------------------------------------- hooks
    def _hooks(self, dry: bool, rollback: bool) -> None:
        from apps.inbox import dispatch
        from apps.inbox.models import ChannelConnection
        from apps.inbox.views_channels import hook_url

        rows = [c for c in ChannelConnection.objects.filter(enabled=True).select_related("store")
                if (c.config or {}).get("webhook_registered")]
        if dry:
            self.stdout.write(f"{len(rows)} کانالِ فعال وب‌هوکِ ثبت‌شده دارد" + ("؛ بعد از عوض‌شدنِ دامنه دوباره ثبت می‌شوند." if rows else "؛ چیزی برای ثبتِ دوباره نیست."))
            return
        host = urlsplit(settings.UPMARKET_PUBLISHING.get("PUBLIC_BASE_URL", "")).netloc or "localhost"
        ok = failed = cleared = 0
        for conn in rows:
            adapter = dispatch.adapter_for(conn)
            if adapter is None:
                continue
            url = hook_url(_request(host), conn)
            result = adapter.register_webhook(url) if url else None
            if result is not None and result.ok:
                ok += 1
                self.stdout.write(f"  {conn.kind} (فروشگاه {conn.store_id}): وب‌هوک روی {url.split('/api/')[0]} ثبت شد")
                continue
            failed += 1
            reason = getattr(result, "reason", "") if result is not None else "نشانی ساخته نشد"
            if rollback:
                # نشانیِ http را پلتفرم‌ها نمی‌پذیرند: وب‌هوک را پاک کن تا «پرسشِ دوره‌ای» جایش بیاید
                clear = getattr(adapter, "clear_webhook", None)
                if clear is not None:
                    clear()
                cfg = dict(conn.config or {})
                cfg["webhook_registered"] = False
                conn.config = cfg
                conn.save(update_fields=["config", "updated_at"])
                cleared += 1
                self.stdout.write(f"  {conn.kind} (فروشگاه {conn.store_id}): وب‌هوک پاک شد؛ پرسشِ دوره‌ای جایگزین می‌شود")
            else:
                self.stdout.write(f"  {conn.kind} (فروشگاه {conn.store_id}): ثبت نشد - {reason}")
        self.stdout.write(f"وب‌هوک‌ها: {ok} ثبت‌شد، {failed} ناموفق" + (f"، {cleared} پاک‌شد" if rollback else "")
                          if rows else "وب‌هوکِ ثبت‌شده‌ای نبود؛ چیزی برای ثبتِ دوباره نیست.")
        if failed and not rollback:
            raise SystemExit(1)
