"""سمتِ گره، بی GPU و بی .NET: همان کدِ agent.py (h_photo_edit، h_photo_analyze، photo_ai_env) در برابرِ یک
PersianAiKit.Photo.Server ِ ساختگی روی 127.0.0.1 با همان قراردادِ HTTP ِ واقعی (Program.cs):

    POST /api/edit?auto=1  (multipart: file، recipe)   ⇐ عکس + سرآیندِ X-Recipe (نسخهٔ واقعاً به‌کاررفته، URL-encoded)
    POST /api/analyze      (multipart: file)           ⇐ {stats, text, auto: {recipe, notes}}
    POST /api/docs         (multipart: file)           ⇐ {id, name, width, height, …}
    POST /api/docs/{id}/ai-edit  {goal, recipe}         ⇐ {recipe, notes, usedAi, error, steps}
    POST /api/docs/{id}/export   recipe                 ⇐ عکس
    DELETE /api/docs/{id}

و یک دورِ کامل: سایت کار را در صف می‌گذارد ⇐ «گره» با agent.py و سرورِ ساختگی انجامش می‌دهد ⇐ خروجی به سایت ⇐
مرحلهٔ سرورِ سایت ⇐ نسخهٔ آماده.
"""
import importlib.util
import io
import json
import os
import re
import shutil
import tempfile
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import SkipTest
from urllib.parse import parse_qs, quote, urlparse

from django.conf import settings
from django.test import SimpleTestCase
from django.utils import timezone
from PIL import Image

from apps.compute import services as compute
from apps.compute.models import ComputeJob, ComputeNode

from .models import PhotoEdit
from .tests import ApiTestBase, photo


def _agent_module():
    root = Path(settings.BASE_DIR).parent
    for cand in (root / "processing" / "agent.py", root / "processing-server" / "agent.py"):
        if cand.is_file():
            spec = importlib.util.spec_from_file_location("nm_agent_photo_test", cand)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod
    raise SkipTest("processing/agent.py is not next to backend/")


def _multipart(body: bytes, ctype: str) -> dict:
    boundary = re.search(r"boundary=([^;]+)", ctype).group(1).strip('"').encode()
    out = {}
    for part in body.split(b"--" + boundary):
        if b"\r\n\r\n" not in part:
            continue
        head, data = part.split(b"\r\n\r\n", 1)
        m = re.search(rb'name="([^"]+)"(?:; filename="([^"]*)")?', head)
        if m:
            out[m.group(1).decode()] = (m.group(2).decode() if m.group(2) else None, data[:-2] if data.endswith(b"\r\n") else data)
    return out


class FakePhotoKit:
    """PersianAiKit.Photo.Server ِ ساختگی: «ویرایش» = روشن‌تر کردن به اندازهٔ exposure؛ شفاف ⇐ PNG."""

    def __init__(self, *, ai_configured=True):
        self.calls: list[tuple[str, str]] = []
        self.recipes: list[dict] = []
        self.goals: list[str] = []
        self.docs: dict[str, bytes] = {}
        self.ai_configured = ai_configured
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, body, ctype="application/json; charset=utf-8", headers=None):
                data = json.dumps(body, ensure_ascii=False).encode() if not isinstance(body, bytes) else body
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _body(self):
                return self.rfile.read(int(self.headers.get("Content-Length") or 0))

            def do_POST(self):
                u = urlparse(self.path)
                fake.calls.append(("POST", u.path))
                body = self._body()
                if u.path in ("/api/edit", "/api/analyze", "/api/docs"):
                    form = _multipart(body, self.headers["Content-Type"])
                    if "file" not in form:
                        return self._send(400, {"error": "فایلِ عکس نیامده (فیلدِ file)."})
                    img = form["file"][1]
                    if u.path == "/api/analyze":
                        return self._send(200, {"stats": {"exposure": -0.6}, "text": "عکس تیره است.",
                                                "auto": {"recipe": {"adjust": {"exposure": 0.6}}, "notes": ["نوردهی +۰٫۶"]}})
                    if u.path == "/api/docs":
                        did = "261027-" + uuid.uuid4().hex[:6]
                        fake.docs[did] = img
                        return self._send(200, {"id": did, "name": "nm", "width": 10, "height": 10})
                    recipe = json.loads(form["recipe"][1].decode()) if "recipe" in form else {}
                    auto = parse_qs(u.query).get("auto") == ["1"]
                    if auto:
                        recipe = {"adjust": {"exposure": 0.3, "vibrance": 12}} | recipe
                    fake.recipes.append(recipe)
                    data, ctype = fake.render(img, recipe)
                    return self._send(200, data, ctype, {"X-Recipe": quote(json.dumps(recipe))})
                m = re.match(r"^/api/docs/([\w-]+)/(ai-edit|export)$", u.path)
                if not m or m.group(1) not in fake.docs:
                    return self._send(404, {"error": "عکس پیدا نشد."})
                req = json.loads(body.decode() or "{}")
                if m.group(2) == "ai-edit":
                    fake.goals.append(req.get("goal"))
                    if not fake.ai_configured:
                        return self._send(200, {"recipe": {"adjust": {"exposure": 0.2}} | (req.get("recipe") or {}),
                                                "notes": "هوشِ مصنوعی تنظیم نشده — تنظیمِ خودکارِ رایگان اعمال شد",
                                                "usedAi": False, "error": "کلیدِ API تنظیم نشده", "steps": []})
                    # the «model» also proposes a crop and a background; the agent must drop what the site did not ask
                    rec = {"adjust": {"temperature": 18, "exposure": 0.25}, "crop": {"x": 0.1, "y": 0.1, "w": 0.5, "h": 0.5},
                           "background": {"remove": True, "color": "#000000"}} | {
                        k: v for k, v in (req.get("recipe") or {}).items() if k == "output"}
                    return self._send(200, {"recipe": rec, "notes": "گرم‌تر و روشن‌تر شد.", "usedAi": True,
                                            "steps": [{"round": 1, "model": "qwen3-vl:30b", "done": True}]})
                fake.recipes.append(req)
                data, ctype = fake.render(fake.docs[m.group(1)], req)
                return self._send(200, data, ctype)

            def do_DELETE(self):
                u = urlparse(self.path)
                fake.calls.append(("DELETE", u.path))
                did = u.path.rsplit("/", 1)[-1]
                fake.docs.pop(did, None)
                return self._send(200, {"ok": True})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = "http://127.0.0.1:%d" % self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    @staticmethod
    def render(img_bytes: bytes, recipe: dict) -> tuple[bytes, str]:
        im = Image.open(io.BytesIO(img_bytes)).convert("RGB")
        lift = int(120 * float((recipe.get("adjust") or {}).get("exposure", 0)))
        im = Image.eval(im, lambda v: max(0, min(255, v + lift)))
        transparent = (recipe.get("background") or {}).get("color") == "transparent"
        buf = io.BytesIO()
        if transparent:
            im.convert("RGBA").save(buf, "PNG")
            return buf.getvalue(), "image/png"
        fmt = ((recipe.get("output") or {}).get("format") or "jpeg").upper()
        im.save(buf, {"JPEG": "JPEG", "PNG": "PNG", "WEBP": "WEBP"}.get(fmt, "JPEG"))
        return buf.getvalue(), {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}.get(fmt, "image/jpeg")

    def close(self):
        self.server.shutdown()


class FakeOllama:
    def __init__(self, names):
        names_ = names

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                data = json.dumps({"models": [{"name": n} for n in names_]}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = "http://127.0.0.1:%d" % self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()


class FakeJob:
    """همان رابطی که agent.py به هر handler می‌دهد (Job: payload، input_path/bytes، out، progress)."""

    def __init__(self, payload, inputs: dict):
        self.uid = uuid.uuid4().hex
        self.payload = payload
        self.timeout_s = 120
        self.cancelled = False
        self.dir = Path(tempfile.mkdtemp(prefix="nmphoto-node-"))
        self.inputs = str(self.dir / "inputs")
        self.outputs = str(self.dir / "outputs")
        os.makedirs(self.inputs)
        for name, src in inputs.items():
            shutil.copyfile(src, os.path.join(self.inputs, name))
        self.reports = []

    def out(self, name):
        os.makedirs(self.outputs, exist_ok=True)
        return os.path.join(self.outputs, os.path.basename(name))

    def input_path(self, name):
        p = os.path.join(self.inputs, os.path.basename(name))
        return p if os.path.isfile(p) else None

    def input_bytes(self, name):
        return open(self.input_path(name), "rb").read()

    def progress(self, fraction, message=""):
        self.reports.append((fraction, message))


class AgentPhotoTests(SimpleTestCase):
    def setUp(self):
        self.agent = _agent_module()
        self.kit = FakePhotoKit()
        os.environ["NM_PHOTO_URL"] = self.kit.url
        self.tmp = Path(tempfile.mkdtemp(prefix="nmphoto-node-in-"))
        self.src = self.tmp / "photo-a1.jpg"
        photo(640, 480, dark=True).save(self.src, quality=90)

    def tearDown(self):
        self.kit.close()
        os.environ.pop("NM_PHOTO_URL", None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _job(self, payload):
        return FakeJob(dict(payload, image="photo-a1.jpg"), {"photo-a1.jpg": self.src})

    def test_recipe_edit_writes_photo_and_used_recipe(self):
        recipe = {"preset": "clean", "adjust": {"exposure": 0.5}, "output": {"format": "jpeg", "quality": 95, "upscale": 2}}
        job = self._job({"recipe": recipe, "auto": True})
        meta = self.agent.h_photo_edit(job)
        self.assertEqual(meta["engine"], "photo")
        self.assertEqual(self.kit.recipes[-1]["adjust"], {"exposure": 0.5}, "نسخهٔ سایت باید روی خودکار بنشیند")
        self.assertEqual(self.kit.recipes[-1]["output"]["upscale"], 2)
        out = Path(job.out(meta["primary"]))
        self.assertTrue(out.name.endswith("-edited.jpg"))
        self.assertEqual(Image.open(out).size, (640, 480))
        side = json.loads(Path(job.out("photo-edit.json")).read_text(encoding="utf-8"))
        self.assertTrue(side["auto"])
        self.assertEqual(side["recipe"]["adjust"], {"exposure": 0.5})   # X-Recipe ِ کیت (URL-decoded)
        shutil.rmtree(job.dir, ignore_errors=True)

    def test_transparent_result_gets_png_name(self):
        job = self._job({"recipe": {"background": {"remove": True, "color": "transparent"},
                                    "output": {"format": "jpeg"}}})
        meta = self.agent.h_photo_edit(job)
        self.assertTrue(meta["primary"].endswith(".png"), meta)
        self.assertEqual(Image.open(job.out(meta["primary"])).mode, "RGBA")
        shutil.rmtree(job.dir, ignore_errors=True)

    def test_smart_edit_goes_through_the_kit_library_and_cleans_up(self):
        recipe = {"output": {"format": "jpeg", "quality": 92, "upscale": 2}}
        job = self._job({"recipe": recipe, "goal": "گرم و روشن برای کافه"})
        meta = self.agent.h_photo_edit(job)
        self.assertTrue(meta.get("smart"))
        self.assertEqual(self.kit.goals, ["گرم و روشن برای کافه"])
        paths = [p for _m, p in self.kit.calls]
        self.assertEqual(paths[0], "/api/docs")
        self.assertTrue(paths[1].endswith("/ai-edit") and paths[2].endswith("/export"))
        self.assertEqual(self.kit.calls[-1][0], "DELETE")
        self.assertEqual(self.kit.docs, {}, "سندِ موقت روی گره ماند")
        exported = self.kit.recipes[-1]
        self.assertEqual(exported["adjust"]["temperature"], 18)
        self.assertNotIn("crop", exported, "برشِ پیشنهادیِ مدل نباید اعمال شود")
        self.assertNotIn("background", exported, "پس‌زمینه را سایت تعیین می‌کند")
        self.assertEqual(exported["output"]["upscale"], 2)
        side = json.loads(Path(job.out("photo-edit.json")).read_text(encoding="utf-8"))
        self.assertTrue(side["usedAi"])
        self.assertEqual(side["notes"], "گرم‌تر و روشن‌تر شد.")
        self.assertGreater(len(job.reports), 0)
        shutil.rmtree(job.dir, ignore_errors=True)

    def test_smart_edit_without_vision_model_says_so(self):
        self.kit.ai_configured = False
        job = self._job({"recipe": {}, "goal": "روشن"})
        meta = self.agent.h_photo_edit(job)
        side = json.loads(Path(job.out("photo-edit.json")).read_text(encoding="utf-8"))
        self.assertFalse(side["usedAi"])
        self.assertIn("خودکار", side["notes"])
        self.assertTrue(Path(job.out(meta["primary"])).is_file())
        shutil.rmtree(job.dir, ignore_errors=True)

    def test_analyze(self):
        job = self._job({})
        meta = self.agent.h_photo_analyze(job)
        data = json.loads(Path(job.out(meta["primary"])).read_text(encoding="utf-8"))
        self.assertEqual(data["text"], "عکس تیره است.")
        shutil.rmtree(job.dir, ignore_errors=True)

    def test_kit_unreachable_is_a_clear_error(self):
        os.environ["NM_PHOTO_URL"] = "http://127.0.0.1:9"
        job = self._job({"recipe": {}})
        try:
            with self.assertRaises(RuntimeError) as cm:
                self.agent.h_photo_edit(job)
            self.assertIn("not reachable", str(cm.exception))
        finally:
            shutil.rmtree(job.dir, ignore_errors=True)

    def test_photo_ai_env_points_the_kit_at_ollama_vision_models(self):
        oll = FakeOllama(["qwq:32b", "qwen3-vl:30b", "llava:7b", "nomic-embed-text"])
        os.environ["NM_OLLAMA_URL"] = oll.url
        try:
            env = self.agent.photo_ai_env({})
            self.assertEqual(env["Photo__Ai__BaseUrl"], oll.url + "/v1")
            self.assertEqual(env["Photo__Ai__Models"], "qwen3-vl:30b,llava:7b")
            self.assertEqual(self.agent.photo_ai_env({"NM_PHOTO_AI": "off"}), {})
            self.assertEqual(self.agent.photo_ai_env({"Photo__Ai__BaseUrl": "http://x/v1"}), {})
            self.assertEqual(self.agent.photo_ai_env({"NM_PHOTO_AI_MODELS": "gemma3:12b"})["Photo__Ai__Models"], "gemma3:12b")
        finally:
            oll.close()
            os.environ.pop("NM_OLLAMA_URL", None)
        os.environ["NM_OLLAMA_URL"] = "http://127.0.0.1:9"     # Ollama خاموش ⇐ فهرستِ پیش‌فرض
        try:
            self.assertIn("qwen3-vl:30b", self.agent.photo_ai_env({})["Photo__Ai__Models"])
        finally:
            os.environ.pop("NM_OLLAMA_URL", None)


class FullLoopTests(ApiTestBase):
    """سایت ⇐ صف ⇐ agent.py + کیتِ ساختگی ⇐ خروجی ⇐ مرحلهٔ سرورِ سایت ⇐ READY."""

    def setUp(self):
        super().setUp()
        self.agent = _agent_module()
        self.kit = FakePhotoKit()
        os.environ["NM_PHOTO_URL"] = self.kit.url

    def tearDown(self):
        self.kit.close()
        os.environ.pop("NM_PHOTO_URL", None)
        super().tearDown()

    def _run_node(self, job: ComputeJob, node: ComputeNode):
        """کاری که عاملِ گره می‌کند: گرفتن، اجرای handler روی ورودی‌ها، بالا فرستادنِ خروجی‌ها، پایان."""
        got = compute.claim(node)
        self.assertEqual(got.pk, job.pk)
        root = compute.job_root(job)
        fj = FakeJob(job.payload, {n: root / rel for n, rel in job.inputs.items()})
        meta = self.agent.HANDLERS[job.kind](fj)      # the same dispatch table the real agent uses
        for name in os.listdir(fj.outputs):
            with open(os.path.join(fj.outputs, name), "rb") as fh:
                compute.save_output(job, name, fh)
        compute.finish(job, node, True, meta=meta)
        shutil.rmtree(fj.dir, ignore_errors=True)

    def test_story_with_smart_edit_round_trip(self):
        ids = self.upload(photo(900, 900, dark=True))
        r = self.api.post(f"{self.base}/edits/", {"assets": ids, "recipe": "smart", "operations": [
            {"tool": "kit_smart", "params": {"goal": "روشن و گرم"}},
            {"tool": "crop_format", "params": {"format": "story", "fit": "contain", "fill": "blur"}},
            {"tool": "text", "params": {"text": "منوی پاییزه"}},
            {"tool": "export", "params": {"format": "jpeg", "quality": 88}}]}, format="json")
        e = PhotoEdit.objects.get(pk=r.json()["edits"][0]["id"])
        self.assertEqual(e.state, "NODE")
        node = ComputeNode.objects.create(name="DESKTOP-FAKE", last_seen=timezone.now(), capabilities={"photo": True})
        self._run_node(ComputeJob.objects.get(uid=e.compute_job), node)
        d = self.api.get(f"{self.base}/edits/{e.pk}/").json()["edit"]
        self.assertEqual(d["state"], "READY", d)
        self.assertTrue(d["kit"]["usedAi"])
        self.assertEqual(d["kit"]["notes"], "گرم‌تر و روشن‌تر شد.")
        self.assertEqual(d["node"], "DESKTOP-FAKE")
        e.refresh_from_db()
        with Image.open(self.media / e.files["result"]) as im:
            self.assertEqual(im.size, (1080, 1920))
            self.assertEqual(im.format, "JPEG")
        self.assertGreater(e.stats["after"]["p50"], e.asset.facts["p50"])
        self.assertEqual(self.kit.goals, ["روشن و گرم"])
