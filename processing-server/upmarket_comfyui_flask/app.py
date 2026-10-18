import os, json, time, uuid, threading
from datetime import datetime
from pathlib import Path
from functools import wraps
import requests
from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, Response

ROOT = Path(__file__).resolve().parent
WORKFLOWS_DIR = ROOT / "workflows"
UPLOAD_DIR = ROOT / "uploads"
OUTPUT_DIR = ROOT / "outputs"
CONFIG_PATH = ROOT / "config.json"
PROFILES_PATH = ROOT / "profiles.json"
for p in (WORKFLOWS_DIR, UPLOAD_DIR, OUTPUT_DIR):
    p.mkdir(parents=True, exist_ok=True)

DEFAULT_CONFIG = {
    "comfyui_url": "http://127.0.0.1:8188",
    "client_id": "upmarket-flask-" + str(uuid.uuid4()),
    "api_key": uuid.uuid4().hex + uuid.uuid4().hex,
    "enabled": {"image": True, "edit": True, "video": True},
    "workflows": {
        "image": {"file": "image_api.json", "prompt_node_id": "4", "prompt_input": "text", "negative_prompt_node_id": "3", "negative_prompt_input": "text", "image_node_id": "", "image_input": "image", "width_node_id": "5", "width_input": "width", "height_node_id": "5", "height_input": "height", "seed_node_id": "2", "seed_input": "seed"},
        "edit": {"file": "image_edit_api.json", "prompt_node_id": "4", "prompt_input": "text", "negative_prompt_node_id": "3", "negative_prompt_input": "text", "image_node_id": "16", "image_input": "image", "width_node_id": "17", "width_input": "width", "height_node_id": "17", "height_input": "height", "seed_node_id": "2", "seed_input": "seed"},
        "video": {"file": "video_api.json", "prompt_node_id": "10", "prompt_input": "text", "negative_prompt_node_id": "11", "negative_prompt_input": "text", "image_node_id": "1", "image_input": "image", "seed_node_id": "13", "seed_input": "noise_seed"}
    }
}

def load_config():
    if not CONFIG_PATH.exists():
        save_config(DEFAULT_CONFIG)
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        data = {}
    merged = json.loads(json.dumps(DEFAULT_CONFIG))
    for k, v in data.items():
        if k not in ("workflows", "enabled"):
            merged[k] = v
    if isinstance(data.get("enabled"), dict):
        merged["enabled"].update(data["enabled"])
    if isinstance(data.get("workflows"), dict):
        for key, value in data["workflows"].items():
            if key in merged["workflows"] and isinstance(value, dict):
                merged["workflows"][key].update(value)
    # Ensure older config files gain an API key.
    if not data.get("api_key"):
        merged["api_key"] = uuid.uuid4().hex + uuid.uuid4().hex
        save_config(merged)
    return merged

def save_config(data):
    CONFIG_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def load_profiles():
    return json.loads(PROFILES_PATH.read_text(encoding="utf-8"))

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "local-dev-change-this")
app.config["MAX_CONTENT_LENGTH"] = 32 * 1024 * 1024
jobs = {}
jobs_lock = threading.Lock()

BASE_NODE_MAP = {
    "image": {"prompt": ("4", "text"), "negative": ("3", "text"), "image": None},
    "edit": {"prompt": ("4", "text"), "negative": ("3", "text"), "image": ("16", "image")},
    "video": {"prompt": ("10", "text"), "negative": ("11", "text"), "image": ("1", "image")},
}

def comfy_url(path):
    return load_config()["comfyui_url"].rstrip("/") + path

def set_node_input(workflow, node_id, input_name, value):
    if not node_id:
        return False
    node = workflow.get(str(node_id))
    if not node:
        raise ValueError(f"Node ID {node_id} در workflow وجود ندارد.")
    inputs = node.get("inputs", {})
    if input_name not in inputs:
        raise ValueError(f"ورودی '{input_name}' در Node {node_id} نیست. ورودی‌های موجود: {', '.join(inputs.keys())}")
    inputs[input_name] = value
    return True

def upload_image_to_comfy(filepath):
    with open(filepath, "rb") as f:
        response = requests.post(comfy_url("/upload/image"), files={"image": (os.path.basename(filepath), f, "application/octet-stream")}, data={"overwrite": "true"}, timeout=120)
    response.raise_for_status()
    data = response.json()
    return data.get("name") or os.path.basename(filepath)

def queue_job(kind, profile_id, prompt, negative_prompt, image_path, values):
    profiles = load_profiles()
    profile = next((p for p in profiles if p["id"] == profile_id and p["kind"] == kind), None)
    if not profile:
        raise ValueError("پروفایل انتخاب‌شده برای این نوع خروجی معتبر نیست.")
    cfg = load_config()
    workflow_path = WORKFLOWS_DIR / profile["file"]
    if not workflow_path.exists():
        raise FileNotFoundError(f"فایل workflow پیدا نشد: {profile['file']}")
    workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
    node_map = BASE_NODE_MAP[kind]
    node_cfg = cfg.get("workflows", {}).get(kind, {})
    prompt_target = (node_cfg.get("prompt_node_id") or node_map["prompt"][0], node_cfg.get("prompt_input") or node_map["prompt"][1])
    negative_target = (node_cfg.get("negative_prompt_node_id") or (node_map.get("negative") or ("", ""))[0], node_cfg.get("negative_prompt_input") or (node_map.get("negative") or ("", ""))[1])
    image_target = (node_cfg.get("image_node_id") or (node_map.get("image") or ("", ""))[0], node_cfg.get("image_input") or (node_map.get("image") or ("", ""))[1])
    set_node_input(workflow, *prompt_target, prompt)
    if negative_prompt and negative_target[0]:
        set_node_input(workflow, *negative_target, negative_prompt)
    if image_path:
        if not image_target[0]:
            raise ValueError("این workflow عکس مرجع نمی‌پذیرد.")
        image_name = upload_image_to_comfy(image_path)
        set_node_input(workflow, *image_target, image_name)
    # Apply only controls declared by the selected profile. This prevents irrelevant inputs leaking between flows.
    for control in profile.get("controls", []):
        name = control["name"]
        raw = values.get(name, control.get("default", profile.get("defaults", {}).get(name)))
        if raw is None or raw == "":
            continue
        if control.get("type") == "number":
            value = int(raw) if name == "seed" or isinstance(control.get("default"), int) else float(raw)
        else:
            allowed = [str(v) for v in control.get("options", [])]
            if allowed and str(raw) not in allowed:
                raise ValueError(f"مقدار {name} برای این پروفایل مجاز نیست.")
            default = control.get("default")
            value = float(raw) if isinstance(default, float) else int(raw) if isinstance(default, int) else raw
        if name == "seed" and int(value) < 0:
            value = int.from_bytes(os.urandom(4), "big")
        for target_node, target_input in control.get("targets", []):
            set_node_input(workflow, target_node, target_input, value)
    payload = {"prompt": workflow, "client_id": cfg["client_id"]}
    r = requests.post(comfy_url("/prompt"), json=payload, timeout=60)
    if not r.ok:
        raise RuntimeError(f"ComfyUI خطا داد ({r.status_code}): {r.text[:1600]}")
    result = r.json()
    prompt_id = result.get("prompt_id")
    if not prompt_id:
        raise RuntimeError(f"ComfyUI شناسه اجرای prompt برنگرداند: {result}")
    with jobs_lock:
        jobs[prompt_id] = {"prompt_id": prompt_id, "kind": kind, "profile_id": profile_id, "profile_label": profile["label"], "status": "queued", "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "prompt": prompt, "outputs": [], "error": None}
    return prompt_id

def output_worker():
    while True:
        time.sleep(2.5)
        with jobs_lock:
            pending = [j.copy() for j in jobs.values() if j["status"] not in ("completed", "error")]
        for job in pending:
            try:
                r = requests.get(comfy_url("/history/" + job["prompt_id"]), timeout=8)
                if r.status_code != 200:
                    continue
                hist = r.json().get(job["prompt_id"])
                if not hist:
                    continue
                status_info = hist.get("status", {})
                if status_info.get("status_str") == "error":
                    with jobs_lock:
                        if job["prompt_id"] in jobs:
                            jobs[job["prompt_id"]]["status"] = "error"
                            jobs[job["prompt_id"]]["error"] = "ComfyUI اجرای workflow را با خطا متوقف کرد. جزئیات را در ترمینال ComfyUI ببین."
                    continue
                outputs = []
                for node_output in hist.get("outputs", {}).values():
                    for key in ("images", "gifs", "videos"):
                        for item in node_output.get(key, []) or []:
                            if item.get("filename"):
                                outputs.append({"filename": item["filename"], "subfolder": item.get("subfolder", ""), "type": item.get("type", "output"), "media": key})
                with jobs_lock:
                    if job["prompt_id"] in jobs:
                        if outputs:
                            jobs[job["prompt_id"]]["status"] = "completed"
                            jobs[job["prompt_id"]]["outputs"] = outputs
                        elif status_info.get("completed") is True:
                            jobs[job["prompt_id"]]["status"] = "completed"
            except Exception:
                pass

threading.Thread(target=output_worker, daemon=True).start()

def sorted_jobs():
    with jobs_lock:
        return sorted([dict(j) for j in jobs.values()], key=lambda x: x["created_at"], reverse=True)

def save_uploaded_image(file):
    if not file or not file.filename:
        return None
    ext = Path(file.filename).suffix.lower()
    if ext not in (".png", ".jpg", ".jpeg", ".webp"):
        raise ValueError("فرمت عکس باید PNG، JPG یا WEBP باشد.")
    dest = UPLOAD_DIR / f"{uuid.uuid4().hex}{ext}"
    file.save(dest)
    return dest

def read_generate_request(req):
    if req.is_json:
        data = req.get_json(silent=True) or {}
        return data, None
    return req.form, req.files.get("image")

def submit_request(req, api_mode=False):
    data, file = read_generate_request(req)
    kind = str(data.get("kind", "image"))
    if kind not in ("image", "edit", "video"):
        return {"ok": False, "error": "نوع خروجی نامعتبر است."}, 400
    cfg = load_config()
    if not cfg.get("enabled", {}).get(kind, True):
        return {"ok": False, "error": f"تولید {kind} در تنظیمات خاموش است."}, 403
    prompt = str(data.get("prompt", "")).strip()
    negative_prompt = str(data.get("negative_prompt", "")).strip()
    if not prompt:
        return {"ok": False, "error": "پرامپت را وارد کن."}, 400
    if kind in ("edit", "video") and (not file or not file.filename):
        return {"ok": False, "error": "برای ویرایش تصویر و تولید ویدئو، عکس مرجع لازم است."}, 400
    try:
        image_path = save_uploaded_image(file) if file and file.filename else None
        profile_id = str(data.get("profile_id", ""))
        if not profile_id:
            profile_id = next(p["id"] for p in load_profiles() if p["kind"] == kind)
        values = {}
        profile = next((p for p in load_profiles() if p["id"] == profile_id and p["kind"] == kind), None)
        if not profile:
            raise ValueError("پروفایل انتخاب‌شده معتبر نیست.")
        for control in profile.get("controls", []):
            if control["name"] in data:
                values[control["name"]] = data[control["name"]]
        prompt_id = queue_job(kind, profile_id, prompt, negative_prompt, image_path, values)
        return {"ok": True, "prompt_id": prompt_id, "profile_id": profile_id, "message": "در صف ComfyUI قرار گرفت."}, 200
    except Exception as e:
        return {"ok": False, "error": str(e)}, 400

@app.route("/")
def index():
    return render_template("index.html", config=load_config(), jobs=sorted_jobs(), profiles=load_profiles())

@app.route("/generate", methods=["POST"])
def generate():
    data, status = submit_request(request)
    return jsonify(data), status

@app.route("/api/jobs")
def api_jobs():
    return jsonify(sorted_jobs())

@app.route("/api/status")
def api_status():
    try:
        r = requests.get(comfy_url("/system_stats"), timeout=4)
        r.raise_for_status()
        return jsonify({"ok": True, "url": load_config()["comfyui_url"], "system": r.json()})
    except Exception as e:
        return jsonify({"ok": False, "url": load_config()["comfyui_url"], "error": str(e)}), 503

# Versioned public API. Protect it with X-API-Key or Authorization: Bearer <key>.
def require_api_key(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        cfg = load_config()
        expected = os.environ.get("UPMARKET_API_KEY") or cfg.get("api_key", "")
        supplied = request.headers.get("X-API-Key", "")
        auth = request.headers.get("Authorization", "")
        if not supplied and auth.lower().startswith("bearer "):
            supplied = auth[7:].strip()
        if not expected or supplied != expected:
            return jsonify({"ok": False, "error": "API key نامعتبر یا ارسال نشده است."}), 401
        return fn(*args, **kwargs)
    return wrapped

@app.route("/api/v1/status")
@require_api_key
def api_v1_status():
    try:
        r = requests.get(comfy_url("/system_stats"), timeout=4)
        r.raise_for_status()
        return jsonify({"ok": True, "comfyui_url": load_config()["comfyui_url"], "system": r.json()})
    except Exception as e:
        return jsonify({"ok": False, "comfyui_url": load_config()["comfyui_url"], "error": str(e)}), 503

@app.route("/api/v1/workflows")
@require_api_key
def api_v1_workflows():
    return jsonify({"ok": True, "workflows": [{"id": p["id"], "kind": p["kind"], "label": p["label"], "description": p.get("description", ""), "defaults": p.get("defaults", {}), "controls": p.get("controls", [])} for p in load_profiles()]})

@app.route("/api/v1/generate", methods=["POST"])
@require_api_key
def api_v1_generate():
    data, status = submit_request(request, api_mode=True)
    return jsonify(data), status

@app.route("/api/v1/jobs")
@require_api_key
def api_v1_jobs():
    return jsonify({"ok": True, "jobs": sorted_jobs()})

@app.route("/api/v1/jobs/<prompt_id>")
@require_api_key
def api_v1_job(prompt_id):
    with jobs_lock:
        job = jobs.get(prompt_id)
        if not job:
            return jsonify({"ok": False, "error": "کار پیدا نشد."}), 404
        return jsonify({"ok": True, "job": dict(job)})

@app.route("/settings", methods=["GET", "POST"])
def settings():
    cfg = load_config()
    if request.method == "POST":
        cfg["comfyui_url"] = request.form.get("comfyui_url", "http://127.0.0.1:8188").strip().rstrip("/")
        cfg.setdefault("enabled", {})
        for kind in ("image", "edit", "video"):
            cfg["enabled"][kind] = request.form.get(f"enabled_{kind}") == "on"
        if request.form.get("rotate_api_key") == "on":
            cfg["api_key"] = uuid.uuid4().hex + uuid.uuid4().hex
        for kind in ("image", "edit", "video"):
            w = cfg["workflows"][kind]
            fields = ["file","prompt_node_id","prompt_input","negative_prompt_node_id","negative_prompt_input","image_node_id","image_input","width_node_id","width_input","height_node_id","height_input","seed_node_id","seed_input"]
            for field in fields:
                form_key = f"{kind}_{field}"
                if form_key in request.form:
                    w[field] = request.form.get(form_key, "").strip()
        save_config(cfg)
        profiles = load_profiles()
        for profile in profiles:
            kind = profile.get("kind")
            if kind in cfg.get("workflows", {}):
                profile["file"] = cfg["workflows"][kind].get("file", profile.get("file"))
        PROFILES_PATH.write_text(json.dumps(profiles, ensure_ascii=False, indent=2), encoding="utf-8")
        flash("تنظیمات ذخیره شد.", "success")
        return redirect(url_for("settings"))
    workflow_files = sorted([p.name for p in WORKFLOWS_DIR.glob("*.json")])
    return render_template("settings.html", config=cfg, workflow_files=workflow_files, profiles=load_profiles())

def graph_to_api(data):
    if isinstance(data, dict) and data and all(isinstance(v, dict) and "class_type" in v and "inputs" in v for v in data.values()):
        return data
    if not isinstance(data, dict) or not isinstance(data.get("nodes"), list) or not isinstance(data.get("links"), list):
        raise ValueError("این JSON نه API format است و نه workflow گرافیکی قابل تبدیل.")
    links = {}
    for link in data["links"]:
        if isinstance(link, list) and len(link) >= 6:
            links[link[0]] = [str(link[1]), link[2]]
    result = {}
    for node in data["nodes"]:
        if node.get("mode") in (2, 4):
            continue
        node_id, class_type = str(node.get("id")), node.get("type")
        widgets, inputs = list(node.get("widgets_values") or []), {}
        for inp in node.get("inputs", []):
            name = inp.get("name")
            if not name: continue
            link_id = inp.get("link")
            if link_id is not None:
                if link_id in links: inputs[name] = links[link_id]
                continue
            widget = inp.get("widget")
            if widget and isinstance(widget, dict):
                wname = widget.get("name", name)
                value = "example.png" if wname in ("image", "upload") else (widgets.pop(0) if widgets else None)
                if value is not None and wname != "upload": inputs[wname] = value
        if class_type == "KSampler" and len(node.get("widgets_values") or []) >= 7:
            vals=node["widgets_values"]
            inputs.update({"seed":vals[0],"steps":vals[2],"cfg":vals[3],"sampler_name":vals[4],"scheduler":vals[5],"denoise":vals[6]})
        if class_type == "KSamplerAdvanced" and len(node.get("widgets_values") or []) >= 10:
            vals=node["widgets_values"]
            inputs.update({"add_noise":vals[0],"noise_seed":vals[1],"steps":vals[3],"cfg":vals[4],"sampler_name":vals[5],"scheduler":vals[6],"start_at_step":vals[7],"end_at_step":vals[8],"return_with_leftover_noise":vals[9]})
        if class_type == "CheckpointLoaderSimple":
            vals=node.get("widgets_values") or []
            if vals: inputs["ckpt_name"] = vals[0]
        result[node_id] = {"class_type":class_type,"inputs":inputs}
    return result

@app.route("/upload-workflow", methods=["POST"])
def upload_workflow():
    f, kind = request.files.get("workflow"), request.form.get("kind")
    if not f or not f.filename or kind not in ("image", "edit", "video"):
        flash("فایل JSON و نوع workflow را انتخاب کن.", "error"); return redirect(url_for("settings"))
    if not f.filename.lower().endswith(".json"):
        flash("فقط فایل JSON پذیرفته می‌شود.", "error"); return redirect(url_for("settings"))
    try:
        data = graph_to_api(json.loads(f.read().decode("utf-8-sig")))
        name = f"{kind}_api_{uuid.uuid4().hex[:6]}.json"
        (WORKFLOWS_DIR / name).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        cfg = load_config(); cfg["workflows"][kind]["file"] = name; save_config(cfg)
        profiles = load_profiles()
        for profile in profiles:
            if profile.get("kind") == kind:
                profile["file"] = name
        PROFILES_PATH.write_text(json.dumps(profiles, ensure_ascii=False, indent=2), encoding="utf-8")
        flash(f"Workflow آپلود شد: {name}. چون ID نودها ممکن است متفاوت باشد، targets همان نوع را در profiles.json بررسی کن.", "success")
    except Exception as e:
        flash(f"فایل معتبر نیست: {e}", "error")
    return redirect(url_for("settings"))

@app.route("/outputs/<path:filename>")
def outputs(filename):
    try:
        r = requests.get(comfy_url("/view"), params={"filename": filename, "subfolder": request.args.get("subfolder", ""), "type": request.args.get("type", "output")}, timeout=60)
        r.raise_for_status()
        return Response(r.content, mimetype=r.headers.get("Content-Type", "application/octet-stream"))
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 502

@app.route("/workflow/<kind>")
def workflow_info(kind):
    if kind not in ("image", "edit", "video"):
        return jsonify({"error": "نوع نامعتبر"}), 400
    try:
        cfg = load_config()["workflows"][kind]
        wf = json.loads((WORKFLOWS_DIR / cfg["file"]).read_text(encoding="utf-8"))
        return jsonify({"file": cfg["file"], "nodes": [{"id": nid, "class_type": node.get("class_type"), "inputs": node.get("inputs", {})} for nid, node in wf.items()]})
    except Exception as e:
        return jsonify({"error": str(e)}), 400

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)
