import streamlit as st
import sys
import traceback

# =============================================
# MUST BE FIRST
# =============================================
st.set_page_config(
    page_title="CUI Mail Monitor",
    page_icon="🛡️",
    layout="wide",
)
# =========================================================
# 📱 MOBILE FLOATING NAV
# =========================================================

PAGES = [
    "Scan",
    "Evidence",
    "Alerts",
    "Cases",
    "Admin",
]

PAGE_MAP = {
    "Scan": "Scan",
    "Evidence": "Evidence Viewer",
    "Alerts": "Alert Center",
    "Cases": "Cases",
    "Admin": "Admin",
}

# ---------------------------------------------------------
# DEFAULT PAGE
# ---------------------------------------------------------

if "page" not in st.session_state:
    st.session_state["page"] = "Scan"

# ---------------------------------------------------------
# FLOATING MOBILE NAV CSS
# ---------------------------------------------------------

st.markdown("""
<style>

.mobile-nav {
    position: fixed;
    bottom: 0;
    left: 0;
    right: 0;

    z-index: 999999;

    background: #0b1220;

    border-top: 1px solid #333;

    display: flex;
    justify-content: space-around;

    padding: 0.5rem;
}

.mobile-nav button {
    background: transparent;
    color: white;
    border: none;
    font-size: 14px;
    font-weight: 600;
}

@media (min-width: 768px) {
    .mobile-nav {
        display: none;
    }
}

</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------
# MOBILE NAV
# ---------------------------------------------------------

mobile_page = st.radio(
    "Mobile Navigation",
    PAGES,
    horizontal=True,
    label_visibility="collapsed",
    key="mobile_nav_bar"
)

mapped_page = PAGE_MAP[mobile_page]

if mapped_page != st.session_state["page"]:

    st.session_state["page"] = mapped_page

    st.rerun()
from veridion_theme import apply_theme
apply_theme()

# ====================== SIDEBAR ======================
with st.sidebar:
    # Veridion Pro Title - Force show every time (session_state was too sticky)
    st.markdown('<h1 class="veridion-sidebar-title">Veridion Pro</h1>', unsafe_allow_html=True)

    # User Role
    if "user_role" not in st.session_state:
        st.session_state["user_role"] = "ANALYST"
    st.selectbox("User Role", ["ANALYST", "SENIOR_ANALYST", "MANAGER", "ADMIN"], key="user_role")

    # Worker Controls
    col1, col2 = st.columns(2)
    with col1:
        if st.button("🛑 Stop Workers"):
            from core.scan.worker import stop_scan_workers
            stop_scan_workers(st.session_state.get("storage"))
            st.session_state["workers_running"] = False
    with col2:
        if st.button("🚀 Start Workers"):
            from core.scan.worker import start_scan_workers
            st.session_state["storage"].stop_workers = False
            start_scan_workers(st.session_state["storage"])
            st.session_state["workers_running"] = True

    st.divider()

    if st.button("📘 Help / How To"):
        st.session_state["page"] = "Help Center"
        st.rerun()

    # Navigation
    st.title("Navigation")

    PAGES = [
        "Scan",
        "Live Forensic Demo",
        "Evidence Viewer",
        "Metrics",
        "Supervisor Dashboard",
        "Trust Center",
        "Alert Settings",
        "Alert Center",
        "Investigation Workspace",
        "Cases",
        "Admin",
        "Help Center",
    ]

    if "page" not in st.session_state:
        st.session_state["page"] = "Scan"

    selected = st.radio(
        "Go to",
        PAGES,
        index=PAGES.index(st.session_state["page"]),
        label_visibility="collapsed"
    )

    if selected != st.session_state["page"]:
        st.session_state["page"] = selected
        st.rerun()

# =============================================
# STORAGE & WORKERS
# =============================================
if "storage" not in st.session_state:
    from core.storage.factory import build_storage
    st.session_state["storage"] = build_storage()

storage = st.session_state["storage"]

if "workers_started" not in st.session_state or not st.session_state.get("workers_running", False):
    from core.scan.worker import start_scan_workers
    storage.stop_workers = False
    start_scan_workers(storage)
    st.session_state["workers_started"] = True
    st.session_state["workers_running"] = True

# =============================================
# PAGE ROUTER
# =============================================
page = st.session_state["page"]

if page == "Scan":
    from core.ui.scan_page import render_scan_page
    render_scan_page(storage)
elif page == "Evidence Viewer":
    from core.ui.evidence_viewer import render_evidence_viewer
    render_evidence_viewer(storage)
elif page == "Metrics":
    from core.ui.metrics_page import render_metrics_page
    render_metrics_page(storage)
elif page == "Supervisor Dashboard":
    from core.ui.supervisor_dashboard import render_supervisor_dashboard
    render_supervisor_dashboard(storage)
elif page == "Trust Center":
    from core.ui.trust_center_page import render_trust_center_page
    render_trust_center_page(storage)
elif page == "Alert Settings":
    from core.ui.admin_alerts_page import render_alert_settings_page
    render_alert_settings_page(storage)
elif page == "Alert Center":
    from core.ui.alert_center_page import render_alert_center_page
    render_alert_center_page(storage)
elif page == "Investigation Workspace":
    from core.ui.investigation_page import render_investigation_page
    render_investigation_page(storage)
elif page == "Cases":
    from core.ui.case_dashboard_page import render_case_dashboard
    render_case_dashboard(storage)
elif page == "Admin":
    from core.ui.admin_page import render_admin_page
    render_admin_page(storage)
elif page == "Live Forensic Demo":
    from core.ui.demo_page import render_demo_page
    render_demo_page(storage)
elif page == "Help Center":
    from core.ui.help_page import render_help_page
    render_help_page(storage)
else:
    from core.ui.scan_page import render_scan_page
    render_scan_page(storage)