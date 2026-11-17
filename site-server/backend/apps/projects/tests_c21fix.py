# -*- coding: utf-8 -*-
"""اصلاحاتِ بازبینیِ ۱۱/۱۶ روی «منبع‌های طراحی + خزندهٔ 21st.dev»:

* اتصالِ پایدار از ایران (c21_net: اتصالِ هم‌زمانِ چندتایی + Keep-Alive)، robots.txt روی دیسک، نوبتِ بی‌پیشرفت ⇒ کارِ گره؛
* قطعه‌ای که به‌صورتِ ایستا خالی دیده می‌شود (blank) درج‌شدنی نیست؛ سرریزِ گوشی ⇒ fail؛ سنجشِ قدیمی خودکار تکرار می‌شود؛
* حقِ نشرِ Apache (متنِ مجوز دیگر «دارنده» نیست)، دسته‌بندیِ بهتر، «الهام» فقط از مجوزِ آزاد، مارک‌داونِ خامِ کتابخانه؛
* پیشنهادِ AI برای متنِ فارسی (قیمت، پرسش، منو … و حوزهٔ کار)؛ * خوانایی (تباین) در سبک‌ها: پالتِ بااحتیاط، متنِ روی گرادیان، نشانِ هیرو، --brand-fg.
شبکه و مرورگر واقعی صدا زده نمی‌شوند (همه تزریق‌پذیرند)؛ اندازه‌گیریِ مرورگری در browser_checks/check_text_contrast.py.
"""
import gzip
import io
import socket
import threading
import time
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase

from apps.projects.builder import (ai_context, c21_convert as CV, c21_crawl as CR, c21_embed as EM, c21_net as NET, c21_rtl, c21_source as SRC, c21st, styles as S, theme as T)
from apps.projects.builder.styles import harden as H
from apps.projects.builder.styles.gen_core import contrast
from apps.projects.tests_builder import Base
from apps.projects.tests_c21x import DataDirMixin, FakeNode, ROBOTS_21ST, session
from services import safenet


# ───────────────────────────── c21_net: اتصالِ هم‌زمانِ چندتایی و Keep-Alive

class RaceConnectTests(SimpleTestCase):
    def test_the_first_successful_connection_wins_and_the_rest_are_closed(self):
        made, lock = [], threading.Lock()

        class Sock:
            def __init__(self, ip):
                self.ip, self.closed = ip, False

            def close(self):
                self.closed = True

        def connect(addr, timeout=None):
            ip = addr[0]
            if ip == "10.0.0.2":                          # نشانیِ بسته (از ایران: اتصال نمی‌شود)
                raise OSError("timed out")
            time.sleep(0.05 if ip == "1.1.1.1" else 0.0)
            s = Sock(ip)
            with lock:
                made.append(s)
            return s
        got = NET._race_connect(["10.0.0.2", "1.1.1.1"], 443, parallel=6, timeout=1.0, rounds=2, deadline=time.monotonic() + 5, connect=connect)
        self.assertIsNotNone(got)
        self.assertEqual(got.ip, "1.1.1.1")
        time.sleep(0.4)                                  # بقیهٔ اتصال‌های موفق (دیرتر) بسته می‌شوند، نه نشت
        self.assertFalse(got.closed)
        self.assertTrue(all(s.closed for s in made if s is not got))

    def test_every_attempt_failing_gives_up_inside_the_deadline(self):
        def connect(addr, timeout=None):
            raise OSError("unreachable")
        t0 = time.monotonic()
        self.assertIsNone(NET._race_connect(["1.1.1.1"], 443, parallel=3, timeout=0.2, rounds=3, deadline=t0 + 2.0, connect=connect))
        self.assertLess(time.monotonic() - t0, 2.5)


class FakeHttp:
    """http.client.HTTPSConnection ِ ساختگی: پاسخ‌های از پیش‌تعیین‌شده؛ lost=True ⇒ اتصالِ کهنه (قطع شده)."""

    def __init__(self, replies, lost=False):
        self.replies, self.lost, self.requests, self.closed = list(replies), lost, [], False

    def request(self, method, path, headers=None):
        if self.lost:
            import http.client
            raise http.client.RemoteDisconnected("closed by peer")
        self.requests.append((method, path))

    def getresponse(self):
        status, headers, body = self.replies.pop(0)
        outer = self

        class Resp:
            def __init__(self):
                self.status = status
                self.will_close = False
                self._buf = io.BytesIO(body)

            def read(self, n=-1):
                return self._buf.read(n)

            def getheaders(self):
                return list(headers.items())
        outer.last = Resp()
        return outer.last

    def close(self):
        self.closed = True


class KeepAliveGetTests(SimpleTestCase):
    def setUp(self):
        NET.reset()
        self.addCleanup(NET.reset)
        self.resolver = lambda host, port: ["216.150.1.65", "216.150.16.65"]

    def install(self, http):
        """_Conn.open ⇒ ساختگی: به جای اتصالِ واقعی، http ِ ساختگی را می‌گذارد؛ تعدادِ بازشدن‌ها را می‌شمارد."""
        opens = []

        def fake_open(conn, addresses, deadline, connect_race=None):
            opens.append(list(addresses))
            conn.http = http() if callable(http) else http
            conn.used_at = time.monotonic()
        return mock.patch.object(NET._Conn, "open", fake_open), opens

    def test_one_connection_serves_many_requests_and_all_addresses_are_offered(self):
        http = FakeHttp([(200, {"content-type": "text/plain"}, b"A"), (200, {"content-type": "text/plain"}, b"B"), (200, {"content-type": "text/plain"}, b"C")])
        patch, opens = self.install(http)
        with patch:
            out = [NET.get("https://21st.dev/x%d" % i, resolver=self.resolver).text for i in range(3)]
        self.assertEqual(out, ["A", "B", "C"])
        self.assertEqual(len(opens), 1, "Keep-Alive: فقط یک اتصال")
        self.assertEqual(opens[0], ["216.150.1.65", "216.150.16.65"], "هم‌زمان به همهٔ نشانی‌ها")
        self.assertEqual([r[1] for r in http.requests], ["/x0", "/x1", "/x2"])

    def test_a_stale_connection_is_replaced_once_and_the_request_is_repeated(self):
        stale = FakeHttp([], lost=True)
        fresh = FakeHttp([(200, {"content-type": "text/plain"}, b"ok")])
        seq = iter([fresh])
        patch, opens = self.install(lambda: next(seq))
        with patch:
            first = NET._conns.setdefault("21st.dev", NET._Conn("21st.dev"))
            first.http, first.used_at = stale, time.monotonic()                  # اتصالِ کهنهٔ نگه‌داشته‌شده
            self.assertEqual(NET.get("https://21st.dev/y", resolver=self.resolver).text, "ok")
        self.assertEqual(len(opens), 1)
        self.assertTrue(stale.closed)

    def test_errors_use_the_same_codes_as_safenet(self):
        http = FakeHttp([(404, {}, b""), (429, {"retry-after": "5"}, b""), (500, {}, b"")])
        patch, _ = self.install(http)
        with patch:
            for code in ("http_404", "http_429", "http_500"):
                with self.assertRaises(safenet.FetchError) as cm:
                    NET.get("https://21st.dev/z", resolver=self.resolver)
                self.assertEqual(cm.exception.code, code)

    def test_gzip_is_decoded_and_the_size_cap_holds(self):
        raw = b"x" * 5000
        gz = gzip.compress(raw)
        http = FakeHttp([(200, {"content-encoding": "gzip", "content-type": "text/plain"}, gz), (200, {"content-encoding": "gzip", "content-type": "text/plain"}, gz)])
        patch, _ = self.install(http)
        with patch:
            self.assertEqual(NET.get("https://21st.dev/g", resolver=self.resolver, max_bytes=10_000).body, raw)
            with self.assertRaises(safenet.FetchError) as cm:
                NET.get("https://21st.dev/g", resolver=self.resolver, max_bytes=1000)
        self.assertEqual(cm.exception.code, "too_large")

    def test_private_addresses_are_refused_and_other_hosts_use_safenet(self):
        with self.assertRaises(safenet.FetchError) as cm:
            NET.get("https://21st.dev/p", resolver=lambda h, p: ["10.1.2.3"])
        self.assertEqual(cm.exception.code, "ssrf")
        sentinel = safenet.Fetched(url="u", status=200, content_type="text/plain", body=b"via-safenet")
        with mock.patch.object(safenet, "get", return_value=sentinel) as g:
            self.assertEqual(NET.get("https://raw.githubusercontent.com/a/b/c.md").body, b"via-safenet")
            self.assertEqual(NET.get("http://21st.dev/plain").body, b"via-safenet")        # http ⇒ همان مسیرِ امنِ قدیمی
        self.assertEqual(g.call_count, 2)

    def test_redirect_to_the_same_host_is_followed_and_to_another_host_leaves_to_safenet(self):
        http = FakeHttp([(301, {"location": "/new"}, b""), (200, {"content-type": "text/plain"}, b"moved")])
        patch, _ = self.install(http)
        with patch:
            self.assertEqual(NET.get("https://21st.dev/old", resolver=self.resolver).text, "moved")
        NET.reset()
        http2 = FakeHttp([(302, {"location": "https://github.com/x"}, b"")])
        patch2, _ = self.install(http2)
        sentinel = safenet.Fetched(url="u", status=200, content_type="text/plain", body=b"gh")
        with patch2, mock.patch.object(safenet, "get", return_value=sentinel):
            self.assertEqual(NET.get("https://21st.dev/away", resolver=self.resolver).body, b"gh")

    def test_connection_failure_is_a_connect_error_not_a_crash(self):
        with mock.patch.object(NET, "_race_connect", return_value=None):
            with self.assertRaises(safenet.FetchError) as cm:
                NET.get("https://21st.dev/none", resolver=self.resolver)
        self.assertEqual(cm.exception.code, "connect")

    def test_the_crawler_uses_the_persistent_fetcher_by_default(self):
        self.assertIs(CR.Session().fetch, NET.get)


# ───────────────────────────── robots.txt روی دیسک و نوبتِ بی‌پیشرفت

class RobotsCacheTests(DataDirMixin, SimpleTestCase):
    def failing(self, code="timeout"):
        calls = []

        def fetch(url, **kw):
            calls.append(url)
            raise safenet.FetchError("x", code)
        fetch.calls = calls
        return fetch

    def test_a_fresh_copy_on_disk_means_no_request_and_a_good_read_is_saved(self):
        sl = []
        s1 = CR.Session(fetch=lambda url, **kw: safenet.Fetched(url=url, status=200, content_type="text/plain", body=ROBOTS_21ST.encode()), sleep=sl.append, robots_cache=True)
        self.assertTrue(s1.load_robots().ok)
        self.assertTrue(CR.Session.robots_cache_path().is_file())
        fail = self.failing()
        s2 = CR.Session(fetch=fail, sleep=sl.append, robots_cache=True)
        self.assertTrue(s2.load_robots().allowed("https://21st.dev/community/components/s/hero.md"))
        self.assertEqual(fail.calls, [])

    def test_an_unreadable_robots_falls_back_to_the_stale_copy_up_to_a_week(self):
        p = CR.Session.robots_cache_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(ROBOTS_21ST, encoding="utf-8")
        old = time.time() - 3 * 24 * 3600
        import os
        os.utime(p, (old, old))
        fail = self.failing()
        s = CR.Session(fetch=fail, sleep=lambda x: None, robots_cache=True)
        r = s.load_robots()
        self.assertTrue(r.ok)
        self.assertFalse(r.allowed("https://21st.dev/api/x"), "قاعده‌های ذخیره‌شده همچنان اعمال می‌شوند")
        self.assertGreaterEqual(len(fail.calls), 1)
        too_old = time.time() - 9 * 24 * 3600
        os.utime(p, (too_old, too_old))
        s2 = CR.Session(fetch=self.failing(), sleep=lambda x: None, robots_cache=True)
        self.assertFalse(s2.load_robots().ok, "نسخهٔ خیلی کهنه ⇒ محتاطانه ممنوع")

    def test_cache_is_off_by_default_so_other_callers_and_tests_are_unchanged(self):
        p = CR.Session.robots_cache_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(ROBOTS_21ST, encoding="utf-8")
        s = CR.Session(fetch=self.failing(), sleep=lambda x: None)
        self.assertFalse(s.load_robots().ok)


class ProgressAndNodeTests(DataDirMixin, Base):
    def test_needs_node_for_403_unreadable_robots_or_stalled_turns_but_not_when_done(self):
        self.assertFalse(CR.needs_node({}))
        self.assertTrue(CR.needs_node({"blocked": True}))
        self.assertTrue(CR.needs_node({"robots_ok": False}))
        self.assertFalse(CR.needs_node({"robots_ok": True, "idle_turns": 2}))
        self.assertTrue(CR.needs_node({"robots_ok": True, "idle_turns": CR.STALL_TURNS}))
        self.assertFalse(CR.needs_node({"robots_ok": False, "finished": True}))

    def test_turns_without_progress_count_up_and_progress_resets_the_counter(self):
        c21st.save([{"id": "acme/a", "title": "A", "detail": False, "cats": []}])
        dead = session({"/sitemap.xml": safenet.FetchError("x", "timeout")})                       # نقشهٔ سایت و بقیه نمی‌آید
        dead.fetch.routes.update({"/community/components/s/hero.md": safenet.FetchError("x", "timeout")})
        for cat in CR.c21st.CATEGORIES:
            dead.fetch.routes["/community/components/s/%s.md" % cat] = safenet.FetchError("x", "timeout")
        dead.fetch.routes["/@acme/components/a.md"] = safenet.FetchError("x", "timeout")
        st1 = CR.run_turn(session=dead, max_seconds=100.0, detail_limit=5)
        st2 = CR.run_turn(session=dead, max_seconds=100.0, detail_limit=5)
        self.assertEqual((st1["turn_progress"], st2["idle_turns"]), (0, 2))
        ok = session({"/@acme/components/a.md": "# A\n\n> About a.\n\n- License: mit\n- Tags: Hero\n"})
        for cat in CR.c21st.CATEGORIES:
            ok.fetch.routes["/community/components/s/%s.md" % cat] = "# C\n"
        ok.fetch.routes["/sitemap.xml"] = "<urlset></urlset>"
        st3 = CR.run_turn(session=ok, max_seconds=100.0, detail_limit=5)
        self.assertGreater(st3["turn_progress"], 0)
        self.assertEqual(st3["idle_turns"], 0)

    def test_the_refresh_task_hands_a_stalled_crawl_to_the_node(self):
        from apps.compute.models import ComputeNode
        from apps.projects import tasks as TK
        from apps.projects.builder import c21_node as ND
        c21st.save([{"id": "acme/hero-%d" % i, "title": "Hero %d" % i, "detail": False, "cats": []} for i in range(60)])
        ComputeNode.objects.create(name="gpu", capabilities={"agent": "2.30", "kinds": ["echo", ND.KIND]})
        from apps.compute.models import ComputeJob
        with mock.patch.object(CR, "run_turn", return_value={"blocked": False, "robots_ok": True, "finished": False, "idle_turns": 3, "turn_progress": 0}), \
                mock.patch.object(TK.c21st_refresh, "apply_async") as again:
            out = TK.c21st_refresh(force=True)
        self.assertTrue(out["node"])
        self.assertEqual(ComputeJob.objects.filter(kind=ND.KIND).count(), 1)
        self.assertEqual(again.call_args.kwargs["countdown"], 600)
        with mock.patch.object(CR, "run_turn", return_value={"blocked": False, "robots_ok": True, "finished": False, "idle_turns": 0, "turn_progress": 90}), \
                mock.patch.object(TK.c21st_refresh, "apply_async") as again2:
            out = TK.c21st_refresh(force=True)
        self.assertFalse(out["node"])
        self.assertEqual(ComputeJob.objects.filter(kind=ND.KIND).count(), 1)
        self.assertEqual(again2.call_args.kwargs["countdown"], 30)


# ───────────────────────────── «خالیِ ایستا» و سرریزِ گوشی

def _png(path, color, boxes=()):
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (400, 200), color)
    d = ImageDraw.Draw(im)
    for b in boxes:
        d.rectangle(b, fill=(20, 20, 20))
    im.save(path)


class BlankComponentTests(DataDirMixin, Base):
    def convert(self, cid, title, cats):
        node = FakeNode()
        rec = CV.convert_bundle(cid, {"entry": {"path": "Usage.tsx", "code": "export default () => null"}, "files": {}, "aliases": {}, "roots": ["/r"],
                                      "source": {"kind": "upstream", "repo": "https://github.com/acme/ui", "license": "MIT"}},
                                meta={"title": title, "license": "mit", "author": "Acme", "library": "Acme UI", "cats": cats}, runner=node)
        CV.save_record(rec)
        rows = c21st.load() + [{"id": cid, "title": title, "detail": True, "usable": True, "license": "mit", "cats": cats, "conv": {"state": "ok", "key": rec["key"]}}]
        c21st.save(rows)
        return rec

    def fake_browser(self, shots):
        """subprocess.run ِ ساختگی برای rtl_check.py: به‌جای مرورگر، اسکرین‌شات‌ها و rtl.json را می‌نویسد. shots: key ⇒ (ink-color-boxes، status)."""
        def run(cmd, **kw):
            d = Path(cmd[2])
            res = {}
            asked = {f.stem for f in d.glob("*.html")}
            for key, (boxes, status, *extra) in shots.items():
                if key not in asked:
                    continue
                for w in (390, 1280):
                    _png(d / ("%s-%d.png" % (key, w)), (0xf7, 0xf8, 0xfa), boxes)
                res[key] = {"status": status, "overflow_390": status == "fail", "overflow_1280": False, "rtl": True, **(extra[0] if extra else {})}
            Path(cmd[3]).write_text(__import__("json").dumps(res), encoding="utf-8")
            return mock.Mock(returncode=0, stdout="", stderr="")
        return run

    def test_ink_counts_pixels_that_differ_from_the_page(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "a.png"
            _png(p, (0xf7, 0xf8, 0xfa))
            self.assertEqual(c21_rtl.ink_of(p), 0)
            _png(p, (0xf7, 0xf8, 0xfa), [(10, 10, 109, 59)])
            self.assertAlmostEqual(c21_rtl.ink_of(p), 100 * 50, delta=400)
            self.assertIsNone(c21_rtl.ink_of(Path(td) / "missing.png"))

    def test_a_component_that_renders_empty_is_hidden_like_an_overflowing_one(self):
        good = self.convert("acme/hero-one", "Hero One", ["hero"])
        empty = self.convert("acme/typing", "Typing Animation", ["text-animation"])
        wide = self.convert("acme/wide", "Wide Table", ["table"])
        run = self.fake_browser({good["key"]: ([(10, 10, 300, 120)], "ok"), empty["key"]: ([], "ok"), wide["key"]: ([(10, 10, 300, 120)], "fail")})
        with mock.patch.object(c21_rtl, "available", return_value=(True, "")):
            res = c21_rtl.apply([good["key"], empty["key"], wide["key"]], runner=run)
        self.assertEqual(res[good["key"]]["status"], "ok")
        self.assertEqual(res[empty["key"]]["status"], "fail")
        self.assertTrue(res[empty["key"]]["blank"])
        self.assertEqual(CV.load_record(empty["key"])["rtl"]["blank"], True)
        self.assertEqual(CV.load_index()["acme/typing"]["rtl"], "fail")
        rows = {r["id"]: r for r in c21st.load()}
        self.assertTrue(c21st.insertable(rows["acme/hero-one"]))
        self.assertFalse(c21st.insertable(rows["acme/typing"]), "خالیِ ایستا ⇒ درج‌شدنی نیست")
        self.assertFalse(c21st.insertable(rows["acme/wide"]))
        # و از پیشنهادِ AI و API ِ درج هم بسته است
        self.assertEqual(self.c.get("/api/v1/studio/c21st/block/%s/" % empty["key"]).status_code, 409)
        self.assertEqual(self.c.get("/api/v1/studio/c21st/block/%s/" % good["key"]).status_code, 200)

    def test_an_empty_frame_with_a_border_is_blank_too_but_text_or_a_field_is_content(self):
        frame = self.convert("acme/flicker", "Flickering Grid", ["background"])          # canvas ⇒ در HTMLِ ایستا فقط یک قابِ خالیِ دارای حاشیه می‌ماند
        field = self.convert("acme/area", "Textarea", ["form"])                           # فیلدِ ورودی: محتواست، هرچند متن ندارد
        words = self.convert("acme/words", "Words", ["hero"])
        box = [(10, 10, 300, 200)]                                                        # حاشیه/پس‌زمینه ⇒ «جوهر» کافی
        zero, one = {"text_390": 0, "text_1280": 0, "visual_390": 0, "visual_1280": 0}, {"text_390": 0, "text_1280": 0, "visual_390": 1, "visual_1280": 1}
        run = self.fake_browser({frame["key"]: (box, "ok", zero), field["key"]: (box, "ok", one), words["key"]: (box, "ok", {"text_390": 40, "text_1280": 40, "visual_390": 0, "visual_1280": 0})})
        with mock.patch.object(c21_rtl, "available", return_value=(True, "")):
            res = c21_rtl.apply([frame["key"], field["key"], words["key"]], runner=run)
        self.assertEqual((res[frame["key"]]["status"], res[frame["key"]].get("blank")), ("fail", True))
        self.assertEqual(res[field["key"]]["status"], "ok")
        self.assertEqual(res[words["key"]]["status"], "ok")
        self.assertEqual(CV.load_record(frame["key"])["rtl"]["v"], c21_rtl.CHECK_VERSION)
        self.assertEqual(CV.load_index()["acme/flicker"]["rtl"], "fail")

    def test_a_stale_catalog_row_cannot_bring_back_a_failed_component(self):
        """خزش ردیفِ کاتالوگ را با نسخهٔ کهنه بازنویسی می‌کند؛ «fail» در converted/index.json می‌ماند و درج را بسته نگه می‌دارد."""
        rec = self.convert("acme/typing", "Typing Animation", ["text-animation"])
        rows = c21st.load()
        self.assertTrue(c21st.insertable(rows[0]))
        rec["rtl"] = {"status": "fail", "blank": True}
        CV.save_record(rec)                                         # ردیفِ کاتالوگ هنوز conv.rtl ندارد (نسخهٔ کهنه)
        self.assertNotIn("rtl", (rows[0].get("conv") or {}))
        self.assertFalse(c21st.insertable(rows[0]))
        self.assertEqual(c21st.search("typing", insertable_only=True)["total"], 0)

    def test_outdated_checks_are_repeated_automatically_in_batches(self):
        a = self.convert("acme/a", "A", ["hero"])
        b = self.convert("acme/b", "B", ["hero"])
        self.assertEqual(set(c21_rtl.outdated_keys()), {a["key"], b["key"]})
        run = self.fake_browser({a["key"]: ([(10, 10, 300, 120)], "ok"), b["key"]: ([(10, 10, 300, 120)], "ok")})
        with mock.patch.object(c21_rtl, "available", return_value=(True, "")):
            out = c21_rtl.recheck_outdated(limit=1, runner=run)
            self.assertEqual((out["checked"], out["left"]), (1, 1))
            out = c21_rtl.recheck_outdated(limit=5, runner=run)
            self.assertEqual((out["checked"], out["left"]), (1, 0))
        self.assertEqual(c21_rtl.outdated_keys(), [])
        with mock.patch.object(c21_rtl, "available", return_value=(False, "no browser")):
            self.assertEqual(c21_rtl.recheck_outdated()["left"], -1)                       # مرورگر نبود ⇒ کاری نمی‌کند

    def test_free_preview_and_block_endpoints_for_the_design_studio(self):
        rec = self.convert("acme/hero-one", "Hero One", ["hero"])
        d = self.c.get("/api/v1/studio/c21st/preview/%s/" % rec["key"]).json()
        self.assertIn("<html", d["doc"])
        self.assertIn(rec["scope"], d["doc"])
        self.assertEqual(d["license"], "mit")
        b = self.c.get("/api/v1/studio/c21st/block/%s/" % rec["key"]).json()
        self.assertEqual(b["block"]["type"], "c21")
        self.assertEqual(b["block"]["props"]["ref"], rec["key"])
        self.assertEqual(self.c.get("/api/v1/studio/c21st/block/x000000000/").status_code, 404)
        from rest_framework.test import APIClient
        self.assertIn(APIClient().get("/api/v1/studio/c21st/block/%s/" % rec["key"]).status_code, (401, 403))


# ───────────────────────────── حقِ نشر، دسته‌ها، الهام، کتابخانه

APACHE = ('Apache License\nVersion 2.0\n"Licensor" shall mean the copyright owner or entity authorized by\nthe copyright owner that is granting the License.\n'
          'APPENDIX: How to apply\n   Copyright [yyyy] [name of copyright owner]\n   Licensed under the Apache License, Version 2.0 (the "License");\n')


class AttributionTests(DataDirMixin, SimpleTestCase):
    def test_only_a_real_copyright_line_counts(self):
        self.assertEqual(SRC.find_copyright("MIT License\n\nCopyright (c) 2024 Dillion Verma\n\nPermission"), "Copyright (c) 2024 Dillion Verma")
        self.assertEqual(SRC.find_copyright("Copyright 2021 Arihant Codes"), "Copyright 2021 Arihant Codes")
        self.assertEqual(SRC.find_copyright("Copyright © 2023-2025 Some Org, Inc."), "Copyright © 2023-2025 Some Org, Inc.")
        self.assertEqual(SRC.find_copyright(APACHE), "", "متنِ خودِ Apache و جای‌نگهدارِ پیوست حقِ نشرِ کسی نیست")

    def test_detect_license_skips_the_apache_boilerplate(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "LICENSE").write_text(APACHE + "\nlicensed under the Apache License, Version 2.0\n", encoding="utf-8")
            self.assertEqual(SRC.detect_license(Path(td))["copyright"], "")

    def test_a_missing_or_bogus_line_becomes_the_repo_holder_not_license_text(self):
        bogus = '"Licensor" shall mean the copyright owner or entity authorized by'
        out = SRC.clean_copyright(bogus, "https://github.com/arihantcodes/accordion-generative")
        self.assertIn("arihantcodes/accordion-generative", out)
        self.assertNotIn("Licensor", out)
        self.assertEqual(SRC.clean_copyright("", "https://github.com/a/b.git"), "Copyright (c) a/b contributors (the licence file names no holder)")
        self.assertEqual(SRC.clean_copyright("Copyright (c) 2025 Acme", "https://github.com/a/b"), "Copyright (c) 2025 Acme")
        self.assertEqual(SRC.clean_copyright("", ""), "")

    def test_stored_records_are_repaired_and_the_inserted_comment_is_clean(self):
        node = FakeNode()
        rec = CV.convert_bundle("acme/acc", {"entry": {"path": "U.tsx", "code": "x"}, "files": {}, "aliases": {}, "roots": [],
                                             "source": {"kind": "upstream", "repo": "https://github.com/acme/acc", "license": "Apache-2.0",
                                                        "copyright": '"Licensor" shall mean the copyright owner or entity authorized by'}},
                                meta={"title": "Acc", "license": "apache-2.0", "author": "Acme", "library": "Acme", "cats": []}, runner=node)
        CV.save_record(rec)
        self.assertNotIn("Licensor", EM.attribution(CV.load_record(rec["key"])), "حتی پیش از ترمیمِ داده، نشانِ خروجی درست است")
        out = CV.repair_attribution()
        self.assertEqual(out["fixed"], 1)
        self.assertIn("acme/acc contributors", CV.load_record(rec["key"])["source"]["copyright"])
        self.assertEqual(CV.repair_attribution()["fixed"], 0)


class CategoryAndLicenceFilterTests(DataDirMixin, SimpleTestCase):
    def test_tags_and_title_words_now_give_every_component_a_category(self):
        self.assertIn("login", CR.infer_cats({"id": "a/account-access-card", "title": "Account Access Card", "tags": ["Login Form"]}))
        self.assertIn("form", CR.infer_cats({"id": "a/dual-range-slider", "title": "Dual Range Slider", "tags": ["Slider"]}))
        self.assertIn("navigation", CR.infer_cats({"id": "a/toolbar", "title": "Expandable Action Bar", "tags": ["Toolbar", "Motion"]}))
        self.assertIn("accordion", CR.infer_cats({"id": "a/faq-5", "title": "Faq 5", "tags": []}))
        self.assertNotIn("form", CR.infer_cats({"id": "a/transform-card", "title": "Transform Card", "tags": []}), "«transform» توکنِ form نیست")
        self.assertEqual(CR.infer_cats({"id": "a/x", "title": "X", "tags": [], "cats": ["hero"]})[0], "hero", "دسته‌های قبلی و ترتیبشان حفظ می‌شود")

    def test_recategorize_catalog_and_records_only_adds(self):
        c21st.save([{"id": "acme/slider-pro", "title": "Slider Pro", "detail": True, "tags": ["Slider"], "cats": []},
                    {"id": "acme/hero-one", "title": "Hero One", "detail": True, "tags": ["Hero"], "cats": ["hero"]}, {"id": "acme/new", "title": "New", "detail": False, "cats": []}])
        out = CR.recategorize_catalog()
        self.assertEqual(out["changed"], 1)
        rows = {r["id"]: r for r in c21st.load()}
        self.assertIn("form", rows["acme/slider-pro"]["cats"])
        self.assertEqual(rows["acme/new"]["cats"], [])
        node = FakeNode()
        rec = CV.convert_bundle("acme/slider-pro", {"entry": {"path": "U.tsx", "code": "x"}, "files": {}, "aliases": {}, "roots": [], "source": {}},
                                meta={"title": "Slider Pro", "license": "mit", "author": "A", "library": "L", "cats": []}, runner=node)
        CV.save_record(rec)
        self.assertEqual(CV.recategorize_records()["changed"], 1)
        self.assertIn("form", CV.load_record(rec["key"])["cats"])
        self.assertEqual(CV.load_index()["acme/slider-pro"]["cats"], ["form"])

    def test_a_crawl_turn_also_gives_old_rows_their_new_categories(self):
        c21st.save([{"id": "acme/slider-pro", "title": "Slider Pro", "detail": True, "usable": True, "tags": ["Slider"], "cats": [], "lib_known": False}])
        s = session({"/sitemap.xml": "<urlset></urlset>"})
        for cat in c21st.CATEGORIES:
            s.fetch.routes["/community/components/s/%s.md" % cat] = "# C\n"
        CR.run_turn(session=s, max_seconds=100.0, detail_limit=1)
        self.assertIn("form", {r["id"]: r for r in c21st.load()}["acme/slider-pro"]["cats"])

    def test_library_markdown_is_shown_as_the_plain_name(self):
        self.assertEqual(c21st.link_text("[Spectrum UI](https://21st.dev/@x/library/spectrum-ui)"), "Spectrum UI")
        self.assertEqual(c21st.link_text("Plain"), "Plain")
        self.assertEqual(c21st.link_text(""), "")
        d = c21st.parse_component_md("# T\n\n- Library: [Spectrum UI](https://21st.dev/@x/library/spectrum-ui)\n- License: mit\n")
        self.assertEqual(d["library"], "Spectrum UI")
        c21st.save([{"id": "a/b", "title": "T", "library": "[Old UI](https://21st.dev/@x/library/old)", "detail": True}])
        self.assertEqual(c21st.search("T")["items"][0]["library"], "Old UI")

    def test_inspiration_and_picks_only_come_from_open_licences(self):
        c21st.save([{"id": "a/open", "title": "Open", "detail": True, "usable": True, "license": "mit", "tags": ["Hero"], "description": "d"},
                    {"id": "a/closed", "title": "Closed", "detail": True, "usable": False, "license": "no-license", "tags": ["Hero"], "description": "secret"},
                    {"id": "a/unchecked", "title": "Unchecked", "detail": False}])
        self.assertEqual([r["id"] for r in c21st.inspiration_for(["a/open", "a/closed", "a/unchecked", "a/none"])], ["a/open"])
        self.assertEqual(c21st.valid_ids(["a/open", "a/closed", "a/unchecked"]), ["a/open"])
        p = ai_context.build("bento-grid", "اپ ورزشی", "home", (), refs21=["a/closed", "a/open"])
        self.assertEqual([i["id"] for i in p.get("inspiration", [])], ["a/open"])
        self.assertNotIn("secret", str(p))


# ───────────────────────────── پیشنهادِ AI برای متنِ فارسی

class PersianBriefTests(DataDirMixin, SimpleTestCase):
    def seed(self):
        node = FakeNode()
        keys = {}
        for cid, title, cats in (("acme/compare", "Comparison 03", ["pricing-section"]), ("acme/faq-tabs", "Faq Tabs Card", ["accordion"]), ("acme/hero-glow", "Hero Glow", ["hero"]),
                                 ("acme/shop-cards", "Product Cards", ["card"]), ("acme/sparkles", "Sparkles Text", ["text-animation", "hero"]), ("acme/nav", "Navbar Dock", ["navigation"])):
            rec = CV.convert_bundle(cid, {"entry": {"path": "U.tsx", "code": "x"}, "files": {}, "aliases": {}, "roots": [], "source": {}},
                                    meta={"title": title, "license": "mit", "author": "A", "library": "L", "cats": cats}, runner=node)
            CV.save_record(rec)
            keys[cid] = rec["key"]
        rec = CV.load_record(keys["acme/sparkles"])
        rec["rtl"] = {"status": "fail", "blank": True}
        CV.save_record(rec)
        return keys

    def test_persian_section_words_pick_the_matching_components(self):
        self.seed()
        ids = lambda b, kind="landing": [x["id"] for x in ai_context.c21_suggest(b, kind)]            # noqa: E731
        self.assertEqual(ids("صفحه قیمت‌گذاری با تاگل ماهانه و سالانه")[0], "acme/compare")
        self.assertEqual(ids("پرسش‌های پرتکرار")[0], "acme/faq-tabs")
        self.assertEqual(ids("فروشگاه لوازم ورزشی")[0], "acme/shop-cards")
        self.assertEqual(ids("منو و ناوبری سایت")[0], "acme/nav")
        both = ids("قیمت و پرسش‌های پرتکرار")
        self.assertEqual(set(both), {"acme/compare", "acme/faq-tabs"}, "هر بخشِ خواسته‌شده نماینده‌ی خودش را می‌گیرد")
        for b in ("صفحه قیمت", "پرسش", "فروشگاه", "کلینیک دندان", "نرم‌افزار"):
            self.assertNotIn("acme/sparkles", ids(b), "قطعهٔ خالیِ ایستا هرگز پیشنهاد نمی‌شود")

    def test_english_briefs_still_work(self):
        self.seed()
        self.assertEqual(ai_context.c21_suggest("faq accordion", "landing")[0]["id"], "acme/faq-tabs")
        self.assertEqual(ai_context.c21_suggest("pricing table with monthly yearly toggle", "landing")[0]["id"], "acme/compare")

    def test_keywords_match_tokens_not_the_middle_of_words(self):
        self.assertEqual([e for _p, _fa, e in ai_context.domain_matches("صفحه قیمت‌گذاری با تاگل ماهانه")], [], "«گل» داخلِ «تاگل» نیست")
        self.assertEqual([e for _p, _fa, e in ai_context.domain_matches("گل فروشی")][0], "florist plant")
        self.assertIn("e-commerce shop store", [e for _p, _fa, e in ai_context.domain_matches("فروشگاهی برای لوازم ورزشی")])
        self.assertEqual(ai_context.domain_matches("فروشگاه لوازم ورزشی")[0][2], "e-commerce shop store", "واژهٔ اولِ متن سرِ موضوع است")
        self.assertEqual(ai_context.domain_matches("مدیریت پروژه"), [], "«مد» (کوتاه) فقط کاملِ توکن")
        self.assertEqual(ai_context.section_intents("قیمت و پرسش‌های پرتکرار", implied=False), ["pricing", "faq"])
        self.assertEqual(ai_context.section_intents("کلینیک دندان")[:3], ["testimonials", "faq", "contact"], "حوزه ⇒ بخش‌های معمولِ آن")

    def test_product_row_follows_the_head_noun_and_section_only_briefs_get_none(self):
        hints = lambda b: ai_context.uiux_hints(b, "landing").get("product", {}).get("type", "")      # noqa: E731
        self.assertEqual(hints("فروشگاه لوازم ورزشی"), "E-commerce")
        self.assertEqual(hints("باشگاه ورزشی"), "Fitness/Gym App")
        self.assertEqual(hints("صفحه قیمت‌گذاری با تاگل ماهانه و سالانه"), "")
        self.assertEqual(hints("پرسش‌های پرتکرار"), "")
        self.assertIn("Medical", hints("کلینیک دندان"))

    def test_own_components_follow_the_sections_the_brief_asks_for(self):
        pick = lambda b: ai_context.pick_components(b, "", "home", limit=5)                              # noqa: E731
        cats = lambda keys: [ai_context.comps.COMPONENTS[k]["cat"] for k in keys]                       # noqa: E731
        self.assertEqual(cats(pick("صفحه قیمت‌گذاری"))[0], "pricing")
        self.assertEqual(cats(pick("پرسش‌های پرتکرار"))[0], "faq")
        self.assertNotEqual(cats(pick("فروشگاه")), cats(pick("کلینیک دندان")))


# ───────────────────────────── خوانایی (تباین)

class ReadabilityTests(SimpleTestCase):
    def test_every_style_palette_keeps_a_safety_margin(self):
        for key, st in S.STYLES.items():
            c = st["theme"]["colors"]
            for bg in (c["bg"], c["surface"]):
                self.assertGreaterEqual(contrast(c["text"], bg), 6.9, key)
                self.assertGreaterEqual(contrast(c["text2"], bg), 6.2, key)
                self.assertGreaterEqual(contrast(c["muted"], bg), 5.5, key)

    def test_hero_and_cta_text_reads_on_every_gradient_stop_with_the_real_brand_too(self):
        for brand in ("#126f85", "#c2410c", "#f5c542"):
            for key, st in S.STYLES.items():
                toks = {k: S.css.rebrand_text(v, st["theme"]["colors"]["primary"]) for k, v in S.tokens_of(key).items()}
                g = H.guard_surface_fg(toks, brand, st["theme"]["colors"]["bg"])
                for bg_key, fg_key in (("hero_bg", "hero_fg"), ("cta_bg", "cta_fg")):
                    stops = H.stops_of(g[bg_key], brand, st["theme"]["colors"]["bg"], boost=1.7)
                    fg = g[fg_key]
                    if not stops or not fg.startswith("#"):
                        continue
                    worst = min(contrast(H._full(fg), s) for s in stops)
                    # گرادیان‌های چندلایهٔ نیمه‌شفاف با پرده هم ≥ ۴٫۵ می‌مانند (حاشیهٔ ۵٫۶ برای opacity)
                    self.assertGreaterEqual(worst, 4.5, "%s/%s %s" % (key, brand, bg_key))

    def test_eyebrow_text_gets_its_own_readable_colour(self):
        t = {"hero_bg": "linear-gradient(135deg,#1d4ed8,#0b2a6f)", "hero_fg": "#ffffff", "eb_bg": "rgba(255,255,255,.92)"}
        g = H.guard_surface_fg(t, "#1d4ed8", "#ffffff")
        self.assertEqual(g["eb_fg"], H.DARK_INK, "نشانِ سفیدِ مات روی هیرویِ تیره: متنِ تیره")
        t2 = {"hero_bg": "linear-gradient(135deg,#1d4ed8,#0b2a6f)", "hero_fg": "#ffffff", "eb_bg": "color-mix(in srgb,currentColor 15%,transparent)"}
        self.assertNotIn("eb_fg", H.guard_surface_fg(t2, "#1d4ed8", "#ffffff"), "currentColor ⇒ همان رنگِ هیرو")
        t3 = {"hero_bg": "#111111", "hero_fg": "#ffffff", "eb_bg": "#ffd23f"}
        self.assertEqual(H.guard_surface_fg(t3, "#111111", "#fff")["eb_fg"], H.DARK_INK)
        self.assertIn("--st-eb-fg", S.style_css("neo-brutalism"))
        self.assertIn("color:var(--st-eb-fg)", S.css.CORE)

    def test_mid_tone_gradients_get_a_scrim_instead_of_unreadable_text(self):
        toks = {"hero_bg": "linear-gradient(135deg,#7da86a,#4d8a52)", "hero_fg": "#ffffff", "cta_bg": "linear-gradient(135deg,#7da86a,#4d8a52)", "cta_fg": "#ffffff"}
        g = H.guard_surface_fg(toks, "#126f85", "#ffffff")
        self.assertTrue(g["hero_bg"].startswith("linear-gradient(rgba("), g["hero_bg"])
        stops = H.stops_of(g["hero_bg"], "#126f85", "#ffffff")
        self.assertGreaterEqual(len(stops), 2)
        solid = {"hero_bg": "#0b2a6f", "hero_fg": "#ffffff"}
        self.assertEqual(H.guard_surface_fg(solid, "#0b2a6f", "#fff")["hero_bg"], "#0b2a6f", "خواناست ⇒ دست نمی‌خورد")

    def test_brand_fg_is_emitted_and_reads_on_light_and_dark_pages(self):
        for key in ("minimalism", "ux-vaporwave", "dark-luxury", "ux-terminal-cli-mobile"):
            th = T.clean_theme(S.apply_to_theme(T.default_theme(), key, keep_brand=True, project_brand="#126f85"))
            zone = T.colors_zone(th)
            fg = zone.split("--brand-fg:")[1].split(";")[0].strip()
            c = th["colors"]
            self.assertGreaterEqual(contrast(fg, c["bg"]), 6.0, key)
            self.assertGreaterEqual(contrast(fg, c["surface"]), 6.0, key)
        light = T.default_theme()
        self.assertIn("--brand-fg: ", T.colors_zone(light))

    def test_text_that_used_to_be_dimmed_by_opacity_keeps_a_margin(self):
        from apps.projects.builder import blocks_css
        self.assertIn(".nb-sub{font-size:1.06rem;line-height:1.95;margin:0;opacity:.92}", blocks_css.BLOCK_CSS)
        self.assertIn(".nb-hero .nb-sub,.nb-cta-box .nb-sub{opacity:1}", blocks_css.BLOCK_CSS, "روی هیرو/دعوت (سطحِ رنگی) متن کم‌رنگ نمی‌شود")
        self.assertNotIn("opacity:.8}", blocks_css.BLOCK_CSS.split(".nb-sub{")[1].split("}")[0] + "}")
        # متنِ برند روی کارت/زمینه از var(--brand-fg) می‌آید، نه خودِ رنگِ برند
        self.assertIn("color:var(--brand-fg,var(--brand))", blocks_css.BLOCK_CSS)
        from apps.projects.builder.components import lib_hero
        self.assertIn(".nbc-hcg .nbc-pill{margin-bottom:18px;color:var(--brand-fg,var(--brand));background:color-mix(in srgb,var(--brand) 12%,var(--card,#fff))}",
                      open(lib_hero.__file__, encoding="utf-8").read())

    def test_every_style_still_renders_and_the_css_stays_logical_rtl(self):
        for key in S.ORDER:
            for brand in (None, "#126f85"):
                css = S.style_css(key, rebrand=bool(brand), brand=brand)
                self.assertEqual(css.count("{"), css.count("}"), key)
                self.assertNotIn("@import", css)


# ───────────────────────────── آمارِ تبدیل: «بدونِ کدِ عمومی» با «در انتظار» قاطی نمی‌شود

class PipelineStatsTests(DataDirMixin, SimpleTestCase):
    def test_components_of_libraries_without_a_public_repo_count_as_no_source_not_as_waiting(self):
        from apps.projects import c21_api

        def row(cid, lib="", conv=None, usable=True):
            r = {"id": cid, "title": cid, "author_name": "", "cats": [], "detail": True, "usable": usable, "license": "mit", "library_id": lib}
            if conv:
                r["conv"] = {"state": conv}
            return r
        c21st.save([row("a/one", "acme/ui"), row("a/two", "acme/ui", "ok"), row("b/lone"), row("b/gone", "nogit/ui"), row("c/tried", "acme/ui", "no-source"),
                    row("d/closed", "acme/ui", usable=False), row("e/lic", "acme/ui", "license")])
        CR.save_libs({"acme/ui": {"id": "acme/ui", "github": "https://github.com/acme/ui"}, "nogit/ui": {"id": "nogit/ui", "github": ""}})
        st = c21_api.pipeline_json()
        self.assertEqual(st["converted"], 1)
        self.assertEqual(st["waiting"], 1, "فقط a/one: کتابخانه‌اش مخزن دارد و نوبتش نرسیده")
        self.assertEqual(st["no_source"], 3, "c/tried (امتحان شد) + b/lone (بی‌کتابخانه) + b/gone (کتابخانهٔ بی‌مخزن)")
        self.assertEqual(st["license_blocked"], 1)


class NodePickTests(DataDirMixin, SimpleTestCase):
    def test_the_node_only_fetches_what_could_still_be_converted(self):
        from apps.projects.builder import c21_node as ND

        def row(cid, lib="", conv=None, detail=True, usable=True):
            r = {"id": cid, "title": cid, "author_name": "", "cats": [], "detail": detail, "usable": usable, "license": "mit", "library_id": lib}
            if conv:
                r["conv"] = {"state": conv}
            return r
        c21st.save([row("a/new", "acme/ui"), row("a/failed", "acme/ui", "failed"), row("a/done", "acme/ui", "ok"), row("a/nosrc", "acme/ui", "no-source"), row("a/lic", "acme/ui", "license"),
                    row("b/norepo", "nogit/ui"), row("b/lone"), row("c/closed", "acme/ui", usable=False), row("d/nodetail", detail=False)])
        CR.save_libs({"acme/ui": {"id": "acme/ui", "github": "https://github.com/acme/ui"}, "nogit/ui": {"id": "nogit/ui", "github": ""}})
        self.assertEqual(ND.pick_ids(20), ["d/nodetail", "a/new", "a/failed"], "جزئیاتِ ناقص اول؛ بعد فقط قطعه‌های قابلِ تبدیل (مخزن دارند، تبدیل نشده‌اند، رد نشده‌اند)")
        ND.save_demo("a/new", {"file": "Usage.tsx", "code": "x"})
        self.assertEqual(ND.pick_ids(20), ["d/nodetail", "a/failed"])
