# core/services/scan_service.py

def extract_documents(emails):
    """
    Normalize emails into documents
    """
    docs = []

    for e in emails:
        docs.append({
            "id": e.get("id"),
            "subject": e.get("subject", ""),
            "content": e.get("body", ""),
            "sender": e.get("from", ""),
        })

    return docs


def classify_documents(docs):
    """
    Simple rule-based detection (placeholder for AI later)
    """
    findings = []

    for d in docs:
        text = (d.get("content") or "").lower()

        if "ssn" in text:
            findings.append({
                "doc_id": d["id"],
                "type": "CUI",
                "rule": "SSN_DETECTED",
                "confidence": 0.95,
            })

        elif "confidential" in text:
            findings.append({
                "doc_id": d["id"],
                "type": "SENSITIVE",
                "rule": "CONFIDENTIAL_KEYWORD",
                "confidence": 0.85,
            })

    return findings