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

        task = CampaignTask.objects.create(
            campaign=campaign,
            store=campaign.store,
            kind=kind,
            title=title[:200],
            detail=str(request.data.get("detail", ""))[:2000],
            due_at=request.data.get("due_at") or None,
            priority=int(request.data.get("priority") or CampaignTask.Priority.NORMAL),
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
                setattr(task, field, request.data[field])
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
