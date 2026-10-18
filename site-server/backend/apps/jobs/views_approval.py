"""The human half of incremental generation.

A job that stops after five seconds is only useful if there is somewhere to say
"yes, keep going" or "no, stop". These are those endpoints.

Rejecting is not the same as cancelling, and the difference is the credit:

* **reject** — this segment is wrong. The job stops, and because nothing usable
  came out of it, the credit goes back through the quality path
  (`apps.billing.credits`), which counts it as an attempt against the quality
  guarantee.
* **cancel** — I have changed my mind. Same refund, but not counted as a
  quality failure, because the model did nothing wrong.

Conflating them would either make our own quality numbers look terrible every
time someone changes their mind, or let genuine failures hide.
"""
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.stores import access

from . import cancellation, machine
from .models import Job
from .serializers import JobSerializer


def _job(request, pk, permission=access.CONTENT):
    store_ids = access.stores_for(request.user)
    job = Job.objects.filter(store__in=store_ids, pk=pk).select_related("store").first()
    if job is None:
        from django.http import Http404

        raise Http404("این Job وجود ندارد.")
    access.get_store(request.user, job.store_id, permission)
    return job


class JobApproveView(APIView):
    """POST /api/v1/jobs/{id}/approve/ — carry on from the preview."""

    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        job = _job(request, pk)
        if not job.awaiting_human:
            return Response(
                {"error": {
                    "code": "not_awaiting_approval",
                    "message": f"این کار «{machine.label(job.state)}» است و تأیید نمی‌خواهد.",
                }},
                status=status.HTTP_409_CONFLICT,
            )
        job.advance(Job.State.APPROVED, label="تأیید شد — ادامه می‌دهیم")
        # Resuming is the pipeline's business, not the endpoint's: the task that
        # parked the job is the one that knows what comes next.
        from .resume import resume

        resume(job)
        job.refresh_from_db()
        return Response(JobSerializer(job).data)


class JobRejectView(APIView):
    """POST /api/v1/jobs/{id}/reject/ — this piece is wrong, stop.

    Counted against the quality guarantee, unlike cancel.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        job = _job(request, pk)
        if job.state in machine.TERMINAL:
            return Response(
                {"error": {"code": "already_finished", "message": "این کار تمام شده است."}},
                status=status.HTTP_409_CONFLICT,
            )

        reason = str(request.data.get("reason", "")).strip() or "فروشگاه‌دار خروجی را نپسندید"
        outcome = cancellation.cancel(job, actor=request.user, reason=reason)
        job.refresh_from_db()
        return Response({"job": JobSerializer(job).data, **outcome})


class JobRegenerateView(APIView):
    """POST /api/v1/jobs/{id}/regenerate/ — this piece is wrong, make it again.

    The third answer at a preview, and the one ROADMAP §9.3 and §9.9 describe:
    regenerate **one** segment, with the prompt compiled around what was wrong,
    and leave the finished ones alone. Until this existed the owner's only
    options were to approve a clip they disliked — whose last frame then
    anchored everything after it — or to cancel the whole job.

    Billing: the rejected render is refunded and counted as an attempt against
    the quality guarantee, exactly like reject; the new render is reserved
    through the same attempt chain, which makes it free once the guarantee's
    attempt count is used up. Later segments only exist if the mode was
    switched mid-run; they were rendered from the rejected frame, so they are
    reset and refunded too — and the response says so.
    """

    permission_classes = [IsAuthenticated]

    CAUSES = {
        "OBJECT": "OBJECT_CONSISTENCY",
        "CHARACTER": "CHARACTER_CONSISTENCY",
        "ANATOMY": "ANATOMY",
        "ARTIFACTS": "ARTIFACTS",
        "MOTION": "MOTION_JUMP",
        "FROZEN": "FROZEN",
        "TALKING": "TALKING",
        "OTHER": "",
    }

    def post(self, request, pk):
        from apps.billing import credits
        from apps.billing.models import Usage
        from apps.content.models import VideoSegment

        job = _job(request, pk)
        if not job.awaiting_human:
            return Response(
                {"error": {
                    "code": "not_awaiting_approval",
                    "message": f"این کار «{machine.label(job.state)}» است و منتظر پاسخ نیست.",
                }},
                status=status.HTTP_409_CONFLICT,
            )
        script_id = (job.context or {}).get("script_id")
        index = (job.preview or {}).get("segment_index")
        if not script_id or not index:
            return Response(
                {"error": {"code": "no_segment", "message": "این کار قطعه‌ای برای بازسازی ندارد."}},
                status=status.HTTP_409_CONFLICT,
            )
        segment = VideoSegment.objects.filter(script_id=script_id, index=index).first()
        if segment is None or segment.status != VideoSegment.Status.DONE:
            return Response(
                {"error": {"code": "no_segment", "message": "قطعه‌ی آماده‌ای برای بازسازی پیدا نشد."}},
                status=status.HTTP_409_CONFLICT,
            )

        reason = str(request.data.get("reason", "")).strip() or "فروشگاه‌دار قطعه را نپسندید"
        raw_causes = request.data.get("causes") or []
        if isinstance(raw_causes, str):
            raw_causes = [raw_causes]
        causes = []
        for item in raw_causes:
            mapped = self.CAUSES.get(str(item).strip().upper(), str(item).strip().upper())
            if mapped and mapped not in causes:
                causes.append(mapped)
        # What QC itself flagged is a cause too — the owner is confirming it.
        qc_report = (segment.metadata or {}).get("qc") or {}
        for cause in qc_report.get("needs_regeneration") or []:
            if cause not in causes:
                causes.append(cause)

        refunded = 0
        usage = None
        usage_id = (segment.metadata or {}).get("usage_id")
        if usage_id:
            usage = Usage.objects.filter(pk=usage_id, store=job.store).first()
        if usage is not None:
            try:
                credits.refund(usage, reason=reason, source=credits.CUSTOMER, actor=request.user)
                refunded += usage.quantity
            except credits.NotRefundable:
                pass

        reset = [self._send_back(segment, reason=reason, causes=causes, usage=usage)]

        # Segments rendered AFTER the rejected one were anchored on its last
        # frame. Only possible when the mode was switched to Auto mid-run.
        for later in VideoSegment.objects.filter(
            script_id=script_id, index__gt=index, status=VideoSegment.Status.DONE,
        ):
            later_usage = None
            later_id = (later.metadata or {}).get("usage_id")
            if later_id:
                later_usage = Usage.objects.filter(pk=later_id, store=job.store).first()
            if later_usage is not None:
                try:
                    credits.refund(
                        later_usage, reason="قطعه‌ی قبلی دوباره ساخته می‌شود",
                        source=credits.CUSTOMER, actor=request.user,
                    )
                    refunded += later_usage.quantity
                except credits.NotRefundable:
                    pass
            reset.append(self._send_back(
                later, reason="قطعه‌ی قبلی دوباره ساخته می‌شود", causes=[], usage=later_usage,
            ))

        guarantee = credits.guarantee_status(usage) if usage is not None else None

        job.advance(Job.State.APPROVED, label=f"قطعه {index} دوباره ساخته می‌شود")
        from .resume import resume

        resume(job)
        job.refresh_from_db()
        return Response({
            "job": JobSerializer(job).data,
            "regenerating": reset,
            "refunded": refunded,
            "causes": causes,
            "guarantee": guarantee,
            "message": (
                f"قطعه {index} دوباره ساخته می‌شود"
                + (f" و {refunded} ثانیه اعتبار برگشت" if refunded else "")
                + (f"؛ {len(reset) - 1} قطعه‌ی بعدی هم چون از روی همین قطعه ساخته شده بود بازسازی می‌شود"
                   if len(reset) > 1 else "")
                + "."
            ),
        })

    @staticmethod
    def _send_back(segment, *, reason: str, causes: list[str], usage) -> int:
        """Put a finished segment back in the queue, keeping its history.

        The file is not deleted: the panel shows the rejected attempt next to
        the new one, and a botched second render should be recoverable.
        """
        from apps.content.models import VideoSegment

        history = list((segment.metadata or {}).get("attempts") or [])
        qc_report = (segment.metadata or {}).get("qc") or {}
        if segment.video and not any(h.get("file") == segment.video.name for h in history):
            history.append({
                "attempt": (segment.metadata or {}).get("attempt") or len(history) + 1,
                "seed": (segment.metadata or {}).get("seed"),
                "file": segment.video.name,
                "overall": qc_report.get("overall"),
                "verdict": qc_report.get("verdict"),
                "causes": list(qc_report.get("needs_regeneration") or []),
                "rejected_by": "CUSTOMER",
                "reason": reason,
            })
        segment.metadata = {
            **(segment.metadata or {}),
            "attempts": history,
            "regen": {
                "causes": causes,
                "reason": reason,
                "by": "CUSTOMER",
                "usage_id": usage.pk if usage is not None else None,
            },
        }
        segment.video = None
        segment.last_frame = None
        segment.status = VideoSegment.Status.PENDING
        segment.retry_count += 1
        segment.error = ""
        segment.save()
        return segment.index


class JobModeView(APIView):
    """PATCH /api/v1/jobs/{id}/mode/ — switch between Safe and Auto mid-flight.

    Allowed while the job is still running because that is when the owner
    learns which one they wanted: the first approval prompt is what tells them
    whether they care to see the rest.
    """

    permission_classes = [IsAuthenticated]

    def patch(self, request, pk):
        job = _job(request, pk)
        mode = request.data.get("mode")
        if mode not in Job.Mode.values:
            return Response(
                {"error": {"code": "bad_mode", "message": "حالت نامعتبر است."}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if job.state in machine.TERMINAL:
            return Response(
                {"error": {"code": "already_finished", "message": "این کار تمام شده است."}},
                status=status.HTTP_409_CONFLICT,
            )
        job.mode = mode
        job.save(update_fields=["mode", "updated_at"])
        return Response(JobSerializer(job).data)
