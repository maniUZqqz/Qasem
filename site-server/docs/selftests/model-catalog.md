# Self-test: model catalog («دانلودِ مدل‌ها») on the GPU node

The automatic acceptance run of the node (`backend/apps/compute/selftests/`, page «آزمونِ خودکارِ سرورِ پردازش») tests this feature with the
module `backend/apps/compute/selftests/model_catalog.py` (Python, not a docs block: the checks read the node's `capabilities.models` report
and the site's own catalog). Four tests, all automatic (after every new agent version and every night):

| key | kind | what it does | pass |
|---|---|---|---|
| `model_catalog` | virtual (no job) | the agent knows the new catalog | every package of the groups image / video / upscale / control / depth (all that have `package_info` in `processing/downloads/*.json`) is in `capabilities.models.packages`, and the free disk (`disk_mb`) is reported. An older agent (no new packages) fails with «به‌روزرسانی را بزنید» |
| `model_catalog_download` | real job `node.models` | one small real download: `{"action": "download", "packages": ["frame-interp"], "window": ""}` (RIFE + FILM, about 109 MB) | the job completes and `models.json` has `result` and `status` |
| `model_catalog_installed` | virtual, after the download | waits (up to 3 h) until the package is installed (sha256-verified) | `capabilities.models.packages["frame-interp"].installed` is true; a download error fails it |
| `model_catalog_auto` | virtual | the automatic mode | every package the enabled features want is installed, or in a legal state (`pending`, `downloading`, `queued`, `waiting_window`, `no_disk`) - never `failed`; no non-commercial package is ever in the wanted list |

Nothing here needs a person: the node's `START.bat` runs `model_auto.py`; the site sends `models_auto` with every heartbeat.

## Manual checks (same facts, for a human or for the integrator)

Everything is read from `GET /api/v1/compute/models/` (staff), or by `python download_models.py --list` in the node's `processing` folder.

### 1. The catalog reaches the node (no download)

| step | what | pass |
|---|---|---|
| a | `GET /api/v1/compute/models/` | `nodes[0].reported == true`; groups `image, video, upscale, control, depth, voice, matting` are all present; **no** package of the new groups has `state == "unknown"` (an `unknown` one means the node runs older code: send the «دستورها» `update` command, wait for the heartbeat, retry) |
| b | same response | `nodes[0].node.disk_free_mb` is a number; every `missing` package has `fits` true/false (not null) |
| c | same response | `flux-dev.state == "installed"` when the file `FLUX.1 [dev] FP8.safetensors` is in `ComfyUI\models\checkpoints` (the alias rule); `flux-dev.license_class == "noncommercial"` and `flux-dev.auto.mode == "never"` |

### 2. One small real download (frame interpolation, about 109 MB)

```
POST /api/v1/compute/nodes/5/models/download/
{"packages": ["frame-interp"], "when": {"mode": "now"}}
```

Pass check (within 10 minutes of the node being online and idle):

1. `capabilities.models.packages["frame-interp"].installed == true` and `missing_mb == 0` (re-read `GET /compute/models/`);
2. `capabilities.models.error == ""` and the node log `logs\download-models-agent.log` has no `FAILED` line for `frame-interp:*`;
3. ComfyUI sees the files: `GET http://127.0.0.1:8188/object_info/FrameInterpolationModelLoader` lists `rife_v4.25.safetensors`,
   `rife_v4.25_lite.safetensors` and `film_net_fp16.safetensors` under `input.required.model_name[0]` (ComfyUI reads the folder per call; no restart);
4. running the packages again changes nothing: a second `download` of the same package finishes in seconds with `skipped` (no bytes).

Clean-up: leave the files (they are wanted by the automatic mode anyway).

### 3. Automatic mode (nothing clicked)

With the default switches (`image_studio, photo_enhance, smooth_motion, depth_3d` on):

1. the answer of the node's next `POST /api/v1/compute/heartbeat/` carries `models_auto.packages ==
   ["depth-anything-v2-small", "esrgan-x4plus", "frame-interp", "flux-schnell"]` (priority order);
2. within 15 minutes of an idle node: `capabilities.models.auto.states` has `installed` for `esrgan-x4plus`, `frame-interp`,
   `depth-anything-v2-small` (small ones start at once), and `flux-schnell` is one of `waiting_window` (outside 02:00-07:00 Tehran),
   `downloading`, `installed`, `no_disk` (never `failed` and never absent);
3. `flux-dev`, `flux-fill`, `flux-kontext`, `ultrasharp-4x`, `nmkd-siax-4x`, `codeformer`, `controlnet-union-flux`,
   `ltx-video-distilled` are **never** in `models_auto.packages` and never in `auto.states`;
4. with `POST /compute/models/auto/ {"enabled": false}` the next heartbeat carries `enabled: false` and no new download starts.

### 4. Disk guard

Not run on the owner's disk. Covered by `processing/tests/test_model_catalog_node.py` (`PlanTests`, `TickTests`): a package that does not fit
`free - reserve` is skipped (`no_disk`) and nothing is started below the reserve.
