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
.dlv-kpi-value, .dlv-dl dd, .dlv-cell {{ font-variant-numeric: tabular-nums; }}
[data-testid="stDecoration"] {{ display: none; }}
[data-testid="stHeader"] {{ background: transparent; }}

/* ---- Buttons: tertiary = navy text link ---- */
[data-testid="stBaseButton-tertiary"] {{ color: {NAVY}; padding-left: 0; padding-right: 0; }}
[data-testid="stBaseButton-tertiary"]:hover {{ color: {NAVY}; text-decoration: underline; }}
[data-testid="stBaseButton-secondary"], [data-testid="stBaseLinkButton-secondary"] {{ background: #FFFFFF; }}
button, a[data-testid^="stBaseLinkButton"] {{ box-shadow: none !important; }}

/* ---- Sidebar: wordmark, navigation with an orange active marker ---- */
[data-testid="stSidebarContent"] {{ padding-top: 8px; }}
/* Wordmark: short orange rule, then the name set large and tight; the same in both roles. */
.dlv-wordmark {{ font-size: 26px; font-weight: 700; color: {INK}; line-height: 1.05; letter-spacing: -0.025em; }}
.dlv-wordmark::before {{ content: ""; display: block; width: 28px; height: 3px; background: {ORANGE}; margin-bottom: 12px; }}
.dlv-wordmark-caption {{ font-size: 13px; color: {MUTED}; margin: 8px 0 28px 0; }}
.st-key-nav [role="radiogroup"] {{ gap: 0; }}
.st-key-nav [role="radiogroup"] > label {{
    width: 100%;
    margin: 0;
    padding: 8px 12px;
    border-left: 2px solid transparent;
    border-radius: 0;
}}
.st-key-nav [role="radiogroup"] > label > div:first-child {{ display: none; }}
.st-key-nav [role="radiogroup"] > label p {{ font-size: 15px; color: {MUTED}; }}
.st-key-nav [role="radiogroup"] > label:has(input:checked) {{ border-left-color: {ORANGE}; background: #FFFFFF; }}
.st-key-nav [role="radiogroup"] > label:has(input:checked) p {{ color: {INK}; font-weight: 600; }}

/* ---- Role band: which view this is, and the switch. Top of every page. ---- */
.st-key-role_bar {{
    background: {SURFACE}; border-left: 3px solid {ORANGE}; border-radius: 4px;
    padding: 10px 12px 10px 20px; margin-bottom: 40px;
}}
.dlv-role {{ display: flex; align-items: baseline; gap: 12px; flex-wrap: wrap; }}
.dlv-role-name {{ font-size: 12px; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase; color: {INK}; }}
.dlv-role-text {{ font-size: 14px; color: {MUTED}; }}
.st-key-role_bar [data-testid="stElementContainer"] {{ margin: 0; }}
.st-key-role_bar [data-testid="stMarkdownContainer"] {{ margin: 0; }}

/* ---- Page header: eyebrow, headline, one muted line ---- */
.dlv-eyebrow {{
    display: flex; align-items: center; gap: 10px; margin: 0 0 10px 0;
    font-size: 12px; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase; color: {ORANGE};
}}
.dlv-eyebrow::before {{ content: ""; width: 24px; height: 2px; background: currentColor; }}
[data-testid="stMain"] h1 {{
    font-size: 34px !important; line-height: 1.15 !important; letter-spacing: -0.02em;
    padding: 0 0 8px 0 !important; text-wrap: balance;
}}
.dlv-subtitle {{ color: {MUTED}; margin: 0 0 8px 0; font-size: 17px; line-height: 1.45; max-width: 640px; }}

/* ---- Text helpers ---- */
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
[class*="st-key-row_"] {{ border-bottom: 1px solid {RULE}; padding: 0; gap: 0; }}
/* Clickable row: the Details button's ::after covers the row head. Everything between the head and the
   button stays unpositioned so the overlay measures against the head, not the button's column. */
[class*="st-key-rowhead_"] {{ position: relative; padding: 8px 0; }}
[class*="st-key-rowhead_"] * {{ position: static; }}
[class*="st-key-rowhead_"] [class*="st-key-toggle_"] button::after {{ content: ""; position: absolute; inset: 0; cursor: pointer; }}
/* Hover tint reaches 12px past the text on both sides without shifting the columns. */
[class*="st-key-rowhead_"]:hover {{ background: {SURFACE}; box-shadow: -12px 0 0 {SURFACE}, 12px 0 0 {SURFACE}; }}
[class*="st-key-rowhead_"]:has(button:focus-visible) {{ outline: 2px solid {NAVY}; outline-offset: -2px; }}
[class*="st-key-details_"] {{ background: {SURFACE}; padding: 16px 24px; margin: 4px 0 8px 0; border-radius: 4px; }}

/* ---- Hero: KPI strip ---- */
.dlv-kpis {{ display: grid; grid-auto-flow: column; grid-auto-columns: 1fr; border: 1px solid {RULE}; border-radius: 4px; margin: 24px 0 8px 0; }}
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

# Executor view: the same layout on navy, so the switch of perspective is visible at a glance.
NAVY_DEEP = "#00346A"
ON_NAVY = "rgba(255, 255, 255, 0.72)"

EXECUTOR_CSS = f"""
<style>
[data-testid="stSidebar"] {{ background: {NAVY} !important; }}
[data-testid="stSidebar"] .dlv-wordmark {{ color: #FFFFFF; }}
[data-testid="stSidebar"] .dlv-wordmark-caption {{ color: {ON_NAVY}; }}
.st-key-nav [role="radiogroup"] > label p {{ color: {ON_NAVY}; }}
.st-key-nav [role="radiogroup"] > label:has(input:checked) {{ background: {NAVY_DEEP}; }}
.st-key-nav [role="radiogroup"] > label:has(input:checked) p {{ color: #FFFFFF; }}
[data-testid="stSidebar"] [data-testid="stSidebarCollapseButton"] svg {{ color: #FFFFFF; }}

.st-key-role_bar {{ background: {NAVY}; }}
.st-key-role_bar .dlv-role-name {{ color: #FFFFFF; }}
.st-key-role_bar .dlv-role-text {{ color: {ON_NAVY}; }}
/* !important: Streamlit styles segmented buttons with a more specific [kind]:not(:disabled) rule. */
.st-key-role_bar button[kind="segmented_control"] {{
    background: transparent !important; border-color: rgba(255, 255, 255, 0.4) !important; color: #FFFFFF !important;
}}
.st-key-role_bar button[kind="segmented_controlActive"] {{
    background: #FFFFFF !important; border-color: #FFFFFF !important; color: {NAVY} !important;
}}
.st-key-role_bar button p {{ color: inherit; }}

.dlv-eyebrow {{ color: {NAVY}; }}
</style>
"""

# Only while the guided onboarding runs (docs/design/onboarding-demo.md). Sizes and the orange button and
# CTA link follow vermoegenszentrum.ch's marketing pages (h1 42px, lead 21px, .button-orange, .cta).
ORANGE_BUTTON = "#C95321"

ONBOARDING_CSS = f"""
<style>
[data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"], [data-testid="stExpandSidebarButton"] {{
    display: none !important;
}}
[data-testid="stMainBlockContainer"] {{ padding-top: 24px !important; margin: 0 auto !important; }}
.dlv-topbar {{ padding: 0 0 20px 0; border-bottom: 1px solid {RULE}; margin-bottom: 64px; }}
.dlv-topbar .dlv-wordmark {{ display: inline-flex; align-items: center; gap: 14px; font-size: 24px; }}
.dlv-topbar .dlv-wordmark::before {{ margin: 0; }}

/* ---- Hero type ---- */
.dlv-hero {{ max-width: 780px; }}
.dlv-hero h1.dlv-hero-title {{ font-weight: 700; color: {INK}; margin: 0 0 12px 0; padding: 0 !important;
    letter-spacing: -0.01em; }}
.dlv-hero h1.dlv-hero-title--xl {{ font-size: 42px !important; line-height: 1.1875; }}
.dlv-hero h1.dlv-hero-title--l {{ font-size: 30px !important; line-height: 1.1875; }}
.dlv-hero p.dlv-lead {{ font-size: 21px !important; line-height: 1.46; color: {MUTED}; margin: 0 0 32px 0; max-width: 720px; }}
.dlv-lead strong {{ color: {INK}; font-weight: 700; }}

/* ---- The step rule: nothing active on the landing, a stepper afterwards ---- */
.dlv-journey--preview {{ margin-top: 80px; }}
.dlv-journey--preview .dlv-step-title {{ color: {INK} !important; }}
.dlv-journey {{ margin-bottom: 48px; }}

/* ---- VZ orange button (one per screen) and CTA link with an orange underline ---- */
.st-key-cta_orange button {{
    background: linear-gradient(180deg, rgba(255, 255, 255, 0.15) 0%, rgba(255, 255, 255, 0) 100%), {ORANGE_BUTTON};
    border: 1px solid {ORANGE_BUTTON}; color: #FFFFFF; padding: 10px 22px; min-height: 44px;
}}
.st-key-cta_orange button:hover {{ background-color: #B5481B; border-color: #B5481B; color: #FFFFFF; }}
.st-key-cta_orange button p, .st-key-cta_link button p {{ font-weight: 700; font-size: 15px; }}
.st-key-cta_link button {{
    color: {INK}; padding: 0 0 2px 0; min-height: 0; border-radius: 0;
    box-shadow: 0 2px 0 0 {ORANGE} !important;
}}
.st-key-cta_link button:hover {{ color: {INK}; text-decoration: none; box-shadow: 0 3px 0 0 {ORANGE} !important; }}

/* ---- Source cards ---- */
.st-key-src_gmail, .st-key-src_statement {{ padding: 24px !important; gap: 8px; }}
.dlv-card-title {{ font-size: 18px; font-weight: 600; color: {INK}; margin: 0; }}

/* ---- Magic moment: count-up, provider grid, countdown line ---- */
@property --dlv-n {{ syntax: "<integer>"; initial-value: 0; inherits: false; }}
.dlv-count {{
    --dlv-n: var(--to); counter-reset: dlv-n var(--dlv-n); font-variant-numeric: tabular-nums;
    animation: dlv-count 1.6s cubic-bezier(0.16, 1, 0.3, 1) 0.2s both;
}}
.dlv-count::after {{ content: counter(dlv-n); content: counter(dlv-n) / ""; }}
@keyframes dlv-count {{ from {{ --dlv-n: 0; }} }}
.dlv-sr {{ position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%); white-space: nowrap; }}

.dlv-reveal {{ max-width: none; }}
.dlv-reveal-grid {{
    display: grid; grid-template-columns: repeat(4, 1fr); gap: 0 32px; list-style: none;
    margin: 8px 0 0 0; padding: 0; border-top: 1px solid {RULE};
}}
.dlv-reveal-grid li {{
    display: flex; justify-content: space-between; gap: 16px; margin: 0; padding: 12px 0;
    border-bottom: 1px solid {RULE}; font-size: 15px; color: {INK};
    opacity: 0; animation: dlv-in 0.45s ease-out forwards; animation-delay: calc(1.2s + var(--i) * 60ms);
}}
.dlv-reveal-grid li span {{ color: {MUTED}; white-space: nowrap; font-variant-numeric: tabular-nums; }}
@keyframes dlv-in {{ from {{ opacity: 0; transform: translateY(6px); }} to {{ opacity: 1; transform: none; }} }}
.dlv-countdown {{ position: relative; height: 2px; background: {RULE}; margin: 40px 0 16px 0; overflow: hidden; }}
.dlv-countdown::after {{
    content: ""; position: absolute; inset: 0; background: {ORANGE}; transform-origin: left center;
    transform: scaleX(0); animation: dlv-fill var(--secs) linear forwards;
}}
@keyframes dlv-fill {{ to {{ transform: scaleX(1); }} }}

@media (prefers-reduced-motion: reduce) {{
    .dlv-count, .dlv-reveal-grid li, .dlv-countdown::after {{ animation: none; }}
    .dlv-reveal-grid li {{ opacity: 1; }}
}}
</style>
"""
