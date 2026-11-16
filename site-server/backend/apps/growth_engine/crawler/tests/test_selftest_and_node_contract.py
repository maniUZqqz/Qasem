"""The finder's entry in the node acceptance run, and the contract between the site and the node (kinds, capability, install list)."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from django.conf import settings
from django.test import TestCase

from apps.compute.models import ComputeNode, capability_for
from apps.compute.selftests import REGISTRY, load_all


class SelfTestRegistrationTests(TestCase):
    def setUp(self):
        load_all()
        self.t = REGISTRY["crawler"]

    def test_registered_with_the_right_kind_and_install_dependency(self):
        self.assertEqual(self.t.kind, "crawl.selftest")
        self.assertIn("crawl", self.t.needs_features)
        self.assertEqual(self.t.requeue["kinds"], ("crawl.run", "crawl.render"))
        spec = self.t.build(SimpleNamespace())
        self.assertEqual(spec.kind, "crawl.selftest")
        self.assertEqual(spec.payload, {"selftest": True})

    def test_the_render_kind_has_its_own_acceptance_entry(self):
        t = REGISTRY["crawler_render"]
        self.assertEqual(t.kind, "crawl.render")
        self.assertEqual(t.build(SimpleNamespace()).payload, {"selftest": True})
        self.assertIn("crawl", t.needs_features)

    def test_not_run_on_an_old_agent_but_run_once_the_node_advertises_it(self):
        old = ComputeNode(name="old", capabilities={"kinds": ["echo"], "agent": "2.10"})
        ok, why = self.t.available(old)
        self.assertFalse(ok)
        self.assertIn("به‌روزرسانی", why)
        new = ComputeNode(name="new", capabilities={"kinds": ["echo", "crawl.selftest"], "crawl": True, "agent": "2.30"})
        self.assertTrue(self.t.available(new)[0])

    def verdict(self, report):
        ctx = SimpleNamespace(read_json=lambda job, name: report)
        return self.t.check(ctx, None)

    def test_verdicts(self):
        good = {"ok": True, "checks": [{"name": "static_site", "ok": True, "detail": ""}, {"name": "javascript_site_rendered", "ok": True, "detail": ""}]}
        self.assertTrue(self.verdict(good).ok)
        no_browser = {"ok": False, "checks": [{"name": "browser_ready", "ok": False, "detail": "no_browser"}, {"name": "javascript_site_rendered", "ok": False, "detail": ""}]}
        v = self.verdict(no_browser)
        self.assertFalse(v.ok)
        self.assertTrue(v.wait)  # the browser is still being installed: wait, do not fail
        broken = {"ok": False, "checks": [{"name": "static_site", "ok": False, "detail": "0 page(s)"}]}
        v = self.verdict(broken)
        self.assertFalse(v.ok)
        self.assertFalse(v.wait)
        self.assertFalse(self.verdict(None).ok)


class NodeContractTests(TestCase):
    def test_the_site_routes_crawl_kinds_only_to_nodes_that_advertise_the_capability(self):
        for kind in ("crawl.run", "crawl.render", "crawl.selftest"):
            self.assertEqual(capability_for(kind), "crawl")
        node_without = ComputeNode(name="a", capabilities={"photo": True})
        node_with = ComputeNode(name="b", capabilities={"crawl": True})
        self.assertFalse(node_without.has("crawl"))
        self.assertTrue(node_with.has("crawl"))
        from apps.compute import services as SV

        self.assertIn("crawl", SV.CAPABILITY_PREFIXES)

    def test_the_node_files_are_in_the_live_processing_folder_the_nodes_update_from(self):
        root = Path(settings.BASE_DIR).parent / "processing"
        self.assertTrue((root / "crawl_jobs.py").is_file())
        spec = json.loads((root / "requirements.d" / "crawl.json").read_text(encoding="utf-8"))
        self.assertEqual(spec["feature"], "crawl")
        agent = (root / "agent.py").read_text(encoding="utf-8")
        self.assertIn("import crawl_jobs", agent)
        self.assertIn("crawl_jobs.register(HANDLERS", agent)
        self.assertIn("except Exception", agent[agent.index("import crawl_jobs"):agent.index("import crawl_jobs") + 400])  # one guarded line: a broken optional module never stops the agent
