from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
import streamlit as st


def run_slack_listener(storage):
    print("🔥 storage has ledger:", hasattr(storage, "ledger"))
    print("🔥 ledger has update_case_status:", hasattr(storage.ledger, "update_case_status"))
    print("🔥 ledger has add_case_event:", hasattr(storage.ledger, "add_case_event"))
    app = App(token=st.secrets["slack"]["bot_token"])

    # -------------------------
    # ACK BUTTON
    # -------------------------
    @app.action("ack_case")
    def handle_ack(ack, body, say):
        ack()

        case_id = body["actions"][0]["value"]
        user = body["user"]["username"]

        print(f"✅ ACK CLICK: {case_id} by {user}")

        storage.ledger.update_case_status(
            case_id,
            "INVESTIGATING",
            actor=user
        )

        say(
            text=f"✅ Case `{case_id}` acknowledged by {user}",
            thread_ts=body["message"]["ts"]
        )

    # -------------------------
    # CLOSE BUTTON
    # -------------------------
    @app.action("close_case")
    def handle_close(ack, body, say):
        ack()

        case_id = body["actions"][0]["value"]
        user = body["user"]["username"]

        print(f"🔒 CLOSE CLICK: {case_id} by {user}")

        storage.ledger.update_case_status(
            case_id,
            "RESOLVED",
            actor=user
        )

        say(
            text=f"🔒 Case `{case_id}` closed by {user}",
            thread_ts=body["message"]["ts"]
        )

    print("🚀 Slack listener running...")

    handler = SocketModeHandler(
        app,
        st.secrets["slack"]["app_token"]
    )

    handler.start()

    # -------------------------
    # Assign Case
    # -------------------------
    @app.action("assign_case")
    def handle_assign(ack, body, say):
        ack()

        case_id = body["actions"][0]["value"]
        user = body["user"]["username"]

        print(f"👤 ASSIGN CLICK: {case_id} → {user}")

        # -------------------------
        # UPDATE CASE OWNER
        # -------------------------
        storage.ledger.update_case_owner(case_id, user)

        # -------------------------
        # LOG EVENT
        # -------------------------
        storage.ledger.add_case_event(
            case_id,
            "SLACK_ASSIGN",
            f"Assigned to {user}",
            actor=user
        )

        say(f"👤 Case `{case_id}` assigned to *{user}*")