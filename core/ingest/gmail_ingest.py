# core/ingest/gmail_ingest.py

from __future__ import annotations

from typing import List, Dict, Any, Optional
import base64

from core.ingest.gmail_auth import get_gmail_service


# ---------------------------------------------------------
# QUERY BUILDER (CONTRACT-STABLE)
# ---------------------------------------------------------

def build_gmail_query(
    lookback_hours: int,
    attachments_only: bool = True,
    monitored_mailbox: Optional[str] = None,
    **kwargs,
) -> str:
    """
    Build a Gmail search query.

    IMPORTANT:
    - Accepts monitored_mailbox for future delegated/journal mailbox patterns.
      For OAuth userId="me", this is informational today.
    - Accepts **kwargs for forward compatibility (never break pipeline again).
    """
    q_parts = [f"newer_than:{int(lookback_hours)}h"]

    if attachments_only:
        q_parts.append("has:attachment")

    # NOTE: monitored_mailbox is intentionally not used for OAuth "me".
    # Future: if you implement delegated mailboxes or Gmail "to:" filters,
    # you can incorporate it here safely.

    return " ".join(q_parts)


# ---------------------------------------------------------
# ATTACHMENT FETCHER (CONTRACT-STABLE)
# ---------------------------------------------------------

def fetch_attachments(
    query: str,
    max_messages: int = 100,
    monitored_mailbox: Optional[str] = None,
    **kwargs,
) -> List[Dict[str, Any]]:
    """
    Fetch attachments from Gmail using OAuth credentials.

    CONTRACT:
    - Accepts monitored_mailbox (unused for userId="me" OAuth).
    - Accepts **kwargs so refactors don't break callers.
    """

    service = get_gmail_service()

    resp = (
        service.users()
        .messages()
        .list(
            userId="me",
            q=query,
            maxResults=int(max_messages),
        )
        .execute()
    )

    messages = resp.get("messages", []) or []
    results: List[Dict[str, Any]] = []

    for m in messages:
        msg_id = m.get("id")
        if not msg_id:
            continue

        msg = (
            service.users()
            .messages()
            .get(userId="me", id=msg_id, format="full")
            .execute()
        )

        payload = msg.get("payload", {}) or {}
        parts = payload.get("parts", []) or []

        attachments: List[Dict[str, Any]] = []

        for part in parts:
            filename = part.get("filename") or ""
            if not filename:
                continue

            body = part.get("body", {}) or {}
            attachment_id = body.get("attachmentId")
            if not attachment_id:
                continue

            att = (
                service.users()
                .messages()
                .attachments()
                .get(userId="me", messageId=msg_id, id=attachment_id)
                .execute()
            )

            data_b64 = att.get("data")
            if not data_b64:
                continue

            blob = base64.urlsafe_b64decode(data_b64.encode("utf-8"))

            attachments.append(
                {
                    "filename": filename,
                    "bytes": blob,
                    "content_type": part.get("mimeType") or "application/octet-stream",
                }
            )

        results.append(
            {
                "message_id": msg_id,
                "attachments": attachments,
            }
        )

    return results
# ---------------------------------------------------------
# PIPELINE ENTRYPOINT (REQUIRED)
# ---------------------------------------------------------

def fetch_emails(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Pipeline-compatible wrapper.
    Converts config → query → attachments → normalized email objects.
    """

    query = build_gmail_query(
        lookback_hours=int(config.get("lookback_hours", 24)),
        attachments_only=bool(config.get("attachments_only", True)),
        monitored_mailbox=config.get("mailbox"),
    )

    raw = fetch_attachments(
        query=query,
        max_messages=int(config.get("max_messages", 100)),
        monitored_mailbox=config.get("mailbox"),
    )

    # Normalize to pipeline format
    emails = []

    for r in raw:
        emails.append({
            "id": r.get("message_id"),
            "body": f"{len(r.get('attachments', []))} attachments",
            "attachments": r.get("attachments", []),
        })

    return emails







