# core/compliance/compliance_export.py

import csv
import json
from datetime import datetime, timezone
from core.classify.compliance_mapping import CATEGORY_COMPLIANCE_MAP, CATEGORY_PRIORITY


def build_compliance_record(alert_row: dict) -> dict:
    category = alert_row.get("category", "UNKNOWN")
    mapping = CATEGORY_COMPLIANCE_MAP.get(category, {})

    return {
        "exported_at_utc": datetime.now(timezone.utc).isoformat(),
        "alert_id": alert_row.get("id"),
        "category": category,
        "priority": CATEGORY_PRIORITY.get(category, 0),
        "severity": alert_row.get("severity"),
        "location": alert_row.get("location"),
        "source_name": alert_row.get("source_name"),
        "notes": alert_row.get("notes"),
        "status": alert_row.get("status"),
        "created_at": alert_row.get("created_at"),
        "compliance_mapping": {
            "description": mapping.get("description"),
            "fedramp_nist_800_53_families": mapping.get("fedramp_nist_800_53_families", []),
            "nist_800_171_families": mapping.get("nist_800_171_families", []),
            "notes": mapping.get("notes"),
        },
    }


def export_alerts_to_json(alert_rows: list[dict], out_path: str) -> str:
    payload = [build_compliance_record(r) for r in alert_rows]
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    return out_path


def export_alerts_to_csv(alert_rows: list[dict], out_path: str) -> str:
    rows = [build_compliance_record(r) for r in alert_rows]

    fieldnames = [
        "exported_at_utc",
        "alert_id",
        "category",
        "priority",
        "severity",
        "location",
        "source_name",
        "notes",
        "status",
        "created_at",
        "fedramp_nist_800_53_families",
        "nist_800_171_families",
        "mapping_description",
        "mapping_notes",
    ]

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for r in rows:
            mapping = r["compliance_mapping"]
            writer.writerow({
                "exported_at_utc": r["exported_at_utc"],
                "alert_id": r["alert_id"],
                "category": r["category"],
                "priority": r["priority"],
                "severity": r["severity"],
                "location": r["location"],
                "source_name": r["source_name"],
                "notes": r["notes"],
                "status": r["status"],
                "created_at": r["created_at"],
                "fedramp_nist_800_53_families": ",".join(mapping.get("fedramp_nist_800_53_families", [])),
                "nist_800_171_families": ",".join(mapping.get("nist_800_171_families", [])),
                "mapping_description": mapping.get("description"),
                "mapping_notes": mapping.get("notes"),
            })

    return out_path