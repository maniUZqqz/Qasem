"""شخصیتِ برند — API پنل (همه زیرِ ``stores/<id>/brand-character/``؛ دسترسی = همان «محتوا»: خواندن برای اعضا، نوشتن برای مالک/مدیر/بازاریابی/مدیر محتوا).

    GET    /                                  ⇐ نمای کلی: شخصیتِ گفتار، شخصیت‌های دیداری، گزینه‌ها، کاربردها
    persona/  GET · PUT · draft/ (جادوگر) · lock/ · unlock/ · active/ · versions/ · restore/ · prompt/
    characters/  GET · POST (نقش/سبک/سند یا از ماسکوت)   <id>/  GET · PATCH · DELETE
        lock/ unlock/ primary/ publish-mascot/ check/ versions/ restore/  — preview/ svg/ render/ sticker/ sheet/ sheet-pdf/ svg-file/ export/ — renders/ …
        ai-render/ ai-jobs/  (کارِ ComfyUI روی سرورِ پردازش؛ در صفِ ماندگار)
    concepts/ (توضیحِ فارسی ⇒ ایده‌ها) · concepts/<id>/choose/
    templates/ · templates/<tid>/render/ · usage/ · use/{motion,thumbnail,site-hero,director,inbox}/ · node/
"""
from __future__ import annotations

import logging

from django.http import FileResponse, Http404, HttpResponse
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.mascot import services as MS
from apps.photoedit import services as photo
from apps.stores import access

from . import ai_render, concepts, persona as P, persona_ai, persona_store, services, templates, usage
from .models import BrandCharacter, CharacterAIJob, CharacterConcept, CharacterRender

logger = logging.getLogger(__name__)


def _err(message: str, code: str = "brandchar", http=status.HTTP_400_BAD_REQUEST, **extra):
    return Response({"error": {"code": code, "message": message, **extra}}, status=http)


def _store(request, store_id, write: bool = True):
    return access.get_store(request.user, store_id, access.CONTENT, write=write)


def _char(store, pk) -> BrandCharacter | None:
    return BrandCharacter.objects.filter(store=store, pk=pk).select_related("store").first()


def _nf():
    return _err("پیدا نشد.", "not_found", status.HTTP_404_NOT_FOUND)


def _body(request) -> dict:
    return request.data if isinstance(request.data, dict) else {}


def _run(fn, *args, **kw):
    """خطای کاربر ⇒ ۴۰۰؛ ادعا ⇒ ۴۲۲ با فهرستِ ادعاها."""
    try:
        return fn(*args, **kw), None
    except services.ClaimsError as exc:
        return None, _err(str(exc), "claims", status.HTTP_422_UNPROCESSABLE_ENTITY, found=exc.found)
    except (services.CharError, persona_store.PersonaError, ai_render.AIRenderError, MS.MascotError, photo.PhotoError) as exc:
        return None, _err(str(exc))


def _render_response(out):
    row, cached = out
    return Response(services.render_dict(row, cached=cached), status=status.HTTP_200_OK if cached else status.HTTP_201_CREATED)


class Base(APIView):
    permission_classes = [IsAuthenticated]


# ───────────────────────────── نمای کلی

class OverviewView(Base):
    def get(self, request, store_id):
        return Response(services.overview(_store(request, store_id, write=False)))


class NodeView(Base):
    def get(self, request, store_id):
        _store(request, store_id, write=False)
        return Response(ai_render.node_status())


# ───────────────────────────── شخصیتِ گفتار

class PersonaView(Base):
    def get(self, request, store_id):
        store = _store(request, store_id, write=False)
        return Response({**persona_store.public(persona_store.get(store)), "archetypes": [{"key": k, "fa": v["fa"], "en": v["en"], "about": v["about"], "tone": dict(zip(P.TONE_KEYS, v["tone"])),
                                                                                           "values": v["values"]} for k, v in P.ARCHETYPES.items()],
                         "sliders": [{"key": k, "label": v[0], "low": v[1], "high": v[2]} for k, v in P.TONE_SLIDERS.items()],
                         "emoji_policies": [{"key": k, "fa": v} for k, v in P.EMOJI_POLICIES.items()], "address": [{"key": k, "fa": v} for k, v in P.ADDRESS.items()],
                         "situations": [{"key": k, "fa": v} for k, v in P.SITUATION_FA.items()], "limits": P.LIMITS, "voices": _voices(store)})

    def put(self, request, store_id):
        store = _store(request, store_id)
        d = _body(request)
        row, err = _run(persona_store.save, store, request.user, d.get("data") if isinstance(d.get("data"), dict) else d, source=str(d.get("source") or "manual"),
                        active=d.get("active") if isinstance(d.get("active"), bool) else None, note=str(d.get("note") or ""))
        return err or Response(persona_store.public(row))


def _voices(store) -> list[dict]:
    """گوینده‌های موجود برای انتخابِ صدا: همان فهرستِ صفحهٔ «گفتار» (MOSS فارسی، صداهای کلون‌شدهٔ همین فروشگاه، Piper) + دو صدای پیش‌فرض (فرید و دلارا)؛ فقط آن‌هایی که الان آماده‌اند
    با برچسبِ گروه. هر شکستی ⇒ همان دو صدای پیش‌فرض (صفحه هرگز به‌خاطرِ صدا نمی‌ایستد)."""
    out: list[dict] = []
    try:
        from services.audio import profile as AP

        for key, v in AP.PERSIAN_VOICES.items():
            out.append({"id": v["id"], "name": v["label"], "gender": key, "group": "صدای پیش‌فرض", "available": True})
    except Exception:  # noqa: BLE001
        pass
    try:
        from services.audio import studio

        for v in studio.voices(store):
            out.append({"id": v.get("id"), "name": v.get("name"), "gender": v.get("gender", ""), "group": v.get("group", ""), "available": bool(v.get("available", True)), "why": v.get("why", "")})
    except Exception:  # noqa: BLE001
        logger.debug("brandchar: studio voices unavailable", exc_info=True)
    return [v for v in out if v.get("id")]


class PersonaDraftView(Base):
    def post(self, request, store_id):
        store = _store(request, store_id)
        d = _body(request)
        out = persona_ai.draft(store, brief=str(d.get("brief") or ""), use_ai=bool(d.get("use_ai", True)))
        return Response({"persona": out["persona"], "sources": out["sources"], "notes": out["notes"], "origin": out["origin"], "ai": out["ai"], "score": P.filled_score(out["persona"])})


class PersonaLockView(Base):
    def post(self, request, store_id):
        store = _store(request, store_id)
        row, err = _run(persona_store.lock, store, request.user, str(_body(request).get("note") or ""))
        return err or Response(persona_store.public(row))


class PersonaUnlockView(Base):
    def post(self, request, store_id):
        store = _store(request, store_id)
        return Response(persona_store.public(persona_store.unlock(store)))


class PersonaActiveView(Base):
    def post(self, request, store_id):
        store = _store(request, store_id)
        row, err = _run(persona_store.set_active, store, bool(_body(request).get("active")))
        return err or Response(persona_store.public(row))


class PersonaVersionsView(Base):
    def get(self, request, store_id):
        return Response({"items": persona_store.versions(_store(request, store_id, write=False))})


class PersonaRestoreView(Base):
    def post(self, request, store_id):
        store = _store(request, store_id)
        try:
            ver = int(_body(request).get("version"))
        except (TypeError, ValueError):
            return _err("شمارهٔ نسخه درست نیست.")
        row, err = _run(persona_store.restore, store, request.user, ver)
        return err or Response(persona_store.public(row))


class PersonaPromptView(Base):
    def get(self, request, store_id):
        store = _store(request, store_id, write=False)
        kind = request.query_params.get("kind") or "caption"
        return Response(persona_store.prompt_preview(store, kind))


# ───────────────────────────── شخصیت‌های دیداری

class CharactersView(Base):
    def get(self, request, store_id):
        store = _store(request, store_id, write=False)
        return Response({"items": [services.character_dict(c) for c in BrandCharacter.objects.filter(store=store)]})

    def post(self, request, store_id):
        store = _store(request, store_id)
        d = _body(request)
        if d.get("from_mascot"):
            from apps.mascot.models import Mascot

            m = Mascot.objects.filter(store=store, pk=d["from_mascot"]).first()
            if m is None:
                return _nf()
            c, err = _run(services.from_mascot, store, request.user, m)
        else:
            brand = d.get("brand_colours") if isinstance(d.get("brand_colours"), list) else None
            c, err = _run(services.create, store, request.user, role=str(d.get("role") or "coach"), name=str(d.get("name") or ""), style=str(d.get("style") or "flat"),
                          use_logo=bool(d.get("use_logo", True)), brand=brand, doc=d.get("doc") if isinstance(d.get("doc"), dict) else None)
        return err or Response(services.character_dict(c), status=status.HTTP_201_CREATED)


class CharacterView(Base):
    def get(self, request, store_id, pk):
        c = _char(_store(request, store_id, write=False), pk)
        return Response(services.character_dict(c)) if c else _nf()

    def patch(self, request, store_id, pk):
        c = _char(_store(request, store_id), pk)
        if c is None:
            return _nf()
        out, err = _run(services.update, c, _body(request))
        return err or Response(services.character_dict(out))

    def delete(self, request, store_id, pk):
        c = _char(_store(request, store_id), pk)
        if c is None:
            return _nf()
        services.delete(c)
        return Response(status=status.HTTP_204_NO_CONTENT)


def _action(fn, *, write: bool = True, user: bool = False, body: bool = False, response=None):
    """یک نمای POST روی یک شخصیت: ``fn(c[, user][, body])``."""
    class V(Base):
        def post(self, request, store_id, pk):
            c = _char(_store(request, store_id, write=write), pk)
            if c is None:
                return _nf()
            args = [c] + ([request.user] if user else []) + ([_body(request)] if body else [])
            out, err = _run(fn, *args)
            if err:
                return err
            return response(out) if response else Response(out)

    return V


def _char_resp(c):
    return Response(services.character_dict(c))


LockView = _action(lambda c, u: services.lock(c, u), user=True, response=_char_resp)
UnlockView = _action(services.unlock, response=_char_resp)
PrimaryView = _action(services.set_primary, response=_char_resp)
CheckView = _action(services.run_check)
PreviewView = _action(services.preview, write=False, body=True)
SvgView = _action(services.figure_svg, write=False, body=True)
RenderView = _action(services.render_shot, user=True, body=True, response=_render_response)
StickerView = _action(services.render_sticker, user=True, body=True, response=_render_response)
SheetView = _action(services.render_sheet, user=True, response=_render_response)
SheetPdfView = _action(services.render_pdf, user=True, response=_render_response)
SvgFileView = _action(services.render_svg, user=True, body=True, response=_render_response)
PublishMascotView = _action(lambda c: {"mascot": services.publish_mascot(c)})


class RestoreView(Base):
    def post(self, request, store_id, pk):
        c = _char(_store(request, store_id), pk)
        if c is None:
            return _nf()
        try:
            ver = int(_body(request).get("version"))
        except (TypeError, ValueError):
            return _err("شمارهٔ نسخه درست نیست.")
        out, err = _run(services.restore, c, ver)
        return err or _char_resp(out)


class VersionsView(Base):
    def get(self, request, store_id, pk):
        c = _char(_store(request, store_id, write=False), pk)
        return Response({"items": services.versions(c)}) if c else _nf()


class ExportView(Base):
    def post(self, request, store_id, pk):
        c = _char(_store(request, store_id), pk)
        if c is None:
            return _nf()
        data, err = _run(services.export_pack, c, request.user)
        if err:
            return err
        resp = HttpResponse(data, content_type="application/zip")
        resp["Content-Disposition"] = f'attachment; filename="brand-character-{c.pk}.zip"'
        return resp


class RendersView(Base):
    def get(self, request, store_id, pk):
        c = _char(_store(request, store_id, write=False), pk)
        if c is None:
            return _nf()
        qs = c.renders.select_related("asset")
        kind = request.query_params.get("kind")
        if kind in ("shot", "sticker", "sheet", "svg", "pdf", "ai", "template"):
            qs = qs.filter(kind=kind)
        try:
            limit = max(1, min(120, int(request.query_params.get("limit") or 48)))
        except ValueError:
            limit = 48
        return Response({"items": [services.render_dict(r) for r in qs[:limit]]})


def _render(store, pk, rid) -> CharacterRender | None:
    return CharacterRender.objects.filter(store=store, character_id=pk, pk=rid).select_related("asset", "character").first()


class RenderItemView(Base):
    def get(self, request, store_id, pk, rid):
        r = _render(_store(request, store_id, write=False), pk, rid)
        return Response(services.render_dict(r)) if r else _nf()

    def delete(self, request, store_id, pk, rid):
        r = _render(_store(request, store_id), pk, rid)
        if r is None:
            return _nf()
        r.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class RenderDownloadView(Base):
    def get(self, request, store_id, pk, rid):
        r = _render(_store(request, store_id, write=False), pk, rid)
        if r is None:
            raise Http404()
        if r.file:
            data = services.read_file(r)
            if data is None:
                raise Http404()
            ctype = "application/pdf" if r.file.endswith(".pdf") else "image/svg+xml"
            resp = HttpResponse(data, content_type=ctype)
            resp["Content-Disposition"] = f'attachment; filename="brand-character-{r.kind}-{r.pk}.{r.file.rsplit(".", 1)[-1]}"'
            return resp
        if r.asset is None:
            raise Http404()
        p = photo.abs_path(r.asset.original)
        if not p.is_file():
            raise Http404()
        return FileResponse(open(p, "rb"), content_type="image/png", as_attachment=True, filename=f"brand-character-{r.kind}-{r.pk}.png")


# ───────────────────────────── ایده و هوش مصنوعی

class ConceptsView(Base):
    def get(self, request, store_id):
        store = _store(request, store_id, write=False)
        return Response({"items": [_concept_dict(c) for c in CharacterConcept.objects.filter(store=store)[:12]]})

    def post(self, request, store_id):
        store = _store(request, store_id)
        d = _body(request)
        desc = str(d.get("description") or "").strip()
        if len(desc) < 3:
            return _err("شخصیت را با چند کلمه توصیف کنید؛ مثلاً «مربیِ خندانِ موبلند با هدبندِ فیروزه‌ای و دمبل».")
        logo = services.store_logo(store) is not None
        out = concepts.generate(store, desc, logo=logo, use_ai=bool(d.get("use_ai", True)))
        row = CharacterConcept.objects.create(store=store, created_by=request.user, description=desc[:600], options=out["options"], source=out["source"], note=out["note"][:240])
        return Response(_concept_dict(row, store=store, previews=True), status=status.HTTP_201_CREATED)


def _concept_dict(row: CharacterConcept, *, store=None, previews: bool = False) -> dict:
    opts = []
    for i, o in enumerate(row.options or []):
        item = {"index": i, "title": o.get("title"), "why": o.get("why"), "source": o.get("source"), "doc": o.get("doc")}
        if previews:
            item["preview"] = _concept_preview(row.store, o.get("doc") or {})
        opts.append(item)
    return {"id": row.pk, "description": row.description, "options": opts, "source": row.source, "note": row.note, "chosen": row.chosen, "character": row.character_id, "created_at": row.created_at}


def _concept_preview(store, doc: dict) -> str:
    """کوچک‌ترین پیش‌نمایش (PNG شفافِ ۲۸۰ پیکسل، base64) برای کارتِ ایده."""
    import base64
    import io

    from .engine import render as R

    logo = services.store_logo(store) if doc.get("logo") == "chest" else None
    with services._slots:
        img, _ = R.sticker(doc, pose="wave", expression="happy", logo=logo, height_px=420)
    img.thumbnail((280, 340))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


class ConceptChooseView(Base):
    def post(self, request, store_id, cid):
        store = _store(request, store_id)
        row = CharacterConcept.objects.filter(store=store, pk=cid).first()
        if row is None:
            return _nf()
        d = _body(request)
        try:
            idx = int(d.get("index"))
            opt = row.options[idx]
        except (TypeError, ValueError, IndexError):
            return _err("ایده‌ای که انتخاب کردید پیدا نشد.")
        c, err = _run(services.create, store, request.user, role=str(opt.get("role") or "coach"), name=str(d.get("name") or opt.get("title") or ""), doc=opt["doc"],
                      concept={"title": opt.get("title"), "description": row.description, "source": opt.get("source")})
        if err:
            return err
        row.chosen, row.character = idx, c
        row.save(update_fields=["chosen", "character", "updated_at"])
        sheet, err = _run(services.render_sheet, c, request.user)
        out = {"character": services.character_dict(c)}
        if not err:
            out["sheet"] = services.render_dict(sheet[0], cached=sheet[1])
        return Response(out, status=status.HTTP_201_CREATED)


class AIRenderView(Base):
    def post(self, request, store_id, pk):
        c = _char(_store(request, store_id), pk)
        if c is None:
            return _nf()
        d = _body(request)
        row, err = _run(ai_render.start, c, request.user, mode=str(d.get("mode") or "illustrated"), look=str(d.get("look") or ""), extra=str(d.get("extra") or ""), pose=str(d.get("pose") or "stand"),
                        expression=str(d.get("expression") or "happy"))
        return err or Response(ai_render.job_dict(row), status=status.HTTP_201_CREATED)


class AIJobsView(Base):
    def get(self, request, store_id, pk):
        c = _char(_store(request, store_id, write=False), pk)
        if c is None:
            return _nf()
        rows = [ai_render.refresh(r) for r in CharacterAIJob.objects.filter(character=c).select_related("asset", "sticker_asset")[:20]]
        return Response({"items": [ai_render.job_dict(r) for r in rows], "node": ai_render.node_status()})


# ───────────────────────────── قالب‌ها و کاربردها

class TemplatesView(Base):
    def get(self, request, store_id):
        store = _store(request, store_id, write=False)
        c = services.primary(store)
        if c is None:
            return Response({"items": [], "character": None})
        return Response({"items": templates.listing(c, services.persona_data(store)), "character": c.pk})


class TemplateRenderView(Base):
    def post(self, request, store_id, tid):
        store = _store(request, store_id)
        d = _body(request)
        c = BrandCharacter.objects.filter(store=store, pk=d.get("character")).first() if d.get("character") else services.primary(store)
        if c is None:
            return _err("اول یک شخصیتِ دیداری بسازید.")
        if tid not in templates.BY_ID:
            return _nf()
        out, err = _run(templates.render, c, request.user, tid, d)
        return err or _render_response(out)


class UsageView(Base):
    def get(self, request, store_id):
        store = _store(request, store_id, write=False)
        return Response({**usage.summary(store), "recent": usage.recent(store)})


def _use(fn):
    class V(Base):
        def post(self, request, store_id):
            store = _store(request, store_id)
            d = _body(request)
            c = BrandCharacter.objects.filter(store=store, pk=d.get("character")).first() if d.get("character") else services.primary(store)
            if c is None:
                return _err("اول یک شخصیتِ دیداری بسازید.")
            out, err = _run(fn, c, request.user, d)
            return err or Response(out)

    return V


UseMotionView = _use(lambda c, u, d: usage.motion_scene(c, u, action=str(d.get("action") or "wave"), text=str(d.get("text") or ""), enter=str(d.get("enter") or "left"),
                                                        side=str(d.get("side") or "right"), duration=float(d.get("duration") or 6)))
UseThumbnailView = _use(lambda c, u, d: usage.thumbnail_subject(c, u, pose=str(d.get("pose") or "thumbs_up"), expression=str(d.get("expression") or "happy")))
UseSiteHeroView = _use(lambda c, u, d: usage.site_hero(c, u, project_slug=str(d.get("project_slug") or ""), pose=str(d.get("pose") or "wave")))
UseDirectorView = _use(lambda c, u, d: usage.director_overlay(c, u))


class UseInboxView(Base):
    def get(self, request, store_id):
        try:
            store = access.get_store(request.user, store_id, access.CONVERSATIONS, write=False)
        except Exception:  # noqa: BLE001 — اگر دسترسیِ گفت‌وگو نداشت، دسترسیِ محتوا هم کافی است
            store = _store(request, store_id, write=False)
        return Response(usage.inbox_card(store, request.user))
