# core/modules/exporters.py
from __future__ import annotations

import csv
import io
import json
from typing import Any, Dict, List


def _to_csv(rows: List[Dict[str, Any]], fieldnames: List[str]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow(r)
    return buf.getvalue()


def build_exports(findings: List[Dict[str, Any]], evidence_manifest: List[Dict[str, Any]]) -> Dict[str, str]:
    # POA&M starter rows (you can expand to full FedRAMP POA&M format)
    poam_rows = []
    for f in findings:
        if f.get("cui_confidence", 0.0) >= 0.6:
            poam_rows.append(
                {
                    "POAM_ID": f"POAM-{f['run_id'][:8]}-{len(poam_rows)+1:03d}",
                    "Weakness_Description": f"Potential CUI detected in {f.get('filename')}",
                    "Risk_Level": "High" if f["cui_confidence"] >= 0.85 else "Moderate",
                    "Recommendation": "Validate CUI markings, restrict sharing, apply encryption, and document handling controls.",
                    "Source_Message_ID": f.get("message_id"),
                    "Evidence_SHA256": "",  # can join by (message_id, filename) if desired
                }
            )

    poam_csv = _to_csv(
        poam_rows,
        ["POAM_ID", "Weakness_Description", "Risk_Level", "Recommendation", "Source_Message_ID", "Evidence_SHA256"],
    )

    # SSP Annex starter: what was found + how handled
    ssp_rows = []
    for f in findings:
        ssp_rows.append(
            {
                "Control_Family": "MP/SC/AU",
                "Control_Statement": "Monitor inbound email for controlled content and maintain evidence integrity.",
                "Implementation_Summary": f"Scanned attachment '{f.get('filename')}' and generated chain-of-custody hash.",
                "CUI_Labels": f.get("cui_labels", ""),
                "CUI_Confidence": f.get("cui_confidence", 0.0),
            }
        )

    ssp_csv = _to_csv(
        ssp_rows,
        ["Control_Family", "Control_Statement", "Implementation_Summary", "CUI_Labels", "CUI_Confidence"],
    )

    bundle_json = json.dumps(
        {"findings": findings, "evidence_manifest": evidence_manifest, "poam": poam_rows},
        indent=2,
        default=str,
    )

    return {"poam_csv": poam_csv, "ssp_csv": ssp_csv, "bundle_json": bundle_json}
