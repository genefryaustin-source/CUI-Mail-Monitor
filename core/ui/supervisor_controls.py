# core/ui/supervisor_controls.py
from __future__ import annotations

import streamlit as st
from typing import Any


def render_supervisor_controls(storage: Any) -> None:
    ledger = storage.ledger

    st.subheader("Supervisor Controls")

    status = ledger.supervisor_status()

    if not status.get("has_lock"):
        st.info("No active supervisor leader.")
        return

    leader_id = status.get("leader_id")
    hb_age = status.get("heartbeat_age_ms")

    st.markdown(f"""
**Current Leader:** `{leader_id}`  
**Heartbeat Age:** `{hb_age} ms`
""")

    if st.button("🔥 Kill Supervisor Leader (Controlled Failover)", type="secondary"):
        ledger.record_watchdog_event(
            event_type="MANUAL_LEADER_KILL",
            leader_id=leader_id,
            details={"source": "ui"},
        )

        cleared = ledger.clear_supervisor_lock()

        if cleared:
            st.success("Supervisor leader cleared. Failover will occur shortly.")
        else:
            st.warning("Supervisor lock already cleared.")
