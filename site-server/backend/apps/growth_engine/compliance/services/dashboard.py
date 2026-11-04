from ..models import GrowthSettings, SuppressionEntry


def block() -> dict:
    s = GrowthSettings.load()
    return {"suppressed": SuppressionEntry.objects.count(), "emergency_stop": s.emergency_stop, "sending_enabled": s.sending_enabled}
