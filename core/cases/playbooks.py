from __future__ import annotations

PLAYBOOKS = {
    "TAMPER_RESPONSE": {
        "name": "Tamper Response",
        "description": "Standard response to integrity failure.",
        "steps": [
            {"action_type": "REQUEST_REVIEW", "requires_approval": False},
            {"action_type": "ISOLATE_EVIDENCE", "requires_approval": True},
            {"action_type": "ESCALATE_TO_MANAGER", "requires_approval": False},
        ],
    },
    "SLA_ESCALATION": {
        "name": "SLA Escalation",
        "description": "Escalation workflow for breached SLA.",
        "steps": [
            {"action_type": "REQUEST_REVIEW", "requires_approval": False},
            {"action_type": "ESCALATE_TO_MANAGER", "requires_approval": False},
            {"action_type": "QUARANTINE_CASE", "requires_approval": True},
        ],
    },
    "ANALYST_REVIEW": {
        "name": "Analyst Review",
        "description": "Manual review workflow.",
        "steps": [
            {"action_type": "REQUEST_REVIEW", "requires_approval": False},
        ],
    },
}