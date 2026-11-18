"""«تلفظ» — API پنل (همه زیرِ ``stores/<id>/pronunciation/``).

    GET    /                 ⇐ تنظیم، موتورها (محلی/آنلاین، آماده یا نه)، شمارش‌ها، آخرین سنجش‌ها
    PATCH  settings/         ⇐ {enabled، ezafe، depth:{piper|edge|moss: normalize|lexicon|full}}
    POST   preview/          ⇐ {text} ⇒ «پیش/پس» برای هر موتور + واژه‌به‌واژه (چه چیزی عوض شد و چرا)
    POST   convert/          ⇐ {respelling} ⇒ آوا + «این‌طور خوانده می‌شود» (زنده، هنگام تایپ)
    POST   listen/           ⇐ {text, engine, variant: before|after} ⇒ صدا (Piper/Edge همین الان؛ MOSS کارِ صف)
    GET    listen/<token>/   ⇐ وضعیتِ کارِ MOSS
    GET    audio/<name>      ⇐ فایلِ صدا (فقط وارد شده‌ها)
    GET    shared/?q=&category=        ⇐ واژه‌نامهٔ مشترک (فقط‌خواندنی)
    GET · POST lexicon/      ⇐ واژه‌نامهٔ فروشگاه (scope=global: افزودهٔ سراسری، فقط کارمند)
    PATCH · DELETE lexicon/<id>/
    GET · POST problems/ · PATCH · DELETE problems/<id>/     ⇐ «مشکل‌دار»؛ PATCH {status} یا {respelling} (= افزودن به واژه‌نامه)
    GET · POST eval/  · GET eval/<id>/   ⇐ سنجشِ صدا ← تشخیصِ گفتار ← نرخِ خطای واژه
    GET    samples/          ⇐ نمونه‌های پیش/پس که روی سرور ساخته شده (فقط وارد شده‌ها؛ فایل‌ها در پوشهٔ دادهٔ سرور، نه در مسیرِ عمومیِ media)
    GET    samples/<set>/<file>
"""
from __future__ import annotations

import json
import logging
import re

import uuid
from pathlib import Path

from django.conf import settings
from django.db.models import Q
from django.http import FileResponse, Http404
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.stores import access
from services.audio import engines as engine_registry
from services.audio import fa_pron

from . import evalrun
from . import services as svc
from .models import EvalRun, LexiconEntry, ProblemWord

logger = logging.getLogger(__name__)


def _err(message: str, code: str = "pronunciation", http=status.HTTP_400_BAD_REQUEST, **extra):
    return Response({"error": {"code": code, "message": message, **extra}}, status=http)


def _store(request, store_id, write: bool = True):
    return access.get_store(request.user, store_id, access.CONTENT, write=write)


def _body(request) -> dict:
    return request.data if isinstance(request.data, dict) else {}


def _audio_dir(store) -> Path:
    p = Path(settings.MEDIA_ROOT) / "pronunciation" / str(store.pk)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _node_state() -> dict:
    """Is a processing node able to do the node-side parts right now?"""
    try:
        from apps.compute import services as compute

        known = compute.known_nodes("voice")
        online = compute.online_nodes("voice")
        return {"known": len(known), "online": len(online), "names": [n.name for n in online]}
    except Exception:  # noqa: BLE001
        return {"known": 0, "online": 0, "names": []}


class OverviewView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id):
        store = _store(request, store_id, write=False)
        s = svc.settings_for(store)
        svc.seed_baseline()
        try:
            evalrun.advance(limit=2)
        except Exception as exc:  # noqa: BLE001
            logger.debug("pronunciation advance: %s", exc)
        local = engine_registry.local_only(store)
        runs = list(EvalRun.objects.filter(Q(store=store) | Q(store__isnull=True)).order_by("-created_at")[:40])
        site_voices = svc.site_piper_voices()
        latest: dict[str, dict] = {}
        for r in runs:
            if r.state != EvalRun.State.DONE:
                continue
            # a real measurement beats the one that shipped with the version; a voice this site really has beats one it does not
            rank = (not r.baseline, r.engine != "piper" or r.voice.removesuffix(".onnx") in site_voices,
                    r.depth == svc.effective_default(r.engine), r.created_at)
            if r.engine not in latest or rank > latest[r.engine]["_rank"]:
                latest[r.engine] = {**svc.run_dict(r), "_rank": rank}
        for v in latest.values():
            v.pop("_rank", None)
        engines = []
        for key, meta in svc.ENGINES.items():
            engines.append({"key": key, **meta, "blocked": bool(local and not meta["local"]),
                            "depth": s["depth"].get(key) or svc.effective_default(key),
                            "default_depth": svc.effective_default(key), "static_default": fa_pron.DEFAULT_DEPTH[key]})
        svc.refresh_problems(store)
        return Response({
            "settings": s, "engines": engines, "depths": svc.DEPTH_LABELS, "depth_help": svc.DEPTH_HELP, "local_only": local, "node": _node_state(),
            "site_voices": site_voices, "layer_version": fa_pron.VERSION,
            "counts": {"store": LexiconEntry.objects.filter(store=store).count(),
                       "global": LexiconEntry.objects.filter(store__isnull=True).count(),
                       "shared": len(fa_pron.dictionary.shared()),
                       "problems": ProblemWord.objects.filter(store=store, status="open").count(),
                       "sentences": len(fa_pron.eval_set.SENTENCES), "quick": len(evalrun.sentences("quick"))},
            "tags": fa_pron.eval_set.TAGS, "latest": latest, "runs": [svc.run_dict(r) for r in runs],
            "is_staff": bool(request.user.is_staff),
        })


class SettingsView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, store_id):
        store = _store(request, store_id)
        d = _body(request)
        try:
            return Response(svc.save_settings(store, enabled=d.get("enabled"), ezafe=d.get("ezafe"), depth=d.get("depth")))
        except svc.PronError as exc:
            return _err(str(exc))


class PreviewView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, store_id):
        store = _store(request, store_id, write=False)
        d = _body(request)
        try:
            return Response(svc.preview(store, str(d.get("text") or ""), d.get("engines") if isinstance(d.get("engines"), list) else None,
                                        depth=str(d.get("depth")) if d.get("depth") else None))
        except svc.PronError as exc:
            return _err(str(exc))


class ConvertView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, store_id):
        _store(request, store_id, write=False)
        try:
            return Response(svc.convert(str(_body(request).get("respelling") or "")))
        except svc.PronError as exc:
            return _err(str(exc))


# ------------------------------------------------------------------ listening (the test box)

class ListenView(APIView):
    """Piper and Edge answer in seconds; MOSS goes through the processing node's queue (durable)."""

    permission_classes = [IsAuthenticated]

    def post(self, request, store_id):
        store = _store(request, store_id, write=False)
        d = _body(request)
        text = str(d.get("text") or "").strip()[:600]
        engine = str(d.get("engine") or "piper")
        variant = "before" if d.get("variant") == "before" else "after"
        if not text:
            return _err("متنی بنویسید.")
        if engine not in svc.ENGINES:
            return _err("موتورِ نامعتبر.")
        depth = str(d.get("depth") or "") or None            # «try another depth»: this one recording only
        if depth is not None and depth not in fa_pron.DEPTHS:
            return _err("عمقِ نامعتبر.")
        from services.audio import tts

        if not tts.is_speakable(text):
            return _err(tts.NOTHING_TO_SPEAK, "empty", status.HTTP_422_UNPROCESSABLE_ENTITY)
        if engine == "edge" and engine_registry.local_only(store):
            return _err("سیاستِ دادهٔ این فروشگاه «فقط لوکال» است و Edge متن را به مایکروسافت می‌فرستد.", "policy", status.HTTP_409_CONFLICT)
        if engine == "moss":
            return self._moss(request, store, text, variant, depth)
        name = f"{uuid.uuid4().hex[:12]}.wav" if engine == "piper" else f"{uuid.uuid4().hex[:12]}.mp3"
        out = _audio_dir(store) / name
        try:
            if engine == "piper":
                provider = tts.PiperProvider(svc.site_piper_voice(str(d.get("voice") or "")))
            else:
                provider = tts.EdgeTTSProvider(voice=str(d.get("voice") or "fa-IR-DilaraNeural"))
            provider.store, provider.language, provider.use_pron = store, "fa", variant == "after"
            provider.depth_override = depth
            path = Path(provider.synthesize(text, out))
        except tts.NothingToSpeakError as exc:
            return _err(str(exc), "empty", status.HTTP_422_UNPROCESSABLE_ENTITY)
        except tts.TTSError as exc:
            return _err(str(exc), "tts", status.HTTP_502_BAD_GATEWAY)
        try:
            svc.cleanup_store_audio(store.pk)             # every click makes a file: keep only the recent ones
        except OSError:
            pass
        return Response({"state": "ready", "url": f"/stores/{store.pk}/pronunciation/audio/{path.name}",
                         "engine": engine, "variant": variant})

    def _moss(self, request, store, text, variant, depth=None):
        from apps.compute import services as compute
        from services.audio import node_audio, pronounce

        spoken = text
        if variant == "after":
            spoken = pronounce.text_for(text, "moss", store=store, depth=depth)
        try:
            job = node_audio.enqueue("moss", "voice.tts", {"text": spoken, "engine": "moss-fa", "voice": node_audio.default_preset("male"),
                                                           "out": "speech.wav", "strict": True},
                                     store=store, purpose="speech", origin="pron_listen", durable=True)
        except (node_audio.NodeAudioError, compute.ComputeUnavailable) as exc:
            return _err(str(exc), "node", status.HTTP_503_SERVICE_UNAVAILABLE)
        if _node_state()["online"]:
            message = "در صفِ سرورِ پردازش است؛ چند ثانیه بعد آماده می‌شود."
        else:
            message = ("سرورِ پردازشِ GPU الان خاموش است؛ این درخواست در صفِ ماندگار می‌ماند و با روشن شدنِ آن خودکار ساخته می‌شود "
                       "(صفحه را می‌توانید ببندید).")
        return Response({"state": "queued", "token": str(job.uid), "engine": "moss", "variant": variant, "message": message})


class ListenResultView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id, token):
        store = _store(request, store_id, write=False)
        from apps.compute import services as compute
        from apps.compute.models import ComputeJob

        try:
            uid = uuid.UUID(str(token))
        except ValueError:
            raise Http404 from None                   # not a job token at all: 404, not a database error
        job = ComputeJob.objects.filter(uid=uid, origin="pron_listen").first()
        if job is None or (job.store_id and job.store_id != store.pk):
            raise Http404
        if job.state == ComputeJob.State.FAILED:
            return Response({"state": "failed", "message": (job.error or "ناموفق")[:300]})
        if job.state != ComputeJob.State.COMPLETED:
            return Response({"state": "queued" if job.state == ComputeJob.State.QUEUED else "running", "message": job.message})
        src = compute.output_path(job, "speech.wav")
        if not src.is_file():
            return Response({"state": "failed", "message": "فایلِ صدا نرسید."})
        name = f"{uuid.uuid4().hex[:12]}.wav"
        dst = _audio_dir(store) / name
        dst.write_bytes(src.read_bytes())
        try:
            svc.cleanup_store_audio(store.pk)
        except OSError:
            pass
        return Response({"state": "ready", "url": f"/stores/{store.pk}/pronunciation/audio/{name}"})


class AudioFileView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id, name):
        store = _store(request, store_id, write=False)
        if not re.fullmatch(r"[0-9a-f]{12}\.(wav|mp3)", name):
            raise Http404
        p = _audio_dir(store) / name
        if not p.is_file():
            raise Http404
        return FileResponse(open(p, "rb"), content_type="audio/wav" if name.endswith(".wav") else "audio/mpeg")


# ------------------------------------------------------------------ lexicon

class SharedView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id):
        _store(request, store_id, write=False)
        q = request.query_params
        try:
            limit = max(1, min(600, int(q.get("limit") or 300)))
            offset = max(0, int(q.get("offset") or 0))
        except ValueError:
            limit, offset = 300, 0
        return Response(svc.shared_rows(q.get("q", ""), q.get("category", ""), limit, offset))


class LexiconView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id):
        store = _store(request, store_id, write=False)
        scope = request.query_params.get("scope", "store")
        qs = LexiconEntry.objects.filter(store=store) if scope == "store" else LexiconEntry.objects.filter(store__isnull=True)
        q = (request.query_params.get("q") or "").strip()
        if q:
            qs = qs.filter(word__icontains=q) | qs.filter(respelling__icontains=q)
        return Response({"scope": scope, "rows": [svc.entry_dict(e) for e in qs.order_by("word")[:500]]})

    def post(self, request, store_id):
        store = _store(request, store_id)
        d = _body(request)
        target = store
        if d.get("scope") == "global":
            if not request.user.is_staff:
                return _err("افزودنِ سراسری فقط برای کارمندِ سایت است.", "forbidden", status.HTTP_403_FORBIDDEN)
            target = None
        try:
            row = svc.save_entry(target, str(d.get("word") or ""), str(d.get("respelling") or ""), note=str(d.get("note") or ""),
                                 user=request.user)
        except svc.PronError as exc:
            return _err(str(exc))
        return Response(svc.entry_dict(row), status=status.HTTP_201_CREATED)


class LexiconItemView(APIView):
    permission_classes = [IsAuthenticated]

    def _row(self, request, store, pk):
        row = LexiconEntry.objects.filter(pk=pk).filter(store=store).first()
        if row is None and request.user.is_staff:
            row = LexiconEntry.objects.filter(pk=pk, store__isnull=True).first()
        return row

    def patch(self, request, store_id, pk):
        store = _store(request, store_id)
        row = self._row(request, store, pk)
        if row is None:
            raise Http404
        d = _body(request)
        if "enabled" in d and "respelling" not in d:
            row.enabled = bool(d["enabled"])
            row.save(update_fields=["enabled", "updated_at"])
            return Response(svc.entry_dict(row))
        try:
            row = svc.save_entry(row.store, str(d.get("word") or row.word), str(d.get("respelling") or row.respelling),
                                 note=str(d.get("note") if "note" in d else row.note), user=request.user, pk=row.pk)
        except svc.PronError as exc:
            return _err(str(exc))
        return Response(svc.entry_dict(row))

    def delete(self, request, store_id, pk):
        store = _store(request, store_id)
        row = self._row(request, store, pk)
        if row is None:
            raise Http404
        row.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# ------------------------------------------------------------------ problems

class ProblemsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id):
        store = _store(request, store_id, write=False)
        st = request.query_params.get("status", "open")
        svc.refresh_problems(store)
        qs = ProblemWord.objects.filter(store=store)
        if st != "all":
            qs = qs.filter(status=st)
        return Response({"rows": [svc.problem_dict(p) for p in qs[:300]]})

    def post(self, request, store_id):
        store = _store(request, store_id)
        d = _body(request)
        word = str(d.get("word") or "").strip()
        if not word:
            return _err("واژه را بنویسید.")
        svc.record_problems(store, [word], source="manual", engine=str(d.get("engine") or ""), context=str(d.get("context") or ""),
                            detail=str(d.get("detail") or ""))
        row = ProblemWord.objects.filter(store=store, source="manual").order_by("-updated_at").first()
        return Response(svc.problem_dict(row), status=status.HTTP_201_CREATED)


class ProblemItemView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, store_id, pk):
        store = _store(request, store_id)
        row = ProblemWord.objects.filter(store=store, pk=pk).first()
        if row is None:
            raise Http404
        d = _body(request)
        if d.get("respelling"):
            try:
                entry = svc.save_entry(store, row.word, str(d["respelling"]), user=request.user)
            except svc.PronError as exc:
                return _err(str(exc))
            row.refresh_from_db()
            return Response({"problem": svc.problem_dict(row), "entry": svc.entry_dict(entry)})
        if d.get("status") in ("open", "fixed", "ignored"):
            row.status = d["status"]
            row.save(update_fields=["status", "updated_at"])
        return Response({"problem": svc.problem_dict(row)})

    def delete(self, request, store_id, pk):
        store = _store(request, store_id)
        ProblemWord.objects.filter(store=store, pk=pk).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# ------------------------------------------------------------------ ezafe check

class EzafeCheckView(APIView):
    """GET: wrong / missing automatic ezafes on the hand-checked marketing sentences, before and after (the conservative rules)."""

    permission_classes = [IsAuthenticated]

    def get(self, request, store_id):
        _store(request, store_id, write=False)
        return Response(svc.ezafe_check())


# ------------------------------------------------------------------ eval

class EvalListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id):
        store = _store(request, store_id, write=False)
        svc.seed_baseline()
        evalrun.advance(limit=3)
        qs = EvalRun.objects.filter(Q(store=store) | Q(store__isnull=True)).order_by("-created_at")[:30]
        return Response({"runs": [svc.run_dict(r) for r in qs], "tags": fa_pron.eval_set.TAGS})

    def post(self, request, store_id):
        store = _store(request, store_id)
        d = _body(request)
        sample = "full" if d.get("sample") == "full" else "quick"
        if sample == "full" and not request.user.is_staff:
            return _err("سنجشِ کامل (همهٔ جمله‌های آزمون) فقط برای کارمندِ سایت است؛ سنجشِ سریع را بزنید.", "forbidden", status.HTTP_403_FORBIDDEN)
        try:
            run = evalrun.start(request.user, store, str(d.get("engine") or ""), voice=str(d.get("voice") or ""), sample=sample)
        except evalrun.EvalError as exc:
            return _err(str(exc))
        return Response(svc.run_dict(run), status=status.HTTP_201_CREATED)


class EvalItemView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id, pk):
        store = _store(request, store_id, write=False)
        run = EvalRun.objects.filter(Q(store=store) | Q(store__isnull=True), pk=pk).first()
        if run is None:
            raise Http404
        evalrun.advance_run(run)
        run.refresh_from_db()
        return Response(svc.run_dict(run, rows=True))

    def delete(self, request, store_id, pk):
        store = _store(request, store_id)
        for run in EvalRun.objects.filter(pk=pk, store=store, baseline=False):
            svc.remove_run_files(run.pk)                  # the run's audio files go with it
            run.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)




# ───────────────────────────────────────────────────────────── ready-made before/after samples (rendered on the server)

_SET_ID = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
_SAMPLE_FILE = re.compile(r"^[A-Za-z0-9_.-]{1,90}\.(mp3|wav)$")


def samples_root() -> Path:
    """Not under MEDIA_ROOT: that folder is served to everyone without a login. These files are for the signed-in owner only."""
    return Path(settings.NM_DATA_DIR) / "pron-samples"


def load_sample_sets(store_id) -> list[dict]:
    """Every set under ``pron-samples/<id>/manifest.json`` (newest first), with the audio URLs of this API filled in."""
    out = []
    root = samples_root()
    if not root.is_dir():
        return out
    for manifest in sorted(root.glob("*/manifest.json"), reverse=True):
        set_id = manifest.parent.name
        if not _SET_ID.match(set_id):
            continue
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        base = f"/stores/{store_id}/pronunciation/samples/{set_id}/"
        lines = []
        for ln in data.get("lines", []):
            files = {}
            for voice, per_variant in (ln.get("files") or {}).items():
                files[voice] = {variant: base + name for variant, name in per_variant.items()
                                if name and _SAMPLE_FILE.match(str(name)) and (manifest.parent / name).is_file()}
            lines.append({"group": ln.get("group", ""), "text": ln.get("text", ""), "spoken": ln.get("spoken", ""), "files": files})
        out.append({"id": set_id, "title": data.get("title", set_id), "note": data.get("note", ""), "created": data.get("created", ""),
                    "layer_version": data.get("layer_version", ""), "variants": data.get("variants", []), "voices": data.get("voices", []),
                    "lines": lines})
    return out


class SamplesView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id):
        _store(request, store_id, write=False)
        return Response({"sets": load_sample_sets(store_id)})


class SampleFileView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id, set_id, name):
        _store(request, store_id, write=False)
        if not _SET_ID.match(set_id) or not _SAMPLE_FILE.match(name):
            raise Http404
        p = samples_root() / set_id / name
        if not p.is_file():
            raise Http404
        return FileResponse(open(p, "rb"), content_type="audio/wav" if name.endswith(".wav") else "audio/mpeg")
