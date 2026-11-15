"""«مرجع» برای ایده‌پردازیِ تامنیل (پینترست / پوسترِ فیلم / عکسِ خودتان): تحلیلِ رنگ و چیدمان، گرفتنِ امنِ تصویر، پوسترهای آزادِ کامنز، API.

هیچ‌جا شبکهٔ واقعی صدا زده نمی‌شود: ``fetch`` تزریق می‌شود. تصویرها ساختگی‌اند (گرادیان و شکل)، نه پوسترِ واقعی.
"""
import io
import json
import shutil
import tempfile
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase, override_settings
from PIL import Image, ImageDraw

from services import safenet

from . import references
from .tests_api import ThumbsApiBase, png_file


def poster(kind="cinema", size=(400, 600)) -> Image.Image:
    """ساختگی: پوسترِ سینمایی (فیروزه‌ای/نارنجی، سوژه چپ)، کارتِ روشن، یا نئونیِ تیره."""
    w, h = size
    im = Image.new("RGB", size)
    d = ImageDraw.Draw(im)
    if kind == "cinema":
        for y in range(h):
            t = y / h
            d.line([(0, y), (w, y)], fill=(int(10 + 20 * t), int(70 + 30 * (1 - t)), int(80 + 20 * (1 - t))))
        d.ellipse([10, 120, 125, 420], fill=(235, 120, 40))          # سوژهٔ نارنجی سمتِ چپ
        d.rectangle([20, 470, 380, 560], fill=(15, 40, 50))
    elif kind == "light":
        im.paste((246, 242, 232), [0, 0, w, h])
        d.rectangle([w // 2 - 60, h // 2 - 90, w // 2 + 60, h // 2 + 90], fill=(222, 160, 90))
    elif kind == "neon":
        im.paste((8, 4, 24), [0, 0, w, h])
        d.ellipse([w - 220, 120, w - 20, 340], fill=(255, 0, 200))
        d.rectangle([40, 400, 200, 440], fill=(0, 255, 240))
    return im


def jpeg_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=88)
    return buf.getvalue()


class AnalyzeTests(SimpleTestCase):
    def test_cinema_poster_reads_mood_side_and_style(self):
        a = references.analyze(poster("cinema"), source="commons")
        self.assertEqual(a["mood"], "cinema", a)
        self.assertEqual(a["format_hint"], "poster")
        self.assertEqual(a["layout"]["subject_side"], "left")
        self.assertIn(a["layout"]["text_zone"], ("bottom", "right", "top"))
        self.assertEqual(a["styles"][0]["key"], "cinema_poster", a["styles"])
        self.assertGreaterEqual(len(a["palette"]), 2)
        self.assertTrue(all(c["hex"].startswith("#") and len(c["hex"]) == 7 for c in a["palette"]))
        self.assertAlmostEqual(sum(c["share"] for c in a["palette"]), 1.0, delta=0.1)
        self.assertIn("حال‌وهوا", a["summary"])

    def test_light_card_is_light_and_neon_is_neon(self):
        self.assertEqual(references.analyze(poster("light"))["mood"], "light")
        self.assertEqual(references.analyze(poster("neon"))["mood"], "neon")

    def test_roles_are_hex_or_empty_and_distinct(self):
        a = references.analyze(poster("cinema"))
        for k in ("primary", "secondary", "accent"):
            self.assertRegex(a["roles"][k] or "#000000", r"^#[0-9a-f]{6}$")
        self.assertNotEqual(a["roles"]["primary"], a["roles"]["secondary"])

    def test_format_hint_by_aspect(self):
        self.assertEqual(references.format_hint(1920, 1080), "youtube")
        self.assertEqual(references.format_hint(1000, 1000), "ig_square")
        self.assertEqual(references.format_hint(800, 1000), "ig_portrait")
        self.assertEqual(references.format_hint(1000, 1500), "pinterest")
        self.assertEqual(references.format_hint(1000, 1500, "commons"), "poster")
        self.assertEqual(references.format_hint(540, 1920), "story")

    def test_a_flat_image_does_not_crash(self):
        a = references.analyze(Image.new("RGB", (300, 300), (128, 128, 128)))
        self.assertIn(a["mood"], ("dark", "light", "cool", "warm", "vivid"))
        self.assertTrue(a["styles"])


class PageParsingTests(SimpleTestCase):
    def test_og_image_and_title_are_read_in_either_attribute_order(self):
        html = ('<html><head><meta property="og:title" content="Pin &amp; board"><meta content="https://i.pinimg.com/236x/aa/bb/cc.jpg" property="og:image">'
                '</head></html>')
        got = references.page_images(html, "https://www.pinterest.com/pin/1/")
        self.assertEqual(got["image"], "https://i.pinimg.com/736x/aa/bb/cc.jpg")
        self.assertEqual(got["title"], "Pin & board")

    def test_relative_image_and_twitter_fallback(self):
        got = references.page_images('<meta name="twitter:image" content="/img/x.png">', "https://example.com/a/b")
        self.assertEqual(got["image"], "https://example.com/img/x.png")

    def test_no_image(self):
        self.assertEqual(references.page_images("<html></html>", "https://e.com/")["image"], "")

    def test_pinterest_detection(self):
        self.assertTrue(references.is_pinterest("https://www.pinterest.com/pin/123/"))
        self.assertTrue(references.is_pinterest("https://pin.it/abc"))
        self.assertFalse(references.is_pinterest("https://notpinterest.com/pin/1"))


class FakeFetch:
    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def __call__(self, url, **kw):
        self.calls.append(url)
        for key, val in self.routes.items():
            if url.startswith(key):
                if isinstance(val, Exception):
                    raise val
                body, ctype = val
                return safenet.Fetched(url=url, status=200, content_type=ctype, body=body if isinstance(body, bytes) else body.encode())
        raise safenet.FetchError("پیدا نشد", "http_404")


class FetchUrlTests(SimpleTestCase):
    def test_pin_page_leads_to_its_image(self):
        html = '<meta property="og:image" content="https://i.pinimg.com/474x/a/b/c.jpg"><meta property="og:title" content="Gym poster">'
        ff = FakeFetch({"https://www.pinterest.com/pin/9": (html, "text/html; charset=utf-8"), "https://i.pinimg.com/736x/a/b/c.jpg": (jpeg_bytes(poster("cinema")), "image/jpeg")})
        img, meta = references.fetch_url("https://www.pinterest.com/pin/9/?utm=1", fetch=ff)
        self.assertEqual(img.size, (400, 600))
        self.assertEqual(meta["source"], "pinterest")
        self.assertEqual(meta["title"], "Gym poster")
        self.assertNotIn("utm", meta["page_url"], "the query string must not be stored")

    def test_a_missing_pin_returns_pinterests_generic_share_image_and_is_refused(self):
        html = '<meta property="og:image" content="https://s.pinimg.com/images/facebook_share_image.png"><meta property="og:title" content="Pinterest">'
        ff = FakeFetch({"https://www.pinterest.com/": (html, "text/html")})
        with self.assertRaises(references.RefError) as cm:
            references.fetch_url("https://www.pinterest.com/pin/123/", fetch=ff)
        self.assertIn("پینترست", str(cm.exception))
        self.assertEqual(len([c for c in ff.calls if "pinimg" in c]), 0, "the generic image must not even be downloaded")

    def test_blocked_pin_image_carries_the_url_so_the_browser_can_try(self):
        html = '<meta property="og:image" content="https://i.pinimg.com/474x/a/b/c.jpg?x=1"><meta property="og:title" content="Gym poster">'
        ff = FakeFetch({"https://www.pinterest.com/pin/9": (html, "text/html"), "https://i.pinimg.com/": safenet.FetchError("این نشانی به شبکهٔ داخلی اشاره می‌کند و باز نمی‌شود.", "ssrf")})
        with self.assertRaises(references.RefError) as cm:
            references.fetch_url("https://www.pinterest.com/pin/9/", fetch=ff)
        self.assertEqual(cm.exception.extra["image_url"], "https://i.pinimg.com/736x/a/b/c.jpg")
        self.assertEqual(cm.exception.extra["title"], "Gym poster")
        self.assertIn("پینترست", str(cm.exception))
        self.assertNotIn("داخلی", str(cm.exception), "the user must not read the misleading internal-network sentence")

    def test_direct_image_url(self):
        ff = FakeFetch({"https://example.com/p.jpg": (jpeg_bytes(poster("light")), "image/jpeg")})
        img, meta = references.fetch_url("example.com/p.jpg", fetch=ff)
        self.assertEqual(meta["source"], "url")
        self.assertEqual(img.size, (400, 600))

    def test_page_without_image_gives_a_clear_persian_message(self):
        ff = FakeFetch({"https://example.com/": ("<html>nothing</html>", "text/html")})
        with self.assertRaises(references.RefError) as cm:
            references.fetch_url("https://example.com/", fetch=ff)
        self.assertIn("عکسِ قابل‌استفاده", str(cm.exception))

    def test_network_failure_is_persian(self):
        ff = FakeFetch({"https://example.com/": safenet.FetchError("سایت به‌موقع جواب نداد.", "timeout")})
        with self.assertRaises(references.RefError) as cm:
            references.fetch_url("https://example.com/x", fetch=ff)
        self.assertIn("به‌موقع", str(cm.exception))

    def test_garbage_image_is_refused(self):
        ff = FakeFetch({"https://example.com/": (b"not an image at all", "image/jpeg")})
        with self.assertRaises(references.RefError):
            references.fetch_url("https://example.com/a.jpg", fetch=ff)


class CommonsTests(SimpleTestCase):
    DATA = {"query": {"pages": [
        {"pageid": 1, "title": "File:Old film poster.jpg", "imageinfo": [{"thumburl": "https://upload.wikimedia.org/a/640px-x.jpg", "mime": "image/jpeg", "width": 2000, "height": 3000,
         "descriptionurl": "https://commons.wikimedia.org/wiki/File:Old_film_poster.jpg",
         "extmetadata": {"LicenseShortName": {"value": "Public domain"}, "Artist": {"value": '<a href="x">Some <b>Studio</b></a>'}}}]},
        {"pageid": 2, "title": "File:Nc poster.jpg", "imageinfo": [{"thumburl": "https://upload.wikimedia.org/b.jpg", "mime": "image/jpeg",
         "extmetadata": {"LicenseShortName": {"value": "CC BY-NC 4.0"}}}]},
        {"pageid": 3, "title": "File:Fair poster.jpg", "imageinfo": [{"thumburl": "https://upload.wikimedia.org/c.jpg", "mime": "image/jpeg",
         "extmetadata": {"LicenseShortName": {"value": "Fair use"}, "NonFree": {"value": "true"}}}]},
        {"pageid": 4, "title": "File:Svg poster.svg", "imageinfo": [{"thumburl": "https://upload.wikimedia.org/d.png", "mime": "image/svg+xml",
         "extmetadata": {"LicenseShortName": {"value": "CC0"}}}]},
        {"pageid": 5, "title": "File:Sa poster.png", "imageinfo": [{"thumburl": "https://upload.wikimedia.org/e.png", "mime": "image/png",
         "extmetadata": {"LicenseShortName": {"value": "CC BY-SA 4.0"}}}]},
    ]}}

    def test_only_free_licences_survive_with_author_and_licence(self):
        ff = FakeFetch({"https://commons.wikimedia.org/w/api.php": (json.dumps(self.DATA), "application/json")})
        rows = references.search_commons("noir", fetch=ff)
        self.assertEqual([r["id"] for r in rows], [1, 5])
        self.assertEqual(rows[0]["license"], "Public domain")
        self.assertEqual(rows[0]["author"], "Some Studio")
        self.assertIn("poster", ff.calls[0].lower(), "the query gets «poster» added")

    def test_hate_propaganda_and_adult_posters_are_never_offered(self):
        """«sport» in Commons returns 1930s Nazi-era posters (title, description or Categories say so): they must not reach the panel."""
        def page(pid, title, **meta):
            em = {"LicenseShortName": {"value": "Public domain"}}
            em.update({k: {"value": v} for k, v in meta.items()})
            return {"pageid": pid, "title": title, "imageinfo": [{"thumburl": "https://upload.wikimedia.org/x%d.jpg" % pid, "mime": "image/jpeg", "extmetadata": em}]}
        data = {"query": {"pages": [
            page(1, "File:Boat Race poster 1920.jpg"),
            page(2, "File:Reichssporttag des B.D.M. 1934.jpg"),
            page(3, "File:Ski poster.jpg", Categories="Posters of Germany|Nazi propaganda posters"),
            page(4, "File:Games 1936.jpg", ImageDescription="<p>Poster of the NSDAP for the Winter Games</p>"),
            page(5, "File:Cabaret poster.jpg", ObjectName="Nude dancer, burlesque 1910"),
            page(6, "File:Lawn tennis poster 1916.jpg", Categories="Tennis posters|Posters of the Netherlands"),
        ]}}
        rows = references.search_commons("sport", fetch=FakeFetch({"https://commons.wikimedia.org/w/api.php": (json.dumps(data), "application/json")}))
        self.assertEqual([r["id"] for r in rows], [1, 6])
        self.assertFalse(references.unsafe_poster("Boat Race poster 1920", "A rowing race on the Thames"))
        self.assertTrue(references.unsafe_poster("Poster", "", "", "Hitlerjugend HJ"))

    def test_licence_rules(self):
        free = ["Public domain", "CC0", "CC BY 4.0", "CC BY-SA 3.0", "PD-US"]
        bad = ["CC BY-NC 4.0", "CC BY-ND 2.0", "Fair use", "", "GFDL-NC", "Non-free poster"]
        for s in free:
            self.assertTrue(references.license_is_free(s), s)
        for s in bad:
            self.assertFalse(references.license_is_free(s), s)
        self.assertFalse(references.license_is_free("CC0", "true"))

    def test_short_query_refused(self):
        with self.assertRaises(references.RefError):
            references.search_commons("a")

    def test_commons_image_must_be_from_wikimedia(self):
        with self.assertRaises(references.RefError):
            references.fetch_commons("https://evil.example.com/a.jpg")


class SafenetTests(SimpleTestCase):
    def test_private_and_loopback_addresses_are_refused(self):
        for url in ("http://127.0.0.1/x", "http://localhost/x", "http://10.0.0.5/a.jpg", "http://[::1]/", "http://169.254.169.254/latest/meta-data/"):
            with self.assertRaises(safenet.FetchError) as cm:
                safenet.get(url, resolver=lambda h, p: ["127.0.0.1"] if h == "localhost" else [h])
            self.assertEqual(cm.exception.code, "ssrf", url)

    def test_dns_that_points_inside_is_refused(self):
        with self.assertRaises(safenet.FetchError) as cm:
            safenet.get("https://innocent.example.com/a.jpg", resolver=lambda h, p: ["93.184.216.34", "192.168.1.5"])
        self.assertEqual(cm.exception.code, "ssrf")

    def test_odd_scheme_and_port_refused(self):
        for url, code in (("file:///etc/passwd", "bad_url"), ("ftp://example.com/a", "bad_url"), ("http://example.com:22/", "bad_port")):
            with self.assertRaises(safenet.FetchError) as cm:
                safenet.get(url, resolver=lambda h, p: ["93.184.216.34"])
            self.assertEqual(cm.exception.code, code, url)

    def test_redirect_into_the_internal_network_is_refused_on_the_second_hop(self):
        import httpx

        def handler(request):
            return httpx.Response(302, headers={"location": "http://10.1.2.3/secret"})
        with self.assertRaises(safenet.FetchError) as cm:
            safenet.get("https://example.com/a", resolver=lambda h, p: ["93.184.216.34"] if h == "example.com" else [h], transport=httpx.MockTransport(handler))
        self.assertEqual(cm.exception.code, "ssrf")

    def test_size_cap_and_status(self):
        import httpx

        ok = lambda request: httpx.Response(200, content=b"x" * 5000, headers={"content-type": "text/plain"})  # noqa: E731
        with self.assertRaises(safenet.FetchError) as cm:
            safenet.get("https://example.com/a", max_bytes=1000, resolver=lambda h, p: ["93.184.216.34"], transport=httpx.MockTransport(ok))
        self.assertEqual(cm.exception.code, "too_large")
        nf = lambda request: httpx.Response(404, content=b"no")  # noqa: E731
        with self.assertRaises(safenet.FetchError) as cm:
            safenet.get("https://example.com/a", resolver=lambda h, p: ["93.184.216.34"], transport=httpx.MockTransport(nf))
        self.assertEqual(cm.exception.code, "http_404")
        fine = safenet.get("https://example.com/a?key=SECRET", resolver=lambda h, p: ["93.184.216.34"],
                           transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"hello", headers={"content-type": "text/plain; charset=utf-8"})))
        self.assertEqual(fine.text, "hello")
        self.assertNotIn("SECRET", fine.url)


class RefApiTests(ThumbsApiBase):
    def upload_ref(self, kind="cinema", title="پوستر"):
        buf = io.BytesIO(jpeg_bytes(poster(kind)))
        buf.name = "ref.jpg"
        r = self.api.post(f"{self.base}/references/", {"file": buf, "title": title}, format="multipart")
        self.assertEqual(r.status_code, 201, r.content)
        return r.json()

    def test_upload_lists_and_deletes(self):
        row = self.upload_ref()
        self.assertEqual(row["analysis"]["mood"], "cinema")
        self.assertTrue(row["image"].endswith(f"/refs/{row['id']}.jpg"))
        self.assertTrue((self.media / "thumbs" / f"s{self.store.pk}" / "refs" / f"{row['id']}.jpg").is_file())
        lst = self.api.get(f"{self.base}/references/").json()
        self.assertEqual([r["id"] for r in lst["references"]], [row["id"]])
        self.assertIn("پینترست", lst["pinterest_note"])
        self.assertEqual(self.api.delete(f"{self.base}/references/{row['id']}/").status_code, 204)
        self.assertEqual(self.api.get(f"{self.base}/references/").json()["references"], [])
        self.assertEqual(self.api.delete(f"{self.base}/references/{row['id']}/").status_code, 404)
        self.assertEqual(self.api.delete(f"{self.base}/references/..%2F..%2Fx/").status_code, 404)

    def test_url_reference_from_a_pin_page(self):
        html = '<meta property="og:image" content="https://i.pinimg.com/474x/a/b/c.jpg"><meta property="og:title" content="Poster idea">'
        ff = FakeFetch({"https://www.pinterest.com/pin/5": (html, "text/html"), "https://i.pinimg.com/736x/a/b/c.jpg": (jpeg_bytes(poster("light")), "image/jpeg")})
        with mock.patch("apps.thumbs.references.safenet.get", ff):
            r = self.api.post(f"{self.base}/references/", {"url": "https://www.pinterest.com/pin/5/"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()["source"], "pinterest")
        self.assertEqual(r.json()["title"], "Poster idea")
        blocked = {"https://www.pinterest.com/pin/6": (html, "text/html"), "https://i.pinimg.com/": safenet.FetchError("x", "ssrf")}
        with mock.patch("apps.thumbs.references.safenet.get", FakeFetch(blocked)):
            r2 = self.api.post(f"{self.base}/references/", {"url": "https://www.pinterest.com/pin/6/"}, format="json")
        self.assertEqual(r2.status_code, 400)
        self.assertEqual(r2.json()["error"]["image_url"], "https://i.pinimg.com/736x/a/b/c.jpg")
        bad = self.api.post(f"{self.base}/references/", {"url": "http://10.0.0.5/admin"}, format="json")
        self.assertEqual(bad.status_code, 400)
        self.assertIn("داخلی", bad.json()["error"]["message"])

    def test_commons_search_and_save_keeps_author_and_licence(self):
        ff = FakeFetch({"https://commons.wikimedia.org/w/api.php": (json.dumps(CommonsTests.DATA), "application/json")})
        with mock.patch("apps.thumbs.references.safenet.get", ff):
            res = self.api.post(f"{self.base}/references/search/", {"q": "noir"}, format="json")
        self.assertEqual(res.status_code, 200, res.content)
        first = res.json()["results"][0]
        ff2 = FakeFetch({"https://upload.wikimedia.org/": (jpeg_bytes(poster("cinema")), "image/jpeg")})
        with mock.patch("apps.thumbs.references.safenet.get", ff2):
            r = self.api.post(f"{self.base}/references/", {"commons": first}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()["license"], "Public domain")
        self.assertEqual(r.json()["author"], "Some Studio")
        self.assertEqual(r.json()["source"], "commons")

    def test_bad_inputs(self):
        self.assertEqual(self.api.post(f"{self.base}/references/", {}, format="json").status_code, 400)
        buf = io.BytesIO(b"nope")
        buf.name = "x.jpg"
        self.assertEqual(self.api.post(f"{self.base}/references/", {"file": buf}, format="multipart").status_code, 400)
        self.assertEqual(self.api.post(f"{self.base}/references/search/", {"q": ""}, format="json").status_code, 400)

    def test_other_store_cannot_use_my_reference(self):
        from django.contrib.auth import get_user_model
        from rest_framework.test import APIClient

        from apps.stores.models import Store

        row = self.upload_ref()
        other_user = get_user_model().objects.create_user("thumbs-other", password="x")
        other_store = Store.objects.create(owner=other_user, name="دیگری")
        c = APIClient()
        c.force_authenticate(other_user)
        r = c.post(f"/api/v1/stores/{other_store.pk}/thumbnails/ideas/", {"topic": "تمرین", "reference": row["id"], "ai": False}, format="json")
        self.assertEqual(r.status_code, 404, r.content)
        self.assertEqual(c.get(f"/api/v1/stores/{self.store.pk}/thumbnails/references/").status_code in (403, 404), True)

    def test_ideas_from_a_reference_take_its_style_palette_and_side(self):
        row = self.upload_ref("cinema")
        r = self.api.post(f"{self.base}/ideas/", {"topic": "برنامهٔ ورزشی شخصی", "format": "poster", "ai": False, "reference": row["id"], "count": 4}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        res = r.json()
        self.assertEqual(res["reference"]["id"], row["id"])
        self.assertIn("مرجع", res["message"])
        styles = {i["style"] for i in res["ideas"]}
        self.assertTrue(styles <= {s["key"] for s in row["analysis"]["styles"]}, styles)
        for i in res["ideas"]:
            self.assertEqual(i["reference"]["id"], row["id"])
            self.assertEqual(i["spec_patch"]["style"], i["style"])
            self.assertEqual(i["spec_patch"]["colors"]["mood"], "cinema")
            self.assertTrue(i["spec_patch"]["colors"]["use_brand"], "the default keeps the store's own colours")
            self.assertIn(i["spec_patch"]["subject"]["side"], ("left", "right", "center", "auto"))
            self.assertIn("no text", i["bg_prompt_en"])
            self.assertRegex(i["bg_prompt_en"], r"^[\x20-\x7e]+$", "the background prompt for the model is plain English")
            self.assertTrue(i["title"], "the text of the idea is kept")
        ref_mode = self.api.post(f"{self.base}/ideas/", {"topic": "برنامهٔ ورزشی", "format": "poster", "ai": False, "reference": row["id"], "palette": "reference"}, format="json").json()
        c = ref_mode["ideas"][0]["spec_patch"]["colors"]
        self.assertFalse(c["use_brand"])
        self.assertRegex(c["primary"], r"^#[0-9a-f]{6}$")
        missing = self.api.post(f"{self.base}/ideas/", {"topic": "x y", "reference": "0" * 12, "ai": False}, format="json")
        self.assertEqual(missing.status_code, 404)

    def test_a_reference_spec_patch_renders(self):
        """ایده‌ی از مرجع باید واقعاً به تامنیل تبدیل شود (spec ِ آماده از clean_spec می‌گذرد و ساخته می‌شود)."""
        row = self.upload_ref("cinema")
        res = self.api.post(f"{self.base}/ideas/", {"topic": "برنامهٔ ورزشی شخصی", "format": "poster", "ai": False, "reference": row["id"]}, format="json").json()
        idea = res["ideas"][0]
        spec = {"format": "poster", "style": idea["spec_patch"]["style"], "content": idea["spec_patch"]["content"], "colors": idea["spec_patch"]["colors"],
                "subject": idea["spec_patch"]["subject"]}
        r = self.api.post(f"{self.base}/render/", {"spec": spec}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()["items"][0]["state"], "READY")
