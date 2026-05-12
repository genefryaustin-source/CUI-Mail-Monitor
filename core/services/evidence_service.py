# core/services/evidence_service.py

from typing import List, Dict, Any
import time

import json
from core.utils.hash_utils import sha256_bytes_hex

def record_evidence(findings: List[Dict[str, Any]]):
    """
    Store findings into vault + evidence_records (correct schema)
    """

    if not findings:
        print("🧾 No findings to record")
        return

    from core.storage.factory import build_storage

    storage = build_storage()
    vault = storage.vault
    ledger = storage.ledger

    now = int(time.time() * 1000)

    with ledger._connect() as con:
        for f in findings:

            # ---------------------------------------
            # 🔹 CREATE RAW EVIDENCE PAYLOAD
            # ---------------------------------------
            raw_bytes = json.dumps(f).encode("utf-8")

            # ---------------------------------------
            # 🔹 HASH
            # ---------------------------------------
            sha256 = sha256_bytes_hex(raw_bytes)

            # ---------------------------------------
            # 🔹 STORE IN VAULT
            # ---------------------------------------
            storage_uri = vault.put_bytes(raw_bytes)

            # ---------------------------------------
            # 🔹 INSERT INTO evidence_records
            # ---------------------------------------
            existing = con.execute("""
                SELECT 1 FROM evidence_records WHERE evidence_id = ?
            """, (sha256,)).fetchone()

            if not existing:
                con.execute("""
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
                """, (
                    sha256,
                    sha256,
                    len(raw_bytes),
                    "application/json",
                    storage_uri,
                    f.get("doc_id", "finding"),
                    now,
                    json.dumps(f),
                ))

            # ---------------------------------------
            # 🔗 CHAIN OF CUSTODY
            # ---------------------------------------
            con.execute("""
                INSERT INTO custody_events (
                    evidence_id,
                    event_type,
                    ts_ms,
                    details_json
                ) VALUES (?, ?, ?, ?)
            """, (
                sha256,
                "INGESTED",
                now,
                json.dumps(f)
            ))

        con.commit()

    print(f"🧾 Stored {len(findings)} evidence records (vault-backed)")