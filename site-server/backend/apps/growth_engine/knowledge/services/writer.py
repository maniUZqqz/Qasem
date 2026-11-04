"""The AI message writer: one version of one outreach item's message, grounded ONLY in the product knowledge and the lead's own facts.

Flow of ``run`` (never raises; the version row carries the outcome):

1. build the context (``context.build``): the active knowledge items + the facts we really stored about the lead + the sender;
2. build the prompt (rules in plain words: only these facts, never invent, no prices that are not in the knowledge, short);
3. ask the routed model for a JSON object ``{subject, message, personalization_reason, evidence_references, warnings}``;
4. ``check`` it: references must exist, every NUMBER must appear in the facts, no price unless a price is in the knowledge, SMS must
   fit its parts, absolute claims are flagged; a problem becomes a warning (``blocking`` ones need an explicit «با این هشدار می‌پذیرم»);
5. the SYSTEM adds the sender block and the opt-out line (``rendering.compose``) - the model can neither drop nor invent them.

If the AI cannot answer (node off, Metis credit exhausted ...) the version is ``failed`` with a plain Persian message and the item keeps
its template text: the templates work without any AI.
"""
from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field

from django.utils import timezone

from apps.growth_engine.compliance.models import GrowthSettings
from apps.growth_engine.core import normalization as nz
from apps.growth_engine.outreach.channels import sms as sms_channel
from apps.growth_engine.outreach.models import Channel
from apps.growth_engine.outreach.services import channel_config, rendering

from ..models import GeneratedMessage
from . import ai, context

logger = logging.getLogger(__name__)

SYSTEM = (
    "تو نویسندهٔ پیام‌های اولین تماسِ یک شرکتِ ایرانی (فرستنده) با یک کسب‌وکارِ دیگر هستی. فقط فارسیِ روان، محترمانه و کوتاه بنویس.\n"
    "قاعده‌های سخت:\n"
    "۱) فقط از «حقایقِ داده‌شده» استفاده کن. هر حقیقت یک شناسه دارد (مثل K12 یا F3). هر چیزی که در پیام می‌گویی باید از یکی از آن‌ها آمده باشد و شناسه‌اش را در evidence_references بنویس.\n"
    "۲) هرگز چیزی از خودت اختراع نکن: نه قیمت، نه عدد، نه درصد تخفیف، نه تعدادِ مشتری، نه نتیجهٔ فروش، نه نظرِ مشتری، نه وعدهٔ تضمینی. اگر چیزی در حقایق نیست، نگو.\n"
    "۳) اگر در حقایق قیمتی نیست، دربارهٔ قیمت هیچ نگو. عددی را فقط وقتی بنویس که عیناً در حقایق باشد.\n"
    "۴) محدودیت‌ها را پنهان نکن؛ اگر ادعایی با یک محدودیتِ داده‌شده نمی‌خواند، آن ادعا را نکن.\n"
    "۵) امضا، نامِ فرستنده، شماره و جملهٔ «لغو» را ننویس؛ سامانه خودش در انتها می‌گذارد.\n"
    "۶) پیام باید فقط یک کار از گیرنده بخواهد (مثلاً پاسخ‌دادن) و به گیرنده فشار نیاورد.\n"
    "۷) خروجی فقط یک شیءِ JSON باشد با این کلیدها: "
    '"subject" (رشته؛ برای کانال‌هایی که موضوع ندارند خالی)، "message" (متنِ پیام)، "personalization_reason" (یک جمله: چرا این پیام برای همین کسب‌وکار شخصی شده)، '
    '"evidence_references" (فهرستِ شناسه‌های حقایقِ استفاده‌شده)، "warnings" (فهرستِ رشته‌ها؛ هر چیزی که فکر می‌کنی جای نگرانی است، وگرنه خالی).'
)

#: per channel: (max characters of the message part or None, whether a subject is wanted, how it should read)
STYLE = {
    Channel.CONTACT_FORM: (900, True, "یک پیام کوتاهِ رسمی برای ثبت در فرمِ تماسِ سایتِ آن‌ها"),
    Channel.EMAIL: (1400, True, "یک ایمیلِ کوتاهِ رسمی با موضوعِ روشن (حداکثر ۸۰ نویسه)"),
    Channel.SMS: (None, False, "یک پیامکِ بسیار کوتاه؛ بدون موضوع، بدون لینک"),
    Channel.WHATSAPP: (700, False, "یک پیامِ دوستانه و کوتاه برای چت"),
    Channel.TELEGRAM: (700, False, "یک پیامِ دوستانه و کوتاه برای چت"),
    Channel.EITAA: (700, False, "یک پیامِ دوستانه و کوتاه برای چت"),
    Channel.BALE: (700, False, "یک پیامِ دوستانه و کوتاه برای چت"),
    Channel.RUBIKA: (700, False, "یک پیامِ دوستانه و کوتاه برای چت"),
    Channel.PHONE_CALL: (900, False, "راهنمای تماسِ تلفنی برای یک آدم: چند جملهٔ معرفی، دلیلِ تماس، پیشنهاد، و اگر مایل نبودند چه بگوید"),
}
SOFT_CLAIMS = ("تضمین", "تضمینی", "صد درصد", "۱۰۰ درصد", "100%", "۱۰۰٪", "بهترین", "ارزان‌ترین", "ارزانترین", "بی‌نظیر", "رکورد")
_PRICE_WITH_NUMBER = re.compile(r"[0-9]+\s*(?:هزار|میلیون|تومان|ریال)|(?:تومان|ریال)\s*[0-9]+|[0-9]+\s*(?:درصد|%|٪)|تخفیف", re.I)
_PERSIAN = re.compile(r"[؀-ۿ]")
_BRACES = re.compile(r"[{}]")


class WriterError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


@dataclass
class Draft:
    subject: str
    body: str
    reason: str
    evidence: list[dict] = field(default_factory=list)
    warnings: list[dict] = field(default_factory=list)


def warning(code: str, text: str, *, blocking: bool = False) -> dict:
    return {"code": code, "text": text, "blocking": blocking}


# --------------------------------------------------------------------------- the prompt


def size_hint(channel: str, settings_obj: GrowthSettings) -> int | None:
    """How many characters the AI's part may have (SMS: what is left of the parts after the closing block)."""
    limit, _, _ = STYLE.get(channel, (700, False, ""))
    if channel == Channel.SMS:
        parts = channel_config.sms_max_parts()
        units = {1: 70, 2: 134, 3: 201}[parts]
        closing = rendering.closing_block(settings_obj, channel)
        return max(20, units - len(closing) - 1)
    return limit


def build_prompt(item, ctx: context.Context, instructions: str, settings_obj: GrowthSettings) -> tuple[str, str]:
    channel = item.channel or Channel.CONTACT_FORM
    _, wants_subject, how = STYLE.get(channel, (700, False, "پیامی کوتاه"))
    limit = size_hint(channel, settings_obj)
    lines = ["حقایقِ داده‌شده (هر خط یک حقیقت):"]
    lines += [f"[{f.ref}] {f.label}: {f.text}" for f in ctx.facts]
    if not ctx.price_known:
        lines.append("(توجه: هیچ قیمتی در حقایق نیست؛ دربارهٔ قیمت هیچ نگو.)")
    lines += [
        "",
        f"کانال: {Channel(channel).label} - {how}.",
        f"حداکثرِ طولِ متنِ پیام: {limit} نویسه." if limit else "",
        "موضوع لازم است." if wants_subject else "موضوع لازم نیست؛ subject را خالی بگذار.",
        f"گیرنده: {item.lead.display_name}.",
    ]
    if instructions:
        lines += ["", f"راهنمای اضافیِ مسئولِ فروش (در چارچوبِ قاعده‌ها): {instructions}"]
    lines += ["", "فقط JSON بده."]
    return SYSTEM, "\n".join(line for line in lines if line is not None)


# --------------------------------------------------------------------------- checking the answer


def check(raw: dict, item, ctx: context.Context, settings_obj: GrowthSettings) -> Draft:
    """Turn the model's JSON into a ``Draft`` with the warnings every check raised. Raises ``WriterError`` when there is no message at all."""
    channel = item.channel or Channel.CONTACT_FORM
    message = _BRACES.sub("", str(raw.get("message") or "")).strip()
    subject = _BRACES.sub("", " ".join(str(raw.get("subject") or "").split())).strip()
    if not message:
        raise WriterError("هوش مصنوعی پیامی ننوشت (متن خالی بود). دوباره امتحان کنید یا از قالب استفاده کنید.")
    warnings: list[dict] = []

    # the system adds the opt-out line and the sender block: a copy the model wrote would only double them
    opt_out = (settings_obj.opt_out_line or "").strip()
    if opt_out and opt_out in message:
        message = message.replace(opt_out, "").strip()
    message = message.rstrip(" \n-—_")

    _, wants_subject, _ = STYLE.get(channel, (700, False, ""))
    if wants_subject and not subject:
        subject = item.subject or ""
        warnings.append(warning("no_subject", "هوش مصنوعی موضوع ننوشت؛ موضوعِ قبلیِ قالب نگه داشته شد."))
    if not wants_subject:
        subject = ""
    if channel == Channel.EMAIL and len(subject) > 120:
        subject = subject[:120].rstrip()
        warnings.append(warning("subject_cut", "موضوع از ۱۲۰ نویسه بلندتر بود و کوتاه شد."))

    # evidence: every cited reference must exist
    by_ref = ctx.by_ref()
    cited = [str(r).strip() for r in (raw.get("evidence_references") or []) if str(r).strip()]
    valid = list(dict.fromkeys(r for r in cited if r in by_ref))
    unknown = [r for r in dict.fromkeys(cited) if r not in by_ref]
    if unknown:
        warnings.append(warning("unknown_reference", "به شناسه‌هایی اشاره کرده که وجود ندارد: " + "، ".join(unknown[:5]) + "."))
    if not valid:
        warnings.append(warning("no_evidence", "هیچ مدرکی (از دانشِ محصول یا اطلاعاتِ لید) برای این پیام ذکر نشد؛ پیش از پذیرفتن با دقت بخوانید."))
    evidence = [{"ref": r, "label": by_ref[r].label, "text": by_ref[r].text[:240]} for r in valid]

    # numbers: only those the facts contain
    wrote = [n for n in dict.fromkeys(context.numbers_in(message + " " + subject)) if n not in ctx.numbers]
    for number in wrote[:5]:
        warnings.append(warning("ungrounded_number", f"عددِ «{number}» در دانشِ محصول و اطلاعاتِ لید نیست؛ ممکن است ساختگی باشد.", blocking=True))
    # a price / discount nobody wrote down
    if not ctx.price_known and _PRICE_WITH_NUMBER.search(nz.to_ascii_digits(message + " " + subject)):
        warnings.append(warning("price_mentioned", "قیمت یا تخفیف ذکر شده در حالی که در دانشِ محصول قیمتی ثبت نشده است.", blocking=True))
    found = [c for c in SOFT_CLAIMS if c in message or c in subject]
    if found:
        warnings.append(warning("absolute_claim", "ادعای مطلق یا وعدهٔ قطعی دارد (" + "، ".join(found[:3]) + ")؛ مطمئن شوید راست است."))
    letters = _PERSIAN.findall(message)
    if len(letters) < 0.4 * max(1, len(re.findall(r"[^\W\d_]", message))):
        warnings.append(warning("not_persian", "متن فارسی نیست یا بیشترش لاتین است."))
    for text in [str(w).strip() for w in (raw.get("warnings") or []) if str(w).strip()][:3]:
        warnings.append(warning("model_note", "یادداشتِ نویسنده: " + text[:200]))

    # SMS: the whole message (text + closing) must fit the parts the operator allows
    composed = rendering.compose(message, subject, settings_obj, channel=channel).text
    if channel == Channel.SMS:
        seg = sms_channel.segments(composed)
        allowed = channel_config.sms_max_parts()
        if seg["parts"] > allowed:
            warnings.append(warning("sms_too_long", f"با امضا و جملهٔ لغو {seg['parts']} بخش می‌شود و حداکثرِ مجاز {allowed} بخش است.", blocking=True))
    reason = " ".join(str(raw.get("personalization_reason") or "").split())[:500]
    return Draft(subject=subject, body=message, reason=reason, evidence=evidence, warnings=warnings)


# --------------------------------------------------------------------------- the run


def run(version_id: int) -> GeneratedMessage | None:
    """Fill a ``generating`` version. Never raises: the row says how it went."""
    version = GeneratedMessage.objects.select_related("item", "item__lead", "item__campaign", "item__campaign__template").filter(pk=version_id).first()
    if version is None or version.status != GeneratedMessage.Status.GENERATING:
        return version
    item = version.item
    try:
        settings_obj = GrowthSettings.load()
        ctx = context.build(item)
        system, prompt = build_prompt(item, ctx, version.instructions, settings_obj)
        version.prompt_sha256 = hashlib.sha256((system + "\n" + prompt).encode("utf-8")).hexdigest()
        parsed, route = ai.complete_json(system, prompt)
        draft = check(parsed, item, ctx, settings_obj)
        version.subject, version.body = draft.subject, draft.body
        version.text = rendering.compose(draft.body, draft.subject, settings_obj, channel=item.channel).text
        version.personalization_reason, version.evidence, version.warnings, version.route = draft.reason, draft.evidence, draft.warnings, route
        version.status = GeneratedMessage.Status.PROPOSED
    except ai.AiUnavailable as exc:
        version.status, version.error = GeneratedMessage.Status.FAILED, exc.message[:600]
    except WriterError as exc:
        version.status, version.error = GeneratedMessage.Status.FAILED, exc.message[:600]
    except Exception as exc:  # noqa: BLE001 - one broken request must not take the worker down
        logger.exception("growth ai writer failed for version %s", version_id)
        version.status, version.error = GeneratedMessage.Status.FAILED, f"خطای داخلی ({type(exc).__name__}). می‌توانید از قالب استفاده کنید."
    version.finished_at = timezone.now()
    version.save()
    return version
