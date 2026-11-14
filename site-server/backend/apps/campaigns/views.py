from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.jobs.models import Job
from apps.jobs.serializers import JobSerializer
from apps.jobs.services import dispatch_job

from . import scheduling
from .models import Campaign, PublishJob
from .serializers import CampaignSerializer
from .tasks import publish_campaign_task
from apps.stores import access

# one list for «انتشار حالا» and «زمان‌بندی»
SUPPORTED_PLATFORMS = set(scheduling.SUPPORTED_PLATFORMS)

#: What followers see of a campaign. Editing any of these after approval means
#: the owner approved something else, so its queued posts are cancelled. (The
#: name, goal, audience and notes are for the team; changing them changes
#: nothing that is posted.)
_CONTENT_FIELDS = ("product_id", "poster_id", "product_image_id", "caption_id", "video_script_id")


def _content_signature(campaign) -> tuple:
    return tuple(getattr(campaign, name) for name in _CONTENT_FIELDS)


class CampaignViewSet(viewsets.ModelViewSet):
    serializer_class = CampaignSerializer

    def get_queryset(self):
        qs = (
            Campaign.objects.filter(store__in=access.stores_for(self.request.user))
            .select_related("product", "poster", "product_image", "caption", "video_script")
            .prefetch_related("publish_jobs")
        )
        store_id = self.request.query_params.get("store")
        if store_id:
            qs = qs.filter(store_id=store_id)
        return qs

    def perform_create(self, serializer):
        product = serializer.validated_data["product"]
        serializer.save(store=product.store)

    def _invalid_transition(self, campaign, target):
        return Response(
            {
                "error": {
                    "code": "invalid_state",
                    "message": f"از وضعیت «{campaign.approval_state}» نمی‌توان به «{target}» رفت.",
                }
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        campaign = self.get_object()
        allowed = {
            Campaign.ApprovalState.DRAFT,
            Campaign.ApprovalState.REJECTED,
            Campaign.ApprovalState.APPROVED,
        }
        if campaign.approval_state not in allowed:
            return self._invalid_transition(campaign, "APPROVED")
        campaign.approval_state = Campaign.ApprovalState.APPROVED
        campaign.save(update_fields=["approval_state", "updated_at"])
        return Response(CampaignSerializer(campaign, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        campaign = self.get_object()
        allowed = {
            Campaign.ApprovalState.DRAFT,
            Campaign.ApprovalState.APPROVED,
            Campaign.ApprovalState.REJECTED,
        }
        if campaign.approval_state not in allowed:
            return self._invalid_transition(campaign, "REJECTED")
        campaign.approval_state = Campaign.ApprovalState.REJECTED
        note = str(request.data.get("note", "") or "")
        if note:
            campaign.notes = (campaign.notes + "\n" if campaign.notes else "") + f"رد شد: {note}"
        campaign.save()
        # a rejected campaign must not still go out at 9 a.m. from the queue
        cancelled = scheduling.cancel_pending(campaign)
        data = dict(CampaignSerializer(campaign, context={"request": request}).data)
        data["cancelled_scheduled"] = cancelled
        return Response(data)

    def update(self, request, *args, **kwargs):
        """Editing what is posted cancels the posts queued with the old content."""
        before = _content_signature(self.get_object())
        response = super().update(request, *args, **kwargs)
        campaign = self.get_object()
        if _content_signature(campaign) != before:
            cancelled = scheduling.cancel_pending(campaign)
            if cancelled and isinstance(response.data, dict):
                response.data["cancelled_scheduled"] = cancelled
        return response

    @action(detail=True, methods=["post"])
    def publish(self, request, pk=None):
        campaign = self.get_object()
        if campaign.approval_state not in {
            Campaign.ApprovalState.APPROVED,
            Campaign.ApprovalState.PUBLISHED,
        }:
            return Response(
                {
                    "error": {
                        "code": "not_approved",
                        "message": "قبل از انتشار، کمپین باید تأیید شود.",
                    }
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        platforms = request.data.get("platforms") or []
        platforms = [str(p).lower() for p in platforms if str(p).lower() in SUPPORTED_PLATFORMS]
        if not platforms:
            return Response(
                {
                    "error": {
                        "code": "no_platforms",
                        "message": f"حداقل یک پلتفرم انتخاب کنید: {sorted(SUPPORTED_PLATFORMS)}",
                    }
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # A PENDING PublishJob is only "in progress" while its publishing Job is
        # actually alive; leftovers from a failed dispatch/dead worker are reset
        # so publishing can never deadlock.
        pending = campaign.publish_jobs.filter(
            status=PublishJob.Status.PENDING, platform__in=platforms
        )
        if pending.exists():
            dispatch_alive = Job.objects.filter(
                store=campaign.store,
                type=Job.Type.PUBLISHING,
                state__in=[Job.State.QUEUED, Job.State.RUNNING],
                context__campaign_id=campaign.id,
            ).exists()
            if dispatch_alive:
                return Response(
                    {
                        "error": {
                            "code": "publish_in_progress",
                            "message": "برای این پلتفرم(ها) یک انتشار در حال انجام است.",
                        }
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            pending.update(
                status=PublishJob.Status.FAILED,
                last_error="انتشار نیمه‌کاره ماند (صف/worker در دسترس نبود) — بازنشانی شد.",
            )

        # Never send the same campaign to a platform twice unless explicitly asked.
        resend = bool(request.data.get("resend"))
        if not resend:
            already_sent = set(
                campaign.publish_jobs.filter(
                    status=PublishJob.Status.SENT, platform__in=platforms
                ).values_list("platform", flat=True)
            )
            platforms = [p for p in platforms if p not in already_sent]
            if not platforms:
                return Response(
                    {
                        "error": {
                            "code": "already_published",
                            "message": "این کمپین قبلاً به همه پلتفرم‌های انتخابی ارسال شده است. "
                            "برای ارسال مجدد، گزینه «ارسال مجدد» را فعال کنید.",
                        }
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

        publish_jobs = [
            PublishJob.objects.create(store=campaign.store, campaign=campaign, platform=platform)
            for platform in platforms
        ]
        job = Job.objects.create(
            store=campaign.store,
            type=Job.Type.PUBLISHING,
            context={"campaign_id": campaign.id, "platforms": platforms},
        )
        error = dispatch_job(
            job, publish_campaign_task, job.id, campaign.id, [p.id for p in publish_jobs]
        )
        if error is not None:
            # dispatch failed → these rows will never be processed; mark them so
            # they cannot block the next publish attempt
            PublishJob.objects.filter(id__in=[p.id for p in publish_jobs]).update(
                status=PublishJob.Status.FAILED,
                last_error="ارسال به صف انجام نشد (Redis/Celery در دسترس نیست).",
            )
            return error
        job.refresh_from_db()
        return Response(
            {"job_id": job.id, "job": JobSerializer(job).data}, status=status.HTTP_202_ACCEPTED
        )


class CampaignScheduleView(APIView):
    """Queue a campaign to publish at a future moment. Phase 24.

    Everything the interactive publish refuses is refused here too — the clock
    must not be a way around the owner's approval: a draft or rejected campaign,
    a platform that does not exist, a list given as text. The same request sent
    twice queues one post, not two.
    """

    permission_classes = [IsAuthenticated]

    @staticmethod
    def _error(code, message, http=status.HTTP_400_BAD_REQUEST):
        return Response({"error": {"code": code, "message": message}}, status=http)

    def post(self, request, pk):
        from django.db import transaction
        from django.utils.dateparse import parse_datetime

        campaign = get_object_or_404(
            Campaign.objects.filter(store__in=access.stores_for(request.user))
            .select_related("store"),
            pk=pk,
        )
        access.get_store(request.user, campaign.store_id, access.CAMPAIGNS)

        if not scheduling.publishable(campaign):
            return self._error(
                "not_approved",
                "قبل از زمان‌بندی، کمپین باید تأیید شود (کمپینِ پیش‌نویس یا ردشده زمان‌بندی نمی‌شود).",
            )

        try:
            when = parse_datetime(str(request.data.get("when", "")))
        except ValueError:  # well-formed but impossible, e.g. month 13
            when = None
        if when is None:
            return self._error("bad_time", "زمان انتشار خوانده نشد.")
        if timezone.is_naive(when):
            when = timezone.make_aware(when)

        raw = request.data.get("platforms")
        if raw in (None, "", []):
            raw = ["instagram"]
        if not isinstance(raw, (list, tuple)):
            return self._error(
                "bad_platforms", "پلتفرم‌ها باید به‌صورت فهرست فرستاده شوند، نه متن.",
            )
        platforms: list[str] = []
        for item in raw:
            name = str(item or "").strip().lower()
            if name not in platforms:  # «instagram» twice is one post
                platforms.append(name)
        unknown = [p for p in platforms if p not in SUPPORTED_PLATFORMS]
        if unknown:
            return self._error(
                "bad_platform",
                f"پلتفرم ناشناخته: {', '.join(unknown)}. "
                f"یکی از {', '.join(sorted(SUPPORTED_PLATFORMS))} را انتخاب کنید.",
            )

        created = []
        try:
            # all or nothing: a bad time must not leave half the platforms queued
            with transaction.atomic():
                for platform in platforms:
                    job, is_new = scheduling.schedule_get_or_create(campaign, platform, when)
                    created.append({
                        "id": job.pk, "platform": platform, "at": job.scheduled_for,
                        "created": is_new,
                    })
        except scheduling.ScheduleError as exc:
            # Refused rather than published now: someone who typed yesterday's
            # date meant a different date, and honouring it literally posts to
            # their followers this second.
            return self._error(exc.code, str(exc))

        fresh = any(row["created"] for row in created)
        return Response(
            {"scheduled": created},
            status=status.HTTP_201_CREATED if fresh else status.HTTP_200_OK,
        )


class ScheduledPublishesView(APIView):
    """What is queued to go out, and what missed its window."""

    permission_classes = [IsAuthenticated]

    def get(self, request, store_id):
        from apps.stores import access

        store = access.get_store(request.user, store_id, access.CAMPAIGNS, write=False)
        rows = (
            PublishJob.objects
            .filter(store=store, scheduled_for__isnull=False)
            .select_related("campaign")
            .order_by("scheduled_for")[:100]
        )
        return Response([
            {
                "id": row.pk,
                "campaign": row.campaign.name,
                "platform": row.platform,
                "scheduled_for": row.scheduled_for,
                "status": row.status,
                "status_label": row.get_status_display(),
                "error": row.last_error,
                "published_at": row.published_at,
            }
            for row in rows
        ])

    def delete(self, request, store_id):
        """Cancel a queued publish before it goes out."""
        from apps.stores import access

        store = access.get_store(request.user, store_id, access.CAMPAIGNS)
        job = PublishJob.objects.filter(
            store=store, pk=request.query_params.get("id"),
            status=PublishJob.Status.PENDING,
        ).first()
        if job is None:
            return Response(
                {"error": {
                    "code": "not_pending",
                    "message": "این انتشار در صف نیست — شاید همین حالا منتشر شده.",
                }},
                status=status.HTTP_409_CONFLICT,
            )
        job.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class PerformanceView(APIView):
    """What actually happened to what we published. Phase 25."""

    permission_classes = [IsAuthenticated]

    def get(self, request, store_id):
        from apps.stores import access

        from . import learning

        store = access.get_store(request.user, store_id, access.ANALYTICS, write=False)
        try:
            days = int(request.query_params.get("days", 90))
        except (TypeError, ValueError):
            days = 90
        return Response(learning.what_worked(store, days))

    def post(self, request, store_id):
        """Fetch fresh numbers now rather than waiting for the hourly sweep."""
        from apps.stores import access

        from . import learning

        store = access.get_store(request.user, store_id, access.ANALYTICS)
        checked = 0
        for publish_job in learning.due_for_refresh():
            if publish_job.store_id != store.pk:
                continue
            try:
                learning.collect_one(publish_job)
                checked += 1
            except Exception:  # noqa: BLE001 — one post must not stop the rest
                continue
        return Response({"checked": checked, **learning.what_worked(store)})
