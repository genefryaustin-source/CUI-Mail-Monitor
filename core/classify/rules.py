# core/classify/rules.py

"""
CUI RULE ENGINE (PHASE 3 - GOVERNMENT-ALIGNED EXPANSION)

Preserves existing logic and adds:
- Credentials detection
- Export control detection
- PHI detection
- Government ID detection
- System/internal data detection
- IP / proprietary detection

NO breaking changes to existing rule names or behavior
"""

from typing import List, Dict
import re
import time


# ------------------------
# Debug Helper (UNCHANGED)
# ------------------------

def _ui_debug(storage, message: str):
    try:
        with storage.ledger._connect() as con:
            con.execute("""
                INSERT INTO ui_debug_log (created_at_ms, message)
                VALUES (?, ?)
            """, (
                int(time.time() * 1000),
                message
            ))
            con.commit()
    except Exception as e:
        print("⚠️ UI DEBUG FAILED:", e)


# ------------------------------------------------------------------
# BASELINE KEYWORDS (UNCHANGED)
# ------------------------------------------------------------------

CUI_KEYWORDS = {
    "CUI":  ["cui",
    "controlled unclassified information"],
    "CONTROLLED_TECHNICAL_INFORMATION": [
        "technical data",
        "engineering drawing",
        "specification",
        "design document",
    ],
    "PERSONAL_DATA": [
        "social security",
        "ssn",
        "date of birth",
        "passport",
    ],
    "FINANCIAL_DATA": [
        "bank account",
        "routing number",
        "credit card",
    ],
}


# ------------------------------------------------------------------
# PUBLIC API (UNCHANGED)
# ------------------------------------------------------------------

def find_matches(text: str) -> List[Dict[str, str]]:
    if not text:
        return []

    text_lower = text.lower()
    matches: List[Dict[str, str]] = []

    for category, keywords in CUI_KEYWORDS.items():
        for kw in keywords:
            if kw in text_lower:
                matches.append(
                    {
                        "category": category,
                        "match": kw,
                    }
                )

    return matches


# ------------------------------------------------------------------
# MAIN RULE ENGINE (EXTENDED)
# ------------------------------------------------------------------

def run_rules(text: str, storage=None):
    if not text:
        return []

    lowered = text.lower()
    hits = []

    def add(rule, match, category):
        hits.append({
            "rule": rule,
            "match": match,
            "category": category
        })

    # ---------------------------------------
    # 🔴 CUI (UNCHANGED)
    # ---------------------------------------
    if re.search(r"\bcui\b", lowered):
        add("cui_keyword", "cui", "CUI")

    if "controlled unclassified information" in lowered:
        add("cui_full", "controlled unclassified information", "CUI")

    # ---------------------------------------
    # 🟠 FINANCIAL (UNCHANGED)
    # ---------------------------------------
    financial_keywords = [
        "account number",
        "routing number",
        "credit card",
        "wire transfer",
        "iban",
        "swift",
        "invoice",
        "receipt",
        "amount due",
        "payment"
    ]

    for kw in financial_keywords:
        if kw in lowered:
            add("financial_keyword", kw, "FINANCIAL")

    # ---------------------------------------
    # 🟡 PII (UNCHANGED)
    # ---------------------------------------

    if re.search(r"\b\d{3}-\d{2}-\d{4}\b", text):
        add("ssn", "ssn", "PII")

    emails = re.findall(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", lowered)

    if len(emails) >= 3:
        add("multiple_emails", "multiple_emails", "PII")

    if re.search(
        r"\b\d{1,5}\s+[A-Za-z0-9\s]+\b(street|st|road|rd|ave|avenue|drive|dr)\b",
        lowered
    ):
        add("address_structured", "address", "PII")

    if "bill to" in lowered or "invoice number" in lowered:
        add("invoice_identity", "invoice_identity", "PII")

    # 🔴 Newsletter suppression (UNCHANGED)
    if "unsubscribe" in lowered:
        return []

    # ==================================================
    # 🔥 NEW CATEGORIES (NON-BREAKING ADDITIONS)
    # ==================================================

    # ---------------------------------------
    # 🔴 EXPORT CONTROL
    # ---------------------------------------
    if any(x in lowered for x in [
        "itar",
        "ear",
        "export controlled",
        "dfars",
        "controlled technical information"
    ]):
        add("export_control", "export_control", "EXPORT_CONTROL")

    # ---------------------------------------
    # 🔴 CREDENTIALS (CRITICAL)
    # ---------------------------------------
    if re.search(r"(api[_-]?key|secret[_-]?key|private[_-]?key|client_secret)", lowered):
        add("credential_exposure", "credential", "CREDENTIALS")

    if re.search(r"password\s*[:=]\s*\S+", lowered):
        add("password_exposure", "password", "CREDENTIALS")

    if re.search(r"bearer\s+[a-z0-9\-_\.=]+", lowered):
        add("token_exposure", "token", "CREDENTIALS")

    # ---------------------------------------
    # 🔴 PHI
    # ---------------------------------------
    if any(x in lowered for x in [
        "patient",
        "diagnosis",
        "treatment",
        "medical record",
        "prescription"
    ]):
        add("phi_detected", "phi", "PHI")

    # ---------------------------------------
    # 🔴 GOV ID
    # ---------------------------------------
    if any(x in lowered for x in [
        "passport number",
        "driver license",
        "state id",
        "military id"
    ]):
        add("gov_id", "gov_id", "GOV_ID")

    # ---------------------------------------
    # 🔴 SYSTEM / INTERNAL
    # ---------------------------------------
    if re.search(r"\b10\.\d+\.\d+\.\d+\b", text):
        add("internal_ip", "internal_ip", "SYSTEM_INTERNAL")

    if any(x in lowered for x in [
        ".internal",
        "prod-db",
        "kubernetes",
        "cluster"
    ]):
        add("internal_system", "internal_system", "SYSTEM_INTERNAL")

    # ---------------------------------------
    # 🔴 IP / PROPRIETARY
    # ---------------------------------------
    if any(x in lowered for x in [
        "source code",
        "proprietary",
        "trade secret",
        "internal design"
    ]):
        add("ip_detected", "ip", "IP")

    # ---------------------------------------
    # 🔥 DEBUG (UNCHANGED)
    # ---------------------------------------
    if storage:
        _ui_debug(storage, f"🧪 RULE INPUT: {text[:200]}")
        _ui_debug(storage, f"🧪 LOWERED: {lowered[:200]}")
        _ui_debug(storage, f"🧪 HITS: {hits}")

    return hits

# ---------------------------------------
# 🚀 SCORING ENGINE
# ---------------------------------------

def score_hits(hits):
    WEIGHTS = {
        "EXPORT_CONTROL": 5,
        "CONTROLLED_TECHNICAL_INFORMATION": 5,
        "CREDENTIALS": 6,
        "PHI": 4,
        "PII": 3,
        "FINANCIAL": 3,
        "IP": 2,
        "SYSTEM_INTERNAL": 2,
        "CUI": 2
    }

    scores = {}

    for h in hits:
        cat = h.get("category")
        if not cat:
            continue
        scores[cat] = scores.get(cat, 0) + WEIGHTS.get(cat, 1)

    return scores


# ---------------------------------------
# 🎯 RESOLVE PRIMARY CATEGORY
# ---------------------------------------

def resolve_category(scores):
    if not scores:
        return None

    return max(scores, key=scores.get)

def resolve_categories(scores):
    if not scores:
        return []

    # keep strong signals only
    max_score = max(scores.values())

    return [
        cat for cat, score in scores.items()
        if score >= max_score - 1
    ]

def detect_structure(text):
    patterns = [
        r"DOCUMENT CONTROL",
        r"CATEGORY \d+",
        r"TECHNICAL DATA",
        r"EXPORTER:",
        r"ITAR",
    ]

    matches = sum(bool(re.search(p, text, re.IGNORECASE)) for p in patterns)

    if matches >= 2:
        return "CONTROLLED_TECHNICAL_INFORMATION"

    return None

def analyze_cui(text: str, storage=None):
    hits = run_rules(text, storage)

    scores = score_hits(hits)

    # 🔥 structure boost
    struct_cat = detect_structure(text)
    if struct_cat:
        scores[struct_cat] = scores.get(struct_cat, 0) + 5

    categories = resolve_categories(scores)

    return {
        "has_cui": len(categories) > 0,
        "categories": categories,
        "hit_count": len(hits),
        "rule_hits": hits
    }