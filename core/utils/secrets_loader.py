# core/utils/secrets_loader.py

"""
UNIVERSAL SECRET LOADER

Priority:
1. Environment variables (local, Docker, CI)
2. Streamlit secrets (Cloud)
3. Explicit failure (clear error)

Core code NEVER imports streamlit directly.
"""

import os

def get_secret(name: str, default=None, required: bool = True):
    import os
    from pathlib import Path
    import toml

    # 🚫 Ignore known bad placeholders
    BAD_VALUES = {"your-client-id", "your-secret", "", None}

    # 1️⃣ Try environment variable
    value = os.getenv(name)
    if value and value not in BAD_VALUES:
        return value

    # 2️⃣ Load Streamlit secrets file manually
    secrets_path = Path(".streamlit/secrets.toml")

    if secrets_path.exists():
        try:
            data = toml.load(secrets_path)
            if name in data:
                return data[name]
        except Exception:
            pass

    # 3️⃣ Default / error
    if not required:
        return default

    raise RuntimeError(
        f"Missing required secret: {name}"
    )
