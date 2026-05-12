from __future__ import annotations

from core.utils.secrets_loader import get_secret
from core.storage.local_vault import LocalVault
from core.storage.s3_vault import S3Vault
from core.storage.sqlite_ledger import SQLiteLedger
from core.evidence.service import EvidenceService


def build_evidence_service(db_path: str) -> EvidenceService:
    provider = (get_secret("EVIDENCE_VAULT_PROVIDER", "local") or "local").lower().strip()

    if provider == "s3":
        bucket = require_secret("EVIDENCE_S3_BUCKET")
        prefix = get_secret("EVIDENCE_S3_PREFIX", "objects")
        region = get_secret("AWS_REGION", None)
        vault = S3Vault(bucket=bucket, prefix=prefix, region=region)
    else:
        vault_dir = get_secret("EVIDENCE_LOCAL_VAULT_DIR", "./_vault")
        vault = LocalVault(vault_dir)

    ledger = SQLiteLedger(db_path=db_path)
    return EvidenceService(vault=vault, ledger=ledger)
