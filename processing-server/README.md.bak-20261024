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
| `worker-3d.bat` | Blender render worker for the 3D video section (same registration); started by the agent (panel: services -> 3D render, or automatically while 3D jobs wait). First run downloads Blender 4.5 (~400 MB) and the MPFB character data (~430 MB) from the site, resumable |
| `upmarket_comfyui_flask\` | ComfyUI profiles (FLUX / Wan) and workflow graphs. `agent.py` reads `profiles.json` + `workflows\*.json` directly; running the Flask bridge itself is optional |
| `up3d\`, `engine\`, `assets\` | 3D engine + assets (shipped; nothing else to download except Blender) |
| `tools\PersianAiKit\Photo`, `Video`, `Voice` | photo / video / voice editors (.NET 8); `Setup-Services.bat` prepares them once |

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
6. For 3D rendering, Blender 4.5 and the MPFB character data (`vendor\blender-user`) are needed. If missing, `worker-3d.bat` downloads them **once**
   from the site (about 400 + 430 MB) into `vendor\blender\`. Or install Blender 4.5 LTS yourself, or set
   `UP3D_BLENDER` to the path of `blender.exe`.

Second machine: copy the same folder (without `node.json`) and run `START.bat` again — it registers under
its own name.

## The editors prepare themselves (agent 1.5)

The photo / video / voice editors (PersianAiKit) need no manual step any more. The first time a job needs one,
the agent prepares it while the job waits (the site is told the job is alive, so it is not re-queued):

1. if a .NET 8+ SDK is installed (found even when it is not on PATH, e.g. `C:\Program Files\dotnet`), it builds the
   editor with `dotnet publish` (first time ~5-20 minutes: NuGet packages are downloaded; log in `logs\build-<editor>.log`);
2. otherwise, or if the build fails, it downloads the ready Windows build from the site (`kit-app-<editor>.zip`,
   43-83 MB, resumable after a dropped connection);
3. then ffmpeg for the video editor and the voice models (engine + default voice) for the voice editor.

`Setup-Services.bat` (runs `setup_kit.py`) does the same for all three editors ahead of time; `python setup_kit.py --all`
also fetches all six Persian voices. Natural voices / voice cloning (3.4 GB, optional): `tools\PersianAiKit\Voice\Setup-Voice.bat`.

Every service the agent starts writes its console output to `logs\service-<name>.log`; if a service does not come up,
the last lines are sent to the site log (panel → Processing servers → log of this node).

**ComfyUI path:** the agent looks for `run_nvidia_gpu.bat` (portable ComfyUI) in the usual folders and writes it into
`services.json` → `comfyui` → `start`. If it is not found (`agent.py --check` says so), write the path there yourself.

## Services and auto-switch (controlled from the panel)

`services.json` (created on first run) tells the agent how to start each local service:
`ollama` (`ollama serve`), `comfyui` (`${NM_COMFY_BAT}` → set the env var or write the path of
`run_nvidia_gpu.bat`), `voice` / `photo` / `video` (PersianAiKit `Run-Server.bat`), `worker3d` (`worker-3d.bat`).

In the panel (Processing servers → the node's services) you choose which services should be **on** or
**off** on each machine; the agent applies it within seconds (services it started can be stopped; a service
you started yourself is reported as *external* — Ollama models can still be unloaded and ComfyUI memory
freed). With **auto-switch** on, a job that needs an engine which is not running is handled automatically:
before an image/video job Ollama's models are unloaded from VRAM and ComfyUI is started; before an Ollama
job ComfyUI's models are freed and Ollama is started; voice/photo/video editors are started on demand.
RAM and VRAM usage are reported to the panel on every heartbeat.

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
