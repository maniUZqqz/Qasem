"""Repairs the visible copy errors of the AI caption drafts of one shop (the owner's flagship «چغر»), once and safely.

Why: a local model wrote the drafts; a review (2026-11-13) found glued slogans, Latin digits in Persian copy, a model's remark left in
a post, doubled dots, glued hashtags, the same opening line in four drafts and a few sentences that mean nothing («به دستورالعمل‌های
شخصی ... پی ببرید»). The quality gate (caption_guard) now WARNS about most of these; this command fixes the ones that are already stored.

Two kinds of change, both idempotent and both refuse to touch a caption the owner edited:

* mechanical rules (every caption of the shop): slogan «با چغر چغر تر شو» (brand-facts-fa.md §1), ASCII digits -> Persian digits in
  Persian text, a parenthesised remark to the owner removed, «..» -> «.», glued hashtags repaired (hashtags.repair);
* FIXES: new text for ~40 fields, applied only while the stored text is still exactly the one reviewed (sha1 prefix), so an edit made in
  the panel in the meantime wins. Every sentence uses only facts of docs/chagher/brand-facts-fa.md (nothing is invented).

    python manage.py repair_caption_copy            # apply
    python manage.py repair_caption_copy --check    # list what would change
    python manage.py repair_caption_copy --store 34
"""
import hashlib
import json
import re

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.common.fatext import fa_digits
from apps.content import hashtags as hashtag_tools
from apps.content.models import Caption
from apps.stores.models import Store

FIXES: dict[int, dict[str, tuple[str, object]]] = {
    17: {
        'short_text': ('c2697de4d5b9', '۱٬۳۰۰ حرکت فارسی با گیف و عکس 🎯'),
        'medium_text': ('d35a2594e7f4', 'کتابخانهٔ حرکت\u200cهای چغر بیش از ۱٬۳۰۰ حرکت با نامِ فارسی، گیف و عکس دارد. هر حرکت در PDF لینکِ آموزش دارد. دستگاه\u200cهای باشگاه را هم می\u200cشود با دوربین اسکن کرد؛ تا تأییدِ مربی چیزی ثبت نمی\u200cشود. 📱'),
        'long_text': ('b49918cdff93', 'مربیان، با چغر آشنا شوید! کتابخانهٔ حرکت\u200cهای چغر بیش از ۱٬۳۰۰ حرکت با نامِ فارسی، گیف و عکس دارد. هر حرکت در PDF لینکِ آموزش دارد و دستگاه\u200cهای باشگاه را هم می\u200cشود با دوربین اسکن کرد؛ تا تأییدِ مربی چیزی ثبت نمی\u200cشود. هزینهٔ توکنیِ این بخش\u200cها فعلاً صفر است. 📱'),
        'hashtags': ('7289594cdfc2', ['#چغر', '#کتابخانه_حرکت', '#اسکن_دستگاه', '#آموزش_حرکت', '#ورزشکار', '#مربی', '#تکنولوژی', '#ورزش']),
    },
    18: {
        'short_text': ('b7caedfc0593', 'صبح مربیگری چطور شروع می\u200cشود؟ 🕐'),
        'medium_text': ('ef0d8403a7ce', 'صبح مربیگری چطور شروع می\u200cشود؟ با چغر پیش\u200cنویسِ برنامهٔ ورزشی و غذاییِ ورزشکار را در کمتر از یک دقیقه بگیر، بازبینی کن و وقتت را برای مربیگری بگذار. ثبت\u200cنام رایگان است؛ ساختِ برنامهٔ کامل ۵۰ توکن هزینه دارد.'),
        'long_text': ('f85a93d9912d', 'صبح مربیگری چطور شروع می\u200cشود؟ یک روز جدید با چغر شروع کن: مشخصاتِ ورزشکار را وارد کن تا چغر با هوش مصنوعی پیش\u200cنویسِ برنامهٔ ورزشی و غذایی را در کمتر از یک دقیقه بنویسد و خروجیِ PDFِ برندشده و قابل\u200cچاپ بدهد. ثبت\u200cنام رایگان است و کارتِ اعتباری نمی\u200cخواهد؛ ساختِ برنامهٔ کامل ۵۰ توکن هزینه دارد. بازبینی و تصمیمِ نهایی با مربی است.'),
        'hashtags': ('1be0b4834b1c', ['چغر', 'هوش_مصنوعی', 'برنامه_ورزشی', 'PDF', 'رایگان', 'مربیگری', 'توکن', 'چغر_تر']),
    },
    19: {
        'medium_text': ('bc8502dfd910', 'برنامهٔ ورزشی یا غذایی، فقط یکی از آن\u200cها را هم می\u200cشود ساخت — ۲۵ توکن. چغر در کمتر از یک دقیقه پیش\u200cنویسِ آن را آماده می\u200cکند. 🧠'),
        'long_text': ('82d8484ec525', 'چغر، دستیار هوش مصنوعیِ مربی\u200cهاست. با واردکردنِ اطلاعاتِ ورزشکار، یک برنامهٔ ورزشی یا غذایی در کمتر از یک دقیقه پیش\u200cنویس می\u200cشود. اگر فقط یکی از برنامه\u200cها را نیاز دارید، فقط همان را بسازید. هزینه ۲۵ توکن یا ۳۰۰ هزار تومان است. 🧠🏋️\u200d♂️🥗'),
        'cta': ('dd78f371b4b9', 'برنامهٔ خود را با ۲۵ توکن بسازید. 📲'),
        'hashtags': ('67683401b653', ['#چغر', '#برنامه_ورزشی', '#برنامه_غذایی', '#هوش_مصنوعی', '#مربی', '#ورزشکار']),
    },
    20: {
        'short_text': ('2dab2a6f5a45', 'چرا وقتت را صرفِ نوشتنِ برنامه کنی؟ 🧠'),
        'medium_text': ('4af3feed5675', 'مربی، وقتت را صرفِ مربیگری کن. با چغر، برنامهٔ ورزشی و غذاییِ ورزشکارت را در کمتر از یک دقیقه پیش\u200cنویس می\u200cکند. PDFِ حرفه\u200cای و قابل\u200cچاپ، آمادهٔ دادن به ورزشکار است. 📄'),
        'long_text': ('e14172e9b1bd', 'مربی، وقتت را صرفِ مربیگری کن. با چغر، برنامهٔ ورزشی و غذاییِ ورزشکارت را در کمتر از یک دقیقه پیش\u200cنویس می\u200cکند. خروجی یک PDFِ برندشده و قابل\u200cچاپ است که می\u200cتوانی به ورزشکارت بدهی. با چغر چغر تر شو. 📱✨'),
        'cta': ('4c8aec8a2da4', 'با چغر چغر تر شو'),
    },
    21: {
        'medium_text': ('1175165ea8a2', 'مربیان، با چغر برنامهٔ ورزشی و غذایی را در کمتر از یک دقیقه پیش\u200cنویس کنید. فقط مشخصاتِ ورزشکار را وارد کنید، پیش\u200cنویس را بازبینی کنید و تحویل بدهید. بدونِ نیاز به نوشتنِ دستی. 📱'),
    },
    22: {
        'short_text': ('2dab2a6f5a45', 'وقتِ مربی برای مربیگری است، نه نوشتنِ برنامه 🧠'),
        'medium_text': ('bbcf5956311f', 'مربی، وقتت را صرفِ مربیگری کن. با چغر، پیش\u200cنویسِ برنامهٔ ورزشی و غذاییِ ورزشکارت را در کمتر از یک دقیقه بگیر. خروجی PDF حرفه\u200cای و قابل\u200cچاپ است. ۵۰ توکن = ۶۰۰٬۰۰۰ تومان 📄'),
        'long_text': ('7e72cd195bf0', 'مربی، وقتت را صرفِ مربیگری کن. با چغر، پیش\u200cنویسِ برنامهٔ ورزشی و غذاییِ ورزشکارت را در کمتر از یک دقیقه بگیر. خروجی PDF حرفه\u200cای و قابل\u200cچاپ است. ۵۰ توکن = ۶۰۰٬۰۰۰ تومان. با چغر چغر تر شو. 🧠💡'),
        'cta': ('3f1ca8ec3190', 'برنامه\u200cات را با برندِ خودت تحویل بده. 📄'),
    },
    23: {
        'short_text': ('1ef5525538c9', 'یک دقیقه وقت داری؟ 🕒 پیش\u200cنویسِ برنامه آماده است'),
        'medium_text': ('a38641d4d1cd', 'مربی، فقط اطلاعاتِ ورزشکار را وارد کن؛ چغر پیش\u200cنویسِ برنامه را در کمتر از یک دقیقه می\u200cنویسد! 📱 PDFِ برندشده و قابل\u200cچاپ هم دارد. همین حالا رایگان شروع کن.'),
        'long_text': ('fa43bf90ddc2', 'مربی، فقط اطلاعاتِ ورزشکار را وارد کن؛ چغر پیش\u200cنویسِ برنامه را در کمتر از یک دقیقه می\u200cنویسد! 📱 PDFِ برندشده و قابل\u200cچاپ هم دارد. بازبینی و تصمیمِ نهایی با مربی است. همین حالا رایگان شروع کن.'),
    },
    24: {
        'short_text': ('f4e3e0f3b654', 'برنامه با قلم و تبلت؟ یا پیش\u200cنویسِ آماده؟ 📝✨'),
        'medium_text': ('d506031ae85d', 'مربی با قلم و تبلت هم باید برنامه را از اول بنویسد. با چغر، پیش\u200cنویسِ برنامهٔ ورزشی و غذایی در کمتر از یک دقیقه آماده است و PDFِ برندشده را در دست داری. 🚀'),
        'long_text': ('9c85229cd67a', 'مربی با قلم و تبلت هم باید برنامه را از اول بنویسد. با چغر، پیش\u200cنویسِ برنامهٔ حرفه\u200cای در کمتر از یک دقیقه آماده است و PDFِ برندشده را در دست داری. این PDF قابل\u200cچاپ است و می\u200cتوانی به ورزشکار تحویلش بدهی. با چغر چغر تر شو. 📄'),
        'cta': ('4c8aec8a2da4', 'با چغر چغر تر شو'),
    },
    25: {
        'short_text': ('e3d5a3749557', 'فقط ورزشی یا فقط غذایی؟ ۲۵ توکن 🏋️\u200d♂️🥗'),
        'long_text': ('5848c7595a81', 'مربیان، وقتِ خود را بازگردانید! چغر، با هوش مصنوعی، پیش\u200cنویسِ برنامهٔ ورزشی یا غذایی را در کمتر از یک دقیقه می\u200cنویسد. فقط یکی از دو برنامه را انتخاب کنید؛ ۲۵ توکن = ۳۰۰ هزار تومان. 🧠💪'),
        'cta': ('d6048ad8658a', 'برنامهٔ خود را با ۲۵ توکن بسازید. 🔗'),
    },
    26: {
        'short_text': ('12b01d92b010', 'وقتت را برای مربیگری نگه دار 🧾'),
        'medium_text': ('f71b0e92966b', 'مربی، وقتت را بگذار برای مربیگری! با چغر، پیش\u200cنویسِ برنامهٔ ورزشی و غذایی با هوش مصنوعی و فرهنگِ غذاییِ ایرانی در کمتر از یک دقیقه آماده می\u200cشود. خروجی PDF برندشده و قابل\u200cچاپ است. ۵۰ توکن = ۶۰۰٬۰۰۰ تومان. 🚀'),
        'long_text': ('d53ec4bf3391', 'مربی، وقتت را بگذار برای مربیگری! با چغر، پیش\u200cنویسِ برنامهٔ ورزشی و غذایی با هوش مصنوعی و فرهنگِ غذاییِ ایرانی در کمتر از یک دقیقه آماده می\u200cشود. خروجی PDF برندشده و قابل\u200cچاپ است. ۵۰ توکن = ۶۰۰٬۰۰۰ تومان. با چغر چغر تر شو. 🧾'),
    },
    27: {
        'short_text': ('cffce9e48f45', 'چغر بدون هوش مصنوعی هم کمک می\u200cکند! 🧠💡'),
        'hashtags': ('d9a4140e0cd8', ['چغر', 'برنامه\u200cساز_دستی', 'PDF', 'بدون_هوش_مصنوعی', 'مربی', 'ورزش', 'کمک_مربی']),
    },
    29: {
        'hashtags': ('869f4de1a19f', ['چغر', 'برنامه\u200cساز_دستی', 'PDF', 'بدون_هوش_مصنوعی', 'مربی', 'ورزش', 'چغر_بدون_هوش']),
    },
    31: {
        'short_text': ('0f07bea82e40', 'کارِ تکراریِ نوشتنِ برنامه را به چغر بسپار 🚫'),
        'medium_text': ('93f00471c930', 'مربی، وقتت را بگذار برای مربیگری! با چغر، برنامهٔ ورزشی و غذاییِ ورزشکارِ تو را در کمتر از یک دقیقه با PDFِ برندشده و قابل\u200cچاپ تحویل بده. ۵۰ توکن = ۶۰۰٬۰۰۰ تومان. 📄'),
        'long_text': ('fc27ebd0de94', 'مربی، وقتت را بگذار برای مربیگری! با چغر، برنامهٔ ورزشی و غذاییِ ورزشکارِ تو را در کمتر از یک دقیقه با PDFِ برندشده و قابل\u200cچاپ تحویل بده. فقط باید مشخصاتِ ورزشکار، تجهیزاتِ مجموعه و دستورالعملِ شخصیِ او را وارد کنی. ۵۰ توکن = ۶۰۰٬۰۰۰ تومان. این پیش\u200cنویسِ کاملِ برنامهٔ ورزشی و غذاییِ اختصاصیِ ورزشکارِ توست. با چغر چغر تر شو. 📱'),
    },
    32: {
        'medium_text': ('ea8879138bdd', 'چغر به شما کمک می\u200cکند تا پیش\u200cنویسِ برنامهٔ ورزشی و غذاییِ هر ورزشکار را در کمتر از یک دقیقه بگیرید. با خریدِ بستهٔ «عادی» (۵۰ توکن)، دستورالعمل\u200cهای شخصی و تجهیزاتِ مجموعهٔ خود را وارد کنید و برنامه\u200cای قابل\u200cچاپ بگیرید. ثبت\u200cنام رایگان است و نیازی به کارتِ اعتباری نیست. 🏋️\u200d♂️🥗'),
        'long_text': ('21eb20b10d11', 'چغر دستیار هوش مصنوعیِ مربیان است که به شما کمک می\u200cکند پیش\u200cنویسِ برنامهٔ ورزشی و غذاییِ هر ورزشکار را در کمتر از یک دقیقه بگیرید. با خریدِ بستهٔ «عادی» (۵۰ توکن)، دستورالعمل\u200cهای شخصی و تجهیزاتِ مجموعهٔ خود را وارد کنید و برنامه\u200cای قابل\u200cچاپ بگیرید. ثبت\u200cنام رایگان است و نیازی به کارتِ اعتباری نیست. با چغر، وقتِ مربی صرفِ مربیگری شود، نه نوشتنِ برنامه. 🏋️\u200d♂️🥗'),
    },
}

FIELDS = ("short_text", "medium_text", "long_text", "cta")
_PERSIAN = re.compile(r"[\u0600-\u06FF]")
_ASCII_DIGITS = re.compile(r"(?<![A-Za-z0-9_])[0-9][0-9]*(?![A-Za-z_])")
_REMARK = re.compile(r"\s*\(([^()\n]{18,}?[.؟!])\)")
_SLOGAN = re.compile(r"با چغر[،,]?\s*چغر\s?تر\s+شو")
_GLUED_WORD = re.compile(r"چغرتر")


def sha(value) -> str:
    text = json.dumps(list(value), ensure_ascii=False) if isinstance(value, (list, tuple)) else (value or "")
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


def mechanical(text: str) -> str:
    """The rules that are right for every caption of the shop."""
    out = text or ""
    out = _SLOGAN.sub("با چغر چغر تر شو", out)
    out = _GLUED_WORD.sub("چغر تر", out)
    out = _REMARK.sub("", out)                         # «(مقایسه دربارهٔ روندِ کار است، نه وعدهٔ نتیجه.)» is a note to the owner, not copy
    out = re.sub(r"(?<!\.)\.\.(?!\.)", ".", out)
    if _PERSIAN.search(out):
        out = _ASCII_DIGITS.sub(lambda m: fa_digits(m.group(0)), out)
    return out


def mechanical_tags(tags):
    out = []
    for tag in tags or []:
        if not isinstance(tag, str):
            out.append(tag)
            continue
        fixed = _GLUED_WORD.sub("چغر_تر", tag)
        repaired = hashtag_tools.repair(fixed)
        # only a tag that WAS glued is rewritten (the same test as the guard); «برنامه ورزشی» -> «برنامه_ورزشی» is shown that way anyway
        out.append(repaired if hashtag_tools.clean(repaired) != hashtag_tools.clean(fixed) else fixed)
    return out


def plan(caption: Caption) -> dict:
    """{field: new value} for one caption (empty when nothing is wrong or the owner edited the text)."""
    changes: dict = {}
    fixes = FIXES.get(caption.pk, {})
    for field in FIELDS:
        current = getattr(caption, field) or ""
        if field in fixes and sha(current) == fixes[field][0]:
            new = fixes[field][1]
        else:
            new = mechanical(current)
        if new != current:
            changes[field] = new
    cur_tags = list(caption.hashtags or [])
    if "hashtags" in fixes and sha(cur_tags) == fixes["hashtags"][0]:
        new_tags = list(fixes["hashtags"][1])
    else:
        new_tags = mechanical_tags(cur_tags)
    if new_tags != cur_tags:
        changes["hashtags"] = new_tags
    return changes


class Command(BaseCommand):
    help = "Repair the visible copy errors of the AI caption drafts of one shop (idempotent; --check only lists)."

    def add_arguments(self, parser):
        parser.add_argument("--store", type=int, default=0, help="store id (default: the shop named «چغر»)")
        parser.add_argument("--check", action="store_true", help="list the changes without saving")

    def handle(self, *args, **opts):
        store = Store.objects.filter(pk=opts["store"]).first() if opts["store"] else Store.objects.filter(name="چغر").order_by("pk").first()
        if store is None:
            self.stdout.write("no such store - nothing to do")
            return
        changed = 0
        for caption in Caption.objects.filter(store=store).order_by("pk"):
            changes = plan(caption)
            if not changes:
                continue
            changed += 1
            self.stdout.write("  caption %d (product %s): %s" % (caption.pk, caption.product_id, ", ".join(sorted(changes))))
            if not opts["check"]:
                for field, value in changes.items():
                    setattr(caption, field, value)
                caption.updated_at = timezone.now()
                caption.save(update_fields=[*changes, "updated_at"])
        self.stdout.write("%s %d caption(s) of store %s" % ("would change" if opts["check"] else "changed", changed, store.pk))
