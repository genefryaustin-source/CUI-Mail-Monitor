from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timedelta

import pandas as pd
import plotly.express as px
import streamlit as st

from core.cases.escalation_engine import run_escalation_check

from veridion_theme import apply_theme
apply_theme()
with st.sidebar:
    st.markdown('<h1 class="veridion-sidebar-title">Veridion Pro</h1>', unsafe_allow_html=True)

# ------------------------
# Helper
# ------------------------

def _severity_score(severity: str) -> int:
    severity = (severity or "").upper()
    return {
        "LOW": 10,
        "MEDIUM": 35,
        "HIGH": 70,
        "CRITICAL": 100,
    }.get(severity, 0)


def _case_priority_label(score: int) -> str:
    if score >= 85:
        return "🔴 Critical"
    if score >= 65:
        return "🟠 High"
    if score >= 35:
        return "🟡 Medium"
    return "🟢 Low"


def _enqueue_notify(ledger, severity: str, message: str, case_id: str | None = None, priority: int | None = None):
    """
    Queue-based notification helper.
    Do NOT call notify() directly from the UI.
    """
    if not hasattr(ledger, "enqueue_task"):
        st.warning("Notification queue is unavailable. Missing ledger.enqueue_task().")
        return

    sev = (severity or "LOW").upper().strip()

    if priority is None:
        priority = 1 if sev == "CRITICAL" else 2 if sev == "HIGH" else 5

    ledger.enqueue_task(
        "NOTIFY",
        {
            "severity": sev,
            "message": message,
            "case_id": case_id,
        },
        priority=priority,
        max_attempts=3,
    )


def _enqueue_escalation_check(ledger):
    """
    Queue escalation checks instead of running heavy escalation logic directly in the UI.
    """
    if hasattr(ledger, "enqueue_task"):
        ledger.enqueue_task(
            "ESCALATE",
            {},
            priority=2,
            max_attempts=3,
        )


def _calculate_case_risk(storage, case_id: str) -> dict:
    with storage.ledger._connect() as con:
        alerts = con.execute("""
            SELECT
                id,
                evidence_id,
                severity,
                category,
                location,
                notes,
                source_name,
                created_at_ms
            FROM alerts
            WHERE case_id = ?
        """, (case_id,)).fetchall()

        custody_gaps = con.execute("""
            SELECT COUNT(*)
            FROM case_evidence ce_map
            JOIN evidence_records er
                ON ce_map.evidence_id = er.evidence_id
            LEFT JOIN custody_events ce
                ON er.evidence_id = ce.evidence_id
            WHERE ce_map.case_id = ?
              AND ce.evidence_id IS NULL
        """, (case_id,)).fetchone()[0]

    alert_count = len(alerts)

    if alert_count == 0:
        return {
            "case_id": case_id,
            "risk_score": 0,
            "priority": "🟢 Low",
            "alert_count": 0,
            "critical_alerts": 0,
            "high_alerts": 0,
            "categories": [],
            "custody_gaps": custody_gaps,
        }

    # ---------------------------------------
    # SCORING ENGINE
    # ---------------------------------------
    severity_weights = {
        "CRITICAL": 40,
        "HIGH": 25,
        "MEDIUM": 10,
        "LOW": 5,
    }

    score = 0
    critical_alerts = 0
    high_alerts = 0
    categories = set()

    for a in alerts:
        sev = (a["severity"] or "LOW").upper()
        score += severity_weights.get(sev, 5)

        if sev == "CRITICAL":
            critical_alerts += 1
        if sev == "HIGH":
            high_alerts += 1

        if a["category"]:
            categories.add(a["category"])

    # ---------------------------------------
    # CONTEXT BOOSTS
    # ---------------------------------------
    if len(categories) >= 3:
        score += 20

    score += custody_gaps * 15

    if alert_count >= 5:
        score += 10

    score = max(0, min(score, 100))

    # ---------------------------------------
    # PRIORITY
    # ---------------------------------------
    if score >= 100:
        priority = "🔴 Critical"
    elif score >= 70:
        priority = "🟠 High"
    elif score >= 30:
        priority = "🟡 Medium"
    else:
        priority = "🟢 Low"

    return {
        "case_id": case_id,
        "risk_score": score,
        "priority": priority,
        "alert_count": alert_count,
        "critical_alerts": critical_alerts,
        "high_alerts": high_alerts,
        "categories": list(categories),
        "custody_gaps": custody_gaps,
    }


def render_investigation_page(storage):
    st.title("🕵️ Investigation Workspace")

    ledger = storage.ledger

    # -----------------------------
    # Create Case
    # -----------------------------
    st.subheader("Create New Case")

    title = st.text_input("Case Title")
    description = st.text_area("Description")

    if st.button("➕ Create Case"):
        case_id = str(uuid.uuid4())
        ledger.create_case(case_id, title, description)
        ledger.add_case_event(
            case_id,
            "CASE_CREATED",
            f"Case created: {title}",
            actor="analyst_user",
        )
        st.success(f"Case created: {case_id}")

    # -----------------------------
    # List Cases
    # -----------------------------
    st.divider()
    st.subheader("Active Cases")

    cases = ledger.list_cases()

    if not cases:
        st.info("No cases yet.")
        return

    # ---------------------------------------
    # 🎯 SCORE + AUTO ASSIGN PER CASE
    # ---------------------------------------
    scored_cases = []

    for c in cases:
        cid = c.get("case_id") or c.get("id")

        if not cid:
            print("⚠️ Skipping case with no case_id/id:", c)
            continue

        risk = _calculate_case_risk(storage, cid)

        # ---------------------------------------
        # 📊 STORE METRIC
        # ---------------------------------------
        if hasattr(ledger, "enqueue_task"):
            ledger.enqueue_task(
                "METRIC_BATCH",
                [
                    {
                        "name": "risk_score",
                        "value": risk["risk_score"],
                        "tags": json.dumps({"case_id": cid}),
                    }
                ],
                priority=9,
                max_attempts=2,
            )
        else:
            with storage.ledger._connect() as con:
                con.execute("""
                    INSERT INTO metrics (name, value, ts_ms, tags_json)
                    VALUES (?, ?, ?, ?)
                """, (
                    "risk_score",
                    risk["risk_score"],
                    int(time.time() * 1000),
                    json.dumps({"case_id": cid}),
                ))
                con.commit()

        # ---------------------------------------
        # 🧠 ENRICH CASE
        # ---------------------------------------
        c["case_id"] = cid
        c["id"] = c.get("id") or cid
        c["risk_score"] = risk["risk_score"]
        c["auto_priority"] = risk["priority"]

        # ---------------------------------------
        # 🤖 AUTO ASSIGNMENT
        # ---------------------------------------
        if not c.get("assigned_to"):
            if risk["risk_score"] >= 85 and hasattr(ledger, "auto_assign_case"):
                assigned_owner = ledger.auto_assign_case(
                    cid,
                    severity="CRITICAL",
                    actor="system",
                )
                print(f"🤖 AUTO-ASSIGNED CRITICAL: {cid} → {assigned_owner}")

            elif risk["risk_score"] >= 65 and hasattr(ledger, "auto_assign_case"):
                assigned_owner = ledger.auto_assign_case(
                    cid,
                    severity="HIGH",
                    actor="system",
                )
                print(f"🤖 AUTO-ASSIGNED HIGH: {cid} → {assigned_owner}")

        scored_cases.append(c)

    if not scored_cases:
        st.info("No valid cases found.")
        return

    # ---------------------------------------
    # 🔥 SORT BY RISK SCORE (DESC)
    # ---------------------------------------
    scored_cases.sort(key=lambda x: x["risk_score"], reverse=True)

    # ---------------------------------------
    # 🎯 BUILD DISPLAY LABELS
    # ---------------------------------------
    case_map = {
        f"{c['auto_priority']} | {c.get('title', 'Untitled Case')} ({(c.get('id') or c.get('case_id'))[:8]}) | Score: {c['risk_score']}": c
        for c in scored_cases
    }

    selected_label = st.selectbox(
        "Select Case (sorted by risk)",
        list(case_map.keys()),
    )

    case = case_map[selected_label]
    st.json(case)

    selected_case_id = case.get("case_id") or case.get("id")

    with storage.ledger._connect() as con:
        con.execute("""
            UPDATE cases
            SET priority = ?
            WHERE case_id = ?
        """, (case["auto_priority"], selected_case_id))
        con.commit()

    st.markdown("### 🧠 Case Ranking")

    top_cases = scored_cases[:5]

    for i, tc in enumerate(top_cases, start=1):
        st.write(
            f"{i}. {tc['auto_priority']} | {tc.get('title', 'Untitled Case')} "
            f"(Score: {tc['risk_score']})"
        )

    st.subheader("Case Details")

    col1, col2, col3 = st.columns(3)

    col1.metric("Owner", case.get("assigned_to") or case.get("owner") or "Unassigned")
    col2.metric("Priority", case.get("priority") or case.get("auto_priority") or "N/A")

    case_id = case.get("case_id") or case.get("id")

    # Queue escalation checks instead of running heavy escalation logic directly.
    _enqueue_escalation_check(ledger)

    try:
        run_escalation_check(storage, case_id)
    except Exception as e:
        print(f"Escalation check failed: {e}")

    # SLA countdown from persisted due date if available
    sla_due = case.get("sla_due_ms")
    if sla_due:
        remaining = int((sla_due - time.time() * 1000) / 1000)

        if remaining > 0:
            col3.metric("SLA Remaining", f"{remaining // 60} min")
        else:
            col3.error("SLA BREACHED")

    # -----------------------------
    # 🧠 CASE RISK SCORING
    # -----------------------------
    risk = _calculate_case_risk(storage, case_id)

    with storage.ledger._connect() as con:
        con.execute("""
            INSERT INTO case_risk_history (
                case_id,
                risk_score,
                alert_count,
                critical_count,
                created_at_ms
            )
            VALUES (?, ?, ?, ?, ?)
        """, (
            case_id,
            risk["risk_score"],
            risk["alert_count"],
            risk["critical_alerts"],
            int(time.time() * 1000),
        ))
        con.commit()

    st.markdown("### 🧠 Case Risk Score")

    r1, r2, r3, r4 = st.columns(4)

    r1.metric("Risk Score", risk["risk_score"])
    r2.metric("Priority", risk["priority"])
    r3.metric("Alerts", risk["alert_count"])
    r4.metric("Critical Alerts", risk["critical_alerts"])

    if risk["categories"]:
        st.caption(f"Categories: {', '.join(risk['categories'])}")

    if risk["custody_gaps"] > 0:
        st.warning(f"⚠️ Custody gaps detected: {risk['custody_gaps']}")

    if risk["risk_score"] >= 85:
        st.error("🚨 Critical case. Immediate investigation required.")
    elif risk["risk_score"] >= 65:
        st.warning("⚠️ High-risk case. Prioritize review.")
    else:
        st.success("Risk level currently controlled.")

    if hasattr(ledger, "check_sla_breach") and ledger.check_sla_breach(case_id):
        existing_alerts = ledger.list_alerts(limit=50)

        if not any("SLA breach" in a.get("message", "") for a in existing_alerts):
            ledger.create_alert(
                evidence_id=None,
                severity="HIGH",
                message=f"SLA breach for case {case_id}",
            )

    st.markdown("### 📈 Risk Trend Over Time")

    with storage.ledger._connect() as con:
        rows = con.execute("""
            SELECT risk_score, created_at_ms
            FROM case_risk_history
            WHERE case_id = ?
            ORDER BY created_at_ms ASC
        """, (case_id,)).fetchall()

    df_risk = pd.DataFrame()

    if rows:
        df_risk = pd.DataFrame(rows, columns=["risk_score", "timestamp"])
        df_risk["time"] = pd.to_datetime(df_risk["timestamp"], unit="ms")
        st.line_chart(df_risk.set_index("time")["risk_score"])
    else:
        st.info("No risk history yet.")

    if not df_risk.empty and len(df_risk) >= 2:
        latest = df_risk["risk_score"].iloc[-1]
        previous = df_risk["risk_score"].iloc[-2]
        delta = latest - previous

        if delta > 10:
            st.error(f"🚨 Risk increasing rapidly (+{delta})")
        elif delta > 0:
            st.warning(f"⚠️ Risk increasing (+{delta})")
        elif delta < 0:
            st.success(f"✅ Risk decreasing ({delta})")

    if not df_risk.empty:
        latest = df_risk["risk_score"].iloc[-1]

        if latest >= 85:
            ledger.create_alert(
                evidence_id=None,
                severity="CRITICAL",
                message=f"Case {case_id} reached critical risk level ({latest})",
            )

    if not case.get("assigned_to") and hasattr(ledger, "ai_route_case"):
        if risk["risk_score"] >= 85:
            routed = ledger.ai_route_case(case_id, severity="CRITICAL")
            st.info(f"🤖 AI routed {routed['domain']} case to {routed['assigned_to']}")

        elif risk["risk_score"] >= 65:
            routed = ledger.ai_route_case(case_id, severity="HIGH")
            st.info(f"🤖 AI routed {routed['domain']} case to {routed['assigned_to']}")

    st.subheader("🚨 Escalation Status")

    alerts = ledger.list_alerts(limit=50)
    case_alerts = [a for a in alerts if case_id in a.get("message", "")]

    if case_alerts:
        for a in case_alerts:
            st.warning(f"{a['severity']} → {a['message']}")
    else:
        st.success("No escalations triggered")

    st.divider()
    st.subheader("Case Lifecycle")

    col1, col2 = st.columns(2)

    current_status = case.get("status", "OPEN")

    col1.metric("Current Status", current_status)

    valid_statuses = ["OPEN", "INVESTIGATING", "RESOLVED"]
    status_index = valid_statuses.index(current_status) if current_status in valid_statuses else 0

    new_status = col2.selectbox(
        "Update Status",
        valid_statuses,
        index=status_index,
    )

    # ----------------------------
    # STATUS UPDATE
    # ----------------------------
    if st.button("🔄 Update Status"):
        old_status = case.get("status")

        ledger.update_case_status(case_id, new_status, actor="analyst_user")

        ledger.add_case_event(
            case_id,
            "STATUS_CHANGE",
            f"{old_status} → {new_status}",
            actor="analyst_user",
            details={
                "old_status": old_status,
                "new_status": new_status,
            },
        )

        if new_status == "RESOLVED":
            ledger.add_case_event(
                case_id,
                "CASE_CLOSED",
                "Case marked as resolved",
                actor="analyst_user",
            )

        st.success(f"Status updated to {new_status}")
        st.rerun()

    # ----------------------------
    # OWNER ASSIGNMENT
    # ----------------------------
    st.subheader("Owner Assignment")

    new_owner = st.text_input(
        "Assign Owner",
        value=case.get("assigned_to") or case.get("owner") or "",
    )

    if st.button("👤 Update Owner"):
        old_owner = case.get("assigned_to") or case.get("owner")

        ledger.update_case_owner(case_id, new_owner, actor="analyst_user")

        ledger.add_case_event(
            case_id,
            "OWNER_ASSIGNED",
            f"{old_owner or 'Unassigned'} → {new_owner}",
            actor="analyst_user",
            details={
                "old_owner": old_owner,
                "new_owner": new_owner,
            },
        )

        st.success("Owner updated")
        st.rerun()

    st.divider()
    st.subheader("📜 Audit Trail")

    logs = ledger.list_case_audit_log(case_id)

    if logs:
        df_audit = pd.DataFrame(logs)

        if "created_at_ms" in df_audit.columns:
            df_audit["time"] = pd.to_datetime(df_audit["created_at_ms"], unit="ms")

        audit_cols = [c for c in ["time", "action", "old_value", "new_value", "actor"] if c in df_audit.columns]

        st.dataframe(
            df_audit[audit_cols],
            use_container_width=True,
        )
    else:
        st.info("No audit history yet.")

    st.divider()
    st.subheader("📊 Investigation Timeline (Visual)")

    timeline = ledger.build_case_timeline(case_id)

    if timeline:
        df_timeline = pd.DataFrame(timeline)

        df_timeline["time"] = pd.to_datetime(df_timeline["ts"], unit="ms")
        df_timeline["type"] = df_timeline["type"].fillna("UNKNOWN")
        df_timeline["label"] = df_timeline["label"].fillna("")

        st.markdown("### 🔎 Timeline Filters")

        col1, col2, col3 = st.columns(3)

        with col1:
            time_filter = st.selectbox(
                "Time Window",
                ["All", "Last 24h", "Last 7 days"],
            )

        with col2:
            selected_types = st.multiselect(
                "Event Types",
                options=sorted(df_timeline["type"].unique()),
                default=list(df_timeline["type"].unique()),
            )

        with col3:
            critical_only = st.checkbox("Critical Only")

        now = datetime.utcnow()

        if time_filter == "Last 24h":
            df_timeline = df_timeline[df_timeline["time"] >= (now - timedelta(days=1))]
        elif time_filter == "Last 7 days":
            df_timeline = df_timeline[df_timeline["time"] >= (now - timedelta(days=7))]

        df_timeline = df_timeline[df_timeline["type"].isin(selected_types)]

        if critical_only:
            df_timeline = df_timeline[df_timeline["label"].str.contains("CRITICAL", na=False)]

        if df_timeline.empty:
            st.info("No timeline data after filters.")
        else:
            lane_map = {
                "ALERT": "Detection",
                "STATUS_CHANGE": "Case Activity",
                "OWNER_ASSIGNED": "Case Activity",
                "NOTE_ADDED": "Case Activity",
                "CASE_ACTION": "Case Activity",
                "RESPONSE_ACTION": "Response",
                "APPROVAL": "Governance",
                "CUSTODY_EVENT": "Forensics",
                "EVENT": "Forensics",
                "UNKNOWN": "Other",
                "AUTO_ASSIGNED": "Case Activity",
                "AUTO_REBALANCED": "Case Activity",
                "DOMAIN_ROUTED": "Case Activity",
                "AI_ROUTED": "Case Activity",
                "SLACK": "Slack",
                "SLACK_ACK": "Slack",
                "SLACK_ASSIGN": "Slack",
                "SLACK_CLOSE": "Slack",
                "SLACK_ESCALATE": "Slack",
                "SLA_BREACH": "Governance",
                "SLA_WARNING": "Governance",
                "ESCALATION_REMINDER": "Governance",
                "ESCALATION_MANAGER_ESCALATION": "Governance",
                "ESCALATION_LEADERSHIP_PAGE": "Governance",
                "ESCALATION_SENIOR_ESCALATION": "Governance",
                "ESCALATION_QUEUE_REMINDER": "Governance",
                "L1_REMINDER": "Governance",
                "L2_MANAGER": "Governance",
                "L3_EXECUTIVE": "Governance",
            }

            df_timeline["lane"] = df_timeline["type"].map(lane_map).fillna("Other")

            df_timeline["priority"] = df_timeline["type"].map({
                "ALERT": 6,
                "SLA_BREACH": 6,
                "ESCALATION_MANAGER_ESCALATION": 6,
                "ESCALATION_LEADERSHIP_PAGE": 6,
                "ESCALATION_SENIOR_ESCALATION": 6,
                "L3_EXECUTIVE": 6,
                "SLA_WARNING": 5,
                "ESCALATION_REMINDER": 5,
                "L2_MANAGER": 5,
                "STATUS_CHANGE": 4,
                "OWNER_ASSIGNED": 4,
                "NOTE_ADDED": 4,
                "CASE_ACTION": 4,
                "AUTO_ASSIGNED": 4,
                "AUTO_REBALANCED": 4,
                "DOMAIN_ROUTED": 4,
                "AI_ROUTED": 4,
                "SLACK": 4,
                "SLACK_ACK": 4,
                "SLACK_ASSIGN": 4,
                "SLACK_CLOSE": 4,
                "SLACK_ESCALATE": 4,
                "L1_REMINDER": 4,
                "RESPONSE_ACTION": 3,
                "APPROVAL": 2,
                "CUSTODY_EVENT": 1,
                "EVENT": 1,
                "UNKNOWN": 0,
            }).fillna(0)

            color_map = {
                "ALERT": "red",
                "STATUS_CHANGE": "orange",
                "OWNER_ASSIGNED": "blue",
                "NOTE_ADDED": "gray",
                "CASE_ACTION": "blue",
                "RESPONSE_ACTION": "purple",
                "APPROVAL": "green",
                "CUSTODY_EVENT": "black",
                "EVENT": "black",
                "UNKNOWN": "lightgray",
                "AUTO_ASSIGNED": "blue",
                "AUTO_REBALANCED": "blue",
                "DOMAIN_ROUTED": "teal",
                "AI_ROUTED": "teal",
                "SLACK": "purple",
                "SLACK_ACK": "purple",
                "SLACK_ASSIGN": "purple",
                "SLACK_CLOSE": "purple",
                "SLACK_ESCALATE": "purple",
                "SLA_BREACH": "red",
                "SLA_WARNING": "orange",
                "ESCALATION_REMINDER": "orange",
                "ESCALATION_MANAGER_ESCALATION": "red",
                "ESCALATION_LEADERSHIP_PAGE": "red",
                "ESCALATION_SENIOR_ESCALATION": "red",
                "ESCALATION_QUEUE_REMINDER": "orange",
                "L1_REMINDER": "orange",
                "L2_MANAGER": "red",
                "L3_EXECUTIVE": "darkred",
            }

            df_timeline = df_timeline.sort_values(by=["time", "priority"], ascending=[True, False])

            fig = px.scatter(
                df_timeline,
                x="time",
                y="lane",
                color="type",
                color_discrete_map=color_map,
                hover_data=["type", "label", "actor"],
                title="Investigation Timeline",
            )

            fig.update_traces(marker=dict(size=12))

            fig.update_layout(
                height=520,
                yaxis_title="Investigation Flow",
                xaxis_title="Time",
                legend_title="Event Type",
                yaxis=dict(
                    categoryorder="array",
                    categoryarray=[
                        "Detection",
                        "Case Activity",
                        "Slack",
                        "Response",
                        "Governance",
                        "Forensics",
                        "Other",
                    ],
                ),
            )

            st.plotly_chart(fig, use_container_width=True)

    else:
        st.info("No timeline data yet.")

    # ----------------------------
    # 🔄 LIVE REFRESH (every 5s)
    # ----------------------------
    try:
        from streamlit_autorefresh import st_autorefresh
        st_autorefresh(interval=5000, key="sla_refresh")
    except Exception:
        pass

    # ----------------------------
    # 🔥 SLA CONFIG
    # ----------------------------
    SLA_RULES = {
        "CRITICAL": {"ack_minutes": 15, "close_minutes": 120},
        "HIGH": {"ack_minutes": 60, "close_minutes": 480},
        "MEDIUM": {"ack_minutes": 240, "close_minutes": 1440},
        "LOW": {"ack_minutes": 1440, "close_minutes": 4320},
    }

    severity = (
        case.get("auto_priority", "LOW")
        .replace("🔴 ", "")
        .replace("🟠 ", "")
        .replace("🟡 ", "")
        .replace("🟢 ", "")
        .upper()
        .strip()
    )

    sla = SLA_RULES.get(severity, SLA_RULES["LOW"])

    now = datetime.utcnow()
    created_time = datetime.utcfromtimestamp(case["created_at_ms"] / 1000)

    ack_deadline = created_time + timedelta(minutes=sla["ack_minutes"])
    close_deadline = created_time + timedelta(minutes=sla["close_minutes"])

    time_to_ack = (ack_deadline - now).total_seconds() / 60
    time_to_close = (close_deadline - now).total_seconds() / 60

    def get_sla_status(minutes):
        if minutes is None:
            return "UNKNOWN"
        try:
            minutes = float(minutes)
        except Exception:
            return "UNKNOWN"

        if minutes < 0:
            return "BREACHED"
        elif minutes < 15:
            return "AT_RISK"
        else:
            return "OK"

    def format_sla(minutes):
        status = get_sla_status(minutes)

        icon_map = {
            "BREACHED": "🔴",
            "AT_RISK": "🟠",
            "OK": "🟢",
            "UNKNOWN": "⚪",
        }

        return f"{icon_map[status]} {status.replace('_', ' ')}"

    def format_countdown(minutes):
        if minutes is None:
            return "—"

        total_seconds = int(minutes * 60)
        sign = "-" if total_seconds < 0 else ""
        total_seconds = abs(total_seconds)

        hrs = total_seconds // 3600
        mins = (total_seconds % 3600) // 60
        secs = total_seconds % 60

        return f"{sign}{hrs:02d}:{mins:02d}:{secs:02d}"

    status = get_sla_status(time_to_close)

    st.subheader("⏱ SLA & Escalation")

    col1, col2, col3 = st.columns(3)

    with col1:
        st.metric(
            "Time to Acknowledge",
            format_countdown(time_to_ack),
            format_sla(time_to_ack),
        )

    with col2:
        st.metric(
            "Time to Close",
            format_countdown(time_to_close),
            format_sla(time_to_close),
        )

    with col3:
        if status == "BREACHED":
            st.error("🚨 SLA BREACH — Immediate escalation required")

            breach_key = f"sla_breach_logged_{case_id}"

            if not st.session_state.get(breach_key):
                print("🚨 SLA BREACH TRIGGERED:", case_id)

                ledger.add_case_event(
                    case_id,
                    "SLA_BREACH",
                    "Case breached SLA",
                    actor="system",
                    details={
                        "case_id": case_id,
                        "severity": severity,
                        "time_to_close": time_to_close,
                        "close_deadline": str(close_deadline),
                    },
                )

                _enqueue_notify(
                    ledger,
                    "CRITICAL",
                    f"SLA breach for case {case_id}",
                    case_id=case_id,
                    priority=1,
                )

                st.session_state[breach_key] = True

        elif status == "AT_RISK":
            st.warning("⚠️ Escalation imminent")

            warning_key = f"sla_warning_logged_{case_id}"

            if not st.session_state.get(warning_key):
                ledger.add_case_event(
                    case_id,
                    "SLA_WARNING",
                    "Case nearing SLA breach",
                    actor="system",
                    details={
                        "case_id": case_id,
                        "severity": severity,
                        "time_to_close": time_to_close,
                        "close_deadline": str(close_deadline),
                    },
                )

                st.session_state[warning_key] = True

        elif status == "OK":
            st.success("Within SLA")

        else:
            st.info("SLA status unavailable")

    progress = max(0, min(1, time_to_close / sla["close_minutes"]))
    st.progress(progress)

    # -----------------------------
    # Attach Evidence
    # -----------------------------
    st.divider()
    st.subheader("Attach Evidence")

    evidence_id = st.text_input("Evidence ID")

    if st.button("🔗 Link Evidence"):
        ledger.add_case_evidence(case_id, evidence_id)
        st.success("Evidence linked")

    # -----------------------------
    # Show Linked Evidence
    # -----------------------------
    st.subheader("Linked Evidence")

    evidence = ledger.list_case_evidence(case_id)

    if evidence:
        for i, e in enumerate(evidence):
            col1, col2 = st.columns([3, 1])

            col1.write(f"{e.get('suggested_name')} ({e.get('evidence_id')[:12]})")

            if col2.button("Open", key=f"open_{e['evidence_id']}_{i}"):
                st.session_state["selected_evidence_id"] = e["evidence_id"]
                st.session_state["page"] = "Evidence Viewer"
                st.rerun()
    else:
        st.info("No evidence linked")

    # -----------------------------
    # Notes
    # -----------------------------
    st.divider()
    st.subheader("Analyst Notes")

    note = st.text_area("Add Note")

    if st.button("📝 Save Note"):
        ledger.add_case_note(case_id, note)

        ledger.add_case_event(
            case_id,
            "NOTE_ADDED",
            "Analyst note added",
            actor="analyst_user",
            details={"note": note},
        )

        st.success("Note added")

    notes = ledger.list_case_notes(case_id)

    for n in notes:
        st.write(n["note"])

    st.divider()
    st.subheader("🛡️ Response Actions")

    from core.cases.response_engine import run_response_action

    response_action = st.selectbox(
        "Choose Response Action",
        [
            "ISOLATE_EVIDENCE",
            "QUARANTINE_CASE",
            "ESCALATE_TO_MANAGER",
            "REQUEST_REVIEW",
        ],
    )

    if st.button("▶ Run Response Action"):
        try:
            result = run_response_action(
                storage=storage,
                case_id=case_id,
                action_type=response_action,
                actor="analyst_user",
            )

            ledger.add_case_event(
                case_id,
                "RESPONSE_ACTION",
                response_action,
                actor="analyst_user",
                details={
                    "action": response_action,
                    "result": str(result),
                },
            )

            st.success(f"Response action completed: {response_action}")
            st.json(result)
            st.rerun()

        except Exception as e:
            st.error(f"Response action failed: {e}")

    st.subheader("Response Action History")

    actions = ledger.list_response_actions(case_id)

    if actions:
        df_actions = pd.DataFrame(actions)

        if "created_at_ms" in df_actions.columns:
            df_actions["time"] = pd.to_datetime(df_actions["created_at_ms"], unit="ms")

        action_cols = [c for c in ["time", "action_type", "status", "actor"] if c in df_actions.columns]

        st.dataframe(
            df_actions[action_cols],
            use_container_width=True,
        )
    else:
        st.info("No response actions executed yet.")

    st.divider()
    st.subheader("📚 Response Playbooks")

    from core.cases.response_engine import (
        execute_playbook,
        approve_and_execute_response_action,
        reject_response_action,
    )

    playbooks = ledger.list_response_playbooks()
    selected_approval = None

    if playbooks:
        playbook_map = {
            f"{p['name']} ({p['playbook_id']})": p
            for p in playbooks
        }

        st.divider()
        st.subheader("✅ Approval Queue")

        approvals = ledger.list_response_approvals(case_id)

        if approvals:
            df_approvals = pd.DataFrame(approvals)

            if "created_at_ms" in df_approvals.columns:
                df_approvals["time"] = pd.to_datetime(df_approvals["created_at_ms"], unit="ms")

            approval_cols = [c for c in ["id", "time", "action_type", "requested_by", "approved_by", "status"] if c in df_approvals.columns]

            st.dataframe(
                df_approvals[approval_cols],
                use_container_width=True,
            )

            pending = [a for a in approvals if a.get("status") == "PENDING"]

            if pending:
                approval_map = {
                    f"#{a['id']} | {a['action_type']} | requested by {a['requested_by']}": a
                    for a in pending
                }

                selected_approval_label = st.selectbox(
                    "Select Pending Approval",
                    list(approval_map.keys()),
                )
                selected_approval = approval_map[selected_approval_label]

                c1, c2 = st.columns(2)

                with c1:
                    if st.button("👍 Approve + Execute"):
                        try:
                            user_role = st.session_state.get("user_role", "ANALYST")

                            try:
                                result = approve_and_execute_response_action(
                                    storage=storage,
                                    approval_id=int(selected_approval["id"]),
                                    approved_by="current_user",
                                    user_role=user_role,
                                )
                                st.success("Approved + Executed")
                                st.json(result)
                                st.rerun()

                            except PermissionError as e:
                                st.error(f"Permission denied: {e}")

                            except Exception as e:
                                st.error(str(e))

                        except Exception as e:
                            st.error(f"Approval failed: {e}")

                with c2:
                    if st.button("👎 Reject"):
                        try:
                            result = reject_response_action(
                                storage=storage,
                                approval_id=int(selected_approval["id"]),
                                approved_by="approver_user",
                            )
                            st.success("Approval rejected.")
                            st.json(result)
                            st.rerun()
                        except Exception as e:
                            st.error(f"Reject failed: {e}")
        else:
            st.info("No approvals recorded.")

        selected_pb_label = st.selectbox("Choose Playbook", list(playbook_map.keys()))
        selected_pb = playbook_map[selected_pb_label]

        st.write(selected_pb.get("description", ""))

        st.subheader("🔐 Approval Permissions")

        from core.auth.permissions import can_approve

        user_role = st.session_state.get("user_role", "ANALYST")

        st.write(f"Current Role: **{user_role}**")

        if selected_approval:
            action_type = selected_approval["action_type"]
            allowed = can_approve(user_role, action_type)

            if allowed:
                st.success(f"✅ You CAN approve {action_type}")
            else:
                st.warning(f"⛔ You CANNOT approve {action_type}")

        if st.button("▶ Run Playbook"):
            try:
                results = execute_playbook(
                    storage=storage,
                    case_id=case_id,
                    playbook_row=selected_pb,
                    actor="analyst_user",
                )
                st.success("Playbook submitted.")
                st.json(results)
                st.rerun()
            except Exception as e:
                st.error(f"Playbook execution failed: {e}")
    else:
        st.info("No playbooks available.")

    st.divider()
    st.subheader("📊 Case Risk Dashboard")

    with storage.ledger._connect() as con:
        case_rows = con.execute("""
            SELECT DISTINCT case_id
            FROM alerts
            WHERE case_id IS NOT NULL
            ORDER BY case_id
        """).fetchall()

    case_ids = [r["case_id"] if isinstance(r, dict) else r[0] for r in case_rows]

    if not case_ids:
        st.info("No cases available for risk scoring.")
    else:
        risk_rows = [_calculate_case_risk(storage, cid) for cid in case_ids]
        risk_df = pd.DataFrame(risk_rows)

        col1, col2, col3, col4 = st.columns(4)

        col1.metric("Open Cases", len(risk_df))
        col2.metric("Critical Cases", int((risk_df["risk_score"] >= 85).sum()))
        col3.metric("Total Alerts", int(risk_df["alert_count"].sum()))
        col4.metric("Custody Gaps", int(risk_df["custody_gaps"].max() if not risk_df.empty else 0))

        st.dataframe(
            risk_df[[
                "case_id",
                "priority",
                "risk_score",
                "alert_count",
                "critical_alerts",
                "high_alerts",
                "categories",
                "custody_gaps",
            ]],
            use_container_width=True,
        )

    if st.button("🧪 Test Notify"):
        print("🔥 BUTTON CLICKED")
        print("🔥 QUEUING NOTIFY TASK")

        _enqueue_notify(
            ledger,
            "CRITICAL",
            "Manual test from investigation page",
            case_id=case_id,
            priority=1,
        )

        st.success("Test alert queued")