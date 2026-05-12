# core/pipeline/scan_pipeline.py

def run_scan_pipeline(config):
    print("📥 Fetching emails...")

    from core.ingest.gmail_ingest import fetch_emails
    from core.services.scan_service import extract_documents, classify_documents
    from core.services.evidence_service import record_evidence

    # ---------------------------------------
    # 📥 INGEST
    # ---------------------------------------
    emails = fetch_emails(config)

    print(f"📄 Extracting documents... {len(emails)} emails")

    # ---------------------------------------
    # 📄 NORMALIZE
    # ---------------------------------------
    docs = extract_documents(emails)

    print(f"🧠 Classifying documents... {len(docs)} docs")

    # ---------------------------------------
    # 🧠 DETECTION
    # ---------------------------------------
    findings = classify_documents(docs)

    print(f"🧾 Recording evidence... {len(findings)} findings")

    # ---------------------------------------
    # 🧾 EVIDENCE
    # ---------------------------------------
    record_evidence(findings)

    return findings
