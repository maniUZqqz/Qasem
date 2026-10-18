"""What a recorded sales call actually said. صفحه ۷، بند ۲.

Two steps, and they are separate on purpose.

**Transcribe with Whisper**, which runs on our own GPU. A sales call is the
most personal data this product ever touches — it is a recording of somebody
who is not our customer — so it does not leave the machine to become text. The
gateway's `CUSTOMER` data class is what enforces that for the second step.

**Then read the transcript, not the audio.** The model gets words, which is
all it needs to find an objection or a promise, and which is the form a person
can check it against. Handing a model the audio would mean nobody can ever
verify what it thought it heard.

**It reports; it does not decide.** The output lands on the recording as a
suggestion, and a person moves the prospect's stage. An analysis that silently
marked a deal lost because the model misheard «فعلاً نه» would be worse than no
analysis at all.
"""
from __future__ import annotations

import logging

from apps.ai.models import AIRequest
from apps.ai.services import recorded_json_call
from services.ai import gateway
from services.ai.gateway import text_provider
from services.ai.router import TASK_REASONING, models_for
from services.audio.transcribe import TranscriptionUnavailable, transcribe

logger = logging.getLogger(__name__)

PROMPT_ID = "call_analysis"
PROMPT_VERSION = 1

SYSTEM = (
    "تو دستیار یک بازاریاب تلفنی هستی. متن پیاده‌شده‌ی یک تماس را می‌خوانی و "
    "فقط چیزی را گزارش می‌کنی که در خودِ متن هست. حدس نزن و چیزی به آن اضافه نکن. "
    "اگر چیزی در تماس گفته نشده، فهرستش را خالی بگذار."
)

TEMPLATE = """متن پیاده‌شده‌ی تماس با «{company}»:

---
{transcript}
---

یک JSON بده با این کلیدها:

- "summary": خلاصه‌ی تماس در حداکثر سه جمله.
- "objections": فهرست مخالفت‌ها یا نگرانی‌هایی که طرف مقابل **گفت**. هر کدام یک جمله.
- "commitments": فهرست قول‌هایی که **داده شد** — از هر دو طرف. هر کدام یک جمله.
- "next": یک جمله، قدم بعدی پیشنهادی.
- "sentiment": یکی از "POSITIVE"، "NEUTRAL"، "NEGATIVE".

فقط JSON بده."""

SENTIMENTS = {"POSITIVE", "NEUTRAL", "NEGATIVE"}


def _valid(parsed) -> tuple[bool, list[str]]:
    problems = []
    if not isinstance(parsed, dict):
        return False, ["خروجی JSON نبود"]
    if not str(parsed.get("summary", "")).strip():
        problems.append("خلاصه خالی است")
    for key in ("objections", "commitments"):
        if not isinstance(parsed.get(key, []), list):
            problems.append(f"«{key}» فهرست نیست")
    if parsed.get("sentiment") and parsed["sentiment"] not in SENTIMENTS:
        problems.append("«sentiment» یکی از سه مقدار مجاز نیست")
    return not problems, problems


def _lines(value, limit: int = 8) -> list[str]:
    """A list of short strings, whatever the model handed back."""
    if isinstance(value, str):
        value = [value]
    out = []
    for item in (value or [])[:limit]:
        text = str(item).strip()[:300]
        if text:
            out.append(text)
    return out


def run(recording) -> None:
    """Transcribe and analyse one recording, in place.

    Never raises: a failure is written onto the row as `FAILED` with a reason
    the owner can read. This runs in the background, and an exception here
    would leave a recording stuck at «ذخیره شد» forever with nothing saying
    why — which looks exactly like the feature not working.
    """
    from apps.customers.calls import Recording

    try:
        result = transcribe(recording.audio.path, language="fa")
    except TranscriptionUnavailable as exc:
        recording.status = Recording.Status.FAILED
        recording.error = str(exc)[:300]
        recording.save(update_fields=["status", "error", "updated_at"])
        return
    except Exception as exc:  # noqa: BLE001 - a stuck row is worse
        logger.exception("Transcription failed for recording %s", recording.pk)
        recording.status = Recording.Status.FAILED
        recording.error = f"پیاده‌سازی صدا خطا داد: {exc}"[:300]
        recording.save(update_fields=["status", "error", "updated_at"])
        return

    recording.transcript = result.text
    recording.seconds = int(result.seconds or recording.seconds)
    recording.status = Recording.Status.TRANSCRIBED
    recording.error = ""
    recording.save(
        update_fields=["transcript", "seconds", "status", "error", "updated_at"]
    )

    if not recording.transcript.strip():
        recording.error = "در این فایل حرفی شنیده نشد."
        recording.save(update_fields=["error", "updated_at"])
        return

    try:
        parsed, _ = recorded_json_call(
            store=recording.store,
            task_type=AIRequest.TaskType.REASONING,
            prompt_id=PROMPT_ID,
            prompt_version=PROMPT_VERSION,
            # CUSTOMER, not PRODUCT: this is a recording of a third party, and
            # the store's data policy decides whether it may leave the machine.
            provider=text_provider(recording.store, gateway.CUSTOMER),
            models=models_for(TASK_REASONING),
            system=SYSTEM,
            prompt=TEMPLATE.format(
                company=recording.prospect.company,
                # Whisper on a long call produces more than a prompt should
                # carry, and the useful parts of a sales call are at both ends.
                transcript=_trimmed(recording.transcript),
            ),
            validate=_valid,
            validation_message="تحلیل تماس ناقص بود",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Call analysis failed for recording %s: %s", recording.pk, exc)
        recording.error = f"متن پیاده شد ولی تحلیل نشد: {exc}"[:300]
        recording.save(update_fields=["error", "updated_at"])
        return

    recording.summary = str(parsed.get("summary", "")).strip()[:2000]
    recording.sentiment = str(parsed.get("sentiment", "")).strip().upper()[:8]
    recording.objections = _lines(parsed.get("objections"))
    recording.commitments = _lines(parsed.get("commitments"))
    recording.suggested_next = str(parsed.get("next", "")).strip()[:200]
    recording.status = Recording.Status.ANALYSED
    recording.save(update_fields=[
        "summary", "sentiment", "objections", "commitments", "suggested_next",
        "status", "updated_at",
    ])


#: Both ends of a long call, because that is where the useful parts are: what
#: they wanted at the start and what was agreed at the end. The middle of a
#: forty-minute call is where the prompt budget goes to die.
HEAD_CHARS = 6000
TAIL_CHARS = 4000


def _trimmed(text: str) -> str:
    if len(text) <= HEAD_CHARS + TAIL_CHARS:
        return text
    return (
        text[:HEAD_CHARS]
        + "\n\n[… میانه‌ی تماس کوتاه شده …]\n\n"
        + text[-TAIL_CHARS:]
    )
