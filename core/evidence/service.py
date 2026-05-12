# core/evidence/service.py
from __future__ import annotations


import json
import time
import uuid
from typing import Any, Dict, Optional
from core.cases.config import CASE_OWNERS, PRIORITY_RULES, SLA_HOURS

import random
from core.utils.hash_utils import sha256_bytes, sha256_text, sha256_file, sha256_bytes_hex


# =========================================================
# Canonical JSON + Hash Helpers
# =========================================================

def _canonical_json(obj: Any) -> str:
    """
    Canonical JSON serialization for hashing.
    Uses stable_json_dumps if available, otherwise
    falls back to deterministic json.dumps.
    """
    try:
        from core.storage.interfaces import stable_json_dumps
        return stable_json_dumps(obj)
    except Exception:
        return json.dumps(obj, sort_keys=True, separators=(",", ":"))





def _now_ms() -> int:
    return int(time.time() * 1000)


# =========================================================
# Evidence & Forensics Service
# =========================================================

class EvidenceService:
    """
    Evidence & Forensics Service Layer (API-STABLE)

    Responsibilities:
      - Evidence byte verification
      - Auto-verified downloads
      - Snapshot anchoring
      - Evidence anchoring
      - Run anchoring
    """

    def __init__(self, storage: Any):
        self.storage = storage
        self.ledger = getattr(storage, "ledger", None)
        self.vault = getattr(storage, "vault", None)

        if self.ledger is None:
            raise RuntimeError("EvidenceService requires storage.ledger")
        if self.vault is None:
            raise RuntimeError("EvidenceService requires storage.vault")

    # =====================================================
    # Evidence Lookup
    # =====================================================

    def get_evidence_record(self, evidence_id: str) -> Optional[Dict[str, Any]]:
        if not hasattr(self.ledger, "get_evidence_record"):
            return None

        rec = self.ledger.get_evidence_record(evidence_id)
        if rec is None:
            return None

        if isinstance(rec, dict):
            return rec

        if hasattr(rec, "__dict__"):
            return dict(rec.__dict__)

        return None

    # =====================================================
    # Verification
    # =====================================================

    def verify_evidence_bytes(
        self,
        evidence_id: str,
        data: bytes,
    ) -> Dict[str, Any]:
        rec = self.get_evidence_record(evidence_id)
        if not rec:
            return {
                "evidence_id": evidence_id,
                "verified": False,
                "error": "Evidence not found in ledger",
            }

        expected = str(rec.get("sha256") or "")
        actual = sha256_bytes(data)

        return {
            "evidence_id": evidence_id,
            "verified": (expected != "" and actual == expected),
            "expected_sha256": expected,
            "actual_sha256": actual,
            "size_bytes": len(data),
        }

    # =====================================================
    # AUTO-VERIFY + DOWNLOAD
    # =====================================================

    def auto_verify_and_get_bytes(self, evidence_id: str) -> bytes:
        rec = self.storage.ledger.get_evidence_record(evidence_id)

        if not rec:
            raise ValueError(f"Evidence not found: {evidence_id}")

        run_id = "demo_run"

        # Ensure parent run exists
        self.storage.ledger.ensure_run(
            run_id=run_id,
            provider="demo_verify",
            mailbox="demo@local",
        )

        data = self.storage.vault.open_bytes(evidence_id=evidence_id)
        actual_sha = sha256_bytes_hex(data)

        # ------------------------
        # 🔴 FAILURE CASE
        # ------------------------
        if actual_sha != rec["sha256"]:
            # Log custody event
            self.storage.ledger.record_custody_event(
                run_id=run_id,
                evidence_id=evidence_id,
                event_type="INTEGRITY_FAILED",
                actor="demo_user",
                details={
                    "expected_sha": rec["sha256"],
                    "actual_sha": actual_sha,
                },
            )

            # 🚨 CREATE ALERT (FIX: capture return)
            alert = self.storage.ledger.create_alert(
                evidence_id=evidence_id,
                severity="CRITICAL",
                message="Integrity failure detected (SHA mismatch)"
            )

            # -------------------------------------------------
            # 🔥 AUTO CASE CREATION (FIX: now actually called)
            # -------------------------------------------------
            def auto_create_case_from_alert(storage, alert):
                if not alert:
                    return

                ledger = storage.ledger

                if alert.get("severity") != "CRITICAL":
                    return

                evidence_id = alert.get("evidence_id")
                if not evidence_id:
                    return

                existing_case = None
                if hasattr(ledger, "find_case_by_evidence"):
                    existing_case = ledger.find_case_by_evidence(evidence_id)

                if existing_case:
                    case_id = existing_case["case_id"]
                else:
                    import uuid
                    case_id = str(uuid.uuid4())

                    if hasattr(ledger, "create_case"):


                        severity = alert.get("severity", "LOW")

                        # 🎯 Priority
                        priority = PRIORITY_RULES.get(severity, "P4")

                        # 👤 Owner (round-robin/random for now)
                        owner = random.choice(CASE_OWNERS)

                        # ⏱ SLA
                        hours = SLA_HOURS.get(priority, 72)
                        sla_due_ms = int(time.time() * 1000 + (hours * 3600 * 1000))

                        ledger.create_case(
                            case_id,
                            title=f"Critical Incident: {evidence_id[:8]}",
                            description="Auto-generated from CRITICAL alert"
                        )

                        # 🔧 Update new fields
                        if hasattr(ledger, "_connect"):
                            with ledger._connect() as con:
                                con.execute("""
                                    UPDATE cases
                                    SET owner = ?, priority = ?, sla_due_ms = ?, status = 'OPEN'
                                    WHERE case_id = ?
                                """, (owner, priority, sla_due_ms, case_id))
                                con.commit()

                    if hasattr(ledger, "add_case_evidence"):
                        ledger.add_case_evidence(case_id, evidence_id)

                if hasattr(ledger, "add_case_alert"):
                    ledger.add_case_alert(case_id, alert.get("id"))

                if hasattr(ledger, "add_case_note"):
                    ledger.add_case_note(
                        case_id,
                        f"Auto-created from CRITICAL alert: {alert.get('message')}"
                    )

            # 🔥 CALL IT (this was missing)
            try:
                auto_create_case_from_alert(self.storage, alert)
            except Exception as e:
                print("Auto case creation failed:", e)

            # 🚨 SEND SLACK ALERT (LEFT COMMENTED AS REQUESTED)
            # try:
            #     from core.alerts.notifier import send_slack_alert
            #     send_slack_alert(
            #         webhook_url="YOUR_SLACK_WEBHOOK_URL",
            #         message=f"Integrity failure for evidence: {evidence_id}"
            #     )
            # except Exception as e:
            #     print(f"Slack alert failed: {e}")

            # from core.alerts.notifier import notify
            # notify(
            #     storage=self.storage,
            #     severity="CRITICAL",
            #     message=f"Integrity failure for evidence: {evidence_id}"
            # )

            raise ValueError("INTEGRITY FAILURE: SHA256 mismatch")

        # ------------------------
        # ✅ SUCCESS CASE
        # ------------------------
        self.storage.ledger.record_custody_event(
            run_id=run_id,
            evidence_id=evidence_id,
            event_type="VERIFIED",
            actor="demo_user",
            details={"status": "success"},
        )

        return data

    # =====================================================
    # SNAPSHOT ANCHORING (Append-only)
    # =====================================================

    def anchor_snapshot(
        self,
        *,
        snapshot_type: str,
        payload: Dict[str, Any],
        actor: str = "system",
    ) -> Dict[str, Any]:
        """
        Anchors a deterministic snapshot hash into forensic_anchors.
        """

        canonical = _canonical_json(payload)
        sha256 = sha256_text(canonical)
        anchor_id = str(uuid.uuid4())

        if not hasattr(self.ledger, "record_forensic_anchor"):
            raise RuntimeError("Ledger does not support forensic anchoring")

        self.ledger.record_forensic_anchor(
            anchor_id=anchor_id,
            anchor_type=snapshot_type,
            target_id=anchor_id,  # self-anchored snapshot
            hash_sha256=sha256,
            metadata={
                "actor": actor,
                "payload_size": len(canonical),
            },
        )

        return {
            "anchor_id": anchor_id,
            "anchor_type": snapshot_type,
            "sha256": sha256,
            "created_at_ms": _now_ms(),
        }

    # =====================================================
    # EVIDENCE HASH ANCHOR
    # =====================================================

    def anchor_evidence_hash(self, evidence_id: str, actor: str = "system") -> Dict[str, Any]:
        rec = self.get_evidence_record(evidence_id)
        if not rec:
            raise RuntimeError("Evidence not found")

        sha256 = rec.get("sha256")
        anchor_id = str(uuid.uuid4())

        self.ledger.record_forensic_anchor(
            anchor_id=anchor_id,
            anchor_type="EVIDENCE",
            target_id=evidence_id,
            hash_sha256=sha256,
            metadata={
                "actor": actor,
                "source": "ledger",
            },
        )

        return {
            "anchor_id": anchor_id,
            "evidence_id": evidence_id,
            "sha256": sha256,
        }

    # =====================================================
    # RUN MANIFEST ANCHOR
    # =====================================================

    def anchor_run_manifest(self, run_id: str, actor: str = "system") -> Dict[str, Any]:
        manifest = self.ledger.load_manifest(run_id)
        if not manifest:
            raise RuntimeError("Manifest not found for run")

        canonical = _canonical_json(manifest)
        sha256 = sha256_text(canonical)
        anchor_id = str(uuid.uuid4())

        self.ledger.record_forensic_anchor(
            anchor_id=anchor_id,
            anchor_type="RUN",
            target_id=run_id,
            hash_sha256=sha256,
            metadata={
                "actor": actor,
                "manifest_size": len(canonical),
            },
        )

        return {
            "anchor_id": anchor_id,
            "run_id": run_id,
            "sha256": sha256,
        }

