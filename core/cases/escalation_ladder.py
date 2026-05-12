import time
from core.alerts.notifier import notify


ESCALATION_RULES = [
    {
        "level": "L1_REMINDER",
        "after_minutes": 15,
        "severity": "HIGH",
        "message": "Case has not been acknowledged within 15 minutes.",
    },
    {
        "level": "L2_MANAGER",
        "after_minutes": 30,
        "severity": "CRITICAL",
        "message": "Case requires manager escalation.",
    },
    {
        "level": "L3_EXECUTIVE",
        "after_minutes": 60,
        "severity": "CRITICAL",
        "message": "Case requires executive escalation.",
    },
]


def run_escalation_ladder(storage):
    now = int(time.time() * 1000)

    with storage.ledger._connect() as con:
        cases = con.execute("""
            SELECT case_id, title, status, created_at_ms, assigned_to
            FROM cases
            WHERE status IN ('OPEN', 'INVESTIGATING')
        """).fetchall()

        for case in cases:
            case_id = case["case_id"]
            age_min = (now - case["created_at_ms"]) / 60000

            for rule in ESCALATION_RULES:
                if age_min < rule["after_minutes"]:
                    continue

                existing = con.execute("""
                    SELECT 1
                    FROM case_events
                    WHERE case_id = ?
                      AND event_type = ?
                    LIMIT 1
                """, (
                    case_id,
                    rule["level"],
                )).fetchone()

                if existing:
                    continue

                con.execute("""
                    INSERT INTO case_events (
                        case_id,
                        event_type,
                        message,
                        created_at_ms,
                        actor
                    )
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    case_id,
                    rule["level"],
                    rule["message"],
                    now,
                    "system",
                ))

                notify(
                    storage,
                    rule["severity"],
                    f"{rule['message']} Case: {case_id}",
                    case_id=case_id,
                )

        con.commit()