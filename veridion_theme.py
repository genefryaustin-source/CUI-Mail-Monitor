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

        /* ── STRONG DUPLICATE PREVENTION (for Streamlit Cloud) ────────── */
        .veridion-sidebar-title + .veridion-sidebar-title,
        .veridion-sidebar-title ~ .veridion-sidebar-title,
        [data-testid="stSidebar"] .veridion-sidebar-title:not(:first-of-type) {{
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

        /* Active page — Streamlit marks it with aria-current="page" */
        section[data-testid="stSidebar"] [data-testid="stPageLink"] a[aria-current="page"],
        section[data-testid="stSidebar"] [data-testid="stPageLink"][aria-current="page"],
        section[data-testid="stSidebar"] [data-testid="stPageLink"] a.active {{
            background: {GREEN} !important;
            color: {WHITE} !important;
            border-radius: 10px !important;
        }}

        /* Remove any bullet / dot markers on nav items */
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

        /* ── "System Online" status badge helper ──────────────────────── */
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

        /* ── st.metric cards ──────────────────────────────────────────── */
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
        [data-testid="stMetricDelta"] {{
            font-weight: 600 !important;
        }}

        /* ── Selectbox / dropdowns ────────────────────────────────────── */
        .stSelectbox > div > div {{
            background: {WHITE} !important;
            border: 1.5px solid #C5D5E4 !important;
            border-radius: 10px !important;
            color: {TEXT_DARK} !important;
        }}
        .stSelectbox > div > div:focus-within {{
            border-color: {GREEN} !important;
            box-shadow: 0 0 0 2px {GREEN}30 !important;
        }}

        /* ── Number inputs (+/- step buttons) ─────────────────────────── */
        [data-testid="stNumberInput"] > div {{
            background: {WHITE} !important;
            border: 1.5px solid #C5D5E4 !important;
            border-radius: 10px !important;
            overflow: hidden;
        }}
        [data-testid="stNumberInput"] input {{
            background: {WHITE} !important;
            color: {TEXT_DARK} !important;
            border: none !important;
        }}
        [data-testid="stNumberInput"] button,
        [data-testid="stNumberInputStepDown"],
        [data-testid="stNumberInputStepUp"] {{
            background: #EDF2F7 !important;
            color: {TEXT_DARK} !important;
            border: none !important;
            border-left: 1.5px solid #C5D5E4 !important;
            opacity: 1 !important;
            visibility: visible !important;
            min-width: 2rem !important;
            cursor: pointer !important;
            display: flex !important;
            align-items: center !important;
            justify-content: center !important;
        }}
        [data-testid="stNumberInput"] button:hover,
        [data-testid="stNumberInputStepDown"]:hover,
        [data-testid="stNumberInputStepUp"]:hover {{
            background: #D5E8F5 !important;
            color: {GREEN} !important;
        }}
        [data-testid="stNumberInput"] button svg path {{
            fill: {TEXT_DARK} !important;
        }}
        [data-testid="stNumberInput"] button:hover svg path {{
            fill: {GREEN} !important;
        }}

        /* ── Text inputs & Textareas ──────────────────────────────────── */
        textarea,
        input[type="text"],
        input[type="email"],
        input[type="number"],
        input[type="password"] {{
            background: {WHITE} !important;
            color: {TEXT_DARK} !important;
            border: 1.5px solid #C5D5E4 !important;
            border-radius: 10px !important;
        }}
        .stTextInput > div > div > input,
        [data-testid="stTextInput"] input,
        [data-testid="stTextInput"] > div > div > input {{
            background: {WHITE} !important;
            color: {TEXT_DARK} !important;
            border: 1.5px solid #C5D5E4 !important;
            border-radius: 10px !important;
        }}
        .stTextArea textarea,
        .stTextArea > div > div > textarea,
        .stTextArea > div > textarea,
        [data-testid="stTextArea"] textarea,
        [data-testid="stTextArea"] > div textarea,
        [data-testid="stTextArea"] > div > div > textarea {{
            background: {WHITE} !important;
            color: {TEXT_DARK} !important;
            border: 1.5px solid #C5D5E4 !important;
            border-radius: 10px !important;
        }}
        textarea:focus,
        input[type="text"]:focus,
        .stTextInput > div > div > input:focus,
        [data-testid="stTextInput"] input:focus,
        [data-testid="stTextArea"] textarea:focus {{
            border-color: {GREEN} !important;
            box-shadow: 0 0 0 2px {GREEN}30 !important;
            outline: none !important;
        }}
        .stTextInput label p,
        .stTextArea label p,
        [data-testid="stTextInput"] label,
        [data-testid="stTextArea"] label {{
            color: {TEXT_MID} !important;
            font-size: 0.85rem !important;
            font-weight: 600 !important;
        }}

        /* ── Sliders ──────────────────────────────────────────────────── */
        [data-testid="stSlider"] > div {{
            background: transparent !important;
        }}
        [data-testid="stSlider"] [data-baseweb="slider"] div[role="progressbar"],
        [data-testid="stSlider"] [data-baseweb="slider"] > div > div:first-child {{
            background: #D0DFED !important;
            height: 4px !important;
            border-radius: 99px !important;
        }}
        [data-testid="stSlider"] [data-baseweb="slider"] div[role="progressbar"] > div {{
            background: {GREEN} !important;
            border-radius: 99px !important;
        }}
        [data-testid="stSlider"] [data-baseweb="slider"] [role="slider"],
        [data-testid="stSlider"] [data-baseweb="slider"] div[role="slider"] {{
            background: {WHITE} !important;
            border: 3px solid {GREEN} !important;
            box-shadow: 0 2px 8px rgba(0,0,0,0.18) !important;
            width: 20px !important;
            height: 20px !important;
            border-radius: 50% !important;
            top: 50% !important;
            transform: translateY(-50%) !important;
        }}
        [data-testid="stSlider"] [data-testid="stTickBarMin"],
        [data-testid="stSlider"] [data-testid="stTickBarMax"],
        [data-testid="stSlider"] p {{
            color: {TEXT_MID} !important;
            font-size: 0.8rem !important;
        }}

        /* ── Checkboxes ────────────────────────────────────────────────── */
        [data-testid="stCheckbox"],
        [data-testid="stCheckbox"] label,
        [data-testid="stCheckbox"] > label {{
            background: transparent !important;
            border: none !important;
            padding: 0 !important;
            border-radius: 0 !important;
        }}
        [data-testid="stCheckbox"] label span,
        [data-testid="stCheckbox"] label p {{
            color: {TEXT_DARK} !important;
            font-weight: 500 !important;
            background: transparent !important;
        }}
        [data-testid="stCheckbox"] [data-baseweb="checkbox"] span,
        [data-baseweb="checkbox"] span[role="checkbox"] {{
            background: {WHITE} !important;
            border: 2px solid #C5D5E4 !important;
            border-radius: 4px !important;
        }}
        [data-testid="stCheckbox"] [data-baseweb="checkbox"] [data-checked="true"],
        [data-baseweb="checkbox"] [data-checked="true"] span {{
            background: {GREEN} !important;
            border-color: {GREEN} !important;
        }}

        /* ── All buttons — broad catch (sidebar overrides below) ─────── */
        button[kind],
        .stButton > button,
        [data-testid="stButton"] > button,
        [data-testid="baseButton-secondary"],
        [data-testid="baseButton-primary"] {{
            border-radius: 10px !important;
            padding: 0.55rem 1.3rem !important;
            font-weight: 600 !important;
            font-size: 0.9rem !important;
            transition: all 0.15s ease !important;
            cursor: pointer !important;
        }}
        .stButton > button,
        [data-testid="stButton"] > button,
        [data-testid="baseButton-secondary"] {{
            background: {WHITE} !important;
            color: {TEXT_DARK} !important;
            border: 1.5px solid #C5D5E4 !important;
            box-shadow: 0 1px 4px rgba(11,25,41,0.06) !important;
        }}
        .stButton > button:hover,
        [data-testid="baseButton-secondary"]:hover {{
            border-color: {GREEN} !important;
            color: {GREEN} !important;
        }}
        .stButton > button[kind="primary"],
        [data-testid="baseButton-primary"] {{
            background: {GREEN} !important;
            color: {WHITE} !important;
            border: none !important;
            font-weight: 700 !important;
        }}
        .stButton > button[kind="primary"]:hover,
        [data-testid="baseButton-primary"]:hover {{
            background: {GREEN_DIM} !important;
            color: {WHITE} !important;
        }}

        /* Sidebar buttons still transparent */
        section[data-testid="stSidebar"] .stButton > button {{
            background: transparent !important;
            border: none !important;
            color: {WHITE} !important;
            box-shadow: none !important;
        }}

        .stCodeBlock,
        .stCodeBlock pre,
        .stCodeBlock code,
        [data-testid="stCode"],
        [data-testid="stCode"] pre,
        [data-testid="stCode"] code {{
            background: #EDF2F7 !important;
            color: {TEXT_DARK} !important;
            border: 1px solid #D0DFED !important;
            border-radius: 8px !important;
        }}

        /* Inline code inside markdown */
        .stMarkdown code,
        .stMarkdown pre {{
            background: #EDF2F7 !important;
            color: {TEXT_DARK} !important;
            border: 1px solid #D0DFED !important;
            border-radius: 6px !important;
            padding: 0.15em 0.45em !important;
            font-size: 0.88em !important;
        }}
        .stProgress > div > div > div {{
            background: {GREEN} !important;
        }}

        /* ── Alerts ───────────────────────────────────────────────────── */
        .stAlert {{
            border-radius: 10px !important;
        }}

        /* ── Tabs ─────────────────────────────────────────────────────── */
        .stTabs [data-baseweb="tab"] {{
            font-weight: 600;
            color: {TEXT_MID};
        }}
        .stTabs [aria-selected="true"] {{
            color: {GREEN} !important;
            border-bottom: 2px solid {GREEN} !important;
        }}

        /* ── Expander ─────────────────────────────────────────────────── */
        .streamlit-expanderHeader {{
            background: {OFF_WHITE} !important;
            border-radius: 8px !important;
            font-weight: 600;
            color: {TEXT_DARK} !important;
        }}

        /* ── Scrollbar ────────────────────────────────────────────────── */
        ::-webkit-scrollbar {{ width: 6px; height: 6px; }}
        ::-webkit-scrollbar-track {{ background: transparent; }}
        ::-webkit-scrollbar-thumb {{
            background: #C5D5E4;
            border-radius: 99px;
        }}
        ::-webkit-scrollbar-thumb:hover {{ background: {GREEN}; }}

        /* ── Hide Streamlit branding ──────────────────────────────────── */
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
    """Render a label + green-accented value (e.g. 'System Status ACTIVE MONITORING')."""
    st.markdown(
        f'<span style="color:#4A5D6E;font-size:0.9rem;">{label} </span>'
        f'<span class="veridion-active">{value}</span>',
        unsafe_allow_html=True,
    )