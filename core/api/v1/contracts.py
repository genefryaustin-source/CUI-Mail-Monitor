from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Protocol


# ---------------------------
# Value objects
# ---------------------------

@dataclass(frozen=True)
class Heartbeat:
    worker_id: str
    leader_id: str
    status: str
    last_seen_ms: int
    details: Dict[str, Any]


@dataclass(frozen=True)
class NotaryRecord:
    evidence_id: str
    sha256: str
    anchor_type: str
    anchor_ref: Optional[str]
    created_at_ms: int


# ---------------------------
# Frozen v1 Ledger API
# ---------------------------

class LedgerV1(Protocol):
    # Evidence
    def get_evidence_record(self, evidence_id: str) -> Optional[Dict[str, Any]]: ...
    def list_events_for_evidence(self, evidence_id: str, limit: int = 500) -> List[Dict[str, Any]]: ...

    # Notary
    def notarize_evidence(
        self,
        *,
        evidence_id: str,
        sha256: str,
        anchor_type: str = "local",
        anchor_ref: Optional[str] = None,
    ) -> None: ...

    def list_notary_records(self, evidence_id: str) -> List[Dict[str, Any]]: ...

    # Supervisor
    def try_acquire_supervisor_lock(self, leader_id: str, ttl_seconds: int = 120) -> bool: ...
    def upsert_heartbeat(
        self,
        *,
        worker_id: str,
        leader_id: str,
        status: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None: ...
    def list_heartbeats(self, limit: int = 50) -> List[Dict[str, Any]]: ...

    def get_supervisor_config(self) -> Dict[str, Any]: ...
    def set_supervisor_config(self, *, enabled: bool, interval_seconds: int) -> None: ...

    # Queue
    def enqueue_scan(
        self,
        *,
        provider: str,
        mailbox: str,
        lookback_hours: int,
        attachments_only: bool,
        max_messages: int,
        payload: Optional[Dict[str, Any]] = None,
    ) -> int: ...

    def claim_next_scan(self, *, worker_id: str) -> Optional[Dict[str, Any]]: ...
    def mark_scan_done(self, *, job_id: int, run_id: Optional[str] = None) -> None: ...
    def mark_scan_failed(self, *, job_id: int, error: str) -> None: ...
    def list_queue(self, limit: int = 200) -> List[Dict[str, Any]]: ...

    # Metrics
    def record_metric(self, name: str, value: float, tags: Optional[Dict[str, Any]] = None) -> None: ...
    def list_metrics(self, name: Optional[str] = None, limit: int = 200) -> List[Dict[str, Any]]: ...
