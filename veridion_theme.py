"""
veridion_theme.py
=================
Drop this file into your Streamlit project and call `apply_theme()` at the
top of every page (before any other st.* calls) to apply the Veridion
Solutions dark-navy / green accent look.
Usage
-----
    from veridion_theme import apply_theme
    apply_theme()
"""
import streamlit as st

# ── Colour tokens (match Veridion Solutions screenshot) ──────────────────────
NAVY = "#0B1929" # sidebar background
NAVY_LIGHT = "#122438" # sidebar hover / card surface
GREEN = "#4CAF72" # primary accent — active nav pill, status dots
GREEN_DIM = "#3a8f5a" # button hover
WHITE = "#FFFFFF"
OFF_WHITE = "#FFFFFF" # main content background — pure white avoids monitor coating artifacts
TEXT_DARK = "#0D1B2A" # headings / body on light bg
TEXT_MID = "#4A5D6E" # secondary text
BORDER = "#1E3348" # subtle dividers inside sidebar

def apply_theme():
    """Inject Veridion-style CSS into the Streamlit app."""
    st.markdown(
        f"""
        <style>
        /* ── Google Font ──────────────────────────────────────────────── */
        @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700;800&display=swap');

        /* ── Global reset ─────────────────────────────────────────────── */
        html, body {{
            font-family: 'DM Sans', sans-serif !important;
        }}
        [class*="css"]:not(.dvn-scroller):not(.gdg-cell):not(canvas) {{
            font-family: 'DM Sans', sans-serif !important;
        }}

        /* ── App shell — fully opaque, no transparency or gradients ─────── */
        .stApp {{
            background-color: {OFF_WHITE} !important;
            background-image: none !important;
        }}
        [data-testid="stAppViewContainer"] {{
            background-color: {OFF_WHITE} !important;
            background-image: none !important;
        }}
        [data-testid="stAppViewBlockContainer"],
        [data-testid="block-container"] {{
            background-color: {OFF_WHITE} !important;
            background-image: none !important;
        }}

        /* ── Dataframe outer border only — do NOT touch internals ───────── */
        [data-testid="stDataFrame"] {{
            border: 1.5px solid #D0DFED !important;
            border-radius: 12px !important;
        }}

        /* Force the outer wrapper fully white — some versions use rgba */
        .appview-container,
        .appview-container > section,
        .appview-container > section > div {{
            background-color: {OFF_WHITE} !important;
            background-image: none !important;
        }}

        /* ── Sidebar wrapper ──────────────────────────────────────────── */
        section[data-testid="stSidebar"] {{
            background-color: {NAVY} !important;
            border-right: none !important;
        }}
        section[data-testid="stSidebar"] > div {{
            background-color: {NAVY} !important;
            padding: 1.2rem 1rem 0.5rem 1rem !important;
        }}

        /* ── VERIDION PRO TITLE (Top of Sidebar) ──────────────────────── */
        .veridion-sidebar-title {{
            font-size: 1.85rem !important;
            font-weight: 800 !important;
            color: {WHITE} !important;
            letter-spacing: -0.04em !important;
            margin: 0 0 1.6rem 0 !important;
            padding-bottom: 0.7rem !important;
            border-bottom: 2px solid {GREEN} !important;
            display: block;
        }}

        /* Prevent duplicate titles (local + Streamlit Cloud) */
        .veridion-sidebar-title + .veridion-sidebar-title,
        .veridion-sidebar-title ~ .veridion-sidebar-title,
        [data-testid="stSidebar"] .veridion-sidebar-title:not(:first-child) {{
            display: none !important;
        }}

        /* ── Sidebar text ─────────────────────────────────────────────── */
        section[data-testid="stSidebar"] * {{
            color: {WHITE} !important;
        }}
        section[data-testid="stSidebar"] p,
        section[data-testid="stSidebar"] span,
        section[data-testid="stSidebar"] label {{
            color: rgba(255,255,255,0.75) !important;
            font-size: 0.9rem;
            letter-spacing: 0.01em;
        }}

        /* ── Sidebar headings ─────────────────────────────────────────── */
        section[data-testid="stSidebar"] h1,
        section[data-testid="stSidebar"] h2,
        section[data-testid="stSidebar"] h3 {{
            color: {WHITE} !important;
            font-weight: 700;
            letter-spacing: -0.01em;
        }}

        /* ── Sidebar nav buttons (pill style) ─────────────────────────── */
        section[data-testid="stSidebar"] .stButton > button {{
            width: 100%;
            text-align: left;
            background: transparent !important;
            color: {WHITE} !important;
            border: none !important;
            border-radius: 10px !important;
            padding: 0.65rem 1.1rem !important;
            font-size: 0.92rem !important;
            font-weight: 600 !important;
            letter-spacing: 0.01em;
            transition: background 0.15s ease;
            margin-bottom: 2px;
            box-shadow: none !important;
        }}
        section[data-testid="stSidebar"] .stButton > button:hover {{
            background: {NAVY_LIGHT} !important;
            color: {WHITE} !important;
            border: none !important;
        }}

        /* Active / primary sidebar button → green pill */
        section[data-testid="stSidebar"] .stButton > button[kind="primary"] {{
            background: {GREEN} !important;
            color: {WHITE} !important;
            border: none !important;
        }}

        /* ── Sidebar page_link nav items ──────────────────────────────── */
        section[data-testid="stSidebar"] [data-testid="stPageLink"],
        section[data-testid="stSidebar"] [data-testid="stPageLink"] a {{
            display: block !important;
            width: 100% !important;
            color: rgba(255,255,255,0.80) !important;
            text-decoration: none !important;
            font-size: 0.92rem !important;
            font-weight: 600 !important;
            padding: 0.55rem 1.1rem !important;
            border-radius: 10px !important;
            transition: background 0.15s ease, color 0.15s ease !important;
            margin-bottom: 2px !important;
            background: transparent !important;
        }}
        section[data-testid="stSidebar"] [data-testid="stPageLink"]:hover,
        section[data-testid="stSidebar"] [data-testid="stPageLink"] a:hover {{
            background: {NAVY_LIGHT} !important;
            color: {WHITE} !important;
        }}

        /* Active page */
        section[data-testid="stSidebar"] [data-testid="stPageLink"] a[aria-current="page"],
        section[data-testid="stSidebar"] [data-testid="stPageLink"][aria-current="page"],
        section[data-testid="stSidebar"] [data-testid="stPageLink"] a.active {{
            background: {GREEN} !important;
            color: {WHITE} !important;
            border-radius: 10px !important;
        }}

        /* Remove bullet markers */
        section[data-testid="stSidebar"] [data-testid="stPageLink"]::before,
        section[data-testid="stSidebar"] [data-testid="stPageLink"] a::before {{
            display: none !important;
        }}

        /* ── Sidebar navigation section label ─────────────────────────── */
        section[data-testid="stSidebar"] [data-testid="stSidebarNavItems"] {{
            padding-top: 0.5rem;
        }}

        /* ── Sidebar divider ──────────────────────────────────────────── */
        section[data-testid="stSidebar"] hr {{
            border-color: {BORDER} !important;
            margin: 1rem 0;
        }}

        /* ── Sidebar selectbox / radio ────────────────────────────────── */
        section[data-testid="stSidebar"] .stSelectbox > div > div,
        section[data-testid="stSidebar"] .stRadio > div {{
            background: {NAVY_LIGHT} !important;
            border: 1px solid {BORDER} !important;
            border-radius: 8px;
            color: {WHITE} !important;
        }}
        section[data-testid="stSidebar"] .stRadio label span {{
            color: {WHITE} !important;
        }}

        /* ── Status badge helper ──────────────────────────────────────── */
        .veridion-status {{
            display: flex;
            align-items: center;
            gap: 8px;
            color: {GREEN} !important;
            font-weight: 600;
            font-size: 0.88rem;
            padding: 0.5rem 0;
        }}
        .veridion-status::before {{
            content: "●";
            font-size: 0.7rem;
            color: {GREEN};
        }}

        /* ── Main content area ────────────────────────────────────────── */
        .main .block-container {{
            background-color: {WHITE} !important;
            background-image: none !important;
            border-radius: 12px !important;
            padding: 2.5rem 2.5rem !important;
            box-shadow: none !important;
            max-width: 1100px !important;
        }}

        /* ── Page headings ────────────────────────────────────────────── */
        h1 {{
            color: {TEXT_DARK} !important;
            font-weight: 800 !important;
            font-size: 2rem !important;
            letter-spacing: -0.02em !important;
            margin-bottom: 0.2rem !important;
        }}
        h2 {{
            color: {TEXT_DARK} !important;
            font-weight: 700 !important;
            font-size: 1.3rem !important;
            letter-spacing: -0.015em !important;
            margin-top: 1.8rem !important;
        }}
        h3 {{
            color: {TEXT_DARK} !important;
            font-weight: 600 !important;
        }}

        /* ── Subheader accent line ────────────────────────────────────── */
        .veridion-subheader {{
            font-size: 0.82rem;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            color: {TEXT_MID};
            margin-bottom: 0.8rem;
        }}

        /* ── Metric / status badge ────────────────────────────────────── */
        .veridion-active {{
            color: {GREEN} !important;
            font-weight: 700;
            font-size: 0.9rem;
        }}

        /* All the rest of your original styles (unchanged) */
        [data-testid="stMetric"] {{
            background: {WHITE} !important;
            border: 1.5px solid #D0DFEd !important;
            border-radius: 14px !important;
            padding: 1.2rem 1.4rem !important;
            box-shadow: 0 1px 6px rgba(11,25,41,0.06) !important;
        }}
        [data-testid="stMetricLabel"] > div,
        [data-testid="stMetricLabel"] label,
        [data-testid="stMetricLabel"] p {{
            color: {TEXT_MID} !important;
            font-size: 0.75rem !important;
            font-weight: 700 !important;
            text-transform: uppercase !important;
            letter-spacing: 0.08em !important;
        }}
        [data-testid="stMetricValue"] > div {{
            color: {TEXT_DARK} !important;
            font-size: 2.2rem !important;
            font-weight: 800 !important;
            letter-spacing: -0.02em !important;
            line-height: 1.1 !important;
        }}

        /* Inputs, buttons, sliders, checkboxes, etc. — all your original rules */
        .stSelectbox > div > div, .stTextInput > div > div > input, .stTextArea textarea,
        [data-testid="stNumberInput"] > div, [data-testid="stSlider"] [role="slider"] {{
            border: 1.5px solid #C5D5E4 !important;
            border-radius: 10px !important;
        }}
        button[kind="primary"], .stButton > button[kind="primary"] {{
            background: {GREEN} !important;
        }}

        /* Hide Streamlit branding */
        #MainMenu, footer, header {{ visibility: hidden; }}
        </style>
        """,
        unsafe_allow_html=True,
    )

def status_badge(text: str = "System Online", online: bool = True):
    """Render a coloured status indicator (use inside the sidebar)."""
    colour = GREEN if online else "#E05C5C"
    st.markdown(
        f'<div class="veridion-status" style="color:{colour} !important;">'
        f'{text}</div>',
        unsafe_allow_html=True,
    )

def active_status(label: str, value: str):
    """Render a label + green-accented value."""
    st.markdown(
        f'<span style="color:#4A5D6E;font-size:0.9rem;">{label} </span>'
        f'<span class="veridion-active">{value}</span>',
        unsafe_allow_html=True,
    )