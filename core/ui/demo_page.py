import streamlit as st
from core.demo.demo_dataset import build_demo_dataset
from core.evidence.service import EvidenceService

from veridion_theme import apply_theme
apply_theme()
with st.sidebar:
    st.markdown('<h1 class="veridion-sidebar-title">Veridion Pro</h1>', unsafe_allow_html=True)

def render_demo_page(storage):
    st.title("🎬 Live Forensic Demo")

    svc = EvidenceService(storage)

    # ---------------------------
    # STEP 1: LOAD DEMO DATA
    # ---------------------------
    if st.button("🚀 Load Demo Dataset"):
        ids = build_demo_dataset(storage)
        st.success(f"Loaded {len(ids)} demo evidence items")
        st.rerun()

    # ---------------------------
    # STEP 2: SELECT EVIDENCE
    # ---------------------------
    st.header("1. Select Evidence")

    records = storage.ledger.list_evidence_records(limit=100)

    if not records:
        st.info("No evidence records found. Click 'Load Demo Dataset' first.")
        return

    option_map = {
        f"{r['suggested_name']} ({r['evidence_id'][:8]})": r["evidence_id"]
        for r in records
    }

    selected_label = st.selectbox("Choose Evidence", list(option_map.keys()))
    evidence_id = option_map[selected_label]

    selected_record = next((r for r in records if r["evidence_id"] == evidence_id), None)

    # ---------------------------
    # STEP 3: VIEW RECORD
    # ---------------------------
    if st.button("📄 View Ledger Record"):
        rec = svc.get_evidence_record(evidence_id)
        if rec:
            st.json(rec)
        else:
            st.error("Not found")

    # ---------------------------
    # STEP 4: VERIFY
    # ---------------------------
    if st.button("🔍 Verify Integrity"):
        try:
            data = svc.auto_verify_and_get_bytes(evidence_id)
            st.success("✅ VERIFIED: Data integrity confirmed")
            st.code(data.decode(errors="ignore"))
        except Exception as e:
            st.error(f"❌ Verification failed: {e}")

    # ---------------------------
    # STEP 5: SHOW CUSTODY
    # ---------------------------
    if st.button("📜 Show Chain of Custody"):
        events = storage.ledger.list_events_for_evidence(evidence_id)
        if events:
            st.json(events)
        else:
            st.info("No custody events found for this evidence yet.")

    # ---------------------------
    # STEP 6: SNAPSHOT + ANCHOR
    # ---------------------------
    if st.button("🔏 Anchor Snapshot"):
        snapshot = {
            "evidence_id": evidence_id,
            "suggested_name": selected_record["suggested_name"] if selected_record else None,
            "ts": int(__import__("time").time() * 1000),
        }

        anchor = svc.anchor_snapshot(
            snapshot_type="demo_snapshot",
            payload=snapshot,
            actor="demo_user",
        )

        st.success("Snapshot anchored")
        st.json(anchor)

    # --------------------------------
    # STEP 7: SIMULATE TAMPERING
    # --------------------------------
    if st.button("💥 Simulate Tampering"):
        if not selected_record:
            st.error("No evidence record selected.")
            return

        try:
            original_path = selected_record["storage_uri"]

            with open(original_path, "wb") as f:
                f.write(b"THIS DATA WAS TAMPERED")

            st.warning("Simulated file tampering by overwriting the stored file bytes.")
        except Exception as e:
            st.error(f"Tamper simulation failed: {e}")