import os
import json
import zipfile
import tempfile
import datetime

import base64

from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    PageBreak,
)
from reportlab.lib import colors

from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives import serialization
from core.utils.hash_utils import sha256_bytes, sha256_text, sha256_file

# ----------------------------
# HELPERS
# ----------------------------
def _fmt_ms(ms):
    if not ms:
        return "-"
    try:
        return datetime.datetime.fromtimestamp(int(ms) / 1000).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return "-"


def _safe_text(value):
    if value is None:
        return "-"
    return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
def _map_rules_to_nist_controls(rules):
    mapping = {
        "multiple_emails": ["AC-2", "IA-5"],  # account mgmt / auth
        "address_structured": ["IA-5", "SC-7"],  # identity / boundary
        "export_control": ["MP-7", "SC-7"],  # media protection / boundary
        "cui": ["AC-3", "SC-28"],  # access control / data protection
        "pii": ["IA-5", "AC-6"],  # least privilege / identity
    }

    controls = set()

    for r in rules:
        key = (r or "").lower()
        for k, v in mapping.items():
            if k in key:
                controls.update(v)

    return sorted(controls)
def _section(story, title, styles):
    story.append(Spacer(1, 14))
    story.append(Paragraph(title, styles["Heading2"]))
    story.append(Spacer(1, 6))


def _para(value, styles):
    return Paragraph(_safe_text(value).replace("\n", "<br/>"), styles["Normal"])


def _short(value, n=36):
    value = _safe_text(value)
    return value if len(value) <= n else value[:n] + "..."
def _map_rules_to_regulations(rules):
    mapping = {
        "export_control": "ITAR / EAR (Export Control)",
        "cui": "NIST SP 800-171 / CUI Handling",
        "pii": "NIST SP 800-53 IA/AC Controls",
        "address_structured": "PII (Privacy Impact)",
        "multiple_emails": "Data Exposure / Privacy",
    }

    regs = set()

    for r in rules:
        key = (r or "").lower()
        for k, v in mapping.items():
            if k in key:
                regs.add(v)

    return sorted(regs)

def _risk_color(level):
    level = (level or "").upper()
    if level in ("CRITICAL", "HIGH"):
        return colors.lightcoral
    if level == "MEDIUM":
        return colors.lightyellow
    return colors.whitesmoke
def _extract_detection_details(alerts, evidence_id):
    severity = "LOW"
    confidence = "LOW"
    rules = set()

    severity_rank = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}

    for a in alerts or []:
        if (a.get("evidence_id") or "") != evidence_id:
            continue

        try:
            notes = json.loads(a.get("notes") or "{}")
        except Exception:
            notes = {}

        # severity
        sev = (a.get("severity") or notes.get("severity") or "LOW").upper()
        if severity_rank.get(sev, 0) > severity_rank.get(severity, 0):
            severity = sev

        # confidence
        conf = (notes.get("confidence") or "LOW").upper()
        confidence = conf

        # rule hits
        for r in notes.get("rule_hits") or []:
            if isinstance(r, dict):
                rules.add(r.get("rule"))
            else:
                rules.add(str(r))

    return severity, confidence, sorted(rules)

def _extract_flags_from_alerts(alerts, evidence_id):
    flags = set()

    for a in alerts or []:
        if (a.get("evidence_id") or "") != evidence_id:
            continue

        try:
            notes = json.loads(a.get("notes") or "{}")
        except Exception:
            notes = {}

        for c in notes.get("categories") or []:
            flags.add(c)

        for m in notes.get("matches") or []:
            flags.add(m)

    return sorted(flags)


def _evidence_risk_from_alerts(alerts, evidence_id):
    severity_rank = {
        "CRITICAL": 4,
        "HIGH": 3,
        "MEDIUM": 2,
        "LOW": 1,
    }

    best = "LOW"

    for a in alerts or []:
        if (a.get("evidence_id") or "") != evidence_id:
            continue

        sev = (a.get("severity") or "LOW").upper()
        if severity_rank.get(sev, 0) > severity_rank.get(best, 0):
            best = sev

    return best


def _canonical_json_bytes(obj) -> bytes:
    """
    Stable JSON serialization for signing/verifying.
    """
    return json.dumps(
        obj,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def _serialize_clusters(clusters):
    if not clusters:
        return {}

    output = {}

    for cluster_name, items in clusters.items():
        output[cluster_name] = []

        for item in items:
            e = item.get("e") or {}

            output[cluster_name].append({
                "evidence_id": e.get("evidence_id") or e.get("id"),
                "suggested_name": e.get("suggested_name"),
                "score": item.get("score"),
                "level": item.get("level"),
                "match_count": len(item.get("matches") or []),
            })

    return output


# ----------------------------
# SIGNING HELPERS
# ----------------------------
def generate_signing_keypair(
    private_key_path="data/signing_private.pem",
    public_key_path="data/signing_public.pem",
):
    """
    Generates an Ed25519 signing keypair if you do not already have one.
    Keep the private key protected. Public key may be distributed.
    """
    private_dir = os.path.dirname(private_key_path)
    public_dir = os.path.dirname(public_key_path)

    if private_dir:
        os.makedirs(private_dir, exist_ok=True)

    if public_dir:
        os.makedirs(public_dir, exist_ok=True)

    private_key = ed25519.Ed25519PrivateKey.generate()
    public_key = private_key.public_key()

    with open(private_key_path, "wb") as f:
        f.write(private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ))

    with open(public_key_path, "wb") as f:
        f.write(public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ))

    return private_key_path, public_key_path


def _load_private_key(private_key_path="data/signing_private.pem"):
    if not os.path.exists(private_key_path):
        generate_signing_keypair(private_key_path=private_key_path)

    with open(private_key_path, "rb") as f:
        return serialization.load_pem_private_key(f.read(), password=None)


def _load_public_key(public_key_path="data/signing_public.pem"):
    with open(public_key_path, "rb") as f:
        return serialization.load_pem_public_key(f.read())


def _get_public_key_bytes(public_key_path="data/signing_public.pem") -> bytes:
    if not os.path.exists(public_key_path):
        generate_signing_keypair(public_key_path=public_key_path)

    with open(public_key_path, "rb") as f:
        return f.read()


def _sign_bytes(data: bytes, private_key_path="data/signing_private.pem") -> str:
    private_key = _load_private_key(private_key_path)
    signature = private_key.sign(data)
    return base64.b64encode(signature).decode("utf-8")
def _fedramp_severity_language(level):
    level = (level or "").upper()

    if level == "HIGH":
        return "This finding represents a significant deficiency that could lead to unauthorized access or data exposure."
    if level == "MEDIUM":
        return "This finding indicates a moderate control weakness requiring remediation."
    if level == "LOW":
        return "This finding represents a minor issue with limited security impact."
    return "Risk level undetermined."

def verify_signature_bytes(data: bytes, signature_b64: str, public_key_bytes: bytes) -> bool:
    try:
        public_key = serialization.load_pem_public_key(public_key_bytes)
        signature = base64.b64decode(signature_b64)
        public_key.verify(signature, data)
        return True
    except Exception:
        return False


def verify_signature(data: bytes, signature_b64: str, public_key_path="data/signing_public.pem") -> bool:
    try:
        public_key = _load_public_key(public_key_path)
        signature = base64.b64decode(signature_b64)
        public_key.verify(signature, data)
        return True
    except Exception:
        return False


# ----------------------------
# PDF REPORT BUILDER
# ----------------------------
def _write_pdf_report(
    output_path,
    case,
    alerts,
    evidence,
    notes,
    timeline,
    intelligence=None,
    narrative=None,
    clusters=None,
    evidence_hashes=None,
):
    doc = SimpleDocTemplate(
        output_path,
        pagesize=LETTER,
        rightMargin=36,
        leftMargin=36,
        topMargin=36,
        bottomMargin=36,
    )

    styles = getSampleStyleSheet()
    story = []

    def section(num, title):
        story.append(Spacer(1, 14))
        story.append(Paragraph(f"{num}. {title}", styles["Heading2"]))
        story.append(Spacer(1, 6))

    def p(text):
        return Paragraph(_safe_text(text).replace("\n", "<br/>"), styles["Normal"])

    def short(text, n=28):
        text = _safe_text(text)
        return text if len(text) <= n else text[:n] + "..."

    def para_cell(text):
        return Paragraph(_safe_text(text).replace("\n", "<br/>"), styles["Normal"])

    def rule_details_for_evidence(eid):
        severity = "LOW"
        confidence = "LOW"
        flags = set()
        rules = set()

        rank = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}

        for a in alerts or []:
            if (a.get("evidence_id") or "") != eid:
                continue

            try:
                notes_json = json.loads(a.get("notes") or "{}")
            except Exception:
                notes_json = {}

            sev = (a.get("severity") or notes_json.get("severity") or "LOW").upper()
            if rank.get(sev, 0) > rank.get(severity, 0):
                severity = sev

            confidence = (notes_json.get("confidence") or confidence or "LOW").upper()

            for c in notes_json.get("categories") or []:
                flags.add(str(c))

            for m in notes_json.get("matches") or []:
                flags.add(str(m))

            for r in notes_json.get("rule_hits") or []:
                if isinstance(r, dict):
                    if r.get("rule"):
                        rules.add(str(r.get("rule")))
                    if r.get("category"):
                        flags.add(str(r.get("category")))
                else:
                    rules.add(str(r))

        return severity, confidence, sorted(flags), sorted(rules)

    def risk_color(level):
        level = (level or "").upper()
        if level in ("CRITICAL", "HIGH"):
            return colors.lightcoral
        if level == "MEDIUM":
            return colors.lightyellow
        return colors.whitesmoke

    def map_rules_to_controls(rules):
        mapping = {
            "multiple_emails": ["AC-2", "IA-5"],
            "address_structured": ["IA-5", "SC-7"],
            "export": ["MP-7", "SC-7"],
            "export_control": ["MP-7", "SC-7"],
            "itar": ["MP-7", "SC-7"],
            "cui": ["AC-3", "SC-28"],
            "pii": ["IA-5", "AC-6"],
            "password": ["IA-5"],
            "token": ["IA-5"],
            "credential": ["IA-5"],
        }

        controls = set()
        for r in rules or []:
            key = str(r).lower()
            for token, mapped in mapping.items():
                if token in key:
                    controls.update(mapped)

        return sorted(controls)

    def fedramp_language(level):
        level = (level or "").upper()
        if level in ("CRITICAL", "HIGH"):
            return "This finding may represent a significant control weakness that could increase the likelihood of unauthorized access, data exposure, or mishandling of sensitive information."
        if level == "MEDIUM":
            return "This finding indicates a moderate control concern requiring review, validation, and appropriate remediation tracking."
        if level == "LOW":
            return "This finding represents limited observed risk but should remain documented for audit traceability and closure review."
        return "Risk impact could not be fully determined from the available evidence."

    # Dedup again defensively
    clean_evidence = []
    seen = set()
    for e in evidence or []:
        eid = e.get("evidence_id") or e.get("id")
        if eid and eid not in seen:
            seen.add(eid)
            clean_evidence.append(e)

    case_id = case.get("id") or case.get("case_id")
    title = case.get("title") or f"Case {case_id}"
    status = case.get("status") or "-"

    risk_score = (intelligence or {}).get("risk_score", "-")
    severity = (intelligence or {}).get("severity", "LOW")
    findings = (intelligence or {}).get("findings") or []
    recommendations = (intelligence or {}).get("recommendations") or []

    # ----------------------------
    # COVER / HEADER
    # ----------------------------
    story.append(Paragraph("Case Investigation Report", styles["Title"]))
    story.append(Spacer(1, 12))

    story.append(Paragraph("<b>Report Classification:</b> Internal Audit / Investigation Artifact", styles["Normal"]))
    story.append(Paragraph(f"<b>Case ID:</b> {_safe_text(case_id)}", styles["Normal"]))
    story.append(Paragraph(f"<b>Title:</b> {_safe_text(title)}", styles["Normal"]))
    story.append(Paragraph(f"<b>Status:</b> {_safe_text(status)}", styles["Normal"]))
    story.append(Paragraph(f"<b>Job ID:</b> {_safe_text(case.get('job_id'))}", styles["Normal"]))
    story.append(Paragraph(f"<b>Created:</b> {_fmt_ms(case.get('created_at_ms'))}", styles["Normal"]))
    story.append(Paragraph(f"<b>Generated UTC:</b> {datetime.datetime.utcnow().isoformat()}Z", styles["Normal"]))

    # ----------------------------
    # 1. EXECUTIVE SUMMARY
    # ----------------------------
    section("1", "Executive Summary")

    if intelligence and intelligence.get("summary"):
        story.append(p(intelligence.get("summary")))
    else:
        story.append(p("No automated case intelligence summary was generated."))

    # ----------------------------
    # 2. RISK ASSESSMENT
    # ----------------------------
    section("2", "Risk Assessment")

    risk_rows = [
        ["Risk Score", "Severity", "Assessment Basis"],
        [
            para_cell(f"{risk_score}/100"),
            para_cell(severity),
            para_cell("Derived from linked alerts, extracted evidence text, detection findings, and case intelligence rules."),
        ],
    ]

    risk_table = Table(risk_rows, repeatRows=1, colWidths=[90, 90, 330])
    risk_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ("BACKGROUND", (0, 1), (-1, 1), risk_color(severity)),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    story.append(risk_table)

    # ----------------------------
    # 3. FINDINGS
    # ----------------------------
    section("3", "Findings")

    if findings:
        for level, msg in findings:
            related_links = []
            detail_lines = []

            msg_lower = str(msg).lower()

            for e in clean_evidence:
                eid = e.get("evidence_id") or e.get("id")
                ev_sev, conf, flags, rules = rule_details_for_evidence(eid)

                if any(str(r).lower() in msg_lower for r in rules) or any(str(f).lower() in msg_lower for f in flags):
                    related_links.append(f"<a href='#{eid}'>{eid[:12]}...</a>")
                    detail_lines.append(
                        f"{eid[:12]}... | Severity={ev_sev} | Confidence={conf} | Rules={', '.join(rules) if rules else 'NONE'}"
                    )

            main_line = f"<b>[{_safe_text(level)}]</b> {_safe_text(msg)}"
            if related_links:
                main_line += f"<br/><b>Related Evidence:</b> {', '.join(related_links)}"

            story.append(Paragraph(main_line, styles["Normal"]))

            for line in detail_lines:
                story.append(Paragraph(f"<font size='8'>{_safe_text(line)}</font>", styles["Normal"]))

            story.append(Spacer(1, 6))
    else:
        story.append(p("No significant findings recorded."))

    # ----------------------------
    # 4. FINDING → EVIDENCE MAPPING
    # ----------------------------
    section("4", "Finding to Evidence Mapping")

    mapping_rows = [["Finding", "Evidence ID", "Severity", "Confidence", "Rules"]]

    for level, msg in findings:
        msg_lower = str(msg).lower()

        for e in clean_evidence:
            eid = e.get("evidence_id") or e.get("id")
            ev_sev, conf, flags, rules = rule_details_for_evidence(eid)

            matched = [
                r for r in rules
                if r and str(r).lower() in msg_lower
            ]

            if matched:
                mapping_rows.append([
                    para_cell(msg),
                    Paragraph(f"<a href='#{eid}'>{eid[:12]}...</a>", styles["Normal"]),
                    para_cell(ev_sev),
                    para_cell(conf),
                    para_cell("\n".join(matched)),
                ])

    if len(mapping_rows) > 1:
        table = Table(mapping_rows, repeatRows=1, colWidths=[190, 95, 70, 80, 145])
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        story.append(table)
    else:
        story.append(p("No direct evidence mappings identified."))

    # ----------------------------
    # 5. RECOMMENDATIONS
    # ----------------------------
    section("5", "Recommendations")

    if recommendations:
        for rec in recommendations:
            story.append(p(f"- {rec}"))
    else:
        story.append(p("No recommendations provided."))

    story.append(PageBreak())

    # ----------------------------
    # 6. INVESTIGATION NARRATIVE
    # ----------------------------
    section("6", "Investigation Narrative")

    if narrative:
        story.append(p(narrative))
    else:
        story.append(p("No investigation narrative generated."))

    story.append(PageBreak())

    # ----------------------------
    # 7. ALERT INVENTORY
    # ----------------------------
    section("7", "Alert Inventory")

    if alerts:
        rows = [["Alert ID", "Severity", "Category", "Evidence ID", "Message"]]

        for a in alerts:
            eid = a.get("evidence_id") or ""
            rows.append([
                para_cell(a.get("id")),
                para_cell(a.get("severity")),
                para_cell(a.get("category")),
                para_cell(short(eid, 18)),
                para_cell(short(a.get("message"), 80)),
            ])

        table = Table(rows, repeatRows=1, colWidths=[55, 70, 85, 115, 205])
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        story.append(table)
    else:
        story.append(p("No alerts associated with this case."))

    # ----------------------------
    # 8. EVIDENCE ANALYSIS / CLUSTERS
    # ----------------------------
    section("8", "Evidence Analysis / Clusters")

    if clusters:
        for cluster_name, items in clusters.items():
            story.append(Paragraph(f"<b>{_safe_text(cluster_name)}</b>", styles["Heading3"]))
            story.append(Paragraph(f"<i>Evidence count: {len(items)}</i>", styles["Normal"]))
            story.append(Spacer(1, 4))

            for item in items[:5]:
                e = item.get("evidence") or item.get("e") or {}
                score = item.get("score", 0)
                level = item.get("level", "LOW")
                eid = e.get("evidence_id") or e.get("id")
                name = e.get("suggested_name") or eid

                story.append(p(
                    f"- {name} | Evidence ID: {short(eid, 18)} | Risk: {level} ({score}/100)"
                ))

            story.append(Spacer(1, 8))
    else:
        story.append(p("Evidence clustering could not be performed or no clustered evidence was available."))

    story.append(PageBreak())

    # ----------------------------
    # 9. TOP RISK EVIDENCE
    # ----------------------------
    section("9", "Top Risk Evidence")

    ranked = []

    for e in clean_evidence:
        eid = e.get("evidence_id") or e.get("id")
        ev_sev, conf, flags, rules = rule_details_for_evidence(eid)

        sev_rank = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}.get(ev_sev, 0)
        ranked.append((sev_rank, ev_sev, conf, flags, rules, e))

    ranked.sort(reverse=True, key=lambda x: x[0])

    if ranked:
        rows = [["Evidence ID", "Name", "Severity", "Confidence", "Flags / Rules"]]
        row_styles = [
            ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]

        for idx, (_, ev_sev, conf, flags, rules, e) in enumerate(ranked[:5], start=1):
            eid = e.get("evidence_id") or e.get("id")
            rows.append([
                Paragraph(f"<a href='#{eid}'>{short(eid, 18)}</a>", styles["Normal"]),
                para_cell(e.get("suggested_name")),
                para_cell(ev_sev),
                para_cell(conf),
                para_cell("\n".join(flags or rules or ["NONE"])),
            ])
            row_styles.append(("BACKGROUND", (0, idx), (-1, idx), risk_color(ev_sev)))

        table = Table(rows, repeatRows=1, colWidths=[100, 180, 70, 80, 155])
        table.setStyle(TableStyle(row_styles))
        story.append(table)
    else:
        story.append(p("No evidence records available for ranking."))

    # ----------------------------
    # 10. EVIDENCE INVENTORY
    # ----------------------------
    section("10", "Evidence Inventory")

    if clean_evidence:
        rows = [["Evidence ID", "Name", "Type", "Size", "Severity", "Confidence", "Rule Hits"]]
        row_styles = [
            ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]

        for idx, e in enumerate(clean_evidence, start=1):
            eid = e.get("evidence_id") or e.get("id")
            ev_sev, conf, flags, rules = rule_details_for_evidence(eid)

            rows.append([
                Paragraph(f"<a name='{eid}'/>{short(eid, 20)}", styles["Normal"]),
                para_cell(e.get("suggested_name")),
                para_cell(e.get("content_type")),
                para_cell(e.get("size_bytes")),
                para_cell(ev_sev),
                para_cell(conf),
                para_cell("\n".join(rules) if rules else "NONE"),
            ])

            row_styles.append(("BACKGROUND", (0, idx), (-1, idx), risk_color(ev_sev)))

        table = Table(rows, repeatRows=1, colWidths=[100, 145, 105, 45, 60, 75, 110])
        table.setStyle(TableStyle(row_styles))
        story.append(table)
    else:
        story.append(p("No linked evidence."))

    story.append(PageBreak())

    # ----------------------------
    # 11. REGULATORY / CONTROL MAPPING
    # ----------------------------
    section("11", "Regulatory and NIST Control Mapping")

    reg_rows = [["Evidence ID", "Rules Triggered", "Potential Controls"]]

    for e in clean_evidence:
        eid = e.get("evidence_id") or e.get("id")
        ev_sev, conf, flags, rules = rule_details_for_evidence(eid)
        controls = map_rules_to_controls(rules + flags)

        if rules or flags:
            reg_rows.append([
                Paragraph(f"<a href='#{eid}'>{short(eid, 18)}</a>", styles["Normal"]),
                para_cell("\n".join(rules or flags)),
                para_cell("\n".join(controls) if controls else "General data handling / review required"),
            ])

    if len(reg_rows) > 1:
        table = Table(reg_rows, repeatRows=1, colWidths=[120, 220, 180])
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        story.append(table)
    else:
        story.append(p("No regulatory or NIST control mappings identified."))

    # ----------------------------
    # 12. ASSESSMENT FINDINGS
    # ----------------------------
    section("12", "Assessment Findings")

    if findings:
        for idx, (level, msg) in enumerate(findings, start=1):
            story.append(Paragraph(f"<b>Finding {idx}:</b> {_safe_text(msg)}", styles["Normal"]))
            story.append(p(f"Assessment: {fedramp_language(level)}"))

            controls = set()
            linked = []

            msg_lower = str(msg).lower()

            for e in clean_evidence:
                eid = e.get("evidence_id") or e.get("id")
                ev_sev, conf, flags, rules = rule_details_for_evidence(eid)

                if any(str(r).lower() in msg_lower for r in rules) or any(str(f).lower() in msg_lower for f in flags):
                    controls.update(map_rules_to_controls(rules + flags))
                    linked.append(f"<a href='#{eid}'>{eid[:12]}...</a> ({ev_sev}/{conf})")

            story.append(p(f"Impacted Controls: {', '.join(sorted(controls)) if controls else 'None identified'}"))

            if linked:
                story.append(Paragraph(f"Supporting Evidence: {', '.join(linked)}", styles["Normal"]))

            story.append(Spacer(1, 8))
    else:
        story.append(p("No SAR-style assessment findings were generated."))

    story.append(PageBreak())

    # ----------------------------
    # 13. CASE NOTES
    # ----------------------------
    section("13", "Case Notes")

    if notes:
        visible_notes = notes[-3:]

        story.append(p(f"Showing latest {len(visible_notes)} of {len(notes)} note(s). Full notes are retained in the bundle metadata."))

        for n in visible_notes:
            story.append(Paragraph(f"<b>{_fmt_ms(n.get('created_at_ms'))}</b>", styles["Normal"]))
            story.append(p(n.get("note")))
            story.append(Spacer(1, 8))
    else:
        story.append(p("No case notes."))

    # ----------------------------
    # 14. CHAIN OF CUSTODY TIMELINE
    # ----------------------------
    section("14", "Chain of Custody Timeline")

    if timeline:
        for t in timeline:
            story.append(Paragraph(
                f"<b>{_fmt_ms(t.get('created_at_ms'))}</b> - {_safe_text(t.get('event_type'))}",
                styles["Normal"],
            ))
            story.append(p(t.get("message")))
            story.append(Spacer(1, 6))
    else:
        story.append(p("No timeline events."))

    story.append(PageBreak())

    # ----------------------------
    # 15. INTEGRITY & VERIFICATION
    # ----------------------------
    section("15", "Integrity and Verification")

    story.append(p("This bundle includes cryptographic evidence hashes and an Ed25519 signed manifest. The PDF report is included in the signed export package."))

    if evidence_hashes:
        rows = [["Evidence ID", "SHA-256", "Size"]]

        for h in evidence_hashes:
            sha = h.get("sha256") or ""
            rows.append([
                para_cell(short(h.get("evidence_id"), 18)),
                para_cell(short(sha, 40)),
                para_cell(h.get("size_bytes")),
            ])

        table = Table(rows, repeatRows=1, colWidths=[120, 300, 70])
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        story.append(table)
    else:
        story.append(p("No evidence hashes available."))

    story.append(Spacer(1, 10))
    story.append(Paragraph("<b>Verification Instructions</b>", styles["Heading3"]))
    story.append(p("1. Compare each evidence SHA-256 against evidence_hashes.json."))
    story.append(p("2. Validate bundle_signature.json using signing_public.pem."))
    story.append(p("3. Confirm the case_manifest.json hash matches the signed manifest hash."))
    story.append(p("4. Review chain-of-custody timeline for export, note, and risk-score events."))

    doc.build(story)


# ----------------------------
# EXPORT BUNDLE
# ----------------------------
def export_case_bundle(
    ledger,
    case_id: int,
    intelligence=None,
    narrative=None,
    clusters=None,
    private_key_path="data/signing_private.pem",
    public_key_path="data/signing_public.pem",
):
    # ============================================================
    # EVIDENCE-FIRST EXPORT FIX
    # ============================================================

    case = {}
    alerts = []
    evidence = []
    notes = []
    timeline = []

    # ----------------------------------------
    # TRY REAL CASE FIRST
    # ----------------------------------------

    try:
        case_data = ledger.get_case_details(case_id)
 
        case = case_data.get("case") or {}
        alerts = case_data.get("alerts") or []
        evidence = case_data.get("evidence") or []

    except Exception as e:
        print("⚠️ get_case_details failed:", e)

    # ----------------------------------------
    # FALLBACK: SYNTHETIC / EVIDENCE CASE
    # ----------------------------------------

    if not evidence:

        print("🔥 FALLBACK TO EVIDENCE-CENTRIC EXPORT")

        try:
            with ledger._connect() as con:

                rows = con.execute("""
                    SELECT DISTINCT
                        json_extract(data_json, '$.evidence_id') as evidence_id
                   FROM evidence_events
                   WHERE
                        json_extract(data_json, '$.evidence_id') IS NOT NULL
                """).fetchall()

            for row in rows:

                eid = row[0]

                if not eid:
                    continue

                if str(eid).startswith(str(case_id)):

                    try:
                        ev = ledger.get_evidence_record(eid)

                        if ev:
                            evidence.append(ev)

                    except Exception as ex:
                        print("⚠️ evidence load failed:", ex)

        except Exception as e:
            print("⚠️ evidence fallback failed:", e)

    # ----------------------------------------
    # TIMELINE
    # ----------------------------------------

    try:
        timeline = ledger.get_case_timeline(case_id) or []
    except:
        timeline = []

    # ----------------------------------------
    # NOTES
    # ----------------------------------------

    try:
        notes = ledger.get_case_notes(case_id) or []
    except:
        notes = []

    # ----------------------------------------
    # ALERTS FROM EVIDENCE
    # ----------------------------------------

    if not alerts and evidence:

        try:

            all_alerts = ledger.get_alerts(limit=5000)

            evidence_ids = {
                e.get("evidence_id") or e.get("id")
                for e in evidence
            }

            alerts = [
                a for a in all_alerts
                if (a.get("evidence_id") in evidence_ids)
            ]

        except Exception as e:
            print("⚠️ alert fallback failed:", e)
 
    # ----------------------------
    # 🔥 GLOBAL DEDUP FIX
    # ----------------------------
    seen = set()
    clean_evidence = []

    for e in evidence:
        eid = e.get("evidence_id") or e.get("id")
        if not eid:
            continue

        if eid in seen:
            continue

        seen.add(eid)
        clean_evidence.append(e)

    with tempfile.TemporaryDirectory() as tmp:
        pdf_path = os.path.join(tmp, f"case_{case_id}.pdf")
        zip_path = os.path.join(tmp, f"case_{case_id}.zip")

        evidence_hashes = []
        evidence_files = []

        # ----------------------------
        # COLLECT EVIDENCE FILES + HASHES
        # ----------------------------
        if hasattr(ledger, "get_evidence_bytes"):
            for e in clean_evidence:
                eid = e.get("evidence_id") or e.get("id")

                try:
                    data = ledger.get_evidence_bytes(eid)
                except Exception:
                    data = None

                if not data:
                    continue

                sha256 = sha256_bytes(data)
                filename = f"evidence/{eid}.bin"

                ev_path = os.path.join(tmp, f"{eid}.bin")
                with open(ev_path, "wb") as f:
                    f.write(data)

                evidence_files.append((ev_path, filename))

                evidence_hashes.append({
                    "evidence_id": eid,
                    "filename": filename,
                    "sha256": sha256,
                    "size_bytes": len(data),
                })

        # ----------------------------
        # WRITE PDF (uses clean data)
        # ----------------------------
        _write_pdf_report(
            output_path=pdf_path,
            case=case,
            alerts=alerts,
            evidence=clean_evidence,  # ✅ FIXED
            notes=notes,
            timeline=timeline,
            intelligence=intelligence,
            narrative=narrative,
            clusters=clusters,
            evidence_hashes=evidence_hashes,
        )

        pdf_hash = sha256_file(pdf_path)

        # ----------------------------
        # BUILD MANIFEST (clean data)
        # ----------------------------
        manifest = {
            "case": case,
            "alerts": alerts,
            "evidence": clean_evidence,  # ✅ FIXED
            "notes": notes,
            "timeline": timeline,
            "intelligence": intelligence,
            "narrative": narrative,
            "clusters": _serialize_clusters(clusters),
            "evidence_hashes": evidence_hashes,
            "report": {
                "filename": f"case_{case_id}_report.pdf",
                "sha256": pdf_hash,
            },
            "signature": {
                "algorithm": "Ed25519",
                "signed_object": "case_manifest.json",
            },
            "exported_at": datetime.datetime.utcnow().isoformat() + "Z",
        }

        manifest_bytes = _canonical_json_bytes(manifest)
        manifest_sha256 = sha256_bytes(manifest_bytes)
        signature_b64 = _sign_bytes(manifest_bytes, private_key_path=private_key_path)

        signature_manifest = {
            "algorithm": "Ed25519",
            "signed_object": "case_manifest.json",
            "manifest_sha256": manifest_sha256,
            "signature_base64": signature_b64,
            "public_key_file": "signing_public.pem",
            "signed_at": datetime.datetime.utcnow().isoformat() + "Z",
        }

        # ----------------------------
        # WRITE ZIP
        # ----------------------------
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:

            # PDF
            z.write(pdf_path, arcname=f"case_{case_id}_report.pdf")

            # Evidence files
            for ev_path, filename in evidence_files:
                z.write(ev_path, arcname=filename)

            # Manifest
            manifest_file = os.path.join(tmp, "case_manifest.json")
            with open(manifest_file, "w", encoding="utf-8") as f:
                json.dump(manifest, f, indent=2, default=str)
            z.write(manifest_file, arcname="case_manifest.json")

            # Hashes
            hash_manifest_file = os.path.join(tmp, "evidence_hashes.json")
            with open(hash_manifest_file, "w", encoding="utf-8") as f:
                json.dump(evidence_hashes, f, indent=2, default=str)
            z.write(hash_manifest_file, arcname="evidence_hashes.json")

            # Signature
            sig_file = os.path.join(tmp, "bundle_signature.json")
            with open(sig_file, "w", encoding="utf-8") as f:
                json.dump(signature_manifest, f, indent=2, default=str)
            z.write(sig_file, arcname="bundle_signature.json")

            # Public key
            public_key_bytes = _get_public_key_bytes(public_key_path)
            public_key_file = os.path.join(tmp, "signing_public.pem")
            with open(public_key_file, "wb") as f:
                f.write(public_key_bytes)
            z.write(public_key_file, arcname="signing_public.pem")

        # ----------------------------
        # FINAL BUNDLE HASH (FIXED)
        # ----------------------------
        bundle_hash = sha256_file(zip_path)

        hash_file = os.path.join(tmp, "bundle_sha256.txt")
        with open(hash_file, "w", encoding="utf-8") as f:
            if isinstance(bundle_hash, bytes):
                bundle_hash = bundle_hash.hex()
            f.write(bundle_hash)

        with zipfile.ZipFile(zip_path, "a", zipfile.ZIP_DEFLATED) as z:
            z.write(hash_file, arcname="bundle_sha256.txt")

        with open(zip_path, "rb") as f:
            return f.read()



# ----------------------------
# VERIFY BUNDLE
# ----------------------------
def verify_case_bundle(bundle_path):
    """
    Verifies:
    1. Manifest signature
    2. Manifest SHA-256
    3. Evidence file hashes
    4. PDF report hash
    5. Bundle hash as stored before bundle_sha256.txt was appended cannot be strictly rechecked
       because the file was appended after hashing. Use signature + file hashes as authority.
    """
    with zipfile.ZipFile(bundle_path, "r") as z:
        names = set(z.namelist())

        required = {
            "case_manifest.json",
            "bundle_signature.json",
            "signing_public.pem",
            "evidence_hashes.json",
        }

        missing = required - names
        if missing:
            return False, f"Missing required files: {sorted(missing)}"

        manifest = json.loads(z.read("case_manifest.json").decode("utf-8"))
        signature_manifest = json.loads(z.read("bundle_signature.json").decode("utf-8"))
        public_key_bytes = z.read("signing_public.pem")

        manifest_bytes = _canonical_json_bytes(manifest)
        actual_manifest_sha256 = sha256_bytes(manifest_bytes)
        expected_manifest_sha256 = signature_manifest.get("manifest_sha256")

        if actual_manifest_sha256 != expected_manifest_sha256:
            return False, "Manifest SHA-256 mismatch"

        if not verify_signature_bytes(
            manifest_bytes,
            signature_manifest.get("signature_base64", ""),
            public_key_bytes,
        ):
            return False, "Manifest signature invalid"

        # Verify evidence hashes
        evidence_hashes = json.loads(z.read("evidence_hashes.json").decode("utf-8"))

        for item in evidence_hashes:
            filename = item.get("filename")
            expected_sha = item.get("sha256")

            if not filename or filename not in names:
                return False, f"Missing evidence file: {filename}"

            actual_sha = sha256_bytes(z.read(filename))

            if actual_sha != expected_sha:
                return False, f"Evidence hash mismatch: {filename}"

        # Verify report hash
        report = manifest.get("report") or {}
        report_filename = report.get("filename")
        report_sha = report.get("sha256")

        if report_filename:
            if report_filename not in names:
                return False, f"Missing report file: {report_filename}"

            actual_report_sha = sha256_bytes(z.read(report_filename))

            if actual_report_sha != report_sha:
                return False, "PDF report hash mismatch"

        return True, "Bundle verified"