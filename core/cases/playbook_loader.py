from __future__ import annotations

import json
from core.cases.playbooks import PLAYBOOKS


def seed_playbooks(storage):
    ledger = storage.ledger

    for playbook_id, pb in PLAYBOOKS.items():
        ledger.create_response_playbook(
            playbook_id=playbook_id,
            name=pb["name"],
            description=pb["description"],
            steps_json=json.dumps(pb["steps"]),
        )