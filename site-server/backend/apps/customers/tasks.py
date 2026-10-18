"""Background work for the inbox.

One task, and it exists for a timing reason rather than a load one: a platform
webhook gets a few seconds before the delivery counts as failed, and an LLM
turn does not reliably fit in that. So the request stores the message and this
answers it.
"""
from celery import shared_task


@shared_task
def answer_inbound(conversation_id: int, text: str, message_id: int | None = None) -> None:
    """Run the sales agent for a message a webhook already stored.

    `message_id` is optional so a task queued by an older worker still runs;
    with it, an image on that message is filed as a payment receipt first.
    """
    from .views_webhook import run_agent_for

    run_agent_for(conversation_id, text, message_id)


@shared_task
def analyse_call(recording_id: int) -> None:
    """Transcribe and analyse a recorded call.

    Whisper on a twenty-minute call is minutes of GPU. Doing it in the request
    would time out in front of the person who just uploaded the file.
    """
    from services.research import call_analysis

    from .calls import Recording

    recording = Recording.objects.filter(pk=recording_id).first()
    if recording:
        call_analysis.run(recording)


@shared_task
def release_expired_reservations() -> int:
    """Put back on the shelf what nobody paid for in time.

    Runs on the beat rather than as a per-order countdown: a scheduled eta
    dies with the worker holding it, and a scan over rows does not.
    """
    from . import stock

    return stock.release_expired()
