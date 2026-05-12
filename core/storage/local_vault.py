from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from .interfaces import EvidenceRecord, now_utc_epoch_ms
from core.utils.hash_utils import sha256_bytes_hex


class LocalVault:
    """
    Local filesystem evidence vault.

    Guarantees:
    ✔ content-addressed storage (sha256)
    ✔ immutability (never overwrite)
    ✔ deterministic paths
    ✔ Windows-safe filenames
    """

    backend_name = "local"

    def __init__(self, root_dir: str = "data") -> None:
        self.root = Path(root_dir).resolve()
        self.evidence_dir = self.root / "evidence"
        self.evidence_dir.mkdir(parents=True, exist_ok=True)

    # ----------------------------

    def _safe_name(self, name: str) -> str:
        name = name.strip().replace("\\", "_").replace("/", "_")
        return "".join(
            ch if ch.isalnum() or ch in ("_", "-", ".", " ")
            else "_"
            for ch in name
        )[:140] or "blob"

    def _path_for(self, sha256: str, name: str) -> Path:
        prefix = sha256[:2]
        folder = self.evidence_dir / prefix
        folder.mkdir(parents=True, exist_ok=True)
        return folder / f"{sha256}__{self._safe_name(name)}"

    # ----------------------------

    def put_bytes(
        self,
        *,
        data: bytes,
        suggested_name: str,
        content_type: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> EvidenceRecord:

        metadata = metadata or {}

        sha = sha256_bytes_hex(data)
        path = self._path_for(sha, suggested_name)

        # 🔒 immutable-by-hash
        if not path.exists():
            path.write_bytes(data)

        return EvidenceRecord(
            evidence_id=sha,  # deterministic
            sha256=sha,
            size_bytes=len(data),
            content_type=content_type or "application/octet-stream",
            storage_uri=str(path),
            suggested_name=suggested_name,
            created_at_ms=now_utc_epoch_ms(),
            metadata=metadata,
        )

    # ----------------------------

    def open_bytes(self, *, evidence_id: str) -> bytes:
        prefix = evidence_id[:2]
        folder = self.evidence_dir / prefix

        if not folder.exists():
            raise FileNotFoundError(f"Evidence folder not found for {evidence_id}")

        for p in folder.glob(f"{evidence_id}__*"):
            return p.read_bytes()

        raise FileNotFoundError(f"Evidence not found: {evidence_id}")

    # ----------------------------

    def exists(self, *, evidence_id: str) -> bool:
        prefix = evidence_id[:2]
        folder = self.evidence_dir / prefix
        if not folder.exists():
            return False

        return any(folder.glob(f"{evidence_id}__*"))
