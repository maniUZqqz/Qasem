"""What this store still needs before the product can do anything for it.

Not a tour. Every step is answered from the database, so a shop that already
added products never sees "add your first product", and one that stalled after
signing up is told the one thing standing between it and a first result.

The order is the order that actually works: a caption written before the brand
voice is set is a caption the owner will throw away, and an analysis run before
a photo is uploaded has nothing to look at. Steps therefore carry `blocked_by`
rather than pretending they are independent.

Deliberately not gamified. No confetti, no percentage badge for reading a
tooltip — `done` means a real row exists in a real table.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Step:
    key: str
    title: str
    why: str
    done: bool
    action: str = ""
    blocked_by: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "key": self.key,
            "title": self.title,
            "why": self.why,
            "done": self.done,
            "action": self.action,
            "blocked_by": self.blocked_by,
        }


def _has_brand_voice(store) -> bool:
    profile = getattr(store, "profile", None)
    if profile is None:
        return False
    return bool((profile.tone or "").strip() or (profile.brand_voice or "").strip())


def _has_publishing(store) -> bool:
    """Somewhere for finished content to go.

    The shared `.env` token counts: it is how a store publishes on day one,
    before the owner has their own NovinHub account.
    """
    from django.conf import settings

    profile = getattr(store, "profile", None)
    if profile is not None and (profile.novinhub_token or "").strip():
        return True
    conf = settings.UPMARKET_AI
    return bool(conf.get("NOVINHUB_TOKEN") or conf.get("N8N_WEBHOOK_URL"))


def steps(store) -> list[Step]:
    """The checklist for this store, each item answered from real rows."""
    from apps.ai.models import ProductIntelligence
    from apps.content.models import Caption, GeneratedImage, VideoScript
    from apps.products.models import Product, ProductImage

    products = Product.objects.filter(store=store)
    has_product = products.exists()
    has_photo = ProductImage.objects.filter(product__store=store).exists()
    has_analysis = ProductIntelligence.objects.filter(product__store=store).exists()
    has_content = (
        Caption.objects.filter(store=store).exists()
        or GeneratedImage.objects.filter(store=store).exists()
        or VideoScript.objects.filter(store=store).exists()
    )
    agent = getattr(store, "agent_settings", None)
    policy = getattr(store, "ai_policy", None)

    return [
        Step(
            key="brand_voice",
            title="لحن و صدای برند را بنویس",
            why="بدون این، هر کپشنی که تولید شود شبیه بقیه‌ی فروشگاه‌ها حرف می‌زند "
                "و آخرش خودت بازنویسی‌اش می‌کنی.",
            done=_has_brand_voice(store),
            action=f"/stores/{store.pk}",
        ),
        Step(
            key="first_product",
            title="اولین محصول را اضافه کن",
            why="قیمت و موجودی از همین‌جا خوانده می‌شود — ایجنت فروش هیچ‌وقت از خودش "
                "قیمت نمی‌سازد.",
            done=has_product,
            action=f"/stores/{store.pk}",
        ),
        Step(
            key="product_photo",
            title="برای محصول عکس بگذار",
            why="تحلیل تصویر و ساخت پوستر روی عکس واقعی محصول انجام می‌شود، نه روی متن.",
            done=has_photo,
            action=f"/stores/{store.pk}",
            blocked_by=[] if has_product else ["first_product"],
        ),
        Step(
            key="analysis",
            title="یک محصول را تحلیل کن",
            why="نتیجه‌ی تحلیل، پایه‌ی کپشن و سناریوی ویدیو است. یک‌بار انجام می‌شود "
                "و بقیه‌ی کارها از آن استفاده می‌کنند.",
            done=has_analysis,
            action=f"/stores/{store.pk}",
            blocked_by=[] if has_photo else ["product_photo"],
        ),
        Step(
            key="agent_settings",
            title="قوانین ایجنت فروش را تعیین کن",
            why="پیش‌فرض، ایجنت هیچ تخفیفی نمی‌دهد و شکایت را به تو ارجاع می‌دهد. "
                "اگر قانون خاصی داری، همین‌جا بنویس.",
            done=bool(agent and agent.updated_at != agent.created_at),
            action=f"/stores/{store.pk}",
        ),
        Step(
            key="data_policy",
            title="تصمیم بگیر داده‌ات کجا پردازش شود",
            why="سه حالت دارد. اگر «فقط لوکال» را انتخاب کنی هیچ داده‌ای از سرور ما "
                "خارج نمی‌شود — ولی صداگذاری هم کار نمی‌کند.",
            done=bool(policy and policy.acknowledged_at),
            action=f"/stores/{store.pk}",
        ),
        Step(
            key="publishing",
            title="مسیر انتشار را وصل کن",
            why="بدون این، محتوا تولید می‌شود ولی جایی برای رفتن ندارد و باید دستی "
                "دانلود و آپلود کنی.",
            done=_has_publishing(store),
            action=f"/stores/{store.pk}",
        ),
        Step(
            key="first_content",
            title="اولین محتوا را بساز",
            why="اینجاست که معلوم می‌شود خروجی به کارت می‌آید یا نه — و دو هفته‌ی "
                "آزمایشی برای همین است.",
            done=has_content,
            action=f"/stores/{store.pk}",
            blocked_by=[] if has_analysis else ["analysis"],
        ),
    ]


def summary(store) -> dict:
    """The checklist plus the one thing to do next.

    `next` skips blocked steps: telling someone to analyse a product they have
    not photographed yet sends them somewhere they cannot finish.
    """
    rows = steps(store)
    done = [s for s in rows if s.done]
    todo = [s for s in rows if not s.done]
    actionable = [s for s in todo if not s.blocked_by]

    return {
        "steps": [s.as_dict() for s in rows],
        "done_count": len(done),
        "total": len(rows),
        "complete": not todo,
        "next": (actionable[0].as_dict() if actionable else (todo[0].as_dict() if todo else None)),
    }
