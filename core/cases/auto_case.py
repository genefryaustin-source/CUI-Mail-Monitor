import uuid
from typing import Any


def auto_create_case_from_alert(storage: Any, alert: dict):
    ledger = storage.ledger

    if not alert:
        return None

    if alert.get("severity") != "CRITICAL":
        return None

    evidence_id = alert.get("evidence_id")
    if not evidence_id:
        return None

    existing_case = None
    if hasattr(ledger, "find_case_by_evidence"):
        existing_case = ledger.find_case_by_evidence(evidence_id)

    if existing_case:
        case_id = existing_case["case_id"]
    else:
        case_id = str(uuid.uuid4())

        if hasattr(ledger, "create_case"):
            ledger.create_case(
                case_id,
                title=f"Critical CUI Incident: {str(evidence_id)[:12]}",
                description="Auto-created from CRITICAL CUI alert",
            )

        if hasattr(ledger, "add_case_evidence"):
            ledger.add_case_evidence(case_id, evidence_id)

    if hasattr(ledger, "add_case_alert"):
        ledger.add_case_alert(case_id, alert["id"])

    if hasattr(ledger, "add_case_note"):
        ledger.add_case_note(
            case_id,
            f"Auto-created from CRITICAL alert: {alert.get('message', '')}",
        )

    return case_id