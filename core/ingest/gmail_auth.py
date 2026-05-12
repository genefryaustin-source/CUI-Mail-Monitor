# core/ingest/gmail_auth.py

"""
GMAIL AUTHENTICATION

✔ Works locally (env vars)
✔ Works on Streamlit Cloud
✔ No direct dependency on Streamlit in core logic
✔ FedRAMP-safe separation
"""

from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials

from core.utils.secrets_loader import get_secret

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


def get_gmail_service():
    """
    Interactive OAuth for DEV / TEST.

    Production should switch to service accounts later.
    """

    client_id = get_secret("GMAIL_CLIENT_ID")
    client_secret = get_secret("GMAIL_CLIENT_SECRET")
    redirect_uri = get_secret("GMAIL_REDIRECT_URI", required=False)

    if not client_id or not client_secret:
        raise RuntimeError(
            "Missing Gmail OAuth secrets. "
            "Set GMAIL_CLIENT_ID and GMAIL_CLIENT_SECRET."
        )

    flow = InstalledAppFlow.from_client_config(
        {
            "installed": {
                "client_id": client_id,
                "client_secret": client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [redirect_uri] if redirect_uri else [],
            }
        },
        scopes=SCOPES,
    )
    print("DEBUG CLIENT ID:", client_id)
    print("DEBUG CLIENT SECRET:", client_secret[:6] if client_secret else None)
    #creds = flow.run_local_server(port=0)
    creds = flow.run_local_server(port=8765)

    return build("gmail", "v1", credentials=creds)
