"""Presentation helpers and the read-only hero components (KPI strip, evidence panel).
Hero components are plain HTML and cannot hold buttons: callers place native
actions directly below them."""

from html import escape
from typing import Dict, List, Optional, Sequence, Tuple

import streamlit as st

from digital_estate_manager.models import Asset
from digital_estate_manager.ui.format import chf, date_display, money, pattern, status_tone
from digital_estate_manager.ui.styles import CSS, EXECUTOR_CSS, ONBOARDING_CSS


def _html(markup: str, container=None) -> None:
    (container or st).markdown(markup, unsafe_allow_html=True)


def inject_styles() -> None:
    _html(CSS)


def inject_executor_styles() -> None:
    """Navy sidebar and role band, so the executor view reads as a different screen on camera."""
    _html(EXECUTOR_CSS)


def wordmark(caption: str) -> None:
    _html(
        '<div class="dlv-wordmark">Digital Legacy<br>Manager</div>'
        f'<div class="dlv-wordmark-caption">{escape(caption)}</div>',
        st.sidebar,
    )


def role_banner(name: str, text: str) -> None:
    """Left half of the role band: which view this is, in one line."""
    _html(f'<div class="dlv-role"><span class="dlv-role-name">{escape(name)}</span>'
          f'<span class="dlv-role-text">{escape(text)}</span></div>')


def page_header(title: str, subtitle: Optional[str] = None, eyebrow: Optional[str] = None):
    """Eyebrow label, headline (34/700), at most one muted line, and a right-aligned column for the
    page's primary action. Returns that column."""
    left, right = st.columns([4, 1.6], vertical_alignment="bottom")
    with left:
        if eyebrow:
            _html(f'<div class="dlv-eyebrow">{escape(eyebrow)}</div>')
        st.title(title, anchor=False)
        if subtitle:
            _html(f'<p class="dlv-subtitle">{escape(subtitle)}</p>')
    return right


def section_label(text: str, first: bool = False) -> None:
    """12px uppercase label; opens a new section 40px below the previous one."""
    cls = "dlv-label" if first else "dlv-label dlv-section"
    _html(f'<div class="{cls}">{escape(text)}</div>')


def status_label(text: str, tone: Optional[str] = None) -> str:
    tone = tone or status_tone(text)
    return f'<span class="dlv-status dlv-status--{tone}">{escape(text)}</span>'


def notice(text: str, tone: str = "muted", container=None) -> None:
    """One inline line with a thin coloured rule. Tones: amber, red, green, navy, muted."""
    _html(f'<div class="dlv-notice dlv-notice--{tone}">{escape(text)}</div>', container)


def muted(text: str, container=None) -> None:
    _html(f'<p class="dlv-muted">{escape(text)}</p>', container)


def cell(primary: str, secondary: Optional[str] = None, strong: bool = False) -> None:
    """A list cell: one value, optionally with a muted second line."""
    cls = "dlv-strong" if strong else ""
    extra = f"<small>{escape(secondary)}</small>" if secondary else ""
    _html(f'<div class="dlv-cell"><span class="{cls}">{escape(primary)}</span>{extra}</div>')


def definition_list(items: Dict[str, object], container=None) -> None:
    rows = "".join(
        f"<dt>{escape(str(k))}</dt><dd>{escape(str(v))}</dd>" for k, v in items.items() if v not in (None, "")
    )
    if rows:
        _html(f'<dl class="dlv-dl">{rows}</dl>', container)


def error_with_details(message: str, exc: BaseException) -> None:
    """What happened and what to do, with the raw exception under 'Technical details'."""
    notice(message, "red")
    with st.expander("Technical details"):
        st.code(f"{type(exc).__name__}: {exc}", language=None)


# -----------------------------------------------------------------------------
# Hero components
# -----------------------------------------------------------------------------

def kpi_strip(items: Sequence[Tuple[str, str, bool]]) -> None:
    """A row of figures: (value, label, alert)."""
    cells = "".join(
        f'<div class="dlv-kpi"><div class="dlv-kpi-value{" dlv-kpi-value--alert" if alert else ""}">'
        f'{escape(value)}</div><div class="dlv-kpi-label">{escape(label)}</div></div>'
        for value, label, alert in items
    )
    _html(f'<div class="dlv-kpis">{cells}</div>')


def _sources(asset: Asset) -> str:
    kinds = []
    if any(e.kind == "transaction" for e in asset.evidence):
        kinds.append("Bank transactions")
    if any(e.kind == "email" for e in asset.evidence):
        kinds.append("Billing emails")
    return " and ".join(kinds) or "Not recorded"


def evidence_panel(asset: Asset) -> None:
    """'Why we think so': pattern, sources, date range, last charge and the finder's reasons."""
    dates = [date_display(e.date) for e in asset.evidence]
    facts = {
        "Pattern": pattern(asset),
        "Sources": _sources(asset),
        "Date range": f"{dates[0]} to {dates[-1]}" if len(dates) > 1 else (dates[0] if dates else None),
        "Last charge": dates[-1] if dates else None,
        "Observations": str(len(asset.evidence)) if asset.evidence else None,
    }
    rows = "".join(f"<dt>{escape(k)}</dt><dd>{escape(v)}</dd>" for k, v in facts.items() if v)
    reasons = "".join(f"<li>{escape(r)}</li>" for r in asset.confidence_reasons)
    reasons_html = f'<dl class="dlv-dl"><dt>Reasons</dt><dd><ul>{reasons}</ul></dd></dl>' if reasons else ""
    _html(
        f'<div class="dlv-evidence"><h4>Why we think so</h4><dl class="dlv-dl">{rows}</dl>{reasons_html}</div>'
    )


def evidence_table(asset: Asset) -> None:
    """The matching transactions and emails, for the 'View evidence' expander."""
    rows = [
        {
            "Date": date_display(e.date),
            "Description": e.description,
            "Amount": money(e.amount, e.currency) if e.amount is not None else "",
            "Source": "Email" if e.kind == "email" else "Transaction",
        }
        for e in reversed(asset.evidence)
    ]
    st.dataframe(rows, hide_index=True, width="stretch")


def numbered(items: Sequence[str]) -> None:
    """One ordered list (separate markdown calls would space the items apart)."""
    st.markdown("\n".join(f"{i}. {item}" for i, item in enumerate(items, 1)))


def step_list(steps: List[Tuple[str, str]], container=None) -> None:
    """Vertical scan progress: (text, state) with state in done / current / todo."""
    items = "".join(f'<li class="{state}">{escape(text)}</li>' for text, state in steps)
    _html(f'<ul class="dlv-steps">{items}</ul>', container)


# -----------------------------------------------------------------------------
# Guided onboarding (docs/design/onboarding-demo.md)
# -----------------------------------------------------------------------------

ONBOARDING_STEPS = [
    ("Connect", "Gmail and your bank statement."),
    ("Analyse", "We look for recurring payments and accounts."),
    ("Review", "Everything your heirs need, in one overview."),
]


def inject_onboarding_styles(hide_stale: bool = False) -> None:
    """`hide_stale` hides elements left over from the previous screen while a long run is still going."""
    stale = '<style>[data-testid="stMain"] [data-stale="true"] { display: none; }</style>' if hide_stale else ""
    _html(ONBOARDING_CSS + stale)


def topbar() -> None:
    """Slim bar with the wordmark; replaces the sidebar during onboarding."""
    _html('<div class="dlv-topbar"><span class="dlv-wordmark">Digital Legacy Manager</span></div>')


def hero(title: str, lead: Optional[str] = None, eyebrow: Optional[str] = None, size: str = "xl") -> None:
    """VZ marketing heading: optional eyebrow label, 42px (xl) or 30px (l) title, 21px lead."""
    eyebrow_html = f'<div class="dlv-label">{escape(eyebrow)}</div>' if eyebrow else ""
    lead_html = f'<p class="dlv-lead">{escape(lead)}</p>' if lead else ""
    _html(f'<div class="dlv-hero">{eyebrow_html}<h1 class="dlv-hero-title dlv-hero-title--{size}">'
          f'{escape(title)}</h1>{lead_html}</div>')


def step_rule(current: int) -> None:
    """Connect -> Analyse -> Review; `current` is 1-based, 0 shows a preview with nothing active."""
    steps = []
    for i, (title, text) in enumerate(ONBOARDING_STEPS, start=1):
        state = "todo" if current == 0 else "done" if i < current else "current" if i == current else "todo"
        steps.append(
            f'<div class="dlv-step dlv-step--{state}"><div class="dlv-step-no">{i:02d}</div>'
            f'<div class="dlv-step-title">{title}</div><div class="dlv-step-text">{text}</div></div>'
        )
    preview = " dlv-journey--preview" if current == 0 else ""
    _html(f'<div class="dlv-journey{preview}">{"".join(steps)}</div>')


def _count(value: int) -> str:
    """A number that counts up from 0 (CSS only); the real value stays readable for screen readers."""
    return f'<span class="dlv-count" style="--to:{int(value)}"><span class="dlv-sr">{int(value)}</span></span>'


def reveal(found: int, monthly_chf: float, needs_review: int, items: Sequence[Tuple[str, str]],
           seconds: int) -> None:
    """The magic moment: counted-up totals, the providers with their cost, and a countdown line."""
    francs = round(monthly_chf)
    amount = f"CHF {_count(francs)}" if francs < 1000 else escape(chf(monthly_chf))
    noun = "account and subscription" if found == 1 else "accounts and subscriptions"
    review = (f" {_count(needs_review)} {'needs' if needs_review == 1 else 'need'} your review."
              if needs_review else " All of them look certain.")
    lead = f"Together they cost about <strong>{amount}</strong> a month.{review}" if francs else review.strip()

    names = "".join(
        f'<li style="--i:{i}">{escape(name)}<span>{escape(detail)}</span></li>' for i, (name, detail) in enumerate(items)
    )

    _html(
        '<div class="dlv-hero dlv-reveal"><div class="dlv-label">Your digital footprint</div>'
        f'<h1 class="dlv-hero-title dlv-hero-title--xl">We found {_count(found)} {noun}.</h1>'
        f'<p class="dlv-lead">{lead}</p>'
        f'<ul class="dlv-reveal-grid">{names}</ul>'
        f'<div class="dlv-countdown" style="--secs:{seconds}s" aria-hidden="true"></div></div>'
    )
