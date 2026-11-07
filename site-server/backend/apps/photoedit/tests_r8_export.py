"""دورِ ۸: حالت‌های رنگِ خروجی (سیاه‌وسفید، CMYK، ۲۵۶ رنگ، ۱۶ بیت، Lab، پروفایل sRGB) و SVGِ شکل‌ها. بی شبکه، بی هوش مصنوعی."""
import io
import xml.etree.ElementTree as ET

import cv2
import numpy as np
from django.test import SimpleTestCase
from PIL import Image

from . import exportfmt
from .tests import ApiTestBase, photo

BASE = {"id": "base", "type": "base"}


def sample(w=64, h=48, alpha=False):
    a = np.zeros((h, w, 4 if alpha else 3), np.uint8)
    a[..., 0] = np.linspace(0, 255, w, dtype=np.uint8)[None, :]
    a[..., 1] = np.linspace(0, 255, h, dtype=np.uint8)[:, None]
    a[..., 2] = 77
    if alpha:
        a[..., 3] = 255
        a[:4, :4, 3] = 0
    return Image.fromarray(a, "RGBA" if alpha else "RGB")


def cv_decode(data: bytes):
    return cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_UNCHANGED)


class Depth16Tests(SimpleTestCase):
    def check(self, data, img: Image.Image):
        dec = cv_decode(data)
        self.assertIsNotNone(dec)
        self.assertEqual(dec.dtype, np.uint16)
        src = np.asarray(img)
        self.assertEqual(dec.shape[:2], src.shape[:2])
        # OpenCV BGR(A) ⇒ RGB(A)
        rgb = dec[..., [2, 1, 0] + ([3] if dec.shape[2] == 4 else [])]
        self.assertTrue(np.array_equal(rgb, src.astype(np.uint16) * 257), "هر نمونهٔ ۸بیتی v ⇒ v·۲۵۷")

    def test_png16_rgb_and_rgba(self):
        self.check(exportfmt.png16_bytes(sample()), sample())
        self.check(exportfmt.png16_bytes(sample(alpha=True)), sample(alpha=True))

    def test_tiff16_rgb_rgba_and_many_strips(self):
        self.check(exportfmt.tiff16_bytes(sample()), sample())
        self.check(exportfmt.tiff16_bytes(sample(alpha=True)), sample(alpha=True))
        big = sample(900, 1400)                      # چند نوار (rows_per < ارتفاع)
        data = exportfmt.tiff16_bytes(big)
        self.check(data, big)
        self.assertEqual(data[:4], b"MM\x00\x2a")

    def test_png16_has_srgb_chunk_and_16bit_header(self):
        data = exportfmt.png16_bytes(sample())
        self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual(data[24], 16)                # عمقِ بیت در IHDR
        self.assertIn(b"sRGB", data[:60])

    def test_size_cap(self):
        orig = exportfmt.RGB16_MAX_PIXELS
        exportfmt.RGB16_MAX_PIXELS = 100
        try:
            with self.assertRaises(exportfmt.ExportError):
                exportfmt.png16_bytes(sample())
            with self.assertRaises(exportfmt.ExportError):
                exportfmt.tiff16_bytes(sample())
        finally:
            exportfmt.RGB16_MAX_PIXELS = orig


class ModesTests(SimpleTestCase):
    def conv(self, fmt, mode, img=None):
        return exportfmt.convert(img or sample(), fmt, 90, mode)

    def test_gray_formats(self):
        for fmt in ("png", "tiff", "jpeg", "bmp", "webp"):
            im = Image.open(io.BytesIO(self.conv(fmt, "gray")))
            self.assertIn(im.mode, ("L", "RGB"), fmt)           # BMP/WebP ممکن است ۸بیتی را RGB بخوانند
        g = Image.open(io.BytesIO(self.conv("png", "gray")))
        self.assertEqual(g.mode, "L")
        ga = Image.open(io.BytesIO(self.conv("png", "gray", sample(alpha=True))))
        self.assertEqual(ga.mode, "LA")

    def test_cmyk_roundtrip_and_formats(self):
        for fmt in ("tiff", "jpeg"):
            im = Image.open(io.BytesIO(self.conv(fmt, "cmyk")))
            self.assertEqual(im.mode, "CMYK", fmt)
        self.assertTrue(exportfmt.convert(sample(), "pdf", 90, "cmyk").startswith(b"%PDF"))
        for rgb in ((255, 255, 255), (0, 0, 0), (200, 30, 30), (120, 120, 120), (10, 200, 90)):
            c = exportfmt.rgb_to_cmyk(Image.new("RGB", (4, 4), rgb))
            back = c.convert("RGB").getpixel((1, 1))
            for a, b in zip(rgb, back):
                self.assertAlmostEqual(a, b, delta=3, msg=str(rgb))
        c = exportfmt.rgb_to_cmyk(Image.new("RGB", (2, 2), (0, 0, 0)))
        self.assertEqual(c.getpixel((0, 0)), (0, 0, 0, 255), "سیاه فقط جوهرِ K")
        self.assertEqual(exportfmt.rgb_to_cmyk(Image.new("RGB", (2, 2), (255, 255, 255))).getpixel((0, 0)), (0, 0, 0, 0))

    def test_indexed_has_a_palette(self):
        for fmt in ("png", "gif", "bmp", "tiff"):
            im = Image.open(io.BytesIO(self.conv(fmt, "indexed")))
            self.assertEqual(im.mode, "P", fmt)
            self.assertLessEqual(len(im.getcolors(maxcolors=256) or []), 256)

    def test_lab_tiff(self):
        im = Image.open(io.BytesIO(self.conv("tiff", "lab", Image.new("RGB", (8, 8), (255, 255, 255)))))
        self.assertEqual(im.mode, "LAB")
        L, a, b = im.getpixel((2, 2))
        self.assertGreater(L, 250)

    def test_depth16_through_convert(self):
        self.assertEqual(cv_decode(self.conv("png", "rgb16")).dtype, np.uint16)
        self.assertEqual(cv_decode(self.conv("tiff", "rgb16")).dtype, np.uint16)

    def test_bad_combinations_and_modes(self):
        for fmt, mode in (("png", "cmyk"), ("gif", "gray"), ("jpeg", "rgb16"), ("webp", "indexed"), ("png", "lab")):
            with self.assertRaises(exportfmt.ExportError, msg=f"{fmt}/{mode}") as cm:
                self.conv(fmt, mode)
            self.assertIn("فقط برای این قالب‌ها", str(cm.exception))
        with self.assertRaises(exportfmt.ExportError):
            self.conv("png", "sepia")
        with self.assertRaises(exportfmt.ExportError):
            exportfmt.convert(sample(), "svg", 90)

    def test_srgb_profile_is_embedded_in_rgb_exports(self):
        icc = exportfmt.srgb_profile()
        self.assertTrue(icc and len(icc) > 100)
        for fmt in ("png", "jpeg", "tiff", "webp"):
            im = Image.open(io.BytesIO(self.conv(fmt, "rgb")))
            self.assertEqual(im.info.get("icc_profile"), icc, fmt)


class SvgTests(SimpleTestCase):
    NS = "{http://www.w3.org/2000/svg}"

    def svg(self, layers_):
        data, notes = exportfmt.svg_bytes([BASE] + layers_, 800, 600)
        return ET.fromstring(data), notes, data

    def test_shapes_become_vector_elements(self):
        star = {"closed": True, "pts": [{"x": 0.5, "y": 0, "hi": None, "ho": None}, {"x": 1, "y": 1, "hi": None, "ho": None}, {"x": 0, "y": 1, "hi": None, "ho": None}]}
        root, notes, _data = self.svg([
            {"id": "r1", "type": "shape", "shape": "rect", "name": "کادر", "cx": 0.5, "cy": 0.5, "w": 0.3, "h": 0.2, "radius": 0.5, "rot": 20,
             "fill": {"type": "solid", "color": "#ff0000", "opacity": 0.5}, "stroke": {"color": "#00ff00", "w": 0.01}, "opacity": 0.7, "blend": "multiply"},
            {"id": "e1", "type": "shape", "shape": "ellipse", "cx": 0.2, "cy": 0.2, "w": 0.1, "h": 0.1, "fill": {"type": "gradient", "c0": "#000000", "c1": "#ffffff", "angle": 90}},
            {"id": "l1", "type": "shape", "shape": "line", "cx": 0.5, "cy": 0.9, "w": 0.4, "h": 0, "stroke": {"color": "#0000ff", "w": 0.005}},
            {"id": "p1", "type": "shape", "shape": "path", "cx": 0.7, "cy": 0.3, "w": 0.2, "h": 0.2, "path": star, "fill": {"type": "solid", "color": "#112233", "opacity": 1}},
        ])
        self.assertEqual(root.tag, self.NS + "svg")
        self.assertEqual((root.get("width"), root.get("height"), root.get("viewBox")), ("800", "600", "0 0 800 600"))
        self.assertEqual(len(root.findall(f"{self.NS}g")), 4)
        rect = root.find(f".//{self.NS}rect")
        self.assertEqual((rect.get("width"), rect.get("height")), ("240", "160"))
        self.assertIsNotNone(rect.get("rx"))
        g0 = root.findall(f"{self.NS}g")[0]
        self.assertIn("rotate(20", g0.get("transform"))
        self.assertEqual(g0.get("opacity"), "0.7")
        self.assertIn("multiply", g0.get("style"))
        self.assertEqual(g0.get("data-name"), "کادر")
        self.assertIsNotNone(root.find(f".//{self.NS}linearGradient"))
        path = root.find(f".//{self.NS}path")
        d = path.get("d")
        self.assertTrue(d.startswith("M") and d.endswith("Z"), d)
        self.assertEqual(notes, [])

    def test_bezier_handles_become_cubic_segments(self):
        curved = {"closed": False, "pts": [{"x": 0, "y": 0.5, "hi": None, "ho": [0.2, -0.3]}, {"x": 1, "y": 0.5, "hi": [-0.2, -0.3], "ho": None}]}
        root, _n, _d = self.svg([{"id": "p1", "type": "shape", "shape": "path", "cx": 0.5, "cy": 0.5, "w": 0.5, "h": 0.5, "path": curved, "fill": None, "stroke": {"color": "#fff", "w": 0.004}}])
        d = root.find(f".//{self.NS}path").get("d")
        self.assertIn("C", d)
        self.assertFalse(d.endswith("Z"))

    def test_hidden_shapes_skipped_and_notes(self):
        _root, notes, data = self.svg([
            {"id": "s1", "type": "shape", "shape": "rect", "cx": 0.5, "cy": 0.5, "w": 0.2, "h": 0.2, "fill": {"type": "solid", "color": "#fff", "opacity": 1},
             "fx": {"shadow": {"color": "#000000", "opacity": 0.5, "blur": 0.01, "dx": 0.01, "dy": 0.01}, "glow": None, "stroke": None}},
            {"id": "s2", "type": "shape", "shape": "rect", "visible": False, "cx": 0.1, "cy": 0.1, "w": 0.1, "h": 0.1},
            {"id": "t1", "type": "text", "text": "hello"},
        ])
        self.assertEqual(data.count(b"<g id="), 1)
        joined = " ".join(notes)
        self.assertIn("متن", joined)
        self.assertIn("سایه", joined)

    def test_no_shapes_is_a_clear_error(self):
        with self.assertRaises(exportfmt.ExportError) as cm:
            exportfmt.svg_bytes([BASE, {"id": "t1", "type": "text", "text": "x"}], 100, 100)
        self.assertIn("شکل", str(cm.exception))


class ExportModeApiTests(ApiTestBase):
    def project(self, layers_):
        (aid,) = self.upload(photo(320, 240))
        r = self.api.post(f"{self.base}/projects/", {"asset": aid, "title": "خروجیِ رنگ", "data": {"layers": layers_}}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        return r.json()["project"]["id"]

    def test_modes_download_and_names_carry_the_mode(self):
        pid = self.project([BASE])
        for fmt, mode, mime in (("tiff", "cmyk", "image/tiff"), ("png", "gray", "image/png"), ("png", "indexed", "image/png"), ("png", "rgb16", "image/png"),
                                ("tiff", "rgb16", "image/tiff"), ("tiff", "lab", "image/tiff"), ("jpeg", "cmyk", "image/jpeg")):
            r = self.api.get(f"{self.base}/projects/{pid}/export/?fmt={fmt}&mode={mode}")
            self.assertEqual(r.status_code, 200, (fmt, mode, r.content[:200]))
            self.assertEqual(r["Content-Type"], mime)
            self.assertIn(mode, r["Content-Disposition"])
            self.assertGreater(len(r.content), 200)

    def test_bad_mode_and_combo_are_400_in_persian(self):
        pid = self.project([BASE])
        for q in ("fmt=png&mode=cmyk", "fmt=png&mode=zzz", "fmt=psd&mode=gray", "fmt=svg&mode=gray"):
            r = self.api.get(f"{self.base}/projects/{pid}/export/?{q}")
            self.assertEqual(r.status_code, 400, q)
            self.assertTrue(r.json()["error"]["message"], q)

    def test_svg_download(self):
        pid = self.project([BASE, {"id": "s1", "type": "shape", "shape": "ellipse", "cx": 0.5, "cy": 0.5, "w": 0.4, "h": 0.3, "fill": {"type": "solid", "color": "#e11d48", "opacity": 1}}])
        r = self.api.get(f"{self.base}/projects/{pid}/export/?fmt=svg")
        self.assertEqual(r.status_code, 200, r.content[:200])
        self.assertEqual(r["Content-Type"], "image/svg+xml")
        self.assertIn(".svg", r["Content-Disposition"])
        root = ET.fromstring(r.content)
        self.assertEqual(len(root.findall("{http://www.w3.org/2000/svg}g")), 1)
        none = self.project([BASE])
        r2 = self.api.get(f"{self.base}/projects/{none}/export/?fmt=svg")
        self.assertEqual(r2.status_code, 400)
        self.assertIn("شکل", r2.json()["error"]["message"])
