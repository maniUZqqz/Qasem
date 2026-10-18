# -*- coding: utf-8 -*-
"""Test the REAL stack, one model at a time — for the machine that has the GPU.

`manage.py selftest` and `tools/e2e_api_test.py` both run against a fake
Ollama/ComfyUI on purpose: they prove the pipelines are wired correctly, on any
laptop, in a minute. What they cannot prove is that the real models load, that
they fit, that they hand the GPU over to each other, and how long all of that
takes. That is this file's whole job.

Written for a modest card — an RTX 3060 with 12 GB of VRAM next to 24 GB of
RAM — because that is the machine this product actually runs on:

  * ONE model at a time. Two text models, FLUX and Wan 2.2 cannot share 12 GB,
    so every stage ends by evicting what it loaded and WAITING until the card
    really is empty before the next stage starts. Without the wait the next
    model loads into whatever is left and either crawls or dies with an
    out-of-memory error that looks like a bug in the workflow.
  * Generous, separate timeouts per kind of work. A 32B model that is half on
    the CPU can take minutes just to load; that is normal here, not a failure.
  * Every stage reports how long the load took and how long the work took, and
    warns when the real number is close to the timeout THE PRODUCT ITSELF uses
    (OLLAMA_TIMEOUT / COMFYUI_TIMEOUT) — because a test that passes with a
    one-hour allowance says nothing about a product that gives up after 15 min.

It starts whatever is not running (Ollama, ComfyUI), and at the end stops only
what it started. It creates no store, no product and no job, and touches no
database row. The image and the clip it makes are kept next to the report so a
human can look at them.

The engines are probed with plain HTTP. The image and video stages go through
the project's OWN workflow files and ComfyUI client on purpose — "does our
FLUX/Wan graph run on this ComfyUI" is exactly the question.

    python tools/real_smoke.py                 everything, short clip (33 frames)
    python tools/real_smoke.py --full-video    the production length (81 frames)
    python tools/real_smoke.py --fast          no generation at all, just "is it there"

Exit code 0 when nothing FAILED (WARN and SKIP do not fail the run).
"""
import argparse
import base64
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
import urllib.error
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BACKEND = Path(__file__).resolve().parent.parent
ROOT = BACKEND.parent
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django  # noqa: E402

django.setup()

from django.conf import settings  # noqa: E402

AI = settings.UPMARKET_AI
RESULTS = []          # (status, name, detail)
ERRORS = []           # dicts: step, what, hint, technical
STARTED = []          # (label, Popen) — only what THIS script started
OUT = None            # Path, set in main()


# ===================================================================== reporting
def record(status, name, detail=""):
    RESULTS.append((status, name, detail))
    print("[%-4s] %-38s %s" % (status, name, detail), flush=True)


def fail(name, what, hint, exc=None):
    """A failure is written twice: one line in the summary, and the whole story
    — what happened, what to do about it, and the traceback — in ERRORS.txt."""
    record("FAIL", name, what[:150])
    ERRORS.append({
        "step": name, "what": what, "hint": hint,
        "technical": "".join(traceback.format_exception(exc)) if exc else "",
    })


def http(method, url, payload=None, timeout=30):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read()
    return json.loads(body) if body else {}


def listening(url, timeout=3):
    try:
        urllib.request.urlopen(url, timeout=timeout).read()
        return True
    except urllib.error.HTTPError:
        return True          # it answered, even if with an error page
    except Exception:  # noqa: BLE001
        return False


def near_limit(took, configured, what, env_name):
    """The product gives up after `configured` seconds. Say so when we got close."""
    if configured and took > 0.7 * configured:
        record("WARN", "%s is close to the product's own limit" % what,
               "took %.0fs, the product waits %ss — raise %s in backend/.env" % (took, configured, env_name))


# ===================================================================== GPU
def vram():
    exe = shutil.which("nvidia-smi")
    if not exe:
        return None
    try:
        out = subprocess.run([exe, "--query-gpu=memory.used,memory.total", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=20).stdout.strip().splitlines()[0]
        used, total = [int(x) for x in out.split(",")]
        return used, total
    except Exception:  # noqa: BLE001
        return None


def vram_note():
    v = vram()
    return "VRAM %d/%d MB" % v if v else "VRAM n/a"


def ollama_base():
    return AI["OLLAMA_BASE_URL"].rstrip("/")


def comfy_base():
    return AI["COMFYUI_BASE_URL"].rstrip("/")


def unload_ollama(wait=180):
    """Evict every Ollama model and WAIT until it is really gone."""
    base = ollama_base()
    try:
        loaded = [m["name"] for m in http("GET", base + "/api/ps", timeout=15).get("models", [])]
    except Exception:  # noqa: BLE001
        return
    for name in loaded:
        try:
            http("POST", base + "/api/generate", {"model": name, "keep_alive": 0}, timeout=60)
        except Exception:  # noqa: BLE001
            pass
    deadline = time.time() + wait
    while time.time() < deadline:
        try:
            if not http("GET", base + "/api/ps", timeout=15).get("models"):
                break
        except Exception:  # noqa: BLE001
            break
        time.sleep(3)


def free_comfyui():
    try:
        http("POST", comfy_base() + "/free", {"unload_models": True, "free_memory": True}, timeout=60)
    except Exception:  # noqa: BLE001
        pass


def settle(label, target_mb=2500, wait=120):
    """Give the driver time to actually return the memory, then say what is left.

    Evicting a model is a request, not an event: the VRAM comes back a few
    seconds later. Starting the next 12 GB model inside that window is how a
    machine that *can* run everything ends up out of memory.
    """
    deadline = time.time() + wait
    while time.time() < deadline:
        v = vram()
        if not v or v[0] <= target_mb:
            break
        time.sleep(4)
    print("       ... GPU handed over after %s: %s" % (label, vram_note()), flush=True)


def check_gpu():
    exe = shutil.which("nvidia-smi")
    if not exe:
        return record("WARN", "GPU (nvidia-smi)", "nvidia-smi not found — no NVIDIA GPU visible to this shell")
    try:
        out = subprocess.run([exe, "--query-gpu=name,memory.total,memory.used,driver_version",
                              "--format=csv,noheader"], capture_output=True, text=True, timeout=20).stdout.strip()
        record("PASS", "GPU (nvidia-smi)", out.replace("\n", " | "))
    except Exception as e:  # noqa: BLE001
        fail("GPU (nvidia-smi)", str(e), "درایور NVIDIA را بررسی کنید؛ nvidia-smi باید در خط فرمان اجرا شود.", e)


# ===================================================================== starting what is not running
def _spawn(label, cmd, cwd, env=None):
    log = open(OUT / ("svc-%s.log" % label), "w", encoding="utf-8", errors="replace")
    flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "CREATE_NO_WINDOW", 0)
    p = subprocess.Popen(cmd, cwd=str(cwd), env=env, stdin=subprocess.DEVNULL,
                         stdout=log, stderr=subprocess.STDOUT, creationflags=flags)
    STARTED.append((label, p))
    return p


def ensure_ollama(no_start):
    base = ollama_base()
    if listening(base + "/api/tags"):
        return record("PASS", "Ollama running", "%s (already up — its settings are whatever it was started with)" % base)
    if no_start:
        return fail("Ollama running", "nothing answers at %s" % base, "Ollama را روشن کنید یا بدون --no-start اجرا کنید.")
    exe = shutil.which("ollama")
    if not exe:
        return fail("Ollama running", "ollama is not installed / not on PATH",
                    "Ollama را از ollama.com نصب کنید، یا OLLAMA_BASE_URL را در backend/.env به سیستمی که دارد اشاره دهید.")
    env = dict(os.environ)
    # The same limits start.bat sets, and for the same reason: on a 12 GB card a
    # second resident model is 12 GB that FLUX and Wan cannot have.
    env.update({"OLLAMA_MAX_LOADED_MODELS": "1", "OLLAMA_NUM_PARALLEL": "1",
                "OLLAMA_KEEP_ALIVE": "30s", "OLLAMA_FLASH_ATTENTION": "1",
                "OLLAMA_KV_CACHE_TYPE": "q8_0", "OLLAMA_CONTEXT_LENGTH": "8192"})
    _spawn("ollama", [exe, "serve"], BACKEND, env)
    for _ in range(40):
        if listening(base + "/api/tags"):
            return record("PASS", "Ollama running", "started by this test (log: svc-ollama.log)")
        time.sleep(2)
    fail("Ollama running", "started `ollama serve` but it never answered at %s" % base,
         "logs/verify/svc-ollama.log را ببینید.")


COMFY_CANDIDATES = ["ComfyUI_windows_portable", "ComfyUI", os.path.join("Ai", "ComfyUI_windows_portable"),
                    os.path.join("AI", "ComfyUI_windows_portable")]


def find_comfyui(explicit):
    places = []
    for value in (explicit, os.getenv("COMFYUI_DIR")):
        if value:
            places.append(Path(value))
    for up in (ROOT.parent, ROOT.parent.parent, ROOT.parent.parent.parent, Path.home(), Path.home() / "Desktop"):
        places += [up / c for c in COMFY_CANDIDATES]
    for drive in "CDEFGH":
        places += [Path(drive + ":\\") / c for c in COMFY_CANDIDATES]
    for p in places:
        try:
            if (p / "run_nvidia_gpu.bat").exists() or (p / "main.py").exists():
                return p
        except OSError:
            continue
    return None


def ensure_comfyui(no_start, explicit_dir, boot_wait):
    base = comfy_base()
    if listening(base + "/system_stats"):
        return record("PASS", "ComfyUI running", "%s (already up)" % base)
    if no_start:
        return fail("ComfyUI running", "nothing answers at %s" % base, "ComfyUI را روشن کنید یا بدون --no-start اجرا کنید.")
    home = find_comfyui(explicit_dir)
    if not home:
        return fail("ComfyUI running", "ComfyUI is not running and its folder was not found",
                    "یکی از این سه: ComfyUI را خودتان روشن کنید و دوباره اجرا کنید؛ یا قبل از اجرا بنویسید "
                    "set COMFYUI_DIR=D:\\مسیر\\ComfyUI_windows_portable ؛ یا پوشه را کنار پروژه یا در ریشه‌ی یک درایو بگذارید.")
    bat = home / "run_nvidia_gpu.bat"
    if bat.exists():
        # The owner's own launcher, flags and all — if they tuned it for this
        # card (--lowvram and friends), those flags are part of what works.
        cmd = ["cmd", "/c", bat.name]
    else:
        cmd = [sys.executable, "main.py"]
    _spawn("comfyui", cmd, home)
    print("       ... waiting for ComfyUI to boot (custom nodes can take minutes) — %s" % home, flush=True)
    deadline = time.time() + boot_wait
    while time.time() < deadline:
        if listening(base + "/system_stats"):
            return record("PASS", "ComfyUI running", "started by this test from %s (log: svc-comfyui.log)" % home)
        time.sleep(5)
    fail("ComfyUI running", "started ComfyUI from %s but it did not answer within %ss" % (home, boot_wait),
         "logs/verify/svc-comfyui.log را ببینید — معمولاً یک custom node خطا داده یا پورت 8188 اشغال است.")


def stop_started():
    for label, p in STARTED:
        try:
            subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"], capture_output=True, timeout=30)
            print("       ... stopped %s (this test had started it)" % label, flush=True)
        except Exception:  # noqa: BLE001
            pass


# ===================================================================== text models
def installed_models():
    tags = http("GET", ollama_base() + "/api/tags", timeout=20)
    return {m["name"] for m in tags.get("models", [])}


def has_model(name, installed):
    return name in installed or (":" not in name and name + ":latest" in installed)


def test_image_b64():
    """A red square on white — small, unambiguous, and made right here."""
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (256, 256), "white")
    ImageDraw.Draw(img).rectangle([48, 48, 208, 208], fill=(220, 20, 30))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def run_text_model(role, model, timeout, with_image=False):
    name = "real generation: %s" % role
    payload = {"model": model, "stream": False, "keep_alive": "30s",
               "prompt": "Reply with exactly one word: OK", "options": {"num_predict": 96}}
    if with_image:
        payload["prompt"] = "What colour is the square in this image? Answer with one word."
        payload["images"] = [test_image_b64()]
    t0 = time.time()
    try:
        r = http("POST", ollama_base() + "/api/generate", payload, timeout=timeout)
    except Exception as e:  # noqa: BLE001
        took = time.time() - t0
        hint = ("مهلت %s ثانیه تمام شد. روی کارت ۱۲ گیگی مدل ۳۰ میلیاردی نیمی روی CPU می‌نشیند و کند است؛ "
                "با --timeout-text عدد بزرگ‌تری بدهید، یا مدل کوچک‌تری در backend/.env بگذارید." % timeout
                if took >= timeout - 5 else
                "logs/verify/svc-ollama.log را ببینید. اگر «model not found» است: ollama pull %s" % model)
        return fail(name, "%s — %s after %.0fs" % (model, str(e)[:90], took), hint, e)
    took = time.time() - t0
    if r.get("error"):
        return fail(name, "%s — %s" % (model, r["error"][:120]), "ollama pull %s" % model)
    load = (r.get("load_duration") or 0) / 1e9
    n, dur = r.get("eval_count") or 0, (r.get("eval_duration") or 0) / 1e9
    speed = (n / dur) if dur else 0
    answer = (r.get("response") or "").strip().replace("\n", " ")[:50]
    record("PASS", name, "%s — load %.0fs, %.1f tok/s, total %.0fs — %r — %s" % (
        model, load, speed, took, answer, vram_note()))
    near_limit(took, AI.get("OLLAMA_TIMEOUT"), "%s model" % role, "OLLAMA_TIMEOUT")
    if speed and speed < 2:
        record("WARN", "%s model is very slow here" % role,
               "%.1f tok/s — a long caption or analysis will take minutes; consider a smaller model" % speed)


def check_text_models(fast, timeout):
    try:
        installed = installed_models()
    except Exception as e:  # noqa: BLE001
        return fail("Ollama model list", str(e)[:120], "Ollama جواب نمی‌دهد.", e)
    record("PASS", "Ollama model list", "%d models installed" % len(installed))

    required = [("reasoning (analysis, writing, research)", AI.get("MODEL_REASONING"), False),
                ("vision (product photos)", AI.get("MODEL_VISION"), True)]
    optional = [("coder", AI.get("MODEL_CODER")), ("embedding", AI.get("MODEL_EMBEDDING"))]

    for role, model, with_image in required:
        if not model:
            continue
        if not has_model(model, installed):
            fail("model installed: %s" % role, "%s is not in `ollama list`" % model,
                 "ollama pull %s   — یا نام مدلی که دارید را در backend/.env بگذارید." % model)
            continue
        record("PASS", "model installed: %s" % role, model)
        if fast:
            record("SKIP", "real generation: %s" % role, "--fast")
            continue
        # One model at a time: nothing else may be resident while this one loads.
        free_comfyui()
        unload_ollama()
        settle("clearing the card for %s" % model)
        run_text_model(role, model, timeout, with_image=with_image)
        unload_ollama()
        settle("unloading %s" % model)

    for role, model in optional:
        if model and not has_model(model, installed):
            record("WARN", "model installed: %s" % role, "%s is not installed (optional)" % model)
        elif model:
            record("PASS", "model installed: %s" % role, model)

    emb = AI.get("MODEL_EMBEDDING")
    if emb and has_model(emb, installed) and not fast:
        try:
            r = http("POST", ollama_base() + "/api/embeddings", {"model": emb, "prompt": "کفش چرم مردانه"}, timeout=300)
            record("PASS" if r.get("embedding") else "FAIL", "real embedding", "%s — %d dims" % (emb, len(r.get("embedding") or [])))
        except Exception as e:  # noqa: BLE001
            fail("real embedding", str(e)[:120], "ollama pull %s" % emb, e)
        unload_ollama()


# ===================================================================== image + video, through the project's own workflows
def comfy_hint(exc):
    text = str(exc)
    if "out of memory" in text.lower() or "OOM" in text:
        return ("حافظه‌ی کارت کم آمد. run_nvidia_gpu.bat را با --lowvram اجرا کنید، و مطمئن شوید Ollama مدلی در "
                "VRAM نگه نداشته (OLLAMA_KEEP_ALIVE کوتاه).")
    if "not found" in text.lower() or "value_not_in_list" in text or "missing" in text.lower():
        return ("یک فایل مدل یا نود در ComfyUI نیست. خروجی «checkmodels» در همین گزارش دقیقاً می‌گوید کدام فایل؛ "
                "آن را در پوشه‌ی models مربوط بگذارید.")
    if "timed out" in text.lower() or "timeout" in text.lower():
        return "مهلت تمام شد؛ با --timeout-image / --timeout-video عدد بزرگ‌تری بدهید و svc-comfyui.log را ببینید."
    return "logs/verify/svc-comfyui.log را ببینید — خطای واقعی ComfyUI آنجاست."


def check_image_and_video(fast, t_image, t_video, full_video):
    if fast:
        record("SKIP", "real FLUX image", "--fast")
        return record("SKIP", "real Wan 2.2 clip", "--fast")
    if not listening(comfy_base() + "/system_stats"):
        record("SKIP", "real FLUX image", "ComfyUI is not running")
        return record("SKIP", "real Wan 2.2 clip", "ComfyUI is not running")

    from services.comfyui.client import ComfyUIClient
    from services.comfyui.workflows import load_workflow, patch_workflow

    artifacts = OUT / "artifacts"
    artifacts.mkdir(exist_ok=True)
    client = ComfyUIClient()

    # ---- FLUX. Ollama must be out of the card first.
    unload_ollama()
    free_comfyui()
    settle("clearing the card for FLUX")
    image_path = None
    t0 = time.time()
    try:
        graph, manifest = load_workflow("flux_txt2img")
        wf = patch_workflow(graph, manifest, seed=12345, filename_prefix="upm_verify_flux",
                            positive="a single red leather handbag on a plain white studio background, product photo",)
        image_path = client.generate(wf, artifacts, filename="flux-test.png", timeout=t_image)
        took = time.time() - t0
        record("PASS", "real FLUX image", "%.0fs — %d KB — %s — %s" % (
            took, image_path.stat().st_size // 1024, image_path.name, vram_note()))
        near_limit(took, AI.get("COMFYUI_TIMEOUT"), "FLUX image", "COMFYUI_TIMEOUT")
    except Exception as e:  # noqa: BLE001
        fail("real FLUX image", "%s after %.0fs" % (str(e)[:110], time.time() - t0), comfy_hint(e), e)

    # ---- Wan 2.2. FLUX must be out of the card first — they do not fit together.
    free_comfyui()
    settle("unloading FLUX")
    if image_path is None:
        return record("SKIP", "real Wan 2.2 clip", "needs the FLUX image as its first frame")
    t0 = time.time()
    try:
        from services.imaging.preprocess import prepare_source_image

        first_frame = prepare_source_image(image_path, artifacts / "wan-first-frame.png", 832, 480)
        server_name = client.upload_image(first_frame)
        graph, manifest = load_workflow("wan22_i2v")
        # 33 frames (~2 s) proves both UNETs load and swap; 81 is what production renders.
        length = 81 if full_video else 33
        wf = patch_workflow(graph, manifest, image=server_name, seed=12345, length=length,
                            filename_prefix="upm_verify_wan",
                            positive="the handbag slowly rotates on the white background, soft studio light")
        clip = client.generate(wf, artifacts, filename="wan-test.mp4", timeout=t_video)
        took = time.time() - t0
        record("PASS", "real Wan 2.2 clip", "%d frames in %.0fs (%.1f min) — %d KB — %s" % (
            length, took, took / 60, clip.stat().st_size // 1024, vram_note()))
        per_segment = took * (81 / length)
        print("       ... one production segment (81 frames) would take about %.1f min on this machine" % (per_segment / 60))
        near_limit(per_segment, AI.get("COMFYUI_TIMEOUT"), "one 5-second video segment", "COMFYUI_TIMEOUT")
        try:
            from services.video.ffmpeg import extract_last_frame

            last = extract_last_frame(clip, artifacts / "wan-last-frame.png")
            record("PASS", "last-frame extraction (continuity)", "%s — %d KB" % (last.name, last.stat().st_size // 1024))
        except Exception as e:  # noqa: BLE001
            fail("last-frame extraction (continuity)", str(e)[:120],
                 "این همان گامی است که پلان بعدی را به این یکی می‌چسباند؛ FFMPEG_BIN را در backend/.env بررسی کنید.", e)
    except Exception as e:  # noqa: BLE001
        fail("real Wan 2.2 clip", "%s after %.0fs" % (str(e)[:110], time.time() - t0), comfy_hint(e), e)
    finally:
        free_comfyui()
        settle("unloading Wan")


# ===================================================================== everything that is not the GPU
def check_models_command():
    """The project's own inventory: which model FILES each workflow needs."""
    try:
        r = subprocess.run([sys.executable, "manage.py", "checkmodels", "--strict"], cwd=str(BACKEND),
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)
        (OUT / "checkmodels.log").write_text((r.stdout or "") + (r.stderr or ""), encoding="utf-8")
        if r.returncode == 0:
            record("PASS", "checkmodels --strict", "every model file the workflows name is installed")
        else:
            fail("checkmodels --strict", "some model the project needs is missing — see checkmodels.log",
                 "logs/verify/checkmodels.log نام دقیق فایل‌های کم را نوشته.")
    except Exception as e:  # noqa: BLE001
        fail("checkmodels --strict", str(e)[:120], "", e)


def check_ffmpeg():
    # The project's own answer to "where is ffmpeg" — the same one every video,
    # voice and subtitle job gets — not a second opinion worked out here.
    from services.video.ffmpeg import FFMPEG as ffmpeg, FFPROBE as ffprobe

    if not (os.path.isfile(ffmpeg) or shutil.which(ffmpeg)):
        return fail("ffmpeg found", "the project resolves ffmpeg to %r, which does not exist" % ffmpeg,
                    "start.bat را یک بار اجرا کنید (ffmpeg را داخل پوشه‌ی پروژه نصب می‌کند)، یا ffmpeg را در PATH بگذارید.")
    pinned = (os.getenv("FFMPEG_BIN") or "").strip()
    if pinned and pinned != ffmpeg:
        record("WARN", "ffmpeg pin in backend/.env is stale", "%s does not exist here — using %s instead" % (pinned, ffmpeg))
    record("PASS", "ffmpeg found", ffmpeg)
    tmp = tempfile.mkdtemp(prefix="upm-smoke-")
    try:
        out = os.path.join(tmp, "probe.mp4")
        r = subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                            "testsrc=duration=1:size=320x240:rate=10", "-pix_fmt", "yuv420p", out],
                           capture_output=True, text=True, timeout=120)
        if r.returncode != 0 or not os.path.exists(out):
            return fail("ffmpeg real encode", (r.stderr or "")[-160:], "ffmpeg خراب است یا libx264 ندارد.")
        record("PASS", "ffmpeg real encode", "%d bytes" % os.path.getsize(out))
        if ffprobe:
            p = subprocess.run([ffprobe, "-v", "error", "-show_entries", "format=duration",
                                "-of", "default=nw=1:nk=1", out], capture_output=True, text=True, timeout=60)
            record("PASS" if p.returncode == 0 else "FAIL", "ffprobe reads it back", "duration=%s" % p.stdout.strip())
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def check_voice(fast):
    try:
        import edge_tts  # noqa: F401
    except Exception as e:  # noqa: BLE001
        return fail("edge-tts installed", str(e)[:100], "pip install edge-tts", e)
    record("PASS", "edge-tts installed")
    if fast:
        return record("SKIP", "real Persian narration", "--fast")
    import asyncio

    out = OUT / "artifacts" / "narration-test.mp3"
    out.parent.mkdir(exist_ok=True)

    async def speak():
        import edge_tts

        await edge_tts.Communicate("این یک آزمایش صدا است.", "fa-IR-DilaraNeural").save(str(out))

    try:
        asyncio.run(asyncio.wait_for(speak(), timeout=60))
        size = out.stat().st_size if out.exists() else 0
        record("PASS" if size > 1000 else "FAIL", "real Persian narration", "%d bytes of mp3" % size)
    except Exception as e:  # noqa: BLE001
        # A Microsoft web service: from a filtered connection this fails for
        # network reasons, which is a real operational finding, not a code bug.
        record("WARN", "real Persian narration", "network? %s" % str(e)[:90])


def check_libs():
    for mod, label, hint in (("faster_whisper", "faster-whisper (subtitles)", "pip install faster-whisper"),
                             ("cv2", "opencv (face-aware zoom)", "pip install opencv-python-headless"),
                             ("PIL", "Pillow", "pip install Pillow")):
        try:
            __import__(mod)
            record("PASS", label)
        except Exception as e:  # noqa: BLE001
            fail(label, str(e)[:100], hint, e)


def check_redis():
    url = getattr(settings, "CELERY_BROKER_URL", "") or ""
    if not url.startswith("redis"):
        return record("SKIP", "Redis", "broker is %r" % url[:40])
    try:
        import redis

        redis.Redis.from_url(url, socket_connect_timeout=5).ping()
        record("PASS", "Redis answers PING", url)
    except Exception as e:  # noqa: BLE001
        fail("Redis answers PING", str(e)[:100],
             "بدون Redis تولید ویدیو صف نمی‌شود. start.bat آن را خودش بالا می‌آورد؛ verify-all.bat هم.", e)


def write_errors():
    path = OUT / "ERRORS-real-stack.txt"
    if not ERRORS:
        if path.exists():
            path.unlink()
        return
    lines = []
    for e in ERRORS:
        lines += ["#" * 70, "مرحله        : " + e["step"], "چه شد        : " + e["what"],
                  "چه باید کرد  : " + (e["hint"] or "—")]
        if e["technical"]:
            lines += ["--- جزئیات فنی ---", e["technical"].rstrip()]
        lines.append("")
    for label, _ in STARTED:
        log = OUT / ("svc-%s.log" % label)
        if log.exists():
            tail = log.read_text(encoding="utf-8", errors="replace").splitlines()[-40:]
            lines += ["#" * 70, "آخرین خط‌های %s" % log.name, *tail, ""]
    path.write_text("\n".join(lines), encoding="utf-8")
    print("\n%d failure(s) explained in %s" % (len(ERRORS), path), flush=True)


def main():
    global OUT
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fast", action="store_true", help="no generation at all — only 'is it installed and reachable'")
    ap.add_argument("--full-video", action="store_true", help="render the production length (81 frames) instead of 33")
    ap.add_argument("--no-start", action="store_true", help="do not start Ollama/ComfyUI; only use what is running")
    ap.add_argument("--keep-services", action="store_true", help="leave what this test started running")
    ap.add_argument("--comfyui-dir", default="", help="where ComfyUI lives, if it is not found automatically")
    ap.add_argument("--out", default=str(ROOT / "logs" / "verify"), help="report folder")
    # Defaults sized for an RTX 3060 12 GB + 24 GB RAM, where a 30B model loads
    # half onto the CPU and Wan 2.2 swaps two 14B UNETs through the card.
    ap.add_argument("--timeout-text", type=int, default=1800, help="seconds per text model (default 30 min)")
    ap.add_argument("--timeout-image", type=int, default=1800, help="seconds for the FLUX image (default 30 min)")
    ap.add_argument("--timeout-video", type=int, default=5400, help="seconds for the Wan clip (default 90 min)")
    ap.add_argument("--boot-wait", type=int, default=600, help="seconds to wait for ComfyUI to boot (default 10 min)")
    args = ap.parse_args()

    OUT = Path(args.out)
    OUT.mkdir(parents=True, exist_ok=True)

    print("=== UpMarket real-stack test — one model at a time ===")
    print("configured: text=%s  vision=%s  | product limits: OLLAMA_TIMEOUT=%ss COMFYUI_TIMEOUT=%ss\n" % (
        AI.get("MODEL_REASONING"), AI.get("MODEL_VISION"), AI.get("OLLAMA_TIMEOUT"), AI.get("COMFYUI_TIMEOUT")))
    started = time.time()
    try:
        check_gpu()
        ensure_ollama(args.no_start)
        ensure_comfyui(args.no_start, args.comfyui_dir, args.boot_wait)
        if listening(ollama_base() + "/api/tags"):
            check_text_models(args.fast, args.timeout_text)
        if listening(ollama_base() + "/api/tags") and listening(comfy_base() + "/system_stats"):
            check_models_command()
        check_image_and_video(args.fast, args.timeout_image, args.timeout_video, args.full_video)
        check_ffmpeg()
        check_voice(args.fast)
        check_libs()
        check_redis()
    except KeyboardInterrupt:
        record("FAIL", "interrupted", "stopped by the user")
    except Exception as e:  # noqa: BLE001 — the report must be written whatever happens
        fail("the test itself crashed", str(e)[:150], "این یک باگ در خود real_smoke.py است؛ جزئیات فنی را بفرستید.", e)
    finally:
        write_errors()
        if not args.keep_services:
            stop_started()

    counts = {}
    for status, _, _ in RESULTS:
        counts[status] = counts.get(status, 0) + 1
    print("\nSUMMARY: %s   (%.1f min)" % ("  ".join("%s=%d" % kv for kv in sorted(counts.items())),
                                         (time.time() - started) / 60))
    return 1 if counts.get("FAIL") else 0


if __name__ == "__main__":
    sys.exit(main())
