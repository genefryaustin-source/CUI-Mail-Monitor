# core/supervisor/scan_supervisor.py
from __future__ import annotations
import sqlite3
import logging
import os
import random
import signal
import time
import uuid
from typing import Any, Dict, Optional


from core.storage.factory import build_storage

from core.pipeline.scan_pipeline import run_scan_pipeline


MAX_RETRIES = 3
RETRY_DELAY_MS = 60_000  # 1 minute


def retry_or_fail_job(ledger, job, error_msg):
    job_id = int(job["id"])
    attempts = job.get("attempts", 0) or 0

    now = int(time.time() * 1000)

    if attempts < MAX_RETRIES:
        next_attempt = now + RETRY_DELAY_MS

        logger.warning(
            f"🔁 RETRY job={job_id} attempt={attempts+1}/{MAX_RETRIES}"
        )

        ledger.db.execute("""
            UPDATE scan_queue
            SET
                status = 'queued',
                attempts = ?,
                next_attempt_ms = ?,
                last_error = ?,
                updated_at_ms = ?
            WHERE id = ?
        """, (
            attempts + 1,
            next_attempt,
            error_msg[:1000],
            now,
            job_id
        ))

    else:
        logger.error(f"💀 PERMANENT FAIL job={job_id}")

        ledger.db.execute("""
            UPDATE scan_queue
            SET
                status = 'failed',
                last_error = ?,
                updated_at_ms = ?
            WHERE id = ?
        """, (
            error_msg[:1000],
            now,
            job_id
        ))

    ledger.db.commit()

logger = logging.getLogger("SUPERVISOR")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s - %(message)s",
)

_STOP = False


def _handle_stop(signum, frame):
    global _STOP
    _STOP = True
    logger.info(f"Stop requested (signal={signum}). Shutting down gracefully...")


def start_supervisor(storage: Any, *, default_job: Optional[Dict[str, Any]] = None):
    """
    Multi-supervisor scaling model:

    - Leader election (TTL lock) is used for coordination ONLY.
      The leader can auto-enqueue default jobs if enabled.
    - Any supervisor process can act as a worker:
      claim_next_scan(worker_id) and execute jobs.

    Graceful shutdown:
      - SIGINT/SIGTERM stop loop cleanly.
      - TTL lock naturally expires; no forensic data is mutated.
    """
    global _STOP

    signal.signal(signal.SIGINT, _handle_stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _handle_stop)

    ledger = storage.ledger
    worker_id = f"supervisor-{uuid.uuid4().hex[:8]}"
    pid = os.getpid()

    logger.info(f"SUPERVISOR DB: {getattr(ledger, 'db_path', '(unknown)')}")
    logger.info("Starting supervisor process (leader election enabled, multi-worker).")
    logger.info(f"Worker id: {worker_id} pid={pid}")

    default_job = default_job or {}

    # small jitter to avoid thundering herd at startup
    time.sleep(random.uniform(0.0, 1.5))

    while not _STOP:
        try:
            cfg = ledger.get_supervisor_config()
            enabled = bool(int(cfg.get("enabled", 1)))
            interval = int(cfg.get("interval_seconds", 60))
            ttl = int(cfg.get("leader_ttl_seconds", 120))
            auto_enqueue = bool(int(cfg.get("auto_enqueue_enabled", 1)))

            # ----------------------------
            # LEADER ELECTION (coordination)
            # ----------------------------
            is_leader = ledger.try_acquire_supervisor_lock(worker_id, ttl_seconds=ttl)

            # Heartbeat always recorded (worker heartbeat)
            hb_status = "leader" if is_leader else "worker"
            print("🔥 WRITING HEARTBEAT:", worker_id)
            ledger.upsert_heartbeat(
                worker_id=worker_id,
                leader_id=(worker_id if is_leader else None),
                status=hb_status,
                details={"pid": pid, "note": "scan supervisor", "is_leader": is_leader},
            )

            if not enabled:
                logger.info("Supervisor disabled via config. Sleeping...")
                time.sleep(max(5, interval))
                continue

            # ----------------------------
            # LEADER: auto-enqueue jobs
            # ----------------------------
            if is_leader:
                try:
                    pending = ledger.count_pending_scans()

                    if pending == 0:
                        mailbox_to_scan = (
                                default_job.get("mailbox")
                                or os.getenv("MONITORED_MAILBOX")
                                or "test@example.com"
                        )

                        logger.info(f"📥 Auto-enqueue scan job for mailbox={mailbox_to_scan}")

                        ledger.enqueue_scan(
                            provider=str(default_job.get("provider") or "gmail"),
                            mailbox=str(mailbox_to_scan),
                            lookback_hours=int(default_job.get("lookback_hours", 1)),
                            attachments_only=bool(default_job.get("attachments_only", True)),
                            max_messages=int(default_job.get("max_messages", 50)),
                            payload=default_job.get("payload") or {
                                "source": "auto_enqueue",
                                "leader_id": worker_id,
                            },
                        )

                except Exception:
                    logger.exception("Auto-enqueue failed")

            # ----------------------------
            # WORKER: claim + run jobs  ✅ MOVED OUTSIDE LEADER BLOCK
            # ----------------------------
            logger.info("Scanning queue...")

            job = ledger.claim_next_scan(worker_id=worker_id)

            if not job:
                logger.info("Queue empty.")
                logger.info(f"Sleeping {interval}s")
                time.sleep(max(2, interval))
                continue

            job_id = int(job["id"])
            mailbox = str(job.get("mailbox", ""))

            logger.info(
                f"Claimed job {job_id} mailbox={mailbox} "
                f"lookback={job.get('lookback_hours')}h"
            )

            ledger.upsert_heartbeat(
                worker_id=worker_id,
                leader_id=(worker_id if is_leader else None),
                status="running",
                details={"pid": pid, "job_id": job_id, "mailbox": mailbox},
            )

            run_id = str(uuid.uuid4())

            try:
                logger.info(f"🚀 START PIPELINE job={job_id}")

                attachments_only_raw = job.get("attachments_only")
                if isinstance(attachments_only_raw, str):
                    attachments_only = attachments_only_raw.strip().lower() in (
                        "1", "true", "yes", "y"
                    )
                else:
                    attachments_only = bool(attachments_only_raw)

                config = {
                    "provider": str(job.get("provider") or "gmail"),
                    "mailbox": mailbox,
                    "monitored_mailbox": mailbox,
                    "lookback_hours": int(job.get("lookback_hours") or 168),
                    "attachments_only": attachments_only,
                    "max_messages": int(job.get("max_messages") or 100),
                    "run_id": run_id,
                    "job_id": job_id,
                    "worker_id": worker_id,
                }

                findings = run_scan_pipeline(config) or []

                logger.info(
                    f"✅ PIPELINE FINISHED job={job_id} "
                    f"findings={len(findings)} run_id={run_id}"
                )

                ledger.mark_scan_done(job_id=job_id, run_id=run_id)

                ledger.record_metric(
                    "scan.job.success",
                    1.0,
                    tags={
                        "worker_id": worker_id,
                        "job_id": job_id,
                        "run_id": run_id,
                        "findings": len(findings),
                    },
                )

                ledger.upsert_heartbeat(
                    worker_id=worker_id,
                    leader_id=(worker_id if is_leader else None),
                    status="idle",
                    details={
                        "pid": pid,
                        "last_job": job_id,
                        "last_run_id": run_id,
                        "findings": len(findings),
                    },
                )

            except Exception as e:
                logger.exception(f"❌ PIPELINE ERROR job={job_id}")

                ledger.create_alert(
                    severity="HIGH",
                    message=f"Scan job {job_id} failed",
                    job_id=job_id,
                    run_id=run_id,
                    metadata={
                        "mailbox": job.get("mailbox"),
                        "provider": job.get("provider"),
                        "error": str(e)[:500],
                    },
                )

                retry_or_fail_job(ledger, job, str(e))

                ledger.record_metric(
                    "scan.job.fail",
                    1.0,
                    tags={
                        "worker_id": worker_id,
                        "job_id": job_id,
                        "run_id": run_id,
                        "error": str(e)[:300],
                    },
                )

                ledger.upsert_heartbeat(
                    worker_id=worker_id,
                    leader_id=(worker_id if is_leader else None),
                    status="error",
                    details={
                        "pid": pid,
                        "job_id": job_id,
                        "run_id": run_id,
                        "error": str(e)[:500],
                    },
                )

            logger.info(f"Sleeping {interval}s")
            time.sleep(max(2, interval))

        except Exception:
            logger.exception("Supervisor loop error")
            time.sleep(max(2, interval))

        except sqlite3.OperationalError as oe:  # type: ignore[name-defined]
            # In case you hit "database is locked", backoff with jitter
            msg = str(oe).lower()
            if "locked" in msg:
                backoff = random.uniform(0.25, 2.5)
                logger.warning(f"DB locked. Backing off {backoff:.2f}s")
                time.sleep(backoff)
                continue
            logger.exception("SQLite operational error")
            time.sleep(2)

        except Exception:
            logger.exception("Supervisor crashed; restarting after short backoff.")
            time.sleep(random.uniform(1.0, 3.0))

    # final heartbeat on exit
    try:
        ledger.upsert_heartbeat(
            worker_id=worker_id,
            leader_id=None,
            status="stopped",
            details={"pid": pid, "note": "graceful shutdown"},
        )
    except Exception:
        pass

    logger.info("Supervisor stopped cleanly.")
    print("DEBUG NAME:", __name__)
if __name__ == "__main__":


    storage = build_storage()

    print("🚀 Starting Scan Supervisor...")
    print("DB:", storage.ledger.db_path)

    start_supervisor(storage)

