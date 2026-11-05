"""Sandbox prototype: stable Bark idempotency identity without production side effects."""
from datetime import datetime
from zoneinfo import ZoneInfo

BEIJING = ZoneInfo("Asia/Shanghai")
SCHEDULED_HOURS = (8, 10, 16, 20, 22)

def delivery_identity(report: dict, *, event_name: str, run_id: str,
                      recovery_slot: str | None = None) -> str:
    """Return a stable identity for one logical delivery attempt.

    Scheduled duplicates in the same Beijing slot collapse to one identity.
    Watchdog recovery uses its durable recovery_slot marker.
    Manual runs remain distinct by GitHub run_id.
    """
    day = str(report.get("signal_day") or "")
    if event_name == "workflow_dispatch" and recovery_slot:
        return recovery_slot if recovery_slot.startswith("recovery:") else f"recovery:{recovery_slot}"
    if event_name == "schedule":
        raw = report.get("started_at")
        if not raw:
            raise ValueError("scheduled report requires started_at")
        stamp = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=BEIJING)
        local = stamp.astimezone(BEIJING)
        if local.hour not in SCHEDULED_HOURS:
            raise ValueError("scan start is not within a configured scheduled hour")
        return f"schedule:{day}:{local:%H}"
    if not run_id:
        raise ValueError("manual delivery requires a GitHub run_id")
    return f"manual:{run_id}"
