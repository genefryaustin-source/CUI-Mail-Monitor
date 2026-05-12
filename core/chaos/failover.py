# core/chaos/failover.py
import time
from typing import Any


def chaos_kill_leader(storage: Any):
    ledger = storage.ledger
    status = ledger.supervisor_status()

    if not status.get("has_lock"):
        return "No leader to kill."

    ledger.clear_supervisor_lock()
    ledger.record_watchdog_event(
        event_type="CHAOS_FAILOVER",
        leader_id=status.get("leader_id"),
        details={"reason": "chaos_test"},
    )

    return "Leader killed via chaos test."
