"""Satisfaction survey after a conversation is closed.

Deliberately text-based: «با یک عدد از ۱ تا ۵ جواب بدهید». A survey that needs a
link or a button works on one channel; a digit works on all of them (Telegram,
Bale, Eitaa, Rubika, SMS, the site widget, WhatsApp). The answer is caught in
`ingest.receive` *before* it reaches the bot or the team, so a customer typing
«۵» is not asked "how can I help?" and the team's inbox does not light up for it.

Rules that keep it from being a nuisance:
* only after a real conversation (a human replied) - never after a thread the
  bot closed on its own;
* never for test conversations;
* at most one survey per conversation per day;
* the answer window is three days; after that a stray digit is just a message.

And rules that keep a *customer's real message* from being eaten as an answer
(«3 نفر هستیم و می‌خوام ثبت‌نام کنم» is a booking, not a 3-star rating):
* the thread must still be closed - once the customer has written something else
  and the thread is open again, a digit belongs to that conversation;
* the message is the digit alone («۵»، «5 ستاره»، «۴ از ۵»), or the digit followed
  by a short remark that is not a question and does not start like a count
  («۴ ممنون»، «۵ - عالی بود»). Anything longer, any question, «3 نفر…» /
  «2 ساعت…» / «5 تا…» is an ordinary message.
"""
from __future__ import annotations

import re
from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from apps.customers.models import Conversation, Message

from . import events, norm
from .models import FollowUp, MessageMeta, SatisfactionSurvey

DEFAULT_TEXT = (
    "ممنون که با ما گفتگو کردید. نظرتان دربارهٔ پاسخ‌گویی ما چه بود؟ "
    "با یک عدد از ۱ (ضعیف) تا ۵ (عالی) جواب بدهید؛ اگر خواستید یک جمله هم بنویسید."
)
ANSWER_WINDOW = timedelta(days=3)

#: The digit alone, or with the usual decorations: «۵»، «5.»، «۴ از ۵»، «۳/۵»، «۵ ستاره»، «⭐ 5».
_BARE = re.compile(
    r"^[\s⭐★☆*]*([1-5])\s*(?:/\s*5|از\s*5|ستاره|امتیاز|[*⭐★])*[\s.!،,:;)\-–]*$"
)
#: Digit + remark. `sep` tells how they are joined: punctuation reads as «a rating, then a comment».
_REMARK = re.compile(r"^\s*([1-5])\s*(?P<sep>[-–:،,.)]|\s)\s*(?P<rest>.{1,160})$", re.S)
#: The word after a digit that makes it a quantity («3 نفر»، «2 ساعت»، «5 تا»…), not a rating.
_UNITS = {
    "نفر", "تا", "عدد", "بار", "دفعه", "ساعت", "دقیقه", "ثانیه", "روز", "هفته", "ماه", "سال", "شب",
    "جلسه", "هزار", "میلیون", "تومان", "تومن", "ریال", "کیلو", "گرم", "لیتر", "متر", "درصد", "ماهه",
    "ساله", "روزه", "نفره", "تایی", "کلاس", "دوره", "برنامه", "بسته", "سری", "مورد", "قسط", "ماهی",
    "پیام", "سفارش", "مربی", "ورزشکار", "شاگرد", "کاربر", "اکانت", "حساب",
    "people", "persons", "times", "hours", "days", "months", "years", "kg",
}
_MAX_WORDS_PLAIN = 4  # «۴ خیلی خوب بود» yes; a sentence that merely begins with a digit no
_MAX_WORDS_PUNCT = 10


def parse_answer(text: str) -> tuple[int, str] | None:
    """(score, comment) when `text` is a survey answer, else None. Pure - no database."""
    cleaned = norm.ascii_digits((text or "").strip())
    if not cleaned:
        return None
    bare = _BARE.match(cleaned)
    if bare:
        return int(bare.group(1)), ""
    found = _REMARK.match(cleaned)
    if not found:
        return None
    rest = found.group("rest").strip()
    if "؟" in rest or "?" in rest or re.search(r"\d", rest):
        return None
    tokens = norm.words(rest)
    if not tokens:
        return None
    punctuated = found.group("sep") != " " and not found.group("sep").isspace()
    if len(tokens) > (_MAX_WORDS_PUNCT if punctuated else _MAX_WORDS_PLAIN):
        return None
    if tokens[0] in _UNITS:
        return None
    return int(found.group(1)), rest[:300]


def schedule(conversation: Conversation, closed_by=None) -> FollowUp | None:
    from .team import settings_for

    cfg = settings_for(conversation.store)
    if not cfg.survey_enabled:
        return None
    from . import sla

    if sla.is_test(conversation):
        return None
    # Only worth asking when a person actually helped.
    if not MessageMeta.objects.filter(
        message__conversation=conversation, kind=MessageMeta.Kind.REPLY,
    ).exists():
        return None
    recent = timezone.now() - timedelta(days=1)
    if SatisfactionSurvey.objects.filter(conversation=conversation, created_at__gte=recent).exists():
        return None
    if FollowUp.objects.filter(
        conversation=conversation, kind=FollowUp.Kind.SURVEY, status=FollowUp.Status.PENDING,
    ).exists():
        return None
    return FollowUp.objects.create(
        store=conversation.store, conversation=conversation, kind=FollowUp.Kind.SURVEY,
        target=FollowUp.Target.CUSTOMER, text=cfg.survey_text or DEFAULT_TEXT,
        due_at=timezone.now() + timedelta(minutes=cfg.survey_delay_min),
        assigned_to=closed_by or conversation.assigned_to, created_by=closed_by,
    )


def mark_sent(conversation: Conversation, agent=None) -> SatisfactionSurvey:
    return SatisfactionSurvey.objects.create(
        conversation=conversation, store=conversation.store, sent_at=timezone.now(),
        agent=agent or conversation.assigned_to,
    )


def _open_survey_for(conversation: Conversation, message: Message):
    """(survey, score, comment) when `message` answers this thread's open survey, else None."""
    if conversation.state != Conversation.State.RESOLVED:
        return None  # the customer wrote again and the thread is open: a digit belongs to it
    parsed = parse_answer(message.text)
    if parsed is None:
        return None
    survey = (
        SatisfactionSurvey.objects.filter(
            conversation=conversation, answered_at__isnull=True,
            sent_at__gte=timezone.now() - ANSWER_WINDOW,
        ).order_by("-sent_at").first()
    )
    if survey is None:
        return None
    return survey, parsed[0], parsed[1]


def is_answer(conversation: Conversation, message: Message) -> bool:
    """Would `try_answer` take this message? A look only - nothing is recorded.

    The message signal asks this *before* it reopens a closed thread or lights up
    the team's unread counter: a customer's «۵» is the end of a conversation,
    not a new one.
    """
    return _open_survey_for(conversation, message) is not None


def try_answer(conversation: Conversation, message: Message) -> bool:
    """Is this message the answer to an open survey? If so, record and thank."""
    hit = _open_survey_for(conversation, message)
    if hit is None:
        return False
    survey, score, comment = hit
    survey.score = score
    survey.comment = comment
    survey.answered_at = timezone.now()
    survey.save(update_fields=["score", "comment", "answered_at", "updated_at"])
    events.emit(conversation.store, "survey.answered", {
        "conversation_id": conversation.id, "score": survey.score, "comment": survey.comment,
        "agent": survey.agent.username if survey.agent_id else "",
    })
    from .replies import system_reply

    system_reply(conversation, "ممنون از نظرتان!" if survey.score >= 4 else
                 "ممنون از صراحتتان؛ حتماً برای بهتر شدن استفاده می‌کنیم.", kind="SYSTEM")
    return True


def summary(store, *, days: int = 30) -> dict:
    since = timezone.now() - timedelta(days=days)
    rows = SatisfactionSurvey.objects.filter(store=store, answered_at__gte=since).exclude(
        Q(conversation__inbox_meta__is_test=True) | Q(conversation__customer__channel="web-test")
    )
    scores = list(rows.values_list("score", flat=True))
    by_agent: dict[str, list[int]] = {}
    for username, score in rows.values_list("agent__username", "score"):
        by_agent.setdefault(username or "-", []).append(score)
    return {
        "answered": len(scores),
        "average": round(sum(scores) / len(scores), 2) if scores else None,
        "distribution": {str(i): scores.count(i) for i in range(1, 6)},
        "by_agent": {
            name: {"average": round(sum(v) / len(v), 2), "count": len(v)} for name, v in by_agent.items()
        },
        "sent": SatisfactionSurvey.objects.filter(store=store, sent_at__gte=since).count(),
    }
