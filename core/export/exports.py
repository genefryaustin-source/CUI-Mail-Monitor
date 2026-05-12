"""
exports.py

Production-grade export helpers for evidence manifests,
chain-of-custody, and audit artifacts.

Design goals:
✔ Deterministic outputs
✔ Byte-safe for Streamlit download
✔ Audit-friendly formatting
✔ Future S3 vault compatibility
✔ No relative imports
"""

from typing import Dict, Any
import json
import csv
import io
from datetime import datetime

# ✅ Absolute import (critical fix)
from core.evidence.chain_of_custody import export_manifest_json_bytes


# ============================================================
# MANIFEST EXPORT
# ============================================================

def manifest_to_json_bytes(manifest: Dict[str, Any]) -> bytes:
    """
    Convert manifest dict → deterministic JSON bytes.

    This wrapper ensures consistent formatting even if the
    underlying chain_of_custody module evolves.
    """

    return export_manifest_json_bytes(manifest)


# ============================================================
# CSV EXPORT (Auditor Friendly)
# ============================================================

def manifest_to_csv_bytes(manifest: Dict[str, Any]) -> bytes:
    """
    Convert manifest → flattened CSV.

    Auditors LOVE CSV because it drops into Excel instantly.
    """

    output = io.StringIO()
    writer = csv.writer(output)

    # Header
    writer.writerow([
        "run_id",
        "evidence_id",
        "timestamp_utc",
        "hash_sha256",
        "source",
        "filename",
        "cui_detected",
        "cui_categories"
    ])

    run_id = manifest.get("run_id", "unknown")

    for item in manifest.get("evidence", []):
        writer.writerow([
            run_id,
            item.get("evidence_id"),
            item.get("timestamp_utc"),
            item.get("hash_sha256"),
            item.get("source"),
            item.get("filename"),
            item.get("cui_detected"),
            ",".join(item.get("cui_categories", []))
        ])

    return output.getvalue().encode("utf-8")


# ============================================================
# POA&M EXPORT (Phase-ready)
# ============================================================

def generate_poam_stub(manifest: Dict[str, Any]) -> bytes:
    """
    Generates a starter POA&M file based on detected CUI findings.

    This is intentionally lightweight for now —
    later phases will map directly to:
        • NIST 800-171
        • FedRAMP controls
        • CMMC practices
    """

    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow([
        "POAM_ID",
        "Run_ID",
        "Evidence_ID",
        "Issue",
        "Severity",
        "Recommended_Action",
        "Status"
    ])

    poam_id = 1
    run_id = manifest.get("run_id", "unknown")

    for item in manifest.get("evidence", []):
        if item.get("cui_detected"):

            categories = ",".join(item.get("cui_categories", []))

            writer.writerow([
                f"POAM-{poam_id:04}",
                run_id,
                item.get("evidence_id"),
                f"CUI detected ({categories})",
                "HIGH",
                "Review document handling and apply proper markings.",
                "OPEN"
            ])

            poam_id += 1

    return output.getvalue().encode("utf-8")


# ============================================================
# HUMAN READABLE REPORT (Optional but Powerful)
# ============================================================

def manifest_to_pretty_json_bytes(manifest: Dict[str, Any]) -> bytes:
    """
    Pretty formatted JSON.

    Useful for:
        ✔ investigators
        ✔ auditors
        ✔ legal review
    """

    return json.dumps(
        manifest,
        indent=2,
        sort_keys=True,
        default=str
    ).encode("utf-8")


# ============================================================
# FUTURE — SIGNED MANIFEST HOOK
# ============================================================

def manifest_signature_placeholder(manifest: Dict[str, Any]) -> Dict[str, Any]:
    """
    Placeholder for Phase 2+ cryptographic signing.

    Will eventually integrate with:

        ✔ AWS KMS
        ✔ HSM
        ✔ Sigstore
        ✔ x509 evidence signing

    DO NOT REMOVE — auditors love seeing forward hooks.
    """

    manifest["signature"] = {
        "status": "unsigned",
        "algorithm": "reserved",
        "timestamp_utc": datetime.utcnow().isoformat()
    }

    return manifest
