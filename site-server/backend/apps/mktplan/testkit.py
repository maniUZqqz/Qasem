"""ابزارِ مشترکِ آزمون‌های برنامهٔ بازاریابی: یک فروشگاهِ ساختگی با پروفایل، محصول و (اختیاری) کمپین‌های قدیمی. هیچ دادهٔ واقعی‌ای این‌جا نیست."""
from __future__ import annotations

import datetime as dt

from django.contrib.auth.models import User
from django.utils import timezone

from apps.campaigns.models import Campaign
from apps.campaigns.tasks_board import CampaignTask
from apps.products.models import Product
from apps.stores.models import Store, StoreProfile


def make_store(*, products: bool = True, name: str = "باشگاه نمونه", staff: bool = False):
    owner = User.objects.create_user(f"owner-{User.objects.count()}", password="x", is_staff=staff)
    store = Store.objects.create(
        owner=owner, name=name, business_type="خدمات ورزشی برای مربیان",
        description="باشگاه نمونه به مربی‌ها کمک می‌کند برنامهٔ تمرین را سریع‌تر بنویسند. هدفش جایگزین‌کردنِ مربی نیست.",
        target_audience="مربی‌های باشگاه و مربی‌های شخصی", social_links={"app": "https://example.test/app"})
    StoreProfile.objects.update_or_create(store=store, defaults={"tone": "صمیمی ولی حرفه‌ای"})
    prod = None
    if products:
        prod = Product.objects.create(store=store, name="برنامهٔ هوشمند", short_description="پیش‌نویسِ برنامهٔ ورزشی در کمتر از یک دقیقه.", price=0)
    return owner, store, prod


_DETAIL = ("نوع: {t}\nموعدِ پیشنهادیِ انتشار: شنبه ۱۴۰۵/۰۸/۲۳ ساعت ۱۹:۳۰ (تهران) — فقط پیشنهاد؛ چیزی خودکار منتشر نمی‌شود.\n\n"
           "متنِ گویندگی (پیشنهادی): مربی‌ای؟ وقتت باید صرفِ مربیگری شود، نه نوشتنِ برنامه. همین حالا شروع کن.\n")


def old_campaigns(store, prod):
    """دو کمپینِ «دورِ قبل» با زمان‌های کهنه، مثلِ کمپین‌های ساخته‌شده در دورهای پیشینِ یک فروشگاه."""
    stale = timezone.now() - dt.timedelta(days=5)
    w1 = Campaign.objects.create(store=store, product=prod, name="نمونه — هفتهٔ ۱")
    prof = Campaign.objects.create(store=store, product=prod, name="نمونه — راه‌اندازی پروفایل و تعامل")
    out = {}
    for n, title in enumerate(("کاروسل: معرفی", "ریلز: معرفی", "استوری: وقتِ مربی", "پست: یک نکته")):
        out[title.split(":")[0]] = CampaignTask.objects.create(
            campaign=w1, store=store, kind=CampaignTask.Kind.CONTENT, title=title, detail=_DETAIL.format(t=title), due_at=stale, order=n)
    out["بایو"] = CampaignTask.objects.create(campaign=prof, store=store, kind=CampaignTask.Kind.CONTENT, title="بایوِ اینستاگرام — سه نسخه",
                                              detail="نسخهٔ الف: نمونه", due_at=stale, order=0)
    out["نظر"] = CampaignTask.objects.create(campaign=w1, store=store, kind=CampaignTask.Kind.CONTENT, title="ریلزِ نظرِ واقعیِ یک مربی (منتظرِ ویدیوی واقعی)",
                                             detail="فقط با ویدیوی واقعی", due_at=stale, order=9)
    return out
