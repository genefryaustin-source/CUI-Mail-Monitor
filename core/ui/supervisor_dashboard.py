import streamlit as st

from veridion_theme import apply_theme
apply_theme()

from core.supervisor.system_supervisor import SystemSupervisor
with st.sidebar:
    st.markdown('<h1 class="veridion-sidebar-title">Veridion Pro</h1>', unsafe_allow_html=True)


def render_supervisor_dashboard(storage):
    supervisor = SystemSupervisor(storage)

    # Run health/escalation checks once when dashboard loads
    supervisor.run_auto_escalation()

    st.subheader("🛠 Supervisor Status")

    status = supervisor.get_status()
    st.json(status)

    st.subheader("📡 Heartbeats")

    hb = supervisor.get_heartbeats()

    if not hb:
        st.info("No worker heartbeats yet.")
    else:
        st.dataframe(hb, use_container_width=True)

    st.subheader("📋 Scan Queue")

    queue = supervisor.get_queue()

    if not queue:
        st.info("Queue empty.")
    else:
        st.dataframe(queue, use_container_width=True)

    st.subheader("📈 Metrics")

    metrics = supervisor.get_metrics()

    if not metrics:
        st.info("No metrics yet.")
    else:
        st.dataframe(metrics, use_container_width=True)