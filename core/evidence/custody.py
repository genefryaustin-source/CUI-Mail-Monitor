from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict

from core.storage.interfaces import CustodyEvent


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def make_event(
    *,
    evidence_id: str,
    run_id: str,
    event_type: str,
    actor: str,
    details: Dict[str, Any] | None = None,
) -> CustodyEvent:
    return CustodyEvent(
        event_id=str(uuid.uuid4()),
        evidence_id=evidence_id,
        run_id=run_id,
        event_type=event_type,
        actor=actor,
        ts_utc=utc_now_iso(),
        details=details or {},
    )
