"""The app's CSS. Colours, fonts and radii live in .streamlit/config.toml; this file only covers
what the theme cannot express. Keep it small: `data-testid` selectors can break on Streamlit upgrades."""

INK = "#191919"
MUTED = "#666666"
RULE = "#E5E5E5"
SURFACE = "#F5F5F7"
NAVY = "#004388"
ORANGE = "#D6521C"
GREEN = "#4E924A"
AMBER = "#B7791F"
RED = "#B42318"

CSS = f"""
<style>
/* ---- Page frame: content capped at ~1200px, left-aligned ---- */
[data-testid="stMainBlockContainer"] {{
    max-width: 1200px !important;
    margin-left: 0 !important;
    margin-right: auto !important;
    padding: 40px 48px !important;
}}
/* Tabular figures only where numbers line up; on body text Inter spaces hyphens oddly. */
.dlv-kpi-value, .dlv-table td, .dlv-dl dd, .dlv-cell {{ font-variant-numeric: tabular-nums; }}
[data-testid="stDecoration"] {{ display: none; }}
[data-testid="stHeader"] {{ background: transparent; }}

/* ---- Buttons: tertiary = navy text link ---- */
[data-testid="stBaseButton-tertiary"] {{ color: {NAVY}; padding-left: 0; padding-right: 0; }}
[data-testid="stBaseButton-tertiary"]:hover {{ color: {NAVY}; text-decoration: underline; }}
[data-testid="stBaseButton-secondary"], [data-testid="stBaseLinkButton-secondary"] {{ background: #FFFFFF; }}
button, a[data-testid^="stBaseLinkButton"] {{ box-shadow: none !important; }}

/* ---- Sidebar: wordmark, navigation with an orange active marker ---- */
[data-testid="stSidebarContent"] {{ padding-top: 8px; }}
.dlv-wordmark {{ font-size: 18px; font-weight: 700; color: {INK}; line-height: 1.2; }}
.dlv-wordmark-caption {{ font-size: 13px; color: {MUTED}; margin-top: 2px; }}
.st-key-active_page [role="radiogroup"] {{ gap: 0; }}
.st-key-active_page [role="radiogroup"] > label {{
    width: 100%;
    margin: 0;
    padding: 8px 12px;
    border-left: 2px solid transparent;
    border-radius: 0;
}}
.st-key-active_page [role="radiogroup"] > label > div:first-child {{ display: none; }}
.st-key-active_page [role="radiogroup"] > label p {{ font-size: 15px; color: {MUTED}; }}
.st-key-active_page [role="radiogroup"] > label:has(input:checked) {{ border-left-color: {ORANGE}; background: #FFFFFF; }}
.st-key-active_page [role="radiogroup"] > label:has(input:checked) p {{ color: {INK}; font-weight: 600; }}
.st-key-view_as_block {{ margin-top: 40px; padding-top: 16px; border-top: 1px solid {RULE}; }}

/* ---- Text helpers ---- */
.dlv-subtitle {{ color: {MUTED}; margin: -4px 0 16px 0; font-size: 15px; }}
.dlv-label {{
    font-size: 12px; font-weight: 600; letter-spacing: 0.06em; text-transform: uppercase;
    color: {MUTED}; margin: 0 0 8px 0;
}}
.dlv-section {{ margin-top: 40px; }}
.dlv-muted {{ color: {MUTED}; }}
.dlv-steps-md ol {{ margin: 0 0 8px 0; }}
.dlv-strong {{ font-weight: 600; color: {INK}; }}
.dlv-cell {{ line-height: 1.35; margin: 0; }}
[class*="st-key-row_"] [data-testid="stMarkdownContainer"] p {{ margin: 0; }}
[class*="st-key-row_"] [data-testid="stElementContainer"] {{ margin: 0; }}
.dlv-cell small {{ display: block; color: {MUTED} !important; font-size: 13px; }}
/* Markdown auto-links email addresses; in lists and facts they are plain text. */
.dlv-cell a, .dlv-dl a {{ color: inherit !important; text-decoration: none; }}

/* ---- Status labels: text plus a thin left rule, never filled ---- */
.dlv-status {{ display: inline-block; padding: 0 0 0 8px; border-left: 2px solid {MUTED};
    font-size: 13px; font-weight: 600; line-height: 1.4; color: {MUTED}; white-space: nowrap; }}
.dlv-status--green {{ border-color: {GREEN}; color: {GREEN}; }}
.dlv-status--amber {{ border-color: {AMBER}; color: {AMBER}; }}
.dlv-status--red {{ border-color: {RED}; color: {RED}; }}

/* ---- Inline notices (errors, warnings) ---- */
.dlv-notice {{ border-left: 2px solid {MUTED}; padding: 4px 0 4px 12px; margin: 8px 0 16px 0; color: {INK}; }}
.dlv-notice--amber {{ border-color: {AMBER}; }}
.dlv-notice--red {{ border-color: {RED}; }}
.dlv-notice--green {{ border-color: {GREEN}; }}
.dlv-notice--navy {{ border-color: {NAVY}; }}

/* ---- Definition lists ---- */
.dlv-dl {{ display: grid; grid-template-columns: minmax(140px, max-content) 1fr; gap: 6px 24px; margin: 0 0 16px 0; }}
.dlv-dl dt {{ color: {MUTED}; font-size: 13px; }}
.dlv-dl dd {{ margin: 0; color: {INK}; overflow-wrap: anywhere; }}

/* ---- Asset list rows ---- */
.st-key-list_head {{ border-bottom: 1px solid {RULE}; padding-bottom: 4px; }}
[class*="st-key-row_"] {{ border-bottom: 1px solid {RULE}; padding: 8px 0; }}
[class*="st-key-details_"] {{ background: {SURFACE}; padding: 16px 24px; margin-bottom: 8px; border-radius: 4px; }}

/* ---- Hero: KPI strip ---- */
.dlv-kpis {{ display: grid; grid-template-columns: repeat(4, 1fr); border: 1px solid {RULE}; border-radius: 4px; margin: 24px 0 8px 0; }}
.dlv-kpi {{ padding: 24px; border-left: 1px solid {RULE}; }}
.dlv-kpi:first-child {{ border-left: none; }}
.dlv-kpi-value {{ font-size: 28px; font-weight: 700; color: {INK}; line-height: 1.2; }}
.dlv-kpi-value--alert {{ color: {RED}; }}
.dlv-kpi-label {{ font-size: 13px; color: {MUTED}; margin-top: 4px; }}

/* ---- Hero: journey strip ---- */
.dlv-journey {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 0; margin: 16px 0 8px 0; }}
.dlv-step {{ padding: 16px 24px 16px 0; border-top: 2px solid {RULE}; margin-right: 16px; }}
.dlv-step--done {{ border-top-color: {NAVY}; }}
.dlv-step--current {{ border-top-color: {ORANGE}; }}
.dlv-step-no {{ font-size: 12px; font-weight: 600; letter-spacing: 0.06em; text-transform: uppercase; color: {MUTED}; }}
.dlv-step-title {{ font-size: 15px; font-weight: 600; color: {INK}; margin-top: 4px; }}
.dlv-step--todo .dlv-step-title {{ color: {MUTED}; }}
.dlv-step-text {{ font-size: 13px; color: {MUTED}; margin-top: 2px; }}

/* ---- Hero: evidence panel ---- */
.dlv-evidence {{ background: #FFFFFF; border: 1px solid {RULE}; border-radius: 4px; padding: 16px 24px; margin: 0 0 8px 0; }}
.dlv-evidence h4 {{ font-size: 15px; font-weight: 600; margin: 0 0 12px 0; padding: 0; }}
.dlv-evidence ul {{ margin: 4px 0 0 0; padding-left: 18px; color: {INK}; }}
.dlv-evidence li {{ margin: 2px 0; }}

/* ---- Category list (Overview) ---- */
.dlv-table {{ width: 100%; border-collapse: collapse; margin: 0 0 8px 0; }}
.dlv-table th, .dlv-table td {{ border: none; }}
.dlv-table tr {{ border: none; background: transparent !important; }}
.dlv-table th {{ text-align: left; background: transparent; font-size: 12px; font-weight: 600; letter-spacing: 0.06em; text-transform: uppercase;
    color: {MUTED}; padding: 8px 16px 8px 0; border-bottom: 1px solid {RULE}; }}
.dlv-table td {{ padding: 10px 16px 10px 0; border-bottom: 1px solid {RULE}; color: {INK}; }}
.dlv-table .num {{ text-align: right; }}

/* ---- Scan step list ---- */
.dlv-steps {{ list-style: none; margin: 8px 0 16px 0; padding: 0; }}
.dlv-steps li {{ position: relative; padding: 4px 0 4px 24px; color: {MUTED}; }}
.dlv-steps li::before {{ content: ""; position: absolute; left: 2px; top: 11px; width: 8px; height: 8px;
    border-radius: 50%; border: 2px solid {RULE}; background: #FFFFFF; }}
.dlv-steps li.done {{ color: {INK}; }}
.dlv-steps li.done::before {{ background: {NAVY}; border-color: {NAVY}; }}
.dlv-steps li.current {{ color: {INK}; font-weight: 600; }}
.dlv-steps li.current::before {{ border-color: {ORANGE}; }}

/* ---- Bordered source panels, expanders, dialogs ---- */
[data-testid="stExpander"] details {{ border-color: {RULE}; }}
[data-testid="stExpander"] summary p {{ font-weight: 600; }}
[data-testid="stDialog"] [data-testid="stHeading"] h2 {{ font-size: 18px; }}

/* Dialog columns stretch to equal height so fields stay aligned when labels wrap. */
div[data-testid="stDialog"] div[data-testid="stHorizontalBlock"] {{ align-items: stretch !important; }}
div[data-testid="stDialog"] [data-testid="stColumn"] {{ display: flex !important; flex-direction: column !important; }}
div[data-testid="stDialog"] [data-testid="stColumn"] > div {{
    display: flex !important; flex-direction: column !important; flex: 1 1 auto !important; height: 100% !important;
}}
div[data-testid="stDialog"] [data-testid="stColumn"] div[data-testid="stTextInput"],
div[data-testid="stDialog"] [data-testid="stColumn"] div[data-testid="stSelectbox"],
div[data-testid="stDialog"] [data-testid="stColumn"] div[data-testid="stNumberInput"],
div[data-testid="stDialog"] [data-testid="stColumn"] div[data-testid="stMultiSelect"] {{
    display: flex !important; flex-direction: column !important; flex: 1 1 auto !important;
    justify-content: flex-end !important; height: 100% !important;
}}
</style>
"""
