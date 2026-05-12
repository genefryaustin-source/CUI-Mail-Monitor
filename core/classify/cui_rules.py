# modules/cui_rules.py
from typing import List, Dict, Any
import re

DEFAULT_RULES: List[Dict[str, Any]] = [
    # High-confidence identifiers (examples)
    {
        "id": "CUI-SSN",
        "name": "Possible SSN",
        "severity": "high",
        "pattern": r"\b(?!000|666|9\d\d)\d{3}[- ]?(?!00)\d{2}[- ]?(?!0000)\d{4}\b",
        "flags": re.IGNORECASE,
        "context_chars": 80,
    },
    {
        "id": "CUI-DODID",
        "name": "Possible DoD ID (10 digits)",
        "severity": "high",
        "pattern": r"\b\d{10}\b",
        "flags": re.IGNORECASE,
        "context_chars": 60,
    },
    # “CUI” markings / phrases
    {
        "id": "CUI-MARKING",
        "name": "CUI marking keywords",
        "severity": "high",
        "pattern": r"\b(CONTROLLED\s+UNCLASSIFIED\s+INFORMATION|CUI\s*(//|/)?\s*(BASIC|SP)?|CUI\s+CONTROLLED)\b",
        "flags": re.IGNORECASE,
        "context_chars": 120,
    },
    # Export control indicators (keywords only – tune to your environment)
    {
        "id": "CUI-EXPORT",
        "name": "Export-controlled indicators (ITAR/EAR)",
        "severity": "med",
        "pattern": r"\b(ITAR|EAR99|ECCN|EXPORT\s+CONTROLLED|DFARS\s+252\.204-7012)\b",
        "flags": re.IGNORECASE,
        "context_chars": 120,
    },
    # Contract / program indicators (usually “needs review” not definitive)
    {
        "id": "CUI-CONTRACT",
        "name": "Contract / CUI program indicators",
        "severity": "low",
        "pattern": r"\b(CDRL|DD254|SOW|PWS|CLIN|WAWF|CAGE\s*CODE)\b",
        "flags": re.IGNORECASE,
        "context_chars": 120,
    },
]

def compile_rules(rules: List[Dict[str, Any]]):
    compiled = []
    for r in rules:
        compiled.append({
            **r,
            "regex": re.compile(r["pattern"], r.get("flags", 0))
        })
    return compiled
