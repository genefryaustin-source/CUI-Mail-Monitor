import json
import pandas as pd
import streamlit as st
import time


def _safe_json(value):
    if not value:
        return {}
    if isinstance(value, dict):
        return value
    try:
        return json.loads(value)
    except Exception:
        return {}


def _ms_to_age_min(ms):
    if not ms:
        return 0
    return round((int(time.time() * 1000) - int(ms)) / 60000, 1)


def render_sla_dashboard_page(storage):
    st.title("🔥 SLA Intelligence Dashboard")
    st.caption("Real-time SLA breaches, predicted risk, case escalations, and worker scaling signals.")

    ledger = storage.ledger

    # -------------------------------------------------
    # LOAD DATA
    # -------------------------------------------------
    try:
        breaches = ledger.detect_queue_sla_breaches() if hasattr(ledger, "detect_queue_sla_breaches") else []
    except Exception as e:
        st.error(f"SLA breach query failed: {e}")
        breaches = []

    try:
        predictions = ledger.predict_sla_breaches() if hasattr(ledger, "predict_sla_breaches") else []
    except Exception as e:
        st.error(f"Predictive SLA query failed: {e}")
        predictions = []

    try:
        events = ledger.list_recent_sla_events(limit=100) if hasattr(ledger, "list_recent_sla_events") else []
    except Exception as e:
        st.warning(f"SLA event history unavailable: {e}")
        events = []

    try:
        worker_stats = ledger.get_worker_scaling_snapshot() if hasattr(ledger, "get_worker_scaling_snapshot") else {}
    except Exception as e:
        st.warning(f"Worker scaling snapshot unavailable: {e}")
        worker_stats = {}

    # -------------------------------------------------
    # TOP METRICS
    # -------------------------------------------------
    critical_count = sum(1 for b in breaches if int(b.get("priority", 5)) <= 1)
    high_count = max(len(breaches) - critical_count, 0)
    predicted_count = len(predictions)
    pending_count = worker_stats.get("pending", 0)
    processing_count = worker_stats.get("processing", 0)
    recommended_workers = worker_stats.get("recommended_workers", 1)

    c1, c2, c3, c4, c5 = st.columns(5)

    c1.metric("Active Breaches", len(breches := breaches))
    c2.metric("Critical Breaches", critical_count)
    c3.metric("Predicted Breaches", predicted_count)
    c4.metric("Pending Jobs", pending_count)
    c5.metric("Recommended Workers", recommended_workers)

    st.divider()

    # -------------------------------------------------
    # ACTIVE BREACHES
    # -------------------------------------------------
    st.subheader("🚨 Active SLA Breaches")

    if breaches:
        df_breaches = pd.DataFrame(breaches)

        preferred_cols = [
            "task_id",
            "task_type",
            "priority",
            "age_min",
            "threshold_min",
            "case_id",
            "owner",
            "status",
        ]

        show_cols = [c for c in preferred_cols if c in df_breaches.columns]
        st.dataframe(df_breaches[show_cols], use_container_width=True, hide_index=True)

    else:
        st.success("No active SLA breaches.")

    st.divider()

    # -------------------------------------------------
    # PREDICTED BREACHES
    # -------------------------------------------------
    st.subheader("🔮 Predicted SLA Breaches")

    if predictions:
        df_pred = pd.DataFrame(predictions)

        preferred_cols = [
            "task_id",
            "job_id",
            "eta_seconds",
            "risk",
            "progress_current",
            "progress_total",
        ]

        show_cols = [c for c in preferred_cols if c in df_pred.columns]
        st.dataframe(df_pred[show_cols], use_container_width=True, hide_index=True)

    else:
        st.info("No predicted SLA breach risk detected.")

    st.divider()

    # -------------------------------------------------
    # WORKER AUTOSCALE SIGNAL
    # -------------------------------------------------
    st.subheader("⚙️ Worker Autoscale Signal")

    wc1, wc2, wc3, wc4 = st.columns(4)

    wc1.metric("Pending", pending_count)
    wc2.metric("Processing", processing_count)
    wc3.metric("Active Workers", worker_stats.get("active_workers", 0))
    wc4.metric("Target Workers", recommended_workers)

    scale_reason = worker_stats.get("reason", "No autoscale reason available.")
    st.info(scale_reason)

    if worker_stats.get("should_scale_up"):
        st.warning("Scale-up recommended.")
    elif worker_stats.get("should_scale_down"):
        st.info("Scale-down may be safe.")
    else:
        st.success("Current worker capacity appears sufficient.")

    st.divider()

    # -------------------------------------------------
    # SLA EVENT HISTORY
    # -------------------------------------------------
    st.subheader("🧾 SLA Event History")

    if events:
        rows = []

        for e in events:
            data = _safe_json(e.get("event_data"))
            rows.append({
                "Event": e.get("event_type"),
                "Evidence/Task": e.get("evidence_id"),
                "Age Min": _ms_to_age_min(e.get("created_at_ms")),
                "Case": data.get("case_id"),
                "Priority": data.get("priority"),
                "Owner": data.get("owner"),
                "Details": data,
            })

        df_events = pd.DataFrame(rows)
        st.dataframe(df_events, use_container_width=True, hide_index=True)

    else:
        st.info("No SLA events recorded yet.")