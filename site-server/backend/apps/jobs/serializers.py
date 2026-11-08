from rest_framework import serializers

from . import machine
from .models import Job


class JobSerializer(serializers.ModelSerializer):
    state_label = serializers.SerializerMethodField()
    #: Whether the panel should draw approve/reject buttons. Derived rather than
    #: inferred in the UI, so one list of human-waiting states exists.
    awaiting_human = serializers.BooleanField(read_only=True)
    #: «پردازشِ دوباره» برای کارِ ناموفق/لغوشده (apps.jobs.retry) — بی پرس‌وجوی اضافه
    can_retry = serializers.SerializerMethodField()

    class Meta:
        model = Job
        fields = [
            "id",
            "store",
            "type",
            "state",
            "state_label",
            "awaiting_human",
            "mode",
            "preview",
            "cancel_requested",
            "progress_step",
            "total_steps",
            "current_step_label",
            "retry_count",
            "can_retry",
            "error",
            "context",
            "result",
            "created_at",
            "updated_at",
        ]

    def get_state_label(self, obj) -> str:
        return machine.label(obj.state)

    def get_can_retry(self, obj) -> bool:
        from . import retry

        try:
            return retry.can_retry(obj)
        except Exception:  # noqa: BLE001 — یک دکمهٔ کم، نه یک فهرستِ خراب
            return False
