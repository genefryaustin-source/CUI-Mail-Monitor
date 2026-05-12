from __future__ import annotations

from datetime import datetime, timezone
import pandas as pd
import streamlit as st
import time

from veridion_theme import apply_theme
apply_theme()
with st.sidebar:
    st.markdown('<h1 class="veridion-sidebar-title">Veridion Pro</h1>', unsafe_allow_html=True)

def _fmt_ms(ms):
    if not ms:
        return ""
    try:
        return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    except Exception:
        return str(ms)


def render_trust_center_page(storage):

    # ----------------------------------
    # 🔄 SAFE AUTO-REFRESH (moved inside)
    # ----------------------------------
    if "last_refresh" not in st.session_state:
        st.session_state.last_refresh = time.time()

    if time.time() - st.session_state.last_refresh > 5:
        st.session_state.last_refresh = time.time()
        st.rerun()

    st.title("🛡️ Trust Center / Forensic Dashboard")
    st.caption("Integrity status, custody activity, and forensic anchors")

    ledger = storage.ledger

    summary = ledger.get_forensic_dashboard_summary()
    evidence_rows = ledger.list_evidence_records(limit=200)
    event_rows = ledger.list_recent_custody_events(limit=50)
    anchor_rows = ledger.list_recent_anchors(limit=50)

    # ---------------------------
    # Top metrics
    # ---------------------------
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Evidence Items", summary["total_evidence"])
    c2.metric("Verified Events", summary["verified_events"])
    c3.metric("Integrity Failures", summary["integrity_failures"])
    c4.metric("Anchors", summary["total_anchors"])

    c5, c6 = st.columns(2)
    c5.metric("Ingested Events", summary["ingested_events"])
    c6.metric("Restored Events", summary["restored_events"])

    st.divider()
    st.subheader("🚨 Live Alerts")

    alerts = ledger.list_active_alerts()

    if alerts:
        df = pd.DataFrame(alerts)

        st.dataframe(
            df[["created_at_ms", "severity", "message", "evidence_id"]],
            use_container_width=True,
            hide_index=True,
        )

        st.error(f"{len(alerts)} active alerts")
    else:
        st.success("No active alerts")

    # ---------------------------
    # Health banner
    # ---------------------------
    if summary["integrity_failures"] > 0:
        st.error(
            f"Integrity alerts detected: {summary['integrity_failures']} failure event(s) recorded."
        )
    else:
        st.success("No integrity failures recorded.")

    # ---------------------------
    # Evidence inventory
    # ---------------------------
    st.subheader("Evidence Inventory")

    if evidence_rows:
        evidence_df = pd.DataFrame(evidence_rows)

        if "created_at_ms" in evidence_df.columns:
            evidence_df["created_at"] = evidence_df["created_at_ms"].apply(_fmt_ms)

        display_cols = [
            c for c in [
                "suggested_name",
                "evidence_id",
                "content_type",
                "size_bytes",
                "created_at",
                "sha256",
                "storage_uri",
            ] if c in evidence_df.columns
        ]

        st.dataframe(
            evidence_df[display_cols],
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("No evidence records found.")

    st.divider()

    # ---------------------------
    # Custody events
    # ---------------------------
    st.subheader("Recent Chain of Custody Events")

    if event_rows:
        event_df = pd.DataFrame(event_rows)

        if "timestamp_ms" in event_df.columns:
            event_df["timestamp"] = event_df["timestamp_ms"].apply(_fmt_ms)

        if "details" in event_df.columns:
            event_df["details"] = event_df["details"].apply(
                lambda x: x if isinstance(x, str) else str(x)
            )

        display_cols = [
            c for c in [
                "timestamp",
                "event_type",
                "actor",
                "run_id",
                "evidence_id",
                "details",
            ] if c in event_df.columns
        ]

        st.dataframe(
            event_df[display_cols],
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("No custody events recorded yet.")

    st.divider()

    # ---------------------------
    # Anchors
    # ---------------------------
    st.subheader("Recent Forensic Anchors")

    if anchor_rows:
        anchor_df = pd.DataFrame(anchor_rows)

        if "created_at_ms" in anchor_df.columns:
            anchor_df["created_at"] = anchor_df["created_at_ms"].apply(_fmt_ms)

        if "metadata" in anchor_df.columns:
            anchor_df["metadata"] = anchor_df["metadata"].apply(
                lambda x: x if isinstance(x, str) else str(x)
            )

        display_cols = [
            c for c in [
                "created_at",
                "anchor_type",
                "target_id",
                "anchor_id",
                "hash_sha256",
                "metadata",
            ] if c in anchor_df.columns
        ]

        st.dataframe(
            anchor_df[display_cols],
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("No forensic anchors recorded yet.")