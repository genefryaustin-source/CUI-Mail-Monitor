import hashlib


# -----------------------------
# BYTES
# -----------------------------
def sha256_bytes(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def sha256_bytes_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# -----------------------------
# TEXT
# -----------------------------
def sha256_text(text: str) -> bytes:
    return hashlib.sha256(text.encode("utf-8")).digest()


def sha256_text_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# -----------------------------
# FILE
# -----------------------------
def sha256_file(path: str) -> bytes:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.digest()


def sha256_file_hex(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()

def md5_text_hex(text: str) -> str:

    return hashlib.md5(text.encode("utf-8")).hexdigest()

