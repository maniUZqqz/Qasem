"""The public website must never send a visitor's browser to a loopback address.

Before the nm_trendsweb audit fix, `NEXT_PUBLIC_API_BASE=http://127.0.0.1:8040` was inlined into the contact form and the
analytics client: every visitor's browser posted to *its own* localhost and not one lead was ever stored. These tests pin
the pieces that keep it from coming back: the build guard (website/scripts/check-static-no-localhost.mjs), the browser-side
URL helper, and the install script.
"""
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
WEBSITE = ROOT / "website"
GUARD = WEBSITE / "scripts" / "check-static-no-localhost.mjs"
NODE = shutil.which("node")


@unittest.skipUnless(NODE and GUARD.exists(), "node or the website folder is not available here")
class BuildGuardTests(unittest.TestCase):
    def run_guard(self, files: dict[str, str]):
        with tempfile.TemporaryDirectory() as tmp:
            for name, text in files.items():
                path = Path(tmp) / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
            return subprocess.run([NODE, str(GUARD), tmp], capture_output=True, text=True, timeout=60)

    def test_a_clean_bundle_passes(self):
        done = self.run_guard({"chunks/a.js": 'fetch("/api/v1/leads/",{method:"POST"})', "b.css": "a{color:red}"})
        self.assertEqual(done.returncode, 0, done.stderr)

    def test_every_loopback_spelling_fails_the_build(self):
        for bad in ("http://127.0.0.1:8040", "http://localhost:8000", "https://localhost", "http://0.0.0.0:3001", "http://[::1]:8040"):
            done = self.run_guard({"chunks/contact.js": f'fetch("{bad}/api/v1/leads/")'})
            self.assertEqual(done.returncode, 1, f"{bad} was not caught")
            self.assertIn("contact.js", done.stderr)

    def test_a_missing_folder_is_an_error_not_a_pass(self):
        done = subprocess.run([NODE, str(GUARD), "/nonexistent-nm-static"], capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 2)


@unittest.skipUnless(WEBSITE.exists(), "the website folder is not available here")
class BrowserCodeTests(unittest.TestCase):
    def read(self, rel: str) -> str:
        return (WEBSITE / rel).read_text(encoding="utf-8")

    def code(self, rel: str) -> str:
        """The file without its comments (the explanations mention the address on purpose)."""
        text = re.sub(r"/\*.*?\*/", "", self.read(rel), flags=re.S)
        return re.sub(r"(?m)^\s*//.*$", "", text)

    def test_browser_code_has_no_loopback_default(self):
        for rel in ("components/ContactForm.tsx", "lib/track.ts", "lib/publicApi.ts"):
            text = self.code(rel)
            self.assertNotIn("127.0.0.1", text, rel)
            self.assertNotIn("localhost", text, rel)

    def test_the_contact_form_and_analytics_use_the_same_origin_helper(self):
        self.assertIn('publicApiUrl("/api/v1/leads/")', self.read("components/ContactForm.tsx"))
        self.assertIn('publicApiUrl("/api/v1/events/")', self.read("lib/track.ts"))

    def test_server_code_reads_the_internal_address(self):
        for rel in ("lib/api.ts", "lib/plans.ts", "lib/version.ts"):
            self.assertIn("internalApiBase", self.read(rel), rel)

    def test_the_build_runs_the_guard_after_every_build(self):
        self.assertIn("check-static-no-localhost.mjs", self.read("package.json"))
        install = (ROOT / "deploy" / "nm" / "install.sh")
        if install.exists():
            text = install.read_text(encoding="utf-8")
            self.assertIn("INTERNAL_API_BASE=http://127.0.0.1", text)
            self.assertIn("NEXT_PUBLIC_API_BASE=\n", text)
