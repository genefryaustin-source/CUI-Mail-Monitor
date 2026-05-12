import hashlib
from pathlib import Path

def build_demo_dataset(storage):
    vault = storage.vault
    ledger = storage.ledger

    demo_run_id = "demo_run"
    ledger.ensure_run(
        run_id=demo_run_id,
        provider="demo_dataset",
        mailbox="demo@local",
    )

    samples = [
        {
            "name": "email_security_alert.txt",
            "content": b"Suspicious login detected from new IP address.",
            "content_type": "text/plain",
            "metadata": {"type": "email", "severity": "high"},
        },
        {
            "name": "system_log_entry.log",
            "content": b"[ERROR] Unauthorized API access attempt.",
            "content_type": "text/plain",
            "metadata": {"type": "log", "severity": "critical"},
        },
        {
            "name": "ai_generated_report.json",
            "content": b'{"summary": "Potential insider threat detected."}',
            "content_type": "application/json",
            "metadata": {"type": "report", "severity": "medium"},
        },
    ]

    inserted_ids = []

    for sample in samples:
        content = sample["content"]
        expected_sha = hashlib.sha256(content).hexdigest()

        existing = ledger.lookup_evidence_by_sha256(expected_sha)
        print("LOOKUP SHA:", expected_sha, existing)

        if existing:
            print(f"FOUND EXISTING: {sample['name']}")

            storage_uri = existing["storage_uri"]
            path = Path(storage_uri)

            repair_needed = True
            if path.exists():
                actual_sha = hashlib.sha256(path.read_bytes()).hexdigest()
                repair_needed = (actual_sha != expected_sha)

            if repair_needed:
                print(f"REPAIRING TAMPERED FILE: {sample['name']}")
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)

                ledger.record_custody_event(
                    run_id=demo_run_id,
                    evidence_id=existing["evidence_id"],
                    event_type="RESTORED",
                    actor="demo_loader",
                    details={"source": "demo_dataset_repair"},
                )
            else:
                print(f"SKIP (healthy): {sample['name']}")

            inserted_ids.append(existing["evidence_id"])
            continue

        print(f"CREATING: {sample['name']}")

        record = vault.put_bytes(
            data=content,
            suggested_name=sample["name"],
            content_type=sample.get("content_type", "application/octet-stream"),
            metadata=sample.get("metadata", {}),
        )

        ledger.record_evidence(
            evidence_id=record.evidence_id,
            sha256=record.sha256,
            size_bytes=record.size_bytes,
            content_type=record.content_type,
            storage_uri=record.storage_uri,
            suggested_name=record.suggested_name,
            created_at_ms=record.created_at_ms,
            metadata=record.metadata,
        )

        ledger.record_custody_event(
            run_id=demo_run_id,
            evidence_id=record.evidence_id,
            event_type="INGESTED",
            actor="demo_loader",
            details={"source": "demo_dataset"},
        )

        inserted_ids.append(record.evidence_id)

    return inserted_ids

