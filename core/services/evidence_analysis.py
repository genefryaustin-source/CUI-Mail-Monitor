import re
from core.classify.rules import run_rules, score_hits, resolve_category


def analyze_evidence_text(text: str):
    text = text or ""
    text_lower = text.lower()

    flags = []
    matches = []
    rule_hits = []

    # ---------------------------------------
    # 🚀 PRIMARY RULE ENGINE (NEW CORE)
    # ---------------------------------------
    hits = run_rules(text)

    scores = score_hits(hits)
    primary_category = resolve_category(scores)

    categories = list(set([h["category"] for h in hits]))
    hit_count = len(hits)

    # ---------------------------------------
    # 🔐 LEGACY / SUPPLEMENTAL SIGNALS
    # (kept but NOT primary classification)
    # ---------------------------------------

    # Credentials
    if any(k in text_lower for k in ["password", "passwd", "pwd"]):
        flags.append("CREDENTIAL")
        matches.append({"type": "credential", "value": "keyword"})
        rule_hits.append("credential_keyword")

    # SSN
    if re.search(r"\b\d{3}-\d{2}-\d{4}\b", text):
        flags.append("PII_SSN")
        matches.append({"type": "ssn", "value": "pattern"})
        rule_hits.append("ssn_pattern")

    # Email
    if re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text):
        flags.append("EMAIL")
        matches.append({"type": "email", "value": "pattern"})
        rule_hits.append("email_pattern")

    # Financial
    if re.search(r"\b\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}\b", text):
        flags.append("FINANCIAL")
        matches.append({"type": "card", "value": "pattern"})
        rule_hits.append("card_pattern")

    # ---------------------------------------
    # 🔥 HEURISTIC BOOST (kept, but scored)
    # ---------------------------------------
    export_signals = [
        "export", "controlled", "defense",
        "military", "restricted", "compliance",
        "regulation", "license", "authorization"
    ]

    signal_score = sum(1 for s in export_signals if s in text_lower)

    if signal_score >= 3:
        scores["EXPORT_CONTROL"] = scores.get("EXPORT_CONTROL", 0) + 2
        rule_hits.append("export_control_heuristic")

    # ---------------------------------------
    # 🧠 FINAL CATEGORY RESOLVE (AFTER BOOST)
    # ---------------------------------------
    primary_category = resolve_category(scores)

    has_cui = primary_category is not None

    # ---------------------------------------
    # 🧪 DEBUG
    # ---------------------------------------
    if has_cui:
        print(f"🚨 PRIMARY CATEGORY: {primary_category}")
        print(f"🧠 SCORES: {scores}")
        print(f"🧠 RULE HITS: {hits}")

    # ---------------------------------------
    # ✅ OUTPUT (STANDARDIZED)
    # ---------------------------------------
    return {
        "has_cui": has_cui,
        "primary_category": primary_category,   # 🔥 USE THIS IN UI
        "categories": categories,
        "scores": scores,
        "hit_count": hit_count,
        "matches": matches,
        "rule_hits": hits
    }