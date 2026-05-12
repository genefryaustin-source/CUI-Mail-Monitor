# core/ui/scan_page.py
import datetime
from typing import Any
import time
import pandas as pd
import streamlit as st
from core.utils.case_utils import generate_case_id
from core.alerts.notifier import notify
import json
import io
import re
from datetime import datetime
from veridion_theme import apply_theme
apply_theme()
with st.sidebar:
    st.markdown('<h1 class="veridion-sidebar-title">Veridion Pro</h1>', unsafe_allow_html=True)

def normalize_severity(val):
    if not val:
        return "LOW"

    val = str(val).upper().strip()

    # Remove emojis
    val = val.replace("🔴", "").replace("🟠", "").replace("🟢", "").strip()

    if val in ["CRITICAL", "HIGH", "MEDIUM", "LOW"]:
        return val

    return "LOW"



def render_scan_page(storage: Any):
    st.title("📡 Scan Control")

    ledger = storage.ledger

    # ----------------------------------------
    # 🔍 LOAD DETECTION FROM EVENTS (NEW)
    # ----------------------------------------
    def load_detection_rows(ledger):
        with ledger._connect() as con:
            rows = con.execute("""
                SELECT 
                    e.evidence_id,
                    e.created_at_ms,

                    -- 🔥 PRIMARY CATEGORY (NEW MODEL + BACKWARD COMPAT)
                    COALESCE(
                        json_extract(ev.data_json, '$.cui_detection.primary_category'),
                        json_extract(ev.data_json, '$.cui_detection.categories[0]')
                    ) AS category,

                    -- 🔥 HIT COUNT
                    COALESCE(
                        json_extract(ev.data_json, '$.cui_detection.hit_count'),
                        0
                    ) AS hit_count,

                    -- 🔥 RISK LEVEL (TOP-LEVEL FIELD)
                    COALESCE(
                        json_extract(ev.data_json, '$.risk_level'),
                        'LOW'
                    ) AS risk_level,

                    -- 🔥 SOURCE TYPE (EMAIL / ATTACHMENT)
                    COALESCE(
                        json_extract(ev.data_json, '$.source_type'),
                        'email'
                    ) AS source_type,

                    -- 🔥 OPTIONAL METADATA (for grouping later)
                    json_extract(ev.data_json, '$.email_metadata.from') AS sender,
                    json_extract(ev.data_json, '$.email_metadata.subject') AS subject,
                    json_extract(ev.data_json, '$.email_metadata.thread_id') AS thread_id,

                    ev.event_type

                FROM evidence_records e

                LEFT JOIN evidence_events ev
                    ON json_extract(ev.data_json, '$.evidence_id') = e.evidence_id

                WHERE ev.event_type IN (
                    'EVIDENCE_CUI_ANALYSIS',
                    'ATTACHMENT_CUI_ANALYSIS'
                )

                AND ev.created_at_ms = (
                    SELECT MAX(ev2.created_at_ms)
                    FROM evidence_events ev2
                    WHERE 
                        ev2.event_type = ev.event_type
                        AND json_extract(ev2.data_json, '$.evidence_id') = e.evidence_id
                )

                ORDER BY e.created_at_ms DESC
                LIMIT 100
            """).fetchall()

        return [dict(r) for r in rows]

    # ----------------------------
    # 📡 LOAD IMAP CONFIGS
    # ----------------------------
    imap_configs = getattr(storage, "imap_configs", [])

    # ----------------------------
    # 🔌 PROVIDER SELECT
    # ----------------------------
    providers = ["gmail"]
    if imap_configs:
        providers.append("imap")

    provider = st.selectbox("Provider", providers)

    st.subheader("Scan Configuration")

    # ----------------------------
    # 📧 MAILBOX SELECTION
    # ----------------------------
    mailbox = None
    selected_config = None

    if provider == "imap":
        if not imap_configs:
            st.warning("No IMAP accounts configured")
            return

        selected_config = st.selectbox(
            "Select IMAP Account",
            options=imap_configs,
            format_func=lambda x: f"{x.get('provider')} — {x.get('username')} @ {x.get('host')}"
        )

        mailbox = selected_config.get("mailbox", "INBOX")

        st.info(f"Using mailbox: {mailbox}")

    elif provider == "gmail":
        connected_mailboxes = []
        if hasattr(ledger, "list_connected_mailboxes"):
            connected_mailboxes = ledger.list_connected_mailboxes(provider="gmail")

        if connected_mailboxes:
            mailbox = st.selectbox("Connected Mailbox", connected_mailboxes)
        else:
            mailbox = st.text_input("Mailbox")

    # ----------------------------
    # ⚙️ SCAN SETTINGS
    # ----------------------------
    lookback = st.number_input("Lookback Hours", min_value=1, max_value=720, value=168)
    attachments_only = st.checkbox("Attachments Only", value=True)
    max_messages = st.number_input("Max Messages", min_value=1, max_value=5000, value=100)

    # ----------------------------
    # 🚀 ACTIONS
    # ----------------------------
    col1, col2 = st.columns(2)

    with col1:
        if st.button("🚀 Enqueue Scan", use_container_width=True):

            mailbox = (mailbox or "").strip()

            if not mailbox:
                st.error("Please select or enter a mailbox.")
                return

            # ----------------------------
            # 📧 GMAIL
            # ----------------------------
            if provider == "gmail":
                if hasattr(ledger, "get_oauth_token"):
                    token = ledger.get_oauth_token("gmail", mailbox)

                    if not token:
                        st.error(
                            f"No Gmail OAuth token found for {mailbox}. "
                            "Connect it from the Admin page first."
                        )
                        return

                job_id = ledger.enqueue_scan(
                    provider="gmail",
                    mailbox=mailbox,
                    lookback_hours=int(lookback),
                    attachments_only=attachments_only,
                    max_messages=int(max_messages),
                    payload={},
                )

                st.success(f"Gmail scan enqueued (job_id={job_id})")
                st.rerun()

            # ----------------------------
            # 📡 IMAP
            # ----------------------------
            elif provider == "imap":

                job_id = ledger.enqueue_scan(
                    provider="imap",
                    mailbox=mailbox,
                    lookback_hours=int(lookback),
                    attachments_only=attachments_only,
                    max_messages=int(max_messages),
                    payload=selected_config,  # 🔥 CRITICAL
                )

                st.success(f"IMAP scan enqueued (job_id={job_id})")
                st.rerun()

    with col2:
        if st.button("🔄 Refresh Jobs", use_container_width=True):
            st.rerun()

    auto_refresh = st.checkbox("Auto Refresh", value=True)
    #if auto_refresh:
        #import time
        #time.sleep(2)
        #st.rerun()
    st.divider()
    st.subheader("🚀 Running Jobs")
    running_jobs = []

    if hasattr(ledger, "list_running_jobs"):
        running_jobs = ledger.list_running_jobs(limit=20)

    if running_jobs:

        for job in running_jobs:
            col1, col2, col3, col4, col5 = st.columns([1, 2, 4, 2, 2])

            job_id = job.get("id")
            mailbox = job.get("mailbox")
            status = job.get("status")

            current = job.get("progress_current") or 0
            total = job.get("progress_total") or 1

            progress = current / max(total, 1)

            # ----------------------------
            # Duration (SAFE VERSION)
            # ----------------------------
            started = job.get("started_at_ms")

            duration_sec = 0  # 🔥 ALWAYS defined
            duration = "-"  # 🔥 ALWAYS defined

            if started:
                duration_sec = int((time.time() * 1000 - started) / 1000)
                duration = f"{duration_sec}s"

    st.divider()
    st.subheader("⚡ Bulk Job Controls")

    b1, b2, b3, b4 = st.columns(4)

    with b1:
        if st.button("🔁 Retry All Failed"):
            ledger.retry_all_failed()
            st.success("All failed jobs requeued")
            st.rerun()

    with b2:
        if st.button("🗑 Delete Completed"):
            ledger.delete_completed()
            st.warning("Completed jobs deleted")
            st.rerun()

    with b3:
        if st.button("🛑 Cancel Running"):
            ledger.cancel_all_running()
            st.error("All running jobs cancelled")
            st.rerun()

    with b4:
        if st.button("☢️ Clear ALL Jobs"):
            if st.checkbox("Confirm full wipe"):
                ledger.clear_all_jobs()
                st.error("ALL jobs deleted")
                st.rerun()

    st.divider()
    st.subheader("📋 Scan Job Queue")



    jobs = ledger.list_scan_jobs(limit=100) if hasattr(ledger, "list_scan_jobs") else []

    if jobs:
        for job in jobs:
            col1, col2, col3, col4, col5, col6 = st.columns([1, 2, 2, 2, 2, 3])

            jid = job.get("id")
            status = (job.get("status") or "").upper()
            completed = job.get("completed_at_ms")

            col1.write(jid)
            col2.write(job.get("provider"))
            col3.write(job.get("mailbox"))

            # Normalize status display
            if status == "RUNNING" and completed:
                status = "COMPLETED"

            col4.write(status)
            col5.write(job.get("last_error") or "-")

            # ------------------------
            # ACTION COLUMN
            # ------------------------
            with col6:

                # RUNNING / QUEUED → Cancel
                if status in ("RUNNING", "QUEUED"):
                    if st.button("Cancel", key=f"cancel_{jid}"):
                        ledger.cancel_scan(jid)
                        st.warning(f"Cancelled job {jid}")
                        st.rerun()

                # FAILED → Retry + Delete
                elif status == "FAILED":
                    c1, c2 = st.columns(2)

                    with c1:
                        if st.button("Retry", key=f"retry_{jid}"):
                            ledger.retry_scan(jid)
                            st.success(f"Requeued job {jid}")
                            st.rerun()

                    with c2:
                        if st.button("Delete", key=f"delete_{jid}"):
                            ledger.delete_scan(jid)
                            st.error(f"Deleted job {jid}")
                            st.rerun()

                # COMPLETED → Re-run + Delete
                elif status == "COMPLETED":
                    c1, c2 = st.columns(2)

                    with c1:
                        if st.button("Re-run", key=f"rerun_{jid}"):
                            ledger.retry_scan(jid)
                            st.success(f"Re-running job {jid}")
                            st.rerun()

                    with c2:
                        if st.button("Delete", key=f"delete_{jid}"):
                            ledger.delete_scan(jid)
                            st.error(f"Deleted job {jid}")
                            st.rerun()

    else:
        st.info("No scan jobs found.")

    st.divider()
    st.subheader("🔍 Detected CUI Evidence")

    rows = load_detection_rows(ledger)

    st.subheader("Detected CUI Evidence")

    for r in rows:
        label = "📎 Attachment" if r["event_type"] == "ATTACHMENT_CUI_ANALYSIS" else "✉️ Email"

        # ✅ DEFINE FIRST (REAL PYTHON)
        cui_val = r.get("has_cui", False)

        # ✅ RENDER MARKDOWN (TEXT ONLY)
        st.markdown(f"""
    {label}  
    **{r['evidence_id'][:8]}**
    Categories: {r.get('categories', [])}  
    Hits: {r.get('hit_count', 0)}
    """)

        # ✅ RENDER CUI STATUS SEPARATELY
        st.write(f"🛡️ CUI: {'🟥 YES' if cui_val else '🟩 NO'}")

        st.divider()


    st.divider()
    st.subheader("📊 Scan Results")

    if hasattr(ledger, "get_scan_stats"):
        stats = ledger.get_scan_stats()
        st.write("DEBUG STATS:", stats)

        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Total Jobs", stats.get("total_jobs", 0))
        c2.metric("Queued", stats.get("queued", 0))
        c3.metric("Running", stats.get("running", 0))
        c4.metric("Completed", stats.get("completed", 0))
        c5.metric("Failed", stats.get("failed", 0))

        if stats.get("last_run"):
            ts = datetime.fromtimestamp(stats["last_run"] / 1000)
            st.caption(f"🕒 Last Scan Run: {ts}")

    if "scan_auto_refresh_count" not in st.session_state:
        st.session_state["scan_auto_refresh_count"] = 0

    if auto_refresh and st.session_state["scan_auto_refresh_count"] < 10:

        st.session_state["scan_auto_refresh_count"] += 1
        time.sleep(2)
        st.rerun()

    if not auto_refresh:
        st.session_state["scan_auto_refresh_count"] = 0

    st.divider()
    st.subheader("📊 Scan Job Analytics")
    print("🔥 ANALYTICS DB PATH:", getattr(ledger, "db_path", "UNKNOWN"))
    if hasattr(ledger, "get_scan_analytics"):
        stats = ledger.get_scan_analytics()

        c1, c2, c3, c4 = st.columns(4)

        c1.metric("Total Jobs", stats["total"])
        c2.metric("Completed", stats["completed"])
        c3.metric("Failed", stats["failed"])
        c4.metric("Success Rate", f"{stats['success_rate']:.1f}%")

        st.metric(
            "Avg Duration (sec)",
            f"{(stats['avg_duration_ms'] or 0) / 1000:.2f}"
        )

        # ----------------------------
        # 📈 JOB TREND
        # ----------------------------
        st.subheader("📈 Jobs Over Time")


        if stats["recent_jobs"]:
            df = pd.DataFrame(stats["recent_jobs"])
            df = df.sort_values("day")

            st.line_chart(df.set_index("day")["jobs"])

        # ----------------------------
        # ❌ TOP ERRORS
        # ----------------------------
        st.subheader("❌ Top Errors")

        if stats["top_errors"]:
            err_df = pd.DataFrame(stats["top_errors"])
            st.dataframe(err_df, use_container_width=True)
        else:
            st.info("No errors recorded")

        # ----------------------------
        # 📧 TOP MAILBOXES
        # ----------------------------
        st.subheader("📧 Most Active Mailboxes")

        if stats["top_mailboxes"]:
            mb_df = pd.DataFrame(stats["top_mailboxes"])
            st.dataframe(mb_df, use_container_width=True)

        # ============================
        # 🚨 ALERTS + CASES SYSTEM
        # ============================



        st.subheader("🚨 CUI Detections")

        # ----------------------------
        # EVIDENCE-LEVEL CUI QUERY
        # ----------------------------
        with storage.ledger._connect() as con:
            evidence_rows = con.execute("""
                SELECT 
                    e.evidence_id,
                    e.created_at_ms AS created,

                    COALESCE(
                        json_extract(ev.data_json, '$.cui_detection.primary_category'),
                        json_extract(ev.data_json, '$.cui_detection.categories[0]'),
                        'UNCATEGORIZED'
                    ) AS category,

                    CAST(
                        COALESCE(json_extract(ev.data_json, '$.cui_detection.hit_count'), 0)
                        AS INTEGER
                    ) AS hit_count,

                    CASE 
                        WHEN ev.event_type LIKE '%ATTACHMENT%' THEN 'attachment'
                        ELSE 'email'
                    END AS source,

                    ev.event_type

                FROM evidence_records e

                LEFT JOIN evidence_events ev
                    ON json_extract(ev.data_json, '$.evidence_id') = e.evidence_id

                WHERE ev.event_type = 'EVIDENCE_CUI_ANALYSIS'

                AND ev.created_at_ms = (
                    SELECT MAX(ev2.created_at_ms)
                    FROM evidence_events ev2
                    WHERE 
                        ev2.event_type = 'EVIDENCE_CUI_ANALYSIS'
                        AND json_extract(ev2.data_json, '$.evidence_id') = e.evidence_id
                )

                ORDER BY e.created_at_ms DESC
                LIMIT 50
            """).fetchall()

        print("🔥 USING EVIDENCE QUERY")
        print("EVIDENCE ROW COUNT:", len(evidence_rows))
        print("EVIDENCE SAMPLE:", dict(evidence_rows[0]) if evidence_rows else "NO ROWS")

        if evidence_rows:

            # ----------------------------
            # BUILD DATAFRAME
            # ----------------------------
            df = pd.DataFrame([dict(r) for r in evidence_rows])

            # ----------------------------
            # NORMALIZE COLUMN NAMES
            # ----------------------------
            df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]

            print("✅ RAW EVIDENCE DF COLUMNS:", df.columns.tolist())

            # Hard guard against wrong dataset
            if "evidence_id" not in df.columns:
                st.error("🚨 Wrong dataset detected. Expected evidence-level data.")
                st.write("Columns received:", df.columns.tolist())
                st.stop()

            # ----------------------------
            # SAFE CORE FIELD NORMALIZATION
            # ----------------------------
            df["evidence_id"] = df["evidence_id"].astype(str).str.strip()

            df = df[
                df["evidence_id"].notna()
                & (df["evidence_id"] != "")
                & (df["evidence_id"] != "None")
                & (df["evidence_id"] != "0")
                ].copy()

            df["hit_count"] = pd.to_numeric(
                df.get("hit_count", pd.Series(index=df.index)),
                errors="coerce"
            ).fillna(0)

            df["category"] = df.get(
                "category",
                pd.Series(index=df.index)
            ).fillna("UNCATEGORIZED")

            df["source"] = df.get(
                "source",
                pd.Series(index=df.index)
            ).fillna("email")

            df["event_type"] = df.get(
                "event_type",
                pd.Series(index=df.index)
            ).fillna("EVIDENCE_CUI_ANALYSIS")

            df["created"] = df.get(
                "created",
                pd.Series(index=df.index)
            )

            def safe_ts(x):
                try:
                    if pd.isna(x):
                        return None
                    if isinstance(x, (int, float)):
                        return datetime.fromtimestamp(x / 1000)
                    return x
                except Exception:
                    return None

            df["created"] = df["created"].apply(safe_ts)

            # ----------------------------
            # NORMALIZE CATEGORY
            # ----------------------------
            def normalize_category(cat):
                if cat is None:
                    return "UNCATEGORIZED"

                if isinstance(cat, list):
                    return str(cat[0]).upper() if cat else "UNCATEGORIZED"

                if isinstance(cat, str):
                    try:
                        parsed = json.loads(cat)
                        if isinstance(parsed, list) and parsed:
                            return str(parsed[0]).upper()
                    except Exception:
                        pass

                    clean = cat.strip()
                    return clean.upper() if clean else "UNCATEGORIZED"

                return str(cat).upper()

            df["category"] = df["category"].apply(normalize_category)

            # ----------------------------
            # FILTER TO ACTUAL CUI DETECTIONS
            # ----------------------------
            df = df[
                (df["hit_count"] > 0)
                & (df["category"] != "UNCATEGORIZED")
                ].copy()

            if df.empty:
                st.warning("No CUI detections found in the latest evidence analysis.")
            else:

                # ----------------------------
                # SEVERITY
                # ----------------------------
                def resolve_severity(cat, hits):
                    if hits == 0 or not cat or cat == "UNCATEGORIZED":
                        return "NONE"

                    if cat in ["EXPORT_CONTROL", "CONTROLLED_TECHNICAL_INFORMATION", "CREDENTIALS"]:
                        return "CRITICAL"
                    if cat == "CUI":
                        return "HIGH"
                    if cat in ["PII", "PHI", "FINANCIAL", "GOV_ID"]:
                        return "MEDIUM"

                    return "LOW"

                df["severity"] = df.apply(
                    lambda r: resolve_severity(
                        r.get("category", "UNCATEGORIZED"),
                        r.get("hit_count", 0)
                    ),
                    axis=1
                )

                # ----------------------------
                # SOURCE NORMALIZATION
                # ----------------------------
                df["source"] = df["source"].apply(
                    lambda x: "Attachment" if str(x).lower() == "attachment" else "Email"
                )

                # ----------------------------
                # METADATA
                # ----------------------------
                df["location"] = ""
                df["notes"] = ""
                df["status"] = "OPEN"
                df["id"] = range(len(df))

                # ----------------------------
                # CASE ID
                # ----------------------------
                df["case_id"] = df["evidence_id"].str[:10]

                # ----------------------------
                # PRIORITY + RISK SCORE
                # ----------------------------
                priority_map = {
                    "EXPORT_CONTROL": 5,
                    "CONTROLLED_TECHNICAL_INFORMATION": 5,
                    "CREDENTIALS": 5,
                    "CUI": 4,
                    "PHI": 3,
                    "FINANCIAL": 3,
                    "PII": 2,
                    "GOV_ID": 2,
                    "IP": 1,
                }

                risk_order = {
                    "CRITICAL": 4,
                    "HIGH": 3,
                    "MEDIUM": 2,
                    "LOW": 1,
                    "NONE": 0,
                }

                df["priority"] = df["category"].map(priority_map).fillna(0)
                df["risk_score"] = df["severity"].map(risk_order).fillna(0)

                # ----------------------------
                # FLAGS
                # ----------------------------
                df["has_cui"] = df["hit_count"] > 0
                df["cui_flag"] = df["has_cui"].apply(
                    lambda x: "🟥 YES" if x else "🟩 NO"
                )

                threshold = df["hit_count"].mean() + 2 * df["hit_count"].std()
                df["is_anomaly"] = df["hit_count"] > threshold

                # ----------------------------
                # SORT
                # ----------------------------
                df = df.sort_values(
                    by=["risk_score", "priority", "hit_count"],
                    ascending=[False, False, False]
                ).reset_index(drop=True)

                print("✅ FINAL CUI DF COLUMNS:", df.columns.tolist())

                # ----------------------------
                # DISPLAY HELPERS
                # ----------------------------
                def format_category(cat):
                    return {
                        "CREDENTIALS": "🔴 CREDENTIALS",
                        "CUI": "🔴 CUI",
                        "EXPORT_CONTROL": "🔴 EXPORT",
                        "CONTROLLED_TECHNICAL_INFORMATION": "🔴 CTI",
                        "PHI": "🟠 PHI",
                        "FINANCIAL": "🟠 FIN",
                        "GOV_ID": "🟡 GOV ID",
                        "PII": "🟡 PII",
                        "SYSTEM_INTERNAL": "🔵 SYSTEM",
                        "IP": "🟢 IP",
                    }.get(cat, cat)

                color_map = {
                    "CREDENTIALS": "#ffcccc",
                    "CUI": "#ffcccc",
                    "EXPORT_CONTROL": "#ffcccc",
                    "CONTROLLED_TECHNICAL_INFORMATION": "#ffcccc",
                    "PHI": "#ffe0b2",
                    "FINANCIAL": "#ffe0b2",
                    "GOV_ID": "#fff59d",
                    "PII": "#fff59d",
                    "SYSTEM_INTERNAL": "#e1f5fe",
                    "IP": "#e8f5e9",
                }

                def highlight_rows(row):
                    color = color_map.get(row["Category"], "#ffffff")
                    style = f"background-color: {color}; border-left: 6px solid black;"
                    if row["Severity"] in ["HIGH", "CRITICAL"]:
                        style += " font-weight: bold;"
                    return [style] * len(row)

                # ----------------------------
                # DISPLAY DATAFRAME
                # ----------------------------
                display_df = df.rename(columns={
                    "id": "ID",
                    "evidence_id": "evidence_id",
                    "case_id": "case_id",
                    "category": "Category",
                    "severity": "Severity",
                    "source": "Source",
                    "hit_count": "Hit Count",
                    "created": "Created",
                    "location": "Location",
                    "notes": "Notes",
                    "status": "Status",
                    "event_type": "Event Type",
                    "cui_flag": "CUI",
                })

                display_df["Display Category"] = display_df["Category"].apply(format_category)
                # ============================
                # 🚨 ALERT CREATION (INSERT HERE)
                # ============================


                # ----------------------------
                # ALERT ENGINE (FINAL)
                # ----------------------------
                SEVERITY_RANK = {
                    "CRITICAL": 4,
                    "HIGH": 3,
                    "MEDIUM": 2,
                    "LOW": 1,
                    "NONE": 0,
                }

                now = int(time.time() * 1000)
                cutoff = now - 300000  # 5 minutes

                with storage.ledger._connect() as con:
                    for _, row in df.iterrows():

                        def normalize_severity(val):
                            if not val:
                                return "LOW"

                            val = str(val).upper().strip()

                            # Remove emojis
                            val = val.replace("🔴", "").replace("🟠", "").replace("🟢", "").strip()

                            if val in ["CRITICAL", "HIGH", "MEDIUM", "LOW"]:
                                return val

                            return "LOW"

                        severity = normalize_severity(
                            row.get("severity")
                            or row.get("cui_severity")
                            or row.get("Risk")
                        )
                        evidence_id = str(row.get("evidence_id", "")).strip()

                        if not evidence_id:
                            continue

                        # Only alert on HIGH / CRITICAL
                        if severity not in ["CRITICAL", "HIGH"]:
                            continue

                        # ----------------------------
                        # CHECK LAST ALERT (FOR ESCALATION + COOLDOWN)
                        # ----------------------------
                        existing = con.execute("""
                            SELECT severity, created_at_ms
                            FROM alerts
                            WHERE evidence_id = ?
                            ORDER BY created_at_ms DESC
                            LIMIT 1
                        """, (evidence_id,)).fetchone()

                        allow_insert = True

                        if existing:
                            last_sev, last_ts = existing

                            # 🔥 Allow escalation (e.g., HIGH → CRITICAL)
                            if SEVERITY_RANK.get(severity, 0) > SEVERITY_RANK.get(last_sev, 0):
                                allow_insert = True
                            else:
                                # ⛔ Apply cooldown window
                                if last_ts and last_ts > cutoff:
                                    allow_insert = False

                        if not allow_insert:
                            continue

                        # ----------------------------
                        # INSERT ALERT (RACE SAFE)
                        # ----------------------------
                        cur = con.execute("""
                            INSERT OR IGNORE INTO alerts (
                                evidence_id,
                                severity,
                                message,
                                created_at_ms,
                                resolved,
                                status,
                                category,
                                location,
                                notes,
                                source_name,
                                detection_json
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            evidence_id,
                            severity,
                            f"CUI detected: {row.get('category', 'UNKNOWN')}",
                            now,
                            0,
                            "OPEN",
                            row.get("category"),
                            row.get("source"),
                            "",
                            row.get("event_type"),
                            json.dumps(row.to_dict(), default=str)
                        ))

                        # ----------------------------
                        # ONLY RUN IF INSERT HAPPENED
                        # ----------------------------
                        if cur.rowcount > 0:
                            # 🔥 GET ALERT ID (SAFE)
                            alert_id = con.execute("""
                                SELECT id FROM alerts
                                WHERE evidence_id = ? AND severity = ?
                                ORDER BY created_at_ms DESC
                                LIMIT 1
                            """, (evidence_id, severity)).fetchone()[0]

                            # ----------------------------
                            # 🔥 CASE LINKING
                            # ----------------------------
                            case_id = storage.ledger.ensure_case_for_alert(
                                alert_id=alert_id,
                                evidence_id=evidence_id,
                                job_id=row.get("job_id")
                            )
                            from core.cases.assignment_engine import auto_assign_case

                            assigned_to = auto_assign_case(
                                storage,
                                case_id,
                                severity,
                                actor="system"
                            )
                            # ----------------------------
                            # 🔥 TIMELINE EVENT (THIS IS STEP 1)
                            # ----------------------------
                            con.execute("""
                                INSERT INTO case_timeline (
                                    case_id,
                                    event_type,
                                    ts,
                                    label,
                                    actor,
                                    details
                                )
                                VALUES (?, ?, ?, ?, ?, ?)
                            """, (
                                case_id,
                                "ALERT_CREATED",
                                now,
                                f"{severity} {row.get('category', 'UNKNOWN')} detected",
                                "system",
                                json.dumps({
                                    "alert_id": alert_id,
                                    "evidence_id": evidence_id,
                                    "severity": severity,
                                    "category": row.get("category"),
                                    "source": row.get("source"),
                                    "hit_count": row.get("hit_count", 0)
                                }, default=str)
                            ))
                            print("🚨 NOTIFY TRIGGERED:", row["severity"], row.get("category"))
                            print("🔥 RAW SEVERITY VALUE:", row.get("severity"))
                            print("🔥 FINAL SEVERITY SENT:", severity)

                            notify(
                                storage,
                                row["severity"],
                                f"{row['category']} detected (hits: {row['hit_count']})"
                            )


                        con.commit()
                st.markdown("### 🛡️ Detection Rows")
                st.dataframe(
                    display_df[
                        [
                            "ID",
                            "case_id",
                            "evidence_id",
                            "Display Category",
                            "Severity",
                            "Source",
                            "Hit Count",
                            "CUI",
                            "Created",
                            "Status",
                        ]
                    ],
                    use_container_width=True
                )

                # ============================
                # 📁 CASE TABLE
                # ============================
                case_source_df = display_df.copy()

                case_source_df = case_source_df.drop_duplicates(
                    subset=["evidence_id", "Event Type"]
                )

                case_df = (
                    case_source_df.groupby("case_id", dropna=True)
                    .agg({
                        "Category": lambda x: list(sorted(set(x))),
                        "Severity": "first",
                        "evidence_id": "count",
                        "Source": "first",
                        "Created": ["min", "max"],
                        "Hit Count": "sum",
                    })
                )

                case_df.columns = [
                    "Category",
                    "Severity",
                    "Alert Count",
                    "Source",
                    "First Seen",
                    "Last Seen",
                    "Total Hits",
                ]

                case_df = case_df.reset_index()

                severity_sort = {
                    "CRITICAL": 4,
                    "HIGH": 3,
                    "MEDIUM": 2,
                    "LOW": 1,
                    "NONE": 0,
                }

                case_df["_severity_rank"] = case_df["Severity"].map(severity_sort).fillna(0)
                case_df = case_df.sort_values(
                    by=["_severity_rank", "Total Hits", "Alert Count"],
                    ascending=[False, False, False]
                ).drop(columns=["_severity_rank"])

                st.subheader("📁 Case Summary")
                st.dataframe(case_df, use_container_width=True)

                # ----------------------------
                # RISK DISTRIBUTION
                # ----------------------------
                st.subheader("🔥 Risk Distribution")
                st.bar_chart(df["severity"].value_counts())

                # =====================================================
                # PERSIST CASE → EVIDENCE MAPPING
                # =====================================================
                with storage.ledger._connect() as con:
                    con.execute("""
                        CREATE TABLE IF NOT EXISTS case_evidence_map (
                            case_id TEXT,
                            evidence_id TEXT,
                            PRIMARY KEY (case_id, evidence_id)
                        )
                    """)

                    con.execute("DELETE FROM case_evidence_map")

                    for _, row in df.iterrows():


                        evidence_id = str(row["evidence_id"]).strip()
                        case_id = generate_case_id(evidence_id)
                        if evidence_id and case_id:
                            con.execute("""
                                INSERT OR IGNORE INTO case_evidence_map (case_id, evidence_id)
                                VALUES (?, ?)
                            """, (case_id, evidence_id))

                    con.commit()

                # ============================
                # 🔗 CORRELATED ALERTS
                # ============================
                selected_case = st.selectbox(
                    "Select Case",
                    options=case_df["case_id"].tolist()
                )

                case_alerts = display_df[
                    display_df["case_id"] == selected_case
                    ].reset_index(drop=True)

                st.markdown("### 🔗 Correlated Alerts")

                st.dataframe(
                    case_alerts.style.apply(highlight_rows, axis=1),
                    use_container_width=True
                )

                selected_idx = st.selectbox(
                    "Select Alert",
                    options=case_alerts.index.tolist(),
                    format_func=lambda i: (
                        f"{case_alerts.loc[i, 'ID']} | "
                        f"{case_alerts.loc[i, 'Category']} | "
                        f"{case_alerts.loc[i, 'Severity']}"
                    )
                )

                alert_row = case_alerts.iloc[selected_idx]

                st.markdown("### 📄 Details")
                st.write("**Category:**", format_category(alert_row["Category"]))
                st.write("**Severity:**", alert_row["Severity"])
                st.write("**Location:**", alert_row["Location"])
                st.write("**Source:**", alert_row["Source"])
                st.write("**Notes:**", alert_row["Notes"])
                st.write("**Created:**", alert_row["Created"])
                st.write("**Evidence ID:**", alert_row["evidence_id"])

                # ============================
                # 🔗 ALERT → EVIDENCE LINK
                # ============================
                notes = alert_row.get("Notes", "") or ""
                evidence_id = str(alert_row["evidence_id"]).strip()

                if st.button("🔎 View Evidence", use_container_width=True):
                    if not evidence_id:
                        st.error("No evidence_id linked to this alert")
                    else:
                        st.session_state["selected_evidence_id"] = evidence_id
                        st.session_state["alert_notes"] = notes
                        st.session_state["page"] = "Evidence Viewer"
                        st.rerun()

                # ============================
                # 📂 EVIDENCE HELPER
                # ============================
                def get_evidence(alert_id):
                    try:
                        with storage.ledger._connect() as con:
                            row = con.execute("""
                                SELECT evidence_id
                                FROM evidence_records
                                WHERE evidence_id LIKE ?
                                LIMIT 1
                            """, (f"{alert_id}%",)).fetchone()

                        if not row:
                            return None

                        found_evidence_id = row[0]
                        data = storage.vault.open_bytes(found_evidence_id)

                        if not data:
                            return None

                        try:
                            return data.decode("utf-8", errors="ignore")
                        except Exception:
                            return str(data[:2000])

                    except Exception as e:
                        return f"[evidence error] {e}"

                # ============================
                # 📤 EXPORT
                # ============================
                st.markdown("### ⬇️ Export")

                col1, col2 = st.columns(2)

                with col1:
                    st.download_button(
                        "Export JSON",
                        data=json.dumps(display_df.to_dict(orient="records"), indent=2, default=str),
                        file_name="alerts.json",
                        mime="application/json"
                    )

                with col2:
                    buffer = io.StringIO()
                    display_df.to_csv(buffer, index=False)

                    st.download_button(
                        "Export CSV",
                        data=buffer.getvalue(),
                        file_name="alerts.csv",
                        mime="text/csv"
                    )

        else:
            st.info("No detections yet.")

        # ============================
        # 🛠 ALERT DEBUG LOG
        # ============================
        st.subheader("🛠 Alert Debug Log")

        with storage.ledger._connect() as con:
            con.execute("""
                CREATE TABLE IF NOT EXISTS ui_debug_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at_ms INTEGER,
                    message TEXT
                )
            """)

            debug_rows = con.execute("""
                SELECT
                    datetime(created_at_ms / 1000, 'unixepoch') as created_at,
                    message
                FROM ui_debug_log
                ORDER BY id DESC
                LIMIT 50
            """).fetchall()

        if debug_rows:
            debug_df = pd.DataFrame(
                [dict(r) for r in debug_rows]
            )

            debug_df = debug_df.rename(columns={
                "created_at": "Created",
                "message": "Message"
            })

            st.dataframe(debug_df, use_container_width=True)
        else:
            st.info("No debug messages yet.")

        if st.button("🧹 Clear Debug Log"):
            with storage.ledger._connect() as con:
                con.execute("DELETE FROM ui_debug_log")
                con.commit()
            st.rerun()