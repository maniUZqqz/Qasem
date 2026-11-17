"""«شخصیتِ برند» در موشن: هر فیلدِ تصویریِ هر قطعه (image_a، image_b، ... و overlay ها) باید برای Remotion به asset:aN برود.

باگِ ۱۱/۱۶: فقط چهار کلیدِ ثابت (image، before_image، after_image، screenshot) عوض می‌شد؛ image_a و image_b همان photo:<id> می‌ماند، Remotion آن را نمی‌خواند و
به‌جای کارتون یک مستطیلِ تخت می‌کشید. این آزمون هم پیش‌نمایشِ زنده را می‌سنجد و هم رندرِ نهایی (materialize) را، برای صحنه و برای overlay.
"""
import io
import json
from pathlib import Path

from django.test import SimpleTestCase
from PIL import Image

from apps.photoedit.models import PhotoAsset

from . import components, services, specs
from .tests_api import Base, png_bytes, spec


def _photo(store, name: str, colour) -> PhotoAsset:
    """یک استیکرِ شفافِ واقعی در رسانهٔ همین فروشگاه + ردیفِ ادیتورِ عکس (همان‌چیزی که بخشِ «شخصیتِ برند» می‌سازد)."""
    from django.conf import settings

    rel = f"photoedit/{store.pk}/{name}.png"
    p = Path(settings.MEDIA_ROOT) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO()
    Image.new("RGBA", (240, 360), colour).save(buf, "PNG")
    p.write_bytes(buf.getvalue())
    return PhotoAsset.objects.create(store=store, title=name, original=rel, thumb=rel, width=240, height=360, has_alpha=True)


def brand_scene(a: str, b: str, **kw) -> dict:
    return {"type": "brand_character", "duration": 6, "name": "مربیِ چغر", "text": "سلام", "image_a": a, "image_b": b, "action": "wave", "arrive": "left", "side": "right", "bubble": True, **kw}


class RefSlots(SimpleTestCase):
    """جاهای تصویر از روی شمای قطعه‌ها پیدا می‌شوند، نه از یک فهرستِ ثابتِ کلید."""

    def test_every_ref_field_of_every_component_is_a_slot(self):
        for cid, comp in components.COMPONENTS.items():
            keys = [k for k, fs in comp["fields"].items() if fs["kind"] == "ref"]
            if not keys:
                continue
            sc = {"type": cid, "duration": 4, **{k: f"photo:{i + 1}" for i, k in enumerate(keys)}}
            got = {k for h, k in specs.ref_slots({"scenes": [sc]})}
            self.assertEqual(got, set(keys), cid)

    def test_overlays_and_logo_are_slots_too(self):
        sp = {"brand": {"logo": "store-logo"}, "scenes": [{"type": "title", "duration": 4, "title": "x", "overlays": [brand_scene("photo:7", "photo:8")]}]}
        self.assertEqual(specs.asset_refs(sp), ["store-logo", "photo:7", "photo:8"])
        specs.map_refs(sp, lambda v: "asset:" + v.replace(":", ""))
        self.assertEqual(sp["brand"]["logo"], "asset:store-logo")
        ov = sp["scenes"][0]["overlays"][0]
        self.assertEqual((ov["image_a"], ov["image_b"]), ("asset:photo7", "asset:photo8"))

    def test_brand_character_has_two_ref_fields(self):
        self.assertEqual([k for k, fs in components.COMPONENTS["brand_character"]["fields"].items() if fs["kind"] == "ref"], ["image_a", "image_b"])


class BrandCharacterImagesReachRemotion(Base):
    def setUp(self):
        super().setUp()
        self.a = _photo(self.store, "stand", (30, 160, 150, 255))
        self.b = _photo(self.store, "wave", (230, 120, 40, 255))
        self.ra, self.rb = f"photo:{self.a.pk}", f"photo:{self.b.pk}"

    def _spec(self, **kw):
        return spec(scenes=[brand_scene(self.ra, self.rb, **kw)])

    def test_live_preview_replaces_image_a_and_image_b(self):
        r = self.api.post(f"{self.base}/preview/", {"spec": self._spec()}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        out = r.json()["spec"]
        sc = out["scenes"][0]
        self.assertEqual((sc["image_a"], sc["image_b"]), ("asset:a1", "asset:a2"))
        self.assertEqual(set(out["assets"]), {"a1", "a2"})
        for k in ("a1", "a2"):
            self.assertTrue(out["assets"][k].startswith("data:image/png;base64,"), k)
        self.assertNotIn("photo:", json.dumps(out["scenes"]))

    def test_final_render_materialize_replaces_image_a_and_image_b(self):
        sp = specs.normalize_spec(self._spec())
        out, files = services.materialize(self.store, sp)
        sc = out["scenes"][0]
        self.assertEqual((sc["image_a"], sc["image_b"]), ("asset:a1", "asset:a2"))
        self.assertEqual(set(files), {"a1", "a2"})
        self.assertEqual(out["assets"], {"a1": "@file:a1.png", "a2": "@file:a2.png"})
        self.assertNotIn("photo:", json.dumps(out["scenes"]))
        # بایت‌های واقعیِ همان دو استیکر (رنگِ متفاوتِ هر کدام) فرستاده می‌شود، نه تصویرِ دیگری
        px = [Image.open(io.BytesIO(files[k][0])).convert("RGBA").getpixel((120, 180)) for k in ("a1", "a2")]
        self.assertEqual(px[0][:3], (30, 160, 150))
        self.assertEqual(px[1][:3], (230, 120, 40))

    def test_same_picture_for_both_poses_is_one_asset(self):
        out, files = services.materialize(self.store, specs.normalize_spec(spec(scenes=[brand_scene(self.ra, self.ra)])))
        self.assertEqual(set(files), {"a1"})
        self.assertEqual((out["scenes"][0]["image_a"], out["scenes"][0]["image_b"]), ("asset:a1", "asset:a1"))

    def test_overlay_brand_character_is_resolved_too(self):
        ov = {"type": "brand_character", "at": 0.5, "dur": 4, "name": "مربی", "text": "سلام", "image_a": self.ra, "image_b": self.rb, "action": "wave", "arrive": "left", "side": "right", "bubble": True}
        sp = specs.normalize_spec(spec(scenes=[{"type": "title", "duration": 6, "title": "عنوان", "overlays": [ov]}]))
        ovs = sp["scenes"][0].get("overlays") or []
        self.assertEqual(len(ovs), 1, "the overlay was dropped by normalize_spec")
        for out in (services.materialize(self.store, sp)[0], self.api.post(f"{self.base}/preview/", {"spec": sp}, format="json").json()["spec"]):
            o = out["scenes"][0]["overlays"][0]
            self.assertEqual((o["image_a"], o["image_b"]), ("asset:a1", "asset:a2"))

    def test_classic_keys_and_logo_still_work_next_to_the_new_ones(self):
        p = _photo(self.store, "prod", (10, 10, 200, 255))
        sp = specs.normalize_spec(spec(brand={"logo": f"photo:{p.pk}"}, scenes=[
            {"type": "product", "duration": 4, "name": "کالا", "image": f"photo:{p.pk}"}, brand_scene(self.ra, self.rb)]))
        out, files = services.materialize(self.store, sp)
        self.assertEqual(out["brand"]["logo"], "asset:a1")
        self.assertEqual(out["scenes"][0]["image"], "asset:a1")
        self.assertEqual((out["scenes"][1]["image_a"], out["scenes"][1]["image_b"]), ("asset:a2", "asset:a3"))
        self.assertEqual(len(files), 3)

    def test_unresolvable_character_image_gives_a_persian_error_not_a_flat_box(self):
        r = self.api.post(f"{self.base}/preview/", {"spec": spec(scenes=[brand_scene("photo:99999", self.rb)])}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("پیدا نشد", json.dumps(r.json(), ensure_ascii=False))

    def test_the_gallery_handoff_scene_survives_the_whole_path(self):
        """همان صحنه‌ای که دکمهٔ «افزودن به استودیوی موشن» می‌دهد (apps.brandchar.usage.motion_scene) ⇒ پیش‌نمایش ⇒ asset:aN."""
        from apps.brandchar import services as BS
        from apps.brandchar import usage

        c = BS.create(self.store, self.owner, role="coach", name="مربی")
        sc = usage.motion_scene(c, self.owner, action="wave", text="سلام")
        self.assertRegex(sc["image_a"], r"^photo:\d+$")
        r = self.api.post(f"{self.base}/preview/", {"spec": spec(scenes=[sc])}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        out = r.json()["spec"]["scenes"][0]
        self.assertTrue(out["image_a"].startswith("asset:") and out["image_b"].startswith("asset:"), out)


class ComponentLibraryIsComplete(Base):
    """هر قطعه بندانگشتی دارد و هر فیلدش نامِ فارسی (۱۱/۱۶: «شخصیتِ برند» ۴۰۴ می‌داد و فیلدهایش انگلیسی بود)."""

    def test_every_component_has_a_thumbnail_file_and_the_endpoint_serves_it(self):
        from django.test import Client

        anon = Client()
        for cid in components.COMPONENTS:
            r = anon.get(f"/api/v1/motion/components/{cid}/thumb/")
            self.assertEqual(r.status_code, 200, cid)
            self.assertEqual(r["Content-Type"], "image/jpeg", cid)
            self.assertGreater(len(b"".join(r.streaming_content)), 2000, cid)

    def _form_source(self) -> str:
        p = Path(__file__).resolve().parents[3] / "frontend" / "src" / "features" / "content" / "motion" / "FieldsForm.tsx"
        return p.read_text(encoding="utf-8")

    def test_every_field_has_a_persian_label_in_the_scene_form(self):
        import re

        src = self._form_source()
        block = src[src.index("FIELD_LABELS"):src.index("const KIND_FA")]
        labels = set(re.findall(r'(?<![\w"])([a-z_0-9]+):\s*"', block))
        missing: dict = {}

        def walk(cid, fields):
            for k, fs in fields.items():
                if k not in labels:
                    missing.setdefault(cid, set()).add(k)
                if fs["kind"] == "objs":
                    walk(cid, fs["fields"])

        for cid, comp in components.COMPONENTS.items():
            walk(cid, comp["fields"])
        self.assertEqual(missing, {}, "fields without a Persian label in FieldsForm.tsx FIELD_LABELS")

    def test_every_small_enum_choice_has_a_persian_label(self):
        import re

        src = self._form_source()
        enum_block = src[src.index("export const ENUM_FA"):src.index("/** برچسبِ یک منبعِ تصویر")]
        kind_block = src[src.index("const KIND_FA"):src.index("/** نامِ فارسیِ گزینه‌های")]
        by_field = {m.group(1): set(re.findall(r"([a-z0-9_]+):\s*\"", m.group(2))) for m in re.finditer(r"^\s{2}([a-z_]+):\s*\{(.*?)\},?\s*$", enum_block, re.M)}
        flat = set(re.findall(r"([a-z0-9_]+):\s*\"", kind_block))
        gaps = []
        for cid, comp in components.COMPONENTS.items():
            for k, fs in comp["fields"].items():
                if fs["kind"] == "enum" and len(fs["choices"]) <= 30:
                    for ch in fs["choices"]:
                        if ch not in by_field.get(k, set()) and ch not in flat:
                            gaps.append(f"{cid}.{k}={ch}")
        self.assertEqual(gaps, [])

    def test_brand_character_field_labels_are_the_agreed_persian_ones(self):
        src = self._form_source()
        for key in ("image_a", "image_b", "arrive", "action", "bubble", "side"):
            self.assertRegex(src, rf'{key}:\s*"[^"a-zA-Z]+')


class SourcesListBrandStickers(Base):
    def test_sources_include_the_brand_stickers_and_requested_library_photos(self):
        from apps.brandchar import services as BS

        c = BS.create(self.store, self.owner, role="coach", name="مربیِ چغر")
        BS.render_sticker(c, self.owner, {"pose": "wave", "expression": "happy", "crop": "full", "prop": "none"})
        BS.render_sticker(c, self.owner, {"pose": "stand", "expression": "happy", "crop": "bust", "prop": "none"})
        r = self.api.get(f"{self.base}/sources/")
        self.assertEqual(r.status_code, 200, r.content)
        rows = [s for s in r.json()["sources"] if s["group"] == "شخصیتِ برند"]
        self.assertEqual(len(rows), 2)
        for s in rows:
            self.assertRegex(s["ref"], r"^photo:\d+$")
            self.assertTrue(s["url"])
            self.assertIn("مربیِ چغر", s["title"])
        self.assertIn("(نیم‌تنه)", " ".join(s["title"] for s in rows))
        # عکسی که در صحنه هست ولی در فهرست نیست با ?refs= می‌آید (فقط از همین فروشگاه)
        other = _photo(self.store, "lib", (1, 2, 3, 255))
        mine = self.api.get(f"{self.base}/sources/", {"refs": f"photo:{other.pk},photo:999999,upload:1"}).json()["sources"]
        self.assertIn(f"photo:{other.pk}", [s["ref"] for s in mine])
        self.assertNotIn("photo:999999", [s["ref"] for s in mine])

    def test_another_stores_photo_is_never_listed(self):
        from apps.stores.models import Store

        stranger = Store.objects.create(owner=self.owner, name="دیگر")
        foreign = _photo(stranger, "foreign", (9, 9, 9, 255))
        got = self.api.get(f"{self.base}/sources/", {"refs": f"photo:{foreign.pk}"}).json()["sources"]
        self.assertNotIn(f"photo:{foreign.pk}", [s["ref"] for s in got])
