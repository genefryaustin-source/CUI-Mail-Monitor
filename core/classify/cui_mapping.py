"""
CUI Category Mapping

Maps rule hits to official CUI categories aligned with:

• NIST 800-171
• DFARS
• ITAR (optional future)
• Export Control
• Privacy

This module is intentionally simple and deterministic.
Later this can be upgraded to ML classification without
changing the public function.
"""

from typing import List, Dict


# --------------------------------------------------------
# RULE → CATEGORY MAP
# Expand freely as detection matures
# --------------------------------------------------------

RULE_CATEGORY_MAP = {

    # Privacy / PII
    "SSN": "Controlled Technical Information",
    "SOCIAL_SECURITY": "Privacy",
    "DOB": "Privacy",
    "DRIVERS_LICENSE": "Privacy",
    "PASSPORT": "Privacy",

    # Financial
    "BANK_ACCOUNT": "Financial",
    "ROUTING_NUMBER": "Financial",
    "CREDIT_CARD": "Financial",

    # Defense / Export
    "ITAR": "Export Controlled",
    "EAR": "Export Controlled",
    "DFARS": "Defense",

    # Healthcare
    "PHI": "Healthcare",

    # Gov identifiers
    "CAGE": "Government Identifier",
    "DUNS": "Government Identifier",
}


# --------------------------------------------------------
# PUBLIC API
# --------------------------------------------------------

def map_cui_categories(rule_hits):
    categories = set()

    for hit in rule_hits or []:
        cat = (hit.get("category") or "").strip().upper()

        if cat in {"CUI", "FOUO", "ITAR", "PII", "FINANCIAL"}:
            categories.add(cat)
        elif cat:
            categories.add(cat)

    return sorted(categories) if categories else ["UNCATEGORIZED CUI"]


