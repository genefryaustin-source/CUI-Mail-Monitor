import time
from core.cases.escalation_config import ESCALATION_RULES


def run_escalation_check(storage, case_id):
    ledger = storage.ledger

    with ledger._connect() as con:
        case = con.execute("""
            SELECT created_at_ms, sla_due_ms, status
            FROM cases
            WHERE case_id = ?
        """, (case_id,)).fetchone()

    if not case:
        return

    if case["status"] == "RESOLVED":
        return

    now = int(time.time() * 1000)

    created = case["created_at_ms"]
    due = case["sla_due_ms"]

    if not due:
        return

    total = due - created
    elapsed = now - created

    pct = (elapsed / total) * 100 if total > 0 else 0

    existing_alerts = storage.ledger.list_alerts(limit=100)

    for rule in ESCALATION_RULES:
        if pct >= rule["threshold_pct"]:

            # prevent duplicate alerts
            if any(rule["message"] in a.get("message", "") for a in existing_alerts):
                continue

            storage.ledger.create_alert(
                evidence_id=None,
                severity=rule["severity"],
                message=f"{rule['message']} (Case {case_id})"
            )

    if rule["level"] == "L4":
        try:
            from core.cases.response_engine import run_response_action
            run_response_action(
                storage=storage,
                case_id=case_id,
                action_type="ESCALATE_TO_MANAGER",
                actor="system_auto",
            )
        except Exception as e:
            print("Auto response action failed:", e)