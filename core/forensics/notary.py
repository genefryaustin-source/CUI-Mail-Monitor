# core/forensics/notary.py
from __future__ import annotations

import os
import uuid
from typing import Any, Dict, Optional

from core.forensics.notary_opentimestamps import OpenTimestampsNotary


class Notary:
    """
    Forensics notary façade.

    - OpenTimestamps stamping (external, decentralized timestamping)
    - Writes an append-only forensic anchor row for auditability
    """

    def __init__(self, storage: Any):
        self.storage = storage
        self.ledger = getattr(storage, "ledger", None)
        if self.ledger is None:
            raise RuntimeError("Notary requires storage.ledger")

        self.ots = OpenTimestampsNotary(work_dir=os.getenv("OTS_WORK_DIR", "data/notary/ots"))

    def opentimestamps_stamp_anchor(
        self,
        *,
        target_id: str,
        hash_sha256: str,
        actor: str = "admin",
        label: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Stamp the provided sha256 hash via OpenTimestamps and record an append-only ledger anchor.

        Stores:
          - proof_path (where the .ots proof is saved)
          - the input hash that was stamped
        """
        res = self.ots.stamp_sha256(sha256_hex=hash_sha256, label=label or target_id)

        anchor_id = str(uuid.uuid4())
        anchor_type = "OTS_STAMP"

        meta = dict(metadata or {})
        meta.update(
            {
                "actor": actor,
                "ots_input_path": res.input_path,
                "ots_proof_path": res.proof_path,
                "ots_stdout": res.calendar_output,
            }
        )

        # Append-only anchor row
        if not hasattr(self.ledger, "record_forensic_anchor"):
            raise RuntimeError("Ledger missing record_forensic_anchor(...)")

        self.ledger.record_forensic_anchor(
            anchor_id=anchor_id,
            anchor_type=anchor_type,
            target_id=target_id,
            hash_sha256=hash_sha256,
            metadata=meta,
        )

        return {
            "anchor_id": anchor_id,
            "anchor_type": anchor_type,
            "target_id": target_id,
            "hash_sha256": hash_sha256,
            "ots_proof_path": res.proof_path,
        }