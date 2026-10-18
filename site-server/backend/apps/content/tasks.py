"""Celery tasks for the content domain.

Caption/script tasks run on the `ai` queue; video generation runs on the `gpu`
queue with concurrency 1 (see settings.CELERY_TASK_ROUTES).
"""
import contextlib
import logging
import random
from pathlib import Path

from celery import shared_task
from django.conf import settings

from apps.ai.models import AIRequest, ProductIntelligence
from apps.ai.services import recorded_json_call
from apps.jobs.models import Job
from apps.products.models import Product
from services import gpu
from apps.billing import credits
from apps.billing import services as billing
from apps.billing.models import Usage
from services.ai import providers
from services.ai.gateway import text_provider
from services.ai.prompts import captions as caption_prompts
from services.ai.prompts import image_studio as image_prompts
from services.ai.prompts import video_script as script_prompts
from services.ai.router import TASK_REASONING, models_for
from services.audio import narration, soundscape
from services.audio.tts import get_tts_provider
from services.comfyui.client import ComfyUIClient
from services.comfyui.workflows import load_workflow, patch_workflow
from services.imaging.preprocess import prepare_source_image
from services.media import files as media
from apps.jobs import metrics
from apps.jobs.metrics import RenderMetric
from services.video import anchor as video_anchor
from services.video import qc, repair, repurpose, scene_state
from services.video.ffmpeg import (
    concat_audio,
    concat_videos,
    extract_last_frame,
    mix_audio,
    probe_duration,
)

from .models import (
    Caption,
    GeneratedImage,
    VideoCut,
    VideoScene,
    VideoScript,
    VideoSegment,
)

logger = logging.getLogger(__name__)

NEGATIVE_PROMPT = (
    "blurry, low quality, distorted, deformed, text, letters, words, writing, "
    "typography, captions, arabic script, gibberish letters, watermark, logo overlay"
)
WAN_FPS = 16


def _media_rel(path: Path) -> str:
    """Path under MEDIA_ROOT → relative name usable in a FileField."""
    return media.media_rel(path)


def _caption_subject(product, image_id, video_script_id):
    """Resolve the content item this caption is about (beter.md #11)."""
    about_image = about_video = None
    subject = None
    if image_id:
        about_image = GeneratedImage.objects.filter(product=product, id=image_id).first()
        if about_image:
            subject = {
                "type": "image",
                "kind": about_image.kind,
                "concept": about_image.concept,
                "style": about_image.style,
                "instructions": about_image.instructions,
            }
    elif video_script_id:
        about_video = (
            VideoScript.objects.filter(product=product, id=video_script_id)
            .prefetch_related("scenes")
            .first()
        )
        if about_video:
            subject = {
                "type": "video",
                "concept": about_video.concept,
                "cta": about_video.cta,
                "duration": about_video.total_duration,
                "narrations": [
                    s.narration for s in about_video.scenes.all() if s.narration.strip()
                ],
            }
    return about_image, about_video, subject


@shared_task(bind=True)
def generate_captions_task(
    self, job_id, product_id, platforms, tone="", objective="", image_id=None, video_script_id=None
):
    job = Job.objects.get(id=job_id)
    try:
        product = (
            Product.objects.select_related("store").prefetch_related("attributes").get(id=product_id)
        )
        intelligence = ProductIntelligence.objects.filter(product=product).first()
        requested = [p for p in (platforms or []) if p in caption_prompts.PLATFORMS] or [
            "INSTAGRAM",
            "TELEGRAM",
            "LINKEDIN",
        ]
        about_image, about_video, subject = _caption_subject(product, image_id, video_script_id)
        job.total_steps = 1
        job.mark_running("در حال نوشتن کپشن‌ها")
        reasoning_models = models_for(TASK_REASONING)
        gpu.before_ollama_work(reasoning_models[0])

        provider = text_provider(product.store)
        parsed, request_row = recorded_json_call(
            job=job,
            store=product.store,
            task_type=AIRequest.TaskType.REASONING,
            prompt_id=caption_prompts.CAPTIONS_PROMPT_ID,
            prompt_version=caption_prompts.CAPTIONS_PROMPT_VERSION,
            provider=provider,
            models=reasoning_models,
            prompt=caption_prompts.build_captions_prompt(
                product, intelligence, requested, tone, objective, subject
            ),
            system=caption_prompts.CAPTIONS_SYSTEM,
            # validated inside the call: an incomplete answer moves on to the
            # next installed model instead of failing the job
            validate=lambda parsed: caption_prompts.validate_captions(parsed, set(requested)),
            validation_message="خروجی کپشن ناقص بود",
        )

        created_ids = []
        for item in parsed["captions"]:
            caption = Caption.objects.create(
                store=product.store,
                product=product,
                platform=item["platform"],
                tone=tone,
                objective=objective,
                short_text=item["short"],
                medium_text=item["medium"],
                long_text=item["long"],
                hashtags=item["hashtags"],
                cta=item["cta"],
                about_image=about_image,
                about_video=about_video,
                source_request=request_row,
            )
            created_ids.append(caption.id)

        if created_ids:
            billing.commit(
                billing.reserve(
                    product.store, Usage.Metric.CAPTIONS, len(created_ids), job=job,
                    detail=f"product {product.id}",
                    external=not providers.uses_own_gpu(providers.TEXT),
                )
            )

        job.mark_progress(1, "")
        job.mark_completed({"caption_ids": created_ids})
        return {"caption_ids": created_ids}
    except Exception as exc:  # noqa: BLE001
        logger.exception("Caption job %s failed", job_id)
        job.mark_failed(exc)
        return {"error": str(exc)}


@shared_task(bind=True)
def generate_video_script_task(self, job_id, product_id, total_duration=30, objective="", language="fa"):
    job = Job.objects.get(id=job_id)
    try:
        product = (
            Product.objects.select_related("store").prefetch_related("attributes").get(id=product_id)
        )
        intelligence = ProductIntelligence.objects.filter(product=product).first()
        segment_duration = settings.UPMARKET_AI["VIDEO_SEGMENT_DURATION"]
        job.total_steps = 1
        job.mark_running("در حال نوشتن سناریوی ویدیو")
        reasoning_models = models_for(TASK_REASONING)
        gpu.before_ollama_work(reasoning_models[0])

        provider = text_provider(product.store)
        parsed, request_row = recorded_json_call(
            job=job,
            store=product.store,
            task_type=AIRequest.TaskType.REASONING,
            prompt_id=script_prompts.VIDEO_SCRIPT_PROMPT_ID,
            prompt_version=script_prompts.VIDEO_SCRIPT_PROMPT_VERSION,
            provider=provider,
            models=reasoning_models,
            prompt=script_prompts.build_video_script_prompt(
                product, intelligence, int(total_duration), segment_duration, objective, language
            ),
            system=script_prompts.VIDEO_SCRIPT_SYSTEM,
            validate=lambda parsed: script_prompts.validate_video_script(
                parsed, segment_duration
            ),
            validation_message="سناریوی ویدیو ناقص بود",
        )

        script = VideoScript.objects.create(
            store=product.store,
            product=product,
            concept=str(parsed.get("concept", "")),
            objective=objective,
            cta=str(parsed.get("cta", "")),
            total_duration=sum(s["duration"] for s in parsed["scenes"]),
            narration_language=language if language in {"fa", "en"} else "fa",
            raw=parsed,
            source_request=request_row,
        )
        for scene in parsed["scenes"]:
            VideoScene.objects.create(script=script, **scene)

        job.mark_progress(1, "")
        job.mark_completed({"script_id": script.id, "scene_count": len(parsed["scenes"])})
        return {"script_id": script.id}
    except Exception as exc:  # noqa: BLE001
        logger.exception("Video script job %s failed", job_id)
        job.mark_failed(exc)
        return {"error": str(exc)}


IMAGE_DIMENSIONS = {
    "POSTER": (832, 1216),  # portrait 2:3-ish for feed/poster
    "PRODUCT_SHOT": (1024, 1024),
    "ENHANCED": (1024, 1024),
}
# All kinds edit the REAL product photo when one exists (beter.md #4: the
# generated product must be OUR product, not an invented one). POSTER keeps a
# higher denoise for creative composition while the product stays anchored.
EDIT_DENOISE = {"ENHANCED": 0.45, "PRODUCT_SHOT": 0.7, "POSTER": 0.75}


@shared_task(bind=True)
def generate_image_task(self, job_id, product_id, kind, style="", instructions="", source_image_id=None):
    """Image Studio (Phase 9): QwQ creative direction → FLUX via ComfyUI."""
    job = Job.objects.get(id=job_id)
    try:
        product = (
            Product.objects.select_related("store")
            .prefetch_related("attributes", "images")
            .get(id=product_id)
        )
        if kind not in GeneratedImage.Kind.values:
            raise RuntimeError(f"نوع تصویر نامعتبر: {kind}")
        intelligence = ProductIntelligence.objects.filter(product=product).first()
        job.total_steps = 2
        job.mark_running("در حال طراحی کانسپت تصویر")
        reasoning_models = models_for(TASK_REASONING)
        gpu.before_ollama_work(reasoning_models[0])

        provider = text_provider(product.store)
        parsed, request_row = recorded_json_call(
            job=job,
            store=product.store,
            task_type=AIRequest.TaskType.REASONING,
            prompt_id=image_prompts.IMAGE_PROMPT_ID,
            prompt_version=image_prompts.IMAGE_PROMPT_VERSION,
            provider=provider,
            models=reasoning_models,
            prompt=image_prompts.build_image_prompt(product, intelligence, kind, style, instructions),
            system=image_prompts.IMAGE_SYSTEM,
            validate=image_prompts.validate_image,
            validation_message="طراحی کانسپت تصویر ناقص بود",
        )

        source_image = None
        if source_image_id:
            source_image = product.images.filter(id=source_image_id).first()
        if source_image is None and kind in EDIT_DENOISE:
            source_image = product.images.first()
        use_edit = kind in EDIT_DENOISE and source_image is not None

        job.mark_progress(1, "در حال تولید تصویر با FLUX")
        # reserved now, committed only if a file actually lands on disk
        quota = billing.reserve(
            product.store, Usage.Metric.IMAGES, 1, job=job,
            detail=f"{kind} · product {product.id}",
            external=not providers.uses_own_gpu(providers.IMAGE),
        )
        gpu.before_comfyui_work()  # evict Ollama models so FLUX has the VRAM
        client = ComfyUIClient()
        out_dir = Path(settings.MEDIA_ROOT) / "generated" / "images"
        width, height = IMAGE_DIMENSIONS[kind]
        # the model's negatives PLUS our hard text ban (Persian text is drawn by code)
        negative = ", ".join(
            part for part in [parsed["negative_en"], NEGATIVE_PROMPT] if part
        )
        seed = random.randint(1, 2**31)
        prefix = f"upmarket/images/product_{product.id}"

        if use_edit:
            graph, manifest = load_workflow("flux_img_edit", "v1")
            # img2img inherits the input's quality, so the owner's phone photo
            # is upscaled/normalised first instead of being blown up by the
            # sampler (beter.md v2 #4)
            # `media.reading` rather than `.path`: on S3 the latter raises,
            # and this is the line a shop would hit first after the switch.
            with media.reading(source_image.image) as source_path:
                prepared = prepare_source_image(
                    source_path,
                    Path(settings.MEDIA_ROOT) / "generated" / "sources"
                    / f"product_{product.id}_src_{source_image.id}_{width}x{height}.png",
                    width,
                    height,
                )
            uploaded = client.upload_image(prepared)
            patched = patch_workflow(
                graph,
                manifest,
                image=uploaded,
                positive=parsed["prompt_en"],
                negative=negative,
                seed=seed,
                denoise=EDIT_DENOISE[kind],
                width=width,
                height=height,
                filename_prefix=prefix,
            )
            workflow_version = "flux_img_edit@v1"
        else:
            graph, manifest = load_workflow("flux_txt2img", "v1")
            patched = patch_workflow(
                graph,
                manifest,
                positive=parsed["prompt_en"],
                negative=negative,
                seed=seed,
                width=width,
                height=height,
                filename_prefix=prefix,
            )
            workflow_version = "flux_txt2img@v1"

        image_path = client.generate(patched, out_dir)

        # beter.md #4b: Persian text is NEVER left to the diffusion model —
        # for posters the real headline/price is drawn by code (Pillow + RTL).
        overlay_meta = {}
        if kind == GeneratedImage.Kind.POSTER:
            headline = parsed.get("headline_fa") or product.name
            subline = parsed.get("subline_fa") or ""
            try:
                from services.imaging.text_overlay import add_poster_text, format_price_fa

                badge = format_price_fa(product.price, product.currency)

                overlaid = Path(image_path).with_name(Path(image_path).stem + "_text.png")
                add_poster_text(image_path, overlaid, headline, subline, badge)
                image_path = overlaid
                overlay_meta = {
                    "text_overlay": {"headline": headline, "subline": subline, "badge": badge}
                }
            except Exception as exc:  # the poster is still usable without text
                logger.warning("Poster text overlay failed: %s", exc)
                overlay_meta = {"text_overlay_error": str(exc)[:300]}

        generated = GeneratedImage.objects.create(
            store=product.store,
            product=product,
            kind=kind,
            concept=parsed["concept_fa"],
            prompt_en=parsed["prompt_en"],
            negative_en=negative,
            style=style,
            instructions=instructions,
            source_image=source_image if use_edit else None,
            workflow_version=workflow_version,
            source_request=request_row,
            metadata={"seed": seed, "width": width, "height": height, **overlay_meta},
        )
        media.store(generated.image, image_path)
        generated.save()

        billing.commit(quota)  # a real file exists — now it counts
        job.mark_progress(2, "")
        job.mark_completed({"image_id": generated.id, "image_url": generated.image.url})
        return {"image_id": generated.id}
    except Exception as exc:  # noqa: BLE001
        logger.exception("Image generation job %s failed", job_id)
        billing.release(locals().get("quota"), reason=type(exc).__name__)
        job.mark_failed(exc)
        return {"error": str(exc)}


@shared_task(bind=True)
def generate_voice_task(self, job_id, script_id):
    """Voice-over (Phase 13): per-scene TTS → timing-aware alignment → mix onto video."""
    job = Job.objects.get(id=job_id)
    try:
        script = VideoScript.objects.select_related("product", "store").get(id=script_id)
        if not script.final_video:
            raise RuntimeError("اول باید ویدیوی نهایی تولید شده باشد.")
        scenes = list(script.scenes.all())
        if not any(scene.narration.strip() for scene in scenes):
            raise RuntimeError("هیچ‌کدام از صحنه‌ها نریشن ندارند.")
        # align narration to the ACTUAL generated segment durations (Wan produces
        # duration + 1/16s per segment), so audio never drifts or truncates video
        done_segments = {
            s.index: s for s in script.segments.filter(status=VideoSegment.Status.DONE)
        }

        # the voice must match the language the narration was written in, and
        # the store must allow the narration text to reach an external voice
        tts = get_tts_provider(
            language=script.narration_language or "fa", store=script.store,
        )
        out_dir = Path(settings.MEDIA_ROOT) / "generated" / "audio" / f"script_{script.id}"
        out_dir.mkdir(parents=True, exist_ok=True)
        job.total_steps = len(scenes) + 2
        job.mark_running("در حال تولید صدا")

        scene_clips = []
        takes = []
        durations = []
        for step, scene in enumerate(scenes, start=1):
            job.mark_progress(step, f"صداگذاری صحنه {scene.index} از {len(scenes)}")
            fitted = out_dir / f"scene_{scene.index}.m4a"
            segment = done_segments.get(scene.index)
            target_duration = scene.duration
            if segment is not None and segment.video:
                try:
                    with media.reading(segment.video) as segment_path:
                        target_duration = probe_duration(segment_path)
                except Exception:  # fall back to the planned duration
                    target_duration = scene.duration
            durations.append(float(target_duration))
            # §7 in one call: spoken-form rewrite, length fitted to the real
            # segment, scored, and resynthesised if it came out badly.
            takes.append(narration.narrate_scene(
                tts=tts,
                text=scene.narration,
                target_duration=target_duration,
                out_path=fitted,
                work_dir=out_dir / "takes",
                store=script.store,
                job=job,
                scene_label=f"صحنه {scene.index}",
            ))
            scene_clips.append(fitted)

        audio_quality = narration.summarize(takes)
        warnings = list(audio_quality["warnings"])
        speaker = tts.describe()
        warnings += list(speaker.get("notes") or [])

        # Say the product's name when the product is on screen: each scene's
        # narration is moved later inside its own scene (same length, silence
        # moved from the end to the start) so that the first mention lands
        # just after the product appears. Before lip-sync, so lips follow the
        # moved words; the subtitles are timed from these same files.
        timing_rows: list[dict] = []
        if settings.UPMARKET_AI.get("NARRATION_FOLLOWS_PRODUCT", True):
            from services.audio import timing

            job.mark_progress(len(scenes) + 1, "در حال هماهنگ‌کردن نریشن با تصویر محصول")
            names = [script.product.name, scene_state.english_name(script.product) or ""]
            product_image = script.product.images.first()
            with contextlib.ExitStack() as stack:
                photo = (
                    stack.enter_context(media.reading(product_image.image))
                    if product_image is not None and product_image.image else None
                )
                for scene, take, clip, length in zip(scenes, takes, scene_clips, durations):
                    segment = done_segments.get(scene.index)
                    if take.silent or not take.spoken_text or segment is None or not segment.video:
                        continue
                    try:
                        video = stack.enter_context(media.reading(segment.video))
                        plan = timing.plan(
                            video, photo, clip, take.spoken_text, names, length,
                            script.narration_language or "fa",
                        )
                        if plan.shift:
                            timing.shift_clip(clip, plan.shift, length)
                        timing_rows.append({"scene": scene.index, **plan.as_dict()})
                    except Exception as exc:  # noqa: BLE001 — timing is an improvement
                        logger.info("Narration timing skipped for scene %s: %s", scene.index, exc)

        # Scenes where the person SPEAKS the narration: their mouth is redrawn
        # to it (LatentSync on ComfyUI) and the picture is re-assembled from
        # the synced segments. A scene that cannot be synced keeps its
        # original picture; the result says which and why.
        picture_path = None
        lipsync_rows: list[dict] = []
        if any(scene.speaker_on_camera for scene in scenes):
            from services.video import lipsync

            job.mark_progress(len(scenes) + 1, "در حال هماهنگ‌کردن لب‌ها با نریشن")
            with contextlib.ExitStack() as stack:
                segment_paths = {}
                for scene in scenes:
                    segment = done_segments.get(scene.index)
                    if segment is not None and segment.video:
                        segment_paths[scene.index] = stack.enter_context(media.reading(segment.video))
                narration_paths = {scene.index: clip for scene, clip in zip(scenes, scene_clips)}
                synced, lipsync_rows = lipsync.apply(
                    scenes, segment_paths, narration_paths, out_dir / "lipsync",
                )
                if synced:
                    parts = [synced.get(scene.index) or segment_paths.get(scene.index) for scene in scenes]
                    if all(parts):
                        picture_path = concat_videos(parts, out_dir / "picture_lipsynced.mp4")
                    else:
                        warnings.append("همه‌ی تکه‌های ویدیو در دسترس نبود؛ لب‌خوانی روی ویدیو اعمال نشد")
            warnings += [row["note"] for row in lipsync_rows if row["status"] not in ("done",)]

        job.mark_progress(len(scenes) + 1, "در حال ساخت صدای محیط و افکت‌ها")
        voice_path = concat_audio(scene_clips, out_dir / "voice.m4a")

        # Everything that is not the voice: ambience per scene and effects on
        # the moments that call for one, mixed under the narration and ducked
        # while it speaks. A failure here costs the ambience, never the video.
        context = job.context or {}
        mixed_path = voice_path
        design = {"voice": speaker, "soundscape": None}
        try:
            # The rendered video goes in too: each effect is moved onto the
            # frame where its action happens, not the time the script guessed.
            with (contextlib.nullcontext(picture_path) if picture_path
                  else media.reading(script.final_video)) as rendered:
                scape = soundscape.build(
                    scenes, durations, out_dir / "soundscape.wav", out_dir / "sound_work",
                    store=script.store, seed=f"script-{script.id}",
                    ambience=bool(context.get("ambience", True)),
                    effects=bool(context.get("effects", True)),
                    video=rendered,
                )
            design["soundscape"] = scape.as_dict()
            if scape.missing:
                warnings.append(
                    "برای این صداها فایلی پیدا نشد و جایشان خالی ماند: "
                    + "، ".join(dict.fromkeys(scape.missing))
                )
            if scape.path is not None:
                mixed_path = soundscape.under_voice(voice_path, scape.path, out_dir / "voice_mix.wav")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Soundscape for script %s failed: %s", script.id, exc)
            warnings.append(f"صدای محیط ساخته نشد و ویدیو فقط با صدای گوینده است: {exc}"[:300])

        job.mark_progress(len(scenes) + 1, "در حال ترکیب صدا با ویدیو")
        with (contextlib.nullcontext(picture_path) if picture_path
              else media.reading(script.final_video)) as final_path:
            voiced_path = mix_audio(
                final_path, mixed_path, out_dir.parent.parent / "videos" /
                f"script_{script.id}" / "final_voiced.mp4"
            )

        media.store(script.voice_audio, voice_path)
        media.store(script.final_video_voiced, voiced_path)
        # Saved with the video, not only in the job result: the score and the
        # warnings (a brand name read letter by letter, a scene squeezed to
        # fit) are what the shop needs next to the player, on any later visit.
        design["quality"] = {k: v for k, v in audio_quality.items() if k != "warnings"}
        design["lipsync"] = lipsync_rows
        design["timing"] = timing_rows
        design["warnings"] = list(dict.fromkeys(warnings))[:20]
        script.sound_design = design
        script.save(update_fields=["voice_audio", "final_video_voiced", "sound_design", "updated_at"])

        job.mark_progress(len(scenes) + 2, "")
        job.mark_completed(
            {
                "script_id": script.id,
                "voiced_video": script.final_video_voiced.url,
                "warnings": warnings,
                # The score travels with the result so the panel can show it
                # next to the video QC number instead of the shop discovering
                # the narration is unlistenable by pressing play.
                "audio_quality": audio_quality,
                "sound_design": design,
            }
        )
        return {
            "script_id": script.id,
            "warnings": warnings,
            "audio_quality": audio_quality,
            "sound_design": design,
        }
    except Exception as exc:  # noqa: BLE001
        logger.exception("Voice job %s failed", job_id)
        job.mark_failed(exc)
        return {"error": str(exc)}


#: How much a NEW_SCENE anchor may depart from the product photo it is built
#: from. High enough for a new setting and framing, low enough that the object
#: in the middle is still the customer's object.
ANCHOR_DENOISE = 0.7


def _flux_anchor(client, scene, out_dir, *, product_image_path=None, state=None,
                 product_name: str = ""):
    """A fresh FLUX anchor image for a NEW_SCENE cut, at video resolution.

    Image-conditioned on the PRODUCT PHOTO whenever there is one. A text-only
    render re-invents the product from words at every hard cut — a different
    shape, a different colour, a different logo — and the continuity chain
    then faithfully carries that new object through every following segment.
    Editing the real photo keeps the object and changes the scene around it,
    which is what a "new scene" means.
    """
    positive, negative = scene_state.compile_prompt(
        scene, state, product_name=product_name, base_negative=NEGATIVE_PROMPT,
    )
    seed = random.randint(1, 2**31)
    if product_image_path and Path(product_image_path).exists():
        graph, manifest = load_workflow("flux_img_edit", "v1")
        prepared = prepare_source_image(
            product_image_path, Path(out_dir) / f"anchor_{scene.index}_src.png", 832, 480,
        )
        uploaded = client.upload_image(prepared)
        patched = patch_workflow(
            graph,
            manifest,
            image=uploaded,
            positive=positive,
            negative=negative,
            seed=seed,
            denoise=ANCHOR_DENOISE,
            width=832,
            height=480,
            filename_prefix=f"upmarket/anchors/scene_{scene.index}",
        )
    else:
        graph, manifest = load_workflow("flux_txt2img", "v1")
        patched = patch_workflow(
            graph,
            manifest,
            positive=positive,
            negative=negative,
            seed=seed,
            width=832,
            height=480,
            filename_prefix=f"upmarket/anchors/scene_{scene.index}",
        )
    return client.generate(patched, out_dir, filename=f"anchor_{scene.index}.png")


def _should_pause(job, segment) -> bool:
    """Does this finished segment need a person to look at it?

    This is the whole difference between the two modes, and the reason the
    default is Safe: a shop owner rendering their first video should find out
    the result is wrong after five seconds of GPU, not after forty.

    Auto does not mean "never stop". It means "stop only when the output looks
    bad", and "bad" is the QC **verdict** — REVIEW or REGENERATE — not a
    separate fraction that could disagree with it (0.6 used to let a segment
    labelled REGENERATE at 65 sail through).

    Two more rules. A report that could not be produced at all (no frames,
    ffmpeg missing) is a system problem, not a verdict, and does not park the
    job on every segment. And a report the vision model never saw — no local
    model, LOCAL_ONLY policy, a timeout — is *half* a verdict: the code axes
    are ~100 on almost every render, so Auto would run to the end with the
    product never checked. That case parks once per job, on its first such
    segment, and says why.
    """
    if job.mode == Job.Mode.SAFE:
        return True

    report = (segment.metadata or {}).get("qc") or {}
    if not report or report.get("error") or not report.get("axes"):
        # No judge. Not "it passed" — "nobody looked", and not the shop's problem.
        return False

    if report.get("verdict") in ("REVIEW", "REGENERATE"):
        return True

    score = (segment.metadata or {}).get("quality_score")
    threshold = float(settings.UPMARKET_AI.get("QUALITY_PAUSE_THRESHOLD", 0.7))
    if score is not None and float(score) < threshold:
        return True

    if not report.get("vision_checked"):
        context = dict(job.context or {})
        if not context.get("code_only_checkpoint_done"):
            context["code_only_checkpoint_done"] = True
            job.context = context
            job.save(update_fields=["context", "updated_at"])
            return True
    return False


def _quality_preview(segment) -> dict:
    """The QC summary the approval card shows next to the clip."""
    meta = segment.metadata or {}
    report = meta.get("qc") or {}
    return {
        "overall": report.get("overall"),
        "verdict": report.get("verdict"),
        "vision_checked": report.get("vision_checked", False),
        "vision_reason": report.get("vision_reason", ""),
        "problems": [
            axis for axis in report.get("axes", [])
            if axis.get("note") or (axis.get("score") or 100) < 80
        ],
        "repaired": (meta.get("code_repair") or {}).get("applied") or [],
        "plan": meta.get("repair_plan"),
        "attempts": len(meta.get("attempts") or []),
        "original_video": meta.get("original_video"),
    }


def _original_url(path) -> str | None:
    """A media URL for a pre-repair file, when local storage can serve it."""
    if path is None or media.is_shared():
        return None
    try:
        return f"{settings.MEDIA_URL}{media.media_rel(Path(path))}"
    except Exception:  # noqa: BLE001 — a missing URL is not worth a failed job
        return None


def _anchor_for_segment(scene, previous_frame_path, product_image_path, segment, client, out_dir,
                        *, state=None, product_name: str = ""):
    """Choose the real anchor image for a segment, recording its origin."""
    if scene.index == 1 or previous_frame_path is None:
        segment.anchor_source = "product_image"
        return product_image_path
    if scene.transition == VideoScene.Transition.NEW_SCENE:
        try:
            anchor = _flux_anchor(
                client, scene, out_dir, product_image_path=product_image_path,
                state=state, product_name=product_name,
            )
            segment.anchor_source = (
                "flux_new_scene (from product photo)" if product_image_path else "flux_new_scene"
            )
            return anchor
        except Exception as exc:  # degrade honestly, keep the pipeline going
            logger.warning("NEW_SCENE FLUX anchor failed, using previous frame: %s", exc)
            segment.anchor_source = "previous_frame (NEW_SCENE degraded)"
            segment.metadata = {**segment.metadata, "new_scene_degraded": str(exc)[:300]}
            return previous_frame_path
    segment.anchor_source = "previous_frame"
    return previous_frame_path


@shared_task(bind=True)
def generate_video_task(self, job_id, script_id):
    """Segment-by-segment Wan 2.2 generation with last-frame continuity (Phase 12)."""
    job = Job.objects.get(id=job_id)
    script = None
    # Holds the product photo open for the whole render. On local storage that
    # is the file itself; on S3 it is one download reused by every segment,
    # rather than one per segment.
    open_media = contextlib.ExitStack()
    try:
        script = VideoScript.objects.select_related("product", "store").get(id=script_id)
        scenes = list(script.scenes.all())
        if not scenes:
            raise RuntimeError("سناریو هیچ صحنه‌ای ندارد.")
        product_image = script.product.images.first()
        if product_image is None:
            raise RuntimeError("برای تولید ویدیو حداقل یک عکس محصول لازم است.")
        product_image_path = open_media.enter_context(
            media.reading(product_image.image)
        )

        # one segment row per scene; completed segments are never regenerated
        for scene in scenes:
            VideoSegment.objects.get_or_create(script=script, index=scene.index)
        segments = {s.index: s for s in script.segments.all()}

        script.status = VideoScript.Status.GENERATING
        script.save(update_fields=["status", "updated_at"])
        job.total_steps = len(scenes) + 1
        job.advance(Job.State.PROCESSING, label="آماده‌سازی تولید ویدیو")

        # Billed per segment, not per script.
        #
        # A single up-front reservation for the whole video would sit on the
        # store's allowance for as long as the job is parked waiting for
        # approval — possibly overnight. Worse, a shop that looks at the first
        # five seconds and walks away would have reserved forty. Reserving one
        # segment at a time means an abandoned job has paid for exactly what
        # the owner actually saw.
        external_render = not providers.uses_own_gpu(providers.VIDEO)

        out_dir = Path(settings.MEDIA_ROOT) / "generated" / "videos" / f"script_{script.id}"
        out_dir.mkdir(parents=True, exist_ok=True)
        gpu.before_comfyui_work()  # evict Ollama models so Wan 2.2 has the VRAM
        client = ComfyUIClient()
        graph_template, manifest = load_workflow("wan22_i2v", "v1")

        # What every segment of THIS product must keep, before the script says
        # anything: the product and its colour. Without it a script that
        # returns no per-scene state — the common case with small local
        # models — leaves the continuity clause empty and "the same handbag"
        # becomes "a handbag" between segments one and two.
        product_state = scene_state.base_state(script.product)
        product_name = scene_state.english_name(script.product) or "product"
        auto_attempts = max(1, int(settings.UPMARKET_AI.get("SEGMENT_AUTO_ATTEMPTS", 2)))

        previous_frame_path = None
        previous_state = None
        for step, scene in enumerate(scenes, start=1):
            segment = segments[scene.index]
            if segment.status == VideoSegment.Status.DONE and segment.last_frame:
                previous_frame_path = Path(segment.last_frame.path)
                # Continue from the state this segment RENDERED with, not from
                # what the script planned: a resumed job should continue the
                # video that exists.
                previous_state = scene_state.SceneState.from_dict(segment.scene_state)
                job.mark_progress(step, f"قطعه {scene.index} از قبل آماده است")
                continue

            # Checkpoint before spending GPU on the next five seconds. A
            # Celery task cannot be killed reliably, so it has to ask.
            if job.cancel_pending():
                logger.info("Job %s stopping before segment %s (cancelled)", job.id, scene.index)
                return {"script_id": script.id, "cancelled_at_segment": scene.index}

            job.mark_progress(step, f"در حال تولید قطعه {scene.index} از {len(scenes)}")

            # A segment the owner sent back ("دوباره بساز") carries what QC or
            # the owner said was wrong, and the usage row of the render that
            # was refunded. The prompt is compiled around those causes and the
            # new reservation is linked to the old one, so the quality
            # guarantee counts the attempts as one chain.
            history = list((segment.metadata or {}).get("attempts") or [])
            regen = dict((segment.metadata or {}).get("regen") or {})
            hints = [str(c).upper() for c in (regen.get("causes") or []) if c]
            quota = None
            previous_usage = None
            if regen.get("usage_id"):
                previous_usage = Usage.objects.filter(pk=regen["usage_id"]).first()
            if previous_usage is not None:
                quota, chain = credits.reserve_retry(
                    previous_usage, job=job,
                    detail=f"script {script.id} · قطعه {scene.index} · تلاش {len(history) + 1}",
                )
                if chain.get("free"):
                    job.mark_progress(step, chain.get("message") or "این تلاش رایگان است")
            else:
                quota = billing.reserve(
                    script.store, Usage.Metric.VIDEO_SECONDS, int(scene.duration), job=job,
                    detail=f"script {script.id} · قطعه {scene.index}",
                    external=external_render,
                )
            segment.status = VideoSegment.Status.GENERATING
            segment.error = ""
            state = scene_state.from_scene(scene, previous_state or product_state)
            anchor_path = _anchor_for_segment(
                scene, previous_frame_path, product_image_path, segment, client, out_dir,
                state=state, product_name=product_name,
            )
            segment.save()
            # Safe mode renders once and asks; Auto mode may re-roll a segment
            # QC rejects, a bounded number of times, and keeps the best.
            attempt_limit = auto_attempts if job.mode == Job.Mode.AUTO else 1
            best = None
            try:
                uploaded_name = client.upload_image(anchor_path)
                for attempt in range(1, attempt_limit + 1):
                    attempt_no = len(history) + attempt
                    # The last frame carries what one instant looked like; the
                    # state carries what the scene IS; the anchors carry what
                    # every clip needs; the hints carry what went wrong last
                    # time. All four, or the jacket changes colour halfway.
                    positive, negative = scene_state.compile_prompt(
                        scene, state, product_name=product_name, hints=hints,
                        attempt=attempt_no, base_negative=NEGATIVE_PROMPT,
                    )
                    seed = random.randint(1, 2**31)
                    patched = patch_workflow(
                        graph_template,
                        manifest,
                        image=uploaded_name,
                        positive=positive,
                        negative=negative,
                        length=scene.duration * WAN_FPS + 1,
                        seed=seed,
                        filename_prefix=f"upmarket/script_{script.id}/segment_{scene.index}",
                    )
                    rendered_name = (
                        f"segment_{scene.index}.mp4" if attempt_no == 1
                        else f"segment_{scene.index}_a{attempt_no}.mp4"
                    )
                    # Measure every render, each attempt on its own row. Phase
                    # 0.5 needs real numbers, and a benchmark that only exists
                    # when someone remembers to run it is a benchmark that
                    # stays unrun.
                    measurement = metrics.measured(
                        RenderMetric.Kind.VIDEO_SEGMENT,
                        "wan22_i2v@v1",
                        output_units=scene.duration,
                        job=job,
                        store=script.store,
                        context={
                            "segment_index": scene.index, "script_id": script.id,
                            "attempt": attempt_no,
                        },
                    )
                    with measurement:
                        video_path = client.generate(patched, out_dir, filename=rendered_name)

                    # Look at what came out, before the customer does. Everything
                    # the code layer can fix gets fixed here — a colour curve costs
                    # two seconds of CPU, a re-render costs minutes of the one GPU.
                    # Lips: a voice-over scene with a person in it must not
                    # show them talking. A lip-sync scene is exempt — its
                    # mouth is redrawn to the narration afterwards.
                    watch_mouth = scene_state.has_people(scene, state) and not getattr(
                        scene, "speaker_on_camera", False,
                    )
                    report = qc.check_segment(
                        video_path,
                        out_dir,
                        store=script.store,
                        product_image_path=product_image_path,
                        scene_note=scene.visual_prompt,
                        job=job,
                        mouth_check=watch_mouth,
                    )
                    decision = repair.decide(report)
                    original_path = None
                    report_before = None
                    code_repair = None
                    if decision.action == repair.CODE_REPAIR:
                        fixed = repair.repair_with_code(
                            video_path, decision,
                            Path(video_path).with_name(f"{Path(video_path).stem}_fixed.mp4"),
                        )
                        code_repair = fixed.as_dict()
                        if fixed.repaired:
                            # Re-check the corrected file with the vision verdicts
                            # carried over: a colour curve cannot change whose
                            # face it is, and dropping those axes used to turn a
                            # 77 into a 100.
                            after = qc.check_segment(
                                fixed.path, out_dir, store=script.store,
                                product_image_path=product_image_path,
                                scene_note=scene.visual_prompt, job=job,
                                use_vision=False, reuse_vision=report,
                                mouth_check=watch_mouth,
                            )
                            kept, why = repair.kept_the_repair(report, after, decision.causes)
                            if kept:
                                original_path = video_path
                                report_before = report
                                video_path = fixed.path
                                report = after
                            else:
                                code_repair = {**code_repair, "repaired": False, "note": why}
                        decision = repair.decide(report)

                    candidate = {
                        "attempt": attempt_no,
                        "seed": seed,
                        "positive": positive,
                        "negative": negative,
                        "video_path": video_path,
                        "original_path": original_path,
                        "report": report,
                        "report_before": report_before,
                        "code_repair": code_repair,
                        "decision": decision,
                    }
                    history.append({
                        "attempt": attempt_no,
                        "seed": seed,
                        "file": media.media_rel(Path(video_path)),
                        "overall": report.as_dict()["overall"],
                        "verdict": report.verdict,
                        "causes": list(decision.causes),
                        "hints": list(hints),
                        "positive": positive,
                    })
                    if best is None or report.overall > best["report"].overall:
                        best = candidate

                    if decision.action != repair.REGENERATE:
                        break
                    # QC says only a re-render can fix this. Re-roll if this run
                    # may, with the prompt compiled around the causes; otherwise
                    # keep the best so far and let a person decide.
                    if attempt >= attempt_limit or job.cancel_pending():
                        break
                    hints = list(dict.fromkeys([*hints, *decision.causes]))
                    if quota is not None:
                        # The GPU really ran, so the row is committed — and
                        # because the output is unusable, refunded on the spot
                        # (§9.9: QC FAIL → credit returned). The next attempt is
                        # reserved through the chain, which makes it free once
                        # the guarantee's attempt count is used up.
                        billing.commit(quota)
                        try:
                            credits.refund(quota, reason=decision.reason, source=credits.AUTO)
                        except credits.NotRefundable:
                            pass
                        try:
                            quota, chain = credits.reserve_retry(
                                quota, job=job,
                                detail=f"script {script.id} · قطعه {scene.index} · تلاش {attempt_no + 1}",
                            )
                        except billing.QuotaExceeded:
                            logger.info(
                                "Job %s: quota exhausted, keeping best attempt of segment %s",
                                job.id, scene.index,
                            )
                            quota = None
                            break
                    job.mark_progress(
                        step, f"قطعه {scene.index}: {decision.reason} — تلاش دوباره",
                    )

                chosen = best
                report = chosen["report"]
                video_path = chosen["video_path"]
                # The anchor comes from the FINAL file, after any repair. Taking
                # it from the dark original would hand the next segment the
                # lighting we just corrected, and the correction would undo
                # itself one clip later.
                # When the next scene CONTINUES from this one, its first frame
                # is this one's last — so the last frame is chosen, not taken:
                # a blurred final frame is trimmed back to the sharpest of the
                # last few, and the segment ends exactly on it (services/video/
                # anchor.py). A NEW_SCENE gets its own FLUX anchor instead.
                anchor_note = None
                following = next((s for s in scenes if s.index > scene.index), None)
                if following is not None and following.transition != "NEW_SCENE":
                    video_path, frame_path, choice = video_anchor.apply(
                        video_path, out_dir, label=f"segment_{scene.index}",
                    )
                    if choice.trimmed:
                        anchor_note = {
                            "frames_trimmed": choice.frames_back,
                            "sharpness": [round(choice.sharpness_last), round(choice.sharpness_chosen)],
                            "note": choice.note,
                        }
                else:
                    frame_path = extract_last_frame(
                        video_path, out_dir / f"segment_{scene.index}_last.png"
                    )
                media.store(segment.video, video_path)
                media.store(segment.last_frame, frame_path)
                # What the model actually rendered (colours, clothing, set) fills
                # whatever the script left empty — only when the product and the
                # person were judged GOOD or better, so a hallucinated colour
                # cannot seed the rest of the video.
                good = float(settings.UPMARKET_AI.get("QC_GOOD", 80))
                identity_axes = [
                    report.axis(name) for name in ("ثبات محصول", "ثبات شخصیت")
                ]
                if (report.vision_checked and not report.needs_regeneration
                        and all(a is None or a.score >= good for a in identity_axes)):
                    state = scene_state.absorb_observed(state, report.observed)
                segment.status = VideoSegment.Status.DONE
                segment.scene_state = state.as_dict()
                metadata = {
                    k: v for k, v in (segment.metadata or {}).items() if k != "regen"
                }
                segment.metadata = {
                    **metadata,
                    "workflow": "wan22_i2v@v1",
                    "positive": chosen["positive"],
                    "negative": chosen["negative"],
                    "seed": chosen["seed"],
                    "attempt": chosen["attempt"],
                    "attempts": history,
                    "duration": scene.duration,
                    "qc": report.as_dict(),
                    "qc_before_repair": (
                        chosen["report_before"].as_dict() if chosen["report_before"] else None
                    ),
                    "code_repair": chosen["code_repair"],
                    # The un-repaired render, kept so the panel can show the
                    # shop what the filter changed — and so a botched repair is
                    # recoverable.
                    "original_video": _original_url(chosen["original_path"]),
                    # The number `_should_pause` has been reading all along.
                    "quality_score": report.score_fraction,
                    "repair_plan": repair.plan(report),
                    "usage_id": quota.pk if quota is not None else None,
                    # A blurred tail trimmed so the next scene starts sharp.
                    "anchor": anchor_note,
                }
                segment.save()
                previous_frame_path = frame_path
                previous_state = state
            except Exception as exc:
                segment.status = VideoSegment.Status.FAILED
                segment.retry_count += 1
                segment.error = str(exc)[:2000]
                segment.metadata = {**(segment.metadata or {}), "attempts": history}
                segment.save()
                billing.release(quota, reason=type(exc).__name__)
                raise

            # This segment exists and is watchable — now it counts.
            billing.commit(quota)

            # A watchable preview now exists. Announce that first, then decide
            # whether it blocks: PREVIEW is the moment the piece is available
            # and is being judged, WAITING_APPROVAL is the moment a person has
            # to answer. In Auto mode the first happens without the second.
            if scene.index != scenes[-1].index:
                job.advance(
                    Job.State.PREVIEW,
                    label=f"قطعه {scene.index} آماده شد",
                    preview={
                        "segment_index": scene.index,
                        "segments_done": step,
                        "segments_total": len(scenes),
                        "video": segment.video.url if segment.video else None,
                        "mode": job.mode,
                        "quality": _quality_preview(segment),
                    },
                )
                if _should_pause(job, segment):
                    verdict = (segment.metadata.get("qc") or {}).get("verdict")
                    tries = len(history)
                    if verdict == "REGENERATE" and tries > 1:
                        label = (
                            f"قطعه {scene.index} بعد از {tries} تلاش به کیفیت لازم نرسید — "
                            "بهترین نسخه نگه داشته شد؛ نگاهی بینداز"
                        )
                    elif verdict in ("REVIEW", "REGENERATE"):
                        label = f"قطعه {scene.index} آماده است — کیفیتش را ببین"
                    elif not (segment.metadata.get("qc") or {}).get("vision_checked"):
                        label = (
                            f"قطعه {scene.index} آماده است — مدل بینایی در دسترس نبود و فقط "
                            "بررسی کد انجام شد؛ یک بار نگاه کن"
                        )
                    else:
                        label = f"قطعه {scene.index} آماده است — نگاهی بینداز"
                    job.advance(Job.State.WAITING_APPROVAL, label=label)
                    logger.info(
                        "Job %s parked after segment %s (mode=%s)",
                        job.id, scene.index, job.mode,
                    )
                    return {"script_id": script.id, "paused_after_segment": scene.index}
                job.advance(Job.State.PROCESSING, label="ادامه‌ی تولید")

        job.advance(Job.State.RENDERING, label="در حال اتصال قطعات ویدیو")
        job.mark_progress(len(scenes) + 1, "در حال اتصال قطعات ویدیو")
        done_segments = [segments[s.index] for s in scenes]
        with media.reading_all([seg.video for seg in done_segments]) as parts:
            final_path = concat_videos(parts, out_dir / "final.mp4")
        media.store(script.final_video, final_path)
        script.status = VideoScript.Status.READY
        script.save()

        # Nothing to commit here: every segment was billed and committed as it
        # finished. Stitching costs no GPU seconds.
        job.mark_completed(
            {"script_id": script.id, "final_video": script.final_video.url}
        )
        return {"script_id": script.id}
    except Exception as exc:  # noqa: BLE001
        logger.exception("Video generation job %s failed", job_id)
        billing.release(locals().get("quota"), reason=type(exc).__name__)
        job.mark_failed(exc)  # job reaches a terminal state no matter what
        if script is not None:
            try:
                script.status = VideoScript.Status.FAILED
                script.save(update_fields=["status", "updated_at"])
            except Exception:  # script row may be gone — job is already FAILED
                logger.warning("Could not mark script %s FAILED", script_id)
        return {"error": str(exc)}
    finally:
        open_media.close()


@shared_task(bind=True)
def repurpose_video_task(self, job_id, script_id, formats=None):
    """Cut a finished video into every platform shape. `ایده‌ها.md` §10.

    No GPU and no model: this is ffmpeg cropping a file that already exists.
    Re-rendering a 9:16 version of a clip we already have would spend minutes
    of the one card to produce something a few seconds of CPU can.

    Not billed. The shop already paid for these seconds of video once, and
    charging again for showing the same footage in a different frame is the
    kind of line item that loses a customer.
    """
    job = Job.objects.get(id=job_id)
    try:
        script = VideoScript.objects.select_related("store").get(id=script_id)
        source = script.final_video_voiced or script.final_video
        if not source:
            raise RuntimeError("اول باید ویدیوی نهایی ساخته شده باشد.")

        source_path = Path(source.path)
        out_dir = Path(settings.MEDIA_ROOT) / "generated" / "cuts" / f"script_{script.id}"
        job.total_steps = len(formats or repurpose.FORMATS_BY_KEY)
        job.advance(Job.State.PROCESSING, label="در حال ساخت برش‌ها")

        results = repurpose.make_all(source_path, out_dir, formats)

        made = []
        for index, result in enumerate(results, start=1):
            job.mark_progress(index, f"برش {result['title']}")
            if not result.get("ok"):
                continue
            cut, _ = VideoCut.objects.update_or_create(
                script=script,
                format=result["key"],
                defaults={
                    "video": _media_rel(Path(result["path"])),
                    "trimmed": result.get("trimmed", False),
                    "has_audio": bool(script.final_video_voiced),
                },
            )
            made.append({"format": cut.format, "url": cut.video.url})

        failed = [r for r in results if not r.get("ok")]
        job.mark_completed({
            "script_id": script.id,
            "cuts": made,
            # Named rather than swallowed: four publishable cuts plus a clear
            # message about the fifth beats an exception that loses all five.
            "failed": [{"format": r["key"], "error": r.get("error", "")} for r in failed],
        })
        return {"script_id": script.id, "cuts": len(made)}
    except Exception as exc:  # noqa: BLE001
        logger.exception("Repurpose job %s failed", job_id)
        job.mark_failed(exc)
        return {"error": str(exc)}
