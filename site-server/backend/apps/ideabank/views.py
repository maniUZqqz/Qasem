"""بانکِ ایده — API پنل (همه زیرِ ``stores/<id>/ideas/``، دسترسیِ «محتوا»).

    GET   /                      ⇐ فهرست + فیلتر (q، category، tag، fmt، channel، favorite، source=builtin|mine، hidden، needs_data، product) + شمارنده‌ها +
                                   پروفایلِ فروشگاه، محصول‌ها، کمپین‌ها و وضعیتِ هوش مصنوعی
    POST  /                      ⇐ ایدهٔ تازهٔ خودِ فروشگاه {category, format, channel, tags, title, logline, hook, shoot, cta}
    GET   random/?category=      ⇐ یک ایدهٔ تصادفی
    POST  generate/              ⇐ «ایده بساز» {category?, count, topic, instruction, facts[], product, ai, variation, save} ⇒ {via, ai, message, ideas}
    POST  from-trend/            ⇐ «ذخیره در بانکِ ایده» {trend_idea | cluster}
    GET|PATCH|DELETE <key>/      ⇐ یک ایده (آماده‌ها فقط‌خواندنی‌اند)
    POST  <key>/duplicate/       ⇐ کپی برای ویرایش
    POST  <key>/mark/            ⇐ {favorite?, hidden?}
    POST  <key>/start/           ⇐ «از این ایده شروع کن» {target: studio|calendar|thumbnail, product?, campaign?, due?}
"""
from __future__ import annotations

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.stores import access

from . import ai, bank, fill, generator, handoff
from .catalog import TARGETS

def _err(message: str, code: str = "ideabank", http=status.HTTP_400_BAD_REQUEST):
    return Response({"error": {"code": code, "message": message}}, status=http)


def _bank_err(exc: bank.BankError):
    return _err(exc.message, exc.code, exc.status)


def _store(request, store_id, write: bool = True, permission=access.CONTENT):
    return access.get_store(request.user, store_id, permission, write=write)


def _flag(v) -> bool:
    return str(v).lower() in ("1", "true", "yes", "on")


def _int(v, default: int) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _product(store, raw):
    if raw in (None, "", "0", 0):
        return None
    from apps.products.models import Product

    try:
        return Product.objects.filter(store=store, pk=int(raw)).first()
    except (TypeError, ValueError):
        return None


def _data(request) -> dict:
    return request.data if isinstance(request.data, dict) else {}


def _store_payload(store, ctx: dict) -> dict:
    return {"id": store.pk, "name": store.name, "business_type": store.business_type or "", "audience": ctx["values"]["مخاطب"] if ctx["known"]["مخاطب"] else "",
            "tone": ctx["tone"], "known": ctx["known"], "values": ctx["values"]}


def _pick_lists(store) -> tuple[list[dict], list[dict]]:
    from apps.campaigns.models import Campaign
    from apps.products.models import Product

    products = [{"id": p.pk, "name": p.name} for p in Product.objects.filter(store=store).order_by("name")[:80]]
    campaigns = [{"id": c.pk, "name": c.name} for c in Campaign.objects.filter(store=store).exclude(approval_state=Campaign.ApprovalState.ARCHIVED).order_by("-id")[:60]]
    return products, campaigns


class IdeasView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id):
        store = _store(request, store_id, write=False)
        q = request.query_params
        product = _product(store, q.get("product"))
        ctx = fill.context(store, product)
        needs = q.get("needs_data")
        rows = bank.list_ideas(store, q=q.get("q", ""), category=q.get("category", ""), tag=q.get("tag", ""), fmt=q.get("fmt", ""), channel=q.get("channel", ""),
                               favorite=_flag(q.get("favorite", "")), source=q.get("source", ""), include_hidden=_flag(q.get("hidden", "")),
                               needs_data=None if needs in (None, "") else _flag(needs), ctx=ctx)
        everything = bank.all_ideas(store, ctx)
        products, campaigns = _pick_lists(store)
        ok, why = ai.status(store)
        return Response({"ideas": rows, "shown": len(rows), **bank.facets(everything), "store": _store_payload(store, ctx), "products": products,
                         "campaigns": campaigns, "ai": {"ok": ok, "why": why}})

    def post(self, request, store_id):
        store = _store(request, store_id)
        try:
            return Response(bank.create_idea(store, _data(request), ctx=fill.context(store)), status=status.HTTP_201_CREATED)
        except bank.BankError as exc:
            return _bank_err(exc)


class RandomView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id):
        store = _store(request, store_id, write=False)
        row = bank.random_idea(store, request.query_params.get("category", ""), fill.context(store, _product(store, request.query_params.get("product"))))
        return Response(row) if row else _err("ایده‌ای پیدا نشد.", "not_found", status.HTTP_404_NOT_FOUND)


class GenerateView(APIView):
    """«ایده بساز»: هوش مصنوعی اگر در دسترس باشد، وگرنه فرمول‌های آمادهٔ فارسی؛ ایده‌ها به‌عنوانِ ایده‌های فروشگاه ذخیره می‌شوند (``save=false`` = فقط پیش‌نمایش)."""

    permission_classes = [IsAuthenticated]

    def post(self, request, store_id):
        store = _store(request, store_id)
        d = _data(request)
        product = _product(store, d.get("product"))
        facts = d.get("facts") if isinstance(d.get("facts"), list) else [x for x in str(d.get("facts") or "").splitlines()]
        kw = dict(category=str(d.get("category") or ""), count=_int(d.get("count"), 5), topic=str(d.get("topic") or ""), instruction=str(d.get("instruction") or ""),
                  facts=[str(x) for x in facts], product=product, use_ai=bool(d.get("ai", True)), variation=_int(d.get("variation"), 0),
                  ctx=fill.context(store, product))
        try:
            result = generator.generate(store, **kw) if d.get("save") is False else generator.generate_and_save(store, **kw)
        except ValueError as exc:
            return _err(str(exc))
        if kw["use_ai"] and not result["ai"].get("ok") and result["ai"].get("parkable"):
            from apps.compute import deferred

            queued = deferred.defer("ideabank.generate", store, {
                "category": kw["category"], "count": kw["count"], "topic": kw["topic"], "instruction": kw["instruction"], "facts": kw["facts"],
                "product_id": getattr(product, "pk", None), "variation": kw["variation"], "save": d.get("save") is not False},
                user=request.user, reason=result["ai"].get("reason") or "")
            if queued:
                result["queued"] = queued
                result["message"] = str(result.get("message") or "").replace("وقتی هوش مصنوعی برگردد همین دکمه پیشنهادهای هوشمند می‌دهد.", "این درخواست «در صف تا روشن شدنِ سرورِ پردازش» ماند؛ ایده‌های هوشمند خودکار می‌رسد.")
        return Response(result)


class FromTrendView(APIView):
    """«ذخیره در بانکِ ایده» روی کارتِ ترند: ``{"trend_idea": <id>}`` (ترندها) یا ``{"cluster": <id>}`` (ترندهای اینستاگرام)."""

    permission_classes = [IsAuthenticated]

    def post(self, request, store_id):
        store = _store(request, store_id)
        d = _data(request)
        ctx = fill.context(store)
        try:
            if d.get("trend_idea"):
                from apps.ai.trend_models import TrendIdea

                row = TrendIdea.objects.filter(store=store, pk=_int(d["trend_idea"], 0)).select_related("trend").first()
                if row is None:
                    return _err("ایدهٔ ترند پیدا نشد.", "not_found", status.HTTP_404_NOT_FOUND)
                idea, created = handoff.save_trend_idea(store, row, ctx)
            elif d.get("cluster"):
                from apps.igtrends.models import IgTrendCluster

                cl = IgTrendCluster.objects.filter(store=store, pk=_int(d["cluster"], 0)).first()
                if cl is None:
                    return _err("موضوعِ ترند پیدا نشد.", "not_found", status.HTTP_404_NOT_FOUND)
                idea, created = handoff.save_cluster_brief(store, cl, ctx)
            else:
                return _err("شناسهٔ ایدهٔ ترند را بفرستید.")
        except bank.BankError as exc:
            return _bank_err(exc)
        return Response({"idea": idea, "created": created, "message": "در بانکِ ایده ذخیره شد." if created else "این ایده قبلاً در بانکِ ایده بود."},
                        status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


class IdeaView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, store_id, key):
        store = _store(request, store_id, write=False)
        row = bank.get_idea(store, key, fill.context(store, _product(store, request.query_params.get("product"))))
        return Response(row) if row else _err("ایده پیدا نشد.", "not_found", status.HTTP_404_NOT_FOUND)

    def patch(self, request, store_id, key):
        store = _store(request, store_id)
        try:
            return Response(bank.update_idea(store, key, _data(request), fill.context(store)))
        except bank.BankError as exc:
            return _bank_err(exc)

    def delete(self, request, store_id, key):
        store = _store(request, store_id)
        try:
            bank.delete_idea(store, key)
        except bank.BankError as exc:
            return _bank_err(exc)
        return Response(status=status.HTTP_204_NO_CONTENT)


class DuplicateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, store_id, key):
        store = _store(request, store_id)
        try:
            return Response(bank.duplicate_idea(store, key, _data(request), fill.context(store)), status=status.HTTP_201_CREATED)
        except bank.BankError as exc:
            return _bank_err(exc)


class MarkView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, store_id, key):
        store = _store(request, store_id)
        d = _data(request)
        try:
            return Response(bank.set_mark(store, key, favorite=_flag(d["favorite"]) if "favorite" in d else None,
                                          hidden=_flag(d["hidden"]) if "hidden" in d else None, ctx=fill.context(store)))
        except bank.BankError as exc:
            return _bank_err(exc)


class StartView(APIView):
    """«از این ایده شروع کن». استودیو و تامنیل فقط آدرس و متنِ آماده می‌گیرند؛ تقویم یک کارِ «محتوا» می‌سازد (نیازِ دسترسیِ «کمپین‌ها»)."""

    permission_classes = [IsAuthenticated]

    def post(self, request, store_id, key):
        d = _data(request)
        target = str(d.get("target") or "")
        if target not in TARGETS:
            return _err("مقصد باید یکی از studio، calendar یا thumbnail باشد.")
        store = _store(request, store_id, permission=access.CAMPAIGNS if target == "calendar" else access.CONTENT)
        product = _product(store, d.get("product"))
        idea = bank.get_idea(store, key, fill.context(store, product))
        if idea is None:
            return _err("ایده پیدا نشد.", "not_found", status.HTTP_404_NOT_FOUND)
        try:
            if target == "studio":
                out = handoff.studio(idea, product_id=product.pk if product else None)
                bank.record_use(store, key, "studio")
            elif target == "thumbnail":
                out = handoff.thumbnail(idea)
                bank.record_use(store, key, "thumbnail")
            else:
                out = handoff.plan(store, idea, campaign_id=d.get("campaign"), product_id=product.pk if product else None, due=d.get("due"))
                bank.record_use(store, key, "calendar", out["task_id"])
        except bank.BankError as exc:
            return _bank_err(exc)
        return Response({"target": target, **out, "uses": bank.get_idea(store, key, fill.context(store, product))["uses"]},
                        status=status.HTTP_201_CREATED if target == "calendar" else status.HTTP_200_OK)
