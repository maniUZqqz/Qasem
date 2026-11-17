# -*- coding: utf-8 -*-
"""«تصویر به کد» — نقشه‌بردارِ درخت ⇒ سندِ سایت‌ساز (خالص، بی‌شبکه و بی‌مرورگر) و محافظِ نشانی.

درخت‌ها ساختگی‌اند (جمله‌های عمومی، بدونِ دادهٔ آدم‌ها)؛ همان شکلِ ``tree_json`` ِ mv2code (docs/tree-json.md) را دارند.
هر نتیجه از صافیِ خودِ سایت‌ساز (clean_doc) می‌گذرد؛ یعنی چیزی که این‌جا سبز است در ویرایشگر هم باز می‌شود.
"""
import numpy as np
from django.test import SimpleTestCase

from apps.projects.builder import render as R
from apps.projects.builder.clean import walk

from . import mapping, netguard

_ID = [0]


def nid():
    _ID[0] += 1
    return _ID[0]


def text(x, y, w, h, t, size=18, weight=400, color="#222222", **kw):
    n = {"id": nid(), "role": "text", "box": [x, y, w, h], "text": t, "font": {"family": "Vazirmatn", "weight": weight, "size": size, "color": color}, "direction": "rtl", "align": "left"}
    n.update(kw)
    return n


def button(x, y, w, h, label, bg="#1b6ec2", fg="#ffffff"):
    return {"id": nid(), "role": "button", "box": [x, y, w, h], "text": label, "background": bg, "radius": 12.0,
            "children": [text(x + 10, y + 10, w - 20, h - 20, label, 17, 700, fg)]}


def card(x, y, w, h, children, bg="#ffffff", radius=18.0):
    return {"id": nid(), "role": "card", "box": [x, y, w, h], "background": bg, "radius": radius, "children": children}


def page(children, w=1280, h=1400, bg="#f4f6fa", direction="rtl"):
    return {"id": 0, "role": "page", "box": [0, 0, w, h], "width": w, "height": h, "direction": direction, "background": bg, "source_scale": 1.0, "children": children}


def landing_tree():
    """هدر + قهرمان + سه کارتِ ویژگی + دعوت + پابرگ؛ متن‌های فارسی و یک متنِ انگلیسی."""
    hero_children = [text(520, 160, 240, 56, "فروشگاهِ نمونه", 52, 700, "#0f2a4a"), text(430, 240, 420, 26, "همه‌چیز برای شروعِ کار", 22, 400, "#41506a"),
                     button(480, 310, 150, 52, "شروع کنید"), button(650, 310, 150, 52, "بیشتر بدانید", "#ffffff", "#1b6ec2")]
    cards = [card(100 + i * 380, 470, 340, 300, [text(140 + i * 380, 600, 260, 30, "ویژگیِ %d" % (i + 1), 26, 700, "#0f2a4a"), text(130 + i * 380, 660, 280, 60, "توضیحِ کوتاهِ همین ویژگی برای آزمون", 17, 400, "#555555", lines=["توضیحِ کوتاهِ همین", "ویژگی برای آزمون"])]) for i in range(3)]
    header = {"id": nid(), "role": "nav", "kind": "header", "box": [0, 0, 1280, 90], "background": "#ffffff", "children": [
        text(1120, 30, 80, 30, "فروشگاه", 26, 700, "#1b6ec2"), text(900, 36, 60, 18, "خانه", 17, 500), text(800, 36, 70, 18, "درباره ما", 17, 500), text(700, 36, 70, 18, "تماس", 17, 500),
        button(60, 24, 150, 42, "ورود / ثبت‌نام")]}
    footer = {"id": nid(), "role": "nav", "kind": "footer", "box": [0, 1200, 1280, 200], "background": "#0f2a4a", "children": [
        text(900, 1240, 260, 20, "همهٔ حقوق محفوظ است", 16, 400, "#c9d3e6"), text(120, 1240, 200, 20, "info@example.com", 16, 400, "#c9d3e6", direction="ltr")]}
    return page([header] + hero_children + cards + [text(380, 900, 520, 44, "آماده‌اید شروع کنیم؟", 38, 700, "#0f2a4a"), footer])


def all_blocks(doc):
    return list(walk(doc["blocks"]))


def texts_of(doc):
    out = []
    for b in all_blocks(doc):
        p = b["props"]
        if b["type"] == "heading":
            out.append(p["text"])
        elif b["type"] == "text":
            out.append(p["html"])
        elif b["type"] == "button":
            out.append(p["text"])
    return out


class MappingTests(SimpleTestCase):
    def map(self, tree, chrome=True, image=None):
        r = mapping.map_tree(tree, image, chrome=chrome)
        return r, mapping.clean_docs(r)

    def test_landing_tree_becomes_valid_builder_documents(self):
        r, docs = self.map(landing_tree())
        self.assertEqual(docs["header"]["blocks"][0]["type"], "site_header")
        self.assertEqual(docs["header"]["blocks"][0]["props"]["btn"], "ورود / ثبت‌نام")
        self.assertEqual([m["label"] for m in r["menu"]], ["خانه", "درباره ما", "تماس"])
        self.assertEqual(r["site_title"], "فروشگاه")
        types = [b["type"] for b in all_blocks(docs["page"])]
        for t in ("section", "heading", "text", "button", "columns", "column"):
            self.assertIn(t, types)
        self.assertTrue(docs["footer"]["blocks"])

    def test_every_text_of_the_tree_arrives_unchanged(self):
        tree = landing_tree()
        _r, docs = self.map(tree)
        want = {"فروشگاهِ نمونه", "همه‌چیز برای شروعِ کار", "شروع کنید", "بیشتر بدانید", "آماده‌اید شروع کنیم؟", "ویژگیِ 1", "ویژگیِ 2", "ویژگیِ 3"}
        got = " ".join(texts_of(docs["page"]))
        for w in want:
            self.assertIn(w, got, w)
        self.assertIn("همهٔ حقوق محفوظ است", " ".join(texts_of(docs["footer"])))

    def test_columns_follow_the_page_right_to_left_and_cards_become_columns(self):
        _r, docs = self.map(landing_tree())
        cols = [b for b in all_blocks(docs["page"]) if b["type"] == "columns" and b["props"]["count"] == 3]
        self.assertTrue(cols, "سه کارت کنارِ هم باید «ستون‌ها»ی سه‌تایی شود")
        heads = [next(k for k in walk(c["children"]) if k["type"] == "heading")["props"]["text"] for c in cols[0]["children"]]
        self.assertEqual(heads, ["ویژگیِ 3", "ویژگیِ 2", "ویژگیِ 1"])        # راست‌به‌چپ مثلِ تصویر
        self.assertTrue(cols[0]["children"][0]["style"]["d"].get("radius"))   # گوشهٔ کارت حفظ می‌شود

    def test_sizes_decide_heading_levels_and_numbers_are_not_headings(self):
        tree = page([text(400, 100, 400, 60, "عنوانِ اصلیِ صفحه", 54, 700), text(400, 220, 300, 40, "عنوانِ بخش", 34, 700), text(400, 300, 300, 30, "زیرعنوانِ کارت", 24, 700),
                     text(400, 380, 600, 60, "یک پاراگرافِ معمولی که چند کلمه دارد و عنوان نیست.", 16, 400), text(400, 460, 90, 50, "۹۸٪", 44, 700),
                     text(400, 540, 400, 20, "متنِ دیگرِ صفحه", 16, 400), text(400, 580, 400, 20, "یک متنِ معمولیِ دیگر", 16, 400)])
        _r, docs = self.map(tree)
        heads = [(b["props"]["level"], b["props"]["text"]) for b in all_blocks(docs["page"]) if b["type"] == "heading"]
        self.assertEqual(heads[0], (1, "عنوانِ اصلیِ صفحه"))
        self.assertEqual(sum(1 for lv, _t in heads if lv == 1), 1)        # فقط یک تیترِ اصلی
        self.assertNotIn("۹۸٪", [t for _l, t in heads])
        self.assertIn("۹۸٪", " ".join(texts_of(docs["page"])))

    def test_a_compact_centred_row_stays_compact_and_is_released_on_small_screens(self):
        """دو دکمهٔ کنارِ هم در وسطِ صفحه نباید به دو سرِ بخش بروند: فاصلهٔ داخلیِ ستون‌ها در دسکتاپ تنگ‌شان می‌کند و در تبلت/گوشی صفر است."""
        wide = [text(60, y, 1160, 20, "یک خطِ پهن در بالای صفحه تا پهنای محتوای سایت ۱۲۰۰ بسنجد", 16, 400) for y in (0, 26, 52)]    # پهنای محتوا را مثلِ یک صفحهٔ واقعی می‌کند
        tree = page(wide + [
                     text(500, 130, 280, 50, "عنوانِ بخش", 40, 700), text(520, 200, 240, 24, "یک زیرعنوانِ کوتاه", 20, 400),
                     button(436, 290, 194, 60, "دکمهٔ اول"), button(648, 290, 200, 60, "دکمهٔ دوم"),
                     text(506, 410, 88, 30, "500+", 30, 700), text(693, 410, 74, 30, "98%", 30, 700),
                     text(496, 450, 108, 16, "برنامه ساخته شده", 15), text(690, 450, 80, 16, "رضایت مربیان", 15)])
        r, docs = self.map(tree)
        # دو گروه ⇒ ۴ ستون: خالی، الف، ب، خالی (ردیف فقط نیمهٔ میانیِ بخش را می‌گیرد)؛ ستون‌های خالی در تبلت و گوشی پنهان‌اند
        rows = [b for b in all_blocks(docs["page"]) if b["type"] == "columns" and b["props"]["count"] == 4]
        self.assertGreaterEqual(len(rows), 2, "هر دو ردیف (دکمه‌ها و آمارها) باید جمع‌وجور شوند")
        self.assertGreaterEqual(r["stats"].get("compact_rows", 0), 2)
        for row in rows:
            kids = row["children"]
            self.assertEqual([[c["type"] for c in k["children"]][:1] == ["spacer"] for k in kids], [True, False, False, True])      # دو ستونِ کنارِ ردیف فقط یک فاصلهٔ ۴ پیکسلی‌اند
            for sp in (kids[0], kids[3]):
                self.assertTrue(sp["style"]["d"]["hide_tablet"] and sp["style"]["d"]["hide_phone"])
            st = row["style"]
            self.assertGreaterEqual(st["d"]["px"], 20)
            self.assertEqual(st["t"]["px"], 0)
            self.assertEqual(st["p"]["px"], 0)
        # و رندرکنندهٔ خودِ سایت‌ساز این را در CSS می‌نویسد: دسکتاپ تنگ، تبلت و گوشی صفر
        rid = rows[0]["id"]
        css = R.render_doc(docs["page"], R.Ctx(canvas=False, target="page", theme=r["theme"]["colors"])).css
        self.assertRegex(css, r"\.b-%s\{[^}]*padding-inline:\d{2,3}px" % rid)
        self.assertRegex(css, r"@media \(max-width:640px\)\{.*\.b-%s\{padding-inline:0px\}" % rid)
        self.assertRegex(css, r"@media \(max-width:1024px\)\{.*\.b-%s\{padding-inline:0px\}" % rid)

    def test_full_width_rows_are_not_squeezed(self):
        _r, docs = self.map(landing_tree())
        cols = [b for b in all_blocks(docs["page"]) if b["type"] == "columns" and b["props"]["count"] == 3]
        self.assertTrue(cols)
        self.assertNotIn("px", (cols[0].get("style") or {}).get("d", {}))      # سه کارتِ تمام‌عرض دست‌نخورده می‌مانند

    def test_site_text_colour_is_a_readable_one_not_the_footers_light_grey(self):
        """متنِ روشنِ پابرگِ تیره نباید «رنگِ متنِ سایت» شود (روی زمینهٔ روشن ناخوانا بود)."""
        tree = page([text(400, 100, 400, 50, "عنوانِ صفحه", 40, 700, "#163f75"), text(400, 200, 500, 24, "یک متنِ معمولی برای صفحه", 18, 400, "#5c5c74"),
                     {"id": nid(), "role": "nav", "kind": "footer", "box": [0, 600, 1280, 200], "background": "#163f75", "children": [
                         text(100, 640, 300, 20, "متنِ بلندِ پابرگ با واژه‌های زیاد برای سنگین‌شدنِ شمارش", 16, 400, "#b1b3b6"), text(100, 680, 300, 20, "یک خطِ دیگرِ پابرگ با واژه‌های زیاد", 16, 400, "#b3b4b7"),
                         text(100, 720, 300, 20, "و باز هم یک خطِ بلندِ دیگر در پابرگ برای شمارش", 16, 400, "#b1b4b7")]}], bg="#f4f8ff")
        r, _docs = self.map(tree)
        text_col = r["theme"]["colors"]["text"]
        self.assertGreaterEqual(mapping._contrast(mapping._hex_to_rgb(text_col), mapping._hex_to_rgb("#f4f8ff")), 4.5, text_col)

    def test_alignment_is_geometric(self):
        # یک خطِ پهن از لبه تا لبه، تا اجزا ستون‌ستون نشوند و چینش نسبت به کلِ صفحه سنجیده شود
        tree = page([text(80, 30, 1120, 24, "یک خطِ پهن که از لبه تا لبهٔ صفحه می‌رود", 18), text(440, 100, 400, 40, "وسطِ صفحه", 30, 700), text(900, 200, 300, 24, "نزدیکِ راست", 18),
                     text(80, 300, 300, 24, "نزدیکِ چپ", 18), text(500, 400, 300, 24, "یک متنِ دیگر برای پرکردنِ صفحه", 18), text(60, 460, 1160, 24, "و یک خطِ پهنِ دیگر در پایان", 18)])
        _r, docs = self.map(tree)
        al = {b["props"].get("text") or b["props"].get("html"): b["style"]["d"].get("align") for b in all_blocks(docs["page"]) if b["type"] in ("heading", "text")}
        self.assertEqual(al["وسطِ صفحه"], "center")
        self.assertEqual(al["<p>نزدیکِ راست</p>"], "start")      # راست در صفحهٔ راست‌به‌چپ
        self.assertEqual(al["<p>نزدیکِ چپ</p>"], "end")

    def test_english_text_is_isolated_ltr_in_an_rtl_page(self):
        tree = page([text(400, 100, 300, 30, "Hello, world!", 22, 700, direction="ltr"), text(400, 200, 400, 24, "یک متنِ فارسی", 18), text(400, 300, 400, 24, "و یک متنِ دیگر", 18)])
        _r, docs = self.map(tree)
        t = " ".join(texts_of(docs["page"]))
        self.assertIn(mapping.LRI + "Hello, world!" + mapping.PDI, t)
        self.assertNotIn(mapping.LRI + "یک", t)                      # فارسی ایزوله نمی‌شود

    def test_inputs_become_a_contact_form_root_block(self):
        inp = lambda y, t, kind="text": {"id": nid(), "role": "input", "kind": kind, "box": [420, y, 440, 44], "text": t, "background": "#ffffff", "children": []}
        tree = page([text(480, 100, 300, 36, "با ما در تماس باشید", 30, 700), inp(180, "نام و نام‌خانوادگی"), inp(250, "ایمیل شما"), inp(320, "شمارهٔ موبایل"), inp(390, "پیامتان", "textarea"),
                     button(500, 480, 160, 48, "ارسال پیام")])
        _r, docs = self.map(tree)
        form = [b for b in docs["page"]["blocks"] if b["type"] == "contact_form"]
        self.assertEqual(len(form), 1, "فرم باید بلوکِ ریشه باشد (داخلِ بخش نمی‌نشیند)")
        p = form[0]["props"]
        self.assertEqual(p["title"], "با ما در تماس باشید")
        self.assertEqual([f["type"] for f in p["fields"]], ["text", "email", "tel", "textarea"])
        self.assertEqual(p["button"], "ارسال پیام")

    def test_table_becomes_a_real_escaped_html_table(self):
        cells = []
        for r, row in enumerate([["نام", "قیمت"], ["الف<script>", "۱۰"], ["ب", "۲۰"]]):
            for c, v in enumerate(row):
                cells.append(text(900 - c * 300, 100 + r * 50, 100, 24, v, 17))
        tree = page([{"id": nid(), "role": "table", "box": [300, 90, 700, 170], "children": cells}, text(400, 400, 300, 24, "پایانِ جدول و یک متن", 18)])
        _r, docs = self.map(tree)
        code = next(b["props"]["code"] for b in all_blocks(docs["page"]) if b["type"] == "custom_html")
        self.assertIn("<table", code)
        self.assertIn("&lt;script&gt;", code)
        self.assertNotIn("<script>", code)
        self.assertEqual(code.count("<tr>"), 3)

    def test_image_and_icon_leaves_become_crops_not_fake_pictures(self):
        img = {"id": nid(), "role": "image", "box": [100, 200, 500, 300], "embedded_raster": True, "radius": 16.0}
        tiny = {"id": nid(), "role": "icon", "box": [700, 210, 18, 18], "vector": True}
        tree = page([text(100, 100, 400, 36, "تصویرِ محصول", 28, 700), img, tiny, text(100, 540, 400, 24, "زیرنویسِ تصویر", 18)])
        r, docs = self.map(tree)
        self.assertEqual(len(r["crops"]), 1)
        self.assertEqual(r["crops"][0]["box"], [100, 200, 500, 300])
        imgs = [b for b in all_blocks(docs["page"]) if b["type"] == "image"]
        self.assertEqual(imgs[0]["props"]["src"], "")                  # هنوز «crop:c1» بود و clean آن را نمی‌شناسد ⇒ خالی؛ ساخت‌گر پیش از clean جایگزین می‌کند
        self.assertEqual(r["stats"].get("icons_skipped"), 1)

    def test_background_colour_comes_from_the_image_not_the_lossy_tree(self):
        tree = page([text(300, 120, 300, 40, "روی زمینهٔ تیره", 30, 700, "#ffffff"), text(300, 200, 400, 24, "متنِ سفید روی زمینهٔ تیره", 18, 400, "#ffffff"),
                     text(300, 260, 400, 24, "یک خطِ دیگر برای پرکردنِ نوار", 18, 400, "#ffffff")], h=500)
        img = np.full((500, 1280, 3), (244, 246, 250), np.uint8)
        img[60:360, :] = (20, 40, 90)                                  # نوارِ تیرهٔ تمام‌عرض که درخت از دست داده است
        _r, docs = self.map(tree, image=img)
        sec = docs["page"]["blocks"][0]
        self.assertEqual(sec["style"]["d"]["bg"], "#14285a")
        self.assertTrue(sec["props"]["full"])

    def test_depth_never_exceeds_the_builders_limit(self):
        def nest(level, x, y, w, h):
            kids = [text(x + 10, y + 10, w - 20, 22, "متنِ تودرتو %d" % level, 16), text(x + 10, y + 40, w - 20, 22, "خطِ دوم %d" % level, 16)]
            if level < 8:
                kids.append(nest(level + 1, x + 14, y + 74, w - 28, h - 90))
            return card(x, y, w, h, kids)
        tree = page([nest(0, 100, 100, 1000, 900)], h=1100)
        _r, docs = self.map(tree)                                       # clean_doc بالا می‌اندازد اگر از ۸ سطح بگذرد
        self.assertTrue(docs["page"]["blocks"])

    def test_chrome_false_keeps_header_and_footer_in_the_page_body(self):
        r, docs = self.map(landing_tree(), chrome=False)
        self.assertIsNone(docs["header"])
        self.assertIsNone(docs["footer"])
        body = " ".join(texts_of(docs["page"]))
        self.assertIn("درباره ما", body)
        self.assertIn("همهٔ حقوق محفوظ است", body)

    def test_theme_colours_come_from_the_tree(self):
        r, _docs = self.map(landing_tree())
        c = r["theme"]["colors"]
        self.assertEqual(c["primary"], "#1b6ec2")
        self.assertEqual(c["bg"], "#f4f6fa")

    def test_mapping_is_deterministic(self):
        a = mapping.map_tree(landing_tree())
        _ID[0] = 0
        b = mapping.map_tree(landing_tree())

        def shape(doc):
            return [(x["type"], x["props"].get("text") or x["props"].get("html") or "") for x in walk(doc["blocks"])]
        self.assertEqual(shape(a["page"]), shape(b["page"]))

    def test_result_renders_with_the_real_site_renderer(self):
        _r, docs = self.map(landing_tree())
        ctx = R.Ctx(canvas=False, target="page", theme=_r["theme"]["colors"])
        html = R.render_doc(docs["page"], ctx).html
        self.assertIn("فروشگاهِ نمونه", html)
        self.assertIn("<h1", html)

    def test_garbage_tree_does_not_crash(self):
        r = mapping.map_tree(page([]))
        self.assertEqual(r["page"]["blocks"], [])
        r = mapping.map_tree(page([{"id": 1, "role": "mystery", "box": [0, 0, 10, 10], "children": [{"id": 2, "role": "text", "box": [0, 0, 5, 5], "text": ""}]}]))
        self.assertEqual(r["page"]["blocks"], [])


class NetGuardTests(SimpleTestCase):
    def fake(self, ip):
        return lambda host, port, **kw: [(2, 1, 6, "", (ip, 0))]

    def test_private_and_special_addresses_are_refused(self):
        for ip in ("127.0.0.1", "10.0.0.5", "192.168.1.9", "172.16.0.3", "169.254.169.254", "100.64.0.1", "::1", "fe80::1", "0.0.0.0"):
            with self.assertRaises(netguard.UrlRefused, msg=ip):
                netguard.check_url("http://host.example/", resolver=self.fake(ip))

    def test_literal_ip_urls_are_checked_without_dns(self):
        for u in ("http://127.0.0.1:8041/", "http://[::1]/", "https://169.254.169.254/latest/meta-data"):
            with self.assertRaises(netguard.UrlRefused, msg=u):
                netguard.check_url(u)

    def test_public_address_and_scheme_less_url_pass(self):
        self.assertEqual(netguard.check_url("example.com/a?b=1", resolver=self.fake("93.184.216.34")), "https://example.com/a?b=1")

    def test_bad_schemes_credentials_and_empty_are_refused(self):
        for u in ("file:///etc/passwd", "ftp://example.com", "javascript:alert(1)", "https://user:pw@example.com/", "", "   ", "http://"):
            with self.assertRaises(netguard.UrlRefused, msg=u):
                netguard.check_url(u, resolver=self.fake("93.184.216.34"))

    def test_one_private_answer_among_public_ones_refuses(self):
        res = lambda host, port, **kw: [(2, 1, 6, "", ("93.184.216.34", 0)), (2, 1, 6, "", ("10.1.1.1", 0))]
        with self.assertRaises(netguard.UrlRefused):
            netguard.check_url("https://example.com/", resolver=res)
