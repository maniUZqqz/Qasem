"""API ِ «فیلم‌برداریِ هدایت‌شده» (پنل › محتوا) و «عکس‌برداری با دوربین» (تعریفِ محصول).

    GET    stores/<id>/shoot/                                   محصول‌ها، جلسه‌ها، موسیقی‌ها، توانایی‌ها
    POST   stores/<id>/shoot/sessions/                          {product, purpose: photos|ad, analyze}
    GET|PATCH|DELETE stores/<id>/shoot/sessions/<pk>/           PATCH {plan}
    POST   stores/<id>/shoot/sessions/<pk>/analyze/             تحلیلِ دوباره (هوش مصنوعی ⇐ الگو)
    POST   stores/<id>/shoot/sessions/<pk>/voice/               ساختِ صدای راهنما
    GET    stores/<id>/shoot/sessions/<pk>/upload/?upload_id=   چقدر رسیده (ادامهٔ آپلود)
    POST   stores/<id>/shoot/sessions/<pk>/upload/              multipart: chunk + upload_id, offset, total, kind, shot, name, mode
    PATCH|DELETE stores/<id>/shoot/sessions/<pk>/takes/<tid>/   PATCH {accepted}
    POST   stores/<id>/shoot/sessions/<pk>/save-photos/         بهترین عکسِ هر زاویه ⇐ عکس‌های محصول (به ترتیب)
    POST   stores/<id>/shoot/sessions/<pk>/outputs/             {kind: video|poster, aspects, template, options}
    DELETE stores/<id>/shoot/sessions/<pk>/outputs/<oid>/
    POST   stores/<id>/shoot/sessions/<pk>/outputs/<oid>/<product|content|editor>/
"""
from __future__ import annotations

import logging

from rest_framework import status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.stores import access

from . import media, poster, render, services
from . import plan as planmod
from .models import ShootOutput, ShootSession, ShootTake
from .tasks import analyze_task, render_poster_task, render_video_task, voice_task

logger = logging.getLogger(__name__)


def _err(message: str, code: str = "shoot", http=status.HTTP_400_BAD_REQUEST, **extra):
    return Response({"error": {"code": code, "message": message}, **extra}, status=http)


def _shoot_err(exc: services.ShootError):
    return _err(str(exc), exc.code, exc.status, **exc.extra)


def _dispatch(task, *args) -> None:
    from apps.jobs.services import broker_reachable, eager_mode

    if not eager_mode() and broker_reachable():
        try:
            task.delay(*args)
            return
        except Exception:  # noqa: BLE001
            logger.warning("shoot: celery dispatch of %s failed; running inline", task.name)
    task(*args)


def _perm(purpose: str) -> str:
    return access.PRODUCTS if purpose == ShootSession.Purpose.PHOTOS else access.CONTENT


def _session(request, store_id, pk, *, write: bool):
    store = access.get_store(request.user, store_id, None, write=False)
    session = ShootSession.objects.filter(store=store, pk=pk).select_related("product", "store").first()
    if session is None:
        return None, _err("جلسه پیدا نشد.", "not_found", status.HTTP_404_NOT_FOUND)
    if not access.can(request.user, store, _perm(session.purpose), write=write):
        return None, _err("نقشِ شما در این فروشگاه اجازهٔ این کار را ندارد.", "forbidden", status.HTTP_403_FORBIDDEN)
    return session, None


def _bool(v, default=False) -> bool:
    if v is None:
        return default
    if isinstance(v, bool):
        return v
    return str(v).lower() in ("1", "true", "yes", "on")


def _texts(raw) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    out = {}
    for key, limit in (("title", 60), ("price", 40), ("old_price", 40), ("cta", 40)):
        if key in raw:
            out[key] = str(raw.get(key) or "").strip()[:limit]
    if isinstance(raw.get("features"), list):
        out["features"] = [str(f).strip()[:60] for f in raw["features"] if str(f).strip()][:5]
    return out


class OverviewView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id):
        from apps.ai.models import AudioAsset
        from apps.photoedit import services as photo_services

        store = access.get_store(request.user, store_id, None, write=False)
        sessions = ShootSession.objects.filter(store=store).select_related("product")[:30]
        products = []
        for p in store.products.prefetch_related("images").order_by("-created_at")[:200]:
            first = next(iter(p.images.all()), None)
            products.append({"id": p.pk, "name": p.name, "price": str(p.price),
                             "thumb": first.image.url if first else None, "images": len(p.images.all())})
        music = [{"id": a.pk, "title": a.title or a.text[:40] or f"موسیقی {a.pk}", "seconds": round(a.duration, 1),
                  "saved": a.saved}
                 for a in AudioAsset.objects.filter(store=store, kind=AudioAsset.Kind.MUSIC,
                                                    status=AudioAsset.Status.READY).order_by("-saved", "-created_at")[:50]]
        try:
            node = photo_services.node_status()
        except Exception:  # noqa: BLE001
            node = {"online": False, "nodes": []}
        return Response({
            "sessions": [services.session_dict(s, full=False) for s in sessions],
            "products": products, "music": music,
            "capabilities": media.capabilities() | {"node_online": node["online"]},
            "templates": [{"key": k, "title": v} for k, v in poster.TEMPLATES.items()],
            "aspects": {"video": ["9:16", "1:1"], "poster": ["1:1", "4:5", "9:16"]},
            "transitions": [{"key": "fade", "title": "محوِ نرم"}, {"key": "slide", "title": "کشویی"},
                            {"key": "zoom", "title": "زوم"}, {"key": "none", "title": "بی‌گذار (برش)"}],
            "angles": [{"key": k, "title": v["title"]} for k, v in planmod.ANGLES.items()],
            "moves": [{"key": k, "title": v["title"]} for k, v in planmod.MOVES.items()],
            "categories": [{"key": k, "title": v} for k, v in planmod.CATEGORIES.items()],
            "disk": services.media_free_note(),
        })


class SessionListView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, store_id):
        purpose = str(request.data.get("purpose") or "ad")
        perm = _perm(purpose)
        store = access.get_store(request.user, store_id, perm, write=True)
        try:
            product = store.products.get(pk=int(request.data.get("product")))
        except (TypeError, ValueError, store.products.model.DoesNotExist):
            return _err("محصول را انتخاب کنید.", "no_product")
        reuse = _bool(request.data.get("reuse"))
        if reuse:
            # دکمهٔ «عکس‌برداری با دوربین»: جلسهٔ عکسِ نیمه‌کارهٔ همین محصول ادامه پیدا می‌کند
            old = ShootSession.objects.filter(store=store, product=product, purpose=purpose).first()
            if old is not None:
                return Response(services.session_dict(old))
        analyze = _bool(request.data.get("analyze"), True)
        session = services.create_session(store, product, request.user, purpose=purpose, analyze=analyze)
        if analyze:
            _dispatch(analyze_task, session.pk)
            session.refresh_from_db()
        return Response(services.session_dict(session), status=status.HTTP_201_CREATED)


class SessionView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser]

    def get(self, request, store_id, pk):
        session, err = _session(request, store_id, pk, write=False)
        if err:
            return err
        return Response(services.session_dict(session))

    def patch(self, request, store_id, pk):
        session, err = _session(request, store_id, pk, write=True)
        if err:
            return err
        if "plan" not in request.data:
            return _err("برنامه فرستاده نشد.", "no_plan")
        problems = services.save_plan(session, request.data["plan"])
        return Response(services.session_dict(session) | {"problems": problems})

    def delete(self, request, store_id, pk):
        session, err = _session(request, store_id, pk, write=True)
        if err:
            return err
        services.delete_session(session)
        return Response(status=status.HTTP_204_NO_CONTENT)


class SessionActionView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, store_id, pk, action):
        session, err = _session(request, store_id, pk, write=True)
        if err:
            return err
        if action == "analyze":
            session.state, session.message = ShootSession.State.ANALYZING, "در حالِ تحلیلِ محصول…"
            session.save(update_fields=["state", "message", "updated_at"])
            _dispatch(analyze_task, session.pk)
        elif action == "voice":
            session.voice = {"state": "RUNNING", "clips": (session.voice or {}).get("clips") or {}}
            session.save(update_fields=["voice", "updated_at"])
            _dispatch(voice_task, session.pk)
        elif action == "save-photos":
            made = services.save_photos_to_product(session)
            return Response({"created": made, "session": services.session_dict(session)})
        else:
            return _err("کارِ ناشناخته.", "bad_action", status.HTTP_404_NOT_FOUND)
        session.refresh_from_db()
        return Response(services.session_dict(session))


class UploadView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def get(self, request, store_id, pk):
        session, err = _session(request, store_id, pk, write=True)
        if err:
            return err
        try:
            return Response({"received": services.received(session, request.query_params.get("upload_id", ""))})
        except services.ShootError as exc:
            return _shoot_err(exc)

    def post(self, request, store_id, pk):
        session, err = _session(request, store_id, pk, write=True)
        if err:
            return err
        d = request.data
        kind = str(d.get("kind") or "")
        if kind not in ShootTake.Kind.values:
            return _err("نوعِ برداشت باید photo یا video باشد.", "bad_kind")
        try:
            offset, total = int(d.get("offset", 0)), int(d.get("total", 0))
        except (TypeError, ValueError):
            return _err("اندازه‌ها درست نیست.", "bad_size")
        upload_id = str(d.get("upload_id") or "")
        try:
            size = services.receive_chunk(session, upload_id=upload_id, offset=offset, total=total, kind=kind,
                                          chunk=request.FILES.get("chunk"))
            if size < total:
                return Response({"received": size})
            take = services.finalize(session, upload_id=upload_id, shot_key=str(d.get("shot") or ""), kind=kind,
                                     name=str(d.get("name") or ""), mode=str(d.get("mode") or "upload"),
                                     vision=_bool(d.get("vision"), True))
        except services.ShootError as exc:
            return _shoot_err(exc)
        return Response({"received": size, "take": services.take_dict(take)}, status=status.HTTP_201_CREATED)


class TakeView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser]

    def _take(self, request, store_id, pk, tid):
        session, err = _session(request, store_id, pk, write=True)
        if err:
            return None, err
        take = session.takes.filter(pk=tid).first()
        if take is None:
            return None, _err("برداشت پیدا نشد.", "not_found", status.HTTP_404_NOT_FOUND)
        return take, None

    def patch(self, request, store_id, pk, tid):
        take, err = self._take(request, store_id, pk, tid)
        if err:
            return err
        if "accepted" in request.data:
            take.accepted = _bool(request.data.get("accepted"))
            take.save(update_fields=["accepted", "updated_at"])
        return Response(services.take_dict(take))

    def delete(self, request, store_id, pk, tid):
        take, err = self._take(request, store_id, pk, tid)
        if err:
            return err
        services.delete_take(take)
        return Response(status=status.HTTP_204_NO_CONTENT)


class OutputListView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser]

    def post(self, request, store_id, pk):
        session, err = _session(request, store_id, pk, write=True)
        if err:
            return err
        d = request.data
        kind = str(d.get("kind") or "")
        raw = d.get("options") if isinstance(d.get("options"), dict) else {}
        template = str(d.get("template") or ("bold" if kind == "video" else "clean"))
        if template not in poster.TEMPLATES:
            template = "clean"
        if kind == ShootOutput.Kind.VIDEO:
            allowed = ("9:16", "1:1")
            music = raw.get("music")
            try:
                music = int(music) if music not in (None, "", 0, "0") else None
            except (TypeError, ValueError):
                music = None
            try:
                level = max(-40.0, min(-10.0, float(raw.get("music_level_db", -24))))
            except (TypeError, ValueError):
                level = -24.0
            options = {
                "stabilize": _bool(raw.get("stabilize"), True),
                "transition": raw.get("transition") if raw.get("transition") in render.TRANSITIONS else "fade",
                "music": music, "music_level_db": level,
                "voiceover": _bool(raw.get("voiceover"), False),
                "voiceover_text": str(raw.get("voiceover_text") or "").strip()[:600],
                "template": template, "logo": _bool(raw.get("logo"), True), "texts": _texts(raw.get("texts")),
            }
            task = render_video_task
        elif kind == ShootOutput.Kind.POSTER:
            allowed = ("1:1", "4:5", "9:16")
            take = raw.get("take")
            try:
                take = int(take) if take not in (None, "", 0, "0") else None
            except (TypeError, ValueError):
                take = None
            options = {"cutout": _bool(raw.get("cutout"), True), "take": take,
                       "logo": _bool(raw.get("logo"), True), "texts": _texts(raw.get("texts"))}
            task = render_poster_task
        else:
            return _err("نوعِ خروجی باید video یا poster باشد.", "bad_kind")
        aspects = [a for a in (d.get("aspects") or [allowed[0]]) if a in allowed]
        if not aspects:
            return _err("دست‌کم یک اندازه انتخاب کنید.", "no_aspect")
        if not session.takes.filter(accepted=True).exists():
            return _err("هنوز هیچ برداشتِ پذیرفته‌ای نیست؛ اول عکس یا فیلم بگیرید.", "no_takes")
        made = []
        for aspect in dict.fromkeys(aspects):
            out = services.new_output(session, kind=kind, aspect=aspect, template=template, options=options)
            made.append(out)
        for out in made:
            _dispatch(task, out.pk, request.user.pk)
        session.refresh_from_db()
        return Response(services.session_dict(session), status=status.HTTP_201_CREATED)


class OutputView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser]

    def _output(self, request, store_id, pk, oid):
        session, err = _session(request, store_id, pk, write=True)
        if err:
            return None, err
        out = session.outputs.filter(pk=oid).first()
        if out is None:
            return None, _err("خروجی پیدا نشد.", "not_found", status.HTTP_404_NOT_FOUND)
        return out, None

    def delete(self, request, store_id, pk, oid):
        out, err = self._output(request, store_id, pk, oid)
        if err:
            return err
        services.delete_output(out)
        return Response(status=status.HTTP_204_NO_CONTENT)

    def post(self, request, store_id, pk, oid, action):
        out, err = self._output(request, store_id, pk, oid)
        if err:
            return err
        try:
            if action == "product":
                result = services.output_to_product(out)
            elif action == "content":
                result = services.output_to_content(out)
            elif action == "editor":
                result = services.output_to_editor(out)
            else:
                return _err("کارِ ناشناخته.", "bad_action", status.HTTP_404_NOT_FOUND)
        except services.ShootError as exc:
            return _shoot_err(exc)
        out.refresh_from_db()
        return Response({"result": result, "output": services.output_dict(out)})
