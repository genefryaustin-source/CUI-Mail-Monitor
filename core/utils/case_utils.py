import hashlib

def generate_case_id(evidence_id: str) -> str:
    return hashlib.sha256(evidence_id.encode()).hexdigest()[:16]

def normalize_case_id(case_id, evidence_id=None):
    """
    Ensures case_id is always valid.
    Falls back to deterministic generation if needed.
    """
    if case_id and isinstance(case_id, str) and len(case_id) > 5:
        return case_id.strip()

    if evidence_id:
        return generate_case_id(str(evidence_id))

    return None