"""Did the form accept the message? A guess from the HTTP status and the page that came back - recorded as a guess, never as fact."""
from __future__ import annotations

import html
import re

from apps.growth_engine.core import conf

from ..models import SendAttempt

_SCRIPT_STYLE = re.compile(r"<(script|style|noscript)\b[^>]*>.*?</\1\s*>", re.I | re.S)
_TAGS = re.compile(r"<[^>]+>")
_SPACES = re.compile(r"\s+")

# a thank-you / acceptance message. «پیام شما» alone is NOT a marker: it is also the label of the textarea of a form that was re-shown.
SUCCESS_MARKERS = (
    "ممنون", "با تشکر", "تشکر از", "ارسال شد", "دریافت شد", "ثبت شد", "با موفقیت", "پیام شما را", "پیامتان",
    "thank", "success", "has been sent", "has been received", "message sent", "received your",
)
FAILURE_MARKERS = (
    "خطا", "نامعتبر", "کپچا", "کد امنیتی", "اجباری است", "را وارد کنید", "ناموفق", "مجاز نیست", "دسترسی ندارید",
    "captcha", "error", "invalid", "required", "failed", "forbidden", "not allowed", "try again",
)


def visible_text(page_html: str, limit: int | None = None) -> str:
    """The text a person would read on ``page_html`` (no scripts, styles or tags), trimmed to ``limit`` characters."""
    text = _SCRIPT_STYLE.sub(" ", page_html or "")
    text = html.unescape(_TAGS.sub(" ", text))
    text = _SPACES.sub(" ", text).strip()
    return text[: limit if limit is not None else int(conf.get("SEND_SNIPPET_CHARS"))]


def judge(status_code: int, text: str, *, outcome: str = "ok") -> str:
    """``likely_success`` | ``unclear`` | ``likely_failure``."""
    if outcome != "ok" and not status_code:
        return SendAttempt.Guess.FAILURE
    if status_code >= 400 or status_code == 0:
        return SendAttempt.Guess.FAILURE
    lowered = visible_text(text, 20000).lower()
    success = any(marker in lowered for marker in SUCCESS_MARKERS)
    failure = any(marker in lowered for marker in FAILURE_MARKERS)
    if failure and not success:
        return SendAttempt.Guess.FAILURE
    if success and not failure:
        return SendAttempt.Guess.SUCCESS
    return SendAttempt.Guess.UNCLEAR
