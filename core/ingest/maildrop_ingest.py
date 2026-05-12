import os
from datetime import datetime, timezone
from email import policy
from email.parser import BytesParser
from typing import List, Dict

#import streamlit as st
from core.utils.secrets_loader import get_secret


def maildrop_fetch_attachments(
    monitored_mailbox: str | None,
    window_start: datetime,
    max_messages: int,
) -> List[Dict]:
    """
    Reads .eml files from a directory.
    Configure directory in Streamlit secrets as MAILDROP_DIR, or default to ./maildrop.
    """
    maildrop_dir = st.secrets.get("MAILDROP_DIR", "maildrop")
    if not os.path.isdir(maildrop_dir):
        return []

    # newest first
    files = sorted(
        [f for f in os.listdir(maildrop_dir) if f.lower().endswith(".eml")],
        key=lambda x: os.path.getmtime(os.path.join(maildrop_dir, x)),
        reverse=True,
    )

    out = []
    count = 0
    for fname in files:
        if count >= max_messages:
            break

        path = os.path.join(maildrop_dir, fname)
        mtime = datetime.fromtimestamp(os.path.getmtime(path), tz=timezone.utc)
        if mtime < window_start.astimezone(timezone.utc):
            continue

        with open(path, "rb") as f:
            msg = BytesParser(policy=policy.default).parse(f)

        subject = msg.get("subject", "")
        date_hdr = msg.get("date", "")

        for part in msg.iter_attachments():
            filename = part.get_filename()
            if not filename:
                continue
            blob = part.get_payload(decode=True) or b""
            filetype = filename.split(".")[-1].lower() if "." in filename else "unknown"

            out.append(
                {
                    "source": "maildrop",
                    "filename": filename,
                    "filetype": filetype,
                    "bytes": blob,
                    "metadata": {
                        "maildrop_eml": fname,
                        "subject": subject,
                        "date": date_hdr,
                        "monitored_mailbox": monitored_mailbox,
                    },
                }
            )

        count += 1

    return out
