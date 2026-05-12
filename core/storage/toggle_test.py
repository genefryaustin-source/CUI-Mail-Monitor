# core/storage/toggle_test.py
from __future__ import annotations

from typing import Dict, Any

from .factory import build_storage
from .interfaces import sha256_bytes


def run_storage_toggle_test() -> Dict[str, Any]:
    """
    Writes a deterministic blob to the current vault backend,
    reads it back, verifies hash, and returns details.
    """
    storage = build_storage()

    blob = b"STORAGE_TOGGLE_TEST::CUI_MAIL_MONITOR::v1\n"
    expected_sha = sha256_bytes(blob)

    rec = storage.vault.put_bytes(
        data=blob,
        suggested_name="storage_toggle_test.txt",
        content_type="text/plain",
        metadata={"purpose": "storage_toggle_test"},
    )

    roundtrip = storage.vault.open_bytes(evidence_id=rec.evidence_id)
    got_sha = sha256_bytes(roundtrip)

    return {
        "vault_backend": getattr(storage.vault, "backend_name", storage.vault.__class__.__name__),
        "evidence_id": rec.evidence_id,
        "storage_uri": rec.storage_uri,
        "expected_sha256": expected_sha,
        "got_sha256": got_sha,
        "ok": (expected_sha == got_sha == rec.sha256),
    }
