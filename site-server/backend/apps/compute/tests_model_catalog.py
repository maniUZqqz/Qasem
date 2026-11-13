"""«دانلودِ مدل‌ها»: کاتالوگِ ComfyUI / Hugging Face (processing/downloads/*.json) + مدل‌های سرورِ پردازش + دانلودِ خودکار.

    cd backend && ../venv/bin/python -X utf8 manage.py test apps.compute.tests_model_catalog --noinput

۱) manifestهای تازه درست و کامل‌اند (sha256، اندازه، نسخهٔ سنجاق‌شده، مجوز، VRAM، متنِ فارسی)؛ هر چیزی که مالک در سفارش
   خواسته بود (FLUX schnell/dev + T5/CLIP/ae، SDXL + یک چک‌پوینتِ آزاد، Fill، بزرگ‌کننده‌ها، ترمیمِ چهره، ControlNet، IP-Adapter،
   Depth-Anything-V2-Small، Wan 5B، LTX، RIFE) هست؛
۲) مجوزِ غیرباز هرگز خودکار نیست و هرگز به مجموعهٔ پیش‌فرض نمی‌رود؛
۳) کارتِ سرور: گروه‌ها به ترتیب، مجوز، VRAM، «نیاز دارد»، جای دیسک، وضعیتِ خودکار؛
۴) دانلودِ خودکار: تنظیم، فهرستِ خواسته‌ها، بلوکِ heartbeat، API؛ دانلودِ دستی: بازبینیِ دیسک و عاملِ قدیمی، افزودنِ نیازها.
"""
import json
import re
import shutil
import tempfile
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from . import api as compute_api
from . import auto_models as AM
from . import model_packages as MP
from . import voice_models as vm
from .models import ComputeJob, ComputeNode

DOWNLOADS = Path(settings.BASE_DIR).parent / "processing" / "downloads"
NEW_FILES = ["image.json", "upscale.json", "control.json", "depth.json", "video-extra.json"]
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
PERSIAN = re.compile(r"[؀-ۿ]")
TMP = tempfile.mkdtemp(prefix="nm-model-catalog-")


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)


def load(name):
    return json.loads((DOWNLOADS / name).read_text(encoding="utf-8"))


def all_docs():
    return {n: load(n) for n in NEW_FILES}


def all_items():
    return [(n, i) for n, d in all_docs().items() for i in d["items"]]


class ManifestTests(SimpleTestCase):
    def test_every_new_manifest_parses_and_has_items(self):
        for name, doc in all_docs().items():
            self.assertTrue(doc["items"], name)
            self.assertEqual(doc["group"], name.rsplit(".", 1)[0], name)
            self.assertTrue(doc.get("license_note"), name)
            self.assertTrue(doc.get("generated"), name)

    def test_items_are_pinned_verified_and_licensed(self):
        ids = set()
        for name, i in all_items():
            self.assertNotIn(i["id"], ids, i["id"])
            ids.add(i["id"])
            self.assertEqual(i["id"].split(":")[0], i["package"], i["id"])
            self.assertTrue(i.get("license"), i["id"])
            self.assertIs(i.get("optional"), True, "%s: every new package is optional (never in the default set)" % i["id"])
            self.assertIn(i["kind"], ("file", "git"), i["id"])
            if i["kind"] == "file":
                self.assertEqual(len(i["urls"]), 1, i["id"])
                m = re.match(r"^\{HF\}/([^/]+/[^/]+)/resolve/([0-9a-f]{40})/(.+)$", i["urls"][0])
                self.assertTrue(m, "%s: a Hugging Face URL pinned to a commit" % i["id"])
                self.assertTrue(HEX64.match(i["sha256"]), i["id"])
                self.assertGreater(i["size"], 0, i["id"])
                self.assertTrue(i["dest"].startswith("{COMFYUI}\\models\\") or i["dest"].startswith("{MODELS}\\"), i["id"])
                self.assertTrue(i["source"].startswith("https://huggingface.co/%s/blob/" % m.group(1)), i["id"])
            else:
                self.assertTrue(HEX40.match(i["ref"]), i["id"])
                self.assertTrue(i["url"].startswith("https://github.com/"), i["id"])
                self.assertIn("\\custom_nodes\\", i["dest"], i["id"])

    def test_every_package_is_fully_described(self):
        for name, doc in all_docs().items():
            pkgs = {i["package"] for i in doc["items"]}
            info = doc["package_info"]
            self.assertEqual(set(info), pkgs, name)
            self.assertEqual(set(doc["packages"]), pkgs, name)
            for pk, row in info.items():
                self.assertIn(row["display"], {g["key"] for g in MP.GROUPS}, pk)
                self.assertTrue(PERSIAN.search(row["title_fa"]), pk)
                self.assertTrue(PERSIAN.search(row["note_fa"]), pk)
                self.assertIn(row["license_class"], ("open", "restricted", "noncommercial"), pk)
                self.assertTrue(row["license"], pk)
                self.assertIn(row["vram"]["fit"], ("full", "offload", "tight"), pk)
                self.assertTrue(PERSIAN.search(row["vram"]["note_fa"]), pk)
                self.assertTrue(row["features"], pk)
                self.assertLessEqual(set(row["features"]), set(MP.FEATURES), pk)
                self.assertIsInstance(row["auto"], bool, pk)
                self.assertIsInstance(row["priority"], int, pk)

    def test_needs_exist_and_never_cycle(self):
        info = {pk: r for d in all_docs().values() for pk, r in d["package_info"].items()}
        for pk, r in info.items():
            for dep in r["needs"]:
                self.assertIn(dep, info, "%s needs %s" % (pk, dep))
        for pk in info:
            seen, stack = set(), list(info[pk]["needs"])
            while stack:
                cur = stack.pop()
                self.assertNotEqual(cur, pk, "cycle at %s" % pk)
                if cur not in seen:
                    seen.add(cur)
                    stack.extend(info[cur]["needs"])

    def test_non_open_licences_are_never_automatic_and_never_pulled_in(self):
        info = {pk: r for d in all_docs().values() for pk, r in d["package_info"].items()}
        for pk, r in info.items():
            if r["license_class"] != "open":
                self.assertFalse(r["auto"], "%s: a non-open licence is never automatic" % pk)
            else:
                for dep in r["needs"]:
                    self.assertEqual(info[dep]["license_class"], "open", "%s (open) must not need %s" % (pk, dep))
        nc = {"flux-dev", "flux-fill", "flux-kontext", "ultrasharp-4x", "nmkd-siax-4x", "codeformer", "controlnet-union-flux"}
        self.assertTrue(nc <= {pk for pk, r in info.items() if r["license_class"] == "noncommercial"})
        self.assertEqual(info["ltx-video-distilled"]["license_class"], "restricted")

    def test_files_two_packages_share_are_the_same_bytes(self):
        by_dest = {}
        for _n, i in all_items():
            if i["kind"] == "file":
                by_dest.setdefault(i["dest"].lower(), []).append(i)
        for dest, rows in by_dest.items():
            self.assertEqual(len({(r["sha256"], r["size"]) for r in rows}), 1, dest)
        shared = {d for d, r in by_dest.items() if len(r) > 1}
        self.assertIn("{comfyui}\\models\\vae\\ae.safetensors", shared)

    def test_the_owners_list_is_complete(self):
        pk = {i["package"] for _n, i in all_items()}
        want = {
            "flux-schnell", "flux-dev", "flux-common", "flux-fill", "flux-kontext", "sdxl-base", "sdxl-realvis", "zimage-turbo",
            "esrgan-x4plus", "ultrasharp-4x", "nmkd-siax-4x", "face-restore", "codeformer",
            "controlnet-union-sdxl", "controlnet-union-flux", "ipadapter-sdxl", "nodes-ipadapter-plus",
            "depth-anything-v2-small", "wan22-ti2v-5b", "ltx-video-distilled", "frame-interp",
        }
        self.assertLessEqual(want, pk)
        files = {i["id"]: i for _n, i in all_items()}
        # the concrete files of the brief
        for fid in ("flux-common:t5xxl_fp8", "flux-common:clip_l", "flux-common:ae_vae", "flux-schnell:schnell_fp8", "flux-dev:dev_fp8",
                    "flux-fill:fill_dev_fp8", "sdxl-base:sdxl_base", "sdxl-realvis:realvisxl_v5", "esrgan-x4plus:realesrgan_x4plus",
                    "ultrasharp-4x:ultrasharp", "nmkd-siax-4x:siax", "face-restore:gfpgan_v14", "codeformer:codeformer_v010",
                    "controlnet-union-sdxl:xinsir_union_promax", "controlnet-union-flux:shakker_union_pro2",
                    "ipadapter-sdxl:plus_sdxl_vith", "depth-anything-v2-small:hf_weights", "depth-anything-v2-small:onnx_fp32",
                    "wan22-ti2v-5b:ti2v_5b_fp16", "ltx-video-distilled:ltxv_2b_distilled_fp8", "frame-interp:rife_v425"):
            self.assertIn(fid, files)
        # every target folder of the brief is used
        folders = {i["dest"].split("\\")[2] for i in files.values() if i["dest"].startswith("{COMFYUI}\\models\\")}
        self.assertLessEqual({"checkpoints", "diffusion_models", "text_encoders", "vae", "upscale_models", "controlnet", "ipadapter",
                              "clip_vision", "frame_interpolation"}, folders)
        # display groups of the card
        shown = {r["display"] for d in all_docs().values() for r in d["package_info"].values()}
        self.assertEqual(shown, {"image", "video", "upscale", "control", "depth"})
        self.assertEqual([g["key"] for g in MP.GROUPS], ["image", "video", "upscale", "control", "depth", "voice", "matting"])

    def test_the_default_set_is_untouched(self):
        """the new manifests add nothing to what a node downloads by itself at start-up: no non-optional item"""
        self.assertTrue(all(i.get("optional") for _n, i in all_items()))

    def test_depth_is_the_apache_small_model_only(self):
        doc = load("depth.json")
        self.assertEqual({i["package"] for i in doc["items"]}, {"depth-anything-v2-small"})
        text = json.dumps(doc)
        self.assertNotIn("Depth-Anything-V2-Large", text)
        self.assertNotIn("Depth-Anything-V2-Base", text)
        self.assertEqual(doc["package_info"]["depth-anything-v2-small"]["license"], "Apache-2.0")

    def test_ui_text_names_no_adobe_products(self):
        text = json.dumps(all_docs(), ensure_ascii=False) + json.dumps(MP.LABELS, ensure_ascii=False)
        for bad in ("Photoshop", "Premiere", "Adobe", "After Effects"):
            self.assertNotIn(bad, text)


@override_settings(NM_DATA_DIR=Path(TMP), IS_TEST=True)
class CatalogTests(SimpleTestCase):
    def setUp(self):
        MP._cache.update(key=None, data=None)

    def test_catalog_has_every_package_with_license_and_needs(self):
        cat = MP.catalog()
        self.assertIn("flux-schnell", cat)
        self.assertEqual(cat["flux-schnell"]["license_class"], "open")
        self.assertEqual(cat["flux-dev"]["license_class"], "noncommercial")
        self.assertFalse(cat["flux-dev"]["auto"])
        self.assertTrue(cat["flux-schnell"]["auto"])
        self.assertEqual(cat["flux-schnell"]["needs"], ["flux-common"])
        self.assertEqual(cat["flux-schnell"]["size_with_needs_mb"], cat["flux-schnell"]["size_mb"] + cat["flux-common"]["size_mb"])
        self.assertEqual(cat["wan22-flf"]["license_class"], "open")                        # old packages keep working
        self.assertEqual(cat["moss-tts"]["features"], ["voice_studio"])
        self.assertFalse(cat["wan22-flf"]["optional"])                                     # the default set is unchanged
        self.assertEqual(cat["nodes-ipadapter-plus"]["kinds"], ["git"])

    def test_expand_needs_adds_dependencies_once(self):
        self.assertEqual(MP.expand_needs(["flux-schnell"]), ["flux-schnell", "flux-common"])
        both = MP.expand_needs(["flux-schnell", "ltx-video-distilled"])
        self.assertEqual(both.count("flux-common"), 1)
        ip = MP.expand_needs(["ipadapter-sdxl"])
        self.assertEqual(set(ip), {"ipadapter-sdxl", "sdxl-base", "nodes-ipadapter-plus"})

    def test_display_group_uses_package_info_then_old_table(self):
        self.assertEqual(MP._display_group("image", "flux-dev", "image"), "image")
        self.assertEqual(MP._display_group("video-extra", "frame-interp", "video"), "video")
        self.assertEqual(MP._display_group("matting", "video-matting"), "matting")
        self.assertEqual(MP._display_group("video", "wan22-flf"), "video")
        self.assertEqual(MP._display_group("", "something-else"), "other")

    def test_the_multiangle_lanes_packages_sit_in_depth_with_a_licence_and_a_feature(self):
        cat = MP.catalog()
        for pk in ("multiangle-runtime", "multiangle-detect", "multiangle-depth"):
            self.assertIn(pk, cat)
            self.assertEqual(MP._display_group(cat[pk]["group"], pk, cat[pk]["display"]), "depth", pk)
            self.assertTrue(cat[pk]["license"], pk)
            self.assertEqual(cat[pk]["license_class"], "open")
            self.assertIn("multiangle", cat[pk]["features"])
            self.assertIn(pk, MP.LABELS)


def node(name="DESKTOP", online=True, packages=None, disk_free_gb=93.4, disk_mb=None, **models):
    caps = {"agent": "2.10", "comfyui": True, "disk_free_gb": disk_free_gb, "disk_total_gb": 511.0,
            "models": {"running": False, "packages": packages if packages is not None else {}, **models}}
    if disk_mb is not None:
        caps["models"]["disk_mb"] = disk_mb
    return ComputeNode.objects.create(name=name, capabilities=caps,
                                      last_seen=timezone.now() if online else timezone.now() - timedelta(hours=1))


def status_for_all(installed=(), **over):
    """the report an updated node sends: every catalog package, installed ones marked"""
    out = {}
    for pk, c in MP.catalog().items():
        mb = c["size_mb"]
        got = pk in installed
        out[pk] = {"installed": got, "optional": c["optional"], "total_mb": mb, "missing_mb": 0 if got else mb, "in_comfyui": 0}
    out.update(over)
    return out


@override_settings(NM_DATA_DIR=Path(TMP), IS_TEST=True)
class NodeCardTests(TestCase):
    def setUp(self):
        MP._cache.update(key=None, data=None)
        (Path(TMP) / AM.FILE).unlink(missing_ok=True)

    def groups(self, n):
        return {g["key"]: {p["key"]: p for p in g["packages"]} for g in MP.for_node(n)["groups"]}

    def test_groups_come_in_the_order_of_the_brief(self):
        n = node(packages=status_for_all())
        keys = [g["key"] for g in MP.for_node(n)["groups"]]
        self.assertEqual(keys, ["image", "video", "upscale", "control", "depth", "voice", "matting"])

    def test_row_carries_license_vram_features_needs_and_auto(self):
        g = self.groups(node(packages=status_for_all(installed=("flux-common",))))
        s = g["image"]["flux-schnell"]
        self.assertEqual(s["license_class"], "open")
        self.assertTrue(s["commercial"])
        self.assertEqual(s["vram_fit"], "offload")
        self.assertEqual([f["key"] for f in s["features"]], ["image_studio", "thumbnails"])
        self.assertEqual([r["key"] for r in s["needs"]], ["flux-common"])
        self.assertTrue(s["needs"][0]["installed"])                       # the encoders are already there: not counted again
        self.assertEqual(s["download_mb"], s["missing_mb"])
        self.assertEqual(s["auto"]["mode"], "on")                         # image_studio is on by default
        d = g["image"]["flux-dev"]
        self.assertFalse(d["commercial"])
        self.assertEqual(d["license_class"], "noncommercial")
        self.assertEqual(d["auto"]["mode"], "never")
        self.assertEqual(g["image"]["sdxl-base"]["auto"]["mode"], "off")  # design_styles is off by default
        self.assertEqual(g["image"]["zimage-turbo"]["auto"]["mode"], "manual")
        self.assertEqual(g["matting"]["photo-background"]["auto"]["mode"], "default")
        self.assertEqual(g["control"]["nodes-ipadapter-plus"]["kind"], "node")
        self.assertTrue(g["control"]["nodes-ipadapter-plus"]["needs_restart"])
        self.assertTrue(g["image"]["flux-fill"]["provenance"])
        self.assertTrue(g["upscale"]["esrgan-x4plus"]["sources"][0].startswith("Comfy-Org/"))

    def test_download_size_counts_the_needs_that_are_missing(self):
        g = self.groups(node(packages=status_for_all()))
        s = g["image"]["flux-schnell"]
        common = g["image"]["flux-common"]
        self.assertEqual(s["download_mb"], s["missing_mb"] + common["missing_mb"])

    def test_fits_uses_the_free_disk_of_the_models_drive(self):
        roomy = self.groups(node("A", packages=status_for_all(), disk_free_gb=93.4))
        self.assertTrue(roomy["image"]["flux-schnell"]["fits"])
        self.assertTrue(roomy["image"]["zimage-turbo"]["fits"])
        tight = self.groups(node("B", packages=status_for_all(), disk_free_gb=15.0))
        self.assertFalse(tight["image"]["flux-schnell"]["fits"])
        self.assertTrue(tight["upscale"]["esrgan-x4plus"]["fits"])
        # the node's own numbers beat disk_free_gb: the smaller of the data drive and the ComfyUI drive
        c = node("C", packages=status_for_all(), disk_free_gb=500.0, disk_mb={"data_free": 400000, "comfy_free": 3000})
        split = self.groups(c)
        self.assertFalse(split["image"]["sdxl-base"]["fits"])
        self.assertEqual(MP.for_node(c)["node"]["disk_free_mb"], 3000)

    def test_old_agent_without_the_new_packages_is_told_to_update(self):
        old = {k: v for k, v in status_for_all().items() if k in ("moss-tts", "wan22-flf", "photo-background")}
        n = node(packages=old)
        self.assertTrue({"image", "upscale"} <= {g["key"] for g in MP.for_node(n)["groups"]})
        states = {p["state"] for g in MP.for_node(n)["groups"] for p in g["packages"] if p["key"] == "flux-schnell"}
        self.assertEqual(states, {"unknown"})
        self.assertIn("به‌روزرسانی", MP.preflight(n, ["flux-schnell"]))
        self.assertEqual(MP.preflight(n, ["moss-tts"]), "")               # old packages are unaffected

    def test_preflight_refuses_when_the_disk_cannot_hold_it(self):
        n = node(packages=status_for_all(), disk_free_gb=10.0)
        msg = MP.preflight(n, ["flux-schnell"])
        self.assertIn("فضای دیسک", msg)
        ok = node("ROOMY", packages=status_for_all(), disk_free_gb=300.0)
        self.assertEqual(MP.preflight(ok, ["flux-schnell"]), "")
        self.assertEqual(MP.preflight(node("D", packages=status_for_all(installed=("flux-schnell", "flux-common")), disk_free_gb=1.0),
                                      ["flux-schnell"]), "")             # nothing left to download

    def test_auto_state_from_the_node_report_and_pending_total(self):
        n = node(packages=status_for_all(), auto={"states": {"flux-schnell": "waiting_window", "esrgan-x4plus": "no_disk"},
                                                  "why": {"depth-anything-v2-small": "boom"}})
        g = self.groups(n)
        self.assertEqual(g["image"]["flux-schnell"]["auto"]["state"], "waiting_window")
        self.assertEqual(g["upscale"]["esrgan-x4plus"]["auto"]["state"], "no_disk")
        data = MP.for_node(n)
        self.assertTrue(data["auto"]["reported"])
        self.assertEqual(data["auto"]["why"], {"depth-anything-v2-small": "boom"})
        self.assertGreater(data["auto"]["pending_mb"], 16000)             # FLUX + encoders + the three small ones

    def test_installed_and_queue_states_still_work(self):
        n = node(packages=status_for_all(installed=("flux-dev",)))
        ComputeJob.objects.create(kind="node.models", node_wanted=n.name, message="منتظرِ بازهٔ شبانه",
                                  payload={"action": "download", "packages": ["zimage-turbo"]})
        g = self.groups(n)
        self.assertEqual(g["image"]["flux-dev"]["state"], "installed")
        self.assertEqual(g["image"]["zimage-turbo"]["state"], "queued")

    def test_ollama_rides_along(self):
        data = MP.listing()
        self.assertIn("ollama", data)
        self.assertIn("models", data["ollama"])
        self.assertIn("auto", data)
        self.assertEqual(data["ollama_page"], "/admin/providers")


@override_settings(NM_DATA_DIR=Path(TMP), IS_TEST=True)
class AutoSettingsTests(TestCase):
    def setUp(self):
        MP._cache.update(key=None, data=None)
        (Path(TMP) / AM.FILE).unlink(missing_ok=True)

    def test_defaults_turn_on_the_four_safe_features_only(self):
        cfg = AM.load()
        self.assertTrue(cfg["enabled"])
        self.assertEqual(cfg["reserve_gb"], 25)
        self.assertEqual({k for k, v in cfg["features"].items() if v}, {"image_studio", "photo_enhance", "smooth_motion", "depth_3d"})
        self.assertEqual(set(cfg["features"]), {k for k, v in MP.FEATURES.items() if v[1]})

    def test_wanted_follows_the_switches_and_never_lists_a_non_open_package(self):
        want = AM.wanted()
        self.assertEqual(set(want), {"flux-schnell", "esrgan-x4plus", "frame-interp", "depth-anything-v2-small"})
        cat = MP.catalog()
        self.assertEqual([cat[p]["priority"] for p in want], sorted(cat[p]["priority"] for p in want))
        AM.save({"features": {"design_styles": True, "video_ai": True, "face_restore": True}})
        more = set(AM.wanted())
        self.assertTrue({"sdxl-base", "sdxl-realvis", "controlnet-union-sdxl", "ipadapter-sdxl", "nodes-ipadapter-plus",
                         "wan22-ti2v-5b", "face-restore"} <= more)
        for p in more:
            self.assertEqual(cat[p]["license_class"], "open", p)
        self.assertNotIn("flux-dev", more)
        self.assertNotIn("ltx-video-distilled", more)
        AM.save({"features": {"image_studio": False}})
        self.assertNotIn("flux-schnell", AM.wanted())
        AM.save({"enabled": False})
        self.assertEqual(AM.wanted(), [])

    def test_save_validates(self):
        for bad in ({"enabled": "yes"}, {"reserve_gb": 2}, {"reserve_gb": 9999}, {"reserve_gb": "abc"}, {"features": {"nope": True}},
                    {"features": {"image_studio": "on"}}, {"features": ["x"]}):
            with self.assertRaises(AM.AutoError, msg=str(bad)):
                AM.save(bad)
        with self.assertRaises(AM.AutoError):
            AM.save("not a dict")
        self.assertEqual(AM.load()["reserve_gb"], 25)                       # nothing half-saved

    def test_roundtrip_and_a_damaged_file_means_defaults(self):
        AM.save({"reserve_gb": 40, "features": {"depth_3d": False}})
        cfg = AM.load()
        self.assertEqual(cfg["reserve_gb"], 40)
        self.assertFalse(cfg["features"]["depth_3d"])
        (Path(TMP) / AM.FILE).write_text("{not json", encoding="utf-8")
        self.assertEqual(AM.load(), AM.defaults())
        (Path(TMP) / AM.FILE).write_text(json.dumps({"enabled": False, "features": {"image_studio": False, "ghost": True}, "reserve_gb": "x"}),
                                         encoding="utf-8")
        cfg = AM.load()
        self.assertFalse(cfg["enabled"])
        self.assertNotIn("ghost", cfg["features"])
        self.assertEqual(cfg["reserve_gb"], 25)

    def test_control_block_is_what_the_node_reads(self):
        blk = AM.control_block()
        self.assertEqual(set(blk), {"enabled", "packages", "reserve_gb", "big_mb"})
        self.assertEqual(blk["big_mb"], 1536)
        self.assertIsInstance(blk["packages"], list)

    def test_heartbeat_control_carries_models_auto(self):
        n = node()
        out = compute_api._control(n)
        self.assertIn("models_auto", out)
        self.assertIn("flux-schnell", out["models_auto"]["packages"])
        self.assertIn("downloads", out)                                      # the existing blocks are still there

    def test_view_lists_features_with_sizes_counted_once(self):
        view = AM.view()
        keys = [f["key"] for f in view["features"]]
        self.assertEqual(keys, [k for k, v in MP.FEATURES.items() if v[1]])
        studio = next(f for f in view["features"] if f["key"] == "image_studio")
        self.assertTrue(studio["on"])
        cat = MP.catalog()
        self.assertEqual(studio["size_mb"], cat["flux-schnell"]["size_mb"] + cat["flux-common"]["size_mb"])
        self.assertTrue(all(f["packages"] for f in view["features"]), "every switch has something to download")


@override_settings(NM_DATA_DIR=Path(TMP), IS_TEST=True)
class ApiTests(TestCase):
    def setUp(self):
        MP._cache.update(key=None, data=None)
        (Path(TMP) / AM.FILE).unlink(missing_ok=True)
        U = get_user_model()
        self.staff = U.objects.create_user("mc-boss", "b@x.io", "pw", is_staff=True)
        self.plain = U.objects.create_user("mc-plain", password="x")
        self.c = APIClient()
        self.c.force_authenticate(self.staff)

    def test_listing_has_packages_ollama_and_auto(self):
        node(packages=status_for_all())
        r = self.c.get("/api/v1/compute/models/")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual([g["key"] for g in body["nodes"][0]["groups"]][:2], ["image", "video"])
        self.assertIn("ollama", body)
        self.assertTrue(body["auto"]["enabled"])
        self.assertTrue(body["auto"]["features"])

    def test_auto_settings_api(self):
        r = self.c.get("/api/v1/compute/models/auto/")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["enabled"])
        r = self.c.post("/api/v1/compute/models/auto/", {"features": {"design_styles": True}, "reserve_gb": 30}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["reserve_gb"], 30)
        self.assertIn("sdxl-base", r.json()["wanted"])
        r = self.c.post("/api/v1/compute/models/auto/", {"reserve_gb": 1}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("error", r.json())
        r = self.c.post("/api/v1/compute/models/auto/", {"enabled": False}, format="json")
        self.assertEqual(r.json()["wanted"], [])

    def test_staff_only(self):
        p = APIClient()
        p.force_authenticate(self.plain)
        self.assertEqual(p.get("/api/v1/compute/models/").status_code, 403)
        self.assertEqual(p.get("/api/v1/compute/models/auto/").status_code, 403)
        self.assertEqual(p.post("/api/v1/compute/models/auto/", {"enabled": False}, format="json").status_code, 403)

    def test_download_adds_the_needs_and_checks_the_disk(self):
        n = node("ROOMY", packages=status_for_all(), disk_free_gb=300.0)
        r = self.c.post(f"/api/v1/compute/nodes/{n.pk}/models/download/", {"packages": ["flux-schnell"]}, format="json")
        self.assertEqual(r.status_code, 202, r.content)
        job = ComputeJob.objects.get(uid=r.json()["job"])                  # the response carries the voice card under "packages"
        self.assertEqual(sorted(job.payload["packages"]), ["flux-common", "flux-schnell"])
        small = node("SMALL", packages=status_for_all(), disk_free_gb=12.0)
        r = self.c.post(f"/api/v1/compute/nodes/{small.pk}/models/download/", {"packages": ["flux-schnell"]}, format="json")
        self.assertEqual(r.status_code, 409)
        self.assertIn("فضای دیسک", r.json()["error"])
        self.assertFalse(ComputeJob.objects.filter(kind="node.models", node_wanted="SMALL").exists())
        old = node("OLD", packages={"moss-tts": {"installed": True, "total_mb": 15800, "missing_mb": 0}})
        r = self.c.post(f"/api/v1/compute/nodes/{old.pk}/models/download/", {"packages": ["esrgan-x4plus"]}, format="json")
        self.assertEqual(r.status_code, 409)
        self.assertIn("به‌روزرسانی", r.json()["error"])
        self.assertEqual(vm._agent_ok(old), True)


@override_settings(NM_DATA_DIR=Path(TMP), IS_TEST=True)
class SelfTestModuleTests(TestCase):
    """selftests/model_catalog.py: the automatic acceptance of the model catalog on the node."""

    def setUp(self):
        MP._cache.update(key=None, data=None)
        (Path(TMP) / AM.FILE).unlink(missing_ok=True)
        from .selftests import REGISTRY, load_all, runner
        load_all()
        self.R = REGISTRY
        self.runner = runner

    def verdict(self, key, n):
        from .models import SelfTestResult, SelfTestRun
        run = SelfTestRun.objects.create(node=n, trigger="manual")
        res = SelfTestResult.objects.create(run=run, key=key, label="x", state="PENDING")
        return self.R[key].virtual(self.runner.Ctx(n, run, {}, result=res))

    def test_the_four_tests_are_registered(self):
        for key in ("model_catalog", "model_catalog_download", "model_catalog_installed", "model_catalog_auto"):
            self.assertIn(key, self.R)
        self.assertEqual(self.R["model_catalog_download"].kind, "node.models")
        self.assertEqual(self.R["model_catalog_installed"].after, ("model_catalog_download",))
        self.assertIsNone(self.R["model_catalog_download"].virtual)
        self.assertFalse(self.R["model_catalog_download"].optional)

    def test_catalog_test_passes_when_every_package_is_reported(self):
        v = self.verdict("model_catalog", node(packages=status_for_all(installed=("frame-interp",)), disk_mb={"data_free": 90000, "comfy_free": 80000}))
        self.assertTrue(v.ok, v.detail)
        self.assertIn("گروه", v.detail)

    def test_catalog_test_fails_for_an_old_agent_and_says_what_to_do(self):
        old = {k: v for k, v in status_for_all().items() if k in ("moss-tts", "wan22-flf")}
        v = self.verdict("model_catalog", node(packages=old, disk_mb={"data_free": 90000}))
        self.assertFalse(v.ok)
        self.assertFalse(v.wait)
        self.assertIn("به‌روزرسانی", v.detail)

    def test_catalog_test_waits_for_the_first_report_and_needs_the_disk_number(self):
        v = self.verdict("model_catalog", node("A", packages={}))
        self.assertTrue(v.wait)
        v = self.verdict("model_catalog", node("B", packages=status_for_all()))
        self.assertFalse(v.ok)
        self.assertIn("دیسک", v.detail)

    def test_download_job_is_the_small_rife_package_and_its_check(self):
        n = node(packages=status_for_all(), disk_mb={"data_free": 90000})
        spec = self.R["model_catalog_download"].build(self.runner.Ctx(n, None, {}))
        self.assertEqual(spec.kind, "node.models")
        self.assertEqual(spec.payload["packages"], ["frame-interp"])
        self.assertEqual(MP.catalog()["frame-interp"]["size_mb"] < 200, True)

        class FakeCtx:
            def __init__(self, data):
                self.data = data

            def read_json(self, job, name):
                return self.data

        t = self.R["model_catalog_download"]
        self.assertTrue(t.check(FakeCtx({"result": "started", "status": {"running": True}}), None).ok)
        self.assertFalse(t.check(FakeCtx({"result": "x"}), None).ok)
        self.assertFalse(t.check(FakeCtx(None), None).ok)
        self.assertFalse(t.check(FakeCtx({"result": "x", "status": {"error": "disk", "running": False}}), None).ok)

    def test_installed_test_waits_then_passes_and_fails_on_an_error(self):
        pk = status_for_all()
        v = self.verdict("model_catalog_installed", node("W", packages=pk))
        self.assertTrue(v.wait)
        running = node("R", packages=pk, running=True, progress={"bytes_done": 50, "bytes_total": 100, "current": "frame-interp:rife"})
        v = self.verdict("model_catalog_installed", running)
        self.assertTrue(v.wait)
        self.assertIn("50", v.detail)
        v = self.verdict("model_catalog_installed", node("E", packages=pk, error="sha256 mismatch"))
        self.assertFalse(v.ok)
        self.assertFalse(v.wait)
        v = self.verdict("model_catalog_installed", node("OK", packages=status_for_all(installed=("frame-interp",))))
        self.assertTrue(v.ok, v.detail)

    def test_auto_test_states(self):
        wanted = AM.wanted()
        self.assertIn("frame-interp", wanted)
        cat = MP.catalog()
        v = self.verdict("model_catalog_auto", node("N0", packages=status_for_all()))
        self.assertTrue(v.wait)                                            # the node has not reported yet
        fine = {p: ("installed" if cat[p]["size_mb"] < 1536 else "waiting_window") for p in wanted}
        v = self.verdict("model_catalog_auto", node("N1", packages=status_for_all(installed=[p for p in wanted if cat[p]["size_mb"] < 1536]),
                                                    auto={"states": fine}))
        self.assertTrue(v.ok, v.detail)
        small = next(p for p in wanted if cat[p]["size_mb"] < 1536)
        busy = dict(fine, **{small: "downloading"})
        v = self.verdict("model_catalog_auto", node("N2", packages=status_for_all(), auto={"states": busy}))
        self.assertTrue(v.wait)
        bad = dict(fine, **{small: "failed"})
        v = self.verdict("model_catalog_auto", node("N3", packages=status_for_all(), auto={"states": bad, "why": {small: "disk error"}}))
        self.assertFalse(v.ok)
        self.assertIn("disk error", v.detail)
        AM.save({"enabled": False})
        v = self.verdict("model_catalog_auto", node("N4", packages=status_for_all(), auto={"states": fine}))
        self.assertFalse(v.ok)
        self.assertTrue(self.R["model_catalog_auto"].available(node("N5"))[0])

    def test_the_old_docs_block_is_gone_so_the_module_is_the_only_definition(self):
        text = (Path(settings.BASE_DIR).parent / "docs" / "selftests" / "model-catalog.md").read_text(encoding="utf-8")
        self.assertNotIn("```json", text)
