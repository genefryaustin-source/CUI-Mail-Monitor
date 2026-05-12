# core/utils/serialization.py

"""
Deterministic serialization helpers.

Used for:
✔ evidence hashing
✔ manifest signing
✔ ledger storage
✔ audit replay

NEVER use raw json.dumps for compliance data.
"""

import json
from typing import Any


def stable_json_dumps(obj: Any) -> str:
    """
    Deterministic JSON encoding.

    Guarantees:
        ✔ sorted keys
        ✔ no whitespace variance
        ✔ stable hashing
    """
    return json.dumps(
        obj,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )
