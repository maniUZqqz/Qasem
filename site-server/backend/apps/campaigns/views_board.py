"""The campaign board's API. §29.1"""
from django.contrib.auth.models import User
from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.stores import access

from .models import Campaign
from .tasks_board import CampaignTask, board, seed


class CampaignTaskSerializer(serializers.ModelSerializer):
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)
    #: The state that is actually true — read from the job when one is doing
    #: the work. `state` is still exposed so the panel can tell the two apart.
    effective_state = serializers.CharField(read_only=True)
    state_label = serializers.SerializerMethodField()
    is_late = serializers.BooleanField(read_only=True)
    waiting_on_person = serializers.BooleanField(read_only=True)
    assigned_username = serializers.CharField(
        source="assigned_to.username", read_only=True, default=None,
    )
    #: The panel greys out the state control on these rather than letting
    #: someone tick off a render that is still going.
    machine_owned = serializers.SerializerMethodField()

    class Meta:
        model = CampaignTask
        fields = [
            "id", "kind", "kind_label", "title", "detail", "state",
            "effective_state", "state_label", "priority", "assigned_to",
            "assigned_username", "due_at", "is_late", "waiting_on_person",
            "job", "machine_owned", "because", "order", "created_at",
        ]

    def get_state_label(self, obj) -> str:
        return dict(CampaignTask.State.choices).get(obj.effective_state, obj.state)

    def get_machine_owned(self, obj) -> bool:
        return obj.job_id is not None


def _campaign(user, pk, permission=access.CAMPAIGNS, write=True):
    campaign = get_object_or_404(Campaign.objects.select_related("store"), pk=pk)
    access.get_store(user, campaign.store_id, permission, write=write)
    return campaign


#: A task's detail is the written plan (slide texts, scripts, reply templates).
#: It used to be cut at 2000 characters without a word; the column is a TextField,
#: so the cap only needs to stop abuse.
DETAIL_MAX = 8000


def _clean_due(value):
    """`due_at` from a request: a timezone-aware datetime, or None for "no date".

    A string used to be stored as is. The row saved, but reading it back crashed
    (`is_late` compares it with now()), so the *response* was a 500 for a task
    that had in fact been created - and a garbage string raised the same 500 on
    PATCH. Now a bad value is a 400 that says what to send.
    """
    if value in (None, ""):
        return None
    from django.utils import timezone
    from django.utils.dateparse import parse_datetime

    parsed = value if hasattr(value, "tzinfo") else parse_datetime(str(value))
    if parsed is None:
        raise ValueError("bad due")
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed)
    return parsed


def _bad_due():
    return Response(
        {"error": {"code": "bad_due", "message": "موعد باید تاریخ و ساعتِ معتبر باشد، مثل 2026-11-13T12:00:00Z."}},
        status=status.HTTP_400_BAD_REQUEST,
    )


def _clean_priority(value):
    try:
        n = int(value or CampaignTask.Priority.NORMAL)
    except (TypeError, ValueError):
        raise ValueError("bad priority")
    if n not in CampaignTask.Priority.values:
        raise ValueError("bad priority")
    return n


def _bad_priority():
    return Response(
        {"error": {"code": "bad_priority", "message": "اولویت باید یکی از ۱ (کم)، ۲ (معمولی) یا ۳ (زیاد) باشد."}},
        status=status.HTTP_400_BAD_REQUEST,
    )


class CampaignBoardView(APIView):
    """Everything this campaign needs, grouped by kind. §29.1"""

    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        campaign = _campaign(request.user, pk, write=False)
        data = board(campaign)
        return Response({
            "campaign": {"id": campaign.pk, "name": campaign.name},
            "columns": [
                {
                    **column,
                    "tasks": CampaignTaskSerializer(column["tasks"], many=True).data,
                }
                for column in data["columns"]
            ],
            "total": data["total"],
            "done": data["done"],
            "percent": data["percent"],
            "late": CampaignTaskSerializer(data["late"], many=True).data,
            "waiting": CampaignTaskSerializer(data["waiting"], many=True).data,
            "kinds": [
                {"key": k, "title": v} for k, v in CampaignTask.Kind.choices
            ],
            "states": [
                {"key": k, "title": v} for k, v in CampaignTask.State.choices
            ],
        })

    def post(self, request, pk):
        """Add one task, or fill an empty board with the usual ones."""
        campaign = _campaign(request.user, pk)

        if request.data.get("seed"):
            created = seed(campaign)
            if not created:
                return Response(
                    {"error": {
                        "code": "not_empty",
                        "message": (
                            "این کمپین از قبل کار دارد. فهرست پیش‌فرض فقط روی "
                            "تخته‌ی خالی گذاشته می‌شود تا کارهایی که پاک کرده‌اید "
                            "دوباره برنگردند."
                        ),
                    }},
                    status=status.HTTP_409_CONFLICT,
                )
            return Response(
                CampaignTaskSerializer(created, many=True).data,
                status=status.HTTP_201_CREATED,
            )

        title = str(request.data.get("title", "")).strip()
        if not title:
            return Response(
                {"error": {"code": "no_title", "message": "کار بدون عنوان نمی‌شود."}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        kind = str(request.data.get("kind", CampaignTask.Kind.OTHER)).upper()
        if kind not in CampaignTask.Kind.values:
            kind = CampaignTask.Kind.OTHER

        try:
            due_at = _clean_due(request.data.get("due_at"))
        except ValueError:
            return _bad_due()
        try:
            priority = _clean_priority(request.data.get("priority"))
        except ValueError:
            return _bad_priority()

        task = CampaignTask.objects.create(
            campaign=campaign,
            store=campaign.store,
            kind=kind,
            title=title[:200],
            detail=str(request.data.get("detail", ""))[:DETAIL_MAX],
            because=str(request.data.get("because", ""))[:300],
            due_at=due_at,
            priority=priority,
            order=campaign.tasks.count(),
        )
        return Response(
            CampaignTaskSerializer(task).data, status=status.HTTP_201_CREATED,
        )


class CampaignTaskView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, pk, task_id):
        campaign = _campaign(request.user, pk)
        task = get_object_or_404(CampaignTask, pk=task_id, campaign=campaign)

        if "state" in request.data:
            state = str(request.data["state"]).upper()
            if state not in CampaignTask.State.values:
                return Response(
                    {"error": {"code": "bad_state", "message": "این وضعیت را نداریم."}},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            try:
                task.mark(state)
            except ValueError as exc:
                # A job-backed task: ticking it off would make the board say
                # done over a render that is still going.
                return Response(
                    {"error": {"code": "machine_owned", "message": str(exc)}},
                    status=status.HTTP_409_CONFLICT,
                )

        changed = []
        for field in ("title", "detail", "due_at", "priority", "order", "kind"):
            if field in request.data:
                value = request.data[field]
                if field == "due_at":
                    try:
                        value = _clean_due(value)
                    except ValueError:
                        return _bad_due()
                elif field == "priority":
                    try:
                        value = _clean_priority(value)
                    except ValueError:
                        return _bad_priority()
                elif field == "detail":
                    value = str(value or "")[:DETAIL_MAX]
                elif field == "title":
                    value = str(value or "").strip()[:200]
                    if not value:
                        return Response(
                            {"error": {"code": "no_title", "message": "کار بدون عنوان نمی‌شود."}},
                            status=status.HTTP_400_BAD_REQUEST,
                        )
                setattr(task, field, value)
                changed.append(field)

        if "assigned_to" in request.data:
            username = request.data["assigned_to"]
            if username in (None, "", "me"):
                task.assigned_to = request.user if username == "me" else None
            else:
                person = User.objects.filter(username=username).first()
                if person is None or not access.role_of(person, campaign.store):
                    return Response(
                        {"error": {
                            "code": "not_a_member",
                            "message": "این شخص عضو این فروشگاه نیست.",
                        }},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                task.assigned_to = person
            changed.append("assigned_to")

        if changed:
            task.save(update_fields=changed + ["updated_at"])
        return Response(CampaignTaskSerializer(task).data)

    def delete(self, request, pk, task_id):
        campaign = _campaign(request.user, pk)
        get_object_or_404(CampaignTask, pk=task_id, campaign=campaign).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class StorePlannedView(APIView):
    """Everything on the shop's campaign boards that has a suggested date.

    The publishing calendar only knew about posts that were *scheduled*. A
    content plan written ahead of time (four weeks of carousels, reels, stories)
    lives on the boards as tasks with a suggested due date, and until now
    nothing showed it on a calendar - the one place a person looks to ask
    "what goes out when, and where are the gaps?". This lists those tasks;
    it schedules nothing and publishes nothing.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, store_id):
        store = access.get_store(request.user, store_id, access.CAMPAIGNS, write=False)
        rows = (
            CampaignTask.objects
            .filter(store=store, due_at__isnull=False)
            .exclude(state__in=[CampaignTask.State.DROPPED])
            .select_related("campaign")
            .order_by("due_at", "order", "id")[:300]
        )
        return Response([
            {
                "id": t.pk,
                "campaign_id": t.campaign_id,
                "campaign": t.campaign.name,
                "kind": t.kind,
                "kind_label": t.get_kind_display(),
                "title": t.title,
                "due_at": t.due_at,
                "state": t.effective_state,
                "state_label": dict(CampaignTask.State.choices).get(t.effective_state, t.state),
            }
            for t in rows
        ])
