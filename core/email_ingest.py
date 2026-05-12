from datetime import datetime
from typing import List, Dict

from core.ingest.gmail_ingest import gmail_fetch_attachments
from core.ingest.m365_ingest import m365_fetch_attachments
from core.ingest.maildrop_ingest import maildrop_fetch_attachments


def ingest_email_attachments(
    provider: str,
    monitored_mailbox: str | None,
    window_start: datetime,
    max_messages: int,
) -> List[Dict]:
    """
    Returns list of items:
    {
      "source": "gmail" | "m365" | "maildrop",
      "filename": str,
      "filetype": "pdf"|"txt"|...,
      "bytes": bytes,
      "metadata": {...}
    }
    """

    if provider == "Gmail (OAuth Read-only)":
        return gmail_fetch_attachments(
            monitored_mailbox=monitored_mailbox,
            window_start=window_start,
            max_messages=max_messages,
        )

    if provider == "Microsoft 365 (Graph Read-only)":
        return m365_fetch_attachments(
            monitored_mailbox=monitored_mailbox,
            window_start=window_start,
            max_messages=max_messages,
        )

    if provider == "Local Maildrop (.eml)":
        return maildrop_fetch_attachments(
            monitored_mailbox=monitored_mailbox,
            window_start=window_start,
            max_messages=max_messages,
        )

    return []

