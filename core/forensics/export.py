# core/forensics/export.py
from __future__ import annotations


import os
import time
import zipfile
from typing import Any, Dict, List, Tuple

from core.storage.interfaces import stable_json_dumps
from core.utils.hash_utils import sha256_bytes, sha256_text, sha256_file

def _now_tag() -> str:
    return time.strftime("%Y%m%d-%H%M%S", time.gmtime())




def export_forensic_snapshot(storage: Any, out_dir: str = "exports/forensic_snapshots") -> Dict[str, Any]:
    """
    Produces a forensic-safe snapshot bundle (ZIP) containing:
      - ledger.db
      - ledger.db-wal (if present)
      - ledger.db-shm (if present)

    Also writes a MANIFEST.json inside the ZIP with SHA256 hashes of each file.

    Returns dict with:
      - zip_path
      - manifest
    """
    os.makedirs(out_dir, exist_ok=True)

    ledger = getattr(storage, "ledger", None)
    if ledger is None:
        raise RuntimeError("storage.ledger missing")

    # Best effort checkpoint so WAL contents are folded
    if hasattr(ledger, "wal_checkpoint"):
        try:
            ledger.wal_checkpoint()
        except Exception:
            pass

    # Get the file list
    if hasattr(ledger, "snapshot_paths"):
        paths: List[str] = ledger.snapshot_paths()
    else:
        base = getattr(ledger, "db_path", "data/ledger.db")
        paths = [base]
        for suffix in ("-wal", "-shm"):
            p = base + suffix
            if os.path.exists(p):
                paths.append(p)

    tag = _now_tag()
    zip_name = f"forensic-snapshot-{tag}.zip"
    zip_path = os.path.join(out_dir, zip_name)

    manifest_files = []
    for p in paths:
        if os.path.exists(p):
            manifest_files.append({"path": os.path.basename(p), "sha256": sha256_file(p), "size_bytes": os.path.getsize(p)})

    manifest = {
        "created_utc": tag,
        "db_path": getattr(ledger, "db_path", ""),
        "immutable": bool(getattr(ledger, "immutable", False)),
        "files": manifest_files,
    }

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for p in paths:
            if os.path.exists(p):
                z.write(p, arcname=os.path.basename(p))
        z.writestr("MANIFEST.json", stable_json_dumps(manifest))

    return {"zip_path": zip_path, "manifest": manifest}

