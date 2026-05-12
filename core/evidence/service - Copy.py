from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, Optional, List

from core.evidence.custody import utc_now_iso
from core.storage.interfaces import (
    EvidenceRecord,
    CustodyEvent,
    now_utc_epoch_ms,
    sha256_bytes,
    Ledger,
)
from core.storage.local_vault import LocalVault
from core.storage.sqlite_ledger import SQLiteLedger


# -------------------------------------------------------
# CONFIG
# -------------------------------------------------------

@dataclass(frozen=True)
class EvidenceServiceConfig:
    storage_backend: str  # "local" | "s3"
    actor_default: str = "system"


# -------------------------------------------------------
# SERVICE
# -------------------------------------------------------

class EvidenceService:
    """
    EvidenceService is the ONLY layer allowed to:
      - write evidence bytes
      - write custody events
      - verify hashes
      - return bytes to callers

    UI, supervisors, and pipelines must go through this service.
    """

    def __init__(self, vault, ledger: Ledger, cfg: EvidenceServiceConfig):
        self.vault = vault
        self.ledger = ledger
        self.cfg = cfg

    # -------------------------------------------------------
    # FACTORY
    # -------------------------------------------------------

    @staticmethod
    def from_env() -> "EvidenceService":
        backend = (os.getenv("EVIDENCE_VAULT_BACKEND") or "local").lower()

        if backend == "s3":
            from core.storage.s3_vault import S3Vault
            vault = S3Vault()
        else:
            vault = LocalVault()

        ledger = SQLiteLedger()

        cfg = EvidenceServiceConfig(storage_backend=backend)
        return EvidenceService(vault=vault, ledger=ledger, cfg=cfg)

    # -------------------------------------------------------
    # STORE (INGEST)
    # -------------------------------------------------------

    def store_attachment(
        self,
        *,
        run_id: str,
        source: str,
        filename: str,
        content_type: str,
        data: bytes,
        metadata: Optional[Dict[str, Any]] = None,
        actor: Optional[str] = None,
    ) -> EvidenceRecord:
        if not data:
            raise ValueError("data is required")

        actor_name = actor or self.cfg.actor_default

        meta = dict(metadata or {})
        meta.update({
            "run_id": run_id,
            "source": source,
            "filename": filename,
            "content_type": content_type,
            "created_utc": utc_now_iso(),
        })

        # 1️⃣ Write bytes to vault
        record = self.vault.put_bytes(
            data=data,
            suggested_name=filename or "attachment.bin",
            content_type=content_type or "application/octet-stream",
            metadata=meta,
        )

        # 2️⃣ Write immutable ledger record
        self.ledger.upsert_evidence_record(record)

        # 3️⃣ Custody events (append-only)
        ts = now_utc_epoch_ms()

        self.ledger.append_event(
            CustodyEvent(
                run_id=run_id,
                evidence_id=record.evidence_id,
                event_type="INGESTED",
                actor=actor_name,
                timestamp_ms=ts,
                details={"source": source, "filename": filename},
            )
        )

        self.ledger.append_event(
            CustodyEvent(
                run_id=run_id,
                evidence_id=record.evidence_id,
                event_type="HASHED",
                actor=actor_name,
                timestamp_ms=now_utc_epoch_ms(),
                details={"sha256": record.sha256},
            )
        )

        self.ledger.append_event(
            CustodyEvent(
                run_id=run_id,
                evidence_id=record.evidence_id,
                event_type="STORED",
                actor=actor_name,
                timestamp_ms=now_utc_epoch_ms(),
                details={
                    "backend": getattr(self.vault, "backend_name", "local"),
                    "uri": record.storage_uri,
                },
            )
        )

        return record

    # -------------------------------------------------------
    # VERIFY (NON-DESTRUCTIVE)
    # -------------------------------------------------------

    def verify_integrity(self, evidence_id: str) -> Dict[str, Any]:
        record = self.ledger.get_evidence_record(evidence_id)
        if not record:
            return {"verified": False, "error": "Evidence not found"}

        try:
            data = self.vault.open_bytes(evidence_id=evidence_id)
            computed_sha = sha256_bytes(data)

            return {
                "verified": computed_sha == record.sha256,
                "expected_sha256": record.sha256,
                "computed_sha256": computed_sha,
            }

        except Exception as e:
            return {"verified": False, "error": str(e)}

    # -------------------------------------------------------
    # VERIFY + DOWNLOAD (STRICT)
    # -------------------------------------------------------

    def auto_verify_and_get_bytes(self, evidence_id: str) -> bytes:
        """
        Hash-verifies evidence BEFORE returning bytes.
        Used by Evidence Viewer + exports.
        """

        record = self.ledger.get_evidence_record(evidence_id)
        if not record:
            raise RuntimeError("Evidence not found")

        data = self.vault.open_bytes(evidence_id=evidence_id)
        actual_sha = sha256_bytes(data)
        verified = actual_sha == record.sha256

        self.ledger.append_event(
            CustodyEvent(
                run_id=record.metadata.get("run_id", "unknown"),
                evidence_id=evidence_id,
                event_type="VERIFIED_OK" if verified else "VERIFIED_FAILED",
                actor="system:auto_verify",
                timestamp_ms=now_utc_epoch_ms(),
                details={
                    "expected_sha256": record.sha256,
                    "actual_sha256": actual_sha,
                },
            )
        )

        if not verified:
            raise RuntimeError(
                "🚨 HASH MISMATCH — Evidence may be corrupted or tampered with."
            )

        return data

    # -------------------------------------------------------
    # READ-ONLY HELPERS
    # -------------------------------------------------------

    def get_attachment_bytes(self, evidence_id: str) -> bytes:
        return self.vault.open_bytes(evidence_id=evidence_id)

    def list_custody(self, evidence_id: str) -> List[Dict[str, Any]]:
        return self.ledger.list_events_for_evidence(evidence_id)
