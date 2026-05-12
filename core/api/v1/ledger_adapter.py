from __future__ import annotations

from typing import Any, Dict, List, Optional

from core.api.v1.contracts import LedgerV1


class SQLiteLedgerV1Adapter(LedgerV1):
    """
    Frozen v1 adapter around your existing SQLiteLedger implementation.
    This prevents UI/supervisors from calling SQLiteLedger directly.
    """

    def __init__(self, sqlite_ledger: Any):
        self._l = sqlite_ledger

    # ---------------- Evidence ----------------

    def get_evidence_record(self, evidence_id: str) -> Optional[Dict[str, Any]]:
        rec = self._l.get_evidence_record(evidence_id)
        if rec is None:
            return None
        # Some versions return EvidenceRecord dataclass; normalize to dict
        if isinstance(rec, dict):
            return rec
        return {
            "evidence_id": getattr(rec, "evidence_id", None),
            "sha256": getattr(rec, "sha256", None),
            "size_bytes": getattr(rec, "size_bytes", None),
            "content_type": getattr(rec, "content_type", None),
            "storage_uri": getattr(rec, "storage_uri", None),
            "suggested_name": getattr(rec, "suggested_name", None),
            "created_at_ms": getattr(rec, "created_at_ms", None),
            "metadata": getattr(rec, "metadata", {}) or {},
        }

    def list_events_for_evidence(self, evidence_id: str, limit: int = 500) -> List[Dict[str, Any]]:
        return self._l.list_events_for_evidence(evidence_id, limit=limit)

    # ---------------- Notary ----------------

    def notarize_evidence(
        self,
        *,
        evidence_id: str,
        sha256: str,
        anchor_type: str = "local",
        anchor_ref: Optional[str] = None,
    ) -> None:
        return self._l.notarize_evidence(
            evidence_id=evidence_id,
            sha256=sha256,
            anchor_type=anchor_type,
            anchor_ref=anchor_ref,
        )

    def list_notary_records(self, evidence_id: str) -> List[Dict[str, Any]]:
        return self._l.list_notary_records(evidence_id)

    # ---------------- Supervisor ----------------

    def try_acquire_supervisor_lock(self, leader_id: str, ttl_seconds: int = 120) -> bool:
        return self._l.try_acquire_supervisor_lock(leader_id, ttl_seconds=ttl_seconds)

    def upsert_heartbeat(
        self,
        *,
        worker_id: str,
        leader_id: str,
        status: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        return self._l.upsert_heartbeat(
            worker_id=worker_id,
            leader_id=leader_id,
            status=status,
            details=details or {},
        )

    def list_heartbeats(self, limit: int = 50) -> List[Dict[str, Any]]:
        return self._l.list_heartbeats(limit=limit)

    def get_supervisor_config(self) -> Dict[str, Any]:
        cfg = self._l.get_supervisor_config()
        return cfg if isinstance(cfg, dict) else cfg.__dict__

    def set_supervisor_config(self, *, enabled: bool, interval_seconds: int) -> None:
        return self._l.set_supervisor_config(enabled=enabled, interval_seconds=interval_seconds)

    # ---------------- Queue ----------------

    def enqueue_scan(
        self,
        *,
        provider: str,
        mailbox: str,
        lookback_hours: int,
        attachments_only: bool,
        max_messages: int,
        payload: Optional[Dict[str, Any]] = None,
    ) -> int:
        return self._l.enqueue_scan(
            provider=provider,
            mailbox=mailbox,
            lookback_hours=lookback_hours,
            attachments_only=attachments_only,
            max_messages=max_messages,
            payload=payload,
        )

    def claim_next_scan(self, *, worker_id: str) -> Optional[Dict[str, Any]]:
        return self._l.claim_next_scan(worker_id)

    def mark_scan_done(self, *, job_id: int, run_id: Optional[str] = None) -> None:
        return self._l.mark_scan_done(job_id=job_id, run_id=run_id)

    def mark_scan_failed(self, *, job_id: int, error: str) -> None:
        return self._l.mark_scan_failed(job_id=job_id, error=error)

    def list_queue(self, limit: int = 200) -> List[Dict[str, Any]]:
        return self._l.list_queue(limit=limit)

    # ---------------- Metrics ----------------

    def record_metric(self, name: str, value: float, tags: Optional[Dict[str, Any]] = None) -> None:
        return self._l.record_metric(name, value, tags=tags)

    def list_metrics(self, name: Optional[str] = None, limit: int = 200) -> List[Dict[str, Any]]:
        return self._l.list_metrics(name=name, limit=limit)
