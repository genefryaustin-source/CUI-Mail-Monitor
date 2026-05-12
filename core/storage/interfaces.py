# core/storage/interfaces.py
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Dict, Optional, Protocol, List
import json
import time


from core.utils.hash_utils import sha256_bytes_hex
def now_utc_epoch_ms() -> int:
    return int(time.time() * 1000)





def stable_json_dumps(obj: Any) -> str:
    """Deterministic JSON for hashing / audit stability."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


@dataclass(frozen=True)
class EvidenceRecord:
    evidence_id: str           # deterministic id (we use sha256)
    sha256: str
    size_bytes: int
    content_type: str
    storage_uri: str           # local path or s3://bucket/key
    suggested_name: str
    created_at_ms: int
    metadata: Dict[str, Any]


@dataclass(frozen=True)
class CustodyEvent:
    run_id: str
    evidence_id: str
    event_type: str
    actor: str
    timestamp_ms: int
    details: Dict[str, Any] | None = None


@dataclass(frozen=True)
class Manifest:
    run_id: str
    provider: str
    mailbox: str
    started_at_ms: int
    completed_at_ms: int
    messages_scanned: int
    attachments_scanned: int
    cui_flagged: int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class BlobVault(Protocol):
    """Evidence blob storage backend (local filesystem or S3)."""

    backend_name: str

    def put_bytes(
        self,
        *,
        data: bytes,
        suggested_name: str,
        content_type: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> EvidenceRecord: ...

    def open_bytes(self, *, evidence_id: str) -> bytes: ...

    def exists(self, *, evidence_id: str) -> bool: ...


class Ledger(Protocol):
    def init_schema(self) -> None: ...

    def upsert_run(self, run_id: str, provider: str, mailbox: str, started_at_ms: int) -> None: ...
    def finish_run(self, run_id: str, completed_at_ms: int, messages_scanned: int, attachments_scanned: int, cui_flagged: int) -> None: ...

    def upsert_evidence_record(self, record: EvidenceRecord) -> None: ...
    def append_event(self, event: CustodyEvent) -> None: ...
    def write_manifest(self, manifest: Manifest) -> None: ...

    # Query (for UI)
    def list_recent_runs(self, limit: int = 25) -> List[Dict[str, Any]]: ...
    def load_manifest(self, run_id: str) -> Optional[Dict[str, Any]]: ...
    def list_events(self, run_id: str, limit: int = 500) -> List[Dict[str, Any]]: ...


@dataclass(frozen=True)
class StorageBundle:
    vault: BlobVault
    ledger: Ledger
