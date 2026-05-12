# core/storage/s3_vault.py
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Optional


class S3Vault:
    """
    Production vault: stores bytes in S3.

    Requires: boto3

    Env:
      EVIDENCE_S3_BUCKET                (required)
      AWS_REGION                        (optional)

      # Encryption
      EVIDENCE_S3_SSE                   ("AES256" | "aws:kms" | empty)
      EVIDENCE_S3_KMS_KEY_ID            (required if aws:kms)

      # Object Lock (bucket must have Object Lock enabled)
      EVIDENCE_S3_OBJECT_LOCK_MODE      ("GOVERNANCE" | "COMPLIANCE")
      EVIDENCE_S3_OBJECT_LOCK_RETAIN_DAYS  (e.g., "30")
    """

    backend_name = "s3"

    def __init__(self, bucket: Optional[str] = None, region: Optional[str] = None):
        try:
            import boto3  # type: ignore
        except Exception as e:
            raise RuntimeError("boto3 is required for S3Vault. Install boto3.") from e

        self.bucket = bucket or os.getenv("EVIDENCE_S3_BUCKET")
        if not self.bucket:
            raise RuntimeError("Missing EVIDENCE_S3_BUCKET for S3Vault.")

        self.region = region or os.getenv("AWS_REGION")
        self._s3 = boto3.client("s3", region_name=self.region) if self.region else boto3.client("s3")

        # Encryption config
        self.sse = (os.getenv("EVIDENCE_S3_SSE") or "").strip()
        self.kms_key_id = (os.getenv("EVIDENCE_S3_KMS_KEY_ID") or "").strip()

        # Object Lock config
        self.lock_mode = (os.getenv("EVIDENCE_S3_OBJECT_LOCK_MODE") or "").strip().upper()
        self.lock_retain_days = (os.getenv("EVIDENCE_S3_OBJECT_LOCK_RETAIN_DAYS") or "").strip()

    def _extra_args(self, content_type: str) -> dict:
        extra = {"ContentType": content_type or "application/octet-stream"}

        # SSE
        if self.sse:
            extra["ServerSideEncryption"] = self.sse
            if self.sse == "aws:kms":
                if not self.kms_key_id:
                    raise RuntimeError("EVIDENCE_S3_KMS_KEY_ID required when EVIDENCE_S3_SSE=aws:kms")
                extra["SSEKMSKeyId"] = self.kms_key_id

        # Object Lock
        if self.lock_mode in ("GOVERNANCE", "COMPLIANCE"):
            extra["ObjectLockMode"] = self.lock_mode
            if self.lock_retain_days:
                days = int(self.lock_retain_days)
                retain_until = datetime.now(timezone.utc) + timedelta(days=days)
                extra["ObjectLockRetainUntilDate"] = retain_until

        return extra

    def put_bytes(self, storage_key: str, data: bytes, content_type: str) -> None:
        self._s3.put_object(
            Bucket=self.bucket,
            Key=storage_key,
            Body=data,
            **self._extra_args(content_type),
        )

    def get_bytes(self, storage_key: str) -> bytes:
        obj = self._s3.get_object(Bucket=self.bucket, Key=storage_key)
        return obj["Body"].read()

    def exists(self, storage_key: str) -> bool:
        try:
            self._s3.head_object(Bucket=self.bucket, Key=storage_key)
            return True
        except Exception:
            return False
