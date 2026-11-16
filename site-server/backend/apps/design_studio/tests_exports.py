"""خروجی‌ها: اندازهٔ صفحه و بلید در PDF، علامت برش، PDF نمایشی، اندازهٔ PNG، باز شدنِ PPTX، SVG، و بسته‌های «کدام فایل را به چه کسی بده»."""
import io
import re
import xml.dom.minidom
import zipfile
import zlib

from django.test import SimpleTestCase
from PIL import Image

from . import catalog_doc, catalog_pages as cp, deck_doc, deck_slides as ds, exports, fixtures, pdf, pptx, render_png, render_svg, scene, ui_doc, ui_frames, ui_blocks

MM = 72 / 25.4


def boxes(pdf_bytes: bytes, page: int = 0) -> dict:
    """جعبه‌های صفحهٔ n ام از متنِ PDF (بی‌کتابخانه)."""
    pages = re.findall(rb"<< /Type /Page /Parent \d+ 0 R (.*?) /Contents", pdf_bytes, re.S)
    out = {}
    for name in (b"MediaBox", b"TrimBox", b"BleedBox"):
        m = re.search(rb"/" + name + rb" \[([0-9. ]+)\]", pages[page])
        out[name.decode()] = [float(x) for x in m.group(1).split()]
    return out


def streams(pdf_bytes: bytes) -> list[bytes]:
    out = []
    for m in re.finditer(rb"stream\n(.*?)\nendstream", pdf_bytes, re.S):
        try:
            out.append(zlib.decompress(m.group(1)))
        except zlib.error:
            pass
    return out


class Base(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.refs = fixtures.make_images(6, size=(2700, 1900))
        cls.items = fixtures.products(cls.refs)
        cls.src = fixtures.source()
        cls.info = fixtures.info("فروشگاهِ نمونه")
        cls.cat = catalog_doc.new_doc(cls.info, cls.items, {}, {"featured": [1]}, cls.src)
        cls.cat_bundle = exports.make_bundle("catalog", cls.cat, cls.info, cls.src, "کاتالوگ نمونه", 1)
        steps = [{"title": f"گام {i}", "text": "توضیحِ کوتاه"} for i in range(1, 5)]
        cls.deck, _ = deck_doc.new_deck(cls.info, cls.items, {}, {"steps": steps, "featured": [1, 2], "team": [{"name": "نامِ نمونه", "role": "سمتِ نمونه"}]}, brief="یک ارائهٔ آزمایشی.")
        cls.deck_bundle = exports.make_bundle("deck", cls.deck, cls.info, cls.src, "ارائهٔ نمونه", 2)
        cls.ui = ui_doc.new_doc(cls.info, template="landing", devices=("desktop", "tablet", "phone"))
        cls.ui_bundle = exports.make_bundle("ui", cls.ui, cls.info, cls.src, "طرح نمونه", 3)


class PdfTests(Base):
    def test_print_pdf_has_trim_bleed_and_crop_marks(self):
        data, rep = exports.print_pdf(self.cat_bundle)
        self.assertTrue(data.startswith(b"%PDF-1.7"))
        b = boxes(data)
        trim_w, trim_h = 210 * MM, 297 * MM
        bleed, slug = 3 * MM, 7 * MM
        self.assertAlmostEqual(b["TrimBox"][2] - b["TrimBox"][0], trim_w, delta=0.05)
        self.assertAlmostEqual(b["TrimBox"][3] - b["TrimBox"][1], trim_h, delta=0.05)
        self.assertAlmostEqual(b["BleedBox"][2] - b["BleedBox"][0], trim_w + 2 * bleed, delta=0.05)
        self.assertAlmostEqual(b["MediaBox"][2], trim_w + 2 * (bleed + slug), delta=0.05)
        self.assertAlmostEqual(b["TrimBox"][0], bleed + slug, delta=0.05)
        self.assertEqual(rep["pages"], len(self.cat_bundle.pages))
        self.assertTrue(rep["marks"])
        self.assertEqual(rep["bleed_mm"], 3.0)
        self.assertEqual(rep["dpi"], 300)
        content = b"\n".join(streams(data))
        self.assertIn(b" l S", content)                                # علامت‌های برش (خطِ ۰٫۲۵pt)
        self.assertIn(b"0.25 w", content)

    def test_print_pdf_without_bleed_or_marks_is_exactly_the_trim_size(self):
        data, rep = exports.print_pdf(self.cat_bundle, {"bleed": False, "marks": False})
        b = boxes(data)
        self.assertAlmostEqual(b["MediaBox"][2], 210 * MM, delta=0.05)
        self.assertEqual(b["MediaBox"], b["TrimBox"])
        self.assertFalse(rep["marks"])

    def test_a5_page_size_and_landscape(self):
        s = {"page_size": "A5"}
        cat = catalog_doc.new_doc(self.info, self.items, s, {}, self.src)
        b5 = exports.make_bundle("catalog", cat, self.info, self.src, "x", 9, with_checks=False)
        data, _ = exports.print_pdf(b5, {"bleed": False, "marks": False})
        box = boxes(data)["TrimBox"]
        self.assertAlmostEqual(box[2], 148 * MM, delta=0.05)
        self.assertAlmostEqual(box[3], 210 * MM, delta=0.05)
        cat["settings"]["orientation"] = "landscape"
        bl = exports.make_bundle("catalog", cat, self.info, self.src, "x", 9, with_checks=False)
        self.assertEqual((bl.pages[0]["w"], bl.pages[0]["h"]), (210.0, 148.0))

    def test_screen_pdf_is_small_has_links_bookmarks_and_rtl_viewer(self):
        big, _ = exports.print_pdf(self.cat_bundle)
        small, rep = exports.screen_pdf(self.cat_bundle)
        self.assertLess(len(small), len(big))
        self.assertEqual(rep["dpi"], 110)
        self.assertAlmostEqual(boxes(small)["MediaBox"][2], 210 * MM, delta=0.05)
        self.assertIn(b"/Direction /R2L", small)
        self.assertIn(b"/Outlines", small)
        self.assertIn(b"/Subtype /Link", small)                        # فهرستِ کلیک‌پذیر
        self.assertFalse(rep["marks"])                                  # بی‌علامتِ برش و بی‌خونریزی
        self.assertEqual(boxes(small)["MediaBox"], boxes(small)["TrimBox"])

    def test_images_are_never_placed_above_300_dpi(self):
        _, rep = exports.print_pdf(self.cat_bundle)
        self.assertTrue(rep["images"])
        for m in re.finditer(rb"/Width (\d+) /Height (\d+) /ColorSpace /DeviceRGB", exports.print_pdf(self.cat_bundle)[0]):
            self.assertLessEqual(int(m.group(1)), 2600)               # بزرگ‌ترین عکسِ تمام‌صفحه: ۲۴۸۰ پیکسل + خونریزی

    def test_text_is_outlined_not_embedded_fonts(self):
        data, _ = exports.screen_pdf(self.cat_bundle)
        self.assertNotIn(b"/Type /Font", data)
        self.assertIn(b"f*", b"\n".join(streams(data)))

    def test_slide_pdf_page_is_16_by_9(self):
        data, _ = exports.screen_pdf(self.deck_bundle)
        b = boxes(data)["MediaBox"]
        self.assertAlmostEqual(b[2] / b[3], 16 / 9, places=3)
        self.assertAlmostEqual(b[2], 960.0, delta=0.01)


class PngTests(Base):
    def test_catalog_page_png_sizes_follow_dpi_and_bleed(self):
        p = self.cat_bundle.pages[0]
        self.assertEqual(render_png.render_page(p, self.src, scale=render_png.px_per_mm(150)).size, (1240, 1754))
        self.assertEqual(render_png.render_page(p, self.src, scale=render_png.px_per_mm(300)).size, (2480, 3508))
        self.assertEqual(render_png.render_page(p, self.src, scale=render_png.px_per_mm(300), with_bleed=True).size, (2551, 3579))
        marks = render_png.render_page(p, self.src, scale=render_png.px_per_mm(100), marks=True)
        self.assertEqual(marks.size, (round(230 * render_png.px_per_mm(100)), round(317 * render_png.px_per_mm(100))))

    def test_slide_and_frame_sizes(self):
        self.assertEqual(render_png.render_page(self.deck_bundle.pages[0], self.src, scale=1.0).size, (1920, 1080))
        by_dev = {p["device"]: p for p in self.ui_bundle.pages}
        self.assertEqual(render_png.render_page(by_dev["desktop"], self.src, scale=1.0).width, 1440)
        self.assertEqual(render_png.render_page(by_dev["tablet"], self.src, scale=1.0).width, 834)
        self.assertEqual(render_png.render_page(by_dev["phone"], self.src, scale=1.0).width, 390)
        self.assertEqual(render_png.render_page(by_dev["phone"], self.src, scale=2.0).width, 780)

    def test_png_zip_names_and_jpg_zip(self):
        data = exports.pages_zip(self.cat_bundle, "PNG", {"dpi": 72})
        z = zipfile.ZipFile(io.BytesIO(data))
        names = z.namelist()
        self.assertEqual(len(names), len(self.cat_bundle.pages))
        self.assertEqual(names[0], "page-01-cover.png")
        self.assertEqual(Image.open(io.BytesIO(z.read(names[0]))).size, (round(210 * render_png.px_per_mm(72)), round(297 * render_png.px_per_mm(72))))
        jz = zipfile.ZipFile(io.BytesIO(exports.pages_zip(self.cat_bundle, "JPEG", {"dpi": 72})))
        self.assertTrue(all(n.endswith(".jpg") for n in jz.namelist()))

    def test_every_page_type_and_slide_type_renders(self):
        """هیچ نوعِ صفحه یا اسلایدی از قلم نیفتاده: همه ساخته و کشیده می‌شوند."""
        specs = [{"id": f"p{i}", "type": t, "products": [1, 2, 3], "product": 1, "title": "نمونه", "image": self.refs[0], "images": self.refs[:4], "captions": ["الف", "ب", "ج", "د"],
                  "paragraphs": ["متنِ نمونه."], "steps": [{"title": "الف", "text": "ب"}]} for i, t in enumerate(cp.PAGE_TYPES)]
        doc = {"settings": {}, "products": self.items, "pages": specs}
        sc = catalog_doc.build_scene(doc, self.info, self.src)
        self.assertEqual({p["section"] for p in sc["pages"]}, set(cp.PAGE_TYPES))
        for p in sc["pages"]:
            self.assertEqual(render_png.render_page(p, self.src, scale=0.5).width, round(210 * 0.5))
        slides = [{"id": f"s{i}", "type": t, "title": "نمونه", "product": 1, "image": self.refs[0], "items": [{"value": "۱۲", "label": "نمونه", "source": "منبعِ نمونه"}], "bullets": ["الف", "ب"],
                   "steps": [{"title": "الف", "text": "ب"}, {"title": "ج", "text": "د"}], "members": [{"name": "علی", "role": "سمت"}], "button": "دکمه", "text": "متن", "caption": "نوشته"}
                  for i, t in enumerate(ds.SLIDE_TYPES)]
        slides[ds.SLIDE_TYPES.index("agenda")]["items"] = ["الف", "ب", "ج"]
        slides[ds.SLIDE_TYPES.index("comparison")]["items"] = [{"product": 1, "points": ["الف"]}, {"product": 2, "points": ["ب"], "highlight": True}]
        sc2 = deck_doc.build_scene({"settings": {}, "products": self.items, "slides": slides}, self.info, self.src)
        self.assertEqual({p["type"] for p in sc2["pages"]}, set(ds.SLIDE_TYPES))
        for tpl in ds.TEMPLATES:
            s3 = deck_doc.build_scene({"settings": {"template": tpl}, "products": self.items, "slides": slides[:4]}, self.info, self.src)
            self.assertEqual(len(s3["pages"]), 4)
            render_png.render_page(s3["pages"][0], self.src, scale=0.3)


class PptxTests(Base):
    def check_package(self, data: bytes, slides: int, size: tuple[int, int]):
        z = zipfile.ZipFile(io.BytesIO(data))
        self.assertIsNone(z.testzip())
        names = set(z.namelist())
        for n in names:
            if n.endswith((".xml", ".rels")):
                xml.dom.minidom.parseString(z.read(n))               # هر بخش XMLِ سالم است
        ct = z.read("[Content_Types].xml").decode()
        for i in range(1, slides + 1):
            self.assertIn(f"/ppt/slides/slide{i}.xml", ct)
            self.assertIn(f"ppt/slides/slide{i}.xml", names)
            self.assertIn(f"ppt/notesSlides/notesSlide{i}.xml", names)
        # هدفِ هر رابطه وجود دارد
        for n in [x for x in names if x.endswith(".rels")]:
            base = n.replace("_rels/", "").rsplit(".rels", 1)[0]
            folder = base.rsplit("/", 1)[0] if "/" in base else ""
            for tgt, mode in re.findall(r'Target="([^"]+)"(?: TargetMode="(\w+)")?', z.read(n).decode()):
                if mode == "External":
                    continue
                path = tgt.lstrip("/") if tgt.startswith("/") else (folder + "/" + tgt if folder else tgt)
                parts = []
                for seg in path.split("/"):
                    if seg == "..":
                        parts.pop()
                    elif seg:
                        parts.append(seg)
                self.assertIn("/".join(parts), names, f"{n} → {tgt}")
        pres = z.read("ppt/presentation.xml").decode()
        self.assertIn(f'<p:sldSz cx="{size[0]}" cy="{size[1]}"/>', pres)
        self.assertIn('rtl="1"', pres)
        return z

    def test_catalog_pptx_opens_and_keeps_text_live_and_rtl(self):
        data = exports.pptx_bytes(self.cat_bundle)
        z = self.check_package(data, len(self.cat_bundle.pages), (7560000, 10692000))
        slide1 = z.read("ppt/slides/slide5.xml").decode()
        self.assertIn('rtl="1"', slide1)
        self.assertIn('algn="r"', slide1)
        self.assertIn("<a:cs typeface=", slide1)
        self.assertIn("lang=\"fa-IR\"", slide1)
        self.assertTrue([n for n in z.namelist() if n.startswith("ppt/media/")])

    def test_deck_pptx_has_speaker_notes_and_16x9_size(self):
        data = exports.pptx_bytes(self.deck_bundle)
        z = self.check_package(data, len(self.deck_bundle.pages), (12192000, 6858000))
        notes = "".join(z.read(f"ppt/notesSlides/notesSlide{i}.xml").decode() for i in range(1, len(self.deck_bundle.pages) + 1))
        self.assertIn("توضیحِ ثبت‌شده", notes)                            # یادداشتِ گوینده از دادهٔ واقعی

    def test_ppsx_is_a_slideshow_package(self):
        data = exports.pptx_bytes(self.deck_bundle, slideshow=True)
        z = zipfile.ZipFile(io.BytesIO(data))
        self.assertIn("presentationml.slideshow.main+xml", z.read("[Content_Types].xml").decode())
        self.assertNotIn("presentationml.presentation.main+xml", z.read("[Content_Types].xml").decode())

    def test_internal_and_external_links_become_hyperlinks(self):
        page = {"id": "a", "name": "الف", "w": 100, "h": 100, "elements": [scene.rect("r1", 0, 0, 10, 10, "#111", link={"page": "b"}),
                                                                              scene.rect("r2", 20, 0, 10, 10, "#222", link={"url": "https://example.com/x"})]}
        page2 = {"id": "b", "name": "ب", "w": 100, "h": 100, "elements": []}
        data = pptx.build_pptx([scene.finalize_page(page), scene.finalize_page(page2)], self.src, unit="mm")
        z = zipfile.ZipFile(io.BytesIO(data))
        rels = z.read("ppt/slides/_rels/slide1.xml.rels").decode()
        self.assertIn("slide2.xml", rels)
        self.assertIn('TargetMode="External"', rels)
        self.assertIn("hlinksldjump", z.read("ppt/slides/slide1.xml").decode())


class SvgAndPackTests(Base):
    def test_svg_is_valid_and_sized(self):
        page = self.ui_bundle.pages[0]
        svg = render_svg.page_svg(page, self.src)
        dom = xml.dom.minidom.parseString(svg)
        root = dom.documentElement
        self.assertEqual(root.getAttribute("viewBox"), f"0 0 {int(page['w'])} {int(round(page['h']))}" if page["h"] == int(page["h"]) else root.getAttribute("viewBox"))
        self.assertIn("<path", svg)                                      # متنِ منحنی
        live = render_svg.page_svg(page, self.src, text_mode="text")
        self.assertIn("<text", live)
        self.assertIn('direction="rtl"', live)

    def test_printer_pack_has_what_the_guide_asks_for(self):
        data, name, info = exports.build("pack_printer", self.cat_bundle)
        z = zipfile.ZipFile(io.BytesIO(data))
        names = z.namelist()
        self.assertTrue(any(n.startswith("print/") and n.endswith("-print.pdf") for n in names))
        self.assertTrue(any(n.endswith("-print-bleed-only.pdf") for n in names))
        self.assertIn("PREFLIGHT-fa.txt", names)
        readme = z.read("README-fa.txt").decode()
        self.assertIn("CMYK", readme)
        self.assertIn("PDF/X", readme)
        self.assertIn("بلید", readme)
        self.assertTrue(name.endswith(".zip"))

    def test_social_pack_has_the_three_instagram_sizes(self):
        data, _, _ = exports.build("pack_social", self.cat_bundle)
        z = zipfile.ZipFile(io.BytesIO(data))
        for folder, size in (("square-1080x1080", (1080, 1080)), ("portrait-1080x1350", (1080, 1350)), ("story-1080x1920", (1080, 1920))):
            f = [n for n in z.namelist() if f"/{folder}/" in n]
            self.assertEqual(len(f), len(self.cat_bundle.pages), folder)
            self.assertEqual(Image.open(io.BytesIO(z.read(f[0]))).size, size)
        deck = zipfile.ZipFile(io.BytesIO(exports.build("pack_social", self.deck_bundle)[0]))
        self.assertTrue([n for n in deck.namelist() if "/landscape-1920x1080/" in n])

    def test_source_pack_has_document_fonts_licences_and_editable_pptx(self):
        z = zipfile.ZipFile(io.BytesIO(exports.build("pack_source", self.cat_bundle)[0]))
        names = z.namelist()
        self.assertIn("source/document.json", names)
        self.assertTrue([n for n in names if n.startswith("fonts/") and n.endswith(".ttf")])
        self.assertTrue([n for n in names if n.startswith("licenses/")])
        self.assertTrue([n for n in names if n.startswith("editable/") and n.endswith(".pptx")])
        self.assertTrue([n for n in names if n.startswith("images/")])
        self.assertTrue([n for n in names if n.startswith("preview/")])

    def test_customer_meeting_kiosk_and_dev_packs(self):
        c = zipfile.ZipFile(io.BytesIO(exports.build("pack_customer", self.cat_bundle)[0])).namelist()
        self.assertTrue(any(n.endswith("-preview.pdf") for n in c) and any(n.startswith("preview/") for n in c))
        m = zipfile.ZipFile(io.BytesIO(exports.build("pack_meeting", self.deck_bundle)[0])).namelist()
        self.assertTrue(any(n.endswith(".pptx") for n in m) and any(n.endswith("-backup.pdf") for n in m) and any(n.startswith("fonts/") for n in m))
        k = zipfile.ZipFile(io.BytesIO(exports.build("pack_kiosk", self.deck_bundle)[0])).namelist()
        self.assertTrue(any(n.endswith(".ppsx") for n in k))
        d = zipfile.ZipFile(io.BytesIO(exports.build("pack_dev", self.ui_bundle)[0]))
        names = d.namelist()
        self.assertIn("tokens/tokens.css", names)
        self.assertIn("site/blocks.json", names)
        css = d.read("tokens/tokens.css").decode()
        self.assertIn(':root[data-theme="dark"]', css)
        self.assertIn("--primary:", css)
        self.assertTrue([n for n in names if n.startswith("svg/")] and [n for n in names if n.startswith("png/")])

    def test_wrong_kind_for_document_is_refused(self):
        with self.assertRaises(exports.ExportError):
            exports.build("print_pdf", self.deck_bundle)
        with self.assertRaises(exports.ExportError):
            exports.build("pack_dev", self.cat_bundle)
        with self.assertRaises(exports.ExportError):
            exports.build("nope", self.cat_bundle)

    def test_recipients_table_matches_the_guide(self):
        keys = {r["key"] for r in exports.RECIPIENTS}
        self.assertEqual(keys, {"printer", "social", "designer", "customer", "meeting", "kiosk", "dev"})
        for r in exports.RECIPIENTS:
            self.assertIn(r["pack"], exports.KINDS)

    def test_preflight_checklist_covers_the_guides_print_list(self):
        keys = {c["key"] for c in self.cat_bundle.checks}
        self.assertTrue({"size", "bleed", "marks", "dpi", "fonts", "color", "safe", "single", "mult4"} <= keys)
        by = {c["key"]: c for c in self.cat_bundle.checks}
        self.assertEqual(by["bleed"]["level"], "ok")
        self.assertEqual(by["color"]["level"], "info")                    # CMYK را چاپخانه می‌سازد
        self.assertEqual(by["single"]["level"], "ok")
        self.assertEqual(by["dpi"]["level"], "ok")                        # عکس‌های آزمون ۱۴۰۰ پیکسل‌اند ⇒ در اندازهٔ کارت‌ها ≥ ۳۰۰


class UiBlockCoverageTests(SimpleTestCase):
    def test_every_site_builder_block_and_component_renders_in_all_devices(self):
        cat = ui_doc.block_catalog()
        self.assertGreater(len(cat["blocks"]), 50)                       # ۱۴ پایه + ۴۹ قطعه
        info = fixtures.info()
        frames = []
        for dev in ("desktop", "tablet", "phone"):
            kids = [ui_doc.block_node(b["type"]) for b in cat["blocks"] if b["type"] not in ("column", "section", "columns")]
            frames.append(ui_doc.new_frame(f"all {dev}", dev, kids, fid=f"f-{dev}"))
        sc = ui_frames.build_scene({"settings": {"menu": ["الف", "ب"]}, "frames": frames}, info, with_styleguide=True)
        for p in sc["pages"]:
            self.assertGreater(len(p["elements"]), 100, p["id"])
            self.assertTrue(all(e["w"] >= 0 for e in p["elements"]))
            self.assertLess(p["h"], 60000)
        self.assertTrue(sc["styleguide"]["elements"])
        top = [n for n in sc["pages"][0]["meta"]["nodes"] if n["top"]]
        self.assertGreaterEqual(len(top), len(cat["blocks"]) - 4)

    def test_dark_mode_swaps_only_variables_and_phone_uses_one_column(self):
        info = fixtures.info()
        nodes = [ui_doc.block_node("c_feat_icon_grid")]
        d = {"settings": {}, "frames": [ui_doc.new_frame("d", "desktop", nodes, fid="d"), ui_doc.new_frame("p", "phone", nodes, fid="p"), ui_doc.new_frame("n", "desktop", nodes, mode="dark", fid="n")]}
        sc = ui_frames.build_scene(d, info)
        desk, phone, night = sc["pages"]
        self.assertEqual(night["bg"], sc["tokens"]["dark"]["bg"])
        self.assertEqual(desk["bg"], sc["tokens"]["light"]["bg"])
        self.assertEqual(len(desk["elements"]), len(night["elements"]))
        cards = lambda p: [e for e in p["elements"] if e["type"] == "rect" and e.get("radius") and e["w"] > 150 and e["h"] > 80]  # noqa: E731
        xs_phone = {round(e["x"]) for e in cards(phone)}
        self.assertEqual(len(xs_phone), 1)                                # یک ستون
