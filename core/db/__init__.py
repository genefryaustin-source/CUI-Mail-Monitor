"""core.db

Public DB/ledger API for the Streamlit app.
Keep imports stable so UI doesn't break when internals move.
"""

from .db import get_db

def connect():
    return get_db()



def get_setting(*args, **kwargs):
    return None