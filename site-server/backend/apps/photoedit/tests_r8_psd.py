"""دورِ ۸: بازکردنِ PSD — خوانندهٔ همه‌منظوره (خام، RLE، ZIP، ZIP با پیش‌بینی، ۱۶ بیت، خاکستری، گروه‌ها) و درون‌ریزی به پروژه. بی شبکه."""
import io
import struct
import zlib

import numpy as np
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase
from PIL import Image

from . import psd, psd_read
from .models import PhotoAsset, PhotoProject
from .tests import ApiTestBase

Z = bytes(1)


def packbits(data: bytes) -> bytes:
    out, i, n = bytearray(), 0, len(data)
    while i < n:
        j = i + 1
        while j < n and j - i < 128 and data[j] == data[i]:
            j += 1
        if j - i >= 3:
            out += bytes([257 - (j - i), data[i]])
            i = j
        else:
            k = i
            while k < n and k - i < 128 and not (k + 2 < n and data[k] == data[k + 1] == data[k + 2]):
                k += 1
            k = max(k, i + 1)
            out += bytes([k - i - 1]) + data[i:k]
            i = k
    return bytes(out)


def channel(plane: np.ndarray, comp: int, depth: int = 8) -> bytes:
    h, w = plane.shape
    if depth == 16:
        raw = (plane.astype(np.uint16) * 257).astype(">u2").tobytes()
    else:
        raw = plane.astype(np.uint8).tobytes()
    if comp == 0:
        return struct.pack(">H", 0) + raw
    if comp == 1:
        bpr = w * (2 if depth == 16 else 1)
        rows = [packbits(raw[r * bpr:(r + 1) * bpr]) for r in range(h)]
        return struct.pack(">H", 1) + b"".join(struct.pack(">H", len(x)) for x in rows) + b"".join(rows)
    if comp == 2:
        return struct.pack(">H", 2) + zlib.compress(raw)
    d = plane.astype(np.int16).copy()
    d[:, 1:] = (plane[:, 1:].astype(np.int16) - plane[:, :-1].astype(np.int16)) % 256
    return struct.pack(">H", 3) + zlib.compress(d.astype(np.uint8).tobytes())


def pascal(name: str) -> bytes:
    b = name.encode("latin-1", "replace")[:30]
    s = bytes([len(b)]) + b
    return s + bytes((-len(s)) % 4)


def luni(name: str) -> bytes:
    u = name.encode("utf-16-be")
    body = struct.pack(">I", len(name)) + u
    body += bytes((-len(body)) % 4)
    return b"8BIM" + b"luni" + struct.pack(">I", len(body)) + body


def lsct(kind: int) -> bytes:
    return b"8BIM" + b"lsct" + struct.pack(">I", 4) + struct.pack(">I", kind)


def mk_psd(W, H, layer_specs, *, mode=3, depth=8, comp=1, merged=None, merged_comp=0, version=1):
    """layer_specs: [{name, x, y, rgba (h,w,4) uint8, opacity, key, visible, kind}] ⇒ بایت‌های PSD."""
    nplanes = 3 if mode == 3 else 1
    head = b"8BPS" + struct.pack(">H", version) + bytes(6) + struct.pack(">HIIHH", nplanes, H, W, depth, mode)
    recs, data = bytearray(), bytearray()
    for L in layer_specs:
        rgba = L.get("rgba")
        kind = L.get("kind", 0)
        if rgba is None:
            h = w = 0
            chans = []
        else:
            h, w = rgba.shape[:2]
            order = [(-1, 3), (0, 0), (1, 1), (2, 2)] if mode == 3 else [(-1, 3), (0, 0)]
            chans = [(cid, channel(rgba[..., src], comp, depth)) for cid, src in order]
        x, y = L.get("x", 0), L.get("y", 0)
        recs += struct.pack(">iiii", y, x, y + h, x + w) + struct.pack(">H", len(chans))
        for cid, blob in chans:
            recs += struct.pack(">hI", cid, len(blob))
        recs += b"8BIM" + L.get("key", b"norm") + struct.pack(">BBBB", int(round(L.get("opacity", 1.0) * 255)), 0, 0 if L.get("visible", True) else 2, 0)
        extra = struct.pack(">I", 0) + struct.pack(">I", 0) + pascal(L["name"].encode("ascii", "ignore").decode() or "L") + luni(L["name"])
        if kind:
            extra += lsct(kind)
        recs += struct.pack(">I", len(extra)) + extra
        for _cid, blob in chans:
            data += blob
    info = struct.pack(">h", len(layer_specs)) + bytes(recs) + bytes(data)
    if len(info) % 2:
        info += Z
    sec = struct.pack(">I", len(info)) + info + struct.pack(">I", 0)
    out = head + struct.pack(">I", 0) + struct.pack(">I", 0) + struct.pack(">I", len(sec)) + sec
    if merged is None:
        merged = np.full((H, W, 3), 128, np.uint8)
    if merged_comp == 1:
        planes = [merged[..., c] for c in range(nplanes)]
        bpr = W * (2 if depth == 16 else 1)
        rows_all = []
        for pl in planes:
            raw = (pl.astype(np.uint16) * 257).astype(">u2").tobytes() if depth == 16 else pl.astype(np.uint8).tobytes()
            rows_all += [packbits(raw[r * bpr:(r + 1) * bpr]) for r in range(H)]
        out += struct.pack(">H", 1) + b"".join(struct.pack(">H", len(r)) for r in rows_all) + b"".join(rows_all)
    else:
        out += struct.pack(">H", 0)
        for c in range(nplanes):
            pl = merged[..., c]
            out += (pl.astype(np.uint16) * 257).astype(">u2").tobytes() if depth == 16 else pl.astype(np.uint8).tobytes()
    return out


def rgba_block(w, h, color):
    a = np.zeros((h, w, 4), np.uint8)
    a[...] = color
    return a


def gradient_block(w, h):
    a = np.zeros((h, w, 4), np.uint8)
    a[..., 0] = np.linspace(0, 255, w, dtype=np.uint8)[None, :]
    a[..., 1] = np.linspace(255, 0, h, dtype=np.uint8)[:, None]
    a[..., 2] = 90
    a[..., 3] = 255
    return a


class PackBitsTests(SimpleTestCase):
    def test_roundtrip_and_tolerance(self):
        rng = np.random.default_rng(5)
        for data in (b"", b"a", b"aaaaaaaaaa", bytes(rng.integers(0, 255, 600, dtype=np.uint8)), b"ab" * 100 + b"c" * 300):
            self.assertEqual(psd_read.unpackbits(packbits(data), len(data)), data)
        self.assertEqual(psd_read.unpackbits(b"\x01", 4), bytes(4), "داده‌ی کوتاه با صفر پر می‌شود و خطا نمی‌دهد")


class ReaderTests(SimpleTestCase):
    def read_back(self, comp, depth=8):
        grad = gradient_block(40, 30)
        red = rgba_block(12, 8, (255, 0, 0, 200))
        raw = mk_psd(64, 48, [{"name": "پس‌زمینه", "x": 5, "y": 4, "rgba": grad}, {"name": "قرمز", "x": 30, "y": 20, "rgba": red, "opacity": 0.5, "key": b"mul ", "visible": False}],
                     comp=comp, depth=depth, merged_comp=1 if comp == 1 else 0)
        return psd_read.read_psd_full(raw), grad, red

    def test_all_compressions_give_the_same_pixels(self):
        for comp in (0, 1, 2, 3):
            doc, grad, red = self.read_back(comp)
            self.assertEqual(doc.size, (64, 48), comp)
            self.assertEqual([l.name for l in doc.layers], ["پس‌زمینه", "قرمز"], comp)
            a, b = doc.layers
            self.assertTrue(np.array_equal(a.rgba, grad), f"comp {comp}")
            self.assertTrue(np.array_equal(b.rgba, red), f"comp {comp}")
            self.assertEqual((a.x, a.y, b.x, b.y), (5, 4, 30, 20))
            self.assertAlmostEqual(b.opacity, 0.5, delta=0.01)
            self.assertEqual((a.blend, b.blend, a.visible, b.visible), ("normal", "multiply", True, False))
            self.assertEqual(doc.merged.shape, (48, 64, 3))

    def test_16_bit_is_reduced_to_8_bit(self):
        doc, grad, _red = self.read_back(0, depth=16)
        self.assertTrue(np.array_equal(doc.layers[0].rgba, grad))

    def test_grayscale_and_groups(self):
        gray = np.zeros((10, 10, 4), np.uint8)
        gray[..., 0] = 77
        gray[..., 3] = 255
        raw = mk_psd(20, 20, [
            {"name": "</Layer group>", "kind": 3},
            {"name": "داخلِ گروه", "x": 2, "y": 2, "rgba": gray},
            {"name": "گروه", "kind": 1},
            {"name": "تنظیم", "rgba": None},
        ], mode=1, comp=1)
        doc = psd_read.read_psd_full(raw)
        self.assertEqual([l.name for l in doc.layers], ["داخلِ گروه"], "نشانگرهای گروه و لایهٔ بی‌پیکسل نمی‌آیند")
        self.assertEqual(tuple(doc.layers[0].rgba[0, 0]), (77, 77, 77, 255))
        self.assertTrue(any("پیکسل نداشت" in n for n in doc.notes))

    def test_writer_output_of_this_project_is_readable(self):
        merged = Image.new("RGB", (30, 20), (9, 9, 9))
        raw = psd.write_psd((30, 20), merged, [psd.PsdLayer("لایه", Image.new("RGBA", (10, 10), (1, 2, 3, 255)), x=3, y=2, opacity=0.8, blend="screen")])
        doc = psd_read.read_psd_full(raw)
        self.assertEqual((doc.layers[0].name, doc.layers[0].blend, doc.layers[0].x), ("لایه", "screen", 3))
        self.assertEqual(tuple(doc.merged[0, 0]), (9, 9, 9))

    def test_unsupported_files_get_persian_errors(self):
        for bad, frag in ((b"nope", "PSD نیست"), (mk_psd(8, 8, [], mode=4), "CMYK"), (mk_psd(8, 8, [], version=2), "PSB")):
            with self.assertRaises(psd_read.PsdReadError) as cm:
                psd_read.read_psd_full(bad)
            self.assertIn(frag, str(cm.exception))
        with self.assertRaises(psd_read.PsdReadError):
            psd_read.read_psd_full(b"8BPS" + struct.pack(">H", 1) + bytes(6) + struct.pack(">HIIHH", 3, 40000, 40000, 8, 3))


class ImportApiTests(ApiTestBase):
    def post(self, raw, name="کار.psd"):
        return self.api.post(f"{self.base}/psd/import/", {"file": SimpleUploadedFile(name, raw, content_type="application/octet-stream")}, format="multipart")

    def test_layers_become_paint_layers_in_a_new_project(self):
        raw = mk_psd(64, 48, [{"name": "پس‌زمینه", "rgba": gradient_block(64, 48)},
                              {"name": "قرمز", "x": 30, "y": 20, "rgba": rgba_block(12, 8, (255, 0, 0, 255)), "opacity": 0.5, "key": b"mul ", "visible": False}])
        r = self.post(raw)
        self.assertEqual(r.status_code, 201, r.content)
        j = r.json()
        self.assertEqual(j["layers"], 2)
        self.assertTrue(PhotoAsset.objects.filter(pk=j["asset"]["id"]).exists())
        proj = PhotoProject.objects.get(pk=j["project"])
        ls = proj.data["layers"]
        self.assertEqual([l["type"] for l in ls], ["base", "image", "image"])
        self.assertEqual([l["name"] for l in ls[1:]], ["پس‌زمینه", "قرمز"])
        self.assertEqual((ls[2]["blend"], ls[2]["visible"]), ("multiply", False))
        self.assertAlmostEqual(ls[2]["opacity"], 0.5, delta=0.01)
        full = self.api.get(f"{self.base}/projects/{proj.pk}/").json()["project"]
        self.assertEqual(len(full["paints"]), 2)
        pid = ls[2]["src"]["id"]
        png = self.api.get(f"{self.base}/projects/{proj.pk}/paints/{pid}/")
        self.assertEqual(png.status_code, 200)
        im = Image.open(io.BytesIO(png.content))
        self.assertEqual(im.mode, "RGBA")
        self.assertEqual(im.getpixel((35, 22)), (255, 0, 0, 255))
        self.assertEqual(im.getpixel((5, 5))[3], 0, "بیرونِ لایه شفاف است")

    def test_large_canvas_is_scaled_and_layer_outside_the_canvas_is_clipped(self):
        raw = mk_psd(4096, 2048, [{"name": "بزرگ", "x": -100, "y": 10, "rgba": rgba_block(300, 200, (0, 255, 0, 255))}], comp=0)
        j = self.post(raw).json()
        self.assertTrue(any("کوچک شد" in n for n in j["notes"]))
        proj = PhotoProject.objects.get(pk=j["project"])
        pid = proj.data["layers"][1]["src"]["id"]
        im = Image.open(io.BytesIO(self.api.get(f"{self.base}/projects/{proj.pk}/paints/{pid}/").content))
        self.assertEqual(im.size, (2048, 1024))
        self.assertEqual(im.getpixel((2, 10))[:3], (0, 255, 0))

    def test_no_layers_falls_back_to_the_merged_image(self):
        merged = np.zeros((20, 30, 3), np.uint8)
        merged[..., 1] = 200
        j = self.post(mk_psd(30, 20, [], merged=merged)).json()
        self.assertEqual((j["layers"], j["project"]), (0, None))
        self.assertTrue(any("ترکیبی" in n for n in j["notes"]))

    def test_bad_file_is_400_and_missing_file_too(self):
        self.assertEqual(self.post(b"not a psd").status_code, 400)
        self.assertEqual(self.api.post(f"{self.base}/psd/import/", {}, format="multipart").status_code, 400)
