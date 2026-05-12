# core/crypto/kms_envelope.py
from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Envelope:
    ciphertext: bytes
    encrypted_data_key: bytes
    alg: str = "AESGCM"


def _require_crypto():
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # type: ignore
        return AESGCM
    except Exception as e:
        raise RuntimeError("cryptography is required for KMS envelope encryption. pip install cryptography") from e


def _kms_client():
    try:
        import boto3  # type: ignore
    except Exception as e:
        raise RuntimeError("boto3 is required for KMS usage. pip install boto3") from e
    region = os.getenv("AWS_REGION")
    return boto3.client("kms", region_name=region) if region else boto3.client("kms")


def encrypt_with_kms(plaintext: bytes, *, kms_key_id: Optional[str] = None, aad: Optional[bytes] = None) -> Envelope:
    """
    Envelope encrypt:
      1) KMS GenerateDataKey
      2) AES-GCM encrypt payload with plaintext data key
      3) return ciphertext + encrypted data key
    """
    AESGCM = _require_crypto()
    kms_key_id = kms_key_id or os.getenv("EVIDENCE_KMS_KEY_ID")
    if not kms_key_id:
        raise RuntimeError("Missing EVIDENCE_KMS_KEY_ID (KMS Key ARN/ID)")

    kms = _kms_client()
    resp = kms.generate_data_key(KeyId=kms_key_id, KeySpec="AES_256")
    pt_key = resp["Plaintext"]
    edk = resp["CiphertextBlob"]

    aes = AESGCM(pt_key)
    nonce = os.urandom(12)
    ct = aes.encrypt(nonce, plaintext, aad)

    # Store nonce + ciphertext together
    return Envelope(ciphertext=nonce + ct, encrypted_data_key=edk)


def decrypt_with_kms(env: Envelope, *, aad: Optional[bytes] = None) -> bytes:
    AESGCM = _require_crypto()
    kms = _kms_client()
    resp = kms.decrypt(CiphertextBlob=env.encrypted_data_key)
    pt_key = resp["Plaintext"]

    nonce = env.ciphertext[:12]
    ct = env.ciphertext[12:]
    aes = AESGCM(pt_key)
    return aes.decrypt(nonce, ct, aad)
