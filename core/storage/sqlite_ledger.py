# core/storage/sqlite_ledger.py
from __future__ import annotations

import json
import os
import random
import shutil
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .interfaces import (
    CustodyEvent,
    EvidenceRecord,
    Ledger,
    Manifest,
    stable_json_dumps,
)

from core.storage.local_vault import LocalVault
from core.storage.app_storage import AppStorage
from core.alerts.slack_listener import run_slack_listener




DEFAULT_DB_PATH = os.path.join("data", "ledger.db")


def _now_ms() -> int:
    return int(time.time() * 1000)


def _truthy(v: Optional[str]) -> bool:
    if not v:
        return False
    return v.strip().lower() in {"1", "true", "yes", "y", "on"}


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 5
    base_delay_seconds: int = 30
    max_delay_seconds: int = 6 * 3600
    jitter_seconds: int = 10


class SQLiteLedger(Ledger):
    """
    Production SQLite Evidence Ledger.

    Immutable mode via ENV:
        IMMUTABLE_LEDGER=1

    Forensic tables (immutable when enabled):
      - runs
      - evidence_records
      - custody_events
      - manifests
      - forensic_anchors   (append-only notarization / anchoring)

    Operational tables (mutable by design):
      - supervisor_config, supervisor_lock, supervisor_heartbeat
      - retry_policy, scan_queue
      - metrics
    """

    def __init__(self, db_path: str = DEFAULT_DB_PATH, immutable: Optional[bool] = None):
        if immutable is None:
            immutable = _truthy(os.getenv("IMMUTABLE_LEDGER"))
        self.db_path = db_path
        self.immutable = bool(immutable)

        os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
        self.init_schema()
        self._ensure_scan_queue_columns()
    # --------------------------------------------------
    # Connection helper
    # --------------------------------------------------



    @contextmanager
    def _connect(self):
        con = sqlite3.connect(
            self.db_path,
            timeout=30,
            check_same_thread=False
        )

        con.row_factory = sqlite3.Row

        try:
            # lightweight pragmas
            con.execute("PRAGMA foreign_keys = ON;")
            con.execute("PRAGMA busy_timeout = 30000;")

            yield con  # 🔥 THIS FIXES YOUR ERROR

        finally:
            con.close()

    _pragmas_initialized = False

    def _set_pragmas_once(self, con):
        if getattr(self, "_pragmas_initialized", False):
            return

        con.execute("PRAGMA journal_mode=WAL;")
        con.execute("PRAGMA synchronous=NORMAL;")

        self._pragmas_initialized = True

    # --------------------------------------------------
    # Schema
    # --------------------------------------------------

    def init_schema(self) -> None:
        with self._connect() as con:
            self._set_pragmas_once(con)

            # ============================
            # FORENSIC TABLES
            # ============================
            con.executescript(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    provider TEXT NOT NULL,
                    mailbox TEXT NOT NULL,
                    started_at_ms INTEGER NOT NULL,
                    completed_at_ms INTEGER,
                    messages_scanned INTEGER DEFAULT 0,
                    attachments_scanned INTEGER DEFAULT 0,
                    cui_flagged INTEGER DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS evidence_records (
                    evidence_id TEXT PRIMARY KEY,
                    sha256 TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    content_type TEXT NOT NULL,
                    storage_uri TEXT NOT NULL,
                    suggested_name TEXT NOT NULL,
                    created_at_ms INTEGER NOT NULL,
                    metadata_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS custody_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL REFERENCES runs(run_id),
                    evidence_id TEXT NOT NULL REFERENCES evidence_records(evidence_id),
                    event_type TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    timestamp_ms INTEGER NOT NULL,
                    details_json TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_custody_run
                    ON custody_events(run_id);

                CREATE INDEX IF NOT EXISTS idx_custody_evidence
                    ON custody_events(evidence_id);

                CREATE TABLE IF NOT EXISTS manifests (
                    run_id TEXT PRIMARY KEY REFERENCES runs(run_id),
                    manifest_json TEXT NOT NULL,
                    manifest_sha256 TEXT NOT NULL,
                    created_at_ms INTEGER NOT NULL
                );

                -- Canonical append-only anchoring table
                CREATE TABLE IF NOT EXISTS forensic_anchors (
                    anchor_id TEXT PRIMARY KEY,
                    anchor_type TEXT NOT NULL,      -- SNAPSHOT | EVIDENCE | RUN
                    target_id TEXT NOT NULL,        -- snapshot path / evidence_id / run_id
                    hash_sha256 TEXT NOT NULL,
                    metadata_json TEXT,
                    created_at_ms INTEGER NOT NULL
                );
                
                CREATE TABLE IF NOT EXISTS alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    evidence_id TEXT,
                    severity TEXT,
                    message TEXT,
                    created_at_ms INTEGER,
                    resolved INTEGER DEFAULT 0
                );
                
                CREATE TABLE IF NOT EXISTS alert_settings (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    slack_enabled INTEGER DEFAULT 0,
                    slack_webhook_url TEXT,
                    email_enabled INTEGER DEFAULT 0,
                    email_to TEXT,
                    min_severity TEXT DEFAULT 'CRITICAL',
                    updated_at_ms INTEGER
                );
                
                CREATE TABLE IF NOT EXISTS cases (
                    case_id TEXT PRIMARY KEY,
                    title TEXT,
                    description TEXT,
                    status TEXT,
                    created_at_ms INTEGER
                );

                CREATE TABLE IF NOT EXISTS case_evidence (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    case_id TEXT,
                    evidence_id TEXT
                );

                CREATE TABLE IF NOT EXISTS case_notes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    case_id TEXT,
                    note TEXT,
                    created_at_ms INTEGER
                );

                INSERT OR IGNORE INTO alert_settings (id) VALUES (1);

                CREATE INDEX IF NOT EXISTS idx_alerts_time
                ON alerts(created_at_ms);

                CREATE INDEX IF NOT EXISTS idx_forensic_anchors_target
                    ON forensic_anchors(target_id);

                CREATE INDEX IF NOT EXISTS idx_forensic_anchors_type_time
                    ON forensic_anchors(anchor_type, created_at_ms);
                """
            )

            # ============================
            # OPERATIONAL TABLES
            # ============================
            con.executescript(
                """
                CREATE TABLE IF NOT EXISTS supervisor_config (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    enabled INTEGER NOT NULL DEFAULT 1,
                    interval_seconds INTEGER NOT NULL DEFAULT 60,
                    updated_at_ms INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS supervisor_lock (
                    lock_name TEXT PRIMARY KEY,
                    leader_id TEXT NOT NULL,
                    acquired_at_ms INTEGER NOT NULL,
                    expires_at_ms INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS supervisor_heartbeat (
                    worker_id TEXT PRIMARY KEY,
                    leader_id TEXT,
                    status TEXT NOT NULL DEFAULT 'idle',
                    last_seen_ms INTEGER NOT NULL,
                    details_json TEXT,
                    timestamp_ms INTEGER
                );

                CREATE INDEX IF NOT EXISTS idx_supervisor_heartbeat_ts
                    ON supervisor_heartbeat(last_seen_ms);

                CREATE TABLE IF NOT EXISTS retry_policy (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    max_attempts INTEGER NOT NULL DEFAULT 5,
                    base_delay_seconds INTEGER NOT NULL DEFAULT 30,
                    max_delay_seconds INTEGER NOT NULL DEFAULT 21600,
                    jitter_seconds INTEGER NOT NULL DEFAULT 10,
                    updated_at_ms INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS scan_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    provider TEXT NOT NULL,
                    mailbox TEXT NOT NULL,
                    lookback_hours INTEGER NOT NULL,
                    attachments_only INTEGER NOT NULL,
                    max_messages INTEGER NOT NULL,
                    payload_json TEXT,
                    status TEXT NOT NULL DEFAULT 'queued',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    next_attempt_ms INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT,
                    created_at_ms INTEGER NOT NULL,
                    updated_at_ms INTEGER NOT NULL,
                    run_id TEXT
                );
                
                CREATE TABLE IF NOT EXISTS emails (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    message_id TEXT UNIQUE,
                    thread_id TEXT,
                    mailbox TEXT,
                    subject TEXT,
                    sender TEXT,
                    received_at TEXT,
                    snippet TEXT,
                    body_text TEXT,
                    body_html TEXT,
                    raw_headers TEXT,
                    has_attachments INTEGER,
                    created_at TEXT
                );
                
                CREATE TABLE IF NOT EXISTS attachments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    message_id TEXT,
                    filename TEXT,
                    mime_type TEXT,
                    size_bytes INTEGER,
                    storage_path TEXT,
                    extracted_text TEXT,
                    created_at TEXT
                );
                
                
                CREATE TABLE IF NOT EXISTS case_audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    case_id INTEGER,
                    action TEXT,
                    performed_by TEXT,
                    details TEXT,
                    created_at_ms INTEGER
                );
                    

                CREATE INDEX IF NOT EXISTS idx_scan_queue_status_next
                    ON scan_queue(status, next_attempt_ms);

                CREATE TABLE IF NOT EXISTS metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    value REAL NOT NULL,
                    ts_ms INTEGER NOT NULL,
                    tags_json TEXT
                );
                CREATE TABLE IF NOT EXISTS evidence_events (
                    event_id TEXT PRIMARY KEY,
                    event_type TEXT,
                    data_json TEXT,
                    created_at_ms INTEGER
                );
    

                CREATE INDEX IF NOT EXISTS idx_metrics_name_ts
                    ON metrics(name, ts_ms);
                """
            )

            # Seed single-row tables
            if con.execute("SELECT id FROM supervisor_config WHERE id=1").fetchone() is None:
                con.execute(
                    "INSERT INTO supervisor_config VALUES (1, 1, 60, ?)",
                    (_now_ms(),),
                )

            if con.execute("SELECT id FROM retry_policy WHERE id=1").fetchone() is None:
                con.execute(
                    "INSERT INTO retry_policy VALUES (1, 5, 30, 21600, 10, ?)",
                    (_now_ms(),),
                )

            # Immutable triggers
            if self.immutable:
                con.executescript(
                    """
                    CREATE TRIGGER IF NOT EXISTS trg_no_update_forensic_anchors
                    BEFORE UPDATE ON forensic_anchors
                    BEGIN
                        SELECT RAISE(ABORT, 'IMMUTABLE_LEDGER: forensic_anchors are append-only');
                    END;

                    CREATE TRIGGER IF NOT EXISTS trg_no_delete_forensic_anchors
                    BEFORE DELETE ON forensic_anchors
                    BEGIN
                        SELECT RAISE(ABORT, 'IMMUTABLE_LEDGER: forensic_anchors are append-only');
                    END;
                    """
                )

    # --------------------------------------------------
    # Forensic Anchoring (canonical API)
    # --------------------------------------------------


    def _execute_with_retry(self, con, query, params=()):
        for attempt in range(5):
            try:
                return con.execute(query, params)
            except Exception as e:
                if "locked" in str(e):
                    print(f"🔒 DB LOCK — retry {attempt + 1}")
                    time.sleep(0.2 * (attempt + 1))
                    continue
                raise
    def record_forensic_anchor(
        self,
        *,
        anchor_id: str,
        anchor_type: str,
        target_id: str,
        hash_sha256: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        with self._connect() as con:
            con.execute(
                """
                INSERT INTO forensic_anchors(
                    anchor_id, anchor_type, target_id, hash_sha256,
                    metadata_json, created_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    anchor_id,
                    anchor_type,
                    target_id,
                    hash_sha256,
                    stable_json_dumps(metadata or {}),
                    _now_ms(),
                ),
            )

    def list_forensic_anchors(self, limit: int = 100) -> List[Dict[str, Any]]:
        with self._connect() as con:
            rows = con.execute(
                """
                SELECT *
                FROM forensic_anchors
                ORDER BY created_at_ms DESC
                LIMIT ?
                """,
                (int(limit),),
            ).fetchall()

            out: List[Dict[str, Any]] = []
            for r in rows:
                d = dict(r)
                if d.get("metadata_json"):
                    try:
                        d["metadata"] = json.loads(d["metadata_json"])
                    except Exception:
                        d["metadata"] = d["metadata_json"]
                out.append(d)
            return out

    def get_evidence_record(self, evidence_id: str):
        with self._connect() as con:
            row = con.execute(
                "SELECT * FROM evidence_records WHERE evidence_id=?",
                (evidence_id,)
            ).fetchone()

            return dict(row) if row else None

    def list_events_for_evidence(self, evidence_id: str):
        with self._connect() as con:
            rows = con.execute(
                """
                SELECT *
                FROM custody_events
                WHERE evidence_id = ?
                ORDER BY timestamp_ms ASC
                """,
                (evidence_id,),
            ).fetchall()

            return [dict(r) for r in rows]

    def lookup_evidence_by_sha256(self, sha256: str):
        with self._connect() as con:
            row = con.execute(
                "SELECT * FROM evidence_records WHERE sha256 = ?",
                (sha256,)
            ).fetchone()
            return dict(row) if row else None

    def record_evidence(
            self,
            *,
            evidence_id: str,
            sha256: str,
            size_bytes: int,
            content_type: str,
            storage_uri: str,
            suggested_name: str,
            created_at_ms: Optional[int] = None,
            metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        with self._connect() as con:
            con.execute(
                """
                INSERT INTO evidence_records (
                    evidence_id,
                    sha256,
                    size_bytes,
                    content_type,
                    storage_uri,
                    suggested_name,
                    created_at_ms,
                    metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    evidence_id,
                    sha256,
                    int(size_bytes),
                    content_type,
                    storage_uri,
                    suggested_name,
                    int(created_at_ms or _now_ms()),
                    stable_json_dumps(metadata or {}),
                ),
            )

    def list_evidence_records(self, limit: int = 100):
        with self._connect() as con:
            rows = con.execute(
                """
                SELECT *
                FROM evidence_records
                ORDER BY created_at_ms DESC
                LIMIT ?
                """,
                (int(limit),),
            ).fetchall()

            out = []
            for row in rows:
                d = dict(row)
                if d.get("metadata_json"):
                    try:
                        d["metadata"] = json.loads(d["metadata_json"])
                    except Exception:
                        d["metadata"] = d["metadata_json"]
                out.append(d)
            return out

    def record_custody_event(
            self,
            *,
            run_id: str,
            evidence_id: str,
            event_type: str,
            actor: str,
            details: Optional[Dict[str, Any]] = None,
    ):
        with self._connect() as con:
            con.execute(
                """
                INSERT INTO custody_events (
                    run_id,
                    evidence_id,
                    event_type,
                    actor,
                    timestamp_ms,
                    details_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    evidence_id,
                    event_type,
                    actor,
                    _now_ms(),
                    stable_json_dumps(details or {}),
                ),
            )

    def ensure_run(
            self,
            *,
            run_id: str,
            provider: str = "demo",
            mailbox: str = "demo@local",
    ):
        with self._connect() as con:
            existing = con.execute(
                "SELECT run_id FROM runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()

            if existing is None:
                con.execute(
                    """
                    INSERT INTO runs (
                        run_id,
                        provider,
                        mailbox,
                        started_at_ms,
                        completed_at_ms,
                        messages_scanned,
                        attachments_scanned,
                        cui_flagged
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        provider,
                        mailbox,
                        _now_ms(),
                        _now_ms(),
                        0,
                        0,
                        0,
                    ),
                )

    def get_forensic_dashboard_summary(self) -> Dict[str, Any]:
        with self._connect() as con:
            total_evidence = con.execute(
                "SELECT COUNT(*) AS c FROM evidence_records"
            ).fetchone()["c"]

            verified_events = con.execute(
                "SELECT COUNT(*) AS c FROM custody_events WHERE event_type = 'VERIFIED'"
            ).fetchone()["c"]

            integrity_failures = con.execute(
                "SELECT COUNT(*) AS c FROM custody_events WHERE event_type = 'INTEGRITY_FAILED'"
            ).fetchone()["c"]

            ingested_events = con.execute(
                "SELECT COUNT(*) AS c FROM custody_events WHERE event_type = 'INGESTED'"
            ).fetchone()["c"]

            restored_events = con.execute(
                "SELECT COUNT(*) AS c FROM custody_events WHERE event_type = 'RESTORED'"
            ).fetchone()["c"]

            total_anchors = con.execute(
                "SELECT COUNT(*) AS c FROM forensic_anchors"
            ).fetchone()["c"]

            return {
                "total_evidence": int(total_evidence or 0),
                "verified_events": int(verified_events or 0),
                "integrity_failures": int(integrity_failures or 0),
                "ingested_events": int(ingested_events or 0),
                "restored_events": int(restored_events or 0),
                "total_anchors": int(total_anchors or 0),
            }

    def list_recent_custody_events(self, limit: int = 25):
        with self._connect() as con:
            rows = con.execute(
                """
                SELECT
                    id,
                    run_id,
                    evidence_id,
                    event_type,
                    actor,
                    timestamp_ms,
                    details_json
                FROM custody_events
                ORDER BY timestamp_ms DESC, id DESC
                LIMIT ?
                """,
                (int(limit),),
            ).fetchall()

            out = []
            for row in rows:
                d = dict(row)
                if d.get("details_json"):
                    try:
                        d["details"] = json.loads(d["details_json"])
                    except Exception:
                        d["details"] = d["details_json"]
                out.append(d)
            return out

    def list_recent_anchors(self, limit: int = 25):
        with self._connect() as con:
            rows = con.execute(
                """
                SELECT
                    anchor_id,
                    anchor_type,
                    target_id,
                    hash_sha256,
                    metadata_json,
                    created_at_ms
                FROM forensic_anchors
                ORDER BY created_at_ms DESC
                LIMIT ?
                """,
                (int(limit),),
            ).fetchall()

            out = []
            for row in rows:
                d = dict(row)
                if d.get("metadata_json"):
                    try:
                        d["metadata"] = json.loads(d["metadata_json"])
                    except Exception:
                        d["metadata"] = d["metadata_json"]
                out.append(d)
            return out

    def get_evidence_health(self, evidence_id: str):
        with self._connect() as con:

            # latest event
            last_event = con.execute(
                """
                SELECT event_type, timestamp_ms
                FROM custody_events
                WHERE evidence_id = ?
                ORDER BY timestamp_ms DESC
                LIMIT 1
                """,
                (evidence_id,),
            ).fetchone()

            # counts
            counts = con.execute(
                """
                SELECT
                    SUM(CASE WHEN event_type='VERIFIED' THEN 1 ELSE 0 END) AS verified_count,
                    SUM(CASE WHEN event_type='INTEGRITY_FAILED' THEN 1 ELSE 0 END) AS failure_count
                FROM custody_events
                WHERE evidence_id = ?
                """,
                (evidence_id,),
            ).fetchone()

            verified = counts["verified_count"] or 0
            failures = counts["failure_count"] or 0

            # ------------------------
            # Health logic
            # ------------------------
            if not last_event:
                status = "UNKNOWN"
            elif last_event["event_type"] == "INTEGRITY_FAILED":
                status = "COMPROMISED"
            elif failures > 0:
                status = "AT_RISK"
            elif verified > 0:
                status = "HEALTHY"
            else:
                status = "UNKNOWN"

            # ------------------------
            # Score logic
            # ------------------------
            score = 100
            score -= failures * 25
            score = max(score, 0)

            alerts = []

            if failures > 0:
                alerts.append("integrity_failure_detected")

            if verified == 0:
                alerts.append("never_verified")

            if failures >= 2:
                alerts.append("repeated_failures")

            return {
                "status": status,
                "score": score,
                "verified_count": verified,
                "failure_count": failures,
                "alerts": alerts,
            }



    def list_active_alerts(self, limit: int = 50):
        with self._connect() as con:
            rows = con.execute(
                """
                SELECT *
                FROM alerts
                WHERE resolved = 0
                ORDER BY created_at_ms DESC
                LIMIT ?
                """,
                (int(limit),),
            ).fetchall()

            return [dict(r) for r in rows]

    def get_alert_settings(self):
        with self._connect() as con:
            row = con.execute(
                "SELECT * FROM alert_settings WHERE id = 1"
            ).fetchone()
            return dict(row) if row else None

    def update_alert_settings(
            self,
            *,
            slack_enabled: int,
            slack_webhook_url: str,
            email_enabled: int,
            email_to: str,
            min_severity: str,
    ):
        with self._connect() as con:
            con.execute(
                """
                UPDATE alert_settings
                SET
                    slack_enabled = ?,
                    slack_webhook_url = ?,
                    email_enabled = ?,
                    email_to = ?,
                    min_severity = ?,
                    updated_at_ms = ?
                WHERE id = 1
                """,
                (
                    int(slack_enabled),
                    slack_webhook_url,
                    int(email_enabled),
                    email_to,
                    min_severity,
                    _now_ms(),
                ),
            )

    def list_alerts(self, limit: int = 100):
        with self._connect() as con:
            rows = con.execute(
                """
                SELECT *
                FROM alerts
                ORDER BY created_at_ms DESC, id DESC
                LIMIT ?
                """,
                (int(limit),),
            ).fetchall()

        return [dict(r) for r in rows]

    def list_recent_events(self, limit: int = 100):
        with self._connect() as con:
            rows = con.execute(
                """
                SELECT *
                FROM custody_events
                ORDER BY timestamp_ms DESC, id DESC
                LIMIT ?
                """,
                (int(limit),),
            ).fetchall()

        return [dict(r) for r in rows]

    def resolve_alert(self, alert_id: int):
        with self._connect() as con:
            con.execute(
                """
                UPDATE alerts
                SET resolved = 1
                WHERE id = ?
                """,
                (int(alert_id),),
            )
            con.commit()

    def list_active_alerts(self, limit: int = 100):
        with self._connect() as con:
            rows = con.execute(
                """
                SELECT *
                FROM alerts
                WHERE resolved = 0
                ORDER BY created_at_ms DESC
                LIMIT ?
                """,
                (int(limit),),
            ).fetchall()

        return [dict(r) for r in rows]

    def create_case(self, title: str, description: str = "", job_id: int = None):
        import time, uuid

        now = int(time.time() * 1000)

        # 🔥 CRITICAL FIX
        case_id = str(uuid.uuid4())

        with self._connect() as con:
            con.execute("""
                INSERT INTO cases (
                    case_id,
                    title,
                    description,
                    status,
                    created_at_ms,
                    job_id
                )
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                case_id,
                title,
                description,
                "OPEN",
                now,
                job_id
            ))

            con.commit()

        print(f"📁 CASE CREATED: {case_id}")
        return case_id

    def list_cases(self, limit=100):
        with self._connect() as con:
            rows = con.execute("""
                SELECT
                    case_id AS id,
                    title,
                    description,
                    status,
                    created_at_ms,
                    updated_at_ms,
                    assigned_to,
                    assigned_by,
                    assigned_at_ms,
                    job_id
                FROM cases
                ORDER BY created_at_ms DESC
            """).fetchall()

        return [dict(r) for r in rows]

    def add_case_evidence(self, case_id, evidence_id):
        import time
        now = int(time.time() * 1000)

        with self._connect() as con:
            con.execute("""
                INSERT INTO case_evidence (case_id, evidence_id, linked_at_ms)
                VALUES (?, ?, ?)
            """, (case_id, evidence_id, now))

            con.commit()

    def list_case_evidence(self, case_id: str):
        with self._connect() as con:
            rows = con.execute("""
                SELECT e.*
                FROM evidence_records e
                JOIN case_evidence ce ON e.evidence_id = ce.evidence_id
                WHERE ce.case_id = ?
            """, (case_id,)).fetchall()  # 🔥 FIX

        return [dict(r) for r in rows]



    def add_case_note(self, case_id: str, note: str):
        with self._connect() as con:
            con.execute("""
                INSERT INTO case_notes (case_id, note, created_at_ms)
                VALUES (?, ?, strftime('%s','now')*1000)
            """, (case_id, note))
            con.commit()

    def list_case_notes(self, case_id: str):
        with self._connect() as con:
            rows = con.execute("""
                SELECT * FROM case_notes
                WHERE case_id = ?
                ORDER BY created_at_ms DESC
            """, (case_id,)).fetchall()  # 🔥 FIX

        return [dict(r) for r in rows]

    def find_case_by_evidence(self, evidence_id: str):
        with self._connect() as con:
            row = con.execute("""
                SELECT c.*
                FROM cases c
                JOIN case_evidence ce ON c.case_id = ce.case_id
                WHERE ce.evidence_id = ?
                LIMIT 1
            """, (evidence_id,)).fetchone()

        return dict(row) if row else None

    def add_case_alert(self, case_id: str, alert_id: int):
        with self._connect() as con:
            con.execute("""
                INSERT OR IGNORE INTO case_alerts (case_id, alert_id)
                VALUES (?, ?)
            """, (case_id, alert_id))
            con.commit()

    def update_case_status(self, case_id, status):
        import time
        now = int(time.time() * 1000)

        with self._connect() as con:
            con.execute("""
                UPDATE cases
                SET status = ?, updated_at_ms = ?
                WHERE case_id = ?
            """, (status, now, case_id))

            con.commit()

            old_status = row["status"] if row else None

            # update case
            con.execute("""
                UPDATE cases
                SET status = ?, updated_at_ms = strftime('%s','now')*1000
                WHERE case_id = ?
            """, (new_status, case_id))

            # audit log
            con.execute("""
                INSERT INTO case_audit_log (
                    case_id, action, old_value, new_value, actor, created_at_ms
                )
                VALUES (?, 'STATUS_CHANGE', ?, ?, ?, strftime('%s','now')*1000)
            """, (case_id, old_status, new_status, actor))

            con.commit()

    def update_case_owner(self, case_id: str, new_owner: str, actor: str):
        with self._connect() as con:
            row = con.execute(
                "SELECT owner FROM cases WHERE case_id = ?",
                (case_id,)
            ).fetchone()

            old_owner = row["owner"] if row else None

            con.execute("""
                UPDATE cases
                SET owner = ?, updated_at_ms = strftime('%s','now')*1000
                WHERE case_id = ?
            """, (new_owner, case_id))

            con.execute("""
                INSERT INTO case_audit_log (
                    case_id, action, old_value, new_value, actor, created_at_ms
                )
                VALUES (?, 'OWNER_CHANGE', ?, ?, ?, strftime('%s','now')*1000)
            """, (case_id, old_owner, new_owner, actor))

            con.commit()

    def list_case_audit_log(self, case_id: str):
        with self._connect() as con:
            rows = con.execute("""
                SELECT *
                FROM case_audit_log
                WHERE case_id = ?
                ORDER BY created_at_ms DESC
            """, (case_id,)).fetchall()

        return [dict(r) for r in rows]

    def build_case_timeline(self, case_id: str):
        timeline = []

        with self._connect() as con:

            # Case audit logs
            audit = con.execute("""
                SELECT created_at_ms, action, new_value, actor
                FROM case_audit_log
                WHERE case_id = ?
            """, (case_id,)).fetchall()

            for r in audit:
                timeline.append({
                    "ts": r["created_at_ms"],
                    "type": "CASE_ACTION",
                    "label": f"{r['action']} → {r['new_value']}",
                    "actor": r["actor"]
                })

            # ----------------------------
            # 🔥 CASE EVENTS (NEW - YOUR WIRED EVENTS)
            # ----------------------------
            events = con.execute("""
                SELECT created_at_ms, event_type, message, actor, details_json
                FROM case_events
                WHERE case_id = ?
            """, (case_id,)).fetchall()

            for r in events:
                timeline.append({
                    "ts": r["created_at_ms"],
                    "type": r["event_type"],  # dynamic types like STATUS_CHANGE
                    "label": r["message"],
                    "actor": r["actor"],
                    "details": r.get("details_json") if isinstance(r, dict) else r[4]
                })

            # Linked alerts
            alerts = con.execute("""
                SELECT a.created_at_ms, a.severity, a.message
                FROM alerts a
                JOIN case_alerts ca ON a.id = ca.alert_id
                WHERE ca.case_id = ?
            """, (case_id,)).fetchall()

            for r in alerts:
                timeline.append({
                    "ts": r["created_at_ms"],
                    "type": "ALERT",
                    "label": f"[{r['severity']}] {r['message']}"
                })

            # Custody events
            events = con.execute("""
                SELECT timestamp_ms, event_type, actor
                FROM custody_events
                WHERE evidence_id IN (
                    SELECT evidence_id FROM case_evidence WHERE case_id = ?
                )
            """, (case_id,)).fetchall()

            for r in events:
                timeline.append({
                    "ts": r["timestamp_ms"],
                    "type": "EVENT",
                    "label": r["event_type"],
                    "actor": r["actor"]
                })

            # Response actions
            actions = con.execute("""
                SELECT created_at_ms, action_type, status, actor, details_json
                FROM response_actions
                WHERE case_id = ?
            """, (case_id,)).fetchall()

            for r in actions:
                timeline.append({
                    "ts": r["created_at_ms"],
                    "type": "RESPONSE",
                    "label": f"{r['action_type']} ({r['status']})",
                    "actor": r["actor"]
                })

            # Response approvals
            approvals = con.execute("""
                SELECT created_at_ms, action_type, status, requested_by, approved_by
                FROM response_approvals
                WHERE case_id = ?
            """, (case_id,)).fetchall()

            # ----------------------------
            # SLACK EVENTS (NEW)
            # ----------------------------
            slack_events = con.execute("""
                SELECT created_at_ms, event_type, message, actor
                FROM case_events
                WHERE case_id = ?
                  AND event_type LIKE 'SLACK_%'
            """, (case_id,)).fetchall()

            for r in slack_events:
                timeline.append({
                    "ts": r["created_at_ms"],
                    "type": "SLACK",
                    "label": r["message"],
                    "actor": r["actor"]
                })

            for r in approvals:
                timeline.append({
                    "ts": r["created_at_ms"],
                    "type": "APPROVAL",
                    "label": f"{r['action_type']} [{r['status']}]",
                    "actor": r["approved_by"] or r["requested_by"],
                })

        # Sort chronologically
        timeline.sort(key=lambda x: x["ts"])

        return timeline

    def check_sla_breach(self, case_id: str):
        import time

        with self._connect() as con:
            row = con.execute("""
                SELECT sla_due_ms, status
                FROM cases
                WHERE case_id = ?
            """, (case_id,)).fetchone()

        if not row:
            return False

        if row["status"] == "RESOLVED":
            return False

        if row["sla_due_ms"] and row["sla_due_ms"] < int(time.time() * 1000):
            return True

        return False

    def record_response_action(
            self,
            case_id: str,
            action_type: str,
            status: str,
            actor: str,
            details: dict | None = None,
    ):
        with self._connect() as con:
            con.execute("""
                INSERT INTO response_actions (
                    case_id,
                    action_type,
                    status,
                    actor,
                    details_json,
                    created_at_ms
                )
                VALUES (?, ?, ?, ?, ?, strftime('%s','now')*1000)
            """, (
                case_id,
                action_type,
                status,
                actor,
                stable_json_dumps(details or {}),
            ))
            con.commit()

    def list_response_actions(self, case_id: str):
        with self._connect() as con:
            rows = con.execute("""
                SELECT *
                FROM response_actions
                WHERE case_id = ?
                ORDER BY created_at_ms DESC
            """, (case_id,)).fetchall()

        return [dict(r) for r in rows]

    def create_response_playbook(
            self,
            playbook_id: str,
            name: str,
            description: str,
            steps_json: str,
    ):
        with self._connect() as con:
            con.execute("""
                INSERT OR REPLACE INTO response_playbooks (
                    playbook_id, name, description, steps_json, created_at_ms
                )
                VALUES (?, ?, ?, ?, strftime('%s','now')*1000)
            """, (playbook_id, name, description, steps_json))
            con.commit()

    def list_response_playbooks(self):
        with self._connect() as con:
            rows = con.execute("""
                SELECT *
                FROM response_playbooks
                ORDER BY name
            """).fetchall()
        return [dict(r) for r in rows]

    def create_response_approval(
            self,
            case_id: str,
            action_type: str,
            requested_by: str,
            details_json: str,
    ):
        with self._connect() as con:
            cur = con.execute("""
                INSERT INTO response_approvals (
                    case_id,
                    action_type,
                    requested_by,
                    approved_by,
                    status,
                    details_json,
                    created_at_ms,
                    updated_at_ms
                )
                VALUES (?, ?, ?, NULL, 'PENDING', ?, strftime('%s','now')*1000, strftime('%s','now')*1000)
            """, (case_id, action_type, requested_by, details_json))
            approval_id = cur.lastrowid
            con.commit()
        return approval_id

    def list_response_approvals(self, case_id: str):
        with self._connect() as con:
            rows = con.execute("""
                SELECT *
                FROM response_approvals
                WHERE case_id = ?
                ORDER BY created_at_ms DESC
            """, (case_id,)).fetchall()
        return [dict(r) for r in rows]

    def update_response_approval(
            self,
            approval_id: int,
            status: str,
            approved_by: str,
    ):
        with self._connect() as con:
            con.execute("""
                UPDATE response_approvals
                SET status = ?, approved_by = ?, updated_at_ms = strftime('%s','now')*1000
                WHERE id = ?
            """, (status, approved_by, int(approval_id)))
            con.commit()

    def get_response_approval(self, approval_id: int):
        with self._connect() as con:
            row = con.execute("""
                SELECT *
                FROM response_approvals
                WHERE id = ?
            """, (int(approval_id),)).fetchone()
        return dict(row) if row else None

    def list_scan_queue(self, limit=100):
        with self._connect() as con:
            rows = con.execute("""
                SELECT *
                FROM processing_queue
                ORDER BY created_at_ms DESC
                LIMIT ?
            """, (int(limit),)).fetchall()

        return [dict(r) for r in rows]

    def get_scan_stats(self):
        with self._connect() as con:
            # Total jobs (guaranteed correct)
            total_row = con.execute("""
                SELECT COUNT(*) FROM processing_queue
            """).fetchone()
            total = total_row[0] if total_row else 0

            # Status counts (normalized)
            rows = con.execute("""
                SELECT UPPER(COALESCE(status, 'UNKNOWN')) as status, COUNT(*) 
                FROM processing_queue
                GROUP BY UPPER(COALESCE(status, 'UNKNOWN'))
            """).fetchall()

            stats_map = {r[0]: r[1] for r in rows}

            # Last run
            last_run_row = con.execute("""
                SELECT MAX(completed_at_ms)
                FROM processing_queue
            """).fetchone()

            last_run = last_run_row[0] if last_run_row else None

        return {
            "total_jobs": total,
            "queued": stats_map.get("QUEUED", 0),
            "running": stats_map.get("RUNNING", 0) + stats_map.get("PROCESSING", 0),
            "completed": stats_map.get("COMPLETED", 0) + stats_map.get("DONE", 0),
            "failed": stats_map.get("FAILED", 0),
            "last_run": last_run,
        }

    def list_recent_evidence(self, limit=20):
        with self._connect() as con:
            rows = con.execute("""
                SELECT *
                FROM evidence_records
                ORDER BY created_at_ms DESC
                LIMIT ?
            """, (limit,)).fetchall()

        return [dict(r) for r in rows]

    print("🔥 THIS enqueue_scan VERSION IS RUNNING")
    def enqueue_scan(self, provider, mailbox, lookback_hours, attachments_only, max_messages, payload=None):
        import time, json
        print("🔥 ENQUEUE_SCAN HIT (sqlite_ledger)")
        now = int(time.time() * 1000)

        with self._connect() as con:
            cur = con.execute("""
                INSERT INTO processing_queue (
                    provider,
                    mailbox,
                    lookback_hours,
                    attachments_only,
                    max_messages,
                    payload_json,
                    status,
                    created_at_ms,
                    updated_at_ms
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                provider,
                mailbox,
                lookback_hours,
                int(attachments_only),
                max_messages,
                json.dumps(payload or {}),
                "PENDING",
                now,
                now
            ))

            job_id = con.execute("SELECT last_insert_rowid()").fetchone()[0]
            print("DEBUG lastrowid:", job_id)
            alt_id = con.execute("SELECT last_insert_rowid()").fetchone()[0]
            print("DEBUG alt_rowid:", alt_id)
            con.commit()

        return job_id  # 🔥 AND THIS LINE

    def list_scan_jobs(self, limit=100):
        with self._connect() as con:
            rows = con.execute("""
                SELECT *
                FROM processing_queue
                ORDER BY created_at_ms DESC
                LIMIT ?
            """, (int(limit),)).fetchall()

        return [dict(r) for r in rows]

    def get_oauth_token(self, provider: str, mailbox: str):
        with self._connect() as con:
            row = con.execute("""
                SELECT *
                FROM oauth_tokens
                WHERE provider=? AND mailbox=?
            """, (provider, mailbox)).fetchone()

        return dict(row) if row else None

    def upsert_oauth_token(
            self,
            *,
            provider: str,
            mailbox: str,
            access_token: str,
            refresh_token: str | None,
            token_uri: str,
            client_id: str,
            client_secret: str,
            scopes: str,
            expiry_ts: int | None,
    ):
        import time
        now = int(time.time() * 1000)

        with self._connect() as con:
            con.execute("""
                INSERT INTO oauth_tokens (
                    provider, mailbox, access_token, refresh_token,
                    token_uri, client_id, client_secret, scopes,
                    expiry_ts, created_at_ms, updated_at_ms
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(provider, mailbox) DO UPDATE SET
                    access_token=excluded.access_token,
                    refresh_token=excluded.refresh_token,
                    token_uri=excluded.token_uri,
                    client_id=excluded.client_id,
                    client_secret=excluded.client_secret,
                    scopes=excluded.scopes,
                    expiry_ts=excluded.expiry_ts,
                    updated_at_ms=excluded.updated_at_ms
            """, (
                provider,
                mailbox,
                access_token,
                refresh_token,
                token_uri,
                client_id,
                client_secret,
                scopes,
                expiry_ts,
                now,
                now
            ))
            con.commit()

    def list_connected_mailboxes(self, provider: str = "gmail"):
        with self._connect() as con:
            rows = con.execute(
                """
                SELECT mailbox
                FROM oauth_tokens
                WHERE provider = ?
                ORDER BY mailbox ASC
                """,
                (provider,),
            ).fetchall()

        return [r["mailbox"] for r in rows]

    def update_scan_progress(self, job_id, current, total):
        with self._connect() as con:
            con.execute("""
                UPDATE processing_queue
                SET progress_current=?,
                    progress_total=?
                WHERE id=?
            """, (int(current), int(total), job_id))
            con.commit()

    def requeue_scan_job(self, job_id):
        with self._connect() as con:
            con.execute("""
                UPDATE processing_queue
                SET status='QUEUED',
                    started_at_ms=NULL,
                    completed_at_ms=NULL,
                    duration_ms=NULL,
                    progress_current=0,
                    progress_total=1,
                    last_error=NULL
                WHERE id=?
            """, (job_id,))
            con.commit()

    def cancel_scan_job(self, job_id):
        import time
        ts = int(time.time() * 1000)

        with self._connect() as con:
            cols = [r[1] for r in con.execute("PRAGMA table_info(scan_queue)")]

            if "completed_at_ms" in cols:
                con.execute("""
                    UPDATE processing_queue
                    SET status='CANCELLED',
                        completed_at_ms=?
                    WHERE id=?
                """, (ts, job_id))
            else:
                con.execute("""
                    UPDATE processing_queue
                    SET status='CANCELLED'
                    WHERE id=?
                """, (job_id,))

            con.commit()

    def delete_scan(self, job_id: int):
        with self._connect() as con:
            con.execute(
                "DELETE FROM processing_queue WHERE id = ?",
                (int(job_id),)
            )
            con.commit()

    def retry_failed_scan(self, job_id):
        with self._connect() as con:
            con.execute("""
                UPDATE processing_queue
                SET status='QUEUED',
                    last_error=NULL,
                    progress_current=0,
                    progress_total=1
                WHERE id=? AND status='FAILED'
            """, (job_id,))
            con.commit()

    def _ensure_scan_queue_columns(self):
        with self._connect() as con:
            existing_cols = [r[1] for r in con.execute("PRAGMA table_info(processing_queue)")]

            def add(col, ddl):
                if col not in existing_cols:
                    con.execute(f"ALTER TABLE processing_queue ADD COLUMN {ddl}")

            add("started_at_ms", "started_at_ms INTEGER")
            add("completed_at_ms", "completed_at_ms INTEGER")
            add("duration_ms", "duration_ms INTEGER")
            add("progress_current", "progress_current INTEGER DEFAULT 0")
            add("progress_total", "progress_total INTEGER DEFAULT 1")
            add("last_error", "last_error TEXT")

            con.commit()

    def get_scan_analytics(self):
        with self._connect() as con:
            total = con.execute("SELECT COUNT(*) FROM processing_queue").fetchone()[0]

            completed = con.execute("""
                SELECT COUNT(*) FROM processing_queue
                WHERE status='COMPLETED'
            """).fetchone()[0]

            failed = con.execute("""
                SELECT COUNT(*) FROM processing_queue
                WHERE status='FAILED'
            """).fetchone()[0]

            avg_duration = con.execute("""
                SELECT AVG(duration_ms)
                FROM processing_queue
                WHERE duration_ms IS NOT NULL
            """).fetchone()[0] or 0

            recent = con.execute("""
                SELECT date(created_at_ms/1000, 'unixepoch') as day,
                       COUNT(*) as jobs
                FROM processing_queue
                GROUP BY day
                ORDER BY day DESC
                LIMIT 14
            """).fetchall()

            errors = con.execute("""
                SELECT last_error, COUNT(*) as cnt
                FROM processing_queue
                WHERE last_error IS NOT NULL
                GROUP BY last_error
                ORDER BY cnt DESC
                LIMIT 5
            """).fetchall()

            mailboxes = con.execute("""
                SELECT mailbox, COUNT(*) as cnt
                FROM processing_queue
                GROUP BY mailbox
                ORDER BY cnt DESC
                LIMIT 5
            """).fetchall()

        return {
            "total": total,
            "completed": completed,
            "failed": failed,
            "success_rate": (completed / total * 100) if total else 0,
            "avg_duration_ms": avg_duration,
            "recent_jobs": [dict(r) for r in recent],
            "top_errors": [dict(r) for r in errors],
            "top_mailboxes": [dict(r) for r in mailboxes],
        }

    def get_alert_correlations(self, limit=50):
        with self._connect() as con:
            rows = con.execute("""
                SELECT
                    json_extract(metadata_json, '$.from') AS from_addr,
                    COUNT(*) AS alert_count
                FROM evidence_records er
                JOIN alerts a ON a.evidence_id = er.evidence_id
                WHERE json_extract(metadata_json, '$.from') IS NOT NULL
                GROUP BY from_addr
                ORDER BY alert_count DESC
                LIMIT ?
            """, (int(limit),)).fetchall()

        return [dict(r) for r in rows]

    def get_alert_domain_correlations(self, limit=50):
        with self._connect() as con:
            rows = con.execute("""
                SELECT
                    substr(json_extract(metadata_json, '$.from'),
                           instr(json_extract(metadata_json, '$.from'), '@') + 1) AS domain,
                    COUNT(*) AS alert_count
                FROM evidence_records er
                JOIN alerts a ON a.evidence_id = er.evidence_id
                WHERE json_extract(metadata_json, '$.from') LIKE '%@%'
                GROUP BY domain
                ORDER BY alert_count DESC
                LIMIT ?
            """, (int(limit),)).fetchall()

        return [dict(r) for r in rows]

    def claim_next_scan_job(self, worker_id: str = None):
        import time

        now = int(time.time() * 1000)

        with self._connect() as con:
            row = con.execute("""
                SELECT *
                FROM processing_queue
                WHERE status = 'PENDING'
                  AND next_attempt_ms <= ?
                ORDER BY created_at_ms ASC
                LIMIT 1
            """, (now,)).fetchone()

            if not row:
                return None

            job_id = row["id"]

            updated = con.execute("""
                UPDATE processing_queue
                SET status = 'RUNNING',
                    worker_id = ?,
                    started_at_ms = ?,
                    updated_at_ms = ?
                WHERE id = ?
                  AND status = 'PENDING'
            """, (worker_id, now, now, job_id))

            if updated.rowcount == 0:
                return None  # another worker took it

            row = con.execute("""
                SELECT * FROM processing_queue WHERE id = ?
            """, (job_id,)).fetchone()

            return dict(row)

    def create_alert(
            self,
            *,
            evidence_id: str,
            severity: str,
            message: str,
    ):
        with self._connect() as con:
            cursor = con.execute(
                """
                INSERT INTO alerts (
                    evidence_id,
                    severity,
                    message,
                    created_at_ms,
                    resolved
                ) VALUES (?, ?, ?, ?, 0)
                """,
                (
                    evidence_id,
                    severity,
                    message,
                    _now_ms(),
                ),
            )

            alert_id = cursor.lastrowid  # 🔥 CRITICAL

            con.commit()

        return alert_id  # 🔥 CRITICAL

    def list_metrics(self, limit=100):
        with self._connect() as con:
            rows = con.execute("""
                SELECT *
                FROM metrics
                ORDER BY ts_ms DESC
                LIMIT ?
            """, (limit,)).fetchall()

            return [dict(row) for row in rows]

    def record_metric(self, name, value, case_id=None, tags=None):
        import json, time

        with self._connect() as con:
            con.execute("""
                INSERT INTO metrics (
                    name,
                    value,
                    ts_ms,
                    tags_json
                )
                VALUES (?, ?, ?, ?)
            """, (
                name,
                value,
                int(time.time() * 1000),
                json.dumps({
                    "case_id": case_id,
                    **(tags or {})
                })
            ))
            con.commit()

    def supervisor_status(self):
        import time

        now = int(time.time() * 1000)

        with self._connect() as con:
            # Open alerts
            open_alerts = con.execute("""
                SELECT COUNT(*) FROM alerts
                WHERE status = 'OPEN'
            """).fetchone()[0]

            # Critical alerts
            critical_alerts = con.execute("""
                SELECT COUNT(*) FROM alerts
                WHERE severity = 'CRITICAL'
            """).fetchone()[0]

            # Recent evidence (last 24h)
            recent_evidence = con.execute("""
                SELECT COUNT(*) FROM evidence_records
                WHERE created_at_ms > ?
            """, (now - 86400000,)).fetchone()[0]

            # Custody failures
            custody_failures = con.execute("""
                SELECT COUNT(*) FROM custody_events
                WHERE event_type = 'INTEGRITY_FAILED'
            """).fetchone()[0]

        return {
            "open_alerts": open_alerts,
            "critical_alerts": critical_alerts,
            "recent_evidence": recent_evidence,
            "custody_failures": custody_failures
        }

    # ---------------------------------------
    # 📊 METRICS
    # ---------------------------------------
    def list_metrics(self, limit=100):
        with self._connect() as con:
            rows = con.execute("""
                SELECT *
                FROM metrics
                ORDER BY ts_ms DESC
                LIMIT ?
            """, (limit,)).fetchall()
            return [dict(r) for r in rows]

    def record_metric(self, name, value, case_id=None, tags=None):
        import json, time

        with self._connect() as con:
            con.execute("""
                INSERT INTO metrics (name, value, ts_ms, tags_json)
                VALUES (?, ?, ?, ?)
            """, (
                name,
                value,
                int(time.time() * 1000),
                json.dumps({
                    "case_id": case_id,
                    **(tags or {})
                })
            ))
            con.commit()

    # ---------------------------------------
    # 🧠 SUPERVISOR STATUS
    # ---------------------------------------
    def supervisor_status(self):
        import time

        now = int(time.time() * 1000)

        with self._connect() as con:
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
    def list_heartbeats(self, limit=50):
        with self._connect() as con:
            try:
                rows = con.execute("""
                    SELECT *
                    FROM heartbeats
                    ORDER BY ts_ms DESC
                    LIMIT ?
                """, (limit,)).fetchall()
                return [dict(r) for r in rows]
            except Exception:
                return []

    # ---------------------------------------
    # 📦 QUEUE
    # ---------------------------------------
    def list_queue(self, limit=100):
        with self._connect() as con:
            try:
                rows = con.execute("""
                    SELECT *
                    FROM processing_queue
                    ORDER BY created_at_ms DESC
                    LIMIT ?
                """, (limit,)).fetchall()
                return [dict(r) for r in rows]
            except Exception:
                return []

    # ---------------------------------------
    # ⚙️ SUPERVISOR CONFIG
    # ---------------------------------------
    def get_supervisor_config(self):
        with self._connect() as con:
            try:
                row = con.execute("""
                    SELECT * FROM supervisor_config
                    ORDER BY id DESC
                    LIMIT 1
                """).fetchone()

                if row:
                    cfg = dict(row)

                    # 🔥 Normalize / backfill missing fields
                    return {
                        "enabled": cfg.get("enabled", 1),
                        "interval_seconds": cfg.get("interval_seconds", 5),
                        "leader_ttl_seconds": cfg.get("leader_ttl_seconds", 120),
                        "auto_enqueue_enabled": cfg.get("auto_enqueue_enabled", 0),
                    }

            except Exception as e:
                print("⚠️ config read error:", e)

        # 🔥 fallback
        return {
            "enabled": 1,
            "interval_seconds": 5,
            "leader_ttl_seconds": 120,
            "auto_enqueue_enabled": 0,
        }

    def try_acquire_supervisor_lock(self, leader_id: str, ttl_seconds: int = 120, lock_name: str = "scan_supervisor"):
        import time

        now = int(time.time() * 1000)
        expires = now + (ttl_seconds * 1000)

        with self._connect() as con:
            row = con.execute("""
                SELECT leader_id, expires_at_ms
                FROM supervisor_locks
                WHERE lock_name = ?
            """, (lock_name,)).fetchone()

            # No lock exists → acquire
            if not row:
                con.execute("""
                    INSERT INTO supervisor_locks (lock_name, leader_id, expires_at_ms)
                    VALUES (?, ?, ?)
                """, (lock_name, leader_id, expires))
                return True

            current_leader = row["leader_id"]
            expiry = row["expires_at_ms"]

            # Expired → steal lock
            if expiry < now:
                con.execute("""
                    UPDATE supervisor_locks
                    SET leader_id = ?, expires_at_ms = ?
                    WHERE lock_name = ?
                """, (leader_id, expires, lock_name))
                return True

            # Already leader → renew
            if current_leader == leader_id:
                con.execute("""
                    UPDATE supervisor_locks
                    SET expires_at_ms = ?
                    WHERE lock_name = ?
                """, (expires, lock_name))
                return True

            return False

    def get_supervisor_lock(self, lock_name="scan_supervisor"):
        with self._connect() as con:
            row = con.execute("""
                SELECT *
                FROM supervisor_locks
                WHERE lock_name = ?
            """, (lock_name,)).fetchone()

            return dict(row) if row else None

    def clear_supervisor_lock(self, lock_name="scan_supervisor"):
        with self._connect() as con:
            res = con.execute("""
                DELETE FROM supervisor_locks
                WHERE lock_name = ?
            """, (lock_name,))
            return res.rowcount > 0

    def get_last_seen_ms(self, worker_id):
        with self._connect() as con:
            row = con.execute("""
                SELECT ts_ms
                FROM heartbeats
                WHERE worker_id = ?
                ORDER BY ts_ms DESC
                LIMIT 1
            """, (worker_id,)).fetchone()

            return row["ts_ms"] if row else None

    def upsert_heartbeat(
            self,
            worker_id: str,
            status: str = "RUNNING",
            **kwargs
    ):
        import time, json

        now = int(time.time() * 1000)

        # 🔥 Normalize all extra fields into details_json
        details = {}

        # If caller passed details dict
        if "details" in kwargs and isinstance(kwargs["details"], dict):
            details.update(kwargs["details"])

        # If caller passed details_json
        if "details_json" in kwargs:
            try:
                details.update(json.loads(kwargs["details_json"]))
            except Exception:
                pass

        # Add leader_id if present
        if "leader_id" in kwargs:
            details["leader_id"] = kwargs["leader_id"]

        details_json_final = json.dumps(details)

        with self._connect() as con:
            con.execute("""
                INSERT INTO heartbeats (worker_id, status, ts_ms, details_json)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(worker_id)
                DO UPDATE SET
                    status = excluded.status,
                    ts_ms = excluded.ts_ms,
                    details_json = excluded.details_json
            """, (
                worker_id,
                status,
                now,
                details_json_final
            ))
            con.commit()

    def claim_next_scan(self, worker_id: str):
        return self.claim_next_scan_job(worker_id=worker_id)

    def mark_scan_done(self, job_id: int, run_id: str):
        import time
        with self._connect() as con:
            con.execute("""
                UPDATE processing_queue
                SET status = 'COMPLETED',
                    completed_at_ms = ?,
                    error = NULL
                WHERE id = ?
            """, (int(time.time() * 1000), job_id))
            con.commit()

    def mark_scan_failed(self, job_id: int, error: str):
        import time
        with self._connect() as con:
            con.execute("""
                UPDATE processing_queue
                SET status = 'FAILED',
                    error = ?,
                    completed_at_ms = ?
                WHERE id = ?
            """, (error, int(time.time() * 1000), job_id))
            con.commit()

    def count_pending_scans(self):
        with self._connect() as con:
            row = con.execute("""
                SELECT COUNT(*) FROM processing_queue
                WHERE status = 'PENDING'
            """).fetchone()
            return int(row[0] or 0)


    def get_cases_for_alert(self, alert_id: int):
        with self._connect() as con:
            rows = con.execute("""
                SELECT case_id
                FROM case_alerts
                WHERE alert_id = ?
            """, (alert_id,)).fetchall()

            return [dict(r) for r in rows]

    def get_active_cases(self):
        with self._connect() as con:
            rows = con.execute("""
                SELECT *
                FROM cases
                WHERE status != 'closed'
                ORDER BY created_at DESC
            """).fetchall()

            return [dict(r) for r in rows]

    def get_failed_jobs(self, limit=50):
        with self._connect() as con:
            rows = con.execute("""
                SELECT *
                FROM processing_queue
                WHERE status = 'FAILED'
                ORDER BY updated_at_ms DESC
                LIMIT ?
            """, (limit,)).fetchall()

            return [dict(r) for r in rows]

    def get_case_by_alert(self, alert_id: int):
        """
        Returns the first case linked to an alert.
        """
        with self._connect() as con:
            row = con.execute("""
                SELECT case_id
                FROM case_alerts
                WHERE alert_id = ?
                LIMIT 1
            """, (alert_id,)).fetchone()

            return dict(row) if row else None

    def log_debug_event(self, job_id: int, message: str):
        import time
        ts = int(time.time() * 1000)

        with self._connect() as con:
            con.execute("""
                INSERT INTO metrics (name, value, tags_json, created_at_ms)
                VALUES (?, ?, ?, ?)
            """, (
                "scan.debug",
                1.0,
                json.dumps({
                    "job_id": job_id,
                    "message": message
                }),
                ts
            ))
            con.commit()

    def list_running_jobs(self, limit=20):
        with self._connect() as con:
            rows = con.execute("""
                SELECT id, provider, mailbox, status,
                       progress_current, progress_total,
                       started_at_ms
                FROM processing_queue
                WHERE status IN ('RUNNING', 'PROCESSING')
                ORDER BY started_at_ms DESC
                LIMIT ?
            """, (int(limit),)).fetchall()

        return [dict(r) for r in rows]

    def retry_all_failed(self):
        import time
        now = int(time.time() * 1000)

        with self._connect() as con:
            con.execute("""
                UPDATE processing_queue
                SET status = 'QUEUED',
                    attempts = COALESCE(attempts, 0) + 1,
                    last_error = NULL,
                    started_at_ms = NULL,
                    completed_at_ms = NULL,
                    duration_ms = NULL,
                    progress_current = 0,
                    progress_total = 1,
                    updated_at_ms = ?
                WHERE UPPER(status) = 'FAILED'
            """, (now,))
            con.commit()

    def delete_completed(self):
        with self._connect() as con:
            con.execute("""
                DELETE FROM processing_queue
                WHERE UPPER(status) = 'COMPLETED'
            """)
            con.commit()

    def cancel_all_running(self):
        import time
        now = int(time.time() * 1000)

        with self._connect() as con:
            con.execute("""
                UPDATE processing_queue
                SET status = 'FAILED',
                    last_error = 'Cancelled by user (bulk)',
                    completed_at_ms = ?,
                    duration_ms = COALESCE(?, 0),
                    updated_at_ms = ?
                WHERE UPPER(status) IN ('RUNNING', 'PROCESSING')
            """, (now, 0, now))
            con.commit()

    def clear_all_jobs(self):
        with self._connect() as con:
            cur = con.execute("DELETE FROM processing_queue")
            deleted = cur.rowcount
            con.commit()

        print(f"🔥 CLEARED ALL JOBS: {deleted} rows removed")

    def cancel_scan(self, job_id: int):
        import time
        now = int(time.time() * 1000)

        with self._connect() as con:
            con.execute("""
                UPDATE processing_queue
                SET status = 'CANCELLED',
                    last_error = 'Cancelled by user',
                    completed_at_ms = ?,
                    duration_ms = CASE
                        WHEN started_at_ms IS NOT NULL
                        THEN (? - started_at_ms)
                        ELSE 0
                    END,
                    updated_at_ms = ?
                WHERE id = ?
            """, (now, now, now, int(job_id)))
            con.commit()

        print(f"🛑 CANCELLED JOB {job_id}")

    def retry_scan(self, job_id: int):
        import time
        now = int(time.time() * 1000)

        with self._connect() as con:
            con.execute("""
                UPDATE processing_queue
                SET status = 'QUEUED',
                    attempts = COALESCE(attempts, 0) + 1,
                    last_error = NULL,
                    started_at_ms = NULL,
                    completed_at_ms = NULL,
                    duration_ms = NULL,
                    progress_current = 0,
                    progress_total = 1,
                    updated_at_ms = ?
                WHERE id = ?
            """, (now, int(job_id)))
            con.commit()

        print(f"🔁 RETRY JOB {job_id}")

    def ensure_case_for_alert(self, alert_id: int, evidence_id=None, job_id=None):
        import time
        from core.utils.case_utils import generate_case_id

        now = int(time.time() * 1000)

        with self._connect() as con:

            # ----------------------------------
            # 1. Reuse existing mapping (fast path)
            # ----------------------------------
            existing = con.execute("""
                SELECT case_id FROM case_alert_map
                WHERE alert_id = ?
            """, (alert_id,)).fetchone()

            if existing:
                return str(existing[0])

            # ----------------------------------
            # 2. Reuse existing OPEN case by job_id
            # ----------------------------------
            case_id = None

            if job_id:
                row = con.execute("""
                    SELECT case_id FROM cases
                    WHERE status = 'OPEN' AND job_id = ?
                    ORDER BY created_at_ms DESC
                    LIMIT 1
                """, (job_id,)).fetchone()

                if row:
                    case_id = str(row[0])

            # ----------------------------------
            # 3. Create new case (CORRECT FIX)
            # ----------------------------------
            if not case_id:

                # 🔥 deterministic case_id
                if job_id:
                    case_id = generate_case_id(str(job_id))
                elif evidence_id:
                    case_id = generate_case_id(str(evidence_id))
                else:
                    case_id = generate_case_id(f"alert_{alert_id}")

                con.execute("""
                    INSERT OR IGNORE INTO cases (
                        case_id,
                        title,
                        description,
                        status,
                        created_at_ms,
                        job_id
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    case_id,
                    f"Critical Alert {alert_id}",
                    f"Auto-generated from alert {alert_id}",
                    "OPEN",
                    now,
                    job_id
                ))

            # ----------------------------------
            # 4. Link alert → case
            # ----------------------------------
            con.execute("""
                INSERT OR IGNORE INTO case_alert_map (case_id, alert_id)
                VALUES (?, ?)
            """, (case_id, alert_id))

            # ----------------------------------
            # 5. Link evidence → case
            # ----------------------------------
            if evidence_id:
                con.execute("""
                    INSERT OR IGNORE INTO case_evidence_map (case_id, evidence_id)
                    VALUES (?, ?)
                """, (case_id, evidence_id))

            con.commit()

        print(f"🚨 AUTO CASE: case_id={case_id} alert_id={alert_id}")
        return case_id

    def get_case_details(self, case_id):
        with self._connect() as con:
            case = con.execute("""
                SELECT
                    case_id AS id,
                    title,
                    description,
                    status,
                    created_at_ms,
                    updated_at_ms,
                    assigned_to,
                    assigned_by,
                    assigned_at_ms,
                    job_id
                FROM cases
                WHERE case_id = ?
            """, (case_id,)).fetchone()

            alerts = con.execute("""
                SELECT *
                FROM alerts
                WHERE case_id = ?
            """, (case_id,)).fetchall()

            evidence = con.execute("""
                SELECT
                    er.evidence_id,
                    er.suggested_name,
                    er.content_type,
                    er.size_bytes,
                    er.created_at_ms,
                    er.sha256
                FROM evidence_records er
                JOIN case_evidence ce
                    ON ce.evidence_id = er.evidence_id
                WHERE ce.case_id = ?
            """, (case_id,)).fetchall()

        return {
            "case": dict(case) if case else None,
            "alerts": [dict(a) for a in alerts],
            "evidence": [dict(e) for e in evidence],
        }

    def add_case_note(self, case_id, note):
        import time

        now = int(time.time() * 1000)

        with self._connect() as con:
            con.execute("""
                INSERT INTO case_notes (case_id, note, created_at_ms)
                VALUES (?, ?, ?)
            """, (case_id, note, now))

            con.commit()

    def get_case_notes(self, case_id):
        with self._connect() as con:
            rows = con.execute("""
                SELECT *
                FROM case_notes
                WHERE case_id = ?
                ORDER BY created_at_ms DESC
            """, (case_id,)).fetchall()

        return [dict(r) for r in rows]

    def add_case_event(self, case_id, event_type, message, actor="system", details=None):
        import time, json

        now = int(time.time() * 1000)

        with self._connect() as con:
            con.execute("""
                INSERT INTO case_events (
                    case_id,
                    event_type,
                    message,
                    created_at_ms,
                    actor,
                    details_json
                )
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                case_id,
                event_type,
                message,
                now,
                actor,
                json.dumps(details) if details else None
            ))

            con.commit()

    def get_case_timeline(self, case_id):
        with self._connect() as con:
            rows = con.execute("""
                SELECT *
                FROM case_events
                WHERE case_id = ?
                ORDER BY created_at_ms DESC
            """, (case_id,)).fetchall()

        return [dict(r) for r in rows]

    def assign_case(self, case_id, assigned_to, assigned_by):
        import time, json

        now = int(time.time() * 1000)

        with self._connect() as con:
            con.execute("""
                UPDATE cases
                SET assigned_to=?, assigned_by=?, assigned_at_ms=?
                WHERE case_id=?
            """, (assigned_to, assigned_by, now, case_id))

            con.execute("""
                INSERT INTO case_audit_log (case_id, action, performed_by, details, created_at_ms)
                VALUES (?, ?, ?, ?, ?)
            """, (
                case_id,
                "CASE_ASSIGNED",
                assigned_by,
                json.dumps({"assigned_to": assigned_to}),
                now
            ))

            con.commit()

    def get_case_audit_log(self, case_id):
        with self._connect() as con:
            rows = con.execute("""
                SELECT *
                FROM case_audit_log
                WHERE case_id = ?
                ORDER BY created_at_ms DESC
            """, (case_id,)).fetchall()

        return [dict(r) for r in rows]

    def get_evidence_for_alert(self, alert_id: int):
        with self._connect() as con:
            rows = con.execute("""
                SELECT evidence_id
                FROM alert_evidence
                WHERE alert_id = ?
            """, (alert_id,)).fetchall()

            if rows:
                return [r["evidence_id"] for r in rows]

            # fallback to legacy
            row = con.execute("""
                SELECT evidence_id
                FROM alerts
                WHERE id = ?
            """, (alert_id,)).fetchone()

        if not row:
            return []

        return [row["evidence_id"]] if row["evidence_id"] else []

    def add_alert_evidence(self, alert_id: int, evidence_id: str):
        with self._connect() as con:
            con.execute("""
                INSERT OR IGNORE INTO alert_evidence (alert_id, evidence_id)
                VALUES (?, ?)
            """, (alert_id, evidence_id))
            con.commit()

    def find_similar_case_for_alert(self, alert_id: int):
        with self._connect() as con:

            # Get alert info
            alert = con.execute("""
                SELECT id, evidence_id, message
                FROM alerts
                WHERE id = ?
            """, (alert_id,)).fetchone()

            if not alert:
                return None

            evidence_id = alert["evidence_id"]

            # 🔥 Find existing case with SAME evidence
            row = con.execute("""
                SELECT ce.case_id
                FROM case_evidence ce
                WHERE ce.evidence_id = ?
                LIMIT 1
            """, (evidence_id,)).fetchone()

            if row:
                return row["case_id"]

            return None

    def evaluate_case_escalation(self, case_id: str):
        with self._connect() as con:

            # Get alerts linked to case
            alerts = con.execute("""
                SELECT a.severity
                FROM alerts a
                JOIN case_alerts ca ON a.id = ca.alert_id
                WHERE ca.case_id = ?
            """, (case_id,)).fetchall()

        if not alerts:
            return None

        severities = [a["severity"] for a in alerts]

        # 🔥 Simple scoring model
        score_map = {
            "CRITICAL": 100,
            "HIGH": 80,
            "MEDIUM": 50,
            "LOW": 10
        }

        risk_score = max([score_map.get(s, 0) for s in severities])

        escalation = None

        if risk_score >= 90:
            escalation = "CRITICAL"
        elif risk_score >= 70:
            escalation = "HIGH"
        elif risk_score >= 40:
            escalation = "MEDIUM"

        return {
            "risk_score": risk_score,
            "escalation": escalation
        }

    def add_case_escalation_event(self, case_id: str, level: str):
        if not hasattr(self, "add_case_event"):
            return

        self.add_case_event(
            case_id,
            "CASE_ESCALATED",
            f"Case escalated to {level}"
        )

    def is_message_processed(self, provider, uid):
        with self._connect() as con:
            row = con.execute(
                "SELECT 1 FROM processed_messages WHERE provider=? AND uid=?",
                (provider, uid)
            ).fetchone()
            return row is not None

    def mark_message_processed(self, provider, uid):
        with self._connect() as con:
            con.execute(
                "INSERT INTO processed_messages (provider, uid) VALUES (?, ?)",
                (provider, uid)
            )

    def record_event(self, event_type: str, data: dict):
        import json
        import time
        import uuid

        event_id = uuid.uuid4().hex
        ts = int(time.time() * 1000)

        with self._connect() as con:
            con.execute("""
                INSERT INTO evidence_events (
                    event_id,
                    event_type,
                    data_json,
                    created_at_ms
                ) VALUES (?, ?, ?, ?)
            """, (
                event_id,
                event_type,
                json.dumps(data),
                ts
            ))
            con.commit()

        print(f"🧾 EVENT INSERTED: {event_type}")

    # ----------------------------
    # 🔔 ALERT SETTINGS
    # ----------------------------
    def save_alert_settings(self, settings: dict):
        with self._connect() as con:
            # Ensure table exists
            con.execute("""
                CREATE TABLE IF NOT EXISTS alert_settings (
                    id INTEGER PRIMARY KEY,
                    slack_enabled INTEGER,
                    slack_webhook_url TEXT,
                    email_enabled INTEGER,
                    email_to TEXT,
                    min_severity TEXT
                )
            """)

            # Upsert (single row config)
            con.execute("""
                INSERT OR REPLACE INTO alert_settings (
                    id,
                    slack_enabled,
                    slack_webhook_url,
                    email_enabled,
                    email_to,
                    min_severity
                )
                VALUES (1, ?, ?, ?, ?, ?)
            """, (
                int(settings.get("slack_enabled", False)),
                settings.get("slack_webhook_url"),
                int(settings.get("email_enabled", False)),
                settings.get("email_to"),
                settings.get("min_severity", "HIGH")
            ))

            con.commit()

    def get_alert_settings(self):
        with self._connect() as con:
            row = con.execute("""
                SELECT * FROM alert_settings WHERE id = 1
            """).fetchone()

            if not row:
                return None

            settings = dict(row)

            # 🔥 FIX BOOLEAN CONVERSION
            settings["slack_enabled"] = bool(settings.get("slack_enabled"))
            settings["email_enabled"] = bool(settings.get("email_enabled"))

            return settings

    def get_case_slack_thread(self, case_id):
        with self._connect() as con:
            row = con.execute(
                "SELECT slack_channel_id, slack_thread_ts FROM cases WHERE case_id = ?",
                (case_id,)
            ).fetchone()

        if row:
            return row["slack_channel_id"], row["slack_thread_ts"]

        return None, None

    def save_case_slack_thread(self, case_id, channel, thread_ts):
        with self._connect() as con:
            con.execute(
                "UPDATE cases SET slack_thread_ts = ? WHERE case_id = ?",
                (ts, case_id)
            )
            con.commit()

    def get_last_escalation(self, case_id):
        with self._connect() as con:
            row = con.execute(
                "SELECT MAX(created_at_ms) FROM case_events WHERE case_id = ? AND event_type = 'ESCALATION'",
                (case_id,)
            ).fetchone()
            return row[0] if row and row[0] else None

    def record_escalation(self, case_id, ts):
        with self._connect() as con:
            con.execute("""
                INSERT INTO case_events (case_id, event_type, message, created_at_ms)
                VALUES (?, 'ESCALATION', 'Auto escalation triggered', ?)
            """, (case_id, ts))
            con.commit()

    def update_case_owner(self, case_id, owner):
        with self._connect() as con:
            con.execute("""
                UPDATE cases
                SET owner = ?
                WHERE case_id = ?
            """, (owner, case_id))
            con.commit()

    # ----------------------------
    # ANALYST WORKLOAD / ASSIGNMENT
    # ----------------------------

    def list_active_analysts(self):
        """
        Returns active analysts. If you do not have a users table yet,
        this safely returns a default analyst pool.
        """
        with self._connect() as con:
            try:
                rows = con.execute("""
                    SELECT username, role, is_active
                    FROM users
                    WHERE is_active = 1
                      AND role IN ('ANALYST', 'SENIOR_ANALYST', 'MANAGER')
                """).fetchall()

                analysts = [dict(r) for r in rows]

                if analysts:
                    return analysts

            except Exception:
                pass

        # Safe fallback until users table is fully wired
        return [
            {"username": "analyst_queue", "role": "ANALYST", "is_active": 1},
            {"username": "senior_analyst", "role": "SENIOR_ANALYST", "is_active": 1},
            {"username": "manager", "role": "MANAGER", "is_active": 1},
        ]

    def get_open_case_count_for_owner(self, owner: str) -> int:
        with self._connect() as con:
            row = con.execute("""
                SELECT COUNT(*)
                FROM cases
                WHERE assigned_to = ?
                  AND status IN ('OPEN', 'INVESTIGATING')
            """, (owner,)).fetchone()

        return int(row[0] or 0)

    def choose_owner_for_case(self, severity: str = "LOW") -> str:
        """
        Picks the least-loaded eligible owner based on severity.
        """
        severity = (severity or "LOW").upper().strip()

        analysts = self.list_active_analysts()

        if severity == "CRITICAL":
            eligible_roles = {"SENIOR_ANALYST", "MANAGER"}
        elif severity == "HIGH":
            eligible_roles = {"ANALYST", "SENIOR_ANALYST"}
        else:
            eligible_roles = {"ANALYST"}

        eligible = [
            a for a in analysts
            if str(a.get("role", "")).upper() in eligible_roles
        ]

        if not eligible:
            eligible = analysts

        scored = []

        for a in eligible:
            username = a.get("username")
            workload = self.get_open_case_count_for_owner(username)
            scored.append((workload, username))

        scored.sort(key=lambda x: x[0])

        return scored[0][1] if scored else "analyst_queue"

    def auto_assign_case(self, case_id: str, severity: str = "LOW", actor: str = "system"):
        import time

        severity = (severity or "LOW").upper()

        # ---------------------------------------
        # SIMPLE ROUTING
        # ---------------------------------------
        if severity == "CRITICAL":
            owner = "senior_analyst"
        elif severity == "HIGH":
            owner = "analyst"
        else:
            owner = "analyst_queue"

        now = int(time.time() * 1000)

        with self._connect() as con:
            con.execute("""
                UPDATE cases
                SET assigned_to = ?,
                    assigned_by = ?,
                    assigned_at_ms = ?,
                    updated_at_ms = ?
                WHERE case_id = ?
            """, (
                owner,
                actor,
                now,
                now,
                case_id
            ))
            con.commit()

        # ---------------------------------------
        # LOG EVENT
        # ---------------------------------------
        self.add_case_event(
            case_id,
            "AUTO_ASSIGNED",
            f"Case auto-assigned to {owner}",
            actor=actor,
            details={
                "assigned_to": owner,
                "severity": severity
            }
        )

        return owner

    def enqueue_task(self, task_type: str, payload: dict, priority: int = None, max_attempts: int = None):
        import json, time

        now = int(time.time() * 1000)

        priority = priority if priority is not None else self._task_priority(task_type, payload)
        max_attempts = max_attempts if max_attempts is not None else self._task_max_attempts(task_type)

        with self._connect() as con:
            con.execute("""
                INSERT INTO task_queue (
                    task_type,
                    payload_json,
                    status,
                    priority,
                    attempts,
                    max_attempts,
                    available_at_ms,
                    created_at_ms
                )
                VALUES (?, ?, 'QUEUED', ?, 0, ?, ?, ?)
            """, (
                task_type,
                json.dumps(payload),
                priority,
                max_attempts,
                now,
                now
            ))
            con.commit()

    def claim_next_task(self):
        import json

        with self._connect() as con:
            row = con.execute("""
                SELECT id, task_type, payload_json
                FROM task_queue
                WHERE status='QUEUED'
                ORDER BY
                    priority ASC,
                    (strftime('%s','now') * 1000 - created_at_ms) DESC
                LIMIT 1
            """).fetchone()

            if not row:
                return None

            task_id = row["id"]

            con.execute("""
                UPDATE task_queue
                SET status='RUNNING',
                    started_at_ms=strftime('%s','now') * 1000
                WHERE id=? AND status='QUEUED'
            """, (task_id,))
            con.commit()

            return {
                "id": task_id,
                "type": row["task_type"],
                "payload": json.loads(row["payload_json"])
            }

    def _task_priority(self, task_type: str, payload: dict) -> int:
        severity = str(payload.get("severity", "")).upper()

        if severity == "CRITICAL":
            return 1
        if severity == "HIGH":
            return 2
        if task_type == "ESCALATE":
            return 2
        if task_type == "NOTIFY":
            return 3
        if task_type == "METRIC_BATCH":
            return 9

        return 5

    def _task_max_attempts(self, task_type: str) -> int:
        return {
            "NOTIFY": 5,
            "ESCALATE": 3,
            "METRIC_BATCH": 2,
        }.get(task_type, 3)

    def _task_backoff_ms(self, task_type: str, attempts: int) -> int:
        base = {
            "NOTIFY": 5_000,
            "ESCALATE": 15_000,
            "METRIC_BATCH": 2_000,
        }.get(task_type, 5_000)

        return min(300_000, base * (2 ** max(attempts - 1, 0)))

    def mark_task_failed(self, task_id: int, error: str):
        import time

        now = int(time.time() * 1000)

        with self._connect() as con:
            row = con.execute("""
                SELECT id, task_type, payload_json, attempts, max_attempts
                FROM task_queue
                WHERE id = ?
            """, (task_id,)).fetchone()

            if not row:
                print(f"⚠️ Task {task_id} not found")
                return

            attempts = int(row["attempts"] or 0) + 1
            max_attempts = int(row["max_attempts"] or 3)
            task_type = row["task_type"]

            print(f"❌ Task {task_id} failed (attempt {attempts}/{max_attempts})")

            # ----------------------------------
            # 🔥 MAX RETRIES EXCEEDED → DEAD LETTER
            # ----------------------------------
            if attempts >= max_attempts:

                con.execute("""
                    INSERT INTO task_dead_letter (
                        original_task_id,
                        task_type,
                        payload_json,
                        attempts,
                        last_error,
                        failed_at_ms
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    row["id"],
                    task_type,
                    row["payload_json"],
                    attempts,
                    error[:2000],
                    now
                ))

                con.execute("""
                    UPDATE task_queue
                    SET status = 'FAILED',
                        attempts = ?,
                        last_error = ?,
                        completed_at_ms = ?
                    WHERE id = ?
                """, (
                    attempts,
                    error[:2000],
                    now,
                    task_id
                ))

                print(f"☠️ Task {task_id} moved to DEAD LETTER")

            else:
                # ----------------------------------
                # 🔥 RETRY WITH BACKOFF
                # ----------------------------------
                backoff_ms = self._task_backoff_ms(task_type, attempts)

                con.execute("""
                    UPDATE task_queue
                    SET status = 'QUEUED',
                        attempts = ?,
                        last_error = ?,
                        available_at_ms = ?
                    WHERE id = ?
                """, (
                    attempts,
                    error[:2000],
                    now + backoff_ms,
                    task_id
                ))

                print(f"🔁 Task {task_id} requeued (retry in {backoff_ms} ms)")

            con.commit()

    def mark_task_done(self, task_id: int):
        import time

        now = int(time.time() * 1000)

        with self._connect() as con:
            con.execute("""
                UPDATE task_queue
                SET status = 'DONE',
                    completed_at_ms = ?
                WHERE id = ?
            """, (now, task_id))
            con.commit()

    def reset_stuck_tasks(self, timeout_minutes=10):
        import time

        now = int(time.time() * 1000)
        threshold = now - (timeout_minutes * 60 * 1000)

        with self._connect() as con:
            rows = con.execute("""
                SELECT id
                FROM task_queue
                WHERE status = 'RUNNING'
                  AND started_at_ms < ?
            """, (threshold,)).fetchall()

            if not rows:
                return 0

            for r in rows:
                con.execute("""
                    UPDATE task_queue
                    SET status = 'QUEUED',
                        attempts = attempts + 1
                    WHERE id = ?
                """, (r["id"],))

            con.commit()

        print(f"♻️ Reset {len(rows)} stuck tasks")
        return len(rows)

    def emit_worker_event(self, worker_name, event_type, message, task_id=None, job_id=None):
        import time

        with self._connect() as con:
            con.execute("""
                CREATE TABLE IF NOT EXISTS worker_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    worker_name TEXT,
                    event_type TEXT,
                    message TEXT,
                    task_id INTEGER,
                    job_id INTEGER,
                    created_at_ms INTEGER
                )
            """)

            con.execute("""
                INSERT INTO worker_events (
                    worker_name, event_type, message, task_id, job_id, created_at_ms
                )
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                worker_name,
                event_type,
                message,
                task_id,
                job_id,
                int(time.time() * 1000)
            ))
            con.commit()

    def get_worker_events(self, limit=100):
        with self._connect() as con:
            rows = con.execute("""
                SELECT *
                FROM worker_events
                ORDER BY created_at_ms DESC
                LIMIT ?
            """, (limit,)).fetchall()

        return [dict(r) for r in rows]

    def get_queue_delay_summary(self):
        with self._connect() as con:
            rows = con.execute("""
                SELECT
                    task_type,
                    status,
                    priority,
                    COUNT(*) AS count,
                    MAX((strftime('%s','now') * 1000 - created_at_ms) / 60000.0) AS max_age_min,
                    AVG((strftime('%s','now') * 1000 - created_at_ms) / 60000.0) AS avg_age_min
                FROM task_queue
                WHERE status IN ('QUEUED', 'RUNNING')
                GROUP BY task_type, status, priority
                ORDER BY priority ASC, max_age_min DESC
            """).fetchall()

        return [dict(r) for r in rows]

    def detect_queue_sla_breaches(self):
        import time

        now = int(time.time() * 1000)

        thresholds = {
            1: 2,  # critical queue priority: 2 min
            2: 10,  # high: 10 min
            5: 30,  # normal: 30 min
            9: 120,  # low metrics: 2h
        }

        breaches = []

        with self._connect() as con:
            rows = con.execute("""
                SELECT id, task_type, priority, created_at_ms, payload_json
                FROM task_queue
                WHERE status = 'QUEUED'
            """).fetchall()

            for r in rows:
                priority = int(r["priority"] or 5)
                threshold = thresholds.get(priority, 30)
                age_min = (now - int(r["created_at_ms"] or now)) / 60000.0

                if age_min >= threshold:
                    breaches.append({
                        "task_id": r["id"],
                        "task_type": r["task_type"],
                        "priority": priority,
                        "age_min": round(age_min, 2),
                        "threshold_min": threshold,
                        "payload_json": r["payload_json"],
                    })

        return breaches

    def score_analyst_for_case(self, analyst: str, case_domain: str, severity: str):
        """
        Deterministic AI-style routing score.
        Lower score is better.
        """
        workload = self.get_open_case_count_for_owner(analyst)

        role_bonus = 0
        domain_bonus = 0

        analyst_l = analyst.lower()

        if severity == "CRITICAL" and "senior" in analyst_l:
            role_bonus -= 3

        if case_domain == "EMAIL" and "email" in analyst_l:
            domain_bonus -= 3
        elif case_domain == "ENDPOINT" and "endpoint" in analyst_l:
            domain_bonus -= 3
        elif case_domain == "AI" and "ai" in analyst_l:
            domain_bonus -= 3

        return workload + role_bonus + domain_bonus

    def ai_route_case(self, case_id: str, severity: str = "LOW"):
        import time

        domain = self.infer_case_domain(case_id)
        severity = (severity or "LOW").upper()

        candidates = [
            "analyst",
            "senior_analyst",
            "email_analyst",
            "endpoint_analyst",
            "ai_risk_analyst",
            "manager",
        ]

        scored = []

        for analyst in candidates:
            score = self.score_analyst_for_case(
                analyst=analyst,
                case_domain=domain,
                severity=severity
            )
            scored.append((score, analyst))

        scored.sort(key=lambda x: x[0])

        winner = scored[0][1]
        now = int(time.time() * 1000)

        with self._connect() as con:
            con.execute("""
                UPDATE cases
                SET assigned_to = ?,
                    assigned_by = ?,
                    assigned_at_ms = ?,
                    updated_at_ms = ?
                WHERE case_id = ?
            """, (
                winner,
                f"ai_router:{domain}",
                now,
                now,
                case_id,
            ))
            con.commit()

        self.add_case_event(
            case_id,
            "AI_ROUTED",
            f"AI router assigned case to {winner}",
            actor="ai_router",
            details={
                "domain": domain,
                "severity": severity,
                "assigned_to": winner,
                "scores": scored,
            }
        )

        return {
            "case_id": case_id,
            "domain": domain,
            "assigned_to": winner,
            "scores": scored,
        }

    def reassign_job(self, job_id, new_owner):
        with self._connect() as con:
            con.execute(
                """
                UPDATE scan_queue
                SET owner=?, updated_at_ms=?
                WHERE id=?
                """,
                (new_owner, int(time.time() * 1000), job_id)
            )
            con.commit()

    def bump_case_priority(self, case_id):
        try:
            with self._connect() as con:

                con.execute("""
                    UPDATE cases
                    SET severity = CASE
                        WHEN severity = 'LOW' THEN 'MEDIUM'
                        WHEN severity = 'MEDIUM' THEN 'HIGH'
                        WHEN severity = 'HIGH' THEN 'CRITICAL'
                        ELSE severity
                    END,
                    updated_at_ms=?
                    WHERE id=?
                """, (int(time.time() * 1000), case_id))

                con.commit()

            # Optional alert hook
            self.create_alert(
                category="CASE_ESCALATION",
                severity="HIGH",
                message=f"Case {case_id} escalated due to SLA breach"
            )

        except Exception as e:
            print(f"[LEDGER][CASE BUMP ERROR] {e}")

    def get_escalation_owner(self, job_id):
        try:
            with self._connect() as con:

                row = con.execute(
                    """
                    SELECT owner
                    FROM scan_queue
                    WHERE id=?
                    """,
                    (job_id,)
                ).fetchone()

            if row and row[0]:
                # future: map owner → manager
                return "manager_queue"

            return "manager_queue"

        except Exception as e:
            print(f"[LEDGER][ESC OWNER ERROR] {e}")
            return "manager_queue"

    def predict_sla_breaches(self):
        try:
            with self._connect() as con:

                rows = con.execute("""
                    SELECT
                        id,
                        started_at_ms,
                        progress_current,
                        progress_total
                    FROM scan_queue
                    WHERE status='PROCESSING'
                """).fetchall()

            now = int(time.time() * 1000)
            results = []

            for r in rows:

                job_id, started, current, total = r

                if not started or not total or total == 0:
                    continue

                elapsed_sec = (now - started) / 1000

                if elapsed_sec <= 0:
                    continue

                rate = current / elapsed_sec

                if rate <= 0:
                    continue

                remaining = total - current
                eta = remaining / rate

                SLA_SECONDS = 300  # configurable later

                if eta > SLA_SECONDS:
                    results.append({
                        "job_id": job_id,
                        "eta_seconds": int(eta),
                        "risk": "HIGH"
                    })

            return results

        except Exception as e:
            print(f"[LEDGER][PREDICT ERROR] {e}")
            return []

    import json
    import time

    def list_recent_sla_events(self, limit=100):

        with self._connect() as con:
            rows = con.execute(
                """
                SELECT
                    evidence_id,
                    event_type,
                    event_data,
                    created_at_ms
                FROM evidence_events
                WHERE event_type IN (
                    'SLA_BREACHED',
                    'SLA_REASSIGNED',
                    'SLA_HARD_ESCALATION',
                    'SLA_PREDICTED_BREACH',
                    'CASE_PRIORITY_BUMP'
                )
                ORDER BY created_at_ms DESC
                LIMIT ?
                """,
                (limit,)
            ).fetchall()

        return [
            {
                "evidence_id": r[0],
                "event_type": r[1],
                "event_data": r[2],
                "created_at_ms": r[3],
            }
            for r in rows
        ]

    def get_worker_scaling_snapshot(self):

        now_ms = int(time.time() * 1000)

        with self._connect() as con:

            pending = con.execute(
                """
                SELECT COUNT(*)
                FROM scan_queue
                WHERE status='PENDING'
                """
            ).fetchone()[0]

            processing = con.execute(
                """
                SELECT COUNT(*)
                FROM scan_queue
                WHERE status='PROCESSING'
                """
            ).fetchone()[0]

            stuck = con.execute(
                """
                SELECT COUNT(*)
                FROM scan_queue
                WHERE status='PROCESSING'
                AND started_at_ms IS NOT NULL
                AND ? - started_at_ms > 600000
                """,
                (now_ms,)
            ).fetchone()[0]

            active_workers = con.execute(
                """
                SELECT COUNT(*)
                FROM worker_heartbeats
                WHERE ? - last_seen_ms < 120000
                """,
                (now_ms,)
            ).fetchone()[0]

        try:
            predictions = self.predict_sla_breaches()
        except Exception:
            predictions = []

        predicted = len(predictions)

        base_workers = 1
        recommended_workers = base_workers

        if pending > 0:
            recommended_workers = max(
                recommended_workers,
                min(5, 1 + (pending // 5))
            )

        if predicted > 0:
            recommended_workers = max(
                recommended_workers,
                min(8, 2 + predicted)
            )

        if stuck > 0:
            recommended_workers = max(
                recommended_workers,
                min(10, 2 + stuck)
            )

        should_scale_up = recommended_workers > active_workers

        should_scale_down = (
                active_workers > recommended_workers
                and pending == 0
                and predicted == 0
        )

        if should_scale_up:

            reason = (
                f"Scale up recommended: "
                f"pending={pending}, "
                f"predicted={predicted}, "
                f"stuck={stuck}."
            )

        elif should_scale_down:

            reason = (
                f"Scale down may be safe: "
                f"active_workers={active_workers}, "
                f"recommended={recommended_workers}."
            )

        else:

            reason = (
                "Worker capacity is aligned "
                "with current queue pressure."
            )

        return {
            "pending": pending,
            "processing": processing,
            "stuck": stuck,
            "predicted": predicted,
            "active_workers": active_workers,
            "recommended_workers": recommended_workers,
            "should_scale_up": should_scale_up,
            "should_scale_down": should_scale_down,
            "reason": reason,
        }

    # =========================================================
    # DELETE SCAN JOB
    # =========================================================

    def delete_scan_job(self, job_id):

        try:

            with self._connect() as con:

                # -----------------------------------------
                # OPTIONAL: LOAD JOB FIRST
                # -----------------------------------------

                row = con.execute(
                    """
                    SELECT id, status
                    FROM scan_queue
                    WHERE id=?
                    """,
                    (job_id,)
                ).fetchone()

                if not row:
                    return False

                status = row[1]

                # -----------------------------------------
                # SAFETY CHECK
                # -----------------------------------------

                if status in ("PROCESSING", "RUNNING"):
                    raise Exception(
                        f"Cannot delete active job: {job_id}"
                    )

                # -----------------------------------------
                # DELETE
                # -----------------------------------------

                con.execute(
                    """
                    DELETE FROM scan_queue
                    WHERE id=?
                    """,
                    (job_id,)
                )

                con.commit()

            print(f"🗑️ Deleted scan job: {job_id}")

            return True

        except Exception as e:

            print(f"[LEDGER][DELETE JOB ERROR] {e}")

            raise









