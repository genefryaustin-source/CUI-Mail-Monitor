# modules/debug.py
import traceback
import streamlit as st
from datetime import datetime, timezone

# Session-scoped error buffer
def _init():
    if "app_errors" not in st.session_state:
        st.session_state.app_errors = []

def capture_error(
    err: Exception,
    context: str = "",
    show_trace: bool = False
):
    """
    Capture an exception and store a clean version for UI display.
    """
    _init()

    entry = {
        "time": datetime.now(timezone.utc).isoformat(),
        "type": type(err).__name__,
        "message": str(err),
        "context": context,
        "trace": traceback.format_exc() if show_trace else None
    }

    st.session_state.app_errors.append(entry)

def error_panel():
    """
    Render a collapsible error panel in the UI.
    """
    _init()

    if not st.session_state.app_errors:
        return

    with st.expander("⚠ Application Errors (debug)", expanded=False):
        for i, e in enumerate(st.session_state.app_errors[::-1], 1):
            st.markdown(
                f"""
**{i}. {e['type']}**
- **Time:** {e['time']}
- **Context:** {e['context']}
- **Message:** `{e['message']}`
"""
            )
            if e["trace"]:
                st.code(e["trace"])
            st.divider()
