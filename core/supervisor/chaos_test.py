# core/supervisor/chaos_test.py
from __future__ import annotations

import time
import uuid
from typing import Any

from core.storage.factory import build_storage


def chaos_enqueue_burst(storage: Any, mailbox: str, n: int = 10):
    ledger = storage.ledger
    for i in range(n):
        ledger.enqueue_scan(
            provider="gmail",
            mailbox=mailbox,
            lookback_hours=1,
            attachments_only=True,
            max_messages=10,
            payload={"chaos": True, "seq": i},
        )
    print(f"[CHAOS] Enqueued burst: {n} jobs for {mailbox}")


def chaos_simulate_stale_leader(storage: Any, hold_seconds: int = 180):
    """
    Create a leader lock but do not heartbeat. Watchdog should clear it.
    """
    ledger = storage.ledger
    fake_leader = f"chaos-leader-{uuid.uuid4().hex[:6]}"
    got = ledger.try_acquire_supervisor_lock(fake_leader, ttl_seconds=hold_seconds)
    print(f"[CHAOS] Acquired fake leader lock={got} leader_id={fake_leader}")
    print("[CHAOS] NOT writing heartbeat. Watchdog should clear lock after stale threshold.")
    time.sleep(hold_seconds + 10)


def main():
    storage = build_storage()
    print("CHAOS DB:", storage.ledger.db_path)

    # 1) Burst queue
    chaos_enqueue_burst(storage, mailbox="test@example.com", n=5)

    # 2) Stale leader simulation
    chaos_simulate_stale_leader(storage, hold_seconds=90)


if __name__ == "__main__":
    main()
