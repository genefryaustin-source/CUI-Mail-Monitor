import streamlit as st
import datetime
from collections import defaultdict
import re
import os
from core.services.case_export_service import export_case_bundle
from core.ui.help_page import render_markdown_help
from core.utils.text_extraction import extract_text_from_bytes
# ----------------------------
# Visual / intelligence mappings
# ----------------------------
EVENT_ICONS = {
    "CASE_CREATED": "🟢",
    "ALERT_LINKED": "🚨",
    "EVIDENCE_LINKED": "📄",
    "NOTE_ADDED": "📝",
    "STATUS_CHANGE": "🔄",
    "CASE_SUMMARY_GENERATED": "🧠",
    "RISK_SCORE_UPDATED": "📊",
    "RECOMMENDATION_ADDED": "✅",
}

HIGHLIGHT_RULES = {
    "CRITICAL": [
        "password",
        "ssn",
        "social security",
        "credit card",
        "private key",
        "secret key",
        "api key",
        "token",
        "credential",
        "credentials",
        "classified",
        "cui",
    ],
    "HIGH": [
        "login",
        "failed",
        "unauthorized",
        "error",
        "alert",
        "blocked",
        "malware",
        "phishing",
        "exfiltration",
        "suspicious",
        "breach",
        "incident",
    ],
    "MEDIUM": [
        "user",
        "account",
        "access",
        "request",
        "attachment",
        "external",
        "policy",
        "review",
        "approval",
    ],
}

RISK_WEIGHTS = {
    "CRITICAL": 35,
    "HIGH": 20,
    "MEDIUM": 10,
    "LOW": 3,
}


# ----------------------------
# Helper functions
# ----------------------------
def _format_ts(ms):
    if not ms:
        return "-"
    try:
        return datetime.datetime.fromtimestamp(int(ms) / 1000)
    except Exception:
        return "-"


def highlight_text(text: str):
    """
    Rules-based evidence signal detector.
    Returns list of tuples: (level, matched_word)
    """
    if not text:
        return []

    highlights = []

    for level, words in HIGHLIGHT_RULES.items():
        for word in words:
            matches = re.findall(rf"\b{re.escape(word)}\b", text, re.IGNORECASE)
            for match in matches:
                highlights.append((level, match))

    return highlights



def detect_sensitive(text: str):
    patterns = [
        ("CUI", r"\bCUI\b", "#ff4d4d"),
        ("SSN", r"\b\d{3}-\d{2}-\d{4}\b", "#ff9900"),
        ("EMAIL", r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", "#3399ff"),
        ("PASSWORD", r"\b(password|secret|token|api key)\b", "#cc00ff"),
    ]

    matches = []

    for label, pattern, color in patterns:
        for m in re.finditer(pattern, text, re.IGNORECASE):
            matches.append({
                "label": label,
                "value": m.group(),
                "start": m.start(),
                "end": m.end(),
                "color": color
            })

    return matches

from pypdf import PdfReader
import io

def extract_text_from_bytes(data: bytes) -> str:
    try:
        reader = PdfReader(io.BytesIO(data))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception:
        return ""

def extract_text_from_bytes(data: bytes) -> str:
    try:
        return data.decode("utf-8", errors="ignore")
    except:
        return ""



def highlight_sensitive_inline(text: str):
    patterns = [
        ("CUI", r"\bCUI\b", "#ff4d4d"),
        ("SSN", r"\b\d{3}-\d{2}-\d{4}\b", "#ff9900"),
        ("EMAIL", r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", "#3399ff"),
        ("PASSWORD", r"\b(password|secret|token|api key)\b", "#cc00ff"),
    ]

    highlighted_text = text

    for label, pattern, color in patterns:
        def repl(match):
            return f"<span style='background-color:{color}; color:white; padding:2px 4px; border-radius:4px;'>[{label}] {match.group()}</span>"

        highlighted_text = re.sub(pattern, repl, highlighted_text, flags=re.IGNORECASE)

    return highlighted_text

def render_highlighted_text(text, matches, filter_type=None):
    output = ""
    last_idx = 0

    for m in sorted(matches, key=lambda x: x["start"]):
        if filter_type and m["label"] != filter_type:
            continue

        start, end = m["start"], m["end"]

        output += text[last_idx:start]

        output += f"<span style='background:{m['color']}; color:white; padding:2px 4px; border-radius:4px;'>[{m['label']}] {text[start:end]}</span>"

        last_idx = end

    output += text[last_idx:]

    return output

def score_evidence(text, alerts=None):
    matches = detect_sensitive(text)

    score = 0

    for m in matches:
        if m["label"] == "SSN":
            score += 40
        elif m["label"] == "CUI":
            score += 25
        elif m["label"] == "PASSWORD":
            score += 35
        elif m["label"] == "EMAIL":
            score += 5

    # Optional: boost based on alert severity
    if alerts:
        for a in alerts:
            sev = (a.get("severity") or "").upper()
            if sev == "CRITICAL":
                score += 30
            elif sev == "HIGH":
                score += 20

    score = min(score, 100)

    if score >= 75:
        level = "CRITICAL"
    elif score >= 50:
        level = "HIGH"
    elif score >= 25:
        level = "MEDIUM"
    else:
        level = "LOW"

    return score, level, matches


def build_simple_clusters(evidence):
    clusters = {}

    for e in evidence:
        text = (e.get("text") or "").lower()

        if not text.strip():
            key = "Unclassified Evidence"

        elif "cui" in text:
            key = "CUI Data Handling"

        elif "export" in text or "itar" in text:
            key = "Export-Controlled Data"

        elif "password" in text or "token" in text:
            key = "Credential Exposure"

        elif "@" in text:
            key = "Email Communication"

        elif "address" in text:
            key = "PII / Address Data"

        else:
            key = "General Evidence"

        clusters.setdefault(key, []).append(e)

    return clusters


def cluster_evidence(ranked_evidence):
    clusters = {}

    for item in ranked_evidence:
        e = item.get("evidence")

        # 🔥 DEFENSIVE FIX
        if not isinstance(e, dict):
            print("⚠️ Skipping invalid evidence (not dict):", e)
            continue

        matches = e.get("matches") or []

        labels = sorted(set(
            m.get("label") for m in matches if isinstance(m, dict) and m.get("label")
        ))

        if not labels:
            cluster_key = "General / Low Signal"
        else:
            cluster_key = " + ".join(labels)

        clusters.setdefault(cluster_key, []).append(item)

    return clusters

def generate_cluster_name(items):
    texts = []

    for item in items[:3]:  # sample top 3 files only
        txt = item.get("text") or ""
        if txt:
            texts.append(txt[:500])

    combined = "\n\n".join(texts)

    # 🔥 Fallback if no LLM
    if not combined.strip():
        return "General Evidence"

    try:

        if not os.getenv("OPENAI_API_KEY"):
            return heuristic_cluster_name(combined)

        from openai import OpenAI
        print("API KEY PRESENT:", bool(os.getenv("OPENAI_API_KEY")))
        client = OpenAI()

        prompt = f"""
Summarize the theme of this evidence into a SHORT title (max 5 words).

Examples:
- Payroll Data Leak
- Credential Exposure
- Internal Email Discussion

Evidence:
{combined}
"""

        response = client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
        )

        name = response.choices[0].message.content.strip()

        return name[:60]

    except Exception:
        return heuristic_cluster_name(combined)

def heuristic_cluster_name(text):
    text = text.lower()

    if "password" in text or "token" in text:
        return "Credential Exposure"
    if "ssn" in text:
        return "SSN Exposure"
    if "cui" in text:
        return "CUI Data Handling"
    if "@" in text:
        return "Email Communication"

    return "General Evidence"

def generate_investigation_narrative(
    clusters,
    alerts=None,
    risk_score=None,
    risk_level=None,
    findings=None,
    recommendations=None
):

    cluster_summaries = []

    for name, items in clusters.items():
        texts = []

        for item in items:
            txt = item.get("text") or ""
            if txt.strip():
                texts.append(txt[:500])
            if len(texts) >= 2:  # keep limit
                break

        combined = "\n\n".join(texts)

        cluster_summaries.append({
            "name": name,
            "text": combined
        })

    # Build input for AI
    combined_input = ""
    for c in cluster_summaries:
        combined_input += f"\n\nCluster: {c['name']}\n{c['text']}"

    if not combined_input.strip():
        return heuristic_narrative(cluster_summaries, alerts)

    # 🔥 Fallback (no LLM)
    import os
    if not os.getenv("OPENAI_API_KEY"):
        return heuristic_narrative(cluster_summaries, alerts)

    try:
        from openai import OpenAI
        client = OpenAI()
        risk_guidance = {
            "LOW": "Emphasize minimal risk and monitoring.",
            "MEDIUM": "Highlight moderate concern and need for review.",
            "HIGH": "Emphasize urgency and potential exposure.",
        }
        findings_text = "\n".join(f"- {f[1] if isinstance(f, tuple) else f}" for f in (findings or []))
        recommendations_text = "\n".join(f"- {r}" for r in (recommendations or []))
        prompt = f"""
        You are a cybersecurity and compliance analyst.

        The system has already determined:

        Risk Score: {risk_score}/100
        Risk Level: {risk_level}

        These values are authoritative and must not be changed.

        Key Findings:
        {findings_text if findings_text else "- No significant findings recorded"}

        Recommended Actions:
        {recommendations_text if recommendations_text else "- No recommendations provided"}

        Your task is to write a concise investigation narrative that:

        - Explains WHY the assigned risk level is appropriate
        - References the findings above
        - Identifies sensitive data types involved (CUI, PII, etc.)
        - Summarizes what occurred
        - Reinforces the recommended actions

        Keep it professional, specific, and under 200 words.

        Investigation Data:
        {combined_input}
        """

        response = client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
        )

        return response.choices[0].message.content.strip()


    except Exception as e:

        print("OPENAI NARRATIVE ERROR:", e)

        return heuristic_narrative(cluster_summaries, alerts)

def heuristic_narrative(cluster_summaries, alerts):
    lines = []

    lines.append("Automated investigation summary:\n")

    for c in cluster_summaries:
        lines.append(f"- Evidence related to {c['name']} detected.")

    if alerts:
        severities = set(a.get("severity") for a in alerts)
        lines.append(f"- Alerts indicate severity levels: {', '.join(severities)}.")

    lines.append("\nRecommended Actions:")
    lines.append("- Review high-risk evidence immediately")
    lines.append("- Validate data exposure scope")
    lines.append("- Escalate if sensitive data confirmed")

    return "\n".join(lines)


def generate_summary(text: str):
    """
    Per-evidence placeholder summary.
    Replace later with OpenAI / local model if desired.
    """
    if not text:
        return "Summary:\nNo text available."

    lines = [line.strip() for line in text.split("\n") if line.strip()]
    sample = " ".join(lines[:5])[:500]

    return f"Summary:\n{sample}..."


def aggregate_case_text(evidence, ledger, per_evidence_limit=3000, max_items=10):
    """
    Pulls text from linked evidence records for case-level intelligence.
    """
    texts = []

    if not hasattr(ledger, "get_evidence_bytes"):
        return ""

    for e in evidence[:max_items]:

        # ✅ FIX: correct ID field
        eid = e.get("evidence_id") or e.get("id")
        if not eid:
            continue

        try:
            data = ledger.get_evidence_bytes(eid)
            if not data:
                continue

            # ✅ Extract ONCE (correctly)
            text = extract_text_from_bytes(
                data,
                filename=e.get("suggested_name")
            )

            # ✅ Cache for downstream AI use
            e["text"] = text

            if text.strip():
                texts.append(
                    f"--- Evidence {eid} ---\n{text[:per_evidence_limit]}"
                )

        except Exception as ex:
            print("AGGREGATION ERROR:", ex)
            continue

    return "\n\n".join(texts)


def analyze_case_intelligence(text: str, alerts=None, evidence=None):
    """
    Case-level rules engine:
    - Summary
    - Findings
    - Recommendations
    - Risk score
    - Case severity
    """


    alerts = alerts or []
    evidence = evidence or []

    text_lower = (text or "").lower()

    findings = []
    recommendations = []

    # ----------------------------
    # Evidence-content findings
    # ----------------------------
    if any(term in text_lower for term in ["password", "credential", "credentials", "private key", "secret key", "api key", "token"]):
        findings.append(("CRITICAL", "Potential credential or secret exposure detected."))
        recommendations.append("Immediately rotate any exposed credentials, keys, tokens, or passwords.")

    if any(term in text_lower for term in ["ssn", "social security", "credit card"]):
        findings.append(("CRITICAL", "Potential regulated sensitive data exposure detected."))
        recommendations.append("Escalate to compliance/privacy owner and validate data handling obligations.")

    if "failed" in text_lower and "login" in text_lower:
        findings.append(("HIGH", "Repeated failed login or authentication pattern detected."))
        recommendations.append("Review authentication logs and confirm whether MFA, lockout, or conditional access controls triggered.")

    if "unauthorized" in text_lower:
        findings.append(("HIGH", "Unauthorized access language detected."))
        recommendations.append("Validate user identity, access grants, and recent permission changes.")

    if any(term in text_lower for term in ["phishing", "malware", "suspicious", "breach", "incident"]):
        findings.append(("HIGH", "Security incident indicators detected in evidence text."))
        recommendations.append("Preserve evidence, review related messages, and initiate incident response triage.")

    if "attachment" in text_lower or "external" in text_lower:
        findings.append(("MEDIUM", "Attachment or external-origin context detected."))
        recommendations.append("Review attachment metadata, sender reputation, and custody chain.")

    if "account" in text_lower or "access" in text_lower:
        findings.append(("MEDIUM", "Account or access-related activity detected."))
        recommendations.append("Review affected user accounts and verify least-privilege alignment.")

    # ----------------------------
    # Alert severity findings
    # ----------------------------
    alert_severities = [(a.get("severity") or "").upper() for a in alerts]

    critical_alerts = sum(1 for s in alert_severities if s == "CRITICAL")
    high_alerts = sum(1 for s in alert_severities if s == "HIGH")
    medium_alerts = sum(1 for s in alert_severities if s == "MEDIUM")

    if critical_alerts:
        findings.append(("CRITICAL", f"{critical_alerts} CRITICAL linked alert(s) found."))
        recommendations.append("Open formal investigation workflow and assign an owner immediately.")

    if high_alerts:
        findings.append(("HIGH", f"{high_alerts} HIGH linked alert(s) found."))
        recommendations.append("Prioritize review of high-severity alerts and linked evidence.")

    if medium_alerts:
        findings.append(("MEDIUM", f"{medium_alerts} MEDIUM linked alert(s) found."))

    # ----------------------------
    # Evidence volume context
    # ----------------------------
    evidence_count = len(evidence)
    if evidence_count >= 5:
        findings.append(("MEDIUM", f"{evidence_count} linked evidence records indicate broader case scope."))
        recommendations.append("Review evidence chronologically and validate whether related events should be merged.")

    # ----------------------------
    # Risk scoring
    # ----------------------------
    score = 0
    for level, _ in findings:
        score += RISK_WEIGHTS.get(level, 0)

    score = min(score, 100)

    if score >= 75:
        severity = "CRITICAL"
    elif score >= 50:
        severity = "HIGH"
    elif score >= 25:
        severity = "MEDIUM"
    else:
        severity = "LOW"

    # ----------------------------
    # Summary
    # ----------------------------
    if text:
        compact = " ".join([line.strip() for line in text.splitlines() if line.strip()])
        summary_body = compact[:900]
    else:
        summary_body = "No text-based evidence was available for automated summarization."

    summary = (
        "Case Summary:\n"
        f"- Linked alerts: {len(alerts)}\n"
        f"- Linked evidence records: {evidence_count}\n"
        f"- Risk score: {score}/100\n"
        f"- Suggested severity: {severity}\n\n"
        f"Evidence narrative:\n{summary_body}..."
    )

    # ----------------------------
    # Deduplicate recommendations
    # ----------------------------
    deduped_recommendations = []
    seen = set()
    for rec in recommendations:
        if rec not in seen:
            deduped_recommendations.append(rec)
            seen.add(rec)

    if not deduped_recommendations:
        deduped_recommendations.append("Continue manual review and validate linked evidence before closure.")

    return {
        "summary": summary,
        "findings": findings,
        "recommendations": deduped_recommendations,
        "risk_score": score,
        "severity": severity,
    }


def _risk_badge(score, severity):
    if severity == "CRITICAL":
        st.error(f"Risk Score: {score}/100 — {severity}")
    elif severity == "HIGH":
        st.warning(f"Risk Score: {score}/100 — {severity}")
    elif severity == "MEDIUM":
        st.info(f"Risk Score: {score}/100 — {severity}")
    else:
        st.success(f"Risk Score: {score}/100 — {severity}")



SENSITIVE_PATTERNS = [
    ("CUI", r"\bCUI\b"),
    ("SSN", r"\b\d{3}-\d{2}-\d{4}\b"),
    ("EMAIL", r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
]

def highlight_sensitive(text: str):
    highlights = []

    for label, pattern in SENSITIVE_PATTERNS:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            highlights.append({
                "label": label,
                "value": match.group(),
                "start": match.start(),
                "end": match.end()
            })

    return highlights



# -------------------
# Cases renderer
# -------------------


def render_case_dashboard(storage):
    ledger = storage.ledger

    st.title("📁 Case Dashboard")

    # ----------------------------
    # CASE LIST
    # ----------------------------
    cases = ledger.list_cases()
    st.write(cases)
    if not cases:
        st.info("No cases found.")
        return

    st.subheader("📋 Cases")

    for case in cases:

        highlight_id = st.session_state.get("highlight_case_id")
        is_highlighted = case.get("id") == highlight_id
        bg = "#1e3a5f" if is_highlighted else "transparent"
        border = "2px solid #4CAF50" if is_highlighted else "1px solid #ddd"

        st.markdown(f"""
        <div style="
            background-color: {bg};
            border: {border};
            padding: 10px;
            border-radius: 8px;
            margin-bottom: 6px;
        ">
        """, unsafe_allow_html=True)
        col1, col2, col3, col4, col5 = st.columns([1, 3, 2, 2, 2])

        case_id = case.get("id")

        if not case_id:
            continue  # skip broken rows

        col1.write(f"#{case_id}")
        col2.write(case.get("title"))
        col3.write(case.get("status"))
        col4.write(_format_ts(case.get("created_at_ms")))
        col5.write(case.get("job_id") or "-")
        st.markdown("</div>", unsafe_allow_html=True)
        if st.button("Open", key=f"open_case_{case_id}"):
            st.session_state["selected_case_id"] = case_id
            st.rerun()

    # ----------------------------
    # CASE DETAILS
    # ----------------------------
    case_id = st.session_state.get("selected_case_id")

    if not case_id:
        st.info("Select a case above to view details.")
        return

    st.divider()
    st.subheader(f"🔍 Case Details #{case_id}")

    data = ledger.get_case_details(case_id)

    case = data.get("case") or {}
    alerts = data.get("alerts") or []
    evidence = data.get("evidence") or []

    if not case:
        st.error("Selected case could not be loaded.")
        return

    # ----------------------------
    # STATUS CONTROL
    # ----------------------------
    status_options = ["OPEN", "INVESTIGATING", "RESOLVED", "CLOSED"]
    current_status = case.get("status", "OPEN")

    try:
        current_index = status_options.index(current_status)
    except ValueError:
        current_index = 0

    new_status = st.selectbox(
        "Update Status",
        status_options,
        index=current_index,
        key=f"status_select_{case_id}",
    )

    if st.button("Update Status", key=f"update_status_{case_id}"):
        ledger.update_case_status(case_id, new_status)
        st.success("Case updated")
        st.rerun()

    st.subheader("👤 Case Assignment")

    current_owner = case.get("assigned_to")

    col1, col2 = st.columns([3, 2])

    with col1:
        new_owner = st.text_input(
            "Assign To",
            value=current_owner or "",
            key=f"assign_input_{case_id}"
        )

    with col2:
        if st.button("Assign / Update Owner", key=f"assign_btn_{case_id}"):
            ledger.assign_case(
                case_id=case_id,
                assigned_to=new_owner,
                assigned_by="analyst"  # later replace with logged-in user
            )

            if hasattr(ledger, "add_case_event"):
                ledger.add_case_event(
                    case_id,
                    "STATUS_CHANGE",
                    f"Assigned to {new_owner}"
                )

            st.success(f"Case assigned to {new_owner}")
            st.rerun()

    if current_owner:
        st.info(f"Current Owner: {current_owner}")

    # ----------------------------
    # CASE INTELLIGENCE
    # ----------------------------
    st.subheader("🧠 Case Intelligence")
    with st.expander("📄 Case Dashboard Full Guide"):
        render_markdown_help("docs/help/case_dashboard.md")
    summary_key = f"case_summary_{case_id}"

    ci1, ci2, ci3 = st.columns([2, 2, 2])

    with ci1:
        if st.button("Generate Case Summary", key=f"gen_summary_{case_id}"):
            combined_text = aggregate_case_text(evidence, ledger)

            result = analyze_case_intelligence(
                text=combined_text,
                alerts=alerts,
                evidence=evidence,
            )

            st.session_state[summary_key] = result

            if hasattr(ledger, "add_case_event"):
                ledger.add_case_event(
                    case_id,
                    "CASE_SUMMARY_GENERATED",
                    f"Case summary generated. Risk={result['risk_score']}/100 Severity={result['severity']}",
                )
                ledger.add_case_event(
                    case_id,
                    "RISK_SCORE_UPDATED",
                    f"Risk score calculated as {result['risk_score']}/100 ({result['severity']})",
                )

            st.rerun()

    with ci2:
        if summary_key in st.session_state:
            if st.button("Export Summary to Notes", key=f"export_summary_note_{case_id}"):
                result = st.session_state[summary_key]
                note_text = (
                    f"{result['summary']}\n\n"
                    f"Findings:\n"
                    + "\n".join([f"- [{level}] {msg}" for level, msg in result["findings"]])
                    + "\n\nRecommendations:\n"
                    + "\n".join([f"- {rec}" for rec in result["recommendations"]])
                )

                ledger.add_case_note(case_id, note_text)

                if hasattr(ledger, "add_case_event"):
                    ledger.add_case_event(case_id, "NOTE_ADDED", "Case intelligence summary exported to notes.")

                st.success("Summary exported to case notes")
                st.rerun()

    with ci3:
        if st.button("🧠 Generate Narrative", key=f"gen_narrative_{case_id}"):

            clusters = st.session_state.get("clusters")

            if not clusters:
                st.warning("No clustered evidence available yet")
            else:
                # 🔥 ADD THIS
                result = st.session_state.get(summary_key)

                risk_score = result.get("risk_score") if result else None
                risk_level = result.get("severity") if result else None
                findings = result.get("findings") if result else []
                recommendations = result.get("recommendations") if result else []

                # 🔥 UPDATED CALL
                narrative = generate_investigation_narrative(
                    clusters,
                    alerts,
                    risk_score=risk_score,
                    risk_level=risk_level,
                    findings=findings,
                    recommendations=recommendations,
                )

                st.session_state[f"case_narrative_{case_id}"] = narrative

                if hasattr(ledger, "add_case_event"):
                    ledger.add_case_event(
                        case_id,
                        "CASE_NARRATIVE_GENERATED",
                        "Investigation narrative generated from clustered evidence"
                    )

                st.rerun()

    if summary_key in st.session_state:

        narrative_key = f"case_narrative_{case_id}"

        if narrative_key in st.session_state:

            st.subheader("📘 Investigation Narrative")

            st.write(st.session_state[narrative_key])

            if st.button("Export Narrative to Notes", key=f"export_narrative_{case_id}"):

                ledger.add_case_note(case_id, st.session_state[narrative_key])

                if hasattr(ledger, "add_case_event"):
                    ledger.add_case_event(
                        case_id,
                        "NOTE_ADDED",
                        "Investigation narrative exported to notes"
                    )

                st.success("Narrative saved to notes")
                st.rerun()

        result = st.session_state[summary_key]

        _risk_badge(result.get("risk_score", 0), result.get("severity", "LOW"))

        st.success("AI Case Summary")
        st.write(result.get("summary", ""))

        st.subheader("🔎 Findings")

        findings = result.get("findings") or []
        if findings:
            for level, msg in findings:
                if level == "CRITICAL":
                    st.error(f"{level}: {msg}")
                elif level == "HIGH":
                    st.warning(f"{level}: {msg}")
                elif level == "MEDIUM":
                    st.info(f"{level}: {msg}")
                else:
                    st.write(f"{level}: {msg}")
        else:
            st.info("No significant findings detected.")

        st.subheader("✅ Recommendations")

        recommendations = result.get("recommendations") or []
        for rec in recommendations:
            st.write(f"- {rec}")

        if narrative_key in st.session_state:
            # ----------------------------
            # 📦 EXPORT CASE REPORT
            # ----------------------------
            st.subheader("📦 Export Case")

            if st.button("Export Full Case Report (PDF + Bundle)", key=f"export_case_{case_id}"):

                try:
                    # ----------------------------
                    # 🔥 STEP 1 — LOAD CASE DATA
                    # ----------------------------
                    case_data = ledger.get_case_details(case_id)
                    evidence = case_data.get("evidence") or []

                    print("EVIDENCE COUNT:", len(evidence))

                    # ----------------------------
                    # 🔥 STEP 2 — EXTRACT TEXT
                    # ----------------------------
                    for e in evidence:
                        eid = e.get("evidence_id") or e.get("id")

                        try:
                            data = ledger.get_evidence_bytes(eid)

                            text = extract_text_from_bytes(
                                data,
                                filename=e.get("suggested_name")
                            )

                            e["text"] = text or ""

                            # ✅ DEBUG INSERT HERE
                            print(f"EVIDENCE {eid} TEXT LENGTH:", len(e.get("text", "")))

                        except Exception as ex:
                            print(f"TEXT EXTRACTION FAILED for {eid}:", ex)
                            e["text"] = ""

                            # ✅ ALSO LOG FAILURE CASE
                            print(f"EVIDENCE {eid} TEXT LENGTH: 0 (EXCEPTION)")
                            print(f"TEXT SAMPLE for {eid}:", e["text"][:200])

                    # ----------------------------
                    # 🔥 STEP 3 — BUILD CLUSTERS
                    # ----------------------------
                    clusters = build_simple_clusters(evidence)

                    print("CLUSTERS BUILT:", list(clusters.keys()))

                    # 🚨 HARD FAIL CHECK (this is important)
                    if not clusters:
                        st.warning("⚠️ No clusters built — evidence text may be empty")
                    print("=== DEBUG CLUSTERS ===")
                    print("CLUSTERS OBJECT:", clusters)
                    print("CLUSTER KEYS:", list(clusters.keys()) if clusters else "NONE")
                    print("======================")
                    # ----------------------------
                    # 🔥 STEP 4 — EXPORT (PASS DIRECTLY)
                    # ----------------------------
                    bundle_bytes = export_case_bundle(
                        ledger=ledger,
                        case_id=case_id,
                        intelligence=st.session_state.get(f"case_summary_{case_id}"),
                        narrative=st.session_state.get(f"case_narrative_{case_id}"),
                        clusters=clusters,  # ✅ NOT session_state
                    )

                    st.session_state[f"bundle_{case_id}"] = bundle_bytes

                    st.success("✅ Bundle ready for download")

                except Exception as e:
                    st.error(f"Export failed: {e}")

                bundle_key = f"bundle_{case_id}"

                if bundle_key in st.session_state:
                    st.download_button(
                        label="⬇ Download Case Bundle",
                        data=st.session_state[bundle_key],
                        file_name=f"case_{case_id}.zip",
                        mime="application/zip",
                    )



    # ----------------------------
    # NOTES
    # ----------------------------
    st.subheader("📝 Case Notes")

    note_input = st.text_area("Add Note", key=f"note_input_{case_id}")

    if st.button("Add Note", key=f"add_note_{case_id}"):
        if note_input.strip():
            ledger.add_case_note(case_id, note_input)

            if hasattr(ledger, "add_case_event"):
                ledger.add_case_event(case_id, "NOTE_ADDED", note_input[:100])

            st.success("Note added")
            st.rerun()
        else:
            st.warning("Note cannot be empty.")

    notes = ledger.get_case_notes(case_id)

    if notes:
        for n in notes:
            ts = _format_ts(n.get("created_at_ms"))
            st.write(f"{ts} — {n.get('note')}")
    else:
        st.info("No notes yet.")



    # ----------------------------
    # ALERTS
    # ----------------------------
    st.subheader("🚨 Linked Alerts")

    if alerts:
        for a in alerts:
            severity = (a.get("severity") or "LOW").upper()
            message = a.get("message", "")

            if severity == "CRITICAL":
                st.error(f"[{severity}] {message}")
            elif severity == "HIGH":
                st.warning(f"[{severity}] {message}")
            elif severity == "MEDIUM":
                st.info(f"[{severity}] {message}")
            else:
                st.write(f"[{severity}] {message}")
    else:
        st.info("No alerts linked.")

    # ----------------------------
    # EVIDENCE
    # ----------------------------
    st.subheader("📄 Linked Evidence")

    if evidence:

        # 🔥 STEP 2 — RANK EVIDENCE FIRST
        ranked_evidence = []

        for e in evidence:


            eid = e.get("evidence_id") or e.get("id")
            # ✅ STEP 1 — DEDUP FIRST
            seen = set()
            unique_evidence = []

            for e in evidence:
                eid = e.get("evidence_id") or e.get("id")
                if not eid:
                    continue

                if eid in seen:
                    continue

                seen.add(eid)
                unique_evidence.append(e)

            # 🔥 STEP 2 — NOW RANK CLEAN DATA
            ranked_evidence = []

            for e in unique_evidence:
                eid = e.get("evidence_id") or e.get("id")

                # your existing scoring logic here
                score = 0

                ranked_evidence.append({
                    "score": score,
                    "evidence": e
                })

            # sort if needed
            # 🔍 DEBUG: inspect structure BEFORE sort
            print("=== DEBUG: ranked_evidence BEFORE SORT ===")
            print("COUNT:", len(ranked_evidence))

            for i, item in enumerate(ranked_evidence[:5]):
                print(f"ITEM {i} TYPE:", type(item))
                print(f"ITEM {i} VALUE:", item)

            print("==========================================")

            # existing sort
            ranked_evidence.sort(key=lambda x: x["score"], reverse=True)
            text = ""
            if hasattr(ledger, "get_evidence_bytes"):
                data = ledger.get_evidence_bytes(eid)
                if data:
                    try:


                        text = extract_text_from_bytes(
                            data,
                            filename=e.get("suggested_name")
                        )[:2000]
                    except:
                        text = ""

            score, level, matches = score_evidence(text, alerts)

            ranked_evidence.append({
                "e": e,
                "score": score,
                "level": level,
                "matches": matches,
                "text": text
            })

        # 🔥 SORT BY RISK (highest first)
        ranked_evidence.sort(key=lambda x: x["score"], reverse=True)
        clusters = cluster_evidence(ranked_evidence)

        st.session_state["clusters"] = clusters

        # -------------------------
        # 🔥 RENDER SORTED EVIDENCE
        # -------------------------
        for raw_cluster_name, items in clusters.items():

            ai_name = generate_cluster_name(items)
            cluster_cache = st.session_state.setdefault("cluster_names", {})

            key = raw_cluster_name

            if key not in cluster_cache:
                cluster_cache[key] = generate_cluster_name(items)

            ai_name = cluster_cache[key]
            st.markdown(f"## 🧵 {ai_name}")

            for item in items:
                e = item["evidence"]
                score = item["score"]
                # ----------------------------------
                # 🔥 SAFE LEVEL RESOLUTION (FIX)
                # ----------------------------------
                level = (
                        item.get("level")
                        or item.get("severity")
                        or item.get("priority")
                        or "UNKNOWN"
                )

                # normalize level
                if isinstance(level, int):
                    if level <= 1:
                        level = "CRITICAL"
                    elif level <= 2:
                        level = "HIGH"
                    else:
                        level = "MEDIUM"

                level = str(level).upper()
                # ----------------------------------
                # 🔥 SAFE TEXT RESOLUTION (FIX)
                # ----------------------------------
                text = (
                        item.get("text")
                        or item.get("message")
                        or item.get("description")
                        or ""
                )
                # ----------------------------------
                # 🔥 SAFE MATCHES RESOLUTION (FIX)
                # ----------------------------------
                # ----------------------------------
                # 🔥 SAFE MATCHES (FULL VERSION)
                # ----------------------------------
                matches = item.get("matches")

                if not matches:
                    event_data = item.get("event_data")
                    if isinstance(event_data, str):
                        try:
                            import json
                            event_data = json.loads(event_data)
                        except Exception:
                            event_data = {}

                    if isinstance(event_data, dict):
                        matches = event_data.get("matches", [])

                matches = matches or []

                eid = e.get("evidence_id") or e.get("id")

            # 🔥 RISK BADGE
            color_map = {
                "CRITICAL": "red",
                "HIGH": "orange",
                "MEDIUM": "gold",
                "LOW": "green"
            }

            st.markdown(
                f"### {level} Risk ({score}/100) — {e.get('suggested_name') or eid}"
            )

            st.markdown(
                f"<span style='color:{color_map[level]}; font-weight:bold;'>{level}</span>",
                unsafe_allow_html=True
            )
            if hasattr(ledger, "evaluate_case_escalation"):
                result = ledger.evaluate_case_escalation(case_id)

                if result:
                    level = result.get("escalation")

                    if level == "CRITICAL":
                        st.error("🚨 CRITICAL ESCALATION")
                    elif level == "HIGH":
                        st.warning("⚠️ HIGH RISK CASE")
                    elif level == "MEDIUM":
                        st.info("🔎 Medium Risk Monitoring")
            # -------------------------
            # 🔥 EVIDENCE PREVIEW + INTELLIGENCE
            # -------------------------
            if hasattr(ledger, "get_evidence_bytes"):
                data = ledger.get_evidence_bytes(eid)

                if data:
                    preview = data[:5000]

                    try:
                        text = preview.decode("utf-8", errors="ignore")
                        text_preview = text[:2000]

                        with st.expander(f"Preview + Intelligence ({eid})"):

                            # ------------------------
                            # 🔢 COUNT DISPLAY
                            # ------------------------
                            counts = {}
                            for m in matches:
                                counts[m["label"]] = counts.get(m["label"], 0) + 1

                            if counts:
                                st.write("### 🔍 Detected Patterns")
                                st.write(", ".join([f"{k}: {v}" for k, v in counts.items()]))

                            # ------------------------
                            # 🎛 FILTER
                            # ------------------------
                            filter_type = st.selectbox(
                                "Filter by type",
                                ["ALL"] + sorted(set(m["label"] for m in matches)),
                                key=f"filter_{eid}"
                            )

                            if filter_type == "ALL":
                                filter_type = None

                            # ------------------------
                            # 🎯 NAVIGATION STATE
                            # ------------------------
                            nav_key = f"nav_{eid}"
                            if nav_key not in st.session_state:
                                st.session_state[nav_key] = 0

                            filtered_matches = [
                                m for m in matches if not filter_type or m["label"] == filter_type
                            ]

                            col1, col2, col3 = st.columns(3)

                            with col1:
                                if st.button("⬅ Prev", key=f"prev_{eid}"):
                                    st.session_state[nav_key] = max(0, st.session_state[nav_key] - 1)

                            with col2:
                                st.write(f"{st.session_state[nav_key] + 1} / {max(1, len(filtered_matches))}")

                            with col3:
                                if st.button("Next ➡", key=f"next_{eid}"):
                                    st.session_state[nav_key] = min(len(filtered_matches) - 1,
                                                                    st.session_state[nav_key] + 1)

                            # ------------------------
                            # 🎯 CURRENT MATCH INFO
                            # ------------------------
                            if filtered_matches:
                                current = filtered_matches[st.session_state[nav_key]]
                                st.info(f"[{current['label']}] {current['value']}")

                            # ------------------------
                            # 🎨 RENDER HIGHLIGHTED TEXT
                            # ------------------------
                            highlighted_html = render_highlighted_text(
                                text_preview,
                                matches,
                                filter_type
                            )

                            st.markdown(
                                f"<div style='font-family: monospace; white-space: pre-wrap;'>{highlighted_html}</div>",
                                unsafe_allow_html=True
                            )

                            # ------------------------
                            # 🔽 RAW FALLBACK
                            # ------------------------
                            st.caption("Raw Preview")
                            st.code(text_preview[:500])

                    except Exception:
                        st.caption("Binary data (preview not available)")
            else:
                st.caption("No evidence preview available")

    else:
        st.info("No evidence linked.")

    # ----------------------------
    # TIMELINE
    # ----------------------------
    st.subheader("📜 Timeline")

    timeline = ledger.get_case_timeline(case_id)

    if not timeline:
        st.info("No timeline events.")
    else:
        grouped = defaultdict(list)

        for event in timeline:
            created = event.get("created_at_ms")
            if not created:
                continue

            ts = datetime.datetime.fromtimestamp(created / 1000)
            date_key = ts.strftime("%Y-%m-%d")
            grouped[date_key].append((ts, event))

        for date in sorted(grouped.keys(), reverse=True):
            dt = datetime.datetime.strptime(date, "%Y-%m-%d")

            if dt.date() == datetime.datetime.now().date():
                label = "📅 Today"
            else:
                label = dt.strftime("%B %d, %Y")

            st.markdown(f"### {label}")

            for ts, event in sorted(grouped[date], reverse=True):
                event_type = event.get("event_type", "UNKNOWN")
                icon = EVENT_ICONS.get(event_type, "⚪")
                time_str = ts.strftime("%H:%M:%S")

                col1, col2 = st.columns([1, 10])

                with col1:
                    st.markdown(f"## {icon}")

                with col2:
                    st.markdown(f"**{event_type}** — {time_str}")
                    st.caption(event.get("message", ""))

            st.divider()

    st.subheader("🧾 Audit Log")

    audit = ledger.get_case_audit_log(case_id)

    if audit:
        for entry in audit:
            ts = _format_ts(entry.get("created_at_ms"))
            action = entry.get("action")
            user = entry.get("performed_by")
            details = entry.get("details")

            col1, col2 = st.columns([1, 10])

            with col1:
                st.markdown("📌")

            with col2:
                st.markdown(f"**{action}** by `{user}` — {ts}")
                if details:
                    st.caption(details)
    else:
        st.info("No audit events recorded.")