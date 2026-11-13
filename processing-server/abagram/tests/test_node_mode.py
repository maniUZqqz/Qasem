"""IGS_NODE_MODE (NMarketing node): the key is the only door; /api/trend/<page> answers with the trend fields only.
python tests/test_node_mode.py   (needs fastapi, httpx, playwright: the engine's own requirements)"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
TMP = tempfile.mkdtemp(prefix="igs-node-")
KEY = "k" * 48
os.environ.update(IGS_DATA=TMP, IGS_NODE_MODE="1", IGS_API_TOKEN=KEY, IGS_NO_BROWSER="1", IGS_AUTH="1")

from starlette.testclient import TestClient  # noqa: E402

import app as site  # noqa: E402
from nm_fixture import post, write_page  # noqa: E402

H = {"X-Igs": "1"}


class NodeModeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        write_page(TMP, "demo_fit_page", [post("N1", age_h=3), post("N2", age_h=9)])

    def client(self):
        return TestClient(site.app, base_url="http://127.0.0.1")

    def test_no_key_no_answer(self):
        c = self.client()
        self.assertEqual(c.get("/api/status").status_code, 401)
        self.assertEqual(c.get("/api/trend/demo_fit_page").status_code, 401)
        r = c.get("/")
        self.assertEqual(r.status_code, 401)
        self.assertIn("Open-Abagram.bat", r.text)

    def test_wrong_key_no_answer(self):
        c = self.client()
        self.assertEqual(c.get("/api/status", headers={"X-Igs-Token": "x" * 48}).status_code, 401)
        self.assertEqual(c.get("/?igs_key=" + "y" * 48, follow_redirects=False).status_code, 401)

    def test_agent_key_header_opens_the_api(self):
        c = self.client()
        r = c.get("/api/status", headers={"X-Igs-Token": KEY})
        self.assertEqual(r.status_code, 200)
        self.assertIn("state", r.json())

    def test_pairing_link_sets_a_cookie_that_opens_the_page_and_api(self):
        c = self.client()
        r = c.get("/?igs_key=" + KEY, follow_redirects=False)
        self.assertEqual(r.status_code, 303)
        cookie = r.headers.get("set-cookie", "")
        self.assertIn("igs_node=", cookie)
        self.assertIn("HttpOnly", cookie)
        self.assertNotIn(KEY, cookie)                      # the cookie is a derived value, never the key itself
        self.assertEqual(c.get("/api/auth/me").status_code, 200)
        self.assertEqual(c.get("/").status_code, 200)

    def test_post_still_needs_the_site_header(self):
        c = self.client()
        r = c.post("/api/cancel", headers={"X-Igs-Token": KEY})
        self.assertEqual(r.status_code, 403)
        r = c.post("/api/cancel", headers={"X-Igs-Token": KEY, **H})
        self.assertNotEqual(r.status_code, 403)

    def test_foreign_host_refused(self):
        c = TestClient(site.app, base_url="http://evil.example")
        self.assertEqual(c.get("/api/status", headers={"X-Igs-Token": KEY}).status_code, 403)

    def test_trend_endpoint(self):
        c = self.client()
        r = c.get("/api/trend/demo_fit_page?limit=1", headers={"X-Igs-Token": KEY})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual([p["code"] for p in body["posts"]], ["N1"])
        self.assertNotIn("followers_list", body)
        self.assertEqual(c.get("/api/trend/never_read", headers={"X-Igs-Token": KEY}).status_code, 404)
        self.assertEqual(c.get("/api/trend/bad%20name", headers={"X-Igs-Token": KEY}).status_code, 404)


class ShortKeyTests(unittest.TestCase):
    def test_a_short_key_is_no_key(self):
        old = site.API_TOKEN
        site.API_TOKEN = "short"
        try:
            c = TestClient(site.app, base_url="http://127.0.0.1")
            self.assertEqual(c.get("/api/status", headers={"X-Igs-Token": "short"}).status_code, 401)
            self.assertEqual(c.get("/?igs_key=short", follow_redirects=False).status_code, 401)
        finally:
            site.API_TOKEN = old


if __name__ == "__main__":
    unittest.main()
