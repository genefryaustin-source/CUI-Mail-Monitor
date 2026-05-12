# core/modules/evidence.py
from __future__ import annotations


from datetime import datetime, timezone
from typing import Any, Dict, List
from core.utils.hash_utils import sha256_bytes_hex




def build_evidence_manifest(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Creates a chain-of-custody style manifest.
    In production: write this to immutable storage (WORM/S3 Object Lock) + sign.
    """
    now = datetime.now(timezone.utc).isoformat()

    manifest: List[Dict[str, Any]] = []
    for idx, it in enumerate(items, start=1):
        b = it.get("bytes") or b""
        if not isinstance(b, (bytes, bytearray)):
            b = str(b).encode("utf-8")
        manifest.append(
            {
                "evidence_id": f"EVI-{idx:06d}",
                "run_id": it.get("run_id"),
                "provider": it.get("provider"),
                "monitored_mailbox": it.get("monitored_mailbox"),
                "message_id": it.get("message_id"),
                "received_utc": it.get("received_utc"),
                "filename": it.get("filename"),
                "content_type": it.get("content_type"),
                "byte_len": len(b),
                "sha256": sha256_bytes_hex(b),
                "collected_utc": now,
                "custody_event": "ingested->hashed",
            }
        )
    return manifest


class EvidenceItem:
    pass


class CustodyEvent:
    pass