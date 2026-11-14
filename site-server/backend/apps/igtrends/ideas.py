"""«ایده بساز» for an Instagram topic: a content brief (hook, what to film, outline, caption draft, hashtags) and a `TrendIdea`.

AI when it is reachable (through the same audited router as the rest of the trends page: local Ollama first, Metis as fallback), a
plain template otherwise - and the template says so. Either way:

* the topic is context, never the product: a brief is about the shop's own thing, in the form that is working;
* nothing is invented: no price, no statistic, no claim about the shop that is not in its own data;
* what other pages wrote is a *signal about form* (their hook types, formats, sounds) - it is not copied.
"""
from __future__ import annotations

import logging
from collections import Counter

from django.utils import timezone

from apps.ai import research_llm, trends as ai_trends
from apps.ai.trend_models import Trend, TrendIdea

from . import textproc
from .explain import FORMAT_FA, fa, hook_label
from .models import IgPost, IgTrendCluster

logger = logging.getLogger(__name__)

KIND_FOR_FORMAT = {"reel": TrendIdea.Kind.VIDEO, "video": TrendIdea.Kind.VIDEO, "carousel": TrendIdea.Kind.POST, "photo": TrendIdea.Kind.POST}

HOOK_TEMPLATES = {
    "question": "{topic}؟ آیا تو هم همین اشتباه را می‌کنی؟",
    "number": "۳ نکته دربارهٔ {topic} که باید همین امروز بدانی",
    "contrarian": "دربارهٔ {topic} این اشتباهِ رایج را نکن",
    "story": "من دربارهٔ {topic} چه یاد گرفتم",
    "cta": "اگر دنبالِ {topic} هستی، این را ذخیره کن",
    "claim": "ساده‌ترین راه برای شروعِ {topic}",
    "statement": "{topic} — کوتاه و کاربردی",
}
OUTLINES = {
    "reel": ["ثانیهٔ ۰ تا ۳: قلاب — جملهٔ بالا هم روی تصویر نوشته شود هم گفته شود",
             "ثانیهٔ ۳ تا ۱۵: نمایشِ عملیِ موضوع (یک مثالِ واقعیِ خودتان، بدونِ وعدهٔ نتیجه)",
             "ثانیهٔ ۱۵ تا ۲۵: یک توصیهٔ کوتاه یا نتیجه",
             "پایان: دعوت به ذخیره‌کردن یا فرستادن برای کسی که به این نیاز دارد"],
    "carousel": ["اسلاید ۱: تیترِ قلاب‌دار (همان جملهٔ بالا)", "اسلایدهای ۲ تا ۵: هر اسلاید فقط یک نکته یا یک مرحله، با متنِ کوتاه و درشت",
                 "اسلایدِ آخر: جمع‌بندی در یک جمله و دعوت به ذخیره‌کردن"],
    "photo": ["یک عکسِ قوی و ساده از موضوع، با متنِ کوتاهِ قلاب‌دار روی تصویر", "کپشن در سه جمله: مسئله، راه‌حل، دعوت به نظر دادن"],
}
OUTLINES["video"] = OUTLINES["reel"]
SYSTEM = (
    "You write short Persian content briefs for one specific shop, from signals about what is working on Instagram in its niche. "
    "You answer with a single valid JSON object and nothing else. You never invent a product, a price, a statistic, a result or a claim "
    "about the shop. You never copy another page's caption: you use only the *form* (hook type, format, rhythm). "
    "The trend is context, never the subject: the content is about the shop's own offer."
)


def _topic(cluster: IgTrendCluster) -> str:
    label = cluster.label.split(" · ")[0].strip()
    return label.lstrip("#") if label else "این موضوع"


def pick_product(store, cluster: IgTrendCluster, products=None):
    """The shop's product whose words appear in the topic; the first one otherwise; None when it has none."""
    from apps.products.models import Product
    products = products if products is not None else list(Product.objects.filter(store=store, is_available=True).order_by("pk")[:25])
    if not products:
        return None, False
    vocab = ai_trends.store_vocabulary(store, products)["words"]
    topic_words = set(textproc.words(cluster.label)) | {w for h in (cluster.stats or {}).get("hashtags", []) for w in textproc.words(textproc.tag_phrase(h))}
    for w in sorted(topic_words):
        name = vocab.get(w)
        if name and not name.startswith("گروهِ"):
            for p in products:
                if p.name == name:
                    return p, True
    return products[0], False


def examples(cluster: IgTrendCluster, limit: int = 4) -> list[dict]:
    posts = IgPost.objects.filter(pk__in=cluster.post_ids or []).select_related("account").order_by("-score")[:limit]
    return [{"id": p.pk, "account": p.account.username, "url": p.url, "fmt": p.fmt, "hook": p.hook, "hook_type": p.hook_type,
             "likes": p.likes, "comments": p.comments, "views": p.views, "score": p.score, "ratio": p.ratio, "taken_at": p.taken_at.isoformat(),
             "why": (p.explain or {}).get("ratio")} for p in posts]


def template_brief(store, cluster: IgTrendCluster, product=None, matched: bool = True) -> dict:
    stats = cluster.stats or {}
    fmt = cluster.fmt if cluster.fmt in OUTLINES else "reel"
    types = Counter(h.get("type") for h in stats.get("hooks", []) if h.get("type"))
    htype = types.most_common(1)[0][0] if types else "number"
    topic = _topic(cluster)
    hook = HOOK_TEMPLATES.get(htype, HOOK_TEMPLATES["statement"]).format(topic=topic)
    tags = ["#" + t for t in (stats.get("hashtags") or [])[:6]]
    # a product is NAMED only when the topic really is about it; "the first product" of a shop can be a billing item («بستهٔ توکن ۵۰تایی»)
    thing = ("«%s»" % product.name) if product is not None and matched else "پیشنهادِ خودتان"
    idea = ("[قالبِ ساده — بدونِ هوش مصنوعی] %s دربارهٔ «%s» بسازید و در آن %s را نشان دهید؛ موضوع فقط زمینه است و محتوا دربارهٔ کارِ خودتان می‌ماند. "
            "قالبِ قلاب: %s." % (FORMAT_FA.get(fmt, "پست"), topic, thing, hook_label(htype)))
    caption = "%s\n\n• [نکتهٔ ۱ دربارهٔ %s]\n• [نکتهٔ ۲]\n• [نکتهٔ ۳]\n\nاگر به کارت آمد ذخیره‌اش کن.\n\n%s" % (hook, topic, " ".join(tags))
    return {"source": "template", "format": fmt, "kind": KIND_FOR_FORMAT.get(fmt, TrendIdea.Kind.VIDEO), "hook": hook, "hook_type": htype, "idea": idea,
            "why": " · ".join(cluster.why[:2]) or "موضوعی که صفحه‌های دیده‌بانی‌شده همین حالا می‌سازند.",
            "outline": OUTLINES.get(fmt, OUTLINES["reel"]), "caption": caption.strip(), "hashtags": tags, "needs_edit": True}


def build_prompt(store, cluster: IgTrendCluster, products, product) -> str:
    import json
    dumps = lambda v: json.dumps(v, ensure_ascii=False, separators=(",", ":"))
    profile = getattr(store, "profile", None)
    stats = cluster.stats or {}
    signal = {"topic": cluster.label, "hashtags": (stats.get("hashtags") or [])[:8], "format": cluster.fmt, "posts": cluster.size,
              "pages": cluster.accounts_count, "median_engagement_vs_normal": stats.get("median_ratio"),
              "hook_types": [h.get("type") for h in stats.get("hooks", [])][:4],
              "sounds": [a.get("title") for a in stats.get("audio", [])][:2], "reasons": cluster.why[:4]}
    return (
        "Make one content brief for this shop from the Instagram signal below.\n\n"
        f"Shop: {dumps({'name': store.name, 'business_type': store.business_type, 'tone': getattr(profile, 'tone', ''), 'brand_voice': getattr(profile, 'brand_voice', '')})}\n"
        f"Its products: {dumps([{'id': p.pk, 'name': p.name, 'description': (p.description or '')[:160]} for p in products[:12]])}\n"
        f"Preferred product id: {product.pk if product else None}\n"
        f"Signal (what pages in the niche are doing now): {dumps(signal)}\n\n"
        "Rules:\n- Everything in Persian except JSON keys.\n- `hook` = the first sentence of the content, under 15 words.\n"
        "- `idea` = what to film/make, 2-3 sentences, about the shop's own thing.\n- `why` = why this fits THIS shop, specific; "
        "'محبوب است' is not a reason.\n- `outline` = 3-5 short beats.\n- `caption` = a draft caption; use [brackets] where the shop must add its own detail.\n"
        "- No invented numbers, prices, results, features. Do not copy any caption.\n"
        'Answer exactly: {"kind":"VIDEO|POST|STORY|CAPTION","hook":"","idea":"","why":"","outline":["",""],"caption":"","hashtags":["#"]}'
    )


def _valid(parsed) -> tuple[bool, list[str]]:
    p = parsed or {}
    problems = []
    if len(str(p.get("hook", "")).strip()) < 6:
        problems.append("hook خالی است")
    if len(str(p.get("idea", "")).strip()) < 30:
        problems.append("idea کوتاه است")
    if not isinstance(p.get("outline"), list) or len([x for x in p["outline"] if str(x).strip()]) < 2:
        problems.append("outline باید فهرستِ حداقل دو مرحله باشد")
    if not ai_trends._usable(str(p.get("why", ""))):
        problems.append("why دلیلِ روشنی نیست")
    return (not problems, problems)


def ai_brief(store, cluster: IgTrendCluster, products, product) -> dict:
    parsed = research_llm.ask_json(store, prompt_id="ig_trend_brief", prompt=build_prompt(store, cluster, products, product), system=SYSTEM, validate=_valid)
    kind = str(parsed.get("kind", "")).upper()
    fmt = cluster.fmt if cluster.fmt in OUTLINES else "reel"
    return {"source": "ai", "format": fmt, "kind": kind if kind in TrendIdea.Kind.values else KIND_FOR_FORMAT.get(fmt, TrendIdea.Kind.VIDEO),
            "hook": str(parsed["hook"]).strip()[:300], "hook_type": textproc.hook_type(str(parsed["hook"])), "idea": str(parsed["idea"]).strip()[:2000],
            "why": str(parsed["why"]).strip()[:1000], "outline": [str(x).strip()[:200] for x in parsed["outline"] if str(x).strip()][:6],
            "caption": str(parsed.get("caption", "")).strip()[:2200], "hashtags": [str(h)[:60] for h in (parsed.get("hashtags") or [])][:10],
            "needs_edit": False}


def make_idea(store, cluster: IgTrendCluster, *, use_ai: bool = True) -> dict:
    """Build the brief (AI -> template), mirror the topic as a `Trend`, and save a `TrendIdea` the content page can run."""
    from apps.products.models import Product
    products = list(Product.objects.filter(store=store, is_available=True).order_by("pk")[:25])
    product, matched = pick_product(store, cluster, products)
    note = ""
    brief = None
    if use_ai:
        ok, why = research_llm.status(store)
        if ok:
            try:
                brief = ai_brief(store, cluster, products, product)
            except Exception as exc:  # noqa: BLE001 - any model/HTTP failure (e.g. 402 out of credit) falls back to the template
                logger.info("igtrends: AI brief failed (%s); template", exc)
                note = "هوش مصنوعی جواب نداد؛ قالبِ ساده ساخته شد."
        else:
            note = "هوش مصنوعی الان در دسترس نیست؛ قالبِ ساده ساخته شد."
    if brief is None:
        brief = template_brief(store, cluster, product, matched)
        brief["note"] = note
    brief["product_id"] = product.pk if product else None
    brief["product_name"] = product.name if product else None
    brief["product_matched"] = matched
    brief["examples"] = examples(cluster)
    brief["made_at"] = timezone.now().isoformat()
    day = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
    ctx = [{"title": (e["hook"] or "")[:160], "url": e["url"], "source": "@" + e["account"]} for e in brief["examples"] if e["hook"]][:4]
    trend, _ = Trend.objects.get_or_create(title=("اینستاگرام: " + cluster.label)[:200], region="IG", seen_at=day,
                                           defaults={"source": "instagram_scrape", "context": ctx})
    TrendIdea.objects.filter(store=store, trend=trend, state=TrendIdea.State.OPEN).delete()
    idea_text = brief["idea"] + ("\n\nمراحل:\n" + "\n".join("• " + s for s in brief["outline"]) if brief["outline"] else "")
    idea = TrendIdea.objects.create(store=store, trend=trend, product=product, kind=brief["kind"], idea=idea_text[:2000],
                                    why=brief["why"][:1000], hook=brief["hook"][:300])
    cluster.idea_trend, cluster.brief = trend, brief
    cluster.save(update_fields=["idea_trend", "brief", "updated_at"])
    return {"brief": brief, "idea_id": idea.pk, "trend_id": trend.pk, "source": brief["source"], "note": brief.get("note", "")}
