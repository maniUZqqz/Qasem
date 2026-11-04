"""The page parser: every extracted field with its confidence tier, and everything it must NOT extract."""
from django.test import SimpleTestCase

from apps.growth_engine.extraction.services import parser
from apps.growth_engine.extraction.services.parser import CONF, parse_page

from .helpers import by_field, fixture, keys, one


class HomePageTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.page = parse_page(fixture("home_shop.html"), "https://golsorkh.ir/", "home")
        cls.f = cls.page.findings

    def test_phone_tel_link_and_json_ld_merge_into_one_finding_at_the_top_tier(self):
        phone = one(self.f, "phone")
        self.assertEqual((phone.key, phone.value, phone.confidence), ("02112345678", "02112345678", CONF["phone_tel"]))
        self.assertEqual(phone.confidence, 90)

    def test_numbers_that_are_not_phones_are_not_taken(self):
        # a price, a Jalali date, a number inside a <script>: none of them is a phone
        self.assertEqual(keys(self.f, "phone"), ["02112345678"])

    def test_emails_from_mailto_and_json_ld_are_normalised(self):
        self.assertEqual(keys(self.f, "email"), ["hello@golsorkh.ir", "info@golsorkh.ir"])
        self.assertEqual({f.confidence for f in by_field(self.f, "email")}, {90})
        self.assertEqual(one(self.f, "email", "info@golsorkh.ir").evidence, "لینک mailto:")

    def test_every_collected_platform_is_found_with_its_canonical_value(self):
        self.assertEqual(one(self.f, "instagram").value, "https://www.instagram.com/golsorkh.shop/")
        self.assertEqual(one(self.f, "instagram").key, "golsorkh.shop")
        self.assertEqual(one(self.f, "telegram").value, "https://t.me/golsorkh_shop")
        self.assertEqual(one(self.f, "whatsapp").value, "09121234567")  # wa.me/98912... -> the number
        self.assertEqual(one(self.f, "eitaa").value, "https://eitaa.com/golsorkh")
        self.assertEqual(one(self.f, "bale").value, "https://ble.ir/golsorkh")
        self.assertEqual(one(self.f, "rubika").value, "https://rubika.ir/golsorkh")
        self.assertEqual(one(self.f, "linkedin").value, "https://linkedin.com/company/golsorkh")
        for name in ("instagram", "telegram", "whatsapp", "eitaa", "bale", "rubika", "linkedin"):
            self.assertEqual(one(self.f, name).confidence, CONF["social_link"], name)

    def test_share_intent_and_post_links_are_never_profiles(self):
        # exactly one finding per platform: the share/sharer/intent/post/wa.me?text links added nothing
        self.assertEqual(len(by_field(self.f, "telegram")), 1)
        self.assertEqual(len(by_field(self.f, "instagram")), 1)
        self.assertEqual(len(by_field(self.f, "whatsapp")), 1)
        self.assertEqual(len(by_field(self.f, "linkedin")), 1)
        for finding in self.f:
            self.assertNotIn("facebook", finding.value)
            self.assertNotIn("twitter", finding.value)
            self.assertNotIn("share", finding.value)
            self.assertNotIn("CxYz123abc", finding.value)

    def test_classify_social_directly(self):
        for href in [
            "https://t.me/share/url?url=x", "https://www.facebook.com/sharer/sharer.php", "https://twitter.com/intent/tweet", "https://instagram.com/p/AAA/",
            "https://instagram.com/reel/AAA/", "https://wa.me/?text=hi", "https://wa.me/message/ABCDEF", "https://chat.whatsapp.com/INVITE",
            "https://www.linkedin.com/sharing/share-offsite/?url=x", "https://www.linkedin.com/feed/", "https://eitaa.com/", "tg://resolve?domain=x", "mailto:a@b.ir",
        ]:
            with self.subTest(href=href):
                self.assertIsNone(parser.classify_social(href))
        self.assertEqual(parser.classify_social("https://api.whatsapp.com/send?phone=989121234567&text=hi")[0:2], ("whatsapp", "09121234567"))
        self.assertEqual(parser.classify_social("https://wa.me/+442079460958")[1], "+442079460958")
        self.assertEqual(parser.classify_social("https://www.linkedin.com/in/some-person/?trk=x")[2], "linkedin.com/in/some-person")

    def test_json_ld_address_city_name_language_description(self):
        address = one(self.f, "address")
        self.assertEqual(address.confidence, CONF["address_jsonld"])
        self.assertIn("خیابان ولیعصر", address.value)
        city = one(self.f, "city")
        self.assertEqual((city.value, city.confidence), ("تهران", CONF["city_jsonld"]))
        name = one(self.f, "business_name")
        self.assertEqual((name.value, name.confidence), ("فروشگاه گل‌سرخ", CONF["name_jsonld"]))
        self.assertEqual(one(self.f, "language").value, "fa")
        self.assertEqual(one(self.f, "language").confidence, CONF["language"])
        self.assertEqual(one(self.f, "description").confidence, CONF["description"])

    def test_support_link_on_the_same_host_is_a_ticket_finding_other_hosts_and_files_are_not(self):
        forms = by_field(self.f, "contact_form")
        self.assertEqual([(f.value, f.confidence, f.label) for f in forms], [("https://golsorkh.ir/support", CONF["ticket_link"], parser.TICKET_LABEL)])

    def test_links_for_the_crawler(self):
        urls = [link.url for link in self.page.links]
        self.assertIn("https://golsorkh.ir/contact-us", urls)
        self.assertIn("https://golsorkh.ir/about", urls)
        self.assertNotIn("https://golsorkh.ir/files/catalog.pdf", urls)  # a file, not a page
        self.assertFalse([u for u in urls if u.startswith(("mailto:", "tel:"))])

    def test_title_and_flags(self):
        self.assertFalse(self.page.has_contact_form)
        self.assertFalse(self.page.is_challenge)
        self.assertFalse(self.page.is_app_shell)
        self.assertEqual(self.page.lang, "fa")


class ContactPageTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.page = parse_page(fixture("contact_with_form.html"), "https://golsorkh.ir/contact-us", "contact")
        cls.f = cls.page.findings

    def test_phone_tiers_label_beside_number_previous_line_label_and_bare(self):
        self.assertEqual(one(self.f, "phone", "02187654321").confidence, CONF["phone_text_near_contact"])  # «تلفن: ۰۲۱-...» (Persian digits)
        self.assertEqual(one(self.f, "phone", "09123456789").confidence, CONF["phone_text_near_contact"])  # label in the previous line
        self.assertEqual(one(self.f, "phone", "09120001111").confidence, CONF["phone_text_bare"])  # no contact word near it
        self.assertEqual(one(self.f, "phone", "09123456789").evidence, "کنار کلمهٔ تماس/تلفن در متن")

    def test_fax_and_prices_are_not_phones(self):
        self.assertNotIn("02188888888", keys(self.f, "phone"))
        self.assertEqual(len(by_field(self.f, "phone")), 3)

    def test_same_text_on_a_non_contact_page_gets_the_lower_tier(self):
        other = parse_page(fixture("contact_with_form.html"), "https://golsorkh.ir/blog/post", "home")
        self.assertEqual(one(other.findings, "phone", "02187654321").confidence, CONF["phone_text_near_other"])
        self.assertEqual(one(other.findings, "email", "support@golsorkh.ir").confidence, CONF["email_text_other"])

    def test_emails_text_and_obfuscated(self):
        self.assertEqual(one(self.f, "email", "support@golsorkh.ir").confidence, CONF["email_text_contact"])
        obf = one(self.f, "email", "sales@golsorkh.ir")
        self.assertEqual(obf.confidence, CONF["email_obfuscated"])
        self.assertIn("[at]", obf.evidence)

    def test_address_label_and_the_single_city_in_it(self):
        address = one(self.f, "address")
        self.assertEqual((address.value, address.confidence), ("تهران، خیابان ولیعصر، پلاک ۱۲، طبقه سوم", CONF["address_label"]))
        city = one(self.f, "city")
        self.assertEqual((city.value, city.confidence), ("تهران", CONF["city_in_address"]))

    def test_contact_form_page_with_a_message_box(self):
        self.assertTrue(self.page.has_contact_form)
        form = one(self.f, "contact_form")
        self.assertEqual((form.value, form.confidence, form.label), ("https://golsorkh.ir/contact-us", CONF["form_with_message"], parser.FORM_LABEL))
        self.assertFalse(self.page.contact_page_without_form)

    def test_title_is_only_a_business_name_on_the_home_page(self):
        self.assertEqual(by_field(self.f, "business_name"), [])  # «تماس با ما | ...» says nothing about the name
        home = parse_page(fixture("contact_with_form.html"), "https://golsorkh.ir/", "home")
        self.assertEqual(one(home.findings, "business_name").confidence, CONF["name_title"])


class OtherPagesTests(SimpleTestCase):
    def test_contact_page_without_a_form(self):
        page = parse_page(fixture("contact_no_form.html"), "https://nofrm.ir/contact", "contact")
        self.assertFalse(page.has_contact_form)
        self.assertTrue(page.contact_page_without_form)
        self.assertEqual(one(page.findings, "phone").key, "02133445566")
        self.assertEqual(by_field(page.findings, "contact_form"), [])  # the crawler decides whether the bare page is worth a finding

    def test_ticket_link_inside_a_support_page_and_no_self_link(self):
        page = parse_page(fixture("support_page.html"), "https://golsorkh.ir/support", "support")
        forms = by_field(page.findings, "contact_form")
        self.assertEqual([f.value for f in forms], ["https://golsorkh.ir/tickets/new"])
        self.assertEqual(forms[0].confidence, CONF["ticket_link"])

    def test_about_page_address_tag_city_description_and_phone(self):
        page = parse_page(fixture("about_page.html"), "https://golsorkh.ir/about", "about")
        address = one(page.findings, "address")
        self.assertEqual((address.confidence, address.evidence), (CONF["address_tag"], "برچسب <address>"))
        self.assertEqual(one(page.findings, "city").value, "تهران")
        self.assertEqual(one(page.findings, "phone", "09123456789").confidence, CONF["phone_text_near_contact"])
        self.assertIn("گلخانه", one(page.findings, "description").value)

    def test_app_shell_has_nothing_to_read(self):
        page = parse_page(fixture("spa_shell.html"), "https://spa.ir/", "home")
        self.assertTrue(page.is_app_shell)
        self.assertEqual([f.field for f in page.findings if f.field in parser.CONTACT_FIELDS], [])

    def test_challenge_page_is_flagged_and_yields_no_contacts(self):
        page = parse_page(fixture("cloudflare_challenge.html"), "https://shop.example/", "home")
        self.assertTrue(page.is_challenge)
        self.assertEqual([f.field for f in page.findings if f.field in parser.CONTACT_FIELDS], [])
        self.assertTrue(parser.looks_like_challenge(fixture("cloudflare_challenge.html")))
        self.assertTrue(parser.looks_like_challenge("<html></html>", {"cf-mitigated": "challenge"}))
        self.assertFalse(parser.looks_like_challenge(fixture("home_shop.html")))

    def test_shared_platform_page_gives_its_profile_links(self):
        page = parse_page(fixture("linktree.html"), "https://linktr.ee/golsorkhshop", "home")
        self.assertEqual(one(page.findings, "instagram").key, "golsorkhshop")
        self.assertEqual(one(page.findings, "whatsapp").value, "09351112233")

    def test_placeholder_image_noreply_and_fax_are_dropped_real_addresses_kept(self):
        page = parse_page(fixture("placeholder_email.html"), "https://real-shop.ir/contact", "contact")
        self.assertEqual(keys(page.findings, "email"), ["accounts@real-shop.ir", "info@real-shop.ir"])
        self.assertEqual(by_field(page.findings, "phone"), [])  # the only number is a fax
        self.assertEqual({f.confidence for f in by_field(page.findings, "email")}, {CONF["email_text_contact"]})

    def test_english_page_international_phone(self):
        page = parse_page(fixture("english_home.html"), "https://english-shop.com/", "home")
        phone = one(page.findings, "phone")
        self.assertEqual((phone.key, phone.confidence), ("+442079460958", CONF["phone_text_near_other"]))
        self.assertEqual(one(page.findings, "language").value, "en")
        self.assertEqual(one(page.findings, "business_name").value, "Blue Orchid Studio")


class LinkClassificationTests(SimpleTestCase):
    def test_persian_and_english_anchors_and_paths(self):
        cases = [
            ("https://s.ir/contact-us", "تماس با ما", ("contact", 100)),
            ("https://s.ir/x", "ارتباط با ما", ("contact", 60)),
            ("https://s.ir/get-in-touch", "Contact Us", ("contact", 100)),
            ("https://s.ir/x", "Contact", ("contact", 60)),
            ("https://s.ir/contactus", "", ("contact", 40)),  # an image link: the path alone
            ("https://s.ir/%D8%AA%D9%85%D8%A7%D8%B3-%D8%A8%D8%A7-%D9%85%D8%A7", "", ("contact", 40)),  # /تماس-با-ما
            ("https://s.ir/about", "درباره ما", ("about", 100)),
            ("https://s.ir/company/about-us", "About Us", ("about", 100)),
            ("https://s.ir/support", "پشتیبانی", ("support", 100)),
            ("https://s.ir/help", "Help Center", ("support", 100)),
            ("https://s.ir/tickets/new", "ارسال تیکت جدید", ("support", 100)),
        ]
        for url, text, expected in cases:
            with self.subTest(url=url, text=text):
                self.assertEqual(parser.classify_link(url, text), expected)

    def test_things_that_only_look_similar_are_not_classified(self):
        for url, text in [
            ("https://s.ir/products/contact-lens-case", "Contact lens case"),
            ("https://s.ir/cart", "Cart"),
            ("https://s.ir/blog/how-to-contact-suppliers", "How to contact suppliers for your shop"),
            ("https://s.ir/account/login", "My account"),
            ("https://s.ir/shop", "محصولات"),
            ("https://s.ir/track-order", "پیگیری سفارش"),
        ]:
            with self.subTest(url=url):
                self.assertIsNone(parser.classify_link(url, text))

    def test_same_host_ignores_www_scheme_and_port(self):
        self.assertTrue(parser.same_host("http://shop.ir/", "https://www.shop.ir:8443/x"))
        self.assertFalse(parser.same_host("https://shop.ir/", "https://other.ir/"))
        self.assertFalse(parser.same_host("https://shop.ir/", "https://shop.ir.evil.com/"))


class NormalisationAndDedupTests(SimpleTestCase):
    def test_one_number_in_many_notations_is_one_finding_with_the_best_confidence(self):
        html = (
            '<a href="tel:۰۹۱۲۱۲۳۴۵۶۷">call</a><p>تلفن: 0912-123-4567</p><p>+98 912 123 4567</p>'
            '<a href="tel:+989121234567;ext=1">x</a>'
        )
        findings = parse_page(html, "https://s.ir/", "home").findings
        phone = one(findings, "phone")
        self.assertEqual((phone.key, phone.confidence), ("09121234567", 90))

    def test_emails_in_different_case_are_one_finding(self):
        html = '<a href="mailto:Info@Shop.IR">a</a> <p>INFO@shop.ir</p>'
        self.assertEqual(keys(parse_page(html, "https://s.ir/", "contact").findings, "email"), ["info@shop.ir"])

    def test_invalid_numbers_are_dropped_not_guessed(self):
        html = "<p>تلفن: 0912 123</p><p>کد: 0123456789</p><p>شماره: 12345678</p><a href='tel:123'>x</a>"
        self.assertEqual(by_field(parse_page(html, "https://s.ir/", "contact").findings, "phone"), [])

    def test_obfuscated_email_variants(self):
        html = "<p>info (at) shop (dot) ir</p><p>sales[at]shop.ir</p><p>a.b{at}shop{dot}co{dot}uk</p>"
        found = keys(parse_page(html, "https://s.ir/", "contact").findings, "email")
        self.assertEqual(found, ["a.b@shop.co.uk", "info@shop.ir", "sales@shop.ir"])

    def test_json_ld_variants_graph_lists_contact_points_and_broken_json(self):
        html = """
        <script type="application/ld+json">{ broken json</script>
        <script type="application/ld+json">{"@graph": [
          {"@type": "WebSite", "name": "Fallback"},
          {"@type": "LocalBusiness", "name": "Graph Shop", "telephone": ["0912 111 2222", "021-5555 6666"],
           "contactPoint": [{"@type": "ContactPoint", "telephone": "+98 35 3333 4444", "email": "cs@graph.ir"}],
           "sameAs": "https://t.me/graphshop", "address": "یزد، بلوار جمهوری، پلاک ۳"}
        ]}</script>"""
        findings = parse_page(html, "https://graph.ir/", "home").findings
        self.assertEqual(keys(findings, "phone"), ["02155556666", "03533334444", "09121112222"])
        self.assertEqual(keys(findings, "email"), ["cs@graph.ir"])
        self.assertEqual(one(findings, "telegram").key, "graphshop")
        self.assertEqual(one(findings, "address").value, "یزد، بلوار جمهوری، پلاک ۳")
        self.assertEqual(one(findings, "business_name").value, "Graph Shop")  # the WebSite node is not an organisation fallback

    def test_several_cities_in_an_address_give_no_city(self):
        html = "<p>آدرس: شیراز، خیابان تهران، پلاک ۵</p>"
        findings = parse_page(html, "https://s.ir/contact", "contact").findings
        self.assertEqual(one(findings, "address").value, "شیراز، خیابان تهران، پلاک ۵")
        self.assertEqual(by_field(findings, "city"), [])

    def test_city_needs_a_whole_word(self):
        self.assertEqual(parser.find_known_cities("تهران، خیابان ولیعصر"), ["تهران"])
        self.assertEqual(parser.find_known_cities("قمیص فروشی"), [])
        self.assertEqual(parser.find_known_cities("بندر عباس، بلوار ساحلی"), ["بندرعباس"])
        self.assertEqual(parser.find_known_cities("خرم آباد و خرم‌آباد"), ["خرم‌آباد"])

    def test_short_or_empty_values_are_ignored(self):
        html = '<meta name="description" content="کوتاه"><address>x</address><p>آدرس: ابج</p>'
        findings = parse_page(html, "https://s.ir/", "home").findings
        self.assertEqual([f.field for f in findings if f.field in ("description", "address")], [])

    def test_description_is_cut_at_500_characters(self):
        html = f'<meta name="description" content="{"گل " * 400}">'
        self.assertEqual(len(one(parse_page(html, "https://s.ir/", "home").findings, "description").value), 500)

    def test_a_comment_search_or_login_form_is_not_a_contact_form(self):
        for form in [
            '<form id="commentform" action="/wp-comments-post.php"><textarea name="comment"></textarea></form>',
            '<form role="search"><textarea name="q"></textarea></form>',
            '<form action="/login"><input type="password" name="p"><textarea name="x"></textarea></form>',
            '<form action="/subscribe" class="newsletter"><textarea name="x"></textarea></form>',
            '<form action="/send"><input name="name"></form>',  # no message box
        ]:
            with self.subTest(form=form[:40]):
                page = parse_page(f"<html><body>{form}</body></html>", "https://s.ir/contact", "contact")
                self.assertFalse(page.has_contact_form)
                self.assertEqual(by_field(page.findings, "contact_form"), [])
        ok = parse_page('<form action="/send"><input name="name"><textarea name="m"></textarea></form>', "https://s.ir/p", "home")
        self.assertTrue(ok.has_contact_form)

    def test_scripts_and_styles_never_contribute(self):
        html = '<script>var p="09121234567"; var e="a@b.ir";</script><style>.x{content:"0912 111 2222"}</style><p>سلام</p>'
        findings = parse_page(html, "https://s.ir/", "contact").findings
        self.assertEqual([f for f in findings if f.field in ("phone", "email")], [])
