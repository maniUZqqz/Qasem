"""Pushing job progress instead of being asked for it every 2.5 seconds.

The panel polls. For a caption that takes eight seconds that is three requests
and nobody notices. For a video render it is one request every 2.5 seconds for
forty minutes — roughly a thousand round trips to say "still working", each one
waking Django, opening a database connection and running the staleness reaper.

**Why SSE and not WebSockets.** WebSockets need Channels, an ASGI server and a
second protocol through nginx. Server-sent events are one HTTP response that
stays open, work through the reverse proxy we already have, reconnect on their
own in every browser, and are exactly one-directional — which is what progress
is. The panel never needs to *send* anything down this channel; approving a
segment is a normal POST.

**Why it still polls the database.** There is no message bus between the Celery
worker and the web process other than Redis, and putting job progress through
Redis pub/sub would mean progress is lost whenever Redis is. The database row
is the truth either way; this loop reads it on the server, where the query is
local, instead of making the browser ask across the network. One connection
replaces four hundred requests per hour and the client-side cost drops to zero.

**The limit that makes this safe.** Gunicorn runs 3 workers x 4 threads here:
twelve concurrent requests for the whole product. An open stream occupies one
of those threads for its whole life, so a dozen shop owners watching renders
would leave nothing for anyone else — the API would appear dead to every other
customer while nothing is actually wrong.

So streams are capped per process, and over the cap the endpoint refuses with
`stream_unavailable` rather than accepting a connection it cannot afford. The
panel falls back to polling on that response, which is slower and completely
fine. A feature that degrades is worth more than one that takes the site down
under mild success.

(The proper fix is async workers — gevent or uvicorn — where an idle connection
costs no thread. That is a deployment-wide change to make deliberately, not a
side effect of adding a progress bar; `deploy/README.md` records it.)
"""
from __future__ import annotations

import json
import logging
import threading
import time

from django.conf import settings
from django.http import JsonResponse, StreamingHttpResponse
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.renderers import BaseRenderer, JSONRenderer
from rest_framework.views import APIView

from apps.stores import access

from . import machine
from .models import Job
from .serializers import JobSerializer

logger = logging.getLogger(__name__)

#: Per-process ceiling. Deliberately well below the thread count so ordinary
#: requests always have somewhere to run.
_open_streams = 0
_stream_lock = threading.Lock()


def max_streams() -> int:
    return int(settings.UPMARKET_AI.get("MAX_SSE_STREAMS", 4))


def _acquire() -> bool:
    global _open_streams
    with _stream_lock:
        if _open_streams >= max_streams():
            return False
        _open_streams += 1
        return True


def _release() -> None:
    global _open_streams
    with _stream_lock:
        _open_streams = max(0, _open_streams - 1)


def open_stream_count() -> int:
    return _open_streams

#: How often the server looks at the row. Faster than the old client poll
#: because the query is local and costs almost nothing.
TICK_SECONDS = 1.0

#: Longest a single stream stays open before the browser is asked to reconnect.
#: Long enough to be invisible, short enough that an abandoned tab lets go.
MAX_STREAM_SECONDS = 300

#: Nothing changed for this long → send a comment line so proxies and phones
#: do not decide the connection is dead.
HEARTBEAT_SECONDS = 20


def _event(name: str, payload: dict) -> str:
    return f"event: {name}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def job_events(job_id: int, user):
    """Yield SSE frames until the job stops needing to be watched.

    Three ways out, and all three send a final frame rather than just closing:
    the job reaches a terminal state, it parks for a human, or the stream ages
    out. A client that only ever sees the socket drop cannot tell "finished"
    from "the server died".
    """
    started = time.monotonic()
    last_payload: str | None = None
    last_sent = started

    try:
        yield from _tick(job_id, started, last_payload, last_sent)
    finally:
        # Whatever ends the stream — the job finishing, the client closing the
        # tab, an exception — the slot has to come back. A leaked counter is a
        # product that stops offering live progress until the next restart.
        _release()


def _tick(job_id: int, started: float, last_payload, last_sent):
    while True:
        try:
            job = Job.objects.filter(pk=job_id).first()
        except Exception as exc:  # noqa: BLE001 — a dropped DB link ends the stream
            logger.info("Job stream %s ended: %s", job_id, exc)
            yield _event("error", {"message": "ارتباط با سرور قطع شد."})
            return

        if job is None:
            yield _event("gone", {"message": "این Job دیگر وجود ندارد."})
            return

        payload = JobSerializer(job).data
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)

        if encoded != last_payload:
            yield _event("progress", payload)
            last_payload = encoded
            last_sent = time.monotonic()

        if job.state in machine.TERMINAL:
            yield _event("done", payload)
            return

        if job.awaiting_human:
            # Nothing will change until a person answers, so holding the
            # connection open would be waiting on a human with a worker thread.
            yield _event("waiting", payload)
            return

        now = time.monotonic()
        if now - started > MAX_STREAM_SECONDS:
            # `retry` tells the browser how soon to come back; EventSource
            # handles the reconnection itself.
            yield "retry: 1000\n"
            yield _event("reconnect", {"job": job.id})
            return
        if now - last_sent > HEARTBEAT_SECONDS:
            yield ": heartbeat\n\n"
            last_sent = now

        time.sleep(TICK_SECONDS)


class EventStreamRenderer(BaseRenderer):
    """Declares `text/event-stream` so DRF's content negotiation accepts it.

    Without this the endpoint answers **406 Not Acceptable** to any proper SSE
    client — which is every one of them, since they all send
    `Accept: text/event-stream`. The Django test client does not send that
    header, so the whole thing passed its tests and failed the first real
    request.

    Nothing is ever rendered through it: the stream is a StreamingHttpResponse
    and the refusal is a JsonResponse, both of which bypass the renderer.
    """

    media_type = "text/event-stream"
    format = "txt"
    charset = "utf-8"

    def render(self, data, accepted_media_type=None, renderer_context=None):
        return data


class JobStreamView(APIView):
    """GET /api/v1/jobs/{id}/stream/ — progress as server-sent events."""

    permission_classes = [IsAuthenticated]
    renderer_classes = [EventStreamRenderer, JSONRenderer]

    def get(self, request, pk):
        job = Job.objects.filter(
            store__in=access.stores_for(request.user), pk=pk
        ).first()
        if job is None:
            from django.http import Http404

            raise Http404("این Job وجود ندارد.")

        if not _acquire():
            # Refused, not queued. The panel polls instead, which is slower and
            # completely fine — far better than holding a thread this process
            # needs for ordinary requests.
            logger.info("SSE refused for job %s: %s streams already open", pk, _open_streams)
            # A plain JsonResponse, not a DRF Response: the negotiated
            # renderer here is the event-stream one, and pushing JSON through
            # it would label the body with the wrong content type.
            return JsonResponse(
                {"error": {
                    "code": "stream_unavailable",
                    "message": "ظرفیت اتصال زنده پر است؛ از حالت معمولی استفاده کنید.",
                }},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        response = StreamingHttpResponse(
            job_events(job.pk, request.user),
            content_type="text/event-stream",
        )
        # Without this nginx buffers the whole response and the stream arrives
        # all at once at the end, which is worse than polling.
        response["X-Accel-Buffering"] = "no"
        response["Cache-Control"] = "no-cache"
        return response
