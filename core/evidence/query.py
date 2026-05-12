# core/evidence/query.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def _ms_to_iso(ms: Optional[int]) -> str:
    if not ms:
        return ""
    try:
        return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc).isoformat()
    except Exception:
        return ""


@dataclass(frozen=True)
class RunRow:
    run_id: str
    provider: str
    mailbox: str
    started_at_ms: int
    completed_at_ms: int
    messages_scanned: int
    attachments_scanned: int
    cui_flagged: int

    @property
    def started_at_utc(self) -> str:
        return _ms_to_iso(self.started_at_ms)

    @property
    def completed_at_utc(self) -> str:
        return _ms_to_iso(self.completed_at_ms)


class EvidenceQueryService:
    """
    Read-only query façade for the forensic ledger.

    UI should ONLY call this layer.
    """

    def __init__(self, ledger: Any):
        self.ledger = ledger

    # ---------------------------
    # Runs
    # ---------------------------

    def list_recent_runs(self, limit: int = 25) -> List[Dict[str, Any]]:
        if not hasattr(self.ledger, "list_recent_runs"):
            return []
        rows = self.ledger.list_recent_runs(limit=int(limit)) or []
        out: List[Dict[str, Any]] = []
        for r in rows:
            run = RunRow(
                run_id=str(r.get("run_id", "")),
                provider=str(r.get("provider", "")),
                mailbox=str(r.get("mailbox", "")),
                started_at_ms=int(r.get("started_at_ms") or 0),
                completed_at_ms=int(r.get("completed_at_ms") or 0),
                messages_scanned=int(r.get("messages_scanned") or 0),
                attachments_scanned=int(r.get("attachments_scanned") or 0),
                cui_flagged=int(r.get("cui_flagged") or 0),
            )
            out.append(
                {
                    "run_id": run.run_id,
                    "provider": run.provider,
                    "mailbox": run.mailbox,
                    "started_at_ms": run.started_at_ms,
                    "completed_at_ms": run.completed_at_ms,
                    "started_at_utc": run.started_at_utc,
                    "completed_at_utc": run.completed_at_utc,
                    "messages_scanned": run.messages_scanned,
                    "attachments_scanned": run.attachments_scanned,
                    "cui_flagged": run.cui_flagged,
                }
            )
        return out

    def load_manifest(self, run_id: str) -> Dict[str, Any]:
        if not hasattr(self.ledger, "load_manifest"):
            return {}
        m = self.ledger.load_manifest(run_id)
        return m if isinstance(m, dict) else {}

    def load_run_summary(self, run_id: str) -> Dict[str, Any]:
        manifest = self.load_manifest(run_id)
        if not manifest:
            return {}

        return {
            "run_id": manifest.get("run_id", run_id),
            "provider": manifest.get("provider", ""),
            "mailbox": manifest.get("mailbox", ""),
            "started_at_ms": manifest.get("started_at_ms", 0),
            "completed_at_ms": manifest.get("completed_at_ms", 0),
            "started_at_utc": _ms_to_iso(manifest.get("started_at_ms")),
            "completed_at_utc": _ms_to_iso(manifest.get("completed_at_ms")),
            "messages_scanned": manifest.get("messages_scanned", 0),
            "attachments_scanned": manifest.get("attachments_scanned", 0),
            "cui_flagged": manifest.get("cui_flagged", 0),
        }

    # ---------------------------
    # Evidence
    # ---------------------------

    def list_evidence_for_run(self, run_id: str) -> List[Dict[str, Any]]:
        if not hasattr(self.ledger, "list_evidence_for_run"):
            return []
        items = self.ledger.list_evidence_for_run(run_id) or []
        return items if isinstance(items, list) else []

    def load_evidence_record(self, evidence_id: str) -> Dict[str, Any]:
        if not hasattr(self.ledger, "get_evidence_record"):
            return {}
        r = self.ledger.get_evidence_record(evidence_id)
        return r if isinstance(r, dict) else {}

    # ---------------------------
    # Custody events
    # ---------------------------

    def list_events_for_run(self, run_id: str, limit: int = 500) -> List[Dict[str, Any]]:
        if not hasattr(self.ledger, "list_events"):
            return []
        ev = self.ledger.list_events(run_id, limit=int(limit)) or []
        return ev if isinstance(ev, list) else []

    def list_events_for_evidence(self, evidence_id: str, limit: int = 500) -> List[Dict[str, Any]]:
        if not hasattr(self.ledger, "list_events_for_evidence"):
            return []

        # 🔥 FIX: remove limit from ledger call
        ev = self.ledger.list_events_for_evidence(evidence_id) or []

        # 🔥 apply limit safely here instead
        if isinstance(ev, list):
            ev = ev[:int(limit)]
        else:
            ev = []

        out: List[Dict[str, Any]] = []
        for e in ev:
            ts = e.get("timestamp_ms")
            out.append({**e, "timestamp_utc": _ms_to_iso(ts)})

        return out


def build_query_service(storage: Any) -> EvidenceQueryService:
    ledger = getattr(storage, "ledger", None)
    return EvidenceQueryService(ledger=ledger)
