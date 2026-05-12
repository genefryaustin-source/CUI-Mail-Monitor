
import time
import json

from core.ingest.ingest import run_ingest
print("🔥 NEW CODE LOADED - run_scan_job")
QUEUE_TABLE = "processing_queue"


def _now_ms():
    return int(time.time() * 1000)


def _get_job_status(ledger, job_id):
    with ledger._connect() as con:
        row = con.execute(
            f"SELECT status FROM {QUEUE_TABLE} WHERE id=?",
            (job_id,)
        ).fetchone()
    return row[0] if row else None


def run_scan_job(storage, job_id):
    ledger = storage.ledger
    start_ts = _now_ms()

    try:
        # ----------------------------------
        # 🚀 MARK RUNNING
        # ----------------------------------
        with ledger._connect() as con:
            con.execute(f"""
                UPDATE {QUEUE_TABLE}
                SET status='RUNNING',
                    started_at_ms=?,
                    progress_current=0,
                    progress_total=1
                WHERE id=?
            """, (start_ts, job_id))

            row = con.execute(f"""
                SELECT * FROM {QUEUE_TABLE}
                WHERE id = ?
            """, (job_id,)).fetchone()

            con.commit()

        if not row:
            raise ValueError(f"Scan job not found: {job_id}")

        row = dict(row)

        provider = row.get("provider")
        mailbox = row.get("mailbox")
        lookback_hours = int(row.get("lookback_hours") or 168)
        attachments_only = bool(row.get("attachments_only"))
        max_messages = int(row.get("max_messages") or 100)
        payload = json.loads(row.get("payload_json") or "{}")

        # ----------------------------------
        # ⛔ PRE-CHECK CANCEL
        # ----------------------------------
        if _get_job_status(ledger, job_id) == "CANCELLED":
            print(f"⛔ Job {job_id} was cancelled before execution")
            return {"status": "CANCELLED"}

        if hasattr(ledger, "update_scan_progress"):
            ledger.update_scan_progress(job_id, current=0, total=1)

        # ----------------------------------
        # 🚀 RUN INGEST PIPELINE
        # ----------------------------------
        result = run_ingest(
            storage=storage,
            provider=provider,
            mailbox=mailbox,
            lookback_hours=lookback_hours,
            attachments_only=attachments_only,
            max_messages=max_messages,
            payload=payload,
            job_id=job_id,
        ) or {}

        # ----------------------------------
        # ⛔ POST-CHECK CANCEL
        # ----------------------------------
        if _get_job_status(ledger, job_id) == "CANCELLED":
            print(f"⛔ Job {job_id} cancelled during execution")
            return {"status": "CANCELLED"}

        end_ts = _now_ms()

        processed = result.get("messages_processed", 0)
        failed = result.get("messages_failed", 0)
        evidence = result.get("evidence_created", 0)

        print(f"📊 Job {job_id} summary → processed={processed}, failed={failed}, evidence={evidence}")

        if processed == 0:
            status = "EMPTY"
        elif failed > 0 and evidence == 0:
            status = "FAILED"
        else:
            status = "COMPLETED"

        # ----------------------------------
        # ✅ UPDATE FINAL STATUS
        # ----------------------------------
        with ledger._connect() as con:
            con.execute(f"""
                UPDATE {QUEUE_TABLE}
                SET status=?,
                    completed_at_ms=?,
                    duration_ms=?,
                    last_error=?
                WHERE id=?
            """, (
                status,
                end_ts,
                end_ts - start_ts,
                None if status != "FAILED" else "Processing errors occurred",
                job_id,
            ))
            con.commit()

        return {
            "status": status,
            **result,
        }

    except Exception as e:
        end_ts = _now_ms()
        error_msg = f"{type(e).__name__}: {e}"
        print(f"🔥 Scan job failed: {error_msg}")

        with ledger._connect() as con:
            con.execute(f"""
                UPDATE {QUEUE_TABLE}
                SET status='FAILED',
                    last_error=?,
                    completed_at_ms=?,
                    duration_ms=?
                WHERE id=?
            """, (error_msg, end_ts, end_ts - start_ts, job_id))
            con.commit()

        return {
            "status": "FAILED",
            "error": error_msg,
        }

