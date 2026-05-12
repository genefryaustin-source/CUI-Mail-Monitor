# core/supervisor/watchdog_supervisor.py
from __future__ import annotations

import logging
import os
import random
import signal
import time
from typing import Any, Optional
from core.supervisor.system_supervisor import SystemSupervisor


WATCHDOG_JOB_TIMEOUT_MS = 120_000  # 2 minutes
MAX_RETRIES = 3  # 🔥 ADD THIS


def recover_stuck_processing_jobs(ledger):
    import time

    now = int(time.time() * 1000)

    with ledger._connect() as con:

        rows = con.execute("""
            SELECT *
            FROM processing_queue
            WHERE status = 'PROCESSING'
        """).fetchall()

        recovered = 0

        for job in rows:
            job_id = job["id"]
            started = job.get("started_at_ms")

            if not started:
                continue

            age = now - int(started)

            if age > WATCHDOG_JOB_TIMEOUT_MS:
                attempts = job.get("attempts", 0) or 0

                # 🔥 OPTIONAL HARDENING GOES HERE
                if attempts >= MAX_RETRIES:
                    logger.error(f"💀 WATCHDOG: job {job_id} exceeded retries → FAILED")

                    con.execute("""
                        UPDATE processing_queue
                        SET
                            status = 'FAILED',
                            updated_at_ms = ?
                        WHERE id = ?
                    """, (now, job_id))

                    continue

                # 🔁 NORMAL RECOVERY PATH
                logger.warning(
                    f"🛑 WATCHDOG JOB STALLED job={job_id} age={age / 1000:.1f}s → requeue"
                )

                con.execute("""
                    UPDATE processing_queue
                    SET
                        status = 'PENDING',
                        next_attempt_ms = ?,
                        attempts = ?,
                        updated_at_ms = ?
                    WHERE id = ?
                """, (
                    now,
                    attempts + 1,
                    now,
                    job_id
                ))

                recovered += 1

        if recovered > 0:
            logger.info(f"♻️ Watchdog recovered {recovered} stuck jobs")

logger = logging.getLogger("SUPERVISOR_WATCHDOG")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s - %(message)s",
)

_STOP = False


def _handle_stop(signum, frame):
    global _STOP
    _STOP = True
    logger.info(f"Stop requested (signal={signum}). Watchdog shutting down...")


def start_watchdog(storage: Any):
    """
    Watchdog loop:
      - checks leader lock
      - verifies leader heartbeat freshness
      - clears stale leader lock (operational metadata)
    """
    global _STOP

    signal.signal(signal.SIGINT, _handle_stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _handle_stop)

    ledger = storage.ledger
    supervisor = SystemSupervisor(storage)

    interval = int(os.getenv("WATCHDOG_INTERVAL_SECONDS", "30"))
    stale_after = int(os.getenv("SUPERVISOR_STALE_AFTER_SECONDS", "120"))
    lock_name = os.getenv("SUPERVISOR_LOCK_NAME", "scan_supervisor")

    logger.info("Watchdog starting.")
    logger.info(f"Config: interval={interval}s stale_after={stale_after}s lock_name={lock_name}")

    # small jitter start
    time.sleep(random.uniform(0.0, 1.5))

    while not _STOP:
        try:
            # ---------------------------------
            # Get lock + run escalation
            # ---------------------------------
            lock = ledger.get_supervisor_lock(lock_name=lock_name)

            supervisor.run_auto_escalation()

            # 🔥 NEW: job-level watchdog (ALWAYS RUN)
            recover_stuck_processing_jobs(ledger)

            # ---------------------------------
            # If no leader, skip leader checks
            # ---------------------------------
            if not lock:
                logger.info("No leader lock present.")
                time.sleep(interval)
                continue

            leader_id = lock.get("leader_id")
            if not leader_id:
                logger.warning("Leader lock has no leader_id.")
                time.sleep(interval)
                continue

            # ---------------------------------
            # Leader heartbeat check
            # ---------------------------------
            hb_ms = ledger.get_last_seen_ms(leader_id)

            if hb_ms is None:
                logger.warning(f"Leader {leader_id} has NO heartbeat row yet.")
                time.sleep(interval)
                continue

            now_ms = int(time.time() * 1000)
            age_ms = now_ms - int(hb_ms)
            age_s = age_ms / 1000.0

            if age_s > stale_after:
                logger.warning(
                    f"Leader {leader_id} stale (age={age_s:.1f}s). Clearing lock."
                )

                cleared = ledger.clear_supervisor_lock(lock_name=lock_name)

                ledger.record_metric(
                    "supervisor.leader.stale",
                    1.0,
                    tags={"leader_id": str(leader_id)},
                )

                if cleared:
                    logger.warning("Leader lock cleared.")
                else:
                    logger.warning("Leader lock clear attempted but no row deleted.")

            else:
                logger.info(
                    f"Leader {leader_id} healthy (heartbeat age={age_s:.1f}s)."
                )

                ledger.record_metric(
                    "supervisor.leader.healthy",
                    1.0,
                    tags={"leader_id": str(leader_id)},
                )

            # ---------------------------------
            # Sleep before next cycle
            # ---------------------------------
            time.sleep(interval)

        except Exception:
            logger.exception("Watchdog error; continuing.")
            time.sleep(max(2, interval))

    logger.info("Watchdog stopped cleanly.")
