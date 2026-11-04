from django.test import SimpleTestCase

from apps.growth_engine.core import normalization as nz


class UrlTests(SimpleTestCase):
    def identity(self, raw):
        return nz.clean_url(raw).identity

    def test_scheme_www_slash_and_case_do_not_matter(self):
        same = ["https://www.Shop.ir/", "http://shop.ir", "shop.ir", "SHOP.IR/", "//www.shop.ir", "https://shop.ir:443/"]
        self.assertEqual({self.identity(u) for u in same}, {"shop.ir"})

    def test_tracking_params_fragment_and_userinfo_are_dropped(self):
        clean = nz.clean_url("https://user:pw@www.shop.ir/products/?utm_source=ig&fbclid=abc&b=2&a=1#top")
        self.assertEqual(clean.url, "https://shop.ir/products?a=1&b=2")
        self.assertEqual(clean.identity, "shop.ir")

    def test_default_ports_dropped_others_kept(self):
        self.assertEqual(nz.clean_url("http://shop.ir:80/x").url, "http://shop.ir/x")
        self.assertEqual(nz.clean_url("http://shop.ir:8080/x").url, "http://shop.ir:8080/x")
        self.assertNotEqual(self.identity("http://shop.ir:8080"), self.identity("http://shop.ir"))

    def test_idn_unicode_and_punycode_are_the_same_business(self):
        a = nz.clean_url("https://www.فروشگاه.ایران/")
        b = nz.clean_url("https://" + "فروشگاه.ایران".encode("idna").decode() + "/")
        self.assertEqual(a.identity, b.identity)
        self.assertTrue(a.identity.startswith("xn--"))
        self.assertEqual(a.host, "فروشگاه.ایران")
        self.assertTrue(a.fetch_url.isascii())

    def test_shared_platform_keeps_the_path_in_the_identity(self):
        self.assertNotEqual(self.identity("https://linktr.ee/shopa"), self.identity("https://linktr.ee/shopb"))
        self.assertEqual(self.identity("https://www.linktr.ee/ShopA/"), self.identity("linktr.ee/shopa"))
        self.assertEqual(self.identity("https://digikala.com/seller/abc/"), "digikala.com/seller/abc")

    def test_subdomains_of_ordinary_sites_are_different_businesses(self):
        self.assertNotEqual(self.identity("https://a.myshopify.com"), self.identity("https://b.myshopify.com"))

    def test_path_slashes_collapse_and_trailing_slash_goes(self):
        self.assertEqual(nz.clean_url("https://shop.ir//a///b/").url, "https://shop.ir/a/b")

    def test_invalid_urls_raise(self):
        for bad in ["", "   ", "javascript:alert(1)", "mailto:a@b.ir", "ftp://shop.ir", "not a url", "http://localhost", "shop", "http://a..b"]:
            with self.subTest(bad=bad), self.assertRaises(nz.NormalizationError):
                nz.clean_url(bad)

    def test_ip_hosts_are_allowed(self):
        self.assertEqual(self.identity("http://87.107.160.17:8080/x"), "87.107.160.17:8080")


class InstagramTests(SimpleTestCase):
    def handle(self, raw):
        return nz.parse_instagram(raw).handle

    def test_every_url_form_gives_the_same_handle(self):
        forms = [
            "https://www.instagram.com/My.Shop_1/", "http://instagram.com/my.shop_1", "instagram.com/my.shop_1?igshid=abc",
            "https://m.instagram.com/my.shop_1/", "https://instagr.am/my.shop_1", "@my.shop_1", "my.shop_1", " @My.Shop_1 ",
            "https://www.instagram.com/_u/my.shop_1/", "https://www.instagram.com/my.shop_1/?hl=fa", "www.instagram.com/my.shop_1/#x",
        ]
        self.assertEqual({self.handle(f) for f in forms}, {"my.shop_1"})

    def test_canonical_url(self):
        self.assertEqual(nz.parse_instagram("@shop").url, "https://www.instagram.com/shop/")

    def test_post_reel_story_links_are_not_profiles(self):
        for bad in ["https://www.instagram.com/p/ABC123/", "https://instagram.com/reel/xyz/", "instagram.com/stories/shop/123", "instagram.com/explore/tags/x"]:
            with self.subTest(bad=bad), self.assertRaises(nz.NormalizationError) as ctx:
                nz.parse_instagram(bad)
            self.assertEqual(ctx.exception.code, "instagram_not_profile")

    def test_other_hosts_and_bad_handles_raise(self):
        for bad in ["https://twitter.com/shop", "", "a b", "shop..name", ".shop", "x" * 31, "فروشگاه"]:
            with self.subTest(bad=bad), self.assertRaises(nz.NormalizationError):
                nz.parse_instagram(bad)


class PhoneTests(SimpleTestCase):
    def phone(self, raw):
        return nz.normalize_phone(raw).normalized

    def test_iranian_mobile_in_every_notation(self):
        forms = [
            "09121234567", "9121234567", "+989121234567", "00989121234567", "989121234567", "+98 912 123 4567",
            "0912-123-4567", "(0912) 123 4567", "۰۹۱۲۱۲۳۴۵۶۷", "٠٩١٢١٢٣٤٥٦٧", "+98 0912 123 4567", "0912 123 45 67",
        ]
        for raw in forms:
            with self.subTest(raw=raw):
                self.assertEqual(self.phone(raw), "09121234567")

    def test_landline(self):
        for raw in ["02112345678", "021-12345678", "+98 21 1234 5678", "0098 21 12345678", "۰۲۱ ۱۲۳۴ ۵۶۷۸", "2112345678"]:
            with self.subTest(raw=raw):
                ref = nz.normalize_phone(raw)
                self.assertEqual((ref.normalized, ref.kind), ("02112345678", "landline"))

    def test_kinds_and_e164(self):
        ref = nz.normalize_phone("0912 123 4567")
        self.assertEqual((ref.kind, ref.e164), ("mobile", "+989121234567"))

    def test_extension_is_dropped(self):
        self.assertEqual(self.phone("021-12345678 داخلی 12"), "02112345678")
        self.assertEqual(self.phone("021 12345678 ext. 305"), "02112345678")

    def test_international_numbers_keep_plus(self):
        ref = nz.normalize_phone("+44 20 7123 4567")
        self.assertEqual((ref.normalized, ref.kind), ("+442071234567", "international"))
        self.assertEqual(self.phone("0044 20 7123 4567"), "+442071234567")

    def test_invalid(self):
        for bad in ["", "abc", "12345", "0912123456", "091212345678", "+98 912 123", "12345678", "00"]:
            with self.subTest(bad=bad), self.assertRaises(nz.NormalizationError):
                nz.normalize_phone(bad)

    def test_eight_digit_landline_is_refused_not_guessed(self):
        with self.assertRaises(nz.NormalizationError) as ctx:
            nz.normalize_phone("12345678")
        self.assertEqual(ctx.exception.code, "missing_area_code")

    def test_display_format_keeps_leading_zero_for_excel(self):
        self.assertEqual(nz.format_phone_display("09121234567"), "0912 123 4567")
        self.assertEqual(nz.format_phone_display("02112345678"), "021 1234 5678")
        self.assertEqual(nz.format_phone_display("+442071234567"), "+442071234567")


class EmailTests(SimpleTestCase):
    def test_lowercase_and_trim(self):
        self.assertEqual(nz.normalize_email("  Info@Shop.IR "), "info@shop.ir")
        self.assertEqual(nz.normalize_email("mailto:Sales@Shop.ir?subject=hi"), "sales@shop.ir")
        self.assertEqual(nz.normalize_email("<a@b.co>"), "a@b.co")

    def test_idn_domain_becomes_punycode(self):
        self.assertEqual(nz.normalize_email("info@فروشگاه.ایران"), "info@" + "فروشگاه.ایران".encode("idna").decode())

    def test_gmail_is_not_second_guessed(self):
        self.assertEqual(nz.normalize_email("a.b+c@gmail.com"), "a.b+c@gmail.com")

    def test_invalid(self):
        for bad in ["", "a", "a@", "@b.ir", "a@b", "a b@c.ir", "a@@b.ir", ".a@b.ir", "a..b@c.ir", "a@b.123"]:
            with self.subTest(bad=bad), self.assertRaises(nz.NormalizationError):
                nz.normalize_email(bad)

    def test_placeholder_detection(self):
        self.assertTrue(nz.is_placeholder_email("email@example.com"))
        self.assertTrue(nz.is_placeholder_email("name@shop.ir"))
        self.assertFalse(nz.is_placeholder_email("info@shop.ir"))


class TextTests(SimpleTestCase):
    def test_arabic_letters_and_digits(self):
        self.assertEqual(nz.normalize_text("كتاب يک"), "کتاب یک")
        self.assertEqual(nz.to_ascii_digits("۱۲۳٤٥٦abc"), "123456abc")

    def test_whitespace_and_invisible_marks(self):
        self.assertEqual(nz.normalize_text("  a ‏ b  c  "), "a b c")
        self.assertEqual(nz.normalize_text("کسب‌وکار"), "کسب‌وکار")  # ZWNJ is kept

    def test_search_key_ignores_spaces_zwnj_case_punctuation(self):
        self.assertEqual(nz.search_key("کسب‌وکار"), nz.search_key("کسب و کار"))
        self.assertEqual(nz.search_key("Blue Shop!"), "blueshop")
        self.assertEqual(nz.search_key("فروشگاه ۱۲۳"), "فروشگاه123")

    def test_split_multi(self):
        self.assertEqual(nz.split_multi("a | b; c ، d,e\nf"), ["a", "b", "c", "d", "e", "f"])
        self.assertEqual(nz.split_multi(["a,b", "c"]), ["a", "b", "c"])
        self.assertEqual(nz.split_multi(None), [])


class CountryTests(SimpleTestCase):
    def test_names_and_codes(self):
        for raw, code in [("ایران", "IR"), ("Iran", "IR"), ("ir", "IR"), ("ترکیه", "TR"), ("UAE", "AE"), ("امارات", "AE"), ("de", "DE"), ("", "")]:
            with self.subTest(raw=raw):
                self.assertEqual(nz.normalize_country(raw), code)

    def test_unknown_name_is_an_error(self):
        with self.assertRaises(nz.NormalizationError):
            nz.normalize_country("آتلانتیس")


class HandleTests(SimpleTestCase):
    def test_telegram(self):
        self.assertEqual(nz.parse_handle("https://t.me/My_Shop", ("t.me",), "تلگرام")[0], "my_shop")
        self.assertEqual(nz.parse_handle("@my_shop", ("t.me",), "تلگرام")[0], "my_shop")

    def test_share_links_are_refused(self):
        with self.assertRaises(nz.NormalizationError):
            nz.parse_handle("https://t.me/share/url?url=x", ("t.me",), "تلگرام")
