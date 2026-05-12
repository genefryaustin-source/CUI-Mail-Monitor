# core/classify/compliance_mapping.py

CATEGORY_COMPLIANCE_MAP = {
    "CUI": {
        "description": "Controlled Unclassified Information and safeguarding markings.",
        "fedramp_nist_800_53_families": ["AC", "AU", "IR", "MP", "SC", "SI"],
        "nist_800_171_families": ["3.1", "3.3", "3.6", "3.8", "3.13", "3.14"],
        "notes": "Use the CUI Registry and agency-specific policy for final category/marking decisions.",
    },
    "EXPORT_CONTROL": {
        "description": "ITAR/EAR/DFARS export-controlled information.",
        "fedramp_nist_800_53_families": ["AC", "AU", "MP", "SC", "SI"],
        "nist_800_171_families": ["3.1", "3.3", "3.8", "3.13", "3.14"],
        "notes": "Commonly operationalized as a high-sensitivity CUI-adjacent category.",
    },
    "CREDENTIALS": {
        "description": "Passwords, tokens, private keys, secrets, API keys.",
        "fedramp_nist_800_53_families": ["AC", "AU", "IA", "IR", "SC", "SI"],
        "nist_800_171_families": ["3.1", "3.5", "3.6", "3.13", "3.14"],
        "notes": "Treat exposed secrets as highest operational priority.",
    },
    "PII": {
        "description": "Personal identifiers and identity context.",
        "fedramp_nist_800_53_families": ["AC", "AU", "PT", "RA", "SC", "SI"],
        "nist_800_171_families": ["3.1", "3.3", "3.13", "3.14"],
        "notes": "PT family is especially relevant in 800-53 privacy context.",
    },
    "GOV_ID": {
        "description": "Government-issued identifiers like passport or driver's license.",
        "fedramp_nist_800_53_families": ["AC", "AU", "PT", "SC", "SI"],
        "nist_800_171_families": ["3.1", "3.3", "3.13", "3.14"],
        "notes": "Operationally often handled as a special PII subtype.",
    },
    "PHI": {
        "description": "Protected health information and medical context.",
        "fedramp_nist_800_53_families": ["AC", "AU", "PT", "RA", "SC", "SI"],
        "nist_800_171_families": ["3.1", "3.3", "3.13", "3.14"],
        "notes": "Useful even if HIPAA is not the primary framework.",
    },
    "FINANCIAL": {
        "description": "Payment, invoice, banking, transfer, and card data.",
        "fedramp_nist_800_53_families": ["AC", "AU", "IR", "SC", "SI"],
        "nist_800_171_families": ["3.1", "3.3", "3.6", "3.13", "3.14"],
        "notes": "Fraud and account takeover workflows often map here.",
    },
    "SYSTEM_INTERNAL": {
        "description": "Internal system/network details, private addressing, infrastructure context.",
        "fedramp_nist_800_53_families": ["AC", "AU", "CM", "RA", "SC", "SI"],
        "nist_800_171_families": ["3.1", "3.4", "3.11", "3.13", "3.14"],
        "notes": "High operational value for cloud and infrastructure security.",
    },
    "IP": {
        "description": "Source code, trade secrets, proprietary designs and architecture.",
        "fedramp_nist_800_53_families": ["AC", "AU", "CM", "MP", "SC", "SI"],
        "nist_800_171_families": ["3.1", "3.4", "3.8", "3.13", "3.14"],
        "notes": "Operational overlay for internal data loss prevention.",
    },
}

CATEGORY_PRIORITY = {
    "CREDENTIALS": 5,
    "CUI": 4,
    "EXPORT_CONTROL": 4,
    "PHI": 3,
    "FINANCIAL": 3,
    "GOV_ID": 2,
    "PII": 2,
    "SYSTEM_INTERNAL": 2,
    "IP": 1,
}

CATEGORY_SEVERITY = {
    "CREDENTIALS": "CRITICAL",
    "CUI": "HIGH",
    "EXPORT_CONTROL": "HIGH",
    "PHI": "HIGH",
    "FINANCIAL": "HIGH",
    "GOV_ID": "HIGH",
    "PII": "MEDIUM",
    "SYSTEM_INTERNAL": "MEDIUM",
    "IP": "MEDIUM",
}