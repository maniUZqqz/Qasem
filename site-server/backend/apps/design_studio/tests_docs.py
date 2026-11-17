"""استودیوی طراحی — API و سرویس: ساختِ کاتالوگ از محصولاتِ فروشگاه، ویرایش‌ها (ops)، کنترلِ rev، پیش‌نمایش، خروجی‌ها، ارائه (قاعده‌ای و هوش مصنوعی با نگهبانِ عدد)،
طراحیِ UI، نظرها، پل‌ها (ادیتورِ عکس، سرورِ پردازش، سایت‌ساز) و دسترسی."""
import io
import json
import shutil
import tempfile
import zipfile
from datetime import timedelta
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone
from PIL import Image
from rest_framework.test import APIClient

from apps.products.models import Product, ProductImage
from apps.stores.models import Store

from . import bridges, deck_doc, exports, fixtures, services, ui_doc
from .models import DesignDoc, DesignExport

User = get_user_model()


def png_upload(name="x.png", color=(40, 120, 160), size=(900, 700)):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return SimpleUploadedFile(name, buf.getvalue(), content_type="image/png")


class Base(TestCase):
    databases = {"default", "studio"}

    def setUp(self):
        self.media = Path(tempfile.mkdtemp(prefix="nmdesign-media-"))
        self.data = Path(tempfile.mkdtemp(prefix="nmdesign-data-"))
        self.override = override_settings(MEDIA_ROOT=str(self.media), NM_DATA_DIR=self.data, IS_TEST=True)
        self.override.enable()
        self.owner = User.objects.create_user("design-owner", password="x")
        self.staff = User.objects.create_user("design-staff", password="x", is_staff=True)
        self.store = Store.objects.create(owner=self.owner, name="فروشگاهِ آزمون", description="توضیحِ فروشگاه برای صفحهٔ دربارهٔ ما.\nخطِ دوم از توضیح.", target_audience="مربی‌ها",
                                          colors={"primary": "#126F85", "secondary": "#163F75"}, contact={"website": "example.ir", "phone": "۰۲۱۰۰۰۰۰۰۰۰"})
        self.products = []
        for i, (name, price) in enumerate([("برنامهٔ آزمون یک", 600000), ("برنامهٔ آزمون دو", 300000), ("برنامهٔ سه", 0), ("برنامهٔ چهار", 250000), ("برنامهٔ پنج", 900000)]):
            p = Product.objects.create(store=self.store, name=name, price=price, currency="IRT", description=f"توضیحِ کاملِ {name}. " * 6, short_description=f"توضیحِ کوتاهِ {name}",
                                       sku=f"T-{i}")
            ProductImage.objects.create(product=p, image=png_upload(f"p{i}.png", (40 + i * 30, 120, 160 - i * 20)), is_main=True)
            self.products.append(p)
        self.api = APIClient()
        self.api.force_authenticate(self.owner)
        self.base = f"/api/v1/stores/{self.store.pk}/design"

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.media, ignore_errors=True)
        shutil.rmtree(self.data, ignore_errors=True)

    def make(self, kind, **opts):
        r = self.api.post(f"{self.base}/docs/", {"kind": kind, "options": opts}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        return r.json()["doc"]

    def ops(self, doc, ops, expect=200):
        r = self.api.post(f"{self.base}/docs/{doc['id']}/ops/", {"ops": ops, "rev": doc["rev"]}, format="json")
        self.assertEqual(r.status_code, expect, r.content)
        return r.json().get("doc") if expect == 200 else r.json()


class OverviewTests(Base):
    def test_overview_lists_everything_the_pages_need(self):
        r = self.api.get(f"{self.base}/")
        self.assertEqual(r.status_code, 200, r.content)
        b = r.json()
        self.assertEqual(len(b["products"]), 5)
        self.assertTrue(b["products"][0]["image_ref"].startswith("product:"))
        self.assertEqual({s["key"] for s in b["deck"]["slide_types"]}, {"title", "agenda", "text", "product", "comparison", "stats", "timeline", "team", "cta", "section", "image"})
        self.assertEqual({s["key"] for s in b["catalog"]["page_types"]}, {"cover", "toc", "text", "grid", "hero", "price_list", "lookbook", "steps", "divider", "back"})
        self.assertGreaterEqual(len(b["ui"]["styles"]), 14)
        self.assertEqual({d["key"] for d in b["ui"]["devices"]}, {"desktop", "tablet", "phone"})
        self.assertEqual({r["key"] for r in b["recipients"]}, {"printer", "social", "designer", "customer", "meeting", "kiosk", "dev"})
        self.assertTrue(any(f["key"] == "vazirmatn" for f in b["fonts"]))
        self.assertGreaterEqual(len(b["looks"]), 20)
        self.assertIn("ok", b["ai"])
        self.assertIn("state", b["node"])

    def test_other_users_get_404_and_fonts_are_public(self):
        other = User.objects.create_user("stranger", password="x")
        c = APIClient()
        c.force_authenticate(other)
        self.assertEqual(c.get(f"{self.base}/").status_code, 404)
        anon = APIClient()
        f = anon.get("/api/v1/design/fonts/vazirmatn/400.ttf")
        self.assertEqual(f.status_code, 200)
        self.assertEqual(anon.get("/api/v1/design/fonts/nope/400.ttf").status_code, 404)
        self.assertIn(anon.get(f"{self.base}/").status_code, (401, 403))


class CatalogTests(Base):
    def test_catalog_is_built_from_the_stores_products_as_stored(self):
        doc = self.make("catalog")
        types = [p["type"] for p in doc["data"]["pages"]]
        self.assertEqual(types[0], "cover")
        self.assertIn("toc", types)
        self.assertIn("grid", types)
        self.assertIn("price_list", types)
        self.assertEqual(types[-1], "back")
        self.assertEqual(len(doc["data"]["products"]), 5)
        p1 = next(p for p in doc["data"]["products"] if p["name"] == "برنامهٔ آزمون یک")
        self.assertEqual(p1["price"], 600000.0)
        self.assertTrue(p1["images"][0].startswith("product:"))
        sc = self.api.get(f"{self.base}/docs/{doc['id']}/scene/").json()
        texts = " ".join(e.get("text", "") for p in sc["pages"] for e in p["elements"] if e["type"] == "text")
        self.assertIn("۶۰۰٬۰۰۰ تومان", texts)                              # قیمتِ ثبت‌شده، بی‌دست‌کاری
        self.assertIn("رایگان", texts)                                    # قیمتِ ۰ همان‌طور که ثبت شده
        self.assertIn("برنامهٔ آزمون یک", texts)
        self.assertTrue(sc["checks"])
        self.assertEqual(sc["unit"], "mm")

    def test_empty_store_gives_a_persian_error(self):
        Product.objects.all().delete()
        r = self.api.post(f"{self.base}/docs/", {"kind": "catalog"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("محصولی", r.json()["error"]["message"])

    def test_ops_edit_pages_overrides_extras_and_rev_conflicts(self):
        doc = self.make("catalog", featured=[self.products[0].pk])
        n0 = len(doc["data"]["pages"])
        doc = self.ops(doc, [{"op": "add_page", "type": "divider", "spec": {"title": "بخشِ تازه", "subtitle": "زیرعنوان"}, "index": 2}])
        self.assertEqual(len(doc["data"]["pages"]), n0 + 1)
        self.assertEqual(doc["data"]["pages"][2]["type"], "divider")
        pid = doc["data"]["pages"][2]["id"]
        doc = self.ops(doc, [{"op": "update_page", "page": pid, "set": {"title": "عنوانِ ویرایش‌شده", "junk": "x"}}])
        self.assertEqual(doc["data"]["pages"][2]["title"], "عنوانِ ویرایش‌شده")
        self.assertNotIn("junk", doc["data"]["pages"][2])
        doc = self.ops(doc, [{"op": "override", "page": pid, "el": "title", "set": {"text": "متنِ دست‌نویس", "x": 12.5}},
                             {"op": "add_element", "page": pid, "element": {"type": "text", "x": 10, "y": 10, "w": 80, "h": 10, "text": "افزوده", "size": 5, "color": "#112233"}}])
        sc = self.api.get(f"{self.base}/docs/{doc['id']}/scene/").json()
        page = next(p for p in sc["pages"] if p["id"] == pid)
        title = next(e for e in page["elements"] if e["id"] == "title")
        self.assertEqual((title["text"], title["x"]), ("متنِ دست‌نویس", 12.5))
        self.assertTrue(any(e.get("text") == "افزوده" for e in page["elements"]))
        stale = self.ops(doc | {"rev": doc["rev"] - 1}, [{"op": "delete_page", "page": pid}], expect=409)
        self.assertEqual(stale["error"]["code"], "conflict")
        doc = self.ops(doc, [{"op": "move_page", "page": pid, "to": 0}, {"op": "duplicate_page", "page": pid}])
        self.assertEqual(doc["data"]["pages"][0]["id"], pid)
        bad = self.ops(doc, [{"op": "explode"}], expect=400)
        self.assertIn("نمی‌شناسم", bad["error"]["message"])
        doc = self.ops(doc, [{"op": "remove_element", "page": pid, "el": "x1"}])
        sc = self.api.get(f"{self.base}/docs/{doc['id']}/scene/").json()
        self.assertFalse(any(e.get("text") == "افزوده" for e in sc["pages"][0]["elements"]))

    def test_settings_change_page_size_and_pad_to_multiple_of_four(self):
        doc = self.make("catalog")
        doc = self.ops(doc, [{"op": "set_settings", "set": {"page_size": "A5", "digits": "en", "look": "warm_sunset", "bleed": 3}}, {"op": "pad4"}])
        self.assertEqual(len(doc["data"]["pages"]) % 4, 0)
        sc = self.api.get(f"{self.base}/docs/{doc['id']}/scene/").json()
        self.assertEqual((sc["pages"][0]["w"], sc["pages"][0]["h"]), (148.0, 210.0))
        texts = " ".join(e.get("text", "") for p in sc["pages"] for e in p["elements"] if e["type"] == "text")
        self.assertIn("600,000", texts)                                   # رقم‌های لاتین
        self.assertEqual(sc["palette"]["primary"], "#26408b" if sc["settings"]["look"] == "cool_midnight" else sc["palette"]["primary"])
        self.assertEqual(next(c for c in sc["checks"] if c["key"] == "mult4")["level"], "ok")

    def test_sync_products_picks_up_store_changes(self):
        doc = self.make("catalog")
        self.products[0].price = 700000
        self.products[0].save()
        doc = self.ops(doc, [{"op": "sync_products"}])
        p1 = next(p for p in doc["data"]["products"] if p["id"] == self.products[0].pk)
        self.assertEqual(p1["price"], 700000.0)

    def test_preview_png_has_requested_width_and_is_cached(self):
        doc = self.make("catalog")
        pid = doc["data"]["pages"][0]["id"]
        r = self.api.get(f"{self.base}/docs/{doc['id']}/preview/{pid}.png?w=600")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "image/png")
        im = Image.open(io.BytesIO(r.content))
        self.assertEqual(im.size[0], 600)
        self.assertAlmostEqual(im.size[1] / im.size[0], 297 / 210, places=2)
        cached = list((self.data / "design").rglob("cache/*.png"))
        self.assertEqual(len(cached), 1)
        self.assertEqual(self.api.get(f"{self.base}/docs/{doc['id']}/preview/{pid}.png?w=600").content, r.content)
        self.assertEqual(self.api.get(f"{self.base}/docs/{doc['id']}/preview/nope.png").status_code, 400)

    def test_export_flow_print_pdf_pack_download_and_errors(self):
        doc = self.make("catalog")
        r = self.api.post(f"{self.base}/docs/{doc['id']}/exports/", {"kind": "print_pdf"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        e = r.json()["export"]
        self.assertEqual(e["state"], "READY", e)                          # Celery در آزمون eager است
        self.assertEqual(e["info"]["bleed_mm"], 3.0)
        d = self.api.get(f"{self.base}/exports/{e['id']}/download/")
        self.assertEqual(d.status_code, 200)
        body = b"".join(d.streaming_content)
        self.assertTrue(body.startswith(b"%PDF"))
        self.assertIn("attachment", d["Content-Disposition"])
        pack = self.api.post(f"{self.base}/docs/{doc['id']}/exports/", {"kind": "pack_customer"}, format="json").json()["export"]
        self.assertEqual(pack["state"], "READY")
        z = zipfile.ZipFile(io.BytesIO(b"".join(self.api.get(f"{self.base}/exports/{pack['id']}/download/").streaming_content)))
        self.assertIn("README-fa.txt", z.namelist())
        bad = self.api.post(f"{self.base}/docs/{doc['id']}/exports/", {"kind": "pack_dev"}, format="json")
        self.assertEqual(bad.status_code, 400)
        lst = self.api.get(f"{self.base}/docs/{doc['id']}/exports/").json()["exports"]
        self.assertEqual(len(lst), 2)

    def test_edit_in_designer_makes_a_photo_project_with_live_text_layers(self):
        from apps.photoedit.models import PhotoProject

        doc = self.make("catalog")
        pid = doc["data"]["pages"][3]["id"]
        r = self.api.post(f"{self.base}/docs/{doc['id']}/designer/", {"page": pid}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        out = r.json()
        proj = PhotoProject.objects.get(pk=out["project"])
        layers = proj.data["layers"]
        self.assertEqual(layers[0]["type"], "base")
        text_layers = [layer for layer in layers if layer["type"] == "text"]
        self.assertGreaterEqual(len(text_layers), 3)
        self.assertEqual(len(text_layers), out["layers"])
        self.assertTrue(all(0 <= layer["cx"] <= 1 and 0 <= layer["cy"] <= 1 for layer in text_layers))
        self.assertTrue(all(layer["dir"] in ("rtl", "ltr") for layer in text_layers))
        self.assertTrue(proj.asset.width >= 1800)
        self.assertIn(f"photo-editor?asset={proj.asset_id}&mode=manual", out["url"])

    def test_delete_doc_and_rename(self):
        doc = self.make("catalog")
        r = self.api.patch(f"{self.base}/docs/{doc['id']}/", {"title": "نامِ تازه"}, format="json")
        self.assertEqual(r.json()["doc"]["title"], "نامِ تازه")
        self.assertEqual(self.api.delete(f"{self.base}/docs/{doc['id']}/").status_code, 204)
        self.assertEqual(self.api.get(f"{self.base}/docs/{doc['id']}/").status_code, 404)


class DeckTests(Base):
    def test_rule_based_deck_uses_only_real_data(self):
        doc = self.make("deck", use_ai=False, brief="معرفیِ برنامه‌ها", steps=[{"title": "گام یک", "text": "متن"}, {"title": "گام دو", "text": "متن"}])
        types = [s["type"] for s in doc["data"]["slides"]]
        self.assertEqual(types[0], "title")
        self.assertEqual(types[1], "agenda")
        for t in ("text", "product", "comparison", "stats", "timeline", "cta"):
            self.assertIn(t, types)
        self.assertNotIn("team", types)                                   # عضوِ تیمی ندادیم ⇒ ساخته نمی‌شود
        stats = next(s for s in doc["data"]["slides"] if s["type"] == "stats")
        self.assertTrue(all(i["source"] for i in stats["items"]))
        self.assertEqual(stats["items"][0]["value"], "۵")                 # تعدادِ واقعیِ محصول‌ها
        self.assertFalse(doc["meta"]["ai"]["used"])
        sc = self.api.get(f"{self.base}/docs/{doc['id']}/scene/").json()
        self.assertEqual(sc["unit"], "px")
        self.assertEqual((sc["pages"][0]["w"], sc["pages"][0]["h"]), (1920.0, 1080.0))
        self.assertTrue(all(p["notes"] is not None for p in sc["pages"]))

    def test_ai_draft_is_guarded_against_invented_numbers_and_foreign_products(self):
        info = services.store_info(self.store)
        items = [{"id": p.pk, "name": p.name, "short": p.short_description, "desc": p.description, "price": float(p.price), "currency": "IRT", "images": [], "attrs": [], "tags": [], "category": ""}
                 for p in self.products]
        pid = self.products[0].pk

        def fake(prompt, system):
            self.assertIn("هرگز قیمت", system)
            self.assertIn("facts", prompt)
            return {"slides": [
                {"type": "title", "title": "ارائهٔ آزمون", "subtitle": "رضایتِ ۹۸ درصدی", "notes": "سلام"},
                {"type": "agenda", "items": ["معرفی", "محصول"]},
                {"type": "product", "product": pid, "text": "قیمتِ ثبت‌شده ۶۰۰٬۰۰۰ تومان است", "points": ["نکته ۱", "تخفیفِ ۵۵ درصدی"], "notes": "یادداشت"},
                {"type": "product", "product": 99999, "text": "محصولِ ناموجود"},
                {"type": "stats", "items": [{"value": "۹۸٪", "label": "رضایت", "source": "ساختگی"}, {"value": "5", "label": "محصولِ ثبت‌شده", "source": "فروشگاه"}]},
                {"type": "team", "members": [{"name": "آدمِ ساختگی"}]},
                {"type": "cta", "title": "با ما بمانید", "button": "تماس"}]}, {"label": "fake"}

        data, ai = deck_doc.new_deck(info, items, {}, {}, brief="آزمون", use_ai=True, ask=fake)
        self.assertTrue(ai["used"], ai)
        slides = data["slides"]
        types = [s["type"] for s in slides]
        self.assertNotIn("team", types)
        self.assertEqual(types.count("product"), 1)                       # محصولِ ناموجود دور ریخته شد
        title = slides[0]
        self.assertEqual(title["subtitle"], "")                           # عددِ ۹۸ در منبع نبود
        prod = next(s for s in slides if s["type"] == "product")
        self.assertIn("۶۰۰٬۰۰۰", prod["text"])                           # قیمتِ واقعی ماند
        self.assertEqual(prod["points"], ["نکته ۱"])                      # «تخفیفِ ۵۵» حذف شد
        stats = next(s for s in slides if s["type"] == "stats")
        self.assertEqual([i["value"] for i in stats["items"]], ["5"])

    def test_ai_unavailable_falls_back_to_rules_with_a_persian_reason(self):
        doc = self.make("deck", use_ai=True, brief="آزمون")                # زیرِ آزمون هوشِ مصنوعی صدا زده نمی‌شود
        ai = doc["meta"]["ai"]
        self.assertFalse(ai["used"])
        self.assertIn("در دسترس نبود", ai["message"])
        self.assertGreaterEqual(len(doc["data"]["slides"]), 5)
        r = self.api.post(f"{self.base}/docs/{doc['id']}/ai/", {"brief": "دوباره", "use_ai": True}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()["ai"]["used"])

    def test_every_slide_type_can_be_added_edited_and_reviewed(self):
        doc = self.make("deck", use_ai=False)
        for t in ("section", "image", "team", "text", "agenda"):
            doc = self.ops(doc, [{"op": "add_slide", "type": t, "spec": {"title": "نمونه"}}])
        n = len(doc["data"]["slides"])
        sid = next(s["id"] for s in doc["data"]["slides"] if s["type"] == "team")
        doc = self.ops(doc, [{"op": "update_slide", "slide": sid, "set": {"members": [{"name": "نامِ واقعی", "role": "سمت"}], "notes": "یادداشتِ گوینده"}}])
        sc = self.api.get(f"{self.base}/docs/{doc['id']}/scene/").json()
        self.assertEqual(len(sc["pages"]), n)
        team = next(p for p in sc["pages"] if p["id"] == sid)
        self.assertEqual(team["notes"], "یادداشتِ گوینده")
        checks = {c["key"]: c for c in sc["checks"]}
        self.assertEqual(checks["placeholders"]["level"], "warn")           # اسلایدهای افزوده هنوز جای‌گیر دارند
        doc = self.ops(doc, [{"op": "add_slide", "type": "stats", "spec": {"title": "آمار", "items": [{"value": "۱۲", "label": "نمونه", "source": ""}]}}])
        sc = self.api.get(f"{self.base}/docs/{doc['id']}/scene/").json()
        self.assertEqual({c["key"]: c for c in sc["checks"]}["stats_source"]["level"], "warn")  # آمارِ بی‌منبع

    def test_video_waits_for_the_node_in_the_durable_queue_and_finishes_when_it_answers(self):
        from apps.compute import services as CS
        from apps.compute.models import ComputeJob, ComputeNode

        doc = self.make("deck", use_ai=False)
        r = self.api.post(f"{self.base}/docs/{doc['id']}/video/", {"seconds": 3}, format="json")
        self.assertEqual(r.status_code, 400)                              # هیچ سرورِ پردازشی ثبت نیست
        self.assertIn("سرورِ پردازش", r.json()["error"]["message"])
        node = ComputeNode.objects.create(name="N1", capabilities={"ffmpeg": True, "kinds": [bridges.VIDEO_KIND]}, last_seen=timezone.now() - timedelta(days=3))
        r = self.api.post(f"{self.base}/docs/{doc['id']}/video/", {"seconds": 3, "transition": "fade"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        e = r.json()["export"]
        self.assertEqual(e["state"], "RUNNING")
        self.assertEqual(r.json()["node"]["state"], "offline")
        job = ComputeJob.objects.get(uid=e["info"]["job"])
        self.assertEqual(job.kind, bridges.VIDEO_KIND)
        self.assertEqual(job.payload["slides"][0]["duration"], 3.0)
        self.assertEqual(len(job.payload["slides"]), len(doc["data"]["slides"]))
        self.assertEqual(job.state, ComputeJob.State.QUEUED)
        out = CS.output_path(job, "out.mp4")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"0" * 4000)
        job.state = ComputeJob.State.COMPLETED
        job.result = {"meta": {"encoder": "h264_nvenc", "duration_s": 12}}
        job.save()
        got = self.api.get(f"{self.base}/exports/{e['id']}/").json()["export"]
        self.assertEqual(got["state"], "READY", got)
        self.assertEqual(got["info"]["encoder"], "h264_nvenc")
        d = self.api.get(f"{self.base}/exports/{e['id']}/download/")
        self.assertEqual(d["Content-Type"], "video/mp4")


class UiTests(Base):
    def test_ui_doc_has_desktop_tablet_phone_frames_and_tokens(self):
        doc = self.make("ui", devices=["desktop", "tablet", "phone"], settings={"style": "glassmorphism", "mode": "light"})
        frames = doc["data"]["frames"]
        self.assertEqual([f["device"] for f in frames], ["desktop", "tablet", "phone"])
        self.assertTrue(all(f["children"] for f in frames))
        sc = self.api.get(f"{self.base}/docs/{doc['id']}/scene/").json()
        self.assertEqual([p["w"] for p in sc["pages"]], [1440.0, 834.0, 390.0])
        self.assertEqual(sc["tokens"]["style"], "glassmorphism")
        self.assertEqual(sc["tokens"]["style_label"], "شیشه‌ای")
        self.assertEqual(sc["tokens"]["light"]["primary"], "#126f85")      # رنگِ برندِ فروشگاه روی سبک می‌نشیند
        self.assertNotEqual(sc["tokens"]["light"]["bg"], sc["tokens"]["dark"]["bg"])
        self.assertTrue(sc["styleguide"])
        dark = self.api.get(f"{self.base}/docs/{doc['id']}/scene/?mode=dark").json()
        self.assertEqual(dark["pages"][0]["bg"], sc["tokens"]["dark"]["bg"])
        sg = self.api.get(f"{self.base}/docs/{doc['id']}/preview/styleguide.png?w=700")
        self.assertEqual(sg.status_code, 200)
        self.assertEqual(Image.open(io.BytesIO(sg.content)).width, 700)

    def test_frame_and_node_ops_auto_layout_and_prototype_links(self):
        doc = self.make("ui", devices=["desktop"])
        f1 = doc["data"]["frames"][0]["id"]
        doc = self.ops(doc, [{"op": "add_frame", "name": "صفحهٔ دوم", "device": "phone"}])
        f2 = doc["data"]["frames"][1]["id"]
        auto = {"t": "frame", "name": "کارت", "dir": "h", "gap": 12, "pad": [16, 16, 16, 16], "fill": "var:surface", "radius": 14,
                "children": [{"t": "text", "text": "عنوانِ کارت", "size": 22, "weight": 700}, {"t": "button", "text": "ادامه", "variant": "filled"}]}
        doc = self.ops(doc, [{"op": "add_node", "frame": f2, "node": auto}, {"op": "add_node", "frame": f2, "type": "c_cta_center_box"}])
        nodes = doc["data"]["frames"][1]["children"]
        self.assertEqual(nodes[0]["t"], "frame")
        btn_id = nodes[0]["children"][1]["id"]
        doc = self.ops(doc, [{"op": "set_link", "frame": f2, "node": btn_id, "to": f1}])
        sc = self.api.get(f"{self.base}/docs/{doc['id']}/scene/").json()
        page2 = next(p for p in sc["pages"] if p["id"] == f2)
        hs = page2["meta"]["hotspots"]
        self.assertTrue(any(h["to"] == f1 for h in hs))
        self.assertEqual(sc["links"], [{"from": f2, "node": btn_id, "to": f1}])
        # Auto Layout: دو فرزندِ ردیف کنارِ هم و درونِ لبه‌های فریم
        card_els = [e for e in page2["elements"] if e.get("node") == btn_id or e["type"] == "text" and e.get("text") == "عنوانِ کارت"]
        self.assertTrue(all(0 <= e["x"] and e["x"] + e["w"] <= 390 + 0.5 for e in card_els))
        doc = self.ops(doc, [{"op": "delete_frame", "frame": f1}])
        self.assertEqual(ui_doc.links(doc["data"]), [])                    # پیوند به فریمِ حذف‌شده پاک شد
        self.ops(doc, [{"op": "delete_frame", "frame": doc["data"]["frames"][0]["id"]}], expect=400)

    def test_comments_are_anchored_and_resolvable(self):
        doc = self.make("ui", devices=["desktop"])
        fid = doc["data"]["frames"][0]["id"]
        r = self.api.post(f"{self.base}/docs/{doc['id']}/comments/", {"frame": fid, "x": 0.4, "y": 0.2, "text": "اینجا را بزرگ‌تر کن"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        c = r.json()["comment"]
        self.assertEqual((c["frame"], c["x"], c["y"], c["resolved"]), (fid, 0.4, 0.2, False))
        reply = self.api.post(f"{self.base}/docs/{doc['id']}/comments/", {"frame": fid, "text": "انجام شد", "parent": c["id"]}, format="json").json()["comment"]
        self.assertEqual(reply["parent"], c["id"])
        done = self.api.patch(f"{self.base}/comments/{c['id']}/", {"resolved": True}, format="json").json()["comment"]
        self.assertTrue(done["resolved"])
        self.assertEqual(len(self.api.get(f"{self.base}/docs/{doc['id']}/comments/").json()["comments"]), 2)
        self.assertEqual(self.api.post(f"{self.base}/docs/{doc['id']}/comments/", {"frame": "nope", "text": "x"}, format="json").status_code, 400)
        self.assertEqual(self.api.post(f"{self.base}/docs/{doc['id']}/comments/", {"frame": fid, "text": " "}, format="json").status_code, 400)
        self.assertEqual(self.api.delete(f"{self.base}/comments/{c['id']}/").status_code, 204)

    def test_build_site_from_design_creates_an_unpublished_draft_with_theme_and_links(self):
        from apps.projects.models import Design, Page, Project, SiteTheme

        doc = self.make("ui", devices=["desktop", "phone"], settings={"style": "bento-grid"})
        d = doc["data"]
        f1 = d["frames"][0]["id"]
        doc = self.ops(doc, [{"op": "add_frame", "name": "درباره", "device": "desktop"}])
        f2 = [f for f in doc["data"]["frames"] if f["name"] == "درباره"][0]["id"]
        doc = self.ops(doc, [{"op": "add_node", "frame": f2, "type": "c_hero_minimal_type"}])
        hero = next(n for n in doc["data"]["frames"][0]["children"] if n["type"] == "c_hero_center_glow")
        doc = self.ops(doc, [{"op": "set_link", "frame": f1, "node": hero["id"], "to": f2}])
        denied = APIClient()
        denied.force_authenticate(self.owner)
        self.assertEqual(denied.post(f"{self.base}/docs/{doc['id']}/site/", {}, format="json").status_code, 403)     # سایت‌ساز فقط برای کارکنان
        Store.objects.filter(pk=self.store.pk).update(owner=self.staff)
        self.api.force_authenticate(self.staff)
        r = self.api.post(f"{self.base}/docs/{doc['id']}/site/", {"name": "طرحِ آزمون"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        out = r.json()["site"]
        self.assertFalse(out["published"])
        p = Project.objects.get(pk=out["project_id"])
        pages = list(Page.objects.filter(project=p).order_by("order"))
        self.assertEqual(len(pages), 2)                                    # دو فریمِ دسکتاپ ⇒ دو صفحه؛ فریمِ گوشی صفحهٔ جدا نمی‌شود
        self.assertEqual(pages[0].slug, "")
        home = Design.objects.get(project=p, page=pages[0]).draft
        types = [b["type"] for b in home["blocks"]]
        self.assertIn("c_hero_center_glow", types)
        self.assertNotIn("c_nav_classic", types)                           # سربرگ و پابرگ جدا نشسته‌اند
        self.assertTrue(Design.objects.filter(project=p, target="header").exists())
        footer = Design.objects.get(project=p, target="footer").draft
        self.assertEqual(footer["blocks"][0]["type"], "c_footer_columns")
        hero_props = next(b for b in home["blocks"] if b["type"] == "c_hero_center_glow")["props"]
        self.assertTrue(any(str(v).startswith("/") and len(str(v)) > 1 for k, v in hero_props.items() if k.endswith("_link")), hero_props)   # پیوندِ نمونهٔ اولیه ⇒ نشانیِ صفحه
        theme = SiteTheme.objects.get(project=p)
        self.assertFalse(theme.active)
        self.assertEqual(theme.draft["colors"]["primary"].lower(), "#126f85")
        self.assertEqual(len(theme.menu), 2)
        self.assertEqual(DesignDoc.objects.get(pk=doc["id"]).meta["site"]["project_id"], p.pk)

    def test_ui_review_checks_contrast_devices_and_links(self):
        doc = self.make("ui", devices=["desktop"])
        sc = self.api.get(f"{self.base}/docs/{doc['id']}/scene/").json()
        by = {c["key"]: c for c in sc["checks"]}
        self.assertEqual(by["contrast"]["level"], "ok")
        self.assertEqual(by["devices"]["level"], "info")                   # فقط یک دستگاه
        self.assertEqual(by["nav"]["level"], "ok")

    def test_ui_exports_png_svg_pdf_tokens_and_dev_pack(self):
        doc = self.make("ui", devices=["desktop", "phone"])
        for kind, name_end in (("png_zip", ".zip"), ("svg_zip", ".zip"), ("screen_pdf", ".pdf"), ("tokens", ".zip"), ("pack_dev", ".zip")):
            e = self.api.post(f"{self.base}/docs/{doc['id']}/exports/", {"kind": kind}, format="json").json()["export"]
            self.assertEqual(e["state"], "READY", (kind, e))
            self.assertTrue(e["filename"].endswith(name_end))
        pdf_export = [x for x in self.api.get(f"{self.base}/docs/{doc['id']}/exports/").json()["exports"] if x["kind"] == "screen_pdf"][0]
        body = b"".join(self.api.get(f"{self.base}/exports/{pdf_export['id']}/download/").streaming_content)
        self.assertEqual(body.count(b"/Type /Page "), len(doc["data"]["frames"]) + 1)      # فریم‌ها + راهنمای سبک


class NodeAndSelftestTests(Base):
    def test_node_slide_command_is_valid_ffmpeg(self):
        import importlib.util
        import shutil as sh
        import subprocess

        spec = importlib.util.spec_from_file_location("design_jobs", Path(__file__).resolve().parents[3] / "processing" / "design_jobs.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.assertEqual(mod.KIND, "edit.slides_mp4")
        p = mod.validate({"slides": [{"file": "a.png", "duration": 2}, {"file": "b.png", "duration": 2}, {"file": "c.png", "duration": 2}], "width": 321, "height": 181, "transition": "fade", "transition_s": 0.5})
        self.assertEqual((p["width"], p["height"]), (320, 180))             # زوج می‌شود
        with self.assertRaises(mod.DesignError):
            mod.validate({"slides": []})
        with self.assertRaises(mod.DesignError):
            mod.validate({"slides": [{"file": "../../etc/passwd", "duration": 1}]})
        cmd = mod.build_command("ffmpeg", ["a.png", "b.png", "c.png"], p, "libx264", "out.mp4")
        graph = cmd[cmd.index("-filter_complex") + 1]
        self.assertEqual(graph.count("xfade="), 2)
        self.assertIn("offset=2.000", graph)
        self.assertIn("offset=4.000", graph)
        ff = sh.which("ffmpeg")
        if not ff:
            self.skipTest("ffmpeg نیست")
        d = Path(tempfile.mkdtemp(prefix="nm-design-ff-"))
        try:
            files = []
            for i, col in enumerate(((200, 40, 40), (40, 200, 40), (40, 40, 200))):
                f = d / f"s{i}.png"
                Image.new("RGB", (640, 360), col).save(f)
                files.append(str(f))
            out = d / "o.mp4"
            r = subprocess.run(mod.build_command(ff, files, p, "libx264", str(out)), capture_output=True, timeout=120)
            self.assertEqual(r.returncode, 0, r.stderr[-400:])
            self.assertGreater(out.stat().st_size, 1000)
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_offline_selftest_passes(self):
        from . import selftest

        res = selftest.run_offline()
        failed = [c for c in res["checks"] if not c["ok"]]
        self.assertEqual(failed, [], failed)
        self.assertTrue(res["ok"])


# ───────────────────────────── دورِ اصلاحِ بازبینی (۱۴۰۵/۰۸/۲۶)

def _pdf_objects(pdf: bytes) -> dict[int, bytes]:
    import re

    return {int(m.group(1)): m.group(2) for m in re.finditer(rb"(\d+) 0 obj\n(.*?)\nendobj", pdf, re.S)}


def _pdf_stream(body: bytes) -> bytes:
    import zlib

    i = body.find(b"stream\n")
    raw = body[i + 7:body.rfind(b"\nendstream")]
    return zlib.decompress(raw) if b"FlateDecode" in body[:i] else raw


def pdf_text_layer(pdf: bytes) -> list[str]:
    """متنِ لایهٔ نامرئیِ PDF (Tr 3) را از روی ToUnicodeِ همان فایل برمی‌گرداند؛ هر خط یک رشته."""
    import re

    from bidi.algorithm import get_display

    objs = _pdf_objects(pdf)
    tounicode: dict[str, dict[int, str]] = {}
    for body in objs.values():
        if b"/Subtype /Type1" in body and b"/ToUnicode" in body:
            ref = int(re.search(rb"/ToUnicode (\d+) 0 R", body).group(1))
            cm = _pdf_stream(objs[ref]).decode("latin-1")
            pairs = [p for blk in re.findall(r"beginbfchar(.*?)endbfchar", cm, re.S) for p in re.findall(r"<([0-9A-F]{2})> <([0-9A-F]+)>", blk)]
            table = {int(a, 16): bytes.fromhex(b).decode("utf-16-be") for a, b in pairs}
            tounicode[body.decode("latin-1")] = table
    name_to_obj: dict[str, int] = {}
    for body in objs.values():
        if b"/Type /Page " in body:
            m = re.search(rb"/Font << (.*?) >>", body)
            if m:
                for nm, num in re.findall(rb"/(TL\d+) (\d+) 0 R", m.group(1)):
                    name_to_obj[nm.decode()] = int(num)
    lines = []
    for body in objs.values():
        if b"stream\n" not in body or b"/Subtype" in body[:body.find(b"stream\n")]:
            continue
        try:
            content = _pdf_stream(body)
        except Exception:  # noqa: BLE001
            continue
        for bt in re.findall(rb"BT 3 Tr (.*?) ET", content, re.S):
            line = ""
            for nm, hexs in re.findall(rb"/(TL\d+) [\d.]+ Tf <([0-9A-F]+)> Tj", bt):
                table = tounicode[objs[name_to_obj[nm.decode()]].decode("latin-1")]
                line += "".join(table[b] for b in bytes.fromhex(hexs.decode()))
            lines.append(get_display(line, base_dir="R"))                       # ترتیبِ دیداری ⇒ منطقی (کاری که نمایشگرِ PDF هم می‌کند)
    return lines


class FixRoundTests(Base):
    # --- ۱) پیوندِ «بازکردن در سایت‌ساز»
    def test_site_link_points_at_a_real_builder_page_and_old_docs_are_repaired(self):
        from apps.projects.models import Page, Project

        Store.objects.filter(pk=self.store.pk).update(owner=self.staff)
        self.api.force_authenticate(self.staff)
        doc = self.make("ui", devices=["desktop"])
        out = self.api.post(f"{self.base}/docs/{doc['id']}/site/", {"name": "پیوند"}, format="json").json()["site"]
        home = Page.objects.filter(project_id=out["project_id"]).order_by("order", "pk").first()
        self.assertEqual(out["pages"][0]["page_id"], home.pk)
        self.assertEqual(out["builder_url"], f"/panel/tools/studio/p/{out['slug']}/builder/page/{home.pk}")
        self.assertEqual(out["url"], f"/panel/tools/studio/p/{out['slug']}")           # نه شناسهٔ پروژه (/studio/19) که به فهرستِ پروژه‌ها می‌رفت
        # سندِ قدیمی: شناسهٔ صفحه در meta نیست ⇒ از روی پروژه پیدا می‌شود
        d = DesignDoc.objects.get(pk=doc["id"])
        d.meta["site"] = {k: v for k, v in d.meta["site"].items() if k not in ("builder_url",)}
        d.meta["site"]["pages"] = [{k: v for k, v in pg.items() if k != "page_id"} for pg in d.meta["site"]["pages"]]
        d.meta["site"]["url"] = f"/panel/tools/studio/{out['project_id']}"
        d.save()
        got = self.api.get(f"{self.base}/docs/{doc['id']}/").json()["doc"]
        self.assertEqual(got["site"]["pages"][0]["page_id"], home.pk)
        self.assertTrue(got["site"]["builder_url"].endswith(f"/builder/page/{home.pk}"))
        self.assertEqual(got["meta"]["site"]["builder_url"], got["site"]["builder_url"])
        self.assertTrue(got["site"]["exists"])
        Project.objects.filter(pk=out["project_id"]).delete()
        gone = self.api.get(f"{self.base}/docs/{doc['id']}/").json()["doc"]
        self.assertFalse(gone["site"]["exists"])

    # --- ۲) پاک‌کردنِ سند فایل‌هایش را هم می‌برد
    def test_delete_doc_removes_its_export_and_cache_folder(self):
        doc = self.make("catalog")
        e = self.api.post(f"{self.base}/docs/{doc['id']}/exports/", {"kind": "screen_pdf"}, format="json").json()["export"]
        self.assertEqual(e["state"], "READY")
        self.api.get(f"{self.base}/docs/{doc['id']}/preview/{doc['data']['pages'][0]['id']}.png?w=300")
        d = services.doc_dir(self.store.pk, doc["id"])
        self.assertTrue(d.is_dir() and any(d.rglob("*.pdf")))
        other = self.make("catalog")
        self.assertEqual(self.api.delete(f"{self.base}/docs/{doc['id']}/").status_code, 204)
        self.assertFalse(d.exists())
        self.api.post(f"{self.base}/docs/{other['id']}/exports/", {"kind": "screen_pdf"}, format="json")
        self.assertTrue(any(services.doc_dir(self.store.pk, other["id"]).rglob("*.pdf")))           # سندِ دیگر دست‌نخورده
        self.assertFalse(DesignExport.objects.filter(doc_id=doc["id"]).exists())

    def test_cascade_delete_of_the_store_cleans_the_folders_too(self):
        doc = self.make("deck", use_ai=False)
        self.api.post(f"{self.base}/docs/{doc['id']}/exports/", {"kind": "screen_pdf"}, format="json")
        d = services.doc_dir(self.store.pk, doc["id"])
        self.assertTrue(d.is_dir())
        with self.captureOnCommitCallbacks(execute=True):
            DesignDoc.objects.filter(pk=doc["id"]).first().delete()                      # مثلِ ادمین یا پاک‌شدنِ زنجیره‌ای
        self.assertFalse(d.exists())

    def test_cleanup_never_leaves_the_design_root(self):
        outside = self.data.parent / "nm-design-outside-probe"
        outside.mkdir(exist_ok=True)
        try:
            self.assertFalse(services.remove_doc_files(self.store.pk, 987654))              # چیزی برای پاک‌کردن نیست
            self.assertTrue(outside.exists())
        finally:
            shutil.rmtree(outside, ignore_errors=True)

    # --- ۳) چک‌لیستِ کاتالوگ: صفحهٔ خالی
    def test_catalog_checklist_warns_about_blank_hero_lookbook_and_friends(self):
        doc = self.make("catalog")
        sc = self.api.get(f"{self.base}/docs/{doc['id']}/scene/").json()
        self.assertEqual({c["key"]: c for c in sc["checks"]}["empty"]["level"], "ok")        # کاتالوگِ خودکار صفحهٔ خالی ندارد
        for t in ("hero", "lookbook", "grid", "steps"):
            doc = self.ops(doc, [{"op": "add_page", "type": t, "spec": {}}])
        sc = self.api.get(f"{self.base}/docs/{doc['id']}/scene/").json()
        c = {c["key"]: c for c in sc["checks"]}["empty"]
        self.assertEqual(c["level"], "warn", c)
        self.assertIn("۴ صفحه خالی", c["title"])
        self.assertIn("محصولی برایش انتخاب نشده", c["detail"])
        pid = next(p["id"] for p in doc["data"]["pages"] if p["type"] == "hero" and not p.get("product"))
        doc = self.ops(doc, [{"op": "update_page", "page": pid, "set": {"product": self.products[0].pk}}])
        sc = self.api.get(f"{self.base}/docs/{doc['id']}/scene/").json()
        self.assertIn("۳ صفحه خالی", {c["key"]: c for c in sc["checks"]}["empty"]["title"])
        # صفحه‌ای که کاربر خودش چیزی رویش گذاشته خالی حساب نمی‌شود
        lb = next(p["id"] for p in doc["data"]["pages"] if p["type"] == "lookbook" and not p.get("images"))
        doc = self.ops(doc, [{"op": "add_element", "page": lb, "element": {"type": "text", "x": 10, "y": 10, "w": 60, "h": 10, "text": "نوشته", "size": 5, "color": "#112233"}}])
        sc = self.api.get(f"{self.base}/docs/{doc['id']}/scene/").json()
        self.assertIn("۲ صفحه خالی", {c["key"]: c for c in sc["checks"]}["empty"]["title"])

    def test_printer_pack_preflight_text_mentions_blank_pages(self):
        doc = self.make("catalog")
        doc = self.ops(doc, [{"op": "add_page", "type": "hero", "spec": {}}])
        e = self.api.post(f"{self.base}/docs/{doc['id']}/exports/", {"kind": "pack_printer"}, format="json").json()["export"]
        z = zipfile.ZipFile(io.BytesIO(b"".join(self.api.get(f"{self.base}/exports/{e['id']}/download/").streaming_content)))
        pre = next(n for n in z.namelist() if "PREFLIGHT" in n.upper())
        self.assertIn("صفحه خالی", z.read(pre).decode("utf-8"))

    # --- ۴) فهرستِ لایه‌ها هرگز «undefined» نشان نمی‌دهد (سمتِ داده: فرزندِ بخش فقط type دارد)
    def test_section_children_are_marked_as_blocks_in_new_docs(self):
        nodes = ui_doc._from_builder_blocks([{"id": "s1", "type": "section", "props": {}, "children": [{"id": "i1", "type": "image", "props": {"src": ""}}]}])
        self.assertEqual(nodes[0]["t"], "block")
        self.assertEqual(nodes[0]["children"][0]["t"], "block")                    # پیش‌تر نبود ⇒ «undefined» در فهرستِ لایه‌ها
        self.assertEqual(nodes[0]["children"][0]["type"], "image")

    # --- ۵) قطعهٔ تازه پیش از پابرگ می‌نشیند
    def test_new_component_lands_before_the_footer_header_first_footer_last(self):
        doc = self.make("ui", devices=["desktop"])
        f = doc["data"]["frames"][0]["id"]
        doc = self.ops(doc, [{"op": "add_node", "frame": f, "type": "c_cta_center_box"}])
        kids = doc["data"]["frames"][0]["children"]
        self.assertTrue(kids[-1]["type"].startswith("c_footer"), [k["type"] for k in kids])
        self.assertEqual(kids[-2]["type"], "c_cta_center_box")
        doc = self.ops(doc, [{"op": "add_node", "frame": f, "type": "c_footer_columns"}])         # پابرگِ دیگر ⇒ آخر
        self.assertTrue(doc["data"]["frames"][0]["children"][-1]["type"].startswith("c_footer"))
        doc = self.ops(doc, [{"op": "add_node", "frame": f, "type": "c_nav_classic"}])            # سربرگ ⇒ اول
        self.assertTrue(doc["data"]["frames"][0]["children"][0]["type"].startswith("c_nav"))
        doc = self.ops(doc, [{"op": "add_node", "frame": f, "type": "c_faq_two_col", "index": 1}])  # index صریح محترم است
        self.assertEqual(doc["data"]["frames"][0]["children"][1]["type"], "c_faq_two_col")
        # فریمِ بی‌پابرگ: مثلِ قبل در انتها
        doc = self.ops(doc, [{"op": "add_frame", "name": "خالی", "device": "phone"}])
        f2 = doc["data"]["frames"][-1]["id"]
        doc = self.ops(doc, [{"op": "add_node", "frame": f2, "type": "c_cta_center_box"}, {"op": "add_node", "frame": f2, "type": "c_faq_two_col"}])
        self.assertEqual([k["type"] for k in doc["data"]["frames"][-1]["children"]], ["c_cta_center_box", "c_faq_two_col"])

    # --- ۶) «ویرایش در طراح» تکرارپذیر است
    def test_edit_in_designer_reuses_the_project_until_the_page_changes(self):
        from apps.photoedit.models import PhotoProject

        doc = self.make("catalog")
        pid = doc["data"]["pages"][3]["id"]
        url = f"{self.base}/docs/{doc['id']}/designer/"
        a = self.api.post(url, {"page": pid}, format="json").json()
        b = self.api.post(url, {"page": pid}, format="json").json()
        self.assertFalse(a["reused"])
        self.assertTrue(b["reused"])
        self.assertEqual((a["project"], a["asset"]), (b["project"], b["asset"]))
        self.assertEqual(a["layers"], b["layers"])
        self.assertEqual(PhotoProject.objects.filter(store=self.store).count(), 1)
        other = self.api.post(url, {"page": doc["data"]["pages"][0]["id"]}, format="json").json()        # صفحهٔ دیگر ⇒ پروژهٔ دیگر
        self.assertFalse(other["reused"])
        self.assertEqual(PhotoProject.objects.filter(store=self.store).count(), 2)
        fresh = self.ops(self.api.get(f"{self.base}/docs/{doc['id']}/").json()["doc"], [{"op": "override", "page": pid, "el": "title", "set": {"text": "عنوانِ تازه"}}])
        c = self.api.post(url, {"page": pid}, format="json").json()                                        # صفحه عوض شد ⇒ پروژهٔ تازه
        self.assertFalse(c["reused"])
        self.assertNotEqual(c["project"], a["project"])
        PhotoProject.objects.filter(pk=c["project"]).delete()                                              # پروژه پاک شد ⇒ دوباره ساخته می‌شود
        d = self.api.post(url, {"page": pid}, format="json").json()
        self.assertFalse(d["reused"])
        self.assertGreater(fresh["rev"], doc["rev"])

    # --- ۷) ارائه: ردیفِ آمارِ بی‌منبع بی‌صدا گم نمی‌شود، و منبعِ خودکار وسطِ واژه نمی‌بُرد
    def test_deck_form_rows_without_source_are_reported_not_silently_dropped(self):
        doc = self.make("deck", use_ai=False, facts=[{"value": "۱۲", "label": "مربیِ فعال", "source": ""}, {"value": "", "label": "", "source": ""}])
        self.assertEqual(doc["data"]["meta"]["facts_dropped"], 1)                                     # ردیفِ کاملاً خالی شمرده نمی‌شود
        sc = self.api.get(f"{self.base}/docs/{doc['id']}/scene/").json()
        c = {c["key"]: c for c in sc["checks"]}["facts_dropped"]
        self.assertEqual(c["level"], "warn")
        self.assertIn("مربیِ فعال", c["detail"])
        stats = next(s for s in doc["data"]["slides"] if s["type"] == "stats")
        self.assertTrue(all(i["source"] for i in stats["items"]))                                      # آمارِ خودکار جایگزین شد، همه منبع دارند
        ok = self.make("deck", use_ai=False, facts=[{"value": "۱۲", "label": "مربیِ فعال", "source": "پرونده‌های داخلی"}])
        self.assertNotIn("facts_dropped", ok["data"]["meta"])
        self.assertEqual(next(s for s in ok["data"]["slides"] if s["type"] == "stats")["items"][0]["source"], "پرونده‌های داخلی")

    def test_auto_stat_sources_do_not_cut_names_mid_word_or_leave_open_brackets(self):
        long_a = "برنامهٔ تکی با هوش مصنوعی (فقط ورزشی یا غذایی)"
        long_b = "بستهٔ کاملِ سه‌ماههٔ تمرین و تغذیه همراه با پشتیبانیِ مربی و پیگیری هفتگی"
        Product.objects.filter(pk=self.products[3].pk).update(name=long_a)
        Product.objects.filter(pk=self.products[4].pk).update(name=long_b)
        doc = self.make("deck", use_ai=False)
        stats = next(s for s in doc["data"]["slides"] if s["type"] == "stats")
        sources = [i["source"] for i in stats["items"] if "قیمتِ ثبت‌شده" in i["source"]]
        self.assertEqual(len(sources), 2, stats)
        for s in sources:
            self.assertEqual(s.count("«"), s.count("»"), s)
            self.assertEqual(s.count("("), s.count(")"), s)
            self.assertTrue(s.endswith("»"), s)
        joined = " | ".join(sources)
        self.assertIn("«برنامهٔ تکی با هوش مصنوعی…»", joined)
        for w in ("پشتیبانیِ", "همراه"):
            self.assertNotIn(w[:3] + "…", joined)
        self.assertEqual(deck_doc.short_name("نامِ کوتاه"), "نامِ کوتاه")
        cut = deck_doc.short_name(long_b)
        self.assertTrue(cut.endswith("…") and long_b.startswith(cut[:-1]) and long_b[len(cut) - 1] == " ", cut)

    # --- ۸) برچسب‌ها و متن‌ها
    def test_mp4_export_has_a_persian_label_and_kiosk_readme_names_the_real_engine(self):
        doc = self.make("deck", use_ai=False)
        e = DesignExport.objects.create(doc_id=doc["id"], kind="mp4", state=DesignExport.State.RUNNING)
        label = services.export_dict(e)["label"]
        self.assertNotEqual(label, "mp4")
        self.assertIn("ویدیو", label)
        k = self.api.post(f"{self.base}/docs/{doc['id']}/exports/", {"kind": "pack_kiosk"}, format="json").json()["export"]
        z = zipfile.ZipFile(io.BytesIO(b"".join(self.api.get(f"{self.base}/exports/{k['id']}/download/").streaming_content)))
        readme = z.read("README-fa.txt").decode("utf-8")
        self.assertNotIn("موتور موشن", readme)
        self.assertIn("ffmpeg", readme)

    # --- ۹) «PDF نمایشی» لایهٔ متنِ جست‌وجوپذیر دارد؛ «PDF چاپی» نه (متنِ منحنی)
    def test_screen_pdf_has_a_searchable_text_layer_and_print_pdf_stays_outlined(self):
        doc = self.make("catalog")
        s = self.api.post(f"{self.base}/docs/{doc['id']}/exports/", {"kind": "screen_pdf"}, format="json").json()["export"]
        p = self.api.post(f"{self.base}/docs/{doc['id']}/exports/", {"kind": "print_pdf"}, format="json").json()["export"]
        screen = b"".join(self.api.get(f"{self.base}/exports/{s['id']}/download/").streaming_content)
        print_ = b"".join(self.api.get(f"{self.base}/exports/{p['id']}/download/").streaming_content)
        lines = pdf_text_layer(screen)
        text = "\n".join(lines)
        self.assertGreater(len(lines), 10)
        self.assertIn("آزمون", text)                                          # نامِ محصول‌ها از فارسیِ واقعی استخراج می‌شود
        self.assertIn(self.store.name, text)
        self.assertEqual(pdf_text_layer(print_), [])                            # چاپی: فقط منحنی
        self.assertNotIn(b"3 Tr", b"".join(_pdf_stream(b) for b in _pdf_objects(print_).values() if b"stream\n" in b and b"/Type /XObject" not in b))
        self.assertLess(len(screen), 3_000_000)
        # شمارِ نویسه‌های متفاوت از ۲۵۴ بیشتر شود ⇒ فونتِ تازه باز می‌شود و استخراج درست می‌ماند
        from . import pdf as pdfmod

        d = pdfmod.PdfDoc()
        runs = d.text_runs("".join(chr(0x4E00 + i) for i in range(300)))
        self.assertEqual(len(d.tfonts), 2)
        self.assertEqual(sum(len(c) for _, c in runs), 300)
