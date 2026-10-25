"""سمتِ گره، بی GPU: همان کدِ agent.py (h_comfy_graph ⇐ comfy_upload/comfy_run) با گرافِ «بازسازیِ تکه» در برابرِ یک
ComfyUI ِ ساختگی که روی 127.0.0.1 گوش می‌دهد.

ComfyUI ِ ساختگی همان قراردادِ HTTP ِ واقعی را دارد (/upload/image، /prompt، /history/<id>، /view)، گراف را مثلِ
اعتبارسنجیِ ComfyUI وارسی می‌کند (نودِ ناشناخته، پیوندِ شکسته، تصویری که بالا نرفته، ورودیِ اجباریِ غایب) و برای
هر SaveImage به اندازهٔ length ِ همان تکه PNG می‌سازد (محوِ تدریجی از تصویرِ اول به آخر). بعد نام‌هایی که agent
پایین می‌آورد باید همان باشد که چسباندنِ سایت می‌خواند (c<i>_00001_.png …) و به همان تعدادِ فریمِ نقشه برسد.
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
from urllib.parse import parse_qs, urlparse

import numpy as np
from django.conf import settings
from django.test import SimpleTestCase
from PIL import Image

from services.video.regen import plan as planmod, stitch

#: ورودی‌های اجباریِ هر نود در ComfyUI v0.42.1 (comfy_extras/nodes_wan.py، nodes.py، nodes_images.py)
REQUIRED = {
    "LoadImage": {"image"},
    "ImageBatch": {"image1", "image2"},
    "ImageFromBatch": {"image", "batch_index", "length"},
    "UNETLoader": {"unet_name", "weight_dtype"},
    "LoraLoaderModelOnly": {"model", "lora_name", "strength_model"},
    "ModelSamplingSD3": {"model", "shift"},
    "CLIPLoader": {"clip_name", "type"},
    "VAELoader": {"vae_name"},
    "CLIPVisionLoader": {"clip_name"},
    "CLIPVisionEncode": {"clip_vision", "image", "crop"},
    "CLIPTextEncode": {"clip", "text"},
    "WanFirstLastFrameToVideo": {"positive", "negative", "vae", "width", "height", "length", "batch_size"},
    "WanFunInpaintToVideo": {"positive", "negative", "vae", "width", "height", "length", "batch_size"},
    "KSamplerAdvanced": {"model", "add_noise", "noise_seed", "steps", "cfg", "sampler_name", "scheduler", "positive",
                         "negative", "latent_image", "start_at_step", "end_at_step", "return_with_leftover_noise"},
    "KSampler": {"model", "seed", "steps", "cfg", "sampler_name", "scheduler", "positive", "negative",
                 "latent_image", "denoise"},
    "VAEDecode": {"samples", "vae"},
    "SaveImage": {"images", "filename_prefix"},
}
OUTPUTS = {"WanFirstLastFrameToVideo": 3, "WanFunInpaintToVideo": 3, "LoadImage": 2}


def _agent_module():
    root = Path(settings.BASE_DIR).parent
    for cand in (root / "processing" / "agent.py", root / "processing-server" / "agent.py"):
        if cand.is_file():
            spec = importlib.util.spec_from_file_location("nm_agent_under_test", cand)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod
    raise SkipTest("processing/agent.py is not next to backend/")


class FakeComfy:
    def __init__(self):
        self.uploads: dict[str, bytes] = {}
        self.files: dict[tuple, bytes] = {}
        self.history: dict[str, dict] = {}
        self.errors: list[str] = []
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, body, ctype="application/json"):
                data = json.dumps(body).encode() if not isinstance(body, bytes) else body
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                u = urlparse(self.path)
                if u.path.startswith("/history/"):
                    pid = u.path.rsplit("/", 1)[-1]
                    return self._send(200, {pid: fake.history[pid]} if pid in fake.history else {})
                if u.path == "/view":
                    q = {k: v[0] for k, v in parse_qs(u.query).items()}
                    key = (q.get("subfolder", ""), q["filename"])
                    return self._send(200, fake.files[key], "image/png") if key in fake.files else self._send(404, {})
                return self._send(200, {})

            def do_POST(self):
                body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                if self.path == "/upload/image":
                    boundary = self.headers["Content-Type"].split("boundary=")[1].encode()
                    for part in body.split(b"--" + boundary):
                        m = re.search(rb'name="image"; filename="([^"]+)"', part)
                        if m:
                            data = part.split(b"\r\n\r\n", 1)[1].rsplit(b"\r\n", 1)[0]
                            fake.uploads[m.group(1).decode()] = data
                            return self._send(200, {"name": m.group(1).decode()})
                    return self._send(400, {"error": "no image"})
                if self.path == "/prompt":
                    graph = json.loads(body)["prompt"]
                    errs = fake.validate(graph)
                    if errs:
                        fake.errors += errs
                        return self._send(400, {"error": "prompt invalid", "node_errors": errs})
                    pid = uuid.uuid4().hex
                    fake.history[pid] = fake.execute(graph)
                    return self._send(200, {"prompt_id": pid, "number": 1})
                return self._send(404, {})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def validate(self, graph) -> list:
        errs = []
        for nid, node in graph.items():
            cls = node.get("class_type")
            if cls not in REQUIRED:
                errs.append(f"{nid}: unknown node {cls}")
                continue
            missing = REQUIRED[cls] - set(node["inputs"])
            if missing:
                errs.append(f"{nid} {cls}: missing {sorted(missing)}")
            for name, value in node["inputs"].items():
                if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str):
                    src = graph.get(value[0])
                    if src is None:
                        errs.append(f"{nid}.{name}: link to missing node {value[0]}")
                    elif value[1] >= OUTPUTS.get(src["class_type"], 1):
                        errs.append(f"{nid}.{name}: output {value[1]} of {src['class_type']} does not exist")
            if cls == "LoadImage" and node["inputs"]["image"] not in self.uploads:
                errs.append(f"{nid}: image {node['inputs']['image']} was not uploaded")
            if cls == "ImageFromBatch" and node["inputs"]["batch_index"] < 0:
                errs.append(f"{nid}: negative batch_index (older ComfyUI rejects it)")
        return errs

    def _first_image(self, graph, ref):
        node = graph[ref[0]]
        while node["class_type"] != "LoadImage":
            key = "image1" if node["class_type"] == "ImageBatch" else "image"
            if key not in node["inputs"]:
                return None
            node = graph[node["inputs"][key][0]]
        return np.asarray(Image.open(io.BytesIO(self.uploads[node["inputs"]["image"]])).convert("RGB"), np.float32)

    def execute(self, graph) -> dict:
        outputs = {}
        for nid, node in graph.items():
            if node["class_type"] != "SaveImage":
                continue
            dec = graph[node["inputs"]["images"][0]]
            lat = graph[dec["inputs"]["samples"][0]]
            while lat["class_type"] in ("KSamplerAdvanced", "KSampler") and \
                    graph[lat["inputs"]["latent_image"][0]]["class_type"] in ("KSamplerAdvanced", "KSampler"):
                lat = graph[lat["inputs"]["latent_image"][0]]
            cond = graph[lat["inputs"]["latent_image"][0]]
            n, w, h = cond["inputs"]["length"], cond["inputs"]["width"], cond["inputs"]["height"]
            a = self._first_image(graph, cond["inputs"]["start_image"]) if "start_image" in cond["inputs"] and \
                graph[cond["inputs"]["start_image"][0]]["class_type"] != "ImageFromBatch" else None
            b = self._first_image(graph, cond["inputs"]["end_image"]) if "end_image" in cond["inputs"] else None
            a = a if a is not None else (b if b is not None else np.full((h, w, 3), 128, np.float32))
            b = b if b is not None else a
            sub, base = node["inputs"]["filename_prefix"].rsplit("/", 1)
            items = []
            for k in range(n):
                t = k / max(1, n - 1)
                img = Image.fromarray(np.clip((1 - t) * a + t * b, 0, 255).astype(np.uint8)).resize((w, h))
                buf = io.BytesIO()
                img.save(buf, "PNG")
                name = f"{base}_{k + 1:05d}_.png"
                self.files[(sub, name)] = buf.getvalue()
                items.append({"filename": name, "subfolder": sub, "type": "output"})
            outputs[nid] = {"images": items}
        return {"status": {"status_str": "success", "completed": True, "messages": []}, "outputs": outputs}

    def close(self):
        self.server.shutdown()


class FakeJob:
    def __init__(self, payload, inputs: dict):
        self.uid = uuid.uuid4().hex
        self.payload = payload
        self.timeout_s = 120
        self.cancelled = False
        self.dir = Path(tempfile.mkdtemp(prefix="nmregen-node-"))
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


def _info(n=600, fps=30.0, w=1280, h=720):
    return {"n_frames": n, "fps": fps, "fps_num": int(fps), "fps_den": 1, "width": w, "height": h,
            "time_base": "1/15360", "format_start": 0.0, "video_start": 0.0,
            "frame_pts": [i * 512 for i in range(n)]}


class AgentWithFakeComfyTests(SimpleTestCase):
    def setUp(self):
        self.agent = _agent_module()
        self.comfy = FakeComfy()
        os.environ["NM_COMFYUI_URL"] = self.comfy.url
        self.tmp = Path(tempfile.mkdtemp(prefix="nmregen-node-in-"))

    def tearDown(self):
        self.comfy.close()
        os.environ.pop("NM_COMFYUI_URL", None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self, plan, context_names):
        files = {}
        for name in context_names:
            path = self.tmp / name
            Image.fromarray(np.full((plan["gen_size"][1], plan["gen_size"][0], 3),
                                    40 if "_s" in name else 220, np.uint8)).save(path)
            files[name] = str(path)
        s = [n for n in context_names if "_s" in n]
        e = [n for n in context_names if "_e" in n]
        graph = planmod.build_graph(plan, prompt="a red ball rolls", seed=3, start_names=s, end_names=e,
                                    prefix="nmregen/test")
        job = FakeJob({"graph": graph, "uploads": sorted(files)}, files)
        meta = self.agent.h_comfy_graph(job)
        self.assertEqual(self.comfy.errors, [])
        names = sorted(os.listdir(job.outputs))
        by_chunk: dict[int, list] = {}
        for name in names:
            m = re.match(r"c(\d+)_\d+_?\.png$", name)       # the same pattern stitch_version reads
            self.assertIsNotNone(m, name)
            by_chunk.setdefault(int(m.group(1)), []).append(Path(job.outputs) / name)
        frames = stitch.gen_index_files(plan, by_chunk)      # raises if anything is missing
        self.assertEqual(sorted(frames), list(range(plan["G"] + 1)))
        shutil.rmtree(job.dir, ignore_errors=True)
        return meta, names

    def test_single_flf_chunk(self):
        plan = planmod.make_plan(_info(), 200, 259)
        meta, names = self._run(plan, ["nmregen_t_s0.png", "nmregen_t_e0.png"])
        self.assertEqual(meta["engine"], "comfyui")
        self.assertEqual(len(names), plan["chunks"][0]["length"])

    def test_chained_chunks_with_motion_context(self):
        plan = planmod.make_plan(_info(), 100, 459, context=5)       # ۱۲ ثانیه ⇐ چند تکه
        self.assertGreater(len(plan["chunks"]), 1)
        names = [f"nmregen_t_s{i}.png" for i in range(5)] + [f"nmregen_t_e{i}.png" for i in range(5)]
        _meta, out = self._run(plan, names)
        self.assertEqual(len(out), sum(c["length"] for c in plan["chunks"]))

    def test_fun_inp_engine(self):
        plan = planmod.make_plan(_info(), 0, 40, engine="fun_inp_13b")   # از اولِ ویدیو: فقط فریمِ انتها
        self._run(plan, ["nmregen_t_e0.png"])
