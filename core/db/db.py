"""core.db.db

SQLite-backed run ledger.

Tables:
- runs(run_id, provider, monitored_mailbox, lookback_start_utc, created_at_utc, summary_json)
- manifests(run_id, manifest_json, created_at_utc)
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_db_path() -> str:
    # Works locally and in Streamlit Cloud.
    # Override via env var if desired.
    return os.getenv("CUI_DB_PATH", os.path.join("data", "cui_mail_monitor.db"))


def get_db() -> sqlite3.Connection:
    path = _default_db_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                provider TEXT,
                monitored_mailbox TEXT,
                lookback_start_utc TEXT,
                created_at_utc TEXT,
                summary_json TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS manifests (
                run_id TEXT PRIMARY KEY,
                manifest_json TEXT,
                created_at_utc TEXT
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def upsert_run(
    run_id: str,
    provider: str,
    monitored_mailbox: str,
    lookback_start_utc: str,
    summary: Dict[str, Any],
) -> None:
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO runs (run_id, provider, monitored_mailbox, lookback_start_utc, created_at_utc, summary_json)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(run_id) DO UPDATE SET
                provider=excluded.provider,
                monitored_mailbox=excluded.monitored_mailbox,
                lookback_start_utc=excluded.lookback_start_utc,
                summary_json=excluded.summary_json
            """,
            (
                run_id,
                provider,
                monitored_mailbox,
                lookback_start_utc,
                _utc_now_iso(),
                json.dumps(summary or {}, ensure_ascii=False),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def replace_manifest(run_id: str, manifest: Any) -> None:
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO manifests (run_id, manifest_json, created_at_utc)
            VALUES (?, ?, ?)
            ON CONFLICT(run_id) DO UPDATE SET
                manifest_json=excluded.manifest_json,
                created_at_utc=excluded.created_at_utc
            """,
            (run_id, json.dumps(manifest, ensure_ascii=False), _utc_now_iso()),
        )
        conn.commit()
    finally:
        conn.close()


def list_recent_runs(limit: int = 25) -> List[Dict[str, Any]]:
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT run_id, provider, monitored_mailbox, lookback_start_utc, created_at_utc
            FROM runs
            ORDER BY created_at_utc DESC
            LIMIT ?
            """,
            (int(limit),),
        )
        rows = cur.fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def load_run_summary(run_id: str) -> Optional[Dict[str, Any]]:
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("SELECT summary_json FROM runs WHERE run_id = ?", (run_id,))
        row = cur.fetchone()
        if not row:
            return None
        return json.loads(row["summary_json"] or "{}")
    finally:
        conn.close()


def load_manifest(run_id: str) -> Optional[Any]:
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("SELECT manifest_json FROM manifests WHERE run_id = ?", (run_id,))
        row = cur.fetchone()
        if not row:
            return None
        return json.loads(row["manifest_json"] or "null")
    finally:
        conn.close()
