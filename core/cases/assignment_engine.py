import time

DEFAULT_ANALYSTS = {
    "CRITICAL": ["senior_analyst"],
    "HIGH": ["analyst_1", "analyst_2"],
    "MEDIUM": ["analyst_1", "analyst_2", "analyst_3"],
    "LOW": ["analyst_queue"],
}


def auto_assign_case(storage, case_id: str, severity: str, actor: str = "system"):
    severity = (severity or "LOW").upper()
    candidates = DEFAULT_ANALYSTS.get(severity, DEFAULT_ANALYSTS["LOW"])

    with storage.ledger._connect() as con:
        rows = con.execute("""
            SELECT assigned_to, COUNT(*) AS open_count
            FROM cases
            WHERE status IN ('OPEN', 'INVESTIGATING')
              AND assigned_to IS NOT NULL
            GROUP BY assigned_to
        """).fetchall()

        workload = {r["assigned_to"]: r["open_count"] for r in rows}

        selected = min(
            candidates,
            key=lambda user: workload.get(user, 0)
        )

        now = int(time.time() * 1000)

        con.execute("""
            UPDATE cases
            SET assigned_to = ?,
                assigned_by = ?,
                assigned_at_ms = ?,
                updated_at_ms = ?
            WHERE case_id = ?
        """, (
            selected,
            actor,
            now,
            now,
            case_id,
        ))

        con.commit()

    storage.ledger.add_case_event(
        case_id,
        "AUTO_ASSIGNED",
        f"Case auto-assigned to {selected}",
        actor=actor,
        details={
            "severity": severity,
            "assigned_to": selected,
        }
    )

    return selected