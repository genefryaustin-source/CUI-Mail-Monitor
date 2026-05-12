# core/process.py

"""
PRIMARY SCAN ORCHESTRATOR

This is the ONLY place that should:

✔ call ingestion
✔ call extraction
✔ call classification
✔ write evidence
✔ update ledger
✔ generate manifest
"""

from __future__ import annotations

from uuid import uuid4
from typing import Dict, Any, List

from core.ingest.gmail_ingest import fetch_attachments, build_gmail_query
from core.extract.extract import extract_text_from_bytes
from core.classify.detect import detect_cui

from core.storage.factory import build_storage
from core.storage.interfaces import CustodyEvent, now_utc_epoch_ms, Manifest


def run_scan_pipeline(
    provider: str,
    monitored_mailbox: str,
    lookback_hours: int,
    attachments_only: bool,
    max_messages: int,
    run_id: str | None = None,
) -> Dict[str, Any]:

    provider_norm = (provider or "").lower()

    if not run_id:
        run_id = str(uuid4())

    started = now_utc_epoch_ms()
    storage = build_storage()

    findings: List[Dict[str, Any]] = []

    messages_scanned = 0
    attachments_scanned = 0
    cui_flagged = 0

    if provider_norm.startswith("gmail"):
        # ✅ Do NOT pass monitored_mailbox here; query builder doesn’t need it for OAuth.
        query = build_gmail_query(
            lookback_hours=int(lookback_hours),
            attachments_only=bool(attachments_only),
        )

        # ✅ OK to pass monitored_mailbox to fetcher (future delegated/journal support)
        email_items = fetch_attachments(
            query=query,
            max_messages=int(max_messages),
            monitored_mailbox=monitored_mailbox,
        )
    else:
        raise ValueError(f"Unsupported provider: {provider}")

    messages_scanned = len(email_items)

    for message in email_items:
        attachments = message.get("attachments", []) or []

        for attachment in attachments:
            attachments_scanned += 1

            blob: bytes = attachment["bytes"]
            filename: str = attachment.get("filename") or "attachment.bin"
            content_type: str = attachment.get("content_type") or "application/octet-stream"

            # Store raw evidence first
            record = storage.vault.put_bytes(
                data=blob,
                suggested_name=filename,
                content_type=content_type,
                metadata={
                    "provider": provider,
                    "mailbox": monitored_mailbox,
                    "run_id": run_id,
                },
            )
            storage.ledger.upsert_evidence_record(record)

            storage.ledger.append_event(
                CustodyEvent(
                    run_id=run_id,
                    evidence_id=record.evidence_id,
                    event_type="INGESTED",
                    actor="system",
                    timestamp_ms=now_utc_epoch_ms(),
                    details={"filename": filename, "provider": provider},
                )
            )

            # Text extraction
            try:
                extracted_text = extract_text_from_bytes(blob, filename=filename)
                storage.ledger.append_event(
                    CustodyEvent(
                        run_id=run_id,
                        evidence_id=record.evidence_id,
                        event_type="TEXT_EXTRACTED",
                        actor="system",
                        timestamp_ms=now_utc_epoch_ms(),
                    )
                )
            except Exception as e:
                storage.ledger.append_event(
                    CustodyEvent(
                        run_id=run_id,
                        evidence_id=record.evidence_id,
                        event_type="EXTRACTION_FAILED",
                        actor="system",
                        timestamp_ms=now_utc_epoch_ms(),
                        details={"error": str(e)},
                    )
                )
                continue

            # CUI detection
            try:
                detection = detect_cui(extracted_text)
                if detection.get("cui_detected"):
                    cui_flagged += 1

                storage.ledger.append_event(
                    CustodyEvent(
                        run_id=run_id,
                        evidence_id=record.evidence_id,
                        event_type="CLASSIFIED",
                        actor="system",
                        timestamp_ms=now_utc_epoch_ms(),
                        details=detection,
                    )
                )

                findings.append(
                    {
                        "evidence_id": record.evidence_id,
                        "filename": filename,
                        "sha256": record.sha256,
                        "cui_detected": bool(detection.get("cui_detected")),
                        "categories": detection.get("categories", []) or [],
                        "confidence": float(detection.get("confidence", 0) or 0),
                    }
                )

            except Exception as e:
                storage.ledger.append_event(
                    CustodyEvent(
                        run_id=run_id,
                        evidence_id=record.evidence_id,
                        event_type="CLASSIFICATION_FAILED",
                        actor="system",
                        timestamp_ms=now_utc_epoch_ms(),
                        details={"error": str(e)},
                    )
                )

    manifest = Manifest(
        run_id=run_id,
        provider=provider,
        mailbox=monitored_mailbox,
        started_at_ms=started,
        completed_at_ms=now_utc_epoch_ms(),
        messages_scanned=messages_scanned,
        attachments_scanned=attachments_scanned,
        cui_flagged=cui_flagged,
    )

    storage.ledger.write_manifest(manifest)

    return {
        "run_id": run_id,
        "messages_scanned": messages_scanned,
        "attachments_scanned": attachments_scanned,
        "cui_flagged": cui_flagged,
        "findings": findings,
        "summary": {
            "run_id": run_id,
            "messages_scanned": messages_scanned,
            "attachments_scanned": attachments_scanned,
            "cui_flagged": cui_flagged,
        },
    }












