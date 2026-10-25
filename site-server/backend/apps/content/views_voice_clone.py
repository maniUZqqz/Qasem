"""«کلونِ صدا» — a shop's own narrator, from someone reading a few sentences.

    GET  POST            /stores/{id}/voice/clones/                          list (+ script, limits, nodes) · create (consent)
    GET  PATCH  DELETE   /stores/{id}/voice/clones/{pk}/                     one voice (+ clips, build progress)
    POST                 /stores/{id}/voice/clones/{pk}/clips/               one read sentence (multipart: file, index, text)
    DELETE               /stores/{id}/voice/clones/{pk}/clips/{index}/
    GET                  /stores/{id}/voice/clones/{pk}/clips/{index}/audio/
    POST                 /stores/{id}/voice/clones/{pk}/build/               «ساختِ صدا» → voice.clone on a processing node
    GET                  /stores/{id}/voice/clones/{pk}/sample/?kind=preview|reference
    POST                 /stores/{id}/voice/clones/{pk}/test/                {text} → voice.tts job (async)
    GET                  /stores/{id}/voice/clones/{pk}/test/{uid}/          its state; /audio/ when done
    POST                 /stores/{id}/voice/clones/{pk}/use/                 {use: bool} — narrate the shop's content with it

Consent comes first: a voice row cannot exist without the person's name, the
purpose and the exact consent sentence the user agreed to (stored with time,
user and IP). Audio is never served from /media/ — only through these views,
to members of the store.
"""
from __future__ import annotations

import logging

from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.stores import access

logger = logging.getLogger(__name__)

MAX_TEST_CHARS = 400


def _error(code: str, message: str, http=status.HTTP_400_BAD_REQUEST) -> Response:
    return Response({"error": {"code": code, "message": message}}, status=http)


def _voice(request, store_id, pk, *, write: bool):
    from apps.ai.models import ClonedVoice

    store = access.get_store(request.user, store_id, access.CONTENT, write=write)
    return store, get_object_or_404(ClonedVoice, pk=pk, store=store)


def _client_ip(request):
    forwarded = (request.META.get("HTTP_X_FORWARDED_FOR") or "").split(",")[0].strip()
    return forwarded or request.META.get("REMOTE_ADDR") or None


def _wav(path) -> FileResponse:
    if not path or not path.is_file():
        raise Http404("صدا پیدا نشد.")
    response = FileResponse(open(path, "rb"), content_type="audio/wav")
    response["Cache-Control"] = "private, no-store"
    return response


def _engine_options() -> list:
    """Both cloning engines, with their licence and whether a processing node can run them right now."""
    from services.audio import node_audio
    from services.audio import voice_clone as vc

    moss_ok, moss_why = node_audio.moss_ready()
    pocket = vc.nodes_status()
    rows = []
    for key, meta in vc.ENGINES.items():
        ready, why = (moss_ok, moss_why) if key == "moss-fa" else (pocket["online"], pocket["message"])
        rows.append({**meta, "ready": ready, "why": why})
    return rows


class ClonedVoiceListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id):
        from apps.ai.models import ClonedVoice
        from services.audio import voice_clone as vc

        store = access.get_store(request.user, store_id, access.CONTENT, write=False)
        voices = []
        for voice in ClonedVoice.objects.filter(store=store).select_related("consent_by"):
            job = vc.sync(voice)
            voices.append(vc.voice_json(voice, job=job))
        return Response({
            "voices": voices,
            "script": list(vc.script()),
            "limits": vc.limits(),
            "nodes": vc.nodes_status(),
            "consent_template": vc.CONSENT_TEMPLATE.replace("{store}", store.name),
            "default_purpose": vc.DEFAULT_PURPOSE,
            "engine": {"id": vc.ENGINE, "label": vc.ENGINE_LABEL, "license": vc.ENGINE_LICENSE,
                       "commercial": vc.ENGINE_COMMERCIAL},
            "engines": _engine_options(),
            "in_use": vc.in_use_id(store),
        })

    def post(self, request, store_id):
        from apps.ai.models import ClonedVoice
        from services.audio import voice_clone as vc

        store = access.get_store(request.user, store_id, access.CONTENT)
        name = vc.clean_text(request.data.get("name"))[:60]
        person = vc.clean_text(request.data.get("person"))[:120]
        purpose = vc.clean_text(request.data.get("purpose"))[:300] or vc.DEFAULT_PURPOSE
        if request.data.get("consent") is not True and str(request.data.get("consent")).lower() not in ("true", "1", "on"):
            return _error("consent_required", "بدونِ رضایتِ صاحبِ صدا نمی‌شود: تیکِ رضایت‌نامه را بزنید.")
        if not name:
            return _error("name_required", "برای صدا یک نام بگذارید.")
        if not person:
            return _error("person_required", "نامِ صاحبِ صدا (کسی که می‌خواند) لازم است.")
        if ClonedVoice.objects.filter(store=store).count() >= 10:
            return _error("too_many", "حداکثر ۱۰ صدای کلون‌شده برای هر فروشگاه — یکی را پاک کنید.")
        engine = str(request.data.get("engine") or vc.ENGINE)
        if engine not in vc.ENGINES:
            return _error("bad_engine", "موتورِ کلونِ ناشناخته.")
        voice = ClonedVoice.objects.create(
            store=store, name=name, person=person, purpose=purpose,
            consent_text=vc.consent_text(person, purpose, store.name), consent_at=timezone.now(),
            consent_by=request.user, consent_ip=_client_ip(request),
            engine=engine, engine_license=vc.ENGINES[engine]["license"],
        )
        return Response(vc.voice_json(voice, with_clips=True), status=status.HTTP_201_CREATED)


class ClonedVoiceDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id, pk):
        from services.audio import voice_clone as vc

        _store, voice = _voice(request, store_id, pk, write=False)
        job = vc.sync(voice)
        return Response(vc.voice_json(voice, with_clips=True, job=job))

    def patch(self, request, store_id, pk):
        from services.audio import voice_clone as vc

        _store, voice = _voice(request, store_id, pk, write=True)
        if "name" in request.data:
            name = vc.clean_text(request.data.get("name"))[:60]
            if not name:
                return _error("name_required", "نامِ صدا خالی است.")
            voice.name = name
            voice.save(update_fields=["name", "updated_at"])
        if "engine" in request.data:
            if voice.status == voice.Status.BUILDING:
                return _error("building", "صدا در حالِ ساخت است.", status.HTTP_409_CONFLICT)
            try:
                vc.set_engine(voice, str(request.data.get("engine")))
            except vc.VoiceCloneError as exc:
                return _error("bad_engine", str(exc))
        return Response(vc.voice_json(voice, with_clips=True, job=vc.sync(voice)))

    def delete(self, request, store_id, pk):
        from services.audio import voice_clone as vc

        _store, voice = _voice(request, store_id, pk, write=True)
        vc.delete_voice(voice)
        return Response(status=status.HTTP_204_NO_CONTENT)


class ClonedVoiceClipsView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, store_id, pk):
        from services.audio import voice_clone as vc

        _store, voice = _voice(request, store_id, pk, write=True)
        if voice.status == voice.Status.BUILDING:
            return _error("building", "صدا در حالِ ساخت است؛ بعد از پایانِ ساخت نمونه اضافه کنید.", status.HTTP_409_CONFLICT)
        upload = request.FILES.get("file")
        try:
            clip, check = vc.save_clip(voice, index=request.data.get("index"), text=request.data.get("text"),
                                       upload=upload, source=str(request.data.get("source") or "record"))
        except vc.VoiceCloneError as exc:
            return _error("bad_clip", str(exc))
        return Response({"clip": vc.clip_json(clip), "check": check,
                         "voice": vc.voice_json(voice, job=vc.sync(voice))}, status=status.HTTP_201_CREATED)


class ClonedVoiceClipView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, store_id, pk, index):
        from services.audio import voice_clone as vc

        _store, voice = _voice(request, store_id, pk, write=True)
        if voice.status == voice.Status.BUILDING:
            return _error("building", "صدا در حالِ ساخت است.", status.HTTP_409_CONFLICT)
        if not vc.delete_clip(voice, index):
            raise Http404("این نمونه نیست.")
        return Response(vc.voice_json(voice, with_clips=True, job=vc.sync(voice)))


class ClonedVoiceClipAudioView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id, pk, index):
        from services.audio import voice_clone as vc

        _store, voice = _voice(request, store_id, pk, write=False)
        get_object_or_404(voice.clips, index=index)
        return _wav(vc.clip_wav(voice, index))


class ClonedVoiceBuildView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, store_id, pk):
        from services.audio import voice_clone as vc

        _store, voice = _voice(request, store_id, pk, write=True)
        # consent is asked again at the moment of building: the person may have changed their mind
        if request.data.get("consent") is not True:
            return _error("consent_required", "پیش از ساخت، رضایتِ صاحبِ صدا را دوباره تأیید کنید.")
        vc.sync(voice)
        if request.data.get("engine"):
            try:
                vc.set_engine(voice, str(request.data.get("engine")))
            except vc.VoiceCloneError as exc:
                return _error("bad_engine", str(exc))
        try:
            job = vc.start_build(voice)
        except vc.NodeOffline as exc:
            return _error("node_offline", str(exc), status.HTTP_503_SERVICE_UNAVAILABLE)
        except vc.VoiceCloneError as exc:
            return _error("cannot_build", str(exc))
        return Response(vc.voice_json(voice, with_clips=True, job=job), status=status.HTTP_202_ACCEPTED)


class ClonedVoiceSampleView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id, pk):
        from services.audio import voice_clone as vc

        _store, voice = _voice(request, store_id, pk, write=False)
        kind = request.query_params.get("kind", "preview")
        return _wav(vc.reference_path(voice) if kind == "reference" else vc.preview_path(voice))


class ClonedVoiceTestView(APIView):
    """`POST {text}` — hear any sentence in the cloned voice. Async: returns the job; poll the status view."""

    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser, FormParser]

    def post(self, request, store_id, pk):
        from services.audio import lexicon
        from services.audio import voice_clone as vc

        store, voice = _voice(request, store_id, pk, write=False)
        vc.sync(voice)
        if not voice.usable:
            return _error("not_ready", "اول صدا را بسازید.", status.HTTP_409_CONFLICT)
        text = vc.clean_text(request.data.get("text"))[:MAX_TEST_CHARS] or vc.SAMPLE_TEXT
        # the same spoken form the narration gets: brand names as the shop says them, numbers as words
        spoken = lexicon.apply(text, store)
        from apps.compute import services as compute

        try:
            job = vc.enqueue_tts(voice, spoken, origin="voice_clone_test")
        except vc.NodeOffline as exc:
            return _error("node_offline", str(exc), status.HTTP_503_SERVICE_UNAVAILABLE)
        except compute.ComputeUnavailable:
            return _error("node_offline", vc.offline_message(voice), status.HTTP_503_SERVICE_UNAVAILABLE)
        return Response({"job": vc.job_state(job), "spoken_text": spoken}, status=status.HTTP_202_ACCEPTED)


def _test_job(voice, uid):
    from apps.compute.models import ComputeJob

    job = get_object_or_404(ComputeJob.objects.select_related("node"), uid=uid, kind="voice.tts", store=voice.store)
    if (job.payload or {}).get("nm_voice") != voice.pk:
        raise Http404
    return job


class ClonedVoiceTestStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id, pk, uid):
        from services.audio import voice_clone as vc

        _store, voice = _voice(request, store_id, pk, write=False)
        job = _test_job(voice, uid)
        if vc.needs_restore(job):
            # the node no longer has this voice: send it again with the best clips so the node rebuilds it
            try:
                job = vc.enqueue_tts(voice, job.payload.get("text") or vc.SAMPLE_TEXT, origin="voice_clone_test",
                                     restore=True)
            except vc.NodeOffline as exc:
                return _error("node_offline", str(exc), status.HTTP_503_SERVICE_UNAVAILABLE)
        if job.state == "COMPLETED":
            vc.note_node_copy(voice, job)
        state = vc.job_state(job)
        state["audio"] = bool(job.state == "COMPLETED" and vc.speech_output(job))
        state["check"] = ((job.result or {}).get("meta") or {}).get("check")
        return Response({"job": state})


class ClonedVoiceTestAudioView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id, pk, uid):
        from services.audio import voice_clone as vc

        _store, voice = _voice(request, store_id, pk, write=False)
        return _wav(vc.speech_output(_test_job(voice, uid)))


class ClonedVoiceUseView(APIView):
    """`POST {use: bool}` — make this voice the narrator of the shop's videos (Persian), or stop."""

    permission_classes = [IsAuthenticated]

    def post(self, request, store_id, pk):
        from services.audio import voice_clone as vc

        store, voice = _voice(request, store_id, pk, write=True)
        vc.sync(voice)
        try:
            vc.set_in_use(voice, bool(request.data.get("use", True)))
        except vc.VoiceCloneError as exc:
            return _error("not_ready", str(exc), status.HTTP_409_CONFLICT)
        store.profile.refresh_from_db()
        return Response(vc.voice_json(voice, with_clips=False))
