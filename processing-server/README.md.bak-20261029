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
   new server"). The machine registers itself as a node named after the computer (`node.json` is written).
   Every start prints a short checklist (Python, git, site, ffmpeg, .NET/NuGet, ComfyUI, GPU driver, models, disk)
   and fetches whatever is missing by itself - the models in the background (see below).
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

## Voice cloning (agent 1.6)

The panel's «صدا و گوینده › کلونِ صدا» sends `voice.clone` (the read sentences + the owner's consent) and then
`voice.tts` jobs that name the cloned voice. They need the kit's Python voice service with Pocket-TTS. If it is not
installed, the first such job installs it by itself (what `Setup-Voice.bat` does, limited to speech: `voice\.venv`,
packages, Pocket-TTS ~490 MB; logs in `logs\setup-voice-*.log`; `NM_VOICE_AUTOSETUP=0` turns this off). If that is
not possible (Python outside 3.10-3.13, no internet), the job fails with the instruction to run
`tools\PersianAiKit\Voice\Setup-Voice.bat` once. A cloned voice never falls back to Piper; if a node does not have the
voice (`VOICE_MISSING`), the site sends the job again with the best recordings and the node rebuilds it.
Tests: `python tests\test_agent_voice.py` (fake kit, no models needed).

## Models for speech, cloning, ambience and music (agent 1.8): nothing to type

`START.bat` checks the machine every time it opens (the checklist below). If a model of the **default set** is missing
it starts the download by itself, in the background: the node keeps taking other jobs meanwhile, the panel shows the
progress, and a job that needs a model still downloading waits in the queue (the panel says why) instead of failing.

Default set (downloaded without asking):

| Package | What | Download (models + Python packages) |
|---|---|---|
| `moss-tts` | speech + voice cloning: MOSS-TTS + Persian LoRA | ~15.5 GB |
| `moss-sfx` | ambience / sound effects: MOSS-SoundEffect v2.0 | ~12.2 GB |
| `acestep` | background music: ACE-Step 1.5 | ~11.8 GB |
| `wan22-flf`, `wan-i2v-legacy` | the main Wan 2.2 video engine - only the files ComfyUI does not have yet | up to 36 GB |

Optional (panel > Processing servers > the node's «مدل‌های صدا» card > «بسته‌های دیگر» > «دانلود»): `wan22-4step`
(4-step lightx2v LoRAs, 2.4 GB) and `fun-inp` (fast Fun-InP 1.3B engine + CLIP-Vision-H, 4.4 GB).

Disk: 29.4 GB of voice models + about 9.4 GB of Python packages in `venvs\moss-tts`, `venvs\moss-sfx`, `venvs\acestep`
(Python 3.12, installed per user into `python312\` when missing). ACE-Step keeps its own torch 2.7.1 (its requirements pin
it on Windows, together with torchao / triton-windows), so it does not share MOSS's torch 2.9.1: about 4 GB more download
and ~6 GB more on disk. Plan about 55 GB free. All engines allow commercial use (Apache-2.0 / MIT).

**Nothing is downloaded twice:**

- a file ComfyUI already has is used where it is (`--list` says `have (ComfyUI)`): any `models\` subfolder of the
  ComfyUI found on this machine, every folder listed in `extra_model_paths.yaml` (`base_path` and the per-type entries,
  multi-line `|` lists included) and the base path of ComfyUI Desktop;
- the same file in two packages (same sha256 or URL) is fetched once and hard-linked (copied on another drive);
- Python wheels go through one shared cache, `pip-cache\` (torch is downloaded once for both MOSS venvs);
- a second downloader started while one runs exits at once (`logs\download.lock`); finished files are skipped,
  broken downloads resume, nothing is deleted.

`Download-Models.bat` with no arguments still works by hand and downloads the whole default set. Options, rarely needed:

    Download-Models.bat --list      what is already here ("already have" / "have (ComfyUI)") and what would be downloaded
    Download-Models.bat --all       the default set + the optional packages
    Download-Models.bat --check     test every link without downloading
    Download-Models.bat --hf-mirror https://hf-mirror.com      if huggingface.co is filtered
    Download-Models.bat --pip-mirror https://mirror-pypi.runflare.com/simple

### Panel: Processing servers > «مدل‌های صدا» (one card per node; linked from the «صدا» section)

- Four rows - speech, voice cloning, ambience, music - each with an **on/off switch**. Off: the site never sends that kind
  of job to this node and the node stops the engine at once (its GPU memory is freed). Speech then falls back to the next
  voice in the admin's list (Edge, then Piper); ambience to the sound library and procedural sounds; music to the library
  only (the page says so); cloning answers "voice cloning is off".
- **«تست»** runs a standard short job cold (about 10 s of Persian speech / 8 s in a cloned voice / 5 s of effect / 15 s of
  music) and reports model load time, generation time, RTF, peak VRAM, peak system RAM and GPU utilisation (nvidia-smi
  sampled every 0.5 s), a verdict (سبک / متوسط / سنگین) with what it means for the queue, and the audio to listen to.
  Results are kept; on an offline node the test waits in the queue and runs when the node is back.
- Installed / downloading (with %) / missing per model; **«دانلود»** for a missing model or an optional package makes the
  node run the downloader itself.
- "Free GPU memory after N minutes idle" (default 15; the variable `NM_AUDIO_IDLE_S` still overrides it).

### The START.bat checklist

Printed on every start (English; `[✓]` / `[✗]` in Windows Terminal, `[OK]` / `[X ]` in the classic console) and sent to the panel (card > "checklist of the last start"):
Python > git > site reachable and node registered > ffmpeg > .NET 8 SDK + NuGet (the editors are built; without dotnet or
without NuGet the ready-made editors are downloaded from the site instead) > ComfyUI found > GPU driver (527+ for
CUDA 12.8) > models (default set missing: background download) > free disk. When everything is in place a re-run takes
a few seconds and changes nothing.

Smoke check without a GPU: `python audio\moss_tts_server.py --fake`. Tests: `python tests\test_download_models.py`,
`python tests\test_agent_audio.py`, `python tests\test_agent_setup.py`.

Every service the agent starts writes its console output to `logs\service-<name>.log`; if a service does not come up,
the last lines are sent to the site log (panel → Processing servers → log of this node).

**ComfyUI path:** the agent looks for `run_nvidia_gpu.bat` (portable ComfyUI) in the usual folders and writes it into
`services.json` → `comfyui` → `start`. If it is not found (`agent.py --check` says so), write the path there yourself.

## Regenerate a piece of a video (panel › Content › «بازسازیِ یک تکه»)

The site sends ordinary `comfy.graph` jobs (no new job kind, no agent change): the last frame before the cut and the
first frame after it go up as PNG, ComfyUI renders the piece with **Wan 2.2 I2V A14B** and the core node
`WanFirstLastFrameToVideo` (quality) or **Wan 2.1 Fun-InP 1.3B** with `WanFunInpaintToVideo` (fast), and the PNG frames
come back. Timing, colour, sharpness/grain and seam matching and the final video are done on the site; the full video
never travels to this machine. Long pieces (> 5 s) are several chained chunks inside ONE graph.

Once on this machine:

1. Nothing to type: `START.bat` fetches what the main Wan 2.2 engine still lacks (the fp8 high/low experts, umT5 and
   the VAE are skipped when ComfyUI already has them). The optional parts - the 4-step lightx2v LoRAs (2 × 1.1 GB) and
   Fun-InP 1.3B (2.9 GB) + CLIP-Vision-H (1.2 GB) - come from the panel: the node's card > «بسته‌های دیگر» > «دانلود».
2. ComfyUI must have `WanFirstLastFrameToVideo` (every ComfyUI that runs Wan 2.2 has it). The panel tab shows per model
   whether this node is ready (from the node list and model folders in the heartbeat).
3. The rendered frames stay in `ComfyUI\output\nmregen\` (~0.5 MB per frame) — delete that folder now and then.

Rough cost on an RTX 3060 12 GB (estimates until the first real runs; the panel then learns the real numbers):
A14B 480p, 4 steps ≈ 4–5 s per generated frame + ~2.5 min loading the two 14 GB experts; 720p ≈ 2.5× slower;
Fun-InP 1.3B ≈ 1.5 s per frame.

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
