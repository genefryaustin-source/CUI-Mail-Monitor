ESCALATION_RULES = [
    {
        "level": "L2",
        "threshold_pct": 50,
        "severity": "MEDIUM",
        "message": "Case approaching SLA breach"
    },
    {
        "level": "L3",
        "threshold_pct": 100,
        "severity": "HIGH",
        "message": "SLA BREACH"
    },
    {
        "level": "L4",
        "threshold_pct": 150,
        "severity": "CRITICAL",
        "message": "ESCALATED: SLA severely breached"
    }
]