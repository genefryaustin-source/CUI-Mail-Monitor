# core/ui/metrics_page.py
# core/ui/metrics_page.py
import streamlit as st
import pandas as pd
import json
from typing import Any
from streamlit_autorefresh import st_autorefresh
import time


from veridion_theme import apply_theme
apply_theme()

# Use this block to show title only once
if "title_shown" not in st.session_state:
    st.session_state.title_shown = False

with st.sidebar:
    if not st.session_state.title_shown:
        st.markdown('<h1 class="veridion-sidebar-title">Veridion Pro</h1>', unsafe_allow_html=True)
        st.session_state.title_shown = True
def compute_case_metrics(storage):


    with storage.ledger._connect() as con:
        cases = con.execute("""
            SELECT case_id, created_at_ms, status
            FROM cases
        """).fetchall()

        events = con.execute("""
            SELECT case_id, event_type, created_at_ms
            FROM case_events
        """).fetchall()

    df_cases = pd.DataFrame([dict(r) for r in cases])
    df_events = pd.DataFrame([dict(r) for r in events])

    if df_cases.empty:
        return None

    results = []

    for _, case in df_cases.iterrows():
        cid = case["case_id"]
        created = case["created_at_ms"]

        ev = df_events[df_events["case_id"] == cid]

        ack = ev[ev["event_type"] == "SLACK_ACK"]
        close = ev[ev["event_type"].isin(["SLACK_CLOSE", "CASE_CLOSED"])]

        ack_ts = ack["created_at_ms"].min() if not ack.empty else None
        close_ts = close["created_at_ms"].min() if not close.empty else None

        results.append({
            "case_id": cid,
            "created": created,
            "ack_ts": ack_ts,
            "close_ts": close_ts,
            "time_to_ack": (ack_ts - created)/60000 if ack_ts else None,
            "time_to_close": (close_ts - created)/60000 if close_ts else None
        })

    return pd.DataFrame(results)

def _dynamic_sla_minutes(risk_score: float):
    if risk_score >= 85:
        return {"ack": 15, "close": 120}
    if risk_score >= 65:
        return {"ack": 60, "close": 480}
    if risk_score >= 35:
        return {"ack": 240, "close": 1440}
    return {"ack": 1440, "close": 4320}

def render_metrics_page(storage: Any):
    ledger = storage.ledger
    st_autorefresh(interval=3000, key="live_ops_refresh")
    st.subheader("📈 Metrics Dashboard")

    # ---------------------------------------
    # 🧠 SLA & MTTR (INSERT HERE)
    # ---------------------------------------
    case_df = compute_case_metrics(storage)

    if case_df is not None and not case_df.empty:

        col1, col2, col3, col4 = st.columns(4)

        col1.metric(
            "Avg Ack (min)",
            round(case_df["time_to_ack"].dropna().mean(), 2)
            if case_df["time_to_ack"].notna().any() else "N/A"
        )

        col2.metric(
            "Avg Close (MTTR)",
            round(case_df["time_to_close"].dropna().mean(), 2)
            if case_df["time_to_close"].notna().any() else "N/A"
        )

        col3.metric(
            "Closed Cases",
            case_df["time_to_close"].notna().sum()
        )

        SLA_THRESHOLD = 120
        case_df["breached"] = case_df["time_to_close"] > SLA_THRESHOLD

        breach_rate = case_df["breached"].mean() * 100 if len(case_df) else 0

        col4.metric("SLA Breach %", round(breach_rate, 2))

        st.markdown("### 📋 Case Lifecycle")
        st.dataframe(case_df, use_container_width=True)

    else:
        st.info("No case metrics yet.")

    # ---------------------------------------
    # EXISTING METRICS QUERY (UNCHANGED)
    # ---------------------------------------
    with storage.ledger._connect() as con:
        rows = con.execute("""
            SELECT *
            FROM metrics
            ORDER BY ts_ms DESC
            LIMIT 500
        """).fetchall()

    metrics = [dict(r) for r in rows]

    if not metrics:
        st.info("No metrics recorded yet.")
        return

    df = pd.DataFrame(metrics)

    # ---------------------------------------
    # 🧠 Normalize fields
    # ---------------------------------------
    if "ts_ms" in df.columns:
        df["time"] = pd.to_datetime(df["ts_ms"], unit="ms")

    if "tags_json" in df.columns:
        def extract_case_id(tags):
            try:
                return json.loads(tags).get("case_id")
            except:
                return None

        df["case_id"] = df["tags_json"].apply(extract_case_id)

        st.markdown("### 📊 MTTR Distribution")
        st.bar_chart(case_df["time_to_close"].dropna())

    # ---------------------------------------
    # 🎯 Filters
    # ---------------------------------------
    st.markdown("### 🔎 Filters")

    metric_types = sorted(df["name"].dropna().unique())
    selected_metric = st.selectbox("Metric Type", ["ALL"] + metric_types)

    case_ids = sorted(df["case_id"].dropna().unique())
    selected_case = st.selectbox("Case Filter", ["ALL"] + case_ids)

    filtered_df = df.copy()

    if selected_metric != "ALL":
        filtered_df = filtered_df[filtered_df["name"] == selected_metric]

    if selected_case != "ALL":
        filtered_df = filtered_df[filtered_df["case_id"] == selected_case]

    if filtered_df.empty:
        st.warning("No data for selected filters.")
        return

    # ---------------------------------------
    # 📊 CHART VIEW
    # ---------------------------------------
    st.markdown("### 📊 Metric Trend")

    chart_df = filtered_df.sort_values("time")

    if selected_metric != "ALL":
        st.line_chart(
            chart_df.set_index("time")["value"]
        )
    else:
        pivot = chart_df.pivot_table(
            index="time",
            columns="name",
            values="value"
        )
        st.line_chart(pivot)

    # ---------------------------------------
    # 🔥 EVENT SPIKE DETECTION
    # ---------------------------------------
    if "value" in chart_df.columns and len(chart_df) > 2:
        latest = chart_df.iloc[-1]["value"]
        prev = chart_df.iloc[-2]["value"]

        delta = latest - prev

        if abs(delta) > 10:
            st.markdown("### 🚨 Significant Change Detected")
            st.warning(f"Δ Change: {delta}")

    # ---------------------------------------
    # 📋 RAW TABLE
    # ---------------------------------------
    st.markdown("### 📋 Raw Metrics")

    st.dataframe(
        filtered_df.sort_values("time", ascending=False),
        use_container_width=True
    )

    st.subheader("📊 Task Queue Overview")

    with storage.ledger._connect() as con:
        rows = con.execute("""
            SELECT status, COUNT(*) as count
            FROM task_queue
            GROUP BY status
        """).fetchall()

    if rows:

        df = pd.DataFrame([dict(r) for r in rows])
        st.bar_chart(df.set_index("status"))
    else:
        st.info("No tasks in queue")

    st.subheader("🧵 Live Task Queue")

    with storage.ledger._connect() as con:
        rows = con.execute("""
            SELECT id, task_type, status, priority, attempts, created_at_ms
            FROM task_queue
            ORDER BY priority ASC, created_at_ms ASC
            LIMIT 100
        """).fetchall()

    if rows:

        df = pd.DataFrame([dict(r) for r in rows])

        df["created_at"] = pd.to_datetime(df["created_at_ms"], unit="ms")

        st.dataframe(df, use_container_width=True)

    st.subheader("📡 Live Operations Feed")

    events = storage.ledger.get_worker_events(limit=100)

    if events:

        df_events = pd.DataFrame(events)
        df_events["time"] = pd.to_datetime(df_events["created_at_ms"], unit="ms")

        st.dataframe(
            df_events[[
                "time",
                "worker_name",
                "event_type",
                "message",
                "task_id",
                "job_id",
            ]],
            use_container_width=True,
        )
    else:
        st.info("No live worker events yet.")



    st.subheader("⏱ Risk-Based SLA Dashboard")

    with storage.ledger._connect() as con:
        rows = con.execute("""
            SELECT
                c.case_id,
                c.title,
                c.status,
                c.assigned_to,
                c.created_at_ms,
                COALESCE(MAX(CASE WHEN m.name = 'risk_score' THEN m.value END), 0) AS risk_score
            FROM cases c
            LEFT JOIN metrics m
                ON m.tags_json LIKE '%' || c.case_id || '%'
            GROUP BY c.case_id
            ORDER BY c.created_at_ms DESC
        """).fetchall()

    if rows:


        now_ms = int(time.time() * 1000)
        sla_rows = []

        for r in rows:
            risk_score = float(r["risk_score"] or 0)
            sla = _dynamic_sla_minutes(risk_score)

            age_min = (now_ms - int(r["created_at_ms"] or now_ms)) / 60000
            ack_remaining = sla["ack"] - age_min
            close_remaining = sla["close"] - age_min

            if close_remaining < 0:
                state = "BREACHED"
            elif close_remaining < 30:
                state = "AT_RISK"
            else:
                state = "OK"

            sla_rows.append({
                "case_id": r["case_id"],
                "title": r["title"],
                "status": r["status"],
                "assigned_to": r["assigned_to"],
                "risk_score": risk_score,
                "age_min": round(age_min, 1),
                "ack_sla_min": sla["ack"],
                "close_sla_min": sla["close"],
                "ack_remaining_min": round(ack_remaining, 1),
                "close_remaining_min": round(close_remaining, 1),
                "sla_state": state,
            })

        sla_df = pd.DataFrame(sla_rows)

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Open Cases", int((sla_df["status"] != "RESOLVED").sum()))
        c2.metric("SLA Breached", int((sla_df["sla_state"] == "BREACHED").sum()))
        c3.metric("At Risk", int((sla_df["sla_state"] == "AT_RISK").sum()))
        c4.metric("Avg Risk", round(sla_df["risk_score"].mean(), 1))

        def color_sla(val):
            if val == "BREACHED":
                return "background-color: #ff4d4f; color: white;"  # red
            elif val == "AT_RISK":
                return "background-color: #faad14; color: black;"  # yellow
            elif val == "OK":
                return "background-color: #52c41a; color: white;"  # green
            return ""

        styled_df = sla_df.style.map(
            color_sla,
            subset=["sla_state"]
        )

        st.dataframe(styled_df, use_container_width=True)

    else:
        st.info("No case SLA data yet.")

    st.markdown("### 🔎 Drill Down Into Case")

    case_options = sla_df["case_id"].tolist()

    breached_cases = sla_df[sla_df["sla_state"] == "BREACHED"]

    if not breached_cases.empty:
        st.error(f"🚨 {len(breached_cases)} SLA BREACHES DETECTED")

        st.dataframe(breached_cases, use_container_width=True)

    selected_case = st.selectbox("Select Case", case_options)

    if selected_case:
        with storage.ledger._connect() as con:
            case = con.execute("""
                SELECT *
                FROM cases
                WHERE case_id = ?
            """, (selected_case,)).fetchone()

        if case:
            st.markdown("#### 📂 Case Details")
            st.json(dict(case))

            # 🔥 timeline
            timeline = storage.ledger.build_case_timeline(selected_case)

            if timeline:

                tdf = pd.DataFrame(timeline)
                tdf["time"] = pd.to_datetime(tdf["ts"], unit="ms")

                st.markdown("#### 🧵 Timeline")
                st.dataframe(tdf.sort_values("time"), use_container_width=True)



    st.subheader("🤖 AI Routing Decisions")

    with storage.ledger._connect() as con:
        rows = con.execute("""
            SELECT case_id, event_type, message, actor, created_at_ms, details_json
            FROM case_events
            WHERE event_type = 'AI_ROUTED'
            ORDER BY created_at_ms DESC
            LIMIT 100
        """).fetchall()

    if rows:


        rdf = pd.DataFrame([dict(r) for r in rows])
        rdf["time"] = pd.to_datetime(rdf["created_at_ms"], unit="ms")
        st.dataframe(rdf, use_container_width=True)
    else:
        st.info("No AI routing decisions yet.")