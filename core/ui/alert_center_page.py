

# core/ui/alert_center_page.py

from __future__ import annotations

import json
import time
from datetime import datetime, timezone

import pandas as pd
import streamlit as st


def _fmt_ms(ms):
    if not ms:
        return ""
    try:
        return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    except Exception:
        return str(ms)


def _safe_json_loads(value):
    if not value:
        return None
    if isinstance(value, dict):
        return value
    try:
        return json.loads(value)
    except Exception:
        return value


def render_alert_center_page(storage):
    st.title("🚨 Alert Center")
    st.caption("Real-time forensic alerts and event stream")
    case_id = None  # 🔥 MUST be here (top-level in function)
    ledger = storage.ledger

    # -----------------------------
    # Filters
    # -----------------------------
    st.subheader("Filters")
    if st.button("Fix Existing Case Links"):

        alerts = ledger.list_alerts()

        for a in alerts:
            alert_id = a["id"]
            evidence_id = a.get("evidence_id")

            # find matching case (by title)
            cases = ledger.list_cases()
            for c in cases:
                if str(alert_id) in (c.get("title") or ""):
                    cid = c.get("id")

                    ledger.add_case_alert(cid, alert_id)

                    if evidence_id:
                        ledger.add_case_evidence(cid, evidence_id)

        st.success("Backfill complete")



    col1, col2 = st.columns(2)
    severity_filter = col1.selectbox(
        "Severity",
        ["ALL", "CRITICAL", "HIGH", "MEDIUM", "LOW"],
        index=0,
    )
    auto_refresh = col2.checkbox("Auto Refresh (Live)", value=True)

    # -----------------------------
    # Alerts
    # -----------------------------
    st.divider()
    st.subheader("🚨 Active Alerts")

    alerts = []
    if hasattr(ledger, "list_active_alerts"):
        alerts = ledger.list_active_alerts(limit=200)
    elif hasattr(ledger, "list_alerts"):
        alerts = ledger.list_alerts(limit=200)

    if alerts:
        df = pd.DataFrame(alerts)

        def severity_color(s):
            return {
                "CRITICAL": "🔴",
                "HIGH": "🟠",
                "MEDIUM": "🟡",
                "LOW": "🟢"
            }.get(s, "⚪")
        df["severity"] = df["severity"].apply(lambda x: f"{severity_color(x)} {x}")
        if severity_filter != "ALL" and "severity" in df.columns:
            df = df[df["severity"] == severity_filter]

        if "created_at_ms" in df.columns:
            df["created_at"] = df["created_at_ms"].apply(_fmt_ms)

        display_cols = [
            c for c in [
                "id",
                "created_at",
                "severity",
                "message",
                "evidence_id",
                "resolved",
            ] if c in df.columns
        ]

        st.dataframe(df[display_cols], use_container_width=True, hide_index=True)

        st.markdown("### Alert Drill-Down")

        alert_options = {}
        for a in alerts:
            label = f"[{a.get('severity', 'UNKNOWN')}] #{a.get('id')} - {a.get('message', '')[:80]}"
            alert_options[label] = a

        selected_alert_label = st.selectbox(
            "Select Alert",
            list(alert_options.keys()),
            key="alert_center_selected_alert",
        )

        selected_alert = alert_options[selected_alert_label]
        selected_alert_id = selected_alert.get("id")
        st.session_state["selected_alert_id"] = selected_alert_id
        case_link = ledger.get_case_by_alert(selected_alert_id)
        st.json(selected_alert)
        # =========================================
        # 🔗 FORENSIC CHAIN (JOB → EVIDENCE → CUSTODY)
        # =========================================

        st.subheader("🔗 Forensic Chain")

        job_id = selected_alert.get("job_id")
        run_id = selected_alert.get("run_id")

        # DEBUG (leave temporarily)
        st.write("DEBUG job_id:", job_id)
        st.write("DEBUG run_id:", run_id)

        # -------------------------
        # 🧩 JOB
        # -------------------------
        if job_id:
            job = ledger.get_job_by_id(job_id)

            if job:
                st.markdown("### 🧩 Job")
                st.json(job)
            else:
                st.error(f"Job {job_id} not found")
        else:
            st.warning("⚠️ No job_id on alert")

        # -------------------------
        # 📄 EVIDENCE
        # -------------------------
        if run_id:
            evidence = ledger.get_evidence_by_run_id(run_id)

            if evidence:
                st.markdown("### 📄 Evidence")
                st.dataframe(evidence)

                selected_evidence_id = st.selectbox(
                    "Select Evidence ID",
                    [e["id"] for e in evidence],
                    key="forensic_evidence_select"
                )

                # -------------------------
                # 🔐 CUSTODY
                # -------------------------
                custody = ledger.get_custody_for_evidence(selected_evidence_id)

                if custody:
                    st.markdown("### 🔐 Custody Chain")
                    st.dataframe(custody)
                else:
                    st.warning("No custody events found")

            else:
                st.warning(f"No evidence found for run_id {run_id}")
        else:
            st.warning("⚠️ No run_id on alert")

        st.subheader("🧠 Investigation")

        if case_link:

            case_id = case_link.get("case_id")
            st.success(f"🔗 Linked to Case {case_id}")

            if st.button("🧠 Open Investigation Workspace", use_container_width=True):
                st.session_state["selected_case_id"] = case_id
                st.session_state["nav_page"] = "Investigation Workspace"
                st.rerun()

        else:
            st.warning("⚠️ No case linked to this alert")
            selected_alert = None

            for a in alerts:
                if a.get("id") == selected_alert_id:
                    selected_alert = a
                    break
            if st.button('🚨 Create Case from Alert', use_container_width=True):

                selected_alert = None
                for a in alerts:
                    if a.get("id") == selected_alert_id:
                        selected_alert = a
                        break

                if not selected_alert:
                    st.error("Selected alert not found")
                    return

                # -------------------------
                # 🔍 CHECK FOR EXISTING CASE
                # -------------------------
                existing_case_id = None

                if hasattr(ledger, "find_similar_case_for_alert"):
                    existing_case_id = ledger.find_similar_case_for_alert(selected_alert_id)

                # -------------------------
                # 🧠 USE EXISTING OR CREATE NEW
                # -------------------------
                if existing_case_id:
                    case_id = existing_case_id
                    st.info(f"🔁 Alert grouped into existing case {case_id}")
                else:
                    case_id = ledger.create_case(
                        title=f"Case from Alert {selected_alert_id}",
                        description=selected_alert.get("message"),
                    )
                    st.success(f"🆕 New case created: {case_id}")

                # -------------------------
                # 🔥 LINK ALERT → CASE
                # -------------------------
                ledger.add_case_alert(case_id, selected_alert_id)

                # ---------------------------------------
                # 🔥 LINK EVIDENCE → CASE
                # ---------------------------------------

                linked = False

                # Primary: direct evidence on alert
                if selected_alert.get("evidence_id"):
                    ledger.add_case_evidence(case_id, selected_alert["evidence_id"])
                    linked = True

                # Fallback: lookup function
                if not linked and hasattr(ledger, "get_evidence_for_alert"):
                    evidence_ids = ledger.get_evidence_for_alert(selected_alert_id) or []
                    for eid in evidence_ids:
                        ledger.add_case_evidence(case_id, eid)

                # -------------------------
                # 🚨 AUTO ESCALATION
                # -------------------------
                if hasattr(ledger, "evaluate_case_escalation"):
                    result = ledger.evaluate_case_escalation(case_id)

                    if result and result.get("escalation"):
                        level = result["escalation"]

                        st.warning(f"🚨 Case escalated to {level}")

                        if hasattr(ledger, "add_case_escalation_event"):
                            ledger.add_case_escalation_event(case_id, level)

                # -------------------------
                # OPTIONAL: ASSIGN
                # -------------------------
                ledger.assign_case(case_id, "analyst", "system")

                # -------------------------
                # UI NAVIGATION
                # -------------------------
                st.session_state["selected_case_id"] = case_id
                st.session_state["highlight_case_id"] = case_id
                st.session_state["nav_page"] = "Case Dashboard"

                st.success(f"Case {case_id} created")
                st.rerun()

            # ✅ SAFE usage outside button
            if case_id:
                print(f"Case {case_id} processed")
        alert_col1, alert_col2 = st.columns(2)

        with alert_col1:
            if selected_alert.get("evidence_id"):
                if st.button("🔎 Open Linked Evidence", use_container_width=True):
                    st.session_state["selected_evidence_id"] = selected_alert["evidence_id"]
                    st.session_state["nav_page"] = "Evidence Viewer"
                    st.success("Linked evidence selected. Open Evidence Viewer from the sidebar.")
            else:
                st.info("This alert is not linked to an evidence record.")

        with alert_col2:
            if selected_alert.get("id") is not None and hasattr(ledger, "resolve_alert"):
                if st.button("✅ Resolve This Alert", use_container_width=True):
                    ledger.resolve_alert(int(selected_alert["id"]))
                    st.success("Alert resolved.")
                    st.rerun()
    else:
        st.info("No alerts found.")

    # -----------------------------
    # Event Stream
    # -----------------------------
    st.divider()
    st.subheader("📜 Live Event Stream")

    events = []
    if hasattr(ledger, "list_recent_events"):
        events = ledger.list_recent_events(limit=200)
    elif hasattr(ledger, "list_recent_custody_events"):
        events = ledger.list_recent_custody_events(limit=200)

    if events:
        parsed_events = []
        for e in events:
            row = dict(e)
            if row.get("timestamp_ms"):
                row["timestamp"] = _fmt_ms(row["timestamp_ms"])
            if row.get("details_json"):
                row["details"] = _safe_json_loads(row["details_json"])
            parsed_events.append(row)

        df_events = pd.DataFrame(parsed_events)

        display_cols = [
            c for c in [
                "timestamp",
                "event_type",
                "actor",
                "run_id",
                "evidence_id",
                "details",
            ] if c in df_events.columns
        ]

        st.dataframe(df_events[display_cols], use_container_width=True, hide_index=True)

        st.markdown("### Event Drill-Down")

        event_options = {}
        for i, e in enumerate(parsed_events):
            label = f"{e.get('timestamp', '')} | {e.get('event_type', '')} | {str(e.get('evidence_id', ''))[:12]}"
            event_options[label] = e

        selected_event_label = st.selectbox(
            "Select Event",
            list(event_options.keys()),
            key="alert_center_selected_event",
        )
        selected_event = event_options[selected_event_label]

        st.json(selected_event)

        if selected_event.get("evidence_id"):
            if st.button("🧾 Open Event Evidence", use_container_width=True):
                st.session_state["selected_evidence_id"] = selected_event["evidence_id"]
                st.session_state["nav_page"] = "Evidence Viewer"
                st.success("Linked evidence selected. Open Evidence Viewer from the sidebar.")
    else:
        st.info("No recent events.")

    # -----------------------------
    # Health Summary
    # -----------------------------
    st.divider()
    st.subheader("🧠 System Health")

    total_alerts = len(alerts)
    critical_alerts = len([a for a in alerts if a.get("severity") == "CRITICAL"])

    c1, c2, c3 = st.columns(3)
    c1.metric("Total Alerts", total_alerts)
    c2.metric("Critical Alerts", critical_alerts)

    health_score = max(0, 100 - min(critical_alerts * 10, 100))
    c3.metric("Health Score", f"{health_score}%")

    if health_score < 70:
        st.error("🔴 System Integrity Risk Detected")
    elif health_score < 90:
        st.warning("🟡 Minor Issues Detected")
    else:
        st.success("🟢 System Healthy")



    # -----------------------------
    # Auto Refresh
    # -----------------------------
    if auto_refresh:
        time.sleep(3)
        st.rerun()



