# core/modules/m365_ingest.py
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

#import streamlit as st
from core.utils.secrets_loader import get_secret
import requests


def _get_m365_secrets() -> Dict[str, str]:
    m = st.secrets.get("m365", {})
    return {
        "tenant_id": m.get("tenant_id", ""),
        "client_id": m.get("client_id", ""),
        "client_secret": m.get("client_secret", ""),
    }


def _get_token(tenant_id: str, client_id: str, client_secret: str) -> str:
    if not tenant_id or not client_id or not client_secret:
        raise RuntimeError(
            "Missing Microsoft 365 secrets. Add to .streamlit/secrets.toml:\n"
            "[m365]\ntenant_id=\nclient_id=\nclient_secret=\n"
        )

    url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
    data = {
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "client_credentials",
        "scope": "https://graph.microsoft.com/.default",
    }
    r = requests.post(url, data=data, timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]


def m365_fetch_attachments(
    monitored_mailbox: str,
    window_start: datetime,
    max_messages: int,
) -> List[Dict[str, Any]]:
    """
    Minimal scaffold:
    - Acquire app-only token (client credentials)
    - TODO: use Graph to read mailbox messages + attachments (read-only)
    """
    cfg = _get_m365_secrets()
    token = _get_token(cfg["tenant_id"], cfg["client_id"], cfg["client_secret"])

    # Placeholder, so the app doesn't crash:
    # Implement Graph calls here (messages list -> get attachments).
    # Return same structure as gmail_fetch_attachments().
    return [
        {
            "message_id": "m365-placeholder",
            "thread_id": None,
            "received_utc": datetime.now(timezone.utc).isoformat(),
            "subject": "M365 ingestion not implemented yet",
            "from": "system",
            "attachments": [],
        }
    ]
