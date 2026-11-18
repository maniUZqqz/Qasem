"""«دامنه و SSL»: نامِ دامنه، ویرایشِ .env، vhostِ nginx، نشانی‌های ذخیره‌شده، کارتِ ادمین، دستورِ کمکی و خودِ ابزارِ nm-domain.sh
(با nginx/certbotِ ساختگی روی پوشهٔ موقت؛ آزمونِ واقعی با Let's Encrypt روی سرور جداست - docs/deploy/domain-fa.md)."""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import re
import shutil
import sqlite3
import stat
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.test import APIClient

from . import domain_core as core
from . import domain_status

REPO = Path(__file__).resolve().parents[3]
CLI_PATH = REPO / "deploy" / "nm" / "nm_domain.py"


def load_cli():
    spec = importlib.util.spec_from_file_location("nm_domain_cli", CLI_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ------------------------------------------------------------------ نامِ دامنه
class NormalizeDomainTests(SimpleTestCase):
    def test_good_forms(self):
        self.assertEqual(core.normalize_domain("example.ir"), ("example.ir", []))
        self.assertEqual(core.normalize_domain("  HTTPS://Example.IR/panel?x=1 ", www=True), ("example.ir", ["www.example.ir"]))
        self.assertEqual(core.normalize_domain("chat.example.ir.", www=True), ("chat.example.ir", ["www.chat.example.ir"]))
        # «www.» ِ داده‌شده خودش نامِ اصلی است؛ www.www ساخته نمی‌شود
        self.assertEqual(core.normalize_domain("www.example.ir", www=True), ("www.example.ir", []))

    def test_persian_domain_becomes_punycode(self):
        domain, _ = core.normalize_domain("دامنه.ir")
        self.assertTrue(domain.startswith("xn--") and domain.endswith(".ir"))

    def test_bad_names_say_why_in_persian(self):
        for raw, needle in (
            ("", "نامِ دامنه را بنویسید"), ("87.107.160.17", "IP"), ("example", "پسوند"), ("a_b.ir", "نامعتبر"),
            ("example.ir:8040", "پورت"), ("*.example.ir", "ستاره"), ("me@example.ir", "نامِ کاربری"), ("site.local", "عمومی"),
            ("-bad-.ir", "نامعتبر"), ("a" * 64 + ".ir", "نامعتبر"),
        ):
            with self.assertRaises(core.DomainError, msg=raw) as ctx:
                core.normalize_domain(raw)
            self.assertIn(needle, str(ctx.exception), raw)


# ------------------------------------------------------------------ .env
ENV = """# comment
SECRET_KEY=abc
PUBLIC_BASE_URL=http://87.107.160.17:8040
PANEL_URL=http://87.107.160.17:8040/panel
CSRF_TRUSTED_ORIGINS=http://87.107.160.17:8040,http://127.0.0.1:8040
ALLOWED_HOSTS=87.107.160.17,127.0.0.1,localhost
"""


class EnvEditTests(SimpleTestCase):
    def updates(self, **kw):
        return core.env_updates(core.env_values(ENV), "example.ir", ["www.example.ir"], kw.get("strict", False), "87.107.160.17")

    def test_apply_in_place_then_block_and_idempotent(self):
        up = self.updates()
        out = core.env_apply(ENV, up)
        vals = core.env_values(out)
        self.assertEqual(vals["PUBLIC_BASE_URL"], "https://example.ir")
        self.assertEqual(vals["PANEL_URL"], "https://example.ir/panel")
        self.assertEqual(vals["PAYMENT_CALLBACK_BASE"], "https://example.ir")
        self.assertEqual(vals["USE_PROXY_SSL_HEADER"], "true")
        self.assertEqual(vals["SECRET_KEY"], "abc", "کلیدهای دیگر دست نمی‌خورند")
        # کلیدِ موجود سرِ جایش عوض شد، کلیدِ تازه فقط در بلوکِ علامت‌دار آمد
        self.assertEqual(out.count("PUBLIC_BASE_URL="), 1)
        self.assertEqual(out.count(core.BLOCK_BEGIN), 1)
        self.assertIn("USE_PROXY_SSL_HEADER=true", out.split(core.BLOCK_BEGIN)[1])
        self.assertNotIn("PUBLIC_BASE_URL", out.split(core.BLOCK_BEGIN)[1])
        self.assertEqual(core.env_apply(out, up), out, "اجرای دوباره = همان متن")

    def test_csrf_keeps_ip_origins_and_adds_https_ones(self):
        vals = core.env_values(core.env_apply(ENV, self.updates()))
        self.assertEqual(vals["CSRF_TRUSTED_ORIGINS"].split(","), [
            "http://87.107.160.17:8040", "http://127.0.0.1:8040", "https://example.ir", "https://www.example.ir"])

    def test_allowed_hosts_wildcard_is_left_and_strict_is_explicit(self):
        # DJANGO_ALLOWED_HOSTS نیست (= «*») ⇒ دست نمی‌زنیم، چون دامنه را می‌پذیرد و فهرستِ سخت‌گیرانه چیزی را (مثلِ گره‌ها) قطع می‌کرد
        self.assertNotIn("DJANGO_ALLOWED_HOSTS", self.updates())
        strict = self.updates(strict=True)["DJANGO_ALLOWED_HOSTS"].split(",")
        self.assertEqual(strict, ["87.107.160.17", "127.0.0.1", "localhost", "example.ir", "www.example.ir"])
        # اگر مالک فهرستِ خودش را دارد، فقط دامنه‌ها به آخرش اضافه می‌شود
        env = ENV + "DJANGO_ALLOWED_HOSTS=87.107.160.17,nm.local\n"
        up = core.env_updates(core.env_values(env), "example.ir", [], False, "87.107.160.17")
        self.assertEqual(up["DJANGO_ALLOWED_HOSTS"], "87.107.160.17,nm.local,example.ir")

    def test_restore_is_byte_exact_and_keeps_other_edits(self):
        up = self.updates()
        prev = {k: core.env_values(ENV).get(k) for k in up}
        out = core.env_apply(ENV, up)
        self.assertEqual(core.env_restore(out, prev), ENV)
        edited = out + "MY_OWN_KEY=1\n"
        self.assertEqual(core.env_restore(edited, prev), ENV + "MY_OWN_KEY=1\n")
        # دومین اجرا برای دامنهٔ دیگر هم با همان prev برمی‌گردد
        second = core.env_apply(out, core.env_updates(core.env_values(out), "other.ir", [], False, "1.2.3.4"))
        self.assertEqual(core.env_restore(second, prev), ENV)


# ------------------------------------------------------------------ vhost
def _location_text(text: str) -> str:
    """از «# ---- فایل‌های ایستا» تا آخرِ بلوکِ server، با فاصله‌ها یکدست‌شده."""
    start = text.index("    # ---- فایل‌های ایستا")
    body = text[start:].rstrip()
    assert body.endswith("}")
    body = body[:-1]  # آکولادِ server
    return re.sub(r"\s+", " ", body).strip()


class VhostTests(SimpleTestCase):
    def render(self, **kw):
        args = dict(domain="example.ir", aliases=["www.example.ir"], phase="final", root="/var/www/NM/upmarket", webroot="/var/www/html",
                    cert_dir="/etc/letsencrypt/live/example.ir", logdir="/www/wwwlogs")
        args.update(kw)
        return core.render_vhost(args.pop("domain"), args.pop("aliases"), **args)

    def test_final_has_https_redirect_acme_and_canonical_www(self):
        v = self.render()
        self.assertIn("listen 443 ssl;", v)
        self.assertIn("http2 on;", v)
        self.assertIn("ssl_certificate /etc/letsencrypt/live/example.ir/fullchain.pem;", v)
        self.assertIn("ssl_certificate_key /etc/letsencrypt/live/example.ir/privkey.pem;", v)
        self.assertIn("location ^~ /.well-known/acme-challenge/ { root /var/www/html;", v)
        self.assertIn("return 301 https://example.ir$request_uri;", v)
        self.assertEqual(v.count("listen 443 ssl;"), 2, "یکی برای دامنه، یکی برای ریدایرکتِ www")
        self.assertNotIn("Strict-Transport-Security", v)
        self.assertIn("Strict-Transport-Security", self.render(hsts=True))
        self.assertEqual(self.render(aliases=[]).count("listen 443 ssl;"), 1)

    def test_bootstrap_serves_the_app_on_80_only(self):
        v = self.render(phase="bootstrap", cert_dir=None)
        self.assertIn("listen 80;", v)
        self.assertNotIn("listen 443", v)
        self.assertNotIn("ssl_certificate", v)
        self.assertIn("proxy_pass http://127.0.0.1:8041;", v)
        self.assertIn("acme-challenge", v)

    def test_names_and_paths_are_only_what_was_asked(self):
        v = self.render(root="/srv/nm")
        self.assertIn("alias /srv/nm/backend/staticfiles/;", v)
        self.assertNotIn("/var/www/NM/upmarket", v)
        self.assertNotIn("listen 8040", v, "پورتِ 8040 از vhostِ دامنه جداست")
        self.assertNotIn("127.0.0.1:8001", v, "به بک‌اندِ سایت‌های دیگر وصل نمی‌شود")

    def test_locations_match_port_8040_conf(self):
        """مسیرها باید با port_8040.conf یکی بمانند؛ اگر کسی آن را عوض کرد این آزمون می‌گوید این‌جا هم عوض کند."""
        conf = (REPO / "deploy" / "nm" / "nginx-port_8040.conf").read_text(encoding="utf-8")
        ours = re.sub(r"\s+", " ", core.LOCATIONS.replace("{root}", "/var/www/NM/upmarket")).strip()
        self.assertEqual(ours, _location_text(conf))


# ------------------------------------------------------------------ نشانی‌های ذخیره‌شده
class UrlRowsTests(SimpleTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "db.sqlite3"
        con = sqlite3.connect(self.db)
        con.executescript("""
            CREATE TABLE inbox_inboxsettings (id INTEGER PRIMARY KEY, store_id INT, public_base_url TEXT);
            INSERT INTO inbox_inboxsettings VALUES (1, 10, ''), (2, 11, 'http://87.107.160.17:8040'),
                (3, 12, 'https://chat.myshop.ir'), (4, 13, 'http://localhost:8000');
            CREATE TABLE growth_knowledge_knowledgeitem (id INTEGER PRIMARY KEY, seed_key TEXT, url TEXT);
            INSERT INTO growth_knowledge_knowledgeitem VALUES (1, 'site', 'http://87.107.160.17:8040/'), (2, 'other', 'http://87.107.160.17:8040/'),
                (3, 'site', 'https://mine.ir/');
        """)
        con.commit()
        con.close()

    def rows(self, sql):
        con = sqlite3.connect(self.db)
        try:
            return con.execute(sql).fetchall()
        finally:
            con.close()

    def test_inbox_replaces_blank_and_ours_but_never_the_owners_own_address(self):
        todo, why = core.inbox_plan(self.db, "https://example.ir", set())
        self.assertEqual(why, "")
        self.assertEqual(sorted(i for i, _ in todo), [1, 2, 4])
        core.inbox_set(self.db, {i: "https://example.ir" for i, _ in todo})
        self.assertEqual(self.rows("select public_base_url from inbox_inboxsettings order by id"),
                         [("https://example.ir",), ("https://example.ir",), ("https://chat.myshop.ir",), ("https://example.ir",)])
        self.assertEqual(core.inbox_plan(self.db, "https://example.ir", set())[0], [], "ایده‌مپوتنت")
        core.inbox_set(self.db, {i: old for i, old in todo})  # برگرداندن
        self.assertEqual(self.rows("select public_base_url from inbox_inboxsettings order by id"),
                         [("",), ("http://87.107.160.17:8040",), ("https://chat.myshop.ir",), ("http://localhost:8000",)])

    def test_switching_to_another_domain_follows_the_previous_one(self):
        core.inbox_set(self.db, {1: "https://old.ir"})
        todo, _ = core.inbox_plan(self.db, "https://new.ir", {"https://old.ir"})
        self.assertIn(1, [i for i, _ in todo])

    def test_knowledge_only_touches_the_site_row_with_our_address(self):
        todo, _ = core.knowledge_plan(self.db, "https://example.ir/", set())
        self.assertEqual([i for i, _ in todo], [1])
        core.knowledge_set(self.db, {1: "https://example.ir/"})
        self.assertEqual(self.rows("select id, url from growth_knowledge_knowledgeitem order by id"),
                         [(1, "https://example.ir/"), (2, "http://87.107.160.17:8040/"), (3, "https://mine.ir/")])

    def test_missing_table_is_a_message_not_a_crash(self):
        todo, why = core.url_plan(self.db, "no_such_table", "x", "https://a.ir", set())
        self.assertEqual(todo, [])
        self.assertIn("no_such_table", why)
        self.assertEqual(core.inbox_plan(Path("/nonexistent/db.sqlite3"), "https://a.ir", set())[0], [])


# ------------------------------------------------------------------ DNS (با dig ساختگی)
class DnsReportTests(SimpleTestCase):
    def report(self, answers: dict, aaaa=()):
        def fake_dig(name, rtype, server=None):
            if rtype == "AAAA":
                return list(aaaa)
            if rtype == "NS":
                return ["ns1.example.ir."]
            return answers.get(server or "system", answers.get("any", []))
        with patch.object(core, "dig", fake_dig), patch.object(core.socket, "getaddrinfo",
                                                               lambda *a, **k: [(2, 1, 6, "", (ip, 80)) for ip in answers.get("system", [])]):
            return core.dns_report("example.ir", "87.107.160.17")

    def test_ok(self):
        r = self.report({"system": ["87.107.160.17"], "any": ["87.107.160.17"], "ns1.example.ir": ["87.107.160.17"]})
        self.assertEqual(r["status"], "ok")

    def test_missing_wrong_partial_and_aaaa_each_have_a_persian_fix(self):
        r = self.report({"system": [], "any": []})
        self.assertEqual(r["status"], "missing")
        self.assertIn("رکوردِ A", r["message"])
        r = self.report({"system": ["1.2.3.4"], "any": ["1.2.3.4"]})
        self.assertEqual(r["status"], "wrong")
        self.assertIn("1.2.3.4", r["message"])
        self.assertIn("CDN", r["message"])
        r = self.report({"system": ["87.107.160.17"], "any": ["87.107.160.17", "1.2.3.4"]})
        self.assertEqual(r["status"], "partial")
        r = self.report({"system": ["87.107.160.17"], "any": ["87.107.160.17"]}, aaaa=["2606:4700::1"])
        self.assertEqual(r["status"], "aaaa")
        self.assertIn("AAAA", r["message"])


# ------------------------------------------------------------------ کارتِ ادمین
STATE = {
    "domain": "example.ir", "aliases": ["www.example.ir"], "canonical": "https://example.ir", "ca": "letsencrypt", "staging": False,
    "cert_dir": "/nonexistent/live/example.ir", "applied_at": "2026-11-18T10:00:00Z", "server_ip": "87.107.160.17", "version": "1.0",
}


class DomainCardApiTests(TestCase):
    def setUp(self):
        U = get_user_model()
        self.user = U.objects.create_user("u", "u@x.io", "pw")
        self.staff = U.objects.create_user("s", "s@x.io", "pw", is_staff=True)
        self.data_dir = Path(tempfile.mkdtemp(prefix="nm-domain-test-"))
        self.override = override_settings(NM_DATA_DIR=self.data_dir)
        self.override.enable()
        self.addCleanup(self.override.disable)

    def write_state(self, **kw):
        p = domain_status.state_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({**STATE, **kw}), encoding="utf-8")

    def get(self, user=None):
        c = APIClient()
        if user:
            c.force_authenticate(user)
        return c.get("/api/v1/panel/domain/")

    def test_only_staff(self):
        self.assertIn(self.get().status_code, (401, 403))
        self.assertEqual(self.get(self.user).status_code, 403)
        self.assertEqual(self.get(self.staff).status_code, 200)

    def test_ip_only_state(self):
        data = self.get(self.staff).data
        self.assertEqual(data["mode"], "ip_only")
        self.assertFalse(data["configured"])
        self.assertTrue(data["ip_url"].endswith(":8040"))
        self.assertEqual(data["script"], "/root/nm-domain.sh")

    def test_domain_state_with_expiry_and_ok_dns(self):
        self.write_state()
        cert = {"not_after": "2027-02-01T00:00:00Z", "days_left": 75, "issuer": "C = US, O = Let's Encrypt, CN = R11", "names": ["example.ir"],
                "staging": False, "self_signed": False}
        with patch.object(domain_status, "tls_probe", return_value=cert), \
                patch.object(core, "dns_report", return_value={"status": "ok", "found": ["87.107.160.17"], "message": "ok"}), \
                override_settings(UPMARKET_PUBLISHING={"PUBLIC_BASE_URL": "https://example.ir"}):
            data = self.get(self.staff).data
        self.assertEqual(data["mode"], "domain")
        self.assertEqual(data["domain"]["domain"], "example.ir")
        self.assertEqual(data["cert"]["days_left"], 75)
        self.assertEqual(data["warnings"], [])
        self.assertTrue(data["cert_served"])
        self.assertIn("--rollback", data["rollback_command"])

    def test_warnings_for_soon_expiring_staging_and_wrong_dns(self):
        self.write_state(ca="letsencrypt-staging", staging=True)
        cert = {"not_after": "2026-11-25T00:00:00Z", "days_left": 7, "issuer": "(STAGING) X", "names": ["example.ir"], "staging": True, "self_signed": False}
        with patch.object(domain_status, "tls_probe", return_value=cert), \
                patch.object(core, "dns_report", return_value={"status": "wrong", "found": ["1.1.1.1"], "message": "به 1.1.1.1 اشاره می‌کند"}), \
                override_settings(UPMARKET_PUBLISHING={"PUBLIC_BASE_URL": "http://87.107.160.17:8040"}):
            data = self.get(self.staff).data
        self.assertEqual(data["mode"], "attention")
        text = " ".join(data["warnings"])
        self.assertIn("7 روز", text)
        self.assertIn("آزمایشی", text)
        self.assertIn("DNS", text)
        self.assertIn("نشانیِ عمومیِ فعلیِ NM", text)

    def test_tls_not_answering_is_a_warning_not_an_error(self):
        self.write_state()
        with patch.object(domain_status, "tls_probe", return_value=None), \
                patch.object(core, "dns_report", return_value={"status": "ok", "found": [], "message": ""}), \
                override_settings(UPMARKET_PUBLISHING={"PUBLIC_BASE_URL": "https://example.ir"}):
            data = self.get(self.staff).data
        self.assertEqual(data["mode"], "attention")
        self.assertFalse(data["cert_served"])

    def check(self, body, user=None):
        c = APIClient()
        c.force_authenticate(user or self.staff)
        return c.post("/api/v1/panel/domain/check/", body, format="json")

    def test_dns_check_tells_what_records_to_add(self):
        report = {"name": "x", "status": "missing", "a": {}, "aaaa": [], "found": [], "server_ip": "87.107.160.17", "message": "رکورد A ندارد"}
        with patch.object(core, "dns_report", return_value=report):
            r = self.check({"domain": "https://Example.IR/", "www": True})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["domain"], "example.ir")
        self.assertEqual(r.data["names"], ["example.ir", "www.example.ir"])
        self.assertFalse(r.data["ok"])
        self.assertEqual([(x["type"], x["name"], x["value"]) for x in r.data["records"]],
                         [("A", "@", "87.107.160.17"), ("A", "www", "87.107.160.17")])
        self.assertEqual(r.data["command"], "/root/nm-domain.sh example.ir --www")
        self.assertTrue(r.data["dry_command"].endswith("--dry-run"))

    def test_dns_check_ok_and_without_www(self):
        ok = {"name": "x", "status": "ok", "a": {}, "aaaa": [], "found": ["87.107.160.17"], "server_ip": "87.107.160.17", "message": "ok"}
        with patch.object(core, "dns_report", return_value=ok):
            r = self.check({"domain": "example.ir", "www": False})
        self.assertTrue(r.data["ok"])
        self.assertEqual(r.data["names"], ["example.ir"])
        self.assertEqual(r.data["command"], "/root/nm-domain.sh example.ir")

    def test_dns_check_bad_name_is_400_in_persian_and_staff_only(self):
        r = self.check({"domain": "87.107.160.17"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("IP", r.data["detail"])
        self.assertEqual(self.check({"domain": "example.ir"}, user=self.user).status_code, 403)


# ------------------------------------------------------------------ دستورِ کمکی (report / hooks)
class FakeAdapter:
    def __init__(self, ok=True):
        self.ok, self.urls, self.cleared = ok, [], 0

    def register_webhook(self, url):
        from apps.inbox.adapters.base import SendResult
        self.urls.append(url)
        return SendResult(self.ok, "" if self.ok else "http نمی‌پذیرد")

    def clear_webhook(self):
        from apps.inbox.adapters.base import SendResult
        self.cleared += 1
        return SendResult(True, "")


@override_settings(ALLOWED_HOSTS=["example.ir"], CSRF_TRUSTED_ORIGINS=["https://example.ir"],
                   SECURE_PROXY_SSL_HEADER=("HTTP_X_FORWARDED_PROTO", "https"),
                   UPMARKET_PUBLISHING={"PUBLIC_BASE_URL": "https://example.ir"})
class NmDomainCommandTests(TestCase):
    def setUp(self):
        from apps.stores.models import Store
        self.owner = get_user_model().objects.create_user("o", "o@x.io", "pw")
        self.store = Store.objects.create(owner=self.owner, name="فروشگاه آزمون")

    def run_cmd(self, *args):
        out = io.StringIO()
        call_command("nm_domain", *args, stdout=out)
        return out.getvalue()

    def test_report_follows_the_domain_and_writes_nothing(self):
        from apps.inbox.models import InboxSettings
        before = InboxSettings.objects.count()
        out = json.loads(self.run_cmd("report", "--domain", "example.ir").strip().splitlines()[-1])
        self.assertEqual(out["public_url"], "https://example.ir")
        self.assertTrue(out["secure"] and out["host_allowed"] and out["csrf_ok"] and out["proxy_ssl"] and out["samples_ok"])
        self.assertTrue(out["webhook_sample"].startswith("https://example.ir/api/v1/inbox/hook/"))
        self.assertTrue(out["widget_sample"].startswith("https://example.ir/api/v1/widget/"))
        self.assertEqual(InboxSettings.objects.count(), before, "گزارش نباید ردیفِ تازه بسازد")

    def test_report_prefers_the_store_setting_and_flags_a_disallowed_host(self):
        from apps.inbox.models import InboxSettings
        InboxSettings.objects.create(store=self.store, public_base_url="https://chat.myshop.ir")
        out = json.loads(self.run_cmd("report", "--domain", "example.ir").strip().splitlines()[-1])
        self.assertEqual(out["public_url"], "https://chat.myshop.ir", "نشانیِ دلخواهِ مالک مقدم است")
        self.assertFalse(out["samples_ok"])
        bad = json.loads(self.run_cmd("report", "--domain", "evil.test").strip().splitlines()[-1])
        self.assertFalse(bad["host_allowed"])

    def make_connection(self, **cfg):
        from apps.inbox.models import ChannelConnection
        return ChannelConnection.objects.create(store=self.store, kind="BALE", enabled=True, token="t", config={"webhook_registered": True, **cfg})

    def test_hooks_dry_run_only_counts(self):
        self.make_connection()
        with patch("apps.inbox.dispatch.adapter_for") as ad:
            out = self.run_cmd("hooks", "--dry-run")
        self.assertIn("1 کانال", out)
        ad.assert_not_called()

    def test_hooks_reregisters_on_the_new_address(self):
        conn = self.make_connection()
        fake = FakeAdapter()
        with patch("apps.inbox.dispatch.adapter_for", return_value=fake):
            out = self.run_cmd("hooks")
        self.assertEqual(len(fake.urls), 1)
        self.assertTrue(fake.urls[0].startswith("https://example.ir/api/v1/inbox/hook/"))
        self.assertIn("1 ثبت‌شد", out)
        conn.refresh_from_db()
        self.assertTrue(conn.config["webhook_registered"])

    def test_hooks_ignore_disabled_and_unregistered_connections(self):
        from apps.inbox.models import ChannelConnection
        ChannelConnection.objects.create(store=self.store, kind="EITAA", enabled=False, token="t", config={"webhook_registered": True})
        ChannelConnection.objects.create(store=self.store, kind="RUBIKA", enabled=True, token="t", config={})
        fake = FakeAdapter()
        with patch("apps.inbox.dispatch.adapter_for", return_value=fake):
            out = self.run_cmd("hooks")
        self.assertEqual(fake.urls, [])
        self.assertIn("چیزی برای ثبتِ دوباره نیست", out)

    def test_hooks_rollback_clears_what_the_platform_refuses(self):
        conn = self.make_connection()
        fake = FakeAdapter(ok=False)
        with patch("apps.inbox.dispatch.adapter_for", return_value=fake):
            out = self.run_cmd("hooks", "--rollback")
        self.assertEqual(fake.cleared, 1)
        self.assertIn("پرسشِ دوره‌ای", out)
        conn.refresh_from_db()
        self.assertFalse(conn.config["webhook_registered"])

    def test_hooks_failure_without_rollback_exits_nonzero(self):
        self.make_connection()
        with patch("apps.inbox.dispatch.adapter_for", return_value=FakeAdapter(ok=False)):
            with self.assertRaises(SystemExit):
                self.run_cmd("hooks")


# ------------------------------------------------------------------ خودِ ابزار (nginx و certbot ساختگی)
FAKE_SCRIPT = "#!/bin/sh\nexit 0\n"


class CliOrchestrationTests(SimpleTestCase):
    """همان مسیرِ زنده روی یک درختِ موقت: apply ⇒ دوباره apply ⇒ rollback، با شکستِ تزریقی و تداخلِ نام."""

    ORIGINAL_ENV = ENV.replace("ALLOWED_HOSTS", "ALLOWED_HOSTS")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        t = Path(self.tmp.name)
        self.root = t / "nm"
        (self.root / "backend").mkdir(parents=True)
        (self.root / "data").mkdir()
        self.env_file = self.root / "backend" / ".env"
        self.env_file.write_text(ENV + f"SQLITE_PATH={self.root}/data/db.sqlite3\n", encoding="utf-8")
        self.db = self.root / "data" / "db.sqlite3"
        con = sqlite3.connect(self.db)
        con.executescript("""
            CREATE TABLE inbox_inboxsettings (id INTEGER PRIMARY KEY, store_id INT, public_base_url TEXT);
            INSERT INTO inbox_inboxsettings VALUES (1, 10, ''), (2, 11, 'https://chat.myshop.ir');
            CREATE TABLE growth_knowledge_knowledgeitem (id INTEGER PRIMARY KEY, seed_key TEXT, url TEXT);
            INSERT INTO growth_knowledge_knowledgeitem VALUES (1, 'site', 'http://87.107.160.17:8040/');
        """)
        con.commit()
        con.close()
        self.vhosts = t / "vhost"
        self.vhosts.mkdir()
        for name, body in (("nginx", FAKE_SCRIPT), ("python", "#!/bin/sh\necho '0 کانالِ فعال وب‌هوکِ ثبت‌شده دارد؛ چیزی برای ثبتِ دوباره نیست.'\n")):
            p = t / name
            p.write_text(body)
            p.chmod(p.stat().st_mode | stat.S_IEXEC)
        self.env = {
            "NM_ROOT": str(self.root), "NM_CONF_ROOT": str(self.root), "NM_VHOST_DIR": str(self.vhosts), "NM_NGINX_BIN": str(t / "nginx"),
            "NM_PYTHON": str(t / "python"), "NM_WEBROOT": str(t / "webroot"), "NM_LE_DIR": str(t / "le"), "NM_LOGDIR": str(t / "logs"),
            "NM_LOCK": str(t / "lock"), "NM_NO_SERVICES": "1", "NM_SKIP_WEBSITE_BUILD": "1", "NM_SKIP_SMOKE": "1", "NM_ALLOW_NONROOT": "1",
            "NM_SERVER_IP": "87.107.160.17", "NM_BUILD_BASE": str(t),
        }
        self.patch = patch.dict(os.environ, self.env)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.cli = load_cli()

    def invoke(self, *args, fail_at=None):
        env = {"NM_FAIL_AT": fail_at} if fail_at else {}
        out = io.StringIO()
        with patch.dict(os.environ, env), contextlib.redirect_stdout(out):
            rc = self.cli.main([*args])
        return rc, out.getvalue()

    def snapshot(self):
        con = sqlite3.connect(self.db)
        rows = (con.execute("select * from inbox_inboxsettings").fetchall(), con.execute("select * from growth_knowledge_knowledgeitem").fetchall())
        con.close()
        return (self.env_file.read_bytes(), rows, sorted(p.name for p in self.vhosts.iterdir()),
                (self.root / "website" / ".env.production.local").exists(), (self.root / "data" / "domain" / "domain.json").exists())

    APPLY = ("example.ir", "--www", "--self-signed", "--skip-dns-check", "--no-webhooks")

    def test_dry_run_changes_nothing(self):
        before = self.snapshot()
        rc, out = self.invoke(*self.APPLY, "--dry-run")
        self.assertEqual(rc, 0, out)
        self.assertIn("dry-run", out)
        self.assertEqual(self.snapshot(), before)

    def test_apply_is_idempotent_and_rollback_restores_every_byte(self):
        before = self.snapshot()
        rc, out = self.invoke(*self.APPLY)
        self.assertEqual(rc, 0, out)
        env = core.env_values(self.env_file.read_text(encoding="utf-8"))
        self.assertEqual(env["PUBLIC_BASE_URL"], "https://example.ir")
        self.assertEqual(env["PANEL_URL"], "https://example.ir/panel")
        self.assertIn("https://www.example.ir", env["CSRF_TRUSTED_ORIGINS"])
        self.assertEqual(env["USE_PROXY_SSL_HEADER"], "true")
        vhost = (self.vhosts / "zz-nm-example.ir.conf").read_text(encoding="utf-8")
        self.assertIn("listen 443 ssl;", vhost)
        self.assertIn("selfsigned/example.ir/fullchain.pem", vhost)
        con = sqlite3.connect(self.db)
        self.assertEqual(con.execute("select public_base_url from inbox_inboxsettings order by id").fetchall(),
                         [("https://example.ir",), ("https://chat.myshop.ir",)], "نشانیِ دلخواهِ مالک دست نخورد")
        self.assertEqual(con.execute("select url from growth_knowledge_knowledgeitem").fetchall(), [("https://example.ir/",)])
        con.close()
        state = json.loads((self.root / "data" / "domain" / "domain.json").read_text(encoding="utf-8"))
        self.assertEqual(state["canonical"], "https://example.ir")
        self.assertIn("IP", state["node_note"])
        applied = self.snapshot()
        rc, out = self.invoke(*self.APPLY)
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.snapshot(), applied, "دوباره اجرا = هیچ تغییری")
        self.assertEqual(self.cli.cmd_status.__name__, "cmd_status")
        rc, out = self.invoke("--rollback")
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.snapshot(), before, "برگرداندن = بایتِ‌به‌بایت مثلِ پیش از دامنه")

    def test_failure_at_any_step_undoes_the_whole_run(self):
        before = self.snapshot()
        for step in ("vhost-final", "env", "inbox", "services", "smoke"):
            rc, out = self.invoke(*self.APPLY, fail_at=step)
            self.assertEqual(rc, 1, (step, out))
            self.assertIn("شکستِ آزمایشی", out)
            self.assertEqual(self.snapshot(), before, f"بعد از شکست در «{step}» باید همه‌چیز برگردد")

    def test_a_failing_website_build_only_warns_and_rollback_still_restores_its_env(self):
        before = self.snapshot()
        with patch.dict(os.environ, {"NM_SKIP_WEBSITE_BUILD": ""}), \
                patch.object(self.cli, "website_rebuild", side_effect=self.cli.StepError("ساخت نشد (آزمایشی)")):
            rc, out = self.invoke(*self.APPLY)
        self.assertEqual(rc, 0, "دامنه و https برقرار می‌مانند")
        self.assertIn("ساخت نشد (آزمایشی)", out)
        self.assertIn("بقیه‌چیز آماده است", out)
        self.assertEqual(core.env_values(self.env_file.read_text(encoding="utf-8"))["PUBLIC_BASE_URL"], "https://example.ir")
        state = json.loads((self.root / "data" / "domain" / "domain.json").read_text(encoding="utf-8"))
        self.assertIn("website_env", state, "env ِ پیشینِ سایت برای --rollback ثبت شد")
        self.assertNotIn("website_built_for", state)
        site_env = (self.root / "website" / ".env.production.local").read_text(encoding="utf-8")
        self.assertIn("NEXT_PUBLIC_SITE_URL=https://example.ir", site_env)
        self.assertEqual(self.invoke("--rollback")[0], 0)
        self.assertEqual(self.snapshot(), before)

    def test_name_used_by_another_site_is_refused(self):
        (self.vhosts / "zz-chagher.conf").write_text("server { listen 80; server_name example.ir www.example.ir; }\n")
        before = self.snapshot()
        rc, out = self.invoke(*self.APPLY)
        self.assertEqual(rc, 1)
        self.assertIn("zz-chagher.conf", out)
        self.assertEqual(self.snapshot(), before)

    def test_commented_out_server_name_is_not_a_clash(self):
        (self.vhosts / "old.conf").write_text("# server_name example.ir;\nserver {\n    server_name something-else.ir;\n}\n")
        rc, out = self.invoke(*self.APPLY, "--dry-run")
        self.assertEqual(rc, 0, out)

    def test_bad_name_exits_2_and_dns_failure_exits_3(self):
        rc, out = self.invoke("87.107.160.17")
        self.assertEqual(rc, 2)
        with patch.object(self.cli, "dns_report", return_value={"status": "wrong", "message": "به 1.2.3.4 اشاره می‌کند"}):
            rc, out = self.invoke("example.ir", "--self-signed", "--no-webhooks")
        self.assertEqual(rc, 3)
        self.assertIn("1.2.3.4", out)
        self.assertFalse((self.vhosts / "zz-nm-example.ir.conf").exists())

    def test_switching_domain_moves_the_stored_addresses_and_rollback_still_returns_to_the_original(self):
        before = self.snapshot()
        self.assertEqual(self.invoke(*self.APPLY)[0], 0)
        self.assertEqual(self.invoke("other.ir", "--self-signed", "--skip-dns-check", "--no-webhooks")[0], 0)
        con = sqlite3.connect(self.db)
        self.assertEqual(con.execute("select public_base_url from inbox_inboxsettings order by id").fetchall(),
                         [("https://other.ir",), ("https://chat.myshop.ir",)])
        con.close()
        rc, out = self.invoke("--rollback")
        self.assertEqual(rc, 0, out)
        # دامنهٔ اول هنوز vhost دارد (عمداً دست نخورده)؛ بقیه‌چیز مثلِ اول است
        after = self.snapshot()
        self.assertEqual(after[0], before[0])
        self.assertEqual(after[1], before[1])

    def test_reload_services_is_graceful_and_leaves_gpu_worker_alone_when_busy(self):
        calls = []

        class P:  # کمترین چیزی که reload_services می‌خواند
            no_services = False
            env_file = self.env_file
            data = self.root / "data"

        args = self.cli.build_parser().parse_args(["example.ir"])
        run_ = self.cli.Run(P(), args, self.cli.Reporter(None))
        with patch.object(self.cli, "run", side_effect=lambda cmd, **k: (calls.append(cmd) or (0, ""))), \
                patch.object(self.cli.shutil, "which", return_value="/usr/local/bin/nm-reload"), \
                patch.object(self.cli, "_running_compute_jobs", return_value=2), contextlib.redirect_stdout(io.StringIO()):
            self.cli.reload_services(run_)
        self.assertEqual(calls[0], ["nm-reload"])
        self.assertIn(["systemctl", "restart", "nm-celery", "nm-celery-beat"], calls)
        self.assertNotIn(["systemctl", "restart", "nm-celery-node"], calls, "کارِ GPU در جریان است")
        calls.clear()
        with patch.object(self.cli, "run", side_effect=lambda cmd, **k: (calls.append(cmd) or (0, ""))), \
                patch.object(self.cli.shutil, "which", return_value="/usr/local/bin/nm-reload"), \
                patch.object(self.cli, "_running_compute_jobs", return_value=0), contextlib.redirect_stdout(io.StringIO()):
            self.cli.reload_services(run_)
        self.assertIn(["systemctl", "restart", "nm-celery-node"], calls)

    # ---------------------------------------------------------------- سایتِ عمومی: ساخت در پوشهٔ جدا و جابه‌جایی
    def _site_fixture(self):
        site = self.root / "website"
        (site / "node_modules").mkdir(parents=True)
        (site / "package.json").write_text("{}")
        (site / ".next").mkdir()
        (site / ".next" / "marker").write_text("old")
        P = self.cli.Paths()
        args = self.cli.build_parser().parse_args(["example.ir"])
        return site, self.cli.Run(P, args, self.cli.Reporter(None)), Path(self.env["NM_BUILD_BASE"])

    def _fake_build_run(self, base, bake):
        real = self.cli.run

        def fake(cmd, timeout=60, env=None):
            if cmd[0] in ("rsync", "systemctl"):
                return 0, ""
            if cmd[0] == "cp":
                next(base.glob("nm-site-build-*")).joinpath("node_modules").mkdir()
                return 0, ""
            if cmd[0] == "flock":
                build = next(base.glob("nm-site-build-*"))
                (build / ".next" / "standalone").mkdir(parents=True)
                (build / ".next" / "standalone" / "server.js").write_text("//")
                (build / ".next" / "server" / "app").mkdir(parents=True)
                (build / ".next" / "server" / "app" / "index.html").write_text(bake)
                return 0, ""
            return real(cmd, timeout=timeout, env=env)
        return fake

    class _Conn:
        status = 200

        def __init__(self, *a, **k):
            pass

        def request(self, *a, **k):
            pass

        def getresponse(self):
            return self

    def test_website_is_built_aside_and_swapped_only_when_healthy(self):
        site, run_, base = self._site_fixture()
        with patch.object(self.cli, "run", self._fake_build_run(base, "<link rel=canonical href=https://example.ir/>")),                 patch.object(self.cli.http.client, "HTTPConnection", self._Conn), patch.object(self.cli.time, "sleep"),                 contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(self.cli.website_rebuild(run_, "https://example.ir", swap=True))
        self.assertFalse((site / ".next" / "marker").exists(), "ساختِ تازه جایش آمد")
        self.assertTrue((site / ".next" / "server" / "app" / "index.html").exists())
        self.assertEqual([p.name for p in site.iterdir() if p.name.startswith(".next.old")], [], "نسخهٔ قدیمی پاک شد")
        self.assertEqual(list(base.glob("nm-site-build-*")), [], "پوشهٔ ساخت پاک شد")

    def test_website_swap_reverts_when_the_new_build_does_not_answer(self):
        site, run_, base = self._site_fixture()

        class Bad(self._Conn):
            status = 500

        with patch.object(self.cli, "run", self._fake_build_run(base, "https://example.ir")),                 patch.object(self.cli.http.client, "HTTPConnection", Bad), patch.object(self.cli.time, "sleep"),                 contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(self.cli.StepError):
                self.cli.website_rebuild(run_, "https://example.ir", swap=True)
        self.assertEqual((site / ".next" / "marker").read_text(), "old", "سایتِ قبلی برگشت")
        self.assertEqual(list(base.glob("nm-site-build-*")), [])

    def test_website_build_that_lacks_the_new_address_is_not_swapped(self):
        site, run_, base = self._site_fixture()
        with patch.object(self.cli, "run", self._fake_build_run(base, "http://87.107.160.17:8040")), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(self.cli.StepError) as ctx:
                self.cli.website_rebuild(run_, "https://example.ir", swap=True)
        self.assertIn("نیست", str(ctx.exception))
        self.assertEqual((site / ".next" / "marker").read_text(), "old")

    def test_website_build_in_test_mode_never_swaps(self):
        site, run_, base = self._site_fixture()
        with patch.object(self.cli, "run", self._fake_build_run(base, "https://example.ir")), contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(self.cli.website_rebuild(run_, "https://example.ir", swap=False))
        self.assertEqual((site / ".next" / "marker").read_text(), "old")
        self.assertEqual(list(base.glob("nm-site-build-*")), [])

    def _selfsigned(self, days):
        d = self.root / "data" / "domain" / "selfsigned" / "example.ir"
        d.mkdir(parents=True)
        import subprocess
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(d / "privkey.pem"), "-out", str(d / "fullchain.pem"),
                        "-days", str(days), "-subj", "/CN=example.ir", "-addext", "subjectAltName=DNS:example.ir"], check=True, capture_output=True)
        shutil.copy(d / "fullchain.pem", d / "cert.pem")
        return d

    def _write_state(self, **kw):
        sf = self.root / "data" / "domain" / "domain.json"
        sf.parent.mkdir(parents=True, exist_ok=True)
        sf.write_text(json.dumps({"domain": "example.ir", "ca": "letsencrypt", "vhost": str(self.vhosts / "zz-nm-example.ir.conf"),
                                  "cert_dir": str(self.root / "data" / "domain" / "selfsigned" / "example.ir"), **kw}), encoding="utf-8")

    def test_watch_is_silent_without_a_domain_and_one_line_when_healthy(self):
        rc, out = self.invoke("--watch")
        self.assertEqual((rc, out), (0, ""))
        (self.vhosts / "zz-nm-example.ir.conf").write_text("x")
        self._selfsigned(300)
        self._write_state(ca="selfsigned")
        with patch.object(self.cli, "dns_report", return_value={"status": "ok", "message": ""}):
            rc, out = self.invoke("--watch")
        self.assertEqual(rc, 0, out)
        self.assertIn("example.ir", out)
        self.assertIn("سالم", out)
        self.assertEqual(len(out.strip().splitlines()), 1)

    def test_watch_renews_a_short_lived_certificate_and_reports_problems(self):
        calls = self.root / "certbot-calls"
        fake = Path(self.tmp.name) / "certbot"
        fake.write_text(f'#!/bin/sh\necho "$@" >> {calls}\nexit 0\n')
        fake.chmod(0o755)
        self._selfsigned(10)  # ۱۰ روز مانده؛ certbotِ ساختگی چیزی را تمدید نمی‌کند
        self._write_state(ca="letsencrypt")
        with patch.dict(os.environ, {"NM_CERTBOT_BIN": str(fake)}), patch.object(self.cli, "dns_report", return_value={"status": "wrong", "message": "به 1.2.3.4 اشاره می‌کند"}):
            rc, out = self.invoke("--watch")
        self.assertEqual(rc, 1)
        self.assertIn("renew --cert-name example.ir", calls.read_text())
        self.assertIn("تمدیدِ گواهی شکست خورد", out)
        self.assertIn("vhost (zz-nm-example.ir.conf) نیست", out)
        self.assertIn("1.2.3.4", out)

    def test_certbot_failures_are_explained_in_persian(self):
        for text, needle in (
            ("too many certificates already issued; retry after 2026-11-19 10:00:00 UTC", "سقفِ"),
            ("Connection refused", "پورتِ 80"),
            ("Invalid response from http://x/.well-known/acme-challenge/abc [1.2.3.4]: 404", "DNS"),
            ("NXDOMAIN looking up A for example.ir", "NXDOMAIN"),
            ("Network is unreachable", "ZeroSSL"),
        ):
            self.assertIn(needle, self.cli.explain_certbot_failure(text, ["example.ir"]), text)
