# UpMarket Processing Node

Put this folder on the **GPU machine**. The machine needs no public IP and no open port: the agent
connects **out** to the site, takes jobs (images, videos, audio, text), runs them on local services and
sends the results back. Any number of machines can run the **same folder**: on the first start each one
registers itself under its own computer name and gets its own token. The site gives every job to exactly
one node and never processes an identical request twice.

## What is in the folder

| Item | Purpose |
|---|---|
| `START.bat` | the only file you run. First time it asks for the **enrollment key** (panel → Tools → Processing servers → "Register a new server") and saves `node.json`; afterwards it just starts |
| `agent.py` | the node (Python standard library only, nothing to install) |
| `site.json` | the site URL (edit it if the site moves) |
| `worker-3d.bat` | Blender render worker for the 3D video section (same registration); started automatically by `START.bat` when the `up3d` folder exists |
| `upmarket_comfyui_flask\` | ComfyUI profiles (FLUX / Wan) and workflow graphs. `agent.py` reads `profiles.json` + `workflows\*.json` directly; running the Flask bridge itself is optional |
| `up3d\`, `engine\`, `assets\` | 3D engine + assets (shipped; nothing else to download except Blender) |
| `tools\PersianAiKit\Photo`, `Video`, `Voice` | photo / video / voice editors (.NET 8); each has its own `Run-Server.bat` |

## Setup (about 5 minutes per machine)

1. Install **Python 3.10 or newer** (tick *Add python to PATH*).
2. Install and run **ComfyUI** with the FLUX / Wan 2.2 models on this machine (port 8188). If you set the
   environment variable `NM_COMFY_BAT` to your `run_nvidia_gpu.bat`, `START.bat` starts it for you.
3. Run `START.bat`. Paste the **enrollment key** from the panel (Tools → Processing servers → "Register a
   new server"). The machine registers itself as a node named after the computer (`node.json` is written);
   a diagnostic is printed (site reachable, ComfyUI, profiles, GPU, Blender …).
4. The node shows **online** in the panel within a few seconds, with the services it found.
5. Optional: Ollama (text/vision models on the GPU) and the PersianAiKit editors — whatever is running is
   detected automatically and reported to the site.
6. For 3D rendering, Blender 4.5 is needed. If it is not installed, `worker-3d.bat` downloads it **once**
   from the site (about 400 MB) into `vendor\blender\`. Or install Blender 4.5 LTS yourself, or set
   `UP3D_BLENDER` to the path of `blender.exe`.

Second machine: copy the same folder (without `node.json`) and run `START.bat` again — it registers under
its own name.

## Diagnostic

    python agent.py --check

Lines starting with `!!` need attention, `--` are optional services that are not running.

## Logs

Console + `logs\agent.log`. Warnings and errors are also sent to the site and are visible in the panel
(**Processing servers → the node's "Log" button**), so you can see what went wrong without opening this
machine.

## Optional environment variables (set before running START)

| Variable | Default | Meaning |
|---|---|---|
| `NM_ENROLL_KEY` | asked once | enrollment key (skips the prompt) |
| `NM_NODE` | computer name | node name used at registration |
| `NM_COMFYUI_URL` | `http://127.0.0.1:8188` | ComfyUI somewhere else |
| `NM_OLLAMA_URL` | `http://127.0.0.1:11434` | |
| `NM_PHOTO_URL` / `NM_VIDEO_URL` / `NM_VOICE_URL` | `:5670` / `:5680` / `:5600` | PersianAiKit servers |
| `NM_SLOTS` | `1` | jobs in parallel (keep 1 for a single GPU) |
| `NM_COMFY_BAT` | — | path of `run_nvidia_gpu.bat` to auto-start ComfyUI |
| `NM_KEEP_WORK` | — | keep each job's `work\` folder (debugging) |
| `UP3D_BLENDER` | auto | path of `blender.exe` |

## Troubleshooting

- **Offline in the panel** → the START window was closed, or the site URL/key is wrong (`python agent.py --check`).
- **Token rejected (401)** → the node was deleted or its token rotated in the panel: delete `node.json` and
  run `START.bat` again with the enrollment key.
- **Image/video job "failed" with a ComfyUI message** → ComfyUI itself reported it (missing model or node);
  the same text is shown in the panel and in ComfyUI's own window.
- **Ollama job "model not found"** → that model is not pulled on this machine (`ollama pull <model>`), or
  use a model name from `ollama list`.
- **Two machines the same job?** Impossible: claiming is atomic on the site; each job has exactly one node.
- **Machine died mid-job** → after 10 minutes without a heartbeat the site hands the job to another node
  (after two failed attempts the job is marked failed).
