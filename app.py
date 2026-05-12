# app.py

import streamlit as st
import sys
import traceback
# ----------------------------------
# 🔥 MUST BE FIRST STREAMLIT CALL
# ----------------------------------
st.set_page_config(
    page_title="CUI Mail Monitor",
    page_icon="🛡️",
    layout="wide",
)


try:
    import slack_bolt
    print("✅ slack_bolt OK")
except Exception:
    traceback.print_exc()

try:
    import slack_sdk
    print("✅ slack_sdk OK")
except Exception:
    traceback.print_exc()

try:
    import google_auth_oauthlib
    print("✅ google_auth_oauthlib OK")
except Exception:
    traceback.print_exc()
# ----------------------------------
# 🔥 NOW SAFE TO IMPORT EVERYTHING
# ----------------------------------

# UI pages
from core.ui.demo_page import render_demo_page
from core.ui.evidence_viewer import render_evidence_viewer
from core.ui.metrics_page import render_metrics_page
from core.ui.supervisor_dashboard import render_supervisor_dashboard
from core.ui.trust_center_page import render_trust_center_page
from core.ui.admin_alerts_page import render_alert_settings_page
from core.ui.investigation_page import render_investigation_page
from core.ui.alert_center_page import render_alert_center_page
from core.ui.scan_page import render_scan_page
from core.ui.admin_page import render_admin_page
from core.ui.case_dashboard_page import render_case_dashboard
from core.ui.help_page import render_help_page
from core.ui.sla_dashboard_page import render_sla_dashboard_page
# Core services
from core.storage.factory import build_storage
from core.scan.worker import start_scan_workers, stop_scan_workers

import threading
# ----------------------------------
# 🔥 GLOBAL STORAGE (ALWAYS AVAILABLE)
# ----------------------------------
if "storage" not in st.session_state:
    st.session_state["storage"] = build_storage()

    # 🔥 INIT DB PRAGMAS ONCE
    try:
        with st.session_state["storage"].ledger._connect() as con:

            st.session_state["storage"].ledger._set_pragmas_once(con)

            con.commit()

        print("✅ SQLite WAL initialized")

    except Exception as e:
        print("⚠️ WAL init failed:", e)

storage = st.session_state["storage"]
# ----------------------------------
# 🚀 START WORKERS (ONCE)
# ----------------------------------
if "workers_started" not in st.session_state or not st.session_state.get("workers_running", False):
    storage.stop_workers = False  # 🔥 CRITICAL RESET
    start_scan_workers(storage)
    st.session_state["workers_started"] = True
    st.session_state["workers_running"] = True

# ----------------------------------
# 🎯 USER ROLE
# ----------------------------------

if "user_role" not in st.session_state:
    st.session_state["user_role"] = "ANALYST"

st.sidebar.selectbox(
    "User Role",
    ["ANALYST", "SENIOR_ANALYST", "MANAGER", "ADMIN"],
    key="user_role"
)
if st.sidebar.button("🛑 Stop Workers"):
    stop_scan_workers(storage)
    st.session_state["workers_running"] = False

if st.sidebar.button("🚀 Start Workers"):
    storage.stop_workers = False
    start_scan_workers(storage)
    st.session_state["workers_running"] = True

st.sidebar.divider()

if st.sidebar.button("📘 Help / How To"):
    st.session_state["page"] = "Help Center"
    st.rerun()
# ---------------------------
# SIDEBAR NAVIGATION
# ---------------------------
st.sidebar.title("Navigation")

PAGES = [
    "Live Forensic Demo",
    "Admin",
    "Scan",
    "Evidence Viewer",
    "Metrics",
    "Supervisor Dashboard",
    "Trust Center",
    "Alert Settings",
    "Alert Center",
    "Investigation Workspace",
    "Cases",
    "Help Center",
]

# 🔥 Initialize
if "page" not in st.session_state:
    st.session_state["page"] = "Scan"

# 🔥 Use session state as source of truth
page = st.sidebar.radio(
    "Go to",
    PAGES,
    index=PAGES.index(st.session_state["page"])
)

# 🔥 ONLY update if user manually changed it
if page != st.session_state["page"]:
    st.session_state["page"] = page

# ---------------------------
# ROUTER
# ---------------------------
if page == "Live Forensic Demo":
    render_demo_page(storage)

elif page == "Admin":
    render_admin_page(storage)

elif page == "Scan":
    render_scan_page(storage)

elif page == "Evidence Viewer":
    render_evidence_viewer(storage)

elif page == "Metrics":
    render_metrics_page(storage)

elif page == "Supervisor Dashboard":
    render_supervisor_dashboard(storage)

elif page == "Trust Center":
    render_trust_center_page(storage)

elif page == "Alert Settings":
    render_alert_settings_page(storage)

elif page == "Alert Center":
    render_alert_center_page(storage)

elif page == "Investigation Workspace":
    render_investigation_page(storage)

elif page == "Cases":
     render_case_dashboard(storage)

elif page == "Help Center":
    render_help_page(storage)
