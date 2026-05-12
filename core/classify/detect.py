"""
CUI Detection Logic (Final Stabilized Version)

- Strong signal gating (prevents false positives)
- Allows valid single-signal CUI
- Removes weak fallback logic
- Keeps severity + confidence scoring
"""

from typing import Dict
from core.classify.rules import run_rules, CUI_KEYWORDS
from .cui_mapping import map_cui_categories

from core.classify.compliance_mapping import CATEGORY_SEVERITY


CATEGORY_SEVERITY = {
    "ITAR": "CRITICAL",
    "EXPORT_CONTROL": "CRITICAL",
    "PII": "HIGH",
    "FINANCIAL": "HIGH",
    "FOUO": "MEDIUM",
    "CUI": "MEDIUM",
}

SEVERITY_ORDER = {
    "LOW": 1,
    "MEDIUM": 2,
    "HIGH": 3,
    "CRITICAL": 4,
}


def _detect(text: str):
    rule_hits = run_rules(text) or []

    matches = []
    matched_values = []

    # --------------------------------------------------
    # 🔥 STEP 1: DEDUPE (UNCHANGED)
    # --------------------------------------------------
    seen = set()
    deduped = []

    for hit in rule_hits:
        key = (
            hit.get("rule"),
            hit.get("match"),
            hit.get("category"),
        )
        if key not in seen:
            seen.add(key)
            deduped.append(hit)

    rule_hits = deduped

    # --------------------------------------------------
    # 🔥 STEP 2: LOWER TEXT
    # --------------------------------------------------
    text_lower = text.lower()

    # ---------------------------------------
    # 🧠 KEYWORD-BASED CUI DETECTION (FIXED)
    # ---------------------------------------
    keyword_hits = False

    seen_categories = set()
    seen_keywords = set()

    for category, keywords in CUI_KEYWORDS.items():
        for keyword in keywords:
            if keyword in text_lower:
                keyword_hits = True

                if category.upper() not in seen_categories:
                    matches.append(category.upper())
                    seen_categories.add(category.upper())

                if keyword not in seen_keywords:
                    matched_values.append(keyword)
                    seen_keywords.add(keyword)

    # --------------------------------------------------
    # 🔥 STEP 3: EARLY EXIT FIX (IMPORTANT)
    # --------------------------------------------------
    if not rule_hits and not keyword_hits:
        return _empty_result()

    # --------------------------------------------------
    # 🔥 STEP 4: COUNT SIGNALS (UNCHANGED)
    # --------------------------------------------------
    counts = {}
    for h in rule_hits:
        cat = h.get("category")
        counts[cat] = counts.get(cat, 0) + 1

    strong_hits = []

    # ==================================================
    # 🔴 CATEGORY FILTERING (UNCHANGED LOGIC)
    # ==================================================
    for h in rule_hits:
        cat = h.get("category")

        if cat in [
            "CUI",
            "EXPORT_CONTROL",
            "CREDENTIALS",
            "PHI",
            "GOV_ID",
            "SYSTEM_INTERNAL",
            "IP"
        ]:
            strong_hits.append(h)

        elif cat == "FINANCIAL":
            if h.get("rule") in [
                "credit_card",
                "routing_number",
                "bank_transfer",
                "invoice",
                "payment",
                "receipt"
            ]:
                strong_hits.append(h)

        elif cat == "PII":
            pii_count = counts.get("PII", 0)

            if h.get("rule") in ["ssn", "invoice_identity"]:
                strong_hits.append(h)

            elif h.get("rule") == "address_structured":
                if (
                    pii_count >= 2
                    or any(k in text_lower for k in [
                        "invoice", "receipt", "bill to",
                        "amount due", "payment", "total"
                    ])
                ):
                    strong_hits.append(h)

            elif h.get("rule") == "multiple_emails":
                if (
                    pii_count >= 2
                    or any(k in text_lower for k in [
                        "invoice", "receipt", "contact", "billing"
                    ])
                ):
                    strong_hits.append(h)

    # --------------------------------------------------
    # 🔥 STEP 5: FINAL FILTER
    # --------------------------------------------------
    if not strong_hits and not keyword_hits:
        return _empty_result()

    # --------------------------------------------------
    # 🔥 STEP 6: BUILD MATCHES FROM RULE HITS
    # --------------------------------------------------
    for h in strong_hits:
        cat = h.get("category")
        val = h.get("match")

        if cat:
            matches.append(cat)

        if val:
            matched_values.append(val)

    # --------------------------------------------------
    # 🔥 STEP 7: CATEGORY MAPPING
    # --------------------------------------------------
    categories = map_cui_categories(strong_hits)

    if not categories and keyword_hits:
        categories = ["CUI"]

    normalized = set([c.upper() for c in categories])

    # --------------------------------------------------
    # 🔥 STEP 8: HIT COUNT
    # --------------------------------------------------
    hit_count = len(strong_hits) + (1 if keyword_hits else 0)

    # --------------------------------------------------
    # 🔥 STEP 9: SEVERITY
    # --------------------------------------------------
    derived = []

    for cat in normalized:
        if cat in CATEGORY_SEVERITY:
            derived.append(CATEGORY_SEVERITY[cat])

    if not derived:
        derived.append("LOW")

    severity = max(derived, key=lambda x: SEVERITY_ORDER[x])

    if "CREDENTIALS" in normalized:
        severity = "CRITICAL"

    if hit_count >= 3:
        severity = max(severity, "HIGH", key=lambda x: SEVERITY_ORDER[x])

    # --------------------------------------------------
    # 🔥 STEP 10: CONFIDENCE
    # --------------------------------------------------
    if severity == "CRITICAL" or hit_count >= 6:
        confidence = "CRITICAL"
    elif hit_count >= 3:
        confidence = "HIGH"
    elif hit_count == 2:
        confidence = "MEDIUM"
    else:
        confidence = "LOW"

    if "CUI" in normalized:
        confidence = max(confidence, "MEDIUM", key=lambda x: SEVERITY_ORDER[x])

    if "CREDENTIALS" in normalized:
        confidence = max(confidence, "HIGH", key=lambda x: SEVERITY_ORDER[x])

    # --------------------------------------------------
    # 🔥 STEP 11: FINDINGS
    # --------------------------------------------------
    findings = [
        {
            "rule": hit.get("rule"),
            "match": hit.get("match"),
            "category": hit.get("category"),
        }
        for hit in strong_hits
    ]

    # --------------------------------------------------
    # 🔥 FINAL RETURN (CRITICAL FIX)
    # --------------------------------------------------
    return {
        "contains_cui": True,
        "has_cui": True,
        "categories": list(normalized),
        "rule_hits": strong_hits,
        "findings": findings,
        "severity": severity,
        "confidence": confidence,
        "hit_count": hit_count,

        # ✅ REQUIRED FOR VIEWER + HIGHLIGHTING
        "matches": list(set(matches)),
        "matched_values": list(set(matched_values)),
    }


def _empty_result():
    return {
        "contains_cui": False,
        "has_cui": False,
        "categories": [],
        "rule_hits": [],
        "severity": "LOW",
        "confidence": "LOW",
        "hit_count": 0,
    }


def detect_cui(text: str) -> Dict:
    if not text or not text.strip():
        return _empty_result()

    return _detect(text)


def classify_attachments():
    return None