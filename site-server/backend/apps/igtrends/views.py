"""The panel's «ترندهای اینستاگرام» tab and the token-authenticated ingest door.

    GET  stores/<id>/igtrends/                    everything the tab shows (node state, seeds, topic cards, top posts, hashtags, sounds, runs)
    POST stores/<id>/igtrends/scan/               ask the node to read Instagram now        {"accounts"?: [...], "force"?: bool}
    GET/POST stores/<id>/igtrends/seeds/         list / add seeds                          {"kind","value"|"values","note"?}
    PATCH/DELETE stores/<id>/igtrends/seeds/<pk>/
    POST stores/<id>/igtrends/seeds/reset/       put the starter pack back
    POST stores/<id>/igtrends/import/            Abagram «abagram-page» JSON file(s) (multipart `files`) - works with the node off
    POST stores/<id>/igtrends/config/            {"auto_scan","interval_h","max_accounts"}
    POST stores/<id>/igtrends/clusters/<pk>/brief/     «ایده بساز»          {"ai"?: bool}
    POST stores/<id>/igtrends/clusters/<pk>/dismiss/   {"dismissed": bool}
    POST igtrends/ingest/                         a batch pushed with `X-Ig-Key` or `Authorization: Node <token>` (store in batch.store_id or ?store=)
    GET/POST igtrends/settings/                  (staff) the ingest key
"""
from __future__ import annotations

import hmac
import json
import logging
import secrets
from datetime import timedelta

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import permissions, status as http
from rest_framework.decorators import api_view, authentication_classes, permission_classes, throttle_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.fatext import fa_digits
from apps.stores import access

from . import dispatch, engine, ideas, ingest, normalize, seeds
from . import status as node_status_mod
from .explain import FORMAT_FA, why_post
from .models import IgAudio, IgHashtag, IgPost, IgScanRun, IgSeed, IgSettings, IgStoreConfig, IgTrendCluster

logger = logging.getLogger(__name__)

MAX_FILE = 25 * 1024 * 1024
MAX_FILES = 40
MAX_TOTAL = 60 * 1024 * 1024
MAX_PUSH = 20 * 1024 * 1024


def err(code: str, message: str, status: int = http.HTTP_400_BAD_REQUEST) -> Response:
    return Response({"error": {"code": code, "message": message}}, status=status)


def _age_h(dt) -> float:
    return round(max(0.0, (timezone.now() - dt).total_seconds() / 3600.0), 1)


def post_json(p: IgPost) -> dict:
    return {"id": p.pk, "account": p.account.username, "url": p.url, "fmt": p.fmt, "fmt_label": FORMAT_FA.get(p.fmt, p.fmt), "hook": p.hook,
            "hook_type": p.hook_type, "caption": p.caption[:300], "hashtags": (p.hashtags or [])[:8], "likes": p.likes, "comments": p.comments,
            "views": p.views, "likes_hidden": p.likes_hidden, "score": p.score, "ratio": p.ratio, "growth": p.growth, "age_h": _age_h(p.taken_at),
            "taken_at": p.taken_at, "music": p.music_title, "why": why_post(p.explain or {}), "followers": p.account.followers}


def cluster_json(c: IgTrendCluster, with_examples: bool = True) -> dict:
    s = c.stats or {}
    out = {"id": c.pk, "key": c.key, "label": c.label, "kind": c.kind, "fmt": c.fmt, "fmt_label": FORMAT_FA.get(c.fmt, c.fmt), "score": c.score,
           "size": c.size, "accounts_count": c.accounts_count, "accounts": s.get("accounts", []), "why": c.why, "hooks": s.get("hooks", []),
           "audio": s.get("audio", []), "hashtags": s.get("hashtags", []), "formats": s.get("formats", {}), "recent_share": s.get("recent_share"),
           "median_ratio": s.get("median_ratio"), "best_ratio": s.get("best_ratio"), "in_niche": s.get("in_niche", False), "dismissed": c.dismissed,
           "brief": c.brief or None, "computed_at": c.computed_at, "first_seen_at": c.first_seen_at}
    if with_examples:
        posts = IgPost.objects.filter(pk__in=c.post_ids or []).select_related("account").order_by("-score")[:4]
        out["examples"] = [post_json(p) for p in posts]
    return out


def seed_json(s: IgSeed) -> dict:
    return {"id": s.pk, "kind": s.kind, "kind_label": s.get_kind_display(), "value": s.value, "note": s.note, "enabled": s.enabled, "scrape": s.scrape,
            "source": s.source, "last_read_at": s.last_read_at, "last_status": s.last_status, "fail_count": s.fail_count}


def run_json(r: IgScanRun) -> dict:
    return {"id": r.pk, "state": r.state, "state_label": r.get_state_display(), "source": r.source, "source_label": r.get_source_display(),
            "message": r.message, "stop_code": r.stop_code, "accounts": r.accounts, "accounts_read": r.accounts_read, "posts_new": r.posts_new,
            "posts_updated": r.posts_updated, "created_at": r.created_at, "finished_at": r.finished_at, "per_account": (r.summary or {}).get("per_account", {})}


def node_json(st: dict) -> dict:
    node = st.get("node") or {}
    rep = node.get("report") or {}
    return {"ready": st["ready"], "problem": st["problem"], "message": st["message"], "can_queue": st["can_queue"], "open_with": st["open_with"],
            "address": st["address"], "node": ({"name": node.get("name"), "online": node.get("online"), "last_seen": node.get("last_seen"),
                                                 "agent": node.get("agent"), "capable": node.get("capable")} if node else None),
            "service": {k: rep.get(k) for k in ("state", "step", "installed", "signed_in", "account", "proxy", "reach", "pages_hour", "pages_day",
                                                 "cooldown_until", "browser", "restarts_last_hour", "error", "version")} if rep else None}


class StoreView(APIView):
    permission_classes = [IsAuthenticated]

    def store(self, request, store_id, write=False):
        return access.get_store(request.user, store_id, access.CONTENT, write=write)


class OverviewView(StoreView):
    def get(self, request, store_id):
        store = self.store(request, store_id)
        cfg, _ = IgStoreConfig.objects.get_or_create(store=store)
        if not cfg.seeded and access.can(request.user, store, access.CONTENT, write=True):
            seeds.apply_defaults(store)
        dispatch.sync_runs(store)
        engine.ensure_fresh(store)
        clusters = IgTrendCluster.objects.filter(store=store, active=True, dismissed=False).order_by("-score")[:12]
        names = engine.watched_usernames(store)
        recent = IgPost.objects.filter(account__username__in=names, taken_at__gte=timezone.now() - timedelta(days=14)).select_related("account")
        top = recent.order_by("-score")[:12]
        st = node_status_mod.node_status()
        last_read = IgPost.objects.filter(account__username__in=names).order_by("-last_seen_at").values_list("last_seen_at", flat=True).first()
        data = {
            "node": node_json(st),
            "config": {"auto_scan": cfg.auto_scan, "interval_h": cfg.interval_h, "max_accounts": cfg.max_accounts, "min_reread_h": cfg.min_reread_h},
            "seeds": [seed_json(s) for s in IgSeed.objects.filter(store=store)],
            "clusters": [cluster_json(c) for c in clusters],
            "dismissed_count": IgTrendCluster.objects.filter(store=store, active=True, dismissed=True).count(),
            "top_posts": [post_json(p) for p in top],
            "hashtags": [{"tag": h.tag, "posts": h.posts, "accounts": h.accounts, "score": h.score, "recent_posts": h.recent_posts}
                         for h in IgHashtag.objects.filter(store=store)[:15]],
            "audio": [{"title": a.title, "artist": a.artist, "reels": a.reels, "accounts": a.accounts, "score": a.score, "total_views": a.total_views}
                      for a in IgAudio.objects.filter(store=store)[:8]],
            "runs": [run_json(r) for r in IgScanRun.objects.filter(store=store)[:6]],
            "totals": {"pages": len(names), "posts": recent.count(), "last_read_at": last_read},
            "can_edit": access.can(request.user, store, access.CONTENT, write=True),
        }
        return Response(data)


class ScanView(StoreView):
    def post(self, request, store_id):
        store = self.store(request, store_id, write=True)
        body = request.data if isinstance(request.data, dict) else {}
        names = [seeds.clean_value("account", n) for n in (body.get("accounts") or [])][:12]
        try:
            run = dispatch.request_scan(store, accounts=[n for n in names if n] or None, force=bool(body.get("force")))
        except dispatch.ScanRefused as exc:
            code = http.HTTP_409_CONFLICT if exc.code in ("busy", "nothing_due") else http.HTTP_503_SERVICE_UNAVAILABLE
            return err(exc.code, str(exc), code)
        return Response(run_json(run), status=http.HTTP_202_ACCEPTED)


class SeedsView(StoreView):
    def get(self, request, store_id):
        store = self.store(request, store_id)
        return Response({"seeds": [seed_json(s) for s in IgSeed.objects.filter(store=store)]})

    def post(self, request, store_id):
        store = self.store(request, store_id, write=True)
        body = request.data if isinstance(request.data, dict) else {}
        kind = body.get("kind")
        if kind not in IgSeed.Kind.values:
            return err("bad_kind", "نوع باید صفحه، هشتگ یا واژه باشد.")
        raw = body.get("values") if isinstance(body.get("values"), list) else str(body.get("value") or "").replace("،", "\n").replace(",", "\n").split("\n")
        added, bad = [], []
        for v in [x for x in (str(r).strip() for r in raw) if x][:60]:
            seed, created = seeds.add_seed(store, kind, v, note=str(body.get("note") or "")[:200])
            (added if seed else bad).append(seed_json(seed) if seed else v)
        if not added and bad:
            return err("bad_value", "مقدارِ واردشده درست نیست: %s" % "، ".join(bad[:3]))
        engine.mark_dirty_for_accounts([a["value"] for a in added if a["kind"] == "account"])
        IgStoreConfig.objects.update_or_create(store=store, defaults={"dirty": True})
        return Response({"added": added, "invalid": bad}, status=http.HTTP_201_CREATED)


class SeedView(StoreView):
    def patch(self, request, store_id, pk):
        store = self.store(request, store_id, write=True)
        seed = get_object_or_404(IgSeed, pk=pk, store=store)
        body = request.data if isinstance(request.data, dict) else {}
        for field in ("enabled", "scrape"):
            if field in body:
                setattr(seed, field, bool(body[field]))
        if "note" in body:
            seed.note = str(body["note"])[:200]
        if body.get("scrape"):
            seed.fail_count = 0
        seed.save()
        IgStoreConfig.objects.update_or_create(store=store, defaults={"dirty": True})
        return Response(seed_json(seed))

    def delete(self, request, store_id, pk):
        store = self.store(request, store_id, write=True)
        get_object_or_404(IgSeed, pk=pk, store=store).delete()
        IgStoreConfig.objects.update_or_create(store=store, defaults={"dirty": True})
        return Response(status=http.HTTP_204_NO_CONTENT)


class SeedsResetView(StoreView):
    def post(self, request, store_id):
        store = self.store(request, store_id, write=True)
        added = seeds.apply_defaults(store, force=True)
        return Response({"added": added, "seeds": [seed_json(s) for s in IgSeed.objects.filter(store=store)]})


class ConfigView(StoreView):
    def post(self, request, store_id):
        store = self.store(request, store_id, write=True)
        body = request.data if isinstance(request.data, dict) else {}
        cfg, _ = IgStoreConfig.objects.get_or_create(store=store)
        if "auto_scan" in body:
            cfg.auto_scan = bool(body["auto_scan"])
        for field, lo, hi in (("interval_h", 2, 72), ("max_accounts", 1, 12), ("min_reread_h", 1, 72)):
            if field in body:
                try:
                    setattr(cfg, field, max(lo, min(hi, int(body[field]))))
                except (TypeError, ValueError):
                    return err("bad_value", "عدد نامعتبر است.")
        cfg.save()
        return Response({"auto_scan": cfg.auto_scan, "interval_h": cfg.interval_h, "max_accounts": cfg.max_accounts, "min_reread_h": cfg.min_reread_h})


class ImportView(StoreView):
    """«واردکردنِ فایلِ آباگرام»: works with the node off. Only the page's profile numbers and posts are read; the followers/following
    lists inside an export are skipped without being stored."""

    def post(self, request, store_id):
        store = self.store(request, store_id, write=True)
        docs, problems = [], []
        files = request.FILES.getlist("files") or request.FILES.getlist("file")
        if files:
            if len(files) > MAX_FILES or sum(f.size for f in files) > MAX_TOTAL:
                return err("too_big", "حداکثر %s فایل و %s مگابایت در هر بار." % (MAX_FILES, MAX_TOTAL // (1024 * 1024)), http.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
            for f in files:
                if f.size > MAX_FILE:
                    problems.append("%s: فایل بزرگ است (بیش از %s مگابایت؛ احتمالاً فهرستِ فالوورها هم دارد)" % (f.name, MAX_FILE // (1024 * 1024)))
                    continue
                try:
                    docs.append((f.name, json.loads(f.read().decode("utf-8-sig"))))
                except (ValueError, UnicodeDecodeError):
                    problems.append("%s: فایلِ JSON نیست" % f.name)
        elif isinstance(request.data, dict) and request.data:
            body = request.data
            for i, d in enumerate(body.get("documents") if isinstance(body.get("documents"), list) else [body]):
                docs.append(("body-%d" % (i + 1), d))
        if not docs and not problems:
            return err("no_file", "فایلِ آباگرام را انتخاب کنید (خروجیِ «دریافت JSON» در آباگرام).")
        batches = []
        for name, doc in docs:
            try:
                batches.append(normalize.from_abagram_page(doc))
            except normalize.BatchError as exc:
                problems.append("%s: %s" % (name, exc))
        if not batches:
            return err("unreadable", "هیچ فایلی خوانده نشد. " + " | ".join(problems[:3]))
        merged = normalize.merge_batches(batches)
        add_pages = request.data.get("add_pages", "true") not in (False, "false", "0", 0, "off")
        run = IgScanRun.objects.create(store=store, source=IgScanRun.Source.IMPORT, state=IgScanRun.State.RUNNING,
                                       accounts=[a["username"] for a in merged["accounts"]], message="در حالِ ذخیره")
        try:
            out = ingest.apply_batch(store, merged, run, add_pages=add_pages)
        except normalize.BatchError as exc:
            run.state, run.message, run.finished_at = IgScanRun.State.FAILED, str(exc)[:300], timezone.now()
            run.save()
            return err("unreadable", str(exc))
        now = timezone.now()
        run.state, run.accounts_read, run.posts_new, run.posts_updated = IgScanRun.State.OK, out["accounts"], out["new"], out["updated"]
        run.message = fa_digits("%d صفحه و %d پست وارد شد (%d تازه)." % (out["accounts"], out["posts"], out["new"]))[:300]
        run.finished_at = run.ingested_at = now
        run.summary = {"files": len(docs), "problems": problems}
        run.save()
        return Response({"run": run_json(run), "problems": problems, "result": {k: out[k] for k in ("accounts", "posts", "new", "updated")}},
                        status=http.HTTP_201_CREATED)


class ClusterBriefView(StoreView):
    def post(self, request, store_id, pk):
        store = self.store(request, store_id, write=True)
        cluster = get_object_or_404(IgTrendCluster, pk=pk, store=store)
        body = request.data if isinstance(request.data, dict) else {}
        result = ideas.make_idea(store, cluster, use_ai=body.get("ai", True) not in (False, "false", 0, "0"))
        return Response(result, status=http.HTTP_201_CREATED)


class ClusterDismissView(StoreView):
    def post(self, request, store_id, pk):
        store = self.store(request, store_id, write=True)
        cluster = get_object_or_404(IgTrendCluster, pk=pk, store=store)
        body = request.data if isinstance(request.data, dict) else {}
        cluster.dismissed = bool(body.get("dismissed", True))
        cluster.save(update_fields=["dismissed", "updated_at"])
        return Response({"id": cluster.pk, "dismissed": cluster.dismissed})


# ---- the token door ----------------------------------------------------------------------------------------------------------

def _authorized(request) -> str | None:
    """'node' | 'key' | None."""
    header = request.META.get("HTTP_AUTHORIZATION", "")
    if header.startswith("Node "):
        from apps.compute.models import ComputeNode
        if ComputeNode.objects.filter(token=header.split(" ", 1)[1].strip(), enabled=True).exists():
            return "node"
        return None
    given = request.META.get("HTTP_X_IG_KEY", "")
    want = IgSettings.get().ingest_key
    if given and want and hmac.compare_digest(given.encode("utf-8"), want.encode("utf-8")):
        return "key"
    return None


@api_view(["POST"])
@authentication_classes([])
@permission_classes([permissions.AllowAny])
@throttle_classes([])
def ingest_view(request):
    who = _authorized(request)
    if who is None:
        return Response({"error": {"code": "auth", "message": "کلید یا توکنِ معتبر نیست."}}, status=http.HTTP_401_UNAUTHORIZED)
    try:
        if int(request.META.get("CONTENT_LENGTH") or 0) > MAX_PUSH:
            return err("too_big", "بسته بزرگ‌تر از حدِ مجاز است.", http.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
    except ValueError:
        pass
    batch = request.data if isinstance(request.data, dict) else {}
    from apps.stores.models import Store
    sid = batch.get("store_id") or request.query_params.get("store")
    store = Store.objects.filter(pk=sid).first() if str(sid or "").isdigit() else None
    if store is None:
        return err("no_store", "store_id در بسته یا ?store= لازم است و باید فروشگاهِ موجود باشد.")
    run = IgScanRun.objects.create(store=store, source=IgScanRun.Source.INGEST, state=IgScanRun.State.RUNNING, message="در حالِ ذخیره")
    try:
        out = ingest.apply_batch(store, batch, run)
    except normalize.BatchError as exc:
        run.state, run.message, run.finished_at = IgScanRun.State.FAILED, str(exc)[:300], timezone.now()
        run.save()
        return err("bad_batch", str(exc))
    now = timezone.now()
    run.state, run.accounts_read, run.posts_new, run.posts_updated = IgScanRun.State.OK, out["accounts"], out["new"], out["updated"]
    run.message, run.finished_at, run.ingested_at = "از راهِ %s ذخیره شد." % ("سرورِ پردازش" if who == "node" else "کلید"), now, now
    run.save()
    return Response({"run": run.pk, "accounts": out["accounts"], "posts": out["posts"], "new": out["new"], "updated": out["updated"]},
                    status=http.HTTP_201_CREATED)


@api_view(["GET", "POST"])
@permission_classes([permissions.IsAdminUser])
def settings_view(request):
    s = IgSettings.get()
    if request.method == "POST" and (request.data or {}).get("rotate"):
        s.ingest_key = secrets.token_urlsafe(32)
        s.save()
    return Response({"ingest_key": s.ingest_key, "header": "X-Ig-Key", "url": "/api/v1/igtrends/ingest/?store=<id>"})
