# modules/migrations.py
from core.db import connect

def ensure_schema():
    """
    Cloud-safe schema migration.
    Safe to run on every startup.
    """
    with connect() as con:
        cols = {
            row[1] for row in con.execute(
                "PRAGMA table_info(attachments)"
            ).fetchall()
        }

        if "ocr_required" not in cols:
            con.execute(
                "ALTER TABLE attachments ADD COLUMN ocr_required BOOLEAN DEFAULT 0"
            )

        if "ocr_reason" not in cols:
            con.execute(
                "ALTER TABLE attachments ADD COLUMN ocr_reason TEXT"
            )
