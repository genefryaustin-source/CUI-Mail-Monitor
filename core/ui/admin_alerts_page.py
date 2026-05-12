import streamlit as st


def render_alert_settings_page(storage):
    st.title("⚙️ Alert Configuration")

    settings = storage.ledger.get_alert_settings()

    if not settings:
        st.error("Alert settings not initialized")
        return

    # -------------------------
    # Form
    # -------------------------
    with st.form("alert_settings_form"):

        st.subheader("Slack Notifications")

        slack_enabled = st.checkbox(
            "Enable Slack Alerts",
            value=bool(settings["slack_enabled"])
        )

        slack_webhook = st.text_input(
            "Slack Webhook URL",
            value=settings.get("slack_webhook_url") or "",
        )

        st.subheader("Email Notifications")

        email_enabled = st.checkbox(
            "Enable Email Alerts",
            value=bool(settings["email_enabled"])
        )

        email_to = st.text_input(
            "Alert Email Address",
            value=settings.get("email_to") or "",
        )

        st.subheader("Severity Threshold")

        min_severity = st.selectbox(
            "Minimum Severity to Notify",
            ["CRITICAL", "HIGH", "MEDIUM"],
            index=["CRITICAL", "HIGH", "MEDIUM"].index(
                settings.get("min_severity", "CRITICAL")
            ),
        )

        submitted = st.form_submit_button("💾 Save Settings")

        if submitted:
            storage.ledger.update_alert_settings(
                slack_enabled=slack_enabled,
                slack_webhook_url=slack_webhook,
                email_enabled=email_enabled,
                email_to=email_to,
                min_severity=min_severity,
            )

            st.success("Settings saved")