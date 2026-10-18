"""The editor's API. §8–§10.

One thing here is worth reading before the code: **planning and applying are
separate endpoints**, and that is what makes «حالت پیشنهادی» real. A plan
endpoint that quietly rendered would make the approval decorative, and a shop
that pressed "see what you'd do" would find their video already changed.

So `POST .../plan/` measures and decides and touches nothing. `POST .../edit/`
is the only thing that writes a frame.
"""
import logging

from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.jobs.models import Job
from apps.jobs.services import dispatch_job
from apps.stores import access
from services.editing import agent, analysis, preferences, tools

from .models import UploadedVideo
from .tasks_editing import analyze_upload_task, edit_video_task, repurpose_upload_task

logger = logging.getLogger(__name__)

#: Big enough for a phone video of a few minutes, small enough that a mistaken
#: upload of a feature film does not fill the disk.
MAX_UPLOAD_MB = 500

ALLOWED_SUFFIXES = (".mp4", ".mov", ".m4v", ".webm", ".avi", ".mkv")


class UploadedVideoSerializer(serializers.ModelSerializer):
    findings = serializers.SerializerMethodField()
    video_url = serializers.SerializerMethodField()
    edited_url = serializers.SerializerMethodField()

    class Meta:
        model = UploadedVideo
        fields = [
            "id", "title", "state", "duration", "has_audio", "facts",
            "findings", "video_url", "edited_url", "edit_outcome", "error",
            "created_at",
        ]

    def get_findings(self, obj) -> list:
        return analysis.obvious_problems(obj.facts or {})

    def get_video_url(self, obj) -> str | None:
        return obj.video.url if obj.video else None

    def get_edited_url(self, obj) -> str | None:
        return obj.edited.url if obj.edited else None


class UploadedVideoListView(APIView):
    """Videos the shop filmed themselves. §8"""

    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def get(self, request, store_id):
        store = access.get_store(request.user, store_id, access.CONTENT, write=False)
        return Response({
            "videos": UploadedVideoSerializer(
                store.uploaded_videos.all()[:50], many=True,
            ).data,
            "modes": [{"key": k, "title": v} for k, v in agent.MODES.items()],
            "tools": tools.catalogue(),
            "habits": preferences.explain(store),
        })

    def post(self, request, store_id):
        store = access.get_store(request.user, store_id, access.CONTENT)

        uploaded = request.FILES.get("video")
        if uploaded is None:
            return Response(
                {"error": {"code": "no_file", "message": "فایلی فرستاده نشد."}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if uploaded.size > MAX_UPLOAD_MB * 1024 * 1024:
            return Response(
                {"error": {
                    "code": "too_big",
                    "message": f"حداکثر اندازه {MAX_UPLOAD_MB} مگابایت است.",
                }},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not str(uploaded.name).lower().endswith(ALLOWED_SUFFIXES):
            return Response(
                {"error": {
                    "code": "wrong_type",
                    "message": f"فرمت‌های قابل قبول: {'، '.join(ALLOWED_SUFFIXES)}",
                }},
                status=status.HTTP_400_BAD_REQUEST,
            )

        upload = UploadedVideo.objects.create(
            store=store,
            title=str(request.data.get("title", "")).strip()[:200] or uploaded.name,
            video=uploaded,
        )

        # Measured once, on upload. Every screen after this reads the cached
        # numbers instead of paying for an ffmpeg pass.
        job = Job.objects.create(
            store=store, type=Job.Type.VIDEO_ANALYSIS,
            context={"upload_id": upload.pk},
        )
        failed = dispatch_job(job, analyze_upload_task, job.id, upload.pk)
        if failed is not None:
            return failed

        return Response(
            {"video": UploadedVideoSerializer(upload).data, "job_id": job.id},
            status=status.HTTP_201_CREATED,
        )


class UploadedVideoDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id, pk):
        store = access.get_store(request.user, store_id, access.CONTENT, write=False)
        upload = get_object_or_404(UploadedVideo, pk=pk, store=store)
        return Response(UploadedVideoSerializer(upload).data)

    def delete(self, request, store_id, pk):
        store = access.get_store(request.user, store_id, access.CONTENT)
        upload = get_object_or_404(UploadedVideo, pk=pk, store=store)
        upload.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class EditPlanView(APIView):
    """What we would do — and nothing else. §9's «پیشنهادی» mode.

    Synchronous because it is cheap: the measurements are already cached on the
    row, and every decision below is arithmetic. Only DIRECTED mode makes a
    model call, and even that is one small text request.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, store_id, pk):
        store = access.get_store(request.user, store_id, access.CONTENT, write=False)
        upload = get_object_or_404(UploadedVideo, pk=pk, store=store)

        if upload.state == UploadedVideo.State.FAILED:
            return Response(
                {"error": {"code": "unreadable", "message": upload.error}},
                status=status.HTTP_409_CONFLICT,
            )
        if not upload.facts:
            return Response(
                {"error": {
                    "code": "not_analyzed",
                    "message": "بررسی این ویدیو هنوز تمام نشده است.",
                }},
                status=status.HTTP_409_CONFLICT,
            )

        mode = str(request.data.get("mode", agent.SUGGEST)).upper()
        if mode not in agent.MODES:
            return Response(
                {"error": {
                    "code": "bad_mode",
                    "message": f"حالت‌های موجود: {'، '.join(agent.MODES)}",
                }},
                status=status.HTTP_400_BAD_REQUEST,
            )

        facts = upload.facts
        findings = analysis.obvious_problems(facts)

        if mode == agent.MANUAL:
            raw = list(request.data.get("operations") or [])
        elif mode == agent.DIRECTED:
            raw = agent.ask_model(
                facts, findings, str(request.data.get("instruction", "")),
                store=store,
            ) or agent.suggest(facts, store=store)
        else:
            raw = agent.suggest(facts, store=store)

        accepted, refusals = tools.validate(
            raw, duration=facts.get("duration"), has_audio=facts.get("has_audio", True),
        )
        return Response({
            "mode": mode,
            "operations": [o.as_dict() for o in accepted],
            "refusals": refusals,
            "findings": findings,
            "facts": facts,
            "habits": preferences.explain(store),
        })


class EditApplyView(APIView):
    """The only endpoint that writes a frame. §9"""

    permission_classes = [IsAuthenticated]

    def post(self, request, store_id, pk):
        store = access.get_store(request.user, store_id, access.CONTENT)
        upload = get_object_or_404(UploadedVideo, pk=pk, store=store)

        mode = str(request.data.get("mode", agent.AUTO)).upper()
        if mode not in agent.MODES or mode == agent.SUGGEST:
            # SUGGEST is refused here on purpose: it is the mode that means
            # "do not apply", and accepting it would make the two endpoints
            # mean the same thing.
            return Response(
                {"error": {
                    "code": "bad_mode",
                    "message": "برای اعمال، یکی از حالت‌های دستی، خودکار یا کارگردانی را بفرستید.",
                }},
                status=status.HTTP_400_BAD_REQUEST,
            )

        job = Job.objects.create(
            store=store, type=Job.Type.VIDEO_EDIT,
            context={"upload_id": upload.pk, "mode": mode},
        )
        failed = dispatch_job(
            job, edit_video_task, job.id, upload.pk, mode,
            request.data.get("operations") or [],
            str(request.data.get("instruction", "")),
        )
        if failed is not None:
            return failed
        return Response({"job_id": job.id}, status=status.HTTP_202_ACCEPTED)


class EditRejectView(APIView):
    """«نه، این یکی را نمی‌خواهم».

    A refusal is the most informative thing a shop tells the editor — §9's
    learning is mostly built from these — so it gets its own endpoint rather
    than being inferred from what did not appear in a later request.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, store_id, pk):
        store = access.get_store(request.user, store_id, access.CONTENT)
        upload = get_object_or_404(UploadedVideo, pk=pk, store=store)

        rejected = request.data.get("tools")
        if not isinstance(rejected, list) or not rejected:
            return Response(
                {"error": {"code": "empty", "message": "کدام پیشنهاد را رد می‌کنید؟"}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        recorded = 0
        for item in rejected[:20]:
            name = item.get("tool") if isinstance(item, dict) else item
            row = preferences.record(
                store, tool=str(name), params=(
                    item.get("params", {}) if isinstance(item, dict) else {}
                ),
                accepted=False, source="SUGGESTED",
            )
            if row is not None:
                row.video = upload
                row.save(update_fields=["video"])
                recorded += 1

        learned = preferences.refresh(store)
        return Response({
            "recorded": recorded,
            "habits": preferences.explain(store),
            "never": learned["never"],
        })


class RepurposeUploadView(APIView):
    """One video, every format. §10"""

    permission_classes = [IsAuthenticated]

    def post(self, request, store_id, pk):
        store = access.get_store(request.user, store_id, access.CONTENT)
        upload = get_object_or_404(UploadedVideo, pk=pk, store=store)

        job = Job.objects.create(
            store=store, type=Job.Type.VIDEO_EDIT,
            context={"upload_id": upload.pk, "what": "repurpose"},
        )
        failed = dispatch_job(
            job, repurpose_upload_task, job.id, upload.pk,
            request.data.get("formats") or [],
        )
        if failed is not None:
            return failed
        return Response({"job_id": job.id}, status=status.HTTP_202_ACCEPTED)


class RealPhotoView(APIView):
    """«عکس واقعی را آخرش بگذار». §26

    A GET that answers whether this is even possible, and a POST that does it.
    The GET matters: a shop with nothing uploaded should see a clear ask for a
    photo instead of a button that fails when pressed.

    Deliberately not automatic. Publishing a photo of your own face is a
    decision, and a pipeline that appended it because the field happened to be
    filled would be making that decision for someone.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, store_id, pk):
        from services.content import trust

        from .models import VideoScript

        store = access.get_store(request.user, store_id, access.CONTENT, write=False)
        script = get_object_or_404(
            VideoScript.objects.select_related("product"), pk=pk, store=store,
        )
        return Response({
            **trust.available(store, script.product),
            "video": (
                script.final_video_real.url if script.final_video_real else None
            ),
        })

    def post(self, request, store_id, pk):
        from .models import VideoScript
        from .tasks_editing import append_real_photo_task

        store = access.get_store(request.user, store_id, access.CONTENT)
        script = get_object_or_404(VideoScript, pk=pk, store=store)

        if not (script.final_video_voiced or script.final_video):
            return Response(
                {"error": {
                    "code": "no_video",
                    "message": "اول باید ویدیو ساخته شده باشد.",
                }},
                status=status.HTTP_400_BAD_REQUEST,
            )

        prefer = request.data.get("prefer")
        prefer = prefer if prefer in ("owner", "product") else "owner"

        job = Job.objects.create(
            store=store, type=Job.Type.VIDEO_EDIT,
            context={"script_id": script.pk, "what": "real_photo"},
        )
        failed = dispatch_job(job, append_real_photo_task, job.id, script.pk, prefer)
        if failed is not None:
            return failed
        return Response({"job_id": job.id}, status=status.HTTP_202_ACCEPTED)


class SubtitleView(APIView):
    """Subtitles for a video we made. §8

    Free, and the reason is worth saying on the endpoint: the narration is a
    column in our own database, so there is nothing to recognise. Only the
    timing is unknown, and that comes from the pauses in the audio.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, store_id, pk):
        from services.video import subtitles

        from .models import VideoScript

        store = access.get_store(request.user, store_id, access.CONTENT, write=False)
        script = get_object_or_404(
            VideoScript.objects.prefetch_related("scenes"), pk=pk, store=store,
        )
        lines = sum(
            len(subtitles.phrases(s.narration or "")) for s in script.scenes.all()
        )
        word_level = subtitles.word_level_available()
        return Response({
            "url": script.subtitles.url if script.subtitles else None,
            "lines": lines,
            "possible": lines > 0,
            # Said plainly rather than hidden behind a disabled button: a shop
            # whose video has no narration should know subtitles are a
            # consequence of narration, not a separate feature they missed.
            "reason": (
                "" if lines else
                "این ویدیو نریشن ندارد، و زیرنویس از روی همان نریشن ساخته می‌شود."
            ),
            # Three states: on, off, or null meaning "whatever the shop
            # decided". See `subtitles.subtitles_wanted` for why not two.
            "enabled": script.subtitles_enabled,
            "burned": script.subtitles_burned,
            "effective_enabled": subtitles.subtitles_wanted(script, store),
            "effective_burned": subtitles.subtitles_burned(script, store),
            "word_level": word_level,
            "word_level_note": (
                "زمان‌بندی هر کلمه از روی خود صدا خوانده می‌شود."
                if word_level else
                "زیرنویس خط‌به‌خط است، نه کلمه‌به‌کلمه — ویسپر نصب نیست."
            ),
        })

    def patch(self, request, store_id, pk):
        """Turn subtitles on or off for this video — or send null to hand it
        back to the shop's default."""
        from .models import VideoScript

        store = access.get_store(request.user, store_id, access.CONTENT)
        script = get_object_or_404(VideoScript, pk=pk, store=store)

        changed = []
        for field in ("subtitles_enabled", "subtitles_burned"):
            key = field.replace("subtitles_", "")
            if key in request.data:
                value = request.data[key]
                setattr(script, field, None if value is None else bool(value))
                changed.append(field)
        if changed:
            script.save(update_fields=changed + ["updated_at"])
        return self.get(request, store_id, pk)

    def post(self, request, store_id, pk):
        from .models import VideoScript
        from .tasks_editing import build_subtitles_task

        store = access.get_store(request.user, store_id, access.CONTENT)
        script = get_object_or_404(VideoScript, pk=pk, store=store)

        job = Job.objects.create(
            store=store, type=Job.Type.VIDEO_EDIT,
            context={"script_id": script.pk, "what": "subtitles"},
        )
        failed = dispatch_job(job, build_subtitles_task, job.id, script.pk)
        if failed is not None:
            return failed
        return Response({"job_id": job.id}, status=status.HTTP_202_ACCEPTED)


class MusicView(APIView):
    """The shop's own music, under their narration. §7

    Upload is a PUT with a file; POST mixes it in. Separate because uploading is
    cheap and mixing is a render, and a shop changing the level three times
    should not re-upload the track three times.
    """

    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    MAX_MB = 20
    SUFFIXES = (".mp3", ".m4a", ".wav", ".aac", ".ogg", ".flac")

    def get(self, request, store_id, pk):
        from services.audio import music as music_engine

        from .models import VideoScript

        store = access.get_store(request.user, store_id, access.CONTENT, write=False)
        script = get_object_or_404(VideoScript, pk=pk, store=store)
        return Response({
            "music": script.music.name.rsplit("/", 1)[-1] if script.music else None,
            "level_db": script.music_level_db,
            "ceiling_db": music_engine.MUSIC_CEILING,
            "video": (
                script.final_video_music.url if script.final_video_music else None
            ),
            # The track's own licence code (CC-BY, CC0…) when it came from
            # the library; empty for the shop's own file.
            "track_licence": script.music_licence,
            "attribution": script.music_attribution,
            "needs_credit": bool(script.music_attribution),
            # Shown before the upload button, not in terms nobody reads: the
            # consequence lands on their account, weeks later. (This key used
            # to be written twice in this dict, so the track's licence above
            # was never returned at all.)
            "licence": music_engine.LICENCE_NOTE,
        })

    def put(self, request, store_id, pk):
        from .models import VideoScript

        store = access.get_store(request.user, store_id, access.CONTENT)
        script = get_object_or_404(VideoScript, pk=pk, store=store)

        uploaded = request.FILES.get("music")
        if uploaded is None:
            return Response(
                {"error": {"code": "no_file", "message": "فایلی فرستاده نشد."}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if uploaded.size > self.MAX_MB * 1024 * 1024:
            return Response(
                {"error": {
                    "code": "too_big",
                    "message": f"حداکثر {self.MAX_MB} مگابایت.",
                }},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not str(uploaded.name).lower().endswith(self.SUFFIXES):
            return Response(
                {"error": {
                    "code": "wrong_type",
                    "message": f"فرمت‌های قابل قبول: {'، '.join(self.SUFFIXES)}",
                }},
                status=status.HTTP_400_BAD_REQUEST,
            )

        script.music = uploaded
        # The shop's own file replaces a library track, and with it that
        # track's credit line — otherwise the panel keeps asking for a credit
        # to a song that is no longer in the video.
        script.music_source = ""
        script.music_licence = ""
        script.music_attribution = ""
        script.save(update_fields=[
            "music", "music_source", "music_licence", "music_attribution", "updated_at",
        ])
        return Response({"music": uploaded.name}, status=status.HTTP_201_CREATED)

    def post(self, request, store_id, pk):
        from .models import VideoScript
        from .tasks_editing import add_music_task

        store = access.get_store(request.user, store_id, access.CONTENT)
        script = get_object_or_404(VideoScript, pk=pk, store=store)

        if not script.music:
            from services.audio import music as music_engine

            return Response(
                {"error": {"code": "no_music", "message": music_engine.LICENCE_NOTE}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        level = request.data.get("level_db")
        if level is not None:
            try:
                script.music_level_db = float(level)
                script.save(update_fields=["music_level_db", "updated_at"])
            except (TypeError, ValueError):
                return Response(
                    {"error": {"code": "bad_level", "message": "بلندی باید عدد باشد."}},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        job = Job.objects.create(
            store=store, type=Job.Type.VIDEO_EDIT,
            context={"script_id": script.pk, "what": "music"},
        )
        failed = dispatch_job(
            job, add_music_task, job.id, script.pk,
            script.music_level_db,
            request.data.get("duck", True) not in (False, "false", "0"),
        )
        if failed is not None:
            return failed
        return Response({"job_id": job.id}, status=status.HTTP_202_ACCEPTED)


class UploadSubtitleView(APIView):
    """Subtitles for video the shop filmed themselves. §8

    Needs Whisper — here we genuinely do not know what was said. The GET says
    whether that is possible *before* the button is pressed, because "install
    faster-whisper" is something a person can act on and a failed job is not.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, store_id, pk):
        from services.audio import transcribe
        from services.video import subtitles

        store = access.get_store(request.user, store_id, access.CONTENT, write=False)
        upload = get_object_or_404(UploadedVideo, pk=pk, store=store)

        ok, why = transcribe.available()
        return Response({
            "url": upload.subtitles.url if upload.subtitles else None,
            "possible": ok and upload.has_audio,
            "reason": (
                why if not ok
                else "" if upload.has_audio
                else "این ویدیو صدا ندارد، پس چیزی برای زیرنویس کردن نیست."
            ),
            "enabled": upload.subtitles_enabled,
            "burned": upload.subtitles_burned,
            "effective_enabled": subtitles.subtitles_wanted(upload, store),
            "effective_burned": subtitles.subtitles_burned(upload, store),
            "lines": len(upload.transcript or []),
            # Lines the shop should look at before publishing. A word we got
            # wrong is fixable; a line we quietly dropped is not.
            "uncertain": sum(
                1 for row in (upload.transcript or []) if row.get("uncertain")
            ),
        })

    def patch(self, request, store_id, pk):
        store = access.get_store(request.user, store_id, access.CONTENT)
        upload = get_object_or_404(UploadedVideo, pk=pk, store=store)

        changed = []
        for field in ("subtitles_enabled", "subtitles_burned"):
            key = field.replace("subtitles_", "")
            if key in request.data:
                value = request.data[key]
                setattr(upload, field, None if value is None else bool(value))
                changed.append(field)
        if changed:
            upload.save(update_fields=changed + ["updated_at"])
        return self.get(request, store_id, pk)

    def post(self, request, store_id, pk):
        from .tasks_editing import transcribe_upload_task

        store = access.get_store(request.user, store_id, access.CONTENT)
        upload = get_object_or_404(UploadedVideo, pk=pk, store=store)

        job = Job.objects.create(
            store=store, type=Job.Type.VIDEO_EDIT,
            context={"upload_id": upload.pk, "what": "subtitles"},
        )
        failed = dispatch_job(job, transcribe_upload_task, job.id, upload.pk)
        if failed is not None:
            return failed
        return Response({"job_id": job.id}, status=status.HTTP_202_ACCEPTED)


class MusicLibraryView(APIView):
    """Free music a shop may actually use in an advertising video. §7

    Separate from `MusicView` because they answer different questions: this one
    is "what can I use", that one is "use this one". And the licence filtering
    lives in the service layer, not here — a caveat on a download button is a
    caveat nobody reads, so tracks a shop may not use are never shown at all.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, store_id):
        from services.audio import library

        access.get_store(request.user, store_id, access.CONTENT, write=False)
        try:
            found = library.search(
                request.query_params.get("q", ""),
                limit=int(request.query_params.get("limit", 20) or 20),
                page=int(request.query_params.get("page", 1) or 1),
            )
        except library.LibraryUnavailable as exc:
            # 503, not an empty list: "nothing matched" and "we could not look"
            # send a shop in opposite directions.
            return Response(
                {"error": {"code": "unavailable", "message": str(exc)}},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except (TypeError, ValueError):
            return Response(
                {"error": {"code": "bad_page", "message": "شماره‌ی صفحه درست نیست."}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response({**found, "about": library.available()})

    def post(self, request, store_id):
        """Take one track from the library and attach it to a video."""
        from pathlib import Path

        from django.conf import settings

        from services.audio import library
        from services.media import files as media

        from .models import VideoScript

        store = access.get_store(request.user, store_id, access.CONTENT)

        script_id = request.data.get("script_id")
        script = get_object_or_404(VideoScript, pk=script_id, store=store)

        url = str(request.data.get("url", "")).strip()
        if not url.startswith(("http://", "https://")):
            return Response(
                {"error": {"code": "bad_url", "message": "نشانی آهنگ درست نیست."}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        work = Path(settings.MEDIA_ROOT) / "uploads" / "music"
        work.mkdir(parents=True, exist_ok=True)
        target = work / f"script_{script.pk}_library.mp3"

        try:
            library.fetch(url, target)
        except library.LibraryUnavailable as exc:
            return Response(
                {"error": {"code": "download_failed", "message": str(exc)}},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        media.store(script.music, target)
        script.music_source = url[:200]
        script.music_licence = str(request.data.get("licence", ""))[:20]
        # Stored with the file, because a credit line the shop cannot find when
        # they publish is a credit line that does not get pasted.
        script.music_attribution = str(request.data.get("attribution", ""))[:400]
        script.save(update_fields=[
            "music", "music_source", "music_licence", "music_attribution",
            "updated_at",
        ])

        return Response({
            "music": target.name,
            "licence": script.music_licence,
            "attribution": script.music_attribution,
            "needs_credit": bool(script.music_attribution),
        }, status=status.HTTP_201_CREATED)
