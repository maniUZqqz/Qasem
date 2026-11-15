"""خودآزمونِ بانکِ ایده. ``manage.py ideabank_selftest [--live] [--store 34]``

بدونِ گزینه: بخشِ آفلاین (ایده‌های آماده، فرمول‌ها، مسیرِ هوش مصنوعی با جوابِ ساختگی)؛ خروجی ۰ = قبول.
``--live``: یک پرسشِ واقعی از مسیریابِ هوش مصنوعی برای فروشگاهِ داده‌شده (پیش‌فرض ۳۴ اگر هست) و سنجشِ جواب؛ اگر هوش مصنوعی در دسترس نیست
(گرهٔ خاموش، متیسِ بی‌اعتبار) «منتظر» چاپ می‌شود و خروجی باز هم ۰ است — چون بخشِ فرمولی همیشه کار می‌کند.
"""
from django.core.management.base import BaseCommand

from apps.ideabank import ai, selftest


class Command(BaseCommand):
    help = "خودآزمونِ بانکِ ایده (آفلاین، و با --live یک پرسشِ واقعی از هوش مصنوعی)"

    def add_arguments(self, parser):
        parser.add_argument("--live", action="store_true", help="یک پرسشِ واقعی از مسیریابِ هوش مصنوعی")
        parser.add_argument("--store", type=int, default=34, help="شناسهٔ فروشگاه برای --live (پیش‌فرض ۳۴)")

    def handle(self, *args, **opts):
        res = selftest.run_offline()
        for c in res["checks"]:
            self.stdout.write(f"{'OK  ' if c['ok'] else 'FAIL'} {c['key']}: {c['detail']}")
        code = 0 if res["ok"] else 1
        if opts["live"]:
            code = max(code, self._live(opts["store"]))
        raise SystemExit(code)

    def _live(self, store_id: int) -> int:
        from apps.stores.models import Store

        store = Store.objects.filter(pk=store_id).first()
        if store is None:
            self.stdout.write(f"WAIT live: فروشگاهِ {store_id} در این پایگاه‌داده نیست؛ پرسشِ زنده انجام نشد.")
            return 0
        prompt, system = selftest.node_prompt()
        try:
            parsed, info = ai.default_ask(store, prompt, system)
        except ai.AIUnavailable as exc:
            self.stdout.write(f"WAIT live: هوش مصنوعی در دسترس نیست ({exc}). فرمول‌ها کار می‌کنند و با برگشتِ هوش مصنوعی این آزمون خودش قبول می‌شود.")
            return 0
        import json

        ok, message = selftest.node_check(json.dumps(parsed, ensure_ascii=False))
        self.stdout.write(f"{'OK  ' if ok else 'FAIL'} live ({(info or {}).get('label', '')}): {message}")
        return 0 if ok else 1
