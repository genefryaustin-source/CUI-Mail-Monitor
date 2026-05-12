from __future__ import annotations

from typing import Any, Dict
from core.auth.permissions import can_approve

import json


def run_response_action(storage: Any, case_id: str, action_type: str, actor: str = "analyst_user") -> Dict[str, Any]:
    ledger = storage.ledger

    result = {
        "case_id": case_id,
        "action_type": action_type,
        "status": "SIMULATED",
        "actor": actor,
    }

    if action_type == "ISOLATE_EVIDENCE":
        details = {
            "message": "Simulated isolation of evidence linked to case.",
            "effect": "Evidence marked for restricted handling only.",
        }

    elif action_type == "QUARANTINE_CASE":
        details = {
            "message": "Simulated quarantine of entire case.",
            "effect": "Case elevated for restricted workflow.",
        }

    elif action_type == "ESCALATE_TO_MANAGER":
        details = {
            "message": "Simulated escalation to manager.",
            "effect": "Management notification would be sent here.",
        }

    elif action_type == "REQUEST_REVIEW":
        details = {
            "message": "Simulated review request.",
            "effect": "Peer review would be requested here.",
        }

    else:
        result["status"] = "FAILED"
        details = {
            "message": f"Unknown response action: {action_type}"
        }

    ledger.record_response_action(
        case_id=case_id,
        action_type=action_type,
        status=result["status"],
        actor=actor,
        details=details,
    )

    if hasattr(ledger, "add_case_note"):
        ledger.add_case_note(
            case_id,
            f"Response action executed: {action_type} ({result['status']})"
        )

    return {
        **result,
        "details": details,
    }




APPROVAL_REQUIRED_ACTIONS = {
    "ISOLATE_EVIDENCE",
    "QUARANTINE_CASE",
}


def request_response_action(
    storage: Any,
    case_id: str,
    action_type: str,
    actor: str = "analyst_user",
) -> Dict[str, Any]:
    ledger = storage.ledger

    requires_approval = action_type in APPROVAL_REQUIRED_ACTIONS

    if requires_approval:
        approval_id = ledger.create_response_approval(
            case_id=case_id,
            action_type=action_type,
            requested_by=actor,
            details_json=json.dumps({"message": "Approval required before execution"}),
        )

        if hasattr(ledger, "add_case_note"):
            ledger.add_case_note(
                case_id,
                f"Approval requested for action: {action_type} (approval_id={approval_id})"
            )

        return {
            "case_id": case_id,
            "action_type": action_type,
            "status": "PENDING_APPROVAL",
            "approval_id": approval_id,
            "requested_by": actor,
        }

    return run_response_action(
        storage=storage,
        case_id=case_id,
        action_type=action_type,
        actor=actor,
    )





def approve_and_execute_response_action(
    storage,
    approval_id: int,
    approved_by: str,
    user_role: str,
):
    ledger = storage.ledger
    approval = ledger.get_response_approval(approval_id)

    if not approval:
        raise ValueError(f"Approval not found: {approval_id}")

    if approval["status"] != "PENDING":
        raise ValueError(f"Already processed: {approval['status']}")

    action_type = approval["action_type"]

    # 🔐 ROLE CHECK
    if not can_approve(user_role, action_type):
        raise PermissionError(
            f"{user_role} cannot approve {action_type}"
        )

    ledger.update_response_approval(
        approval_id=approval_id,
        status="APPROVED",
        approved_by=approved_by,
    )

    result = run_response_action(
        storage=storage,
        case_id=approval["case_id"],
        action_type=action_type,
        actor=approved_by,
    )

    ledger.add_case_note(
        approval["case_id"],
        f"{approved_by} ({user_role}) approved {action_type}"
    )

    return {
        "approval": ledger.get_response_approval(approval_id),
        "execution": result,
    }


def reject_response_action(
    storage: Any,
    approval_id: int,
    approved_by: str = "approver_user",
) -> Dict[str, Any]:
    ledger = storage.ledger
    approval = ledger.get_response_approval(approval_id)

    if not approval:
        raise ValueError(f"Approval not found: {approval_id}")

    if approval["status"] != "PENDING":
        raise ValueError(f"Approval already processed with status: {approval['status']}")

    ledger.update_response_approval(
        approval_id=approval_id,
        status="REJECTED",
        approved_by=approved_by,
    )

    if hasattr(ledger, "add_case_note"):
        ledger.add_case_note(
            approval["case_id"],
            f"Approval rejected for action: {approval['action_type']} by {approved_by}"
        )

    return ledger.get_response_approval(approval_id)




def execute_playbook(
    storage: Any,
    case_id: str,
    playbook_row: Dict[str, Any],
    actor: str = "analyst_user",
):
    steps = playbook_row.get("steps_json")
    if isinstance(steps, str):
        steps = json.loads(steps)

    results = []

    for step in steps:
        action_type = step["action_type"]
        result = request_response_action(
            storage=storage,
            case_id=case_id,
            action_type=action_type,
            actor=actor,
        )
        results.append(result)

    return results