"""
Evidence manifest + chain-of-custody (Phase 1.5).

This module builds a deterministic "Evidence Manifest" for each scan run.
The manifest is intentionally *metadata only* (no attachment bytes), and is
safe to export for audit / review.

Design goals:
- Deterministic ordering (stable across runs given identical inputs)
- Strong hashing (sha256) per attachment
- Minimal, extensible chain-of-custody event model
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import json
from typing import Any, Dict, List, Optional, Tuple

from core.utils.hash_utils import sha256_bytes_hex

HASH_ALG = "sha256"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()





def _canonical_json_bytes(obj: Any) -> bytes:
    """
    Canonical JSON (stable ordering):
    - sort_keys=True
    - separators eliminate whitespace
    """
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _safe_int(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except Exception:
        return default


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)




def _evidence_id(message_id: str, attachment_id: str, sha256_hex: str) -> str:
    raw = f"{message_id}:{attachment_id}:{sha256_hex}".encode("utf-8")
    return sha256_bytes_hex(raw)[:32]


def build_manifest(
    *,
    run_id: str,
    provider: str,
    monitored_mailbox: str,
    query: str,
    window_start: datetime,
    email_items: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Build a metadata-only manifest from the ingested email_items.
    """
    window_start = _ensure_utc(window_start)
    window_end = datetime.now(timezone.utc)

    evidence: List[Dict[str, Any]] = []

    for msg in (email_items or []):
        message_id = str(msg.get("message_id", ""))
        thread_id = str(msg.get("thread_id", ""))
        subject = str(msg.get("subject", ""))[:500]
        from_ = str(msg.get("from", ""))[:500]
        to_ = str(msg.get("to", ""))[:500]
        date = str(msg.get("date", ""))[:500]

        attachments = msg.get("attachments") or []
        for att in attachments:
            attachment_id = str(att.get("attachment_id", ""))
            filename = str(att.get("filename", ""))[:512]
            mime_type = str(att.get("mime_type", ""))[:255]
            size_bytes = _safe_int(att.get("size"), default=0)

            data = att.get("data") or b""
            if not isinstance(data, (bytes, bytearray)):
                # Defensive: if something passed a str, hash its bytes
                data = str(data).encode("utf-8")

            sha = sha256_bytes_hex(bytes(data))
            eid = _evidence_id(message_id, attachment_id, sha)

            evidence.append(
                {
                    "evidence_id": eid,
                    "source": {
                        "provider": provider,
                        "message_id": message_id,
                        "thread_id": thread_id,
                        "mailbox": monitored_mailbox,
                        "headers": {
                            "from": from_,
                            "to": to_,
                            "subject": subject,
                            "date": date,
                        },
                    },
                    "attachment": {
                        "attachment_id": attachment_id,
                        "filename": filename,
                        "mime_type": mime_type,
                        "size_bytes": size_bytes if size_bytes > 0 else len(data),
                    },
                    "hash": {
                        "algorithm": HASH_ALG,
                        "value": sha,
                    },
                    "timestamps": {
                        "retrieved_utc": _utc_now_iso(),
                    },
                    "storage": {
                        "uri": None,  # Phase 2+: s3://... or file://...
                    },
                }
            )

    # Deterministic ordering
    evidence.sort(key=lambda x: (x["hash"]["value"], x["attachment"]["filename"], x["evidence_id"]))

    # Minimal chain-of-custody for Phase 1.5


    chain_events = [
        {
            "event_id": sha256_bytes_hex(
                f"{run_id}:manifest_created".encode("utf-8")
            )[:24],
            "event_type": "manifest_created",
            "actor": "system",
            "timestamp_utc": _utc_now_iso(),
            "details": {
                "provider": provider,
                "mailbox": monitored_mailbox,
            },
        }
    ]

    manifest: Dict[str, Any] = {
        "schema": {
            "name": "cui_mail_monitor_evidence_manifest",
            "version": "1.5",
        },
        "run_id": run_id,
        "generated_utc": _utc_now_iso(),
        "provider": provider,
        "monitored_mailbox": monitored_mailbox,
        "query": query,
        "window": {
            "start_utc": window_start.isoformat(),
            "end_utc": window_end.isoformat(),
        },
        "counts": {
            "messages_scanned": _safe_int(len(email_items or []), 0),
            "attachments_scanned": _safe_int(len(evidence), 0),
        },
        "hashing": {
            "algorithm": HASH_ALG,
        },
        "evidence": evidence,
        "chain_of_custody": {
            "events": chain_events,
        },
    }

    return manifest


def export_manifest_json_bytes(manifest: dict) -> bytes:
    import json
    return json.dumps(
        manifest,
        sort_keys=True,
        default=str
    ).encode("utf-8")

    return _canonical_json_bytes(manifest)

