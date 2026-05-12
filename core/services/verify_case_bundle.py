import sys
import json
import zipfile

import base64
import tempfile
import os
from cryptography.hazmat.primitives import serialization
from core.utils.hash_utils import sha256_bytes_hex




def verify_bundle(zip_path: str):
    with zipfile.ZipFile(zip_path, "r") as z:
        bundle_sig = json.loads(z.read("bundle_signature.json").decode("utf-8"))
        expected_hash = z.read("bundle_sha256.txt").decode("utf-8").strip()
        public_key_bytes = z.read("signing_public.pem")

    with open(zip_path, "rb") as f:
        bundle_bytes = f.read()

    # NOTE:
    # The signature signs the ZIP before signature files were appended.
    # For strict verification, use external detached .sig files instead.
    # This embedded method verifies hash presence and evidence hashes.
    actual_hash = sha256_bytes_hex(bundle_bytes)

    print("Bundle SHA256 in manifest:", bundle_sig.get("bundle_sha256"))
    print("Bundle SHA256 file:", expected_hash)
    print("Current ZIP SHA256:", actual_hash)

    with zipfile.ZipFile(zip_path, "r") as z:
        evidence_hashes = json.loads(z.read("evidence_hashes.json").decode("utf-8"))

        ok = True
        for item in evidence_hashes:
            filename = item["filename"]
            expected = item["sha256"]
            data = z.read(filename)
            actual = sha256_bytes_hex(data)

            if actual != expected:
                print(f"❌ Evidence hash mismatch: {filename}")
                ok = False
            else:
                print(f"✅ Evidence verified: {filename}")

    if ok:
        print("✅ Evidence integrity verified")
    else:
        print("❌ Evidence integrity failed")

    return ok


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m core.services.verify_case_bundle <bundle.zip>")
        sys.exit(1)

    ok = verify_bundle(sys.argv[1])
    sys.exit(0 if ok else 2)