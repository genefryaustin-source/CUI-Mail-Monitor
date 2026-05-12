import streamlit as st

from pathlib import Path
from veridion_theme import apply_theme
apply_theme()
with st.sidebar:
    st.markdown('<h1 class="veridion-sidebar-title">Veridion Pro</h1>', unsafe_allow_html=True)

def render_markdown_help(path):
    p = Path(path)
    if p.exists():
        st.markdown(p.read_text(encoding="utf-8"))
    else:
        st.warning(f"Help file not found: {path}")
HELP_SECTIONS = {
    "Getting Started": {
        "audience": "All Users",
        "summary": "Basic orientation for first-time users.",
        "steps": [
            "Confirm workers are running if background ingestion is needed.",
            "Open Scan, Alert Center, Evidence Viewer, or Cases from the sidebar.",
            "Start with Alert Center when reviewing new detections.",
            "Use Cases for investigation, summary, narrative, export, and verification workflows.",
        ],
    },
    "Analyst Workflow": {
        "audience": "Analyst",
        "summary": "Daily investigation workflow for alerts and evidence.",
        "steps": [
            "Open Alert Center.",
            "Select an alert.",
            "Open linked evidence and review extracted content.",
            "Create or open the related case.",
            "Generate Case Summary.",
            "Review risk score, findings, recommendations, and linked evidence.",
            "Generate Investigation Narrative.",
            "Export narrative to notes if it is accurate.",
        ],
    },
    "Supervisor Workflow": {
        "audience": "Supervisor",
        "summary": "Review and approval workflow.",
        "steps": [
            "Open Cases.",
            "Review case risk level and case status.",
            "Review findings and recommendations.",
            "Review chain-of-custody timeline.",
            "Confirm narrative aligns with risk score.",
            "Approve escalation, closure, or additional review.",
            "Export the full evidence bundle when ready.",
        ],
    },
    "Auditor Workflow": {
        "audience": "Auditor",
        "summary": "Evidence verification and audit review workflow.",
        "steps": [
            "Open the exported case bundle.",
            "Review case report PDF.",
            "Review evidence_hashes.json.",
            "Verify evidence SHA-256 values.",
            "Verify case_manifest.json.",
            "Verify bundle_signature.json using signing_public.pem.",
            "Review chain-of-custody timeline.",
            "Confirm findings map back to evidence records.",
        ],
    },
    "Case Summary": {
        "audience": "Analyst / Supervisor",
        "summary": "Generates deterministic case intelligence.",
        "steps": [
            "Open Cases.",
            "Select the case.",
            "Click Generate Case Summary.",
            "Review risk score.",
            "Review findings.",
            "Review recommendations.",
            "Export summary to notes if accurate.",
        ],
    },
    "Investigation Narrative": {
        "audience": "Analyst / Supervisor",
        "summary": "AI-generated narrative constrained by system risk.",
        "steps": [
            "Generate Case Summary first.",
            "Confirm risk score and severity are correct.",
            "Confirm clustered evidence exists.",
            "Click Generate Narrative.",
            "Review narrative for consistency.",
            "Export narrative to notes if approved.",
        ],
    },
    "Evidence Bundle Export": {
        "audience": "Supervisor / Auditor",
        "summary": "Creates the PDF report, manifest, hashes, signature, and evidence bundle.",
        "steps": [
            "Open case dashboard.",
            "Generate summary and narrative first.",
            "Click Export Full Case Report.",
            "Download the case bundle.",
            "Use Verify Bundle to validate integrity.",
        ],
    },
    "Common Issues": {
        "audience": "All Users",
        "summary": "Troubleshooting guide.",
        "steps": [
            "No clustered evidence: check text extraction for linked evidence.",
            "Narrative says LOW but risk is MEDIUM/HIGH: regenerate narrative after case summary.",
            "PDF missing evidence hashes: confirm get_evidence_bytes works.",
            "Duplicate evidence rows: confirm clean_evidence dedup is active.",
            "Bundle export fails: check binary writes use wb and JSON writes use w.",
        ],
    },
}


def _render_steps(steps):
    for idx, step in enumerate(steps, start=1):
        st.markdown(f"**{idx}.** {step}")


def render_help_page(storage=None):
    st.title("📘 Help Center")
    st.caption("Interactive operating guide for analysts, supervisors, auditors, and administrators.")

    role = st.selectbox(
        "Select your role",
        ["All", "Analyst", "Supervisor", "Auditor", "Administrator"],
    )

    search = st.text_input("Search help topics", placeholder="Search: narrative, export, risk, evidence, bundle...")

    st.divider()

    for title, section in HELP_SECTIONS.items():
        audience = section["audience"]

        if role != "All" and role not in audience and audience != "All Users":
            continue

        if search:
            haystack = f"{title} {audience} {section['summary']} {' '.join(section['steps'])}".lower()
            if search.lower() not in haystack:
                continue

        with st.expander(f"{title} — {audience}", expanded=False):
            st.markdown(f"**Purpose:** {section['summary']}")
            st.markdown("### Steps")
            _render_steps(section["steps"])

    st.divider()

    st.subheader("🚦 Production Readiness Checklist")

    checklist = {
        "Evidence ingestion configured": False,
        "Text extraction verified": False,
        "Alert creation verified": False,
        "Case summary generation verified": False,
        "Narrative generation verified": False,
        "PDF export verified": False,
        "Bundle verification verified": False,
        "Chain-of-custody timeline verified": False,
    }

    for item in checklist:
        st.checkbox(item, key=f"help_check_{item}")

    st.info(
        "Tip: Before production use, run one full test case from ingestion through bundle verification."
    )