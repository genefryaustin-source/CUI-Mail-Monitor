from __future__ import annotations

from datetime import datetime, timedelta, timezone

from core.ingest.gmail_auth import get_gmail_service
from core.ingest.gmail_ingest import (
    fetch_attachments,
    build_gmail_query,
)
from core.evidence.chain_of_custody import build_manifest
from core.classify.detect import classify_attachments


def run_scan_pipeline(
    provider: str,
    monitored_mailbox: str,
    lookback_hours: int,
    max_messages: int,
    attachments_only: bool,
    run_id: str,
):
    """
    End-to-end scan:
      1) authenticate
      2) fetch messages + attachment bytes
      3) classify attachments for potential CUI
      4) build deterministic evidence manifest (Phase 1.5)
    """

    # Gmail auth
    service = get_gmail_service()

    # Compute a single window_start that is used for BOTH query + manifest
    now_utc = datetime.now(timezone.utc)
    window_start = now_utc - timedelta(hours=int(lookback_hours))

    query = build_gmail_query(
        lookback_hours=lookback_hours,
        attachments_only=attachments_only,
        monitored_mailbox=monitored_mailbox,
        window_start=window_start,
    )

    # Ingest attachments (bytes stay in memory for analysis, but are never put in manifest)
    email_items = fetch_attachments(
        service=service,
        query=query,
        max_messages=int(max_messages),
    )

    # Normalize (defensive): ensure every email item has an 'attachments' list
    for item in email_items or []:
        if "attachments" not in item or item["attachments"] is None:
            item["attachments"] = []

    # Classification
    findings = classify_attachments(email_items)

    # Summary counts
    messages_scanned = len(email_items or [])
    emails_with_attachments = sum(1 for x in (email_items or []) if (x.get("attachments") or []))
    attachments_scanned = sum(len(x.get("attachments") or []) for x in (email_items or []))
    cui_flagged = sum(1 for f in findings if f.get("cui_flagged"))

    summary = {
        "run_id": run_id,
        "messages_scanned": messages_scanned,
        "emails_with_attachments": emails_with_attachments,
        "attachments_scanned": attachments_scanned,
        "cui_flagged": cui_flagged,
    }

    # Phase 1.5: Deterministic Evidence Manifest (metadata-only)
    manifest = build_manifest(
        run_id=run_id,
        provider=provider,
        monitored_mailbox=monitored_mailbox,
        query=query,
        window_start=window_start,
        email_items=email_items,
    )

    return {
        "run_id": run_id,
        "query": query,
        "summary": summary,
        "findings": findings,
        "manifest": manifest,
        "downloads": [],
    }









