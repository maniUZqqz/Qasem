"""Lip-sync: the person on screen says the narration with their own mouth.

For a scene marked «گوینده در تصویر» (`VideoScene.speaker_on_camera`), the
rendered segment and that scene's fitted narration go to ComfyUI, where
ByteDance's LatentSync 1.6 (custom node ComfyUI-LatentSyncWrapper) redraws the
mouth region frame by frame to match the audio. Everything else in the frame
is left as rendered.

Honest status: the workflow is built from the node's own source (inputs
`images, audio, seed, lips_expression, inference_steps`, outputs `images,
audio`) and the core ComfyUI video/audio nodes, and the plumbing is exercised
against the fake ComfyUI of the self-check — but it has not yet run on the real
GPU system. `manage.py lipsync_setup --check` there says whether the node and
its checkpoints are in place.

Three details that decide whether the result lines up:

* **Frame rate.** The node writes its frames as a 25 fps video internally, so
  it must RECEIVE 25 fps: Wan's 16 fps segment is converted to 25 fps before
  upload (frames repeated, timing unchanged), and the result is converted back
  to the segment's own rate and exact duration, so the final concatenation
  keeps its stream-copy path and its timing.
* **Length.** The narration was already fitted to the segment's real length by
  narration.narrate_scene, so audio and video match; the node needs no
  length adjuster.
* **Failure is per scene.** A scene that cannot be synced (no GPU, node not
  installed, no face found by the model) keeps its original picture and the
  voiced video says so — a lip-sync step must never cost the whole video.
"""
from __future__ import annotations

import logging
from pathlib import Path

from django.conf import settings

logger = logging.getLogger(__name__)

WORKFLOW = "latentsync"
NODE = "LatentSyncNode"
#: The frame rate LatentSync treats its input as (see the node's source:
#: it writes its frames with fps=25).
MODEL_FPS = 25


class LipSyncError(Exception):
    pass


def _conf(name: str, default):
    return settings.UPMARKET_AI.get(name, default)


def enabled() -> bool:
    return bool(_conf("LIPSYNC_ENABLED", True))


def node_available(client) -> tuple[bool, str]:
    """Is the LatentSync node loaded in this ComfyUI? (ok, reason when not)."""
    try:
        client._ensure_up()
    except Exception as exc:  # noqa: BLE001
        return False, f"ComfyUI در دسترس نیست: {exc}"[:200]
    present = client.has_node(NODE)
    if present is None:
        # گرهٔ راه‌دور فهرستِ نودهایش را نفرستاده — نمی‌توان مطمئن بود؛ خودِ کار اگر نود نباشد خطا می‌دهد
        return True, ""
    if not present:
        return False, (
            "نود لب‌خوانی (LatentSync) روی ComfyUI نصب نیست — "
            "start.bat نصبش را پیشنهاد می‌دهد، یا: python manage.py lipsync_setup"
        )
    return True, ""


def _to_rate(source: Path, out: Path, fps: float, duration: float | None = None) -> Path:
    from services.video.ffmpeg import FFMPEG, _run

    chain = f"fps={fps}"
    if duration:
        chain += f",tpad=stop_mode=clone:stop_duration={duration:.3f}"
    command = [FFMPEG, "-y", "-i", str(source), "-an", "-vf", chain]
    if duration:
        command += ["-t", f"{duration:.3f}"]
    command += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "16", "-preset", "medium", str(out)]
    _run(command)
    return out


def sync_segment(client, segment_video, narration_audio, work_dir, *, label: str, seed: int = 1247) -> Path:
    """One segment with its mouth redrawn to `narration_audio`. Raises LipSyncError."""
    from services.comfyui.workflows import load_workflow, patch_workflow
    from services.video.ffmpeg import FFMPEG, _run, probe_video

    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)
    source = probe_video(segment_video)
    fps = float(source.get("fps") or 16.0)
    duration = float(source.get("duration") or 0.0)

    at_model_rate = _to_rate(Path(segment_video), work / f"{label}_in25.mp4", MODEL_FPS)
    speech = work / f"{label}_voice.wav"
    _run([FFMPEG, "-y", "-i", str(narration_audio), "-ac", "1", "-ar", "16000", str(speech)])

    try:
        video_name = client.upload_image(at_model_rate)
        audio_name = client.upload_image(speech)
        graph, manifest = load_workflow(WORKFLOW, "v1")
        workflow = patch_workflow(
            graph, manifest,
            video=video_name, audio=audio_name, seed=seed, fps=MODEL_FPS,
            lips_expression=float(_conf("LIPSYNC_LIPS_EXPRESSION", 1.5)),
            inference_steps=int(_conf("LIPSYNC_STEPS", 20)),
            filename_prefix=f"upmarket/lipsync/segment_{label}",
        )
        synced = client.generate(workflow, work, filename=f"{label}_synced25.mp4")
    except Exception as exc:  # noqa: BLE001 — every ComfyUI failure is one scene's failure
        raise LipSyncError(str(exc)[:300]) from exc

    # The segment's exact length is not optional: the picture is re-assembled
    # from segments, and a synced scene one frame short would pull every later
    # scene — its narration, its effects — out of step with its sound.
    got = float(probe_video(synced).get("duration") or 0.0)
    if duration and got < duration * 0.9:
        raise LipSyncError(
            f"خروجی لب‌خوانی کوتاه‌تر از صحنه است ({got:.2f} از {duration:.2f} ثانیه)"
        )
    # Back to the segment's own rate, padded or cut to its exact length (the
    # last frame held for a few milliseconds at most), silent — the narration
    # is mixed in once, for the whole video, as before.
    return _to_rate(Path(synced), work / f"{label}_synced.mp4", fps, duration or None)


def apply(scenes, segment_paths: dict, narration_paths: dict, work_dir) -> tuple[dict, list[dict]]:
    """Lip-sync every scene marked `speaker_on_camera`.

    `segment_paths` and `narration_paths` map scene index → local file.
    Returns ({index: synced video}, report rows). Never raises.
    """
    wanted = [s for s in scenes if getattr(s, "speaker_on_camera", False)]
    report: list[dict] = []
    if not wanted:
        return {}, report
    if not enabled():
        return {}, [{"scene": s.index, "status": "off", "note": "لب‌خوانی در تنظیمات خاموش است"}
                    for s in wanted]

    from services import gpu
    from services.comfyui.client import ComfyUIClient

    client = ComfyUIClient()
    ok, why = node_available(client)
    if not ok:
        return {}, [{"scene": s.index, "status": "unavailable", "note": why} for s in wanted]

    try:
        gpu.before_comfyui_work()
    except Exception:  # noqa: BLE001 — freeing VRAM is best effort
        pass

    synced: dict = {}
    for scene in wanted:
        segment = segment_paths.get(scene.index)
        voice = narration_paths.get(scene.index)
        if segment is None or voice is None or not (getattr(scene, "narration", "") or "").strip():
            report.append({"scene": scene.index, "status": "skipped",
                           "note": "این صحنه ویدیو یا نریشن ندارد"})
            continue
        try:
            synced[scene.index] = sync_segment(
                client, segment, voice, work_dir, label=f"scene{scene.index}",
            )
            report.append({"scene": scene.index, "status": "done", "note": "لب‌ها با نریشن هماهنگ شد"})
        except (LipSyncError, Exception) as exc:  # noqa: BLE001
            logger.warning("Lip-sync failed for scene %s: %s", scene.index, exc)
            report.append({"scene": scene.index, "status": "failed",
                           "note": f"لب‌خوانی انجام نشد و تصویر اصلی ماند: {exc}"[:300]})
    return synced, report
