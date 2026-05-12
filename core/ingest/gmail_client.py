
# ----------------------------------
# 🔐 LOAD OR REFRESH CREDENTIALS
# ----------------------------------
from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
import os
import streamlit as st
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


# ----------------------------------
# 🔐 LOAD OR REFRESH TOKEN FROM DB
# ----------------------------------
def get_gmail_credentials(storage, mailbox: str):
    ledger = storage.ledger

    token = ledger.get_oauth_token("gmail", mailbox)

    if not token:
        raise RuntimeError(f"No Gmail token found for {mailbox}. Connect Gmail first.")

    creds = Credentials(
        token=token["access_token"],
        refresh_token=token.get("refresh_token"),
        token_uri=token.get("token_uri"),
        client_id=token.get("client_id"),
        client_secret=token.get("client_secret"),
        scopes=token.get("scopes", "").split(",") if token.get("scopes") else SCOPES,
    )

    # 🔄 Refresh if expired
    if creds.expired:
        if not creds.refresh_token:
            raise RuntimeError("Missing refresh_token. Reconnect Gmail.")

        creds.refresh(Request())

        expiry_ts = int(creds.expiry.timestamp()) if creds.expiry else None

        ledger.upsert_oauth_token(
            provider="gmail",
            mailbox=mailbox,
            access_token=creds.token,
            refresh_token=creds.refresh_token,
            token_uri=creds.token_uri,
            client_id=creds.client_id,
            client_secret=creds.client_secret,
            scopes=",".join(creds.scopes or []),
            expiry_ts=expiry_ts,
        )

    return creds


# ----------------------------------
# 🚀 BUILD GMAIL SERVICE
# ----------------------------------
def build_service_from_db(storage, mailbox: str):
    creds = get_gmail_credentials(storage, mailbox)
    return build("gmail", "v1", credentials=creds)


# ----------------------------------
# 🔗 GROK-STYLE OAUTH FLOW (FIXED)
# ----------------------------------
def run_oauth_flow_and_store(storage, mailbox: str):
    ledger = storage.ledger

    print(f"🔥 Starting OAuth for mailbox: {mailbox}")



    client_config = {
        "web": {
            "client_id": st.secrets["gmail_oauth"]["client_id"],
            "project_id": st.secrets["gmail_oauth"]["project_id"],
            "auth_uri": st.secrets["gmail_oauth"]["auth_uri"],
            "token_uri": st.secrets["gmail_oauth"]["token_uri"],
            "auth_provider_x509_cert_url":
                st.secrets["gmail_oauth"]["auth_provider_x509_cert_url"],
            "client_secret":
                st.secrets["gmail_oauth"]["client_secret"],
            "redirect_uris":
                st.secrets["gmail_oauth"]["redirect_uris"],
        }
    }

    flow = InstalledAppFlow.from_client_config(
        client_config,
        SCOPES
    )

    creds = flow.run_local_server(
        host="127.0.0.1",
        port=8765,
        open_browser=True,
        redirect_uri_trailing_slash=False
    )

    print("🔥 OAuth returned creds:", creds)

    if not creds:
        raise RuntimeError("OAuth failed. No credentials returned.")

    if not creds.refresh_token:
        raise RuntimeError("No refresh_token returned. Remove Google app access and retry.")

    expiry_ts = int(creds.expiry.timestamp()) if creds.expiry else None

    print("🔥 Saving token to DB...")

    ledger.upsert_oauth_token(
        provider="gmail",
        mailbox=mailbox,
        access_token=creds.token,
        refresh_token=creds.refresh_token,
        token_uri=creds.token_uri,
        client_id=creds.client_id,
        client_secret=creds.client_secret,
        scopes=",".join(creds.scopes or []),
        expiry_ts=expiry_ts,
    )

    print("🔥 Token saved successfully")

    return creds




# ----------------------------------
# 💾 STORE TOKEN
# ----------------------------------
def store_credentials(storage, mailbox, creds):
    if not creds:
        raise ValueError("No credentials provided to store.")

    ledger = storage.ledger

    expiry_ts = int(creds.expiry.timestamp()) if creds.expiry else None


# ----------------------------------
# 📩 GMAIL OPERATIONS
# ----------------------------------
def list_messages(service, max_results=100, query=None):
    response = service.users().messages().list(
        userId="me",
        maxResults=max_results,
        q=query,
    ).execute()

    return [m["id"] for m in response.get("messages", [])]


def get_message(service, msg_id):
    return service.users().messages().get(userId="me", id=msg_id).execute()


def get_attachment(service, msg_id, attach_id):
    import base64

    att = service.users().messages().attachments().get(
        userId="me",
        messageId=msg_id,
        id=attach_id,
    ).execute()

    return base64.urlsafe_b64decode(att["data"])