def compute_case_risk(evidence, alerts):
    score = 0
    reasons = []

    # ----------------------------
    # ALERT-BASED SIGNALS
    # ----------------------------
    severity_weights = {
        "LOW": 10,
        "MEDIUM": 30,
        "HIGH": 60,
        "CRITICAL": 90,
    }

    for a in alerts or []:
        sev = (a.get("severity") or "").upper()
        if sev in severity_weights:
            score += severity_weights[sev]
            reasons.append(f"Alert severity: {sev}")

    # ----------------------------
    # EVIDENCE DETECTIONS
    # ----------------------------
    for e in evidence or []:
        detection = e.get("detection") or {}

        categories = detection.get("categories", [])
        hit_count = detection.get("hit_count", 0)

        if "CUI" in categories:
            score += 40
            reasons.append("CUI detected")

        if "PII" in categories:
            score += 25
            reasons.append("PII detected")

        if hit_count >= 3:
            score += 20
            reasons.append("Multiple detection hits")

    # ----------------------------
    # NORMALIZE
    # ----------------------------
    score = min(score, 100)

    # ----------------------------
    # LEVEL
    # ----------------------------
    if score >= 70:
        level = "HIGH"
    elif score >= 40:
        level = "MEDIUM"
    else:
        level = "LOW"

    return score, level, reasons