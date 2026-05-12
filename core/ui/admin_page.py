# core/ui/admin_page.py
from __future__ import annotations

import os
import uuid

import json
import streamlit as st
from core.cases.playbook_loader import seed_playbooks
from core.forensics.export import export_forensic_snapshot
from core.forensics.notary import Notary
import shutil
from core.ingest.gmail_client import run_oauth_flow_and_store
from core.utils.hash_utils import sha256_file_hex
from core.services.imap_service import connect_imap


st.subheader("System Status")

if shutil.which("ots"):
    st.success("🟢 OpenTimestamps: Available")
else:
    st.warning("🟡 OpenTimestamps: Not available (running in fallback mode)")

def _normalize_snapshot_path(raw):
    """
    Handles cases where export returns:
    - string path
    - dict { zip_path, manifest }
    - stringified dict (bad UI state)
    """
    if isinstance(raw, dict):
        return raw.get("zip_path", "")

    if isinstance(raw, str) and raw.startswith("{"):
        try:
            parsed = json.loads(raw.replace("'", '"'))
            return parsed.get("zip_path", raw)
        except Exception:
            return raw

    return raw or ""


def render_admin_page(storage):
    st.title("🛠️ Administration")

    ledger = storage.ledger
    notary = Notary(storage)

    # =========================================================
    # 🧪 FORENSICS (QUICK EXPORT ONLY)
    # =========================================================
    st.subheader("Forensics")

    col1, col2 = st.columns(2)

    with col1:
        if st.button("📦 Quick Export Forensic Snapshot", use_container_width=True):
            result = export_forensic_snapshot(storage)

            if isinstance(result, dict):
                path = result.get("zip_path")
                manifest = result.get("manifest")
            else:
                path = result
                manifest = None

            st.success(f"Snapshot exported: {path}")
            st.session_state["last_snapshot_path"] = path

            if manifest:
                st.caption("Snapshot Manifest")
                st.json(manifest)

    with col2:
        if st.button("⛔ Kill Leader (Failover)", use_container_width=True):
            ok = ledger.clear_supervisor_lock()
            if ok:
                st.success("Leader lock cleared. A new supervisor can acquire leadership.")
            else:
                st.info("No leader lock row found (already clear).")

    # =========================================================
    # 🔐 SNAPSHOT ANCHORING (FORENSIC PROOF)
    # =========================================================
    st.divider()
    st.subheader("Snapshot Anchoring")

    st.caption(
        "Flow: export → hash → append-only anchor → OpenTimestamps proof"
    )

    # ---------------------------
    # EXPORT FOR ANCHORING
    # ---------------------------
    if st.button("📦 Export Snapshot for Anchoring", use_container_width=True):

        result = export_forensic_snapshot(storage)

        if isinstance(result, dict):
            path = result.get("zip_path")
        else:
            path = result

        st.success(f"Snapshot exported: {path}")
        st.session_state["last_snapshot_path"] = path

    # ---------------------------
    # LOAD + NORMALIZE PATH
    # ---------------------------
    raw_path = st.session_state.get("last_snapshot_path", "")
    snapshot_path = _normalize_snapshot_path(raw_path)

    # ---------------------------
    # INPUT FIELD
    # ---------------------------
    snapshot_path = st.text_input(
        "Snapshot path to anchor",
        value=snapshot_path
    )

    # ---------------------------
    # ANCHOR BUTTON
    # ---------------------------
    if st.button(
        "🔐 Anchor Snapshot + ⏱ OpenTimestamps Stamp",
        type="primary",
        use_container_width=True,
    ):

        if not snapshot_path:
            st.error("Provide a snapshot path (export one above or paste one).")
            return

        if not os.path.exists(snapshot_path):
            st.error(f"File does not exist: {snapshot_path}")
            return

        # Hash file


        file_hash = sha256_file_hex(snapshot_path)

        snapshot_sha = h.hexdigest()

        anchor_id = str(uuid.uuid4())

        # Record in ledger
        ledger.record_forensic_anchor(
            anchor_id=anchor_id,
            anchor_type="SNAPSHOT_HASH",
            target_id=snapshot_path,
            hash_sha256=snapshot_sha,
            metadata={"source": "admin_ui"},
        )

        # OpenTimestamps proof
        ots_result = None  # ✅ ALWAYS initialize

        try:
            ots_result = notary.opentimestamps_stamp_anchor(
                target_id=anchor_id,
                hash_sha256=snapshot_sha,
                actor="admin_ui",
                label="snapshot",
                metadata={"snapshot_path": snapshot_path},
            )
            st.success("✅ Snapshot anchored and timestamped")

        except Exception as e:
            st.warning("⚠️ OpenTimestamps not available")
            st.code(str(e))

        # ✅ SAFE OUTPUT

        st.json({
            "snapshot_path": snapshot_path,
            "snapshot_sha256": snapshot_sha,
            "ledger_anchor_id": anchor_id,
            "ots_proof": ots_result if ots_result else None,
            "ots_status": "SUCCESS" if ots_result else "UNAVAILABLE"
        })

    # ----------------------------------------
    # 📧 GMAIL OAUTH CONNECT
    # ----------------------------------------

    st.subheader("🔗 Gmail Integration")

    mailbox = st.text_input("Mailbox to connect", value="")

    st.info(
        "⚠️ Gmail OAuth will open a browser window.\n\n"
        "Make sure no other process is using port 8765."
    )

    if st.button("🔗 Connect Gmail"):
        if not mailbox:
            st.error("Please enter a mailbox")
        else:
            try:
                st.warning("Launching Gmail OAuth flow...")

                run_oauth_flow_and_store(
                    storage=storage,
                    mailbox=mailbox
                )

                st.success(f"✅ Gmail connected for {mailbox}")

            except Exception as e:
                st.error(f"Gmail connection failed: {e}")

    # ----------------------------------
    # 🔍 DEBUG: Show stored tokens
    # ----------------------------------
    if st.checkbox("Show stored Gmail tokens"):
        try:
            with storage.ledger._connect() as con:
                rows = con.execute(
                    "SELECT provider, mailbox, expiry_ts FROM oauth_tokens"
                ).fetchall()

            st.write(rows)

        except Exception as e:
            st.error(f"Error reading tokens: {e}")

    # ----------------------------------------
    # 📡 IMAP CONNECT (NEW)
    # ----------------------------------------

    st.subheader("📡 IMAP Integration")

    imap_host = st.text_input(
        "IMAP Host",
        placeholder="e.g. imap.gmail.com, outlook.office365.com, mail.company.com"
    )
    imap_provider_label = st.text_input(
        "Provider Label",
        value="custom_imap",
        help="Used to identify this connection (e.g. gmail_imap, outlook_imap, corp_mail)"
    )
    imap_port = st.number_input("IMAP Port", value=993)
    imap_user = st.text_input("IMAP Username")
    imap_pass = st.text_input("IMAP Password", type="password")
    imap_mailbox = st.text_input("Mailbox", value="INBOX")

    if st.button("📡 Save IMAP Configuration"):
        if not imap_host or not imap_user or not imap_pass:
            st.error("Host, username, and password are required")
        else:


            # ----------------------------
            # 🔁 UPSERT (NO DUPLICATES)
            # ----------------------------
            new_config = {
                "provider": imap_provider_label,
                "host": imap_host,
                "port": imap_port,
                "username": imap_user,
                "password": imap_pass,
                "mailbox": imap_mailbox
            }

            configs = getattr(storage, "imap_configs", [])

            # Remove existing config for same user+host
            configs = [
                c for c in configs
                if not (c.get("host") == imap_host and c.get("username") == imap_user)
            ]

            configs.append(new_config)

            setattr(storage, "imap_configs", configs)

            st.success("✅ IMAP configuration saved")

    st.divider()
    st.subheader("📡 Configured IMAP Accounts")

    configs = getattr(storage, "imap_configs", [])

    if not configs:
        st.info("No IMAP accounts configured")
    else:
        for i, cfg in enumerate(configs):
            col1, col2, col3 = st.columns([4, 1, 1])

            with col1:
                st.write(f"**{cfg.get('provider')}** — {cfg.get('username')} @ {cfg.get('host')}")

            with col2:
                if st.button(f"Test {i}"):
                    try:


                        mail = connect_imap(
                            cfg["host"],
                            cfg["username"],
                            cfg["password"],
                            cfg.get("port", 993)
                        )
                        mail.logout()
                        st.success("✅ OK")
                    except Exception as e:
                        st.error(f"❌ {e}")

            with col3:
                if st.button(f"Delete {i}"):
                    new_configs = [c for j, c in enumerate(configs) if j != i]
                    setattr(storage, "imap_configs", new_configs)
                    st.rerun()

    st.subheader("🔔 Alert Notification Settings")

    settings = storage.ledger.get_alert_settings() or {}

    col1, col2 = st.columns(2)

    with col1:
        slack_enabled = st.toggle(
            "Enable Slack Alerts",
            value=settings.get("slack_enabled", False)
        )

    with col2:
        email_enabled = st.toggle(
            "Enable Email Alerts",
            value=settings.get("email_enabled", False)
        )

    # ----------------------------
    # SLACK CONFIG
    # ----------------------------
    slack_webhook = None
    if slack_enabled:
        slack_webhook = st.text_input(
            "Slack Webhook URL",
            value=settings.get("slack_webhook_url", ""),
            type="password"
        )

    # ----------------------------
    # EMAIL CONFIG
    # ----------------------------
    email_to = None
    if email_enabled:
        email_to = st.text_input(
            "Alert Email Recipient",
            value=settings.get("email_to", "")
        )

    # ----------------------------
    # SEVERITY THRESHOLD
    # ----------------------------
    min_severity = st.selectbox(
        "Minimum Severity to Notify",
        ["CRITICAL", "HIGH", "MEDIUM"],
        index=["CRITICAL", "HIGH", "MEDIUM"].index(settings.get("min_severity", "HIGH"))
    )

    # ----------------------------
    # SAVE BUTTON
    # ----------------------------
    if st.button("💾 Save Notification Settings"):
        storage.ledger.save_alert_settings({
            "slack_enabled": slack_enabled,
            "slack_webhook_url": slack_webhook,
            "email_enabled": email_enabled,
            "email_to": email_to,
            "min_severity": min_severity
        })

        st.success("Notification settings saved")


    # =========================================================
    # 📜 RECENT ANCHORS
    # =========================================================
    st.divider()
    st.subheader("Recent Forensic Anchors")

    if hasattr(ledger, "list_forensic_anchors"):
        rows = ledger.list_forensic_anchors(limit=50)

        if rows:
            import pandas as pd
            df = pd.DataFrame(rows)
            st.dataframe(df, use_container_width=True)
        else:
            st.info("No anchors recorded yet.")

    else:
        st.info("Ledger does not expose list_forensic_anchors(limit=...)")



    if st.button("📚 Seed Response Playbooks"):
        seed_playbooks(storage)
        st.success("Playbooks seeded.")