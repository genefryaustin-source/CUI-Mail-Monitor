import time

class SystemSupervisor:

    def __init__(self, storage):
        self.storage = storage
        self.ledger = storage.ledger

    # ---------------------------------------
    # 📊 SYSTEM STATUS
    # ---------------------------------------
    def get_status(self):
        now = int(time.time() * 1000)

        with self.ledger._connect() as con:
            return {
                "open_alerts": con.execute(
                    "SELECT COUNT(*) FROM alerts WHERE status='OPEN'"
                ).fetchone()[0],

                "critical_alerts": con.execute(
                    "SELECT COUNT(*) FROM alerts WHERE severity='CRITICAL'"
                ).fetchone()[0],

                "recent_evidence": con.execute(
                    "SELECT COUNT(*) FROM evidence_records WHERE created_at_ms > ?",
                    (now - 86400000,)
                ).fetchone()[0],

                "custody_failures": con.execute(
                    "SELECT COUNT(*) FROM custody_events WHERE event_type='INTEGRITY_FAILED'"
                ).fetchone()[0],
            }

    # ---------------------------------------
    # ❤️ HEARTBEATS
    # ---------------------------------------
    def get_heartbeats(self, limit=20):
        now = int(time.time() * 1000)

        with self.ledger._connect() as con:
            try:
                rows = con.execute("""
                    SELECT *
                    FROM heartbeats
                    ORDER BY ts_ms DESC
                    LIMIT ?
                """, (limit,)).fetchall()

                hb = [dict(r) for r in rows]

                for h in hb:
                    age = (now - h["ts_ms"]) / 1000
                    h["status_live"] = "🟢 ONLINE" if age < 60 else "🔴 OFFLINE"
                    h["last_seen_sec"] = int(age)

                return hb

            except Exception:
                return []

    # ---------------------------------------
    # 📦 QUEUE
    # ---------------------------------------
    def get_queue(self, limit=100):
        now = int(time.time() * 1000)

        with self.ledger._connect() as con:
            try:
                rows = con.execute("""
                    SELECT *
                    FROM processing_queue
                    ORDER BY created_at_ms DESC
                    LIMIT ?
                """, (limit,)).fetchall()

                queue = [dict(r) for r in rows]

                for q in queue:
                    age = (now - q["created_at_ms"]) / 1000
                    q["age_sec"] = int(age)
                    q["status_flag"] = "⚠️ STUCK" if age > 300 else "OK"

                return queue

            except Exception:
                return []

    # ---------------------------------------
    # 📈 METRICS
    # ---------------------------------------
    def get_metrics(self, limit=100):
        with self.ledger._connect() as con:
            try:
                rows = con.execute("""
                    SELECT *
                    FROM metrics
                    ORDER BY ts_ms DESC
                    LIMIT ?
                """, (limit,)).fetchall()

                return [dict(r) for r in rows]

            except Exception:
                return []

    # ---------------------------------------
    # 🔍 ALERT DEDUP CHECK
    # ---------------------------------------
    def _alert_exists(self, con, message):
        row = con.execute("""
            SELECT 1
            FROM alerts
            WHERE message = ?
            LIMIT 1
        """, (message,)).fetchone()

        return row is not None

    # ---------------------------------------
    # 🚨 CREATE ALERT
    # ---------------------------------------
    def _create_alert(self, con, evidence_id, severity, message):
        import time

        con.execute("""
            INSERT INTO alerts (
                evidence_id,
                severity,
                message,
                status,
                created_at_ms
            )
            VALUES (?, ?, ?, 'OPEN', ?)
        """, (
            evidence_id,
            severity,
            message,
            int(time.time() * 1000)
        ))

    # ---------------------------------------
    # 🚨 AUTO ESCALATION ENGINE
    # ---------------------------------------
    def run_auto_escalation(self):
        import time

        now = int(time.time() * 1000)

        with self.ledger._connect() as con:

            # Stuck queue jobs
            try:
                jobs = con.execute("""
                    SELECT id, evidence_id, created_at_ms
                    FROM processing_queue
                    WHERE status IN ('PENDING', 'PROCESSING')
                """).fetchall()

                for job in jobs:
                    age_sec = (now - job["created_at_ms"]) / 1000

                    if age_sec > 300:
                        message = f"Stuck job > {int(age_sec)}s (evidence {job['evidence_id']})"

                        if not self._alert_exists(con, message):
                            self._create_alert(con, job["evidence_id"], "HIGH", message)

            except Exception:
                pass

            # Offline workers
            try:
                heartbeats = con.execute("""
                    SELECT worker_id, ts_ms
                    FROM heartbeats
                """).fetchall()

                for hb in heartbeats:
                    age_sec = (now - hb["ts_ms"]) / 1000

                    if age_sec > 60:
                        message = f"Worker {hb['worker_id']} offline ({int(age_sec)}s)"

                        if not self._alert_exists(con, message):
                            self._create_alert(con, None, "CRITICAL", message)

            except Exception:
                pass

            # Queue overload
            try:
                queue_size = con.execute("""
                    SELECT COUNT(*)
                    FROM processing_queue
                    WHERE status IN ('PENDING', 'PROCESSING')
                """).fetchone()[0]

                if queue_size > 100:
                    message = f"Queue overload: {queue_size} active jobs"

                    if not self._alert_exists(con, message):
                        self._create_alert(con, None, "CRITICAL", message)

            except Exception:
                pass

            con.commit()