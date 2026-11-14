# -*- coding: utf-8 -*-
"""فهرستِ آزمون‌های پذیرشِ سرورِ پردازش (۱۴۰۵/۰۸/۲۳): هر ویژگی یک آزمون دارد، هر آزمون کاری می‌فرستد که عاملِ فرستاده‌شده واقعاً می‌شناسد،
هر نصبِ خودکاری که آزمونی به آن تکیه دارد وجود دارد، و بلوک‌های docs/selftests/*.md همه بار می‌شوند.

اگر ویژگیِ تازه‌ای آزمونش را فراموش کند یا یک `kind` را غلط بنویسد، این‌جا قرمز می‌شود — نه صبحی که مالک گره را روشن می‌کند."""
import json
import os
import subprocess
import sys
import tempfile
import types
from pathlib import Path

from django.conf import settings
from django.test import TestCase, override_settings
from django.utils import timezone

from . import commands as C
from .models import ComputeNode
from .readiness import REQUIRED                     # the same list the readiness report uses
from .selftests import REGISTRY, Spec, docs_loader, load_all, tests as catalog_tests

PROC = Path(settings.BASE_DIR).parent / "processing"


def agent_kinds() -> list[str]:
    """The job kinds the SHIPPED agent registers (a real import of processing/agent.py in a clean interpreter, optional modules included)."""
    tmp = tempfile.mkdtemp(prefix="nm-catalog-agent-")
    env = dict(os.environ, NM_DATA=tmp, NM_DATA_POINTER=os.path.join(tmp, "pointer.txt"), NM_NO_MIGRATE="1", PYTHONIOENCODING="utf-8")
    code = "import json, sys; sys.path.insert(0, '.'); import agent; print('KINDS=' + json.dumps(sorted(agent.HANDLERS)))"
    out = subprocess.run([sys.executable, "-c", code], cwd=str(PROC), env=env, capture_output=True, text=True, timeout=180, encoding="utf-8")
    for line in reversed(out.stdout.splitlines()):
        if line.startswith("KINDS="):
            return json.loads(line[6:])
    raise AssertionError("the agent could not be imported: %s" % (out.stderr or out.stdout)[-600:])


def requirement_features() -> dict:
    out = {}
    for path in sorted((PROC / "requirements.d").glob("*.json")):
        spec = json.loads(path.read_text(encoding="utf-8"))
        out[spec["feature"]] = spec
    return out


def full_caps(kinds) -> dict:
    """What a completely equipped node reports (everything on, everything installed)."""
    from .tests_platform import models_caps

    return {"agent": "9.99", "kinds": list(kinds), "commands": list(C.ACTIONS), "code": {"version": "9.99", "id": "z" * 16}, "started_at": 1000,
            "comfyui": True, "photo": True, "video": True, "voice": True, "ollama": True, "ffmpeg": True, "gpu": "RTX 3060, 12288 MiB",
            "ollama_models": ["qwen3:8b", "qwen3-vl:30b"], "photo_matting": True, "matting_runtime": {"ok": True, "gpu": True},
            "matting_models": {"u2netp": {"state": "installed"}}, "audio": {"moss": True, "sfx": True, "music": True},
            "edit": {"render": True, "nvenc": {"h264": True}, "matte": True}, "comfy_profiles": ["flux-product-fast", "wan22-480p-short"],
            "comfy_models": {"checkpoints": ["FLUX.1 [dev] FP8.safetensors"]}, "blender": True, "motion_render": True,
            "motion": {"state": "ready"}, "multiangle": True, "instagram": True, "models": models_caps(),
            "bootstrap": {"summary": {"ready": 5}, "blocked_kinds": {}, "features": {}}}


class CatalogTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        load_all()
        cls.kinds = agent_kinds()

    def test_every_feature_of_the_brief_has_an_acceptance_test(self):
        missing = {feature: keys for feature, keys in REQUIRED.items() if not all(k in REGISTRY for k in keys)}
        self.assertEqual(missing, {}, "features without their acceptance test: %s" % missing)

    def test_keys_are_unique_short_and_in_a_known_group(self):
        groups = {"system", "gpu", "text", "image", "audio", "video"}
        for key, t in REGISTRY.items():
            self.assertEqual(key, t.key)
            self.assertRegex(key, r"^[a-z0-9_]{2,40}$")
            self.assertIn(t.group, groups, "%s: unknown group %r" % (key, t.group))
            self.assertTrue(t.label.strip(), "%s has no label" % key)

    def test_every_real_test_sends_a_kind_the_shipped_agent_serves(self):
        bad = {k: t.kind for k, t in REGISTRY.items() if t.kind and t.kind not in self.kinds}
        self.assertEqual(bad, {}, "tests whose kind no handler of the shipped agent answers: %s (agent kinds: %s)" % (bad, self.kinds))

    def test_the_agent_kinds_every_feature_added_are_all_there(self):
        for kind in ("echo", "comfy.graph", "comfy.profile", "photo.edit", "photo.matting", "voice.tts", "edit.render", "asr.transcribe", "selftest.gpu",
                     "multiangle.selftest", "up3d.render", "motion.render", "ig.health", "ig.scrape", "node.models", "ollama.generate"):
            self.assertIn(kind, self.kinds, kind)

    def test_what_a_test_waits_for_exists_in_requirements_d(self):
        feats = requirement_features()
        for key, t in REGISTRY.items():
            for f in t.needs_features:
                self.assertIn(f, feats, "%s waits for the install «%s» which no requirements.d file declares" % (key, f))

    def test_every_install_that_holds_back_a_kind_has_a_test_for_that_kind(self):
        tested = {t.kind for t in REGISTRY.values() if t.kind}
        for name, spec in requirement_features().items():
            for kind in spec.get("kinds") or []:
                self.assertIn(kind, tested, "requirements.d/%s holds jobs of kind %s but no acceptance test sends one" % (name, kind))
                self.assertIn(kind, self.kinds, "requirements.d/%s names kind %s, which the agent does not serve" % (name, kind))

    def test_every_min_agent_is_a_version_that_exists(self):
        from .selftests import version_tuple

        have = ""
        for line in (PROC / "agent.py").read_text(encoding="utf-8").splitlines():
            if line.startswith("VERSION = "):
                have = line.split('"')[1]
        for key, t in REGISTRY.items():
            if t.min_agent:
                self.assertLessEqual(version_tuple(t.min_agent), version_tuple(have), "%s needs agent %s but the package is %s" % (key, t.min_agent, have))

    def test_every_block_of_docs_selftests_loads_and_its_key_is_in_the_catalog(self):
        seen = 0
        for path in sorted(docs_loader.docs_dir().glob("*.md")):
            if path.name.lower() == "readme.md":
                continue
            for raw in docs_loader.BLOCK_RE.findall(path.read_text(encoding="utf-8")):
                data = json.loads(raw)                                     # a broken block must be loud HERE, the loader hides it
                for obj in data if isinstance(data, list) else [data]:
                    t = docs_loader.from_block(obj)
                    self.assertIn(t.key, REGISTRY, "%s: the test %s was not registered" % (path.name, t.key))
                    seen += 1
        self.assertGreater(seen, 0)

    def test_every_test_of_a_fully_equipped_node_can_be_built_and_names_a_served_kind(self):
        node = ComputeNode.objects.create(name="all-caps", capabilities=full_caps(self.kinds), last_seen=timezone.now())
        from .selftests import Ctx

        built = skipped = 0
        for t in catalog_tests(deep=True):
            ok, why = t.available(node)
            if not ok:
                skipped += 1
                continue
            if t.build is None:
                continue
            ctx = Ctx(node, None, results={}, result=types.SimpleNamespace(extra={}))
            try:
                spec = t.build(ctx)
            except Exception:  # noqa: BLE001 — a test that builds on the output of another one (after=...) cannot be built alone
                self.assertTrue(t.after, "%s could not build its job on a fully equipped node" % t.key)
                continue
            if spec is None:
                continue
            self.assertIsInstance(spec, Spec, t.key)
            self.assertIn(spec.kind, self.kinds, "%s builds a %s job the agent does not serve" % (t.key, spec.kind))
            self.assertGreater(spec.timeout_s, 0)
            built += 1
        self.assertGreater(built, 15)

    def test_the_motion_test_is_a_real_three_second_persian_template_render(self):
        from apps.motion import selftest

        spec = selftest.PAYLOAD["props"]["spec"]
        self.assertEqual(selftest.PAYLOAD["mode"], "template")
        self.assertEqual([s["duration"] for s in spec["scenes"]], [3])
        self.assertEqual((spec["aspect"], spec["lang"], spec["fps"]), ("9:16", "fa", 30))
        self.assertEqual(selftest.EXPECT["frames"], 3 * spec["fps"])
        self.assertTrue(REGISTRY["motion_studio"].gpu_required)         # a card is required: a CPU render fails the test on purpose

    def test_the_catalog_api_lists_every_registered_test(self):
        from django.contrib.auth import get_user_model
        from rest_framework.test import APIClient

        with override_settings(NM_DATA_DIR=Path(tempfile.mkdtemp(prefix="nm-catalog-api-"))):
            admin = get_user_model().objects.create_user("catalog-admin", password="x", is_staff=True, is_superuser=True)
            client = APIClient()
            client.force_authenticate(admin)
            res = client.get("/api/v1/compute/selftests/")
        self.assertEqual(res.status_code, 200)
        keys = {row["key"] for row in res.json()["catalog"]}
        self.assertEqual(keys, set(REGISTRY))
        for feature, wanted in REQUIRED.items():
            self.assertTrue(set(wanted) <= keys, feature)
