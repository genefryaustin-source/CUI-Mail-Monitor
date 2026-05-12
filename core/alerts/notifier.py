import requests
import smtplib
import streamlit as st
from collections import defaultdict
import time
from slack_sdk import WebClient
import streamlit as st
AGG_BUFFER = defaultdict(list)
AGG_WINDOW = 10  # seconds
AGG_LAST_FLUSH = defaultdict(lambda: 0)
# -------------------------
# SEVERITY RANKING
# -------------------------
SEVERITY_RANK = {
    "CRITICAL": 4,
    "HIGH": 3,
    "MEDIUM": 2,
    "LOW": 1,
    "NONE": 0,
}


# -------------------------
# HELPER: NORMALIZE SEVERITY
# -------------------------
def normalize_severity(val):
    if not val:
        return "LOW"

    val = str(val).upper().strip()

    # Remove emojis
    val = val.replace("🔴", "").replace("🟠", "").replace("🟢", "").strip()

    if val in SEVERITY_RANK:
        return val

    return "LOW"


# -------------------------
# MAIN NOTIFY FUNCTION
# -------------------------
def notify(storage, severity: str, message: str, case_id: str = None):

    print("🚨 NOTIFY ENTERED")

    settings = storage.ledger.get_alert_settings()
    print("⚙️ SETTINGS RAW:", settings)

    if not settings:
        print("⛔ EXITING — NO SETTINGS FOUND")
        return

    # -------------------------
    # NORMALIZE INPUTS
    # -------------------------
    severity = normalize_severity(severity)
    min_sev = normalize_severity(settings.get("min_severity", "HIGH"))

    print(f"🔎 SEVERITY CHECK: incoming={severity} threshold={min_sev}")

    # -------------------------
    # THRESHOLD FILTER
    # -------------------------
    if SEVERITY_RANK[severity] < SEVERITY_RANK[min_sev]:
        print("⛔ DROPPED BY THRESHOLD")
        return

    # -------------------------
    # BUILD ALERT MESSAGE
    # -------------------------
    alert_text = f"🚨 [{severity}] {message}"

    # -------------------------
    # ROUTING LOGIC
    # -------------------------
    send_slack_flag = severity in ["CRITICAL", "HIGH"]
    send_email_flag = severity == "CRITICAL"

    # -------------------------
    # AGGREGATION (SKIP FOR CRITICAL)
    # -------------------------
    if severity != "CRITICAL":
        agg_key = f"{case_id or 'global'}_{severity}"
        now_ts = time.time()

        AGG_BUFFER[agg_key].append(message)

        if len(AGG_BUFFER[agg_key]) < 5 and (now_ts - AGG_LAST_FLUSH[agg_key]) < AGG_WINDOW:
            print("⏳ Aggregating alerts...")
            return

        combined_message = "\n".join(AGG_BUFFER[agg_key])
        alert_text = f"🚨 [{severity}] {len(AGG_BUFFER[agg_key])} alerts:\n{combined_message}"

        AGG_BUFFER[agg_key] = []
        AGG_LAST_FLUSH[agg_key] = now_ts

    # -------------------------
    # SLACK BOT SEND
    # -------------------------
    if send_slack_flag and settings.get("slack_enabled"):
        try:
            print("📡 TRYING SLACK BOT")

            client = WebClient(token=st.secrets["slack"]["bot_token"])
            channel = st.secrets["slack"]["channel_id"]

            thread_ts = None

            if case_id:
                result = storage.ledger.get_case_slack_thread(case_id)
                if result:
                    saved_channel, saved_thread = result
                    thread_ts = saved_thread

            # -------------------------
            # BUILD BLOCKS
            # -------------------------
            blocks = [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"🚨 *{severity} Alert*\n{alert_text}"
                    }
                }
            ]

            if case_id:
                blocks.append({
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": f"*Case ID:* `{case_id}`"
                        }
                    ]
                })

            if case_id and not thread_ts:
                blocks.append({
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Acknowledge"},
                            "style": "primary",
                            "action_id": "ack_case",
                            "value": case_id
                        },
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Assign to Me"},
                            "action_id": "assign_case",
                            "value": case_id
                        },
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Close Case"},
                            "style": "danger",
                            "action_id": "close_case",
                            "value": case_id
                        }
                    ]
                })

            # -------------------------
            # SEND MESSAGE
            # -------------------------
            resp = client.chat_postMessage(
                channel=channel,
                text=alert_text,
                blocks=blocks,
                thread_ts=thread_ts
            )

            print("📡 SLACK BOT RESPONSE OK:", resp["ok"])

            # -------------------------
            # SAVE THREAD
            # -------------------------
            if case_id and not thread_ts:
                ts = resp.get("ts")

                if ts:
                    storage.ledger.save_case_slack_thread(
                        case_id,
                        channel,
                        ts
                    )
                    print("🧵 THREAD CREATED:", ts)

        except Exception as e:
            print("❌ Slack bot notify failed:", e)

    # -------------------------
    # EMAIL SEND
    # -------------------------
    if send_email_flag and settings.get("email_enabled") and settings.get("email_to"):
        try:
            from email.mime.text import MIMEText

            print("📧 TRYING EMAIL SEND")

            EMAIL_USER = st.secrets["email"]["user"]
            EMAIL_PASS = st.secrets["email"]["password"]

            msg = MIMEText(alert_text, "plain", "utf-8")
            msg["Subject"] = f"CUI Alert ({severity})"
            msg["From"] = EMAIL_USER
            msg["To"] = settings["email_to"]

            with smtplib.SMTP("smtp.gmail.com", 587) as server:
                server.starttls()
                server.login(EMAIL_USER, EMAIL_PASS)
                server.sendmail(
                    EMAIL_USER,
                    settings["email_to"],
                    msg.as_string()
                )

            print("✅ EMAIL SENT")

        except Exception as e:
            print("❌ Email notify failed:", e)

    # -------------------------
    # ESCALATION (SAFE)
    # -------------------------
    if case_id:
        try:
            last_escalation = storage.ledger.get_last_escalation(case_id)
            now_ms = int(time.time() * 1000)

            if not last_escalation or (now_ms - last_escalation) > 15 * 60 * 1000:
                storage.ledger.record_escalation(case_id, now_ms)

                print("🚨 ESCALATION TRIGGERED")

                # 🔥 prevent infinite recursion
                if severity == "HIGH":
                    notify(
                        storage,
                        "CRITICAL",
                        f"Escalation: Case {case_id} still open",
                        case_id=case_id
                    )

        except Exception as e:
            print("Escalation check failed:", e)