"""گرهٔ پردازش: ماژولِ ``processing/brandchar_jobs.py`` (انتخابِ پروفایل، کنترل‌ها، ثبتِ کار و گزارشِ قابلیت)، ثبتِ یک‌خطیِ محافظت‌شده در ``agent.py``،
فایلِ نصبِ خودکار (``requirements.d/brandchar.json``) و آزمونِ خودکارِ سرورِ پردازش."""
import importlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

from django.conf import settings
from django.test import SimpleTestCase

PROC = Path(settings.BASE_DIR).parent / "processing"
PROFILES = [
    {"id": "flux-product-balanced", "kind": "image", "controls": [{"name": n} for n in ("width", "height", "steps", "guidance", "seed")]},
    {"id": "flux-edit-balanced", "kind": "edit", "controls": [{"name": n} for n in ("width", "height", "steps", "denoise", "guidance", "seed")]},
    {"id": "flux-edit-preserve", "kind": "edit", "controls": [{"name": n} for n in ("width", "height", "steps", "denoise", "guidance", "seed")]},
]


def load():
    if str(PROC) not in sys.path:
        sys.path.insert(0, str(PROC))
    return importlib.import_module("brandchar_jobs")


class ModuleTests(SimpleTestCase):
    def test_kind_and_version(self):
        m = load()
        self.assertEqual(m.KIND, "brandchar.render")
        self.assertEqual(m.KINDS, ("brandchar.render",))

    def test_profile_choice(self):
        m = load()
        self.assertEqual(m.pick_profile(PROFILES, "", True)["id"], "flux-edit-balanced")
        self.assertEqual(m.pick_profile(PROFILES, "flux-edit-preserve", True)["id"], "flux-edit-preserve")
        self.assertEqual(m.pick_profile(PROFILES, "", False)["id"], "flux-product-balanced")
        self.assertEqual(m.pick_profile(PROFILES, "nope", True)["id"], "flux-edit-balanced")
        self.assertIsNone(m.pick_profile([{"id": "wan22-480p-short", "kind": "video"}], "", True))

    def test_controls_are_clamped_and_limited_to_the_profile(self):
        m = load()
        edit = PROFILES[1]
        c = m.controls_from({"width": 99999, "height": 100, "steps": 500, "guidance": "x", "denoise": 0.01, "seed": 7, "evil": 1}, edit)
        self.assertEqual((c["width"], c["height"], c["steps"], c["denoise"], c["seed"]), (1536, 512, 50, 0.2, 7))
        self.assertNotIn("guidance", c)
        self.assertNotIn("evil", c)
        txt = m.controls_from({"denoise": 0.6, "seed": 3}, PROFILES[0])
        self.assertNotIn("denoise", txt)
        self.assertEqual(m.controls_from({"seed": "-5"}, edit)["seed"], -5)

    def test_identity_tools_are_reported_not_required(self):
        m = load()
        self.assertEqual(m.identity_tools(["KSampler", "ApplyPulidFlux", "IPAdapterAdvanced"]), ["ipadapter", "pulid"])
        self.assertEqual(m.identity_tools(["KSampler"]), [])
        self.assertEqual(m.identity_tools(None), [])

    def test_run_builds_the_graph_through_the_agents_own_functions(self):
        m = load()
        calls = {}

        class Job:
            uid = "abcdef1234567890"
            payload = {"prompt": "a mascot", "negative_prompt": "text", "reference": "reference.png", "width": 512, "height": 512, "steps": 4, "denoise": 0.55, "seed": 7, "mode": "illustrated"}
            progress_msgs = []

            def input_path(self, n):
                return "/x/" + n

            def input_bytes(self, n):
                return b"PNG"

            def progress(self, f, msg="", meta=None):
                self.progress_msgs.append(msg)

        agent = SimpleNamespace(load_profiles=lambda: PROFILES, comfy_upload=lambda name, data: calls.setdefault("upload", name) or name,
                                apply_profile=lambda profile, prompt, neg, image, ctl: calls.update(profile=profile["id"], prompt=prompt, image=image, ctl=ctl) or {"graph": 1},
                                comfy_run=lambda graph, job: (["/o/image.png"], "image.png"))
        out = m.run(Job(), agent)
        self.assertEqual(out["primary"], "image.png")
        self.assertEqual(out["profile"], "flux-edit-balanced")
        self.assertEqual(out["identity"], "img2img")
        self.assertEqual(calls["profile"], "flux-edit-balanced")
        self.assertEqual(calls["ctl"]["steps"], 4)
        self.assertTrue(calls["image"].startswith("nm_bc_"))

    def test_run_refuses_an_empty_prompt_and_a_node_without_flux(self):
        m = load()

        class J:
            uid = "u" * 16
            payload = {"prompt": ""}

            def input_path(self, n):
                return None

        with self.assertRaises(RuntimeError):
            m.run(J(), SimpleNamespace(load_profiles=lambda: PROFILES))
        J.payload = {"prompt": "x"}
        with self.assertRaises(RuntimeError) as cm:
            m.run(J(), SimpleNamespace(load_profiles=lambda: []))
        self.assertIn("FLUX", str(cm.exception))

    def test_register_adds_the_handler_and_the_capability_once(self):
        m = load()
        probe_calls = []

        class Caps:
            def probe(self):
                probe_calls.append(1)
                return {"comfy_nodes": ["ApplyPulidFlux"], "agent": "2.27"}

        agent = SimpleNamespace(Capabilities=Caps, load_profiles=lambda: PROFILES)
        handlers = {}
        self.assertTrue(m.register(agent, handlers))
        self.assertTrue(m.register(agent, handlers))                    # دوباره صدا زدن چیزِ دوم نمی‌چسباند
        self.assertIn("brandchar.render", handlers)
        caps = Caps().probe()
        self.assertEqual(caps["brandchar"]["identity_tools"], ["pulid"])
        self.assertTrue(caps["brandchar"]["ready"])
        self.assertEqual(len(probe_calls), 1)

    def test_a_broken_probe_never_stops_the_heartbeat(self):
        m = load()

        class Caps:
            def probe(self):
                return {"comfy_nodes": None}

        agent = SimpleNamespace(Capabilities=Caps, load_profiles=lambda: (_ for _ in ()).throw(RuntimeError("profiles broken")))
        m.register(agent, {})
        caps = Caps().probe()
        self.assertIn("brandchar", caps)


class WiringFilesTests(SimpleTestCase):
    def test_agent_has_one_guarded_registration(self):
        src = (PROC / "agent.py").read_text(encoding="utf-8")
        self.assertEqual(src.count("brandchar_jobs.register("), 1)
        i = src.index("brandchar_jobs.register(")
        block = src[i - 400:i + 400]
        self.assertIn("try:", block)
        self.assertIn("except Exception", block)

    def test_requirements_file_is_valid_and_gates_the_kind(self):
        spec = json.loads((PROC / "requirements.d" / "brandchar.json").read_text(encoding="utf-8"))
        self.assertEqual(spec["feature"], "brandchar")
        self.assertEqual(spec["kinds"], ["brandchar.render"])
        self.assertTrue(spec["needs_gpu"])
        self.assertTrue(all(i["type"] in ("cmd", "files", "pip", "venv", "archive") for i in spec["items"]))
        item = spec["items"][0]
        self.assertIn("brandchar_jobs.py", " ".join(item["check"]))

    def test_check_command_fails_without_profiles_or_checkpoint(self):
        m = load()
        self.assertIn(m.check(), (0, 1, 2))

    def test_the_site_side_routing_knows_the_kind(self):
        from apps.compute import models as CM

        self.assertEqual(CM.capability_for("brandchar.render"), "comfyui")
        self.assertEqual(CM.capability_for("brandchar.anything"), "comfyui")

    def test_selftests_are_registered_with_agent_and_feature_gates(self):
        from apps.compute import selftests as ST

        ST.load_all(force=True)
        eng, ren = ST.REGISTRY["brandchar_engine"], ST.REGISTRY["brandchar_render"]
        self.assertIsNotNone(eng.virtual)
        self.assertEqual(ren.kind, "brandchar.render")
        self.assertTrue(ren.optional)
        self.assertIn("brandchar", ren.needs_features)
        old = SimpleNamespace(capabilities={"comfyui": True, "agent": "2.26", "kinds": ["comfy.profile"]}, has=lambda c: True)
        ok, why = ren.available(old)
        self.assertFalse(ok)
        self.assertIn("به‌روزرسانی", why)                                   # عاملِ قدیمی: «منتظرِ به‌روزرسانی»، نه رد
        self.assertFalse(ren.available(SimpleNamespace(capabilities={"comfyui": True}, has=lambda c: True))[0])
        new = SimpleNamespace(capabilities={"comfyui": True, "kinds": ["brandchar.render"], "brandchar": {"ready": True}}, has=lambda c: True)
        self.assertEqual(ren.available(new), (True, ""))
        noflux = SimpleNamespace(capabilities={"comfyui": True, "kinds": ["brandchar.render"], "brandchar": {"ready": False}}, has=lambda c: True)
        self.assertFalse(ren.available(noflux)[0])
        spec = ren.build(SimpleNamespace(node=None))
        self.assertEqual(spec.kind, "brandchar.render")
        self.assertIn("reference.png", spec.files)
        v = eng.virtual(SimpleNamespace())
        self.assertTrue(v.ok, v.detail)
