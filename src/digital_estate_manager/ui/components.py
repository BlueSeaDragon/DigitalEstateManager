"""Presentation helpers and the three read-only hero components (KPI strip, evidence panel,
journey strip). Hero components are plain HTML and cannot hold buttons: callers place native
actions directly below them."""

from html import escape
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import streamlit as st

from digital_estate_manager.models import Asset
from digital_estate_manager.ui.format import date_display, money, pattern, status_tone
from digital_estate_manager.ui.styles import CSS


def _html(markup: str, container=None) -> None:
    (container or st).markdown(markup, unsafe_allow_html=True)


def inject_styles() -> None:
    _html(CSS)


def wordmark() -> None:
    _html(
        '<div class="dlv-wordmark">Digital Legacy Vault</div>'
        '<div class="dlv-wordmark-caption">Digital estate overview</div>',
        st.sidebar,
    )


def page_header(title: str, subtitle: Optional[str] = None):
    """Title (28/700), at most one muted line, and a right-aligned column for the page's single
    primary action. Returns that column."""
    left, right = st.columns([4, 1.3], vertical_alignment="bottom")
    with left:
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
    """Four figures: (value, label, alert)."""
    cells = "".join(
        f'<div class="dlv-kpi"><div class="dlv-kpi-value{" dlv-kpi-value--alert" if alert else ""}">'
        f'{escape(value)}</div><div class="dlv-kpi-label">{escape(label)}</div></div>'
        for value, label, alert in items
    )
    _html(f'<div class="dlv-kpis">{cells}</div>')


JOURNEY = [
    ("Inventory", "List every account and subscription."),
    ("Instructions", "Decide what should happen to each one."),
    ("Share", "Hand the plan to your executor."),
]


def journey_strip(current: int) -> None:
    """Inventory -> Instructions -> Share; `current` is the 1-based active step."""
    steps = []
    for i, (title, text) in enumerate(JOURNEY, start=1):
        state = "done" if i < current else "current" if i == current else "todo"
        steps.append(
            f'<div class="dlv-step dlv-step--{state}"><div class="dlv-step-no">Step {i}</div>'
            f'<div class="dlv-step-title">{title}</div><div class="dlv-step-text">{text}</div></div>'
        )
    _html(f'<div class="dlv-journey">{"".join(steps)}</div>')


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


def category_table(rows: Iterable[Tuple[str, int, str]]) -> None:
    """Overview's grouped category list: (category, count, monthly)."""
    body = "".join(
        f'<tr><td>{escape(c)}</td><td class="num">{n}</td><td class="num">{escape(m)}</td></tr>' for c, n, m in rows
    )
    _html(
        '<table class="dlv-table"><thead><tr><th>Category</th><th class="num">Assets</th>'
        f'<th class="num">Per month (approx.)</th></tr></thead><tbody>{body}</tbody></table>'
    )


def numbered(items: Sequence[str]) -> None:
    """One ordered list (separate markdown calls would space the items apart)."""
    st.markdown("\n".join(f"{i}. {item}" for i, item in enumerate(items, 1)))


def step_list(steps: List[Tuple[str, str]], container=None) -> None:
    """Vertical scan progress: (text, state) with state in done / current / todo."""
    items = "".join(f'<li class="{state}">{escape(text)}</li>' for text, state in steps)
    _html(f'<ul class="dlv-steps">{items}</ul>', container)
