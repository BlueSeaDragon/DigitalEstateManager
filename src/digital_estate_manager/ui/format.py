"""Display formatting for assets: money, categories, status tones. No Streamlit imports."""

import re
from typing import Dict, Optional

from digital_estate_manager.currency import FX_TO_CHF, chf, money, to_chf
from digital_estate_manager.models import (
    Asset,
    CloudStorageAssetInfo,
    FinancialAssetInfo,
    GenericAssetInfo,
    SocialMediaAssetInfo,
    SubscriptionAssetInfo,
)

__all__ = [
    "FX_TO_CHF",
    "CATEGORY_LABELS",
    "asset_facts",
    "category_label",
    "categories_display",
    "chf",
    "date_display",
    "display_name",
    "monthly_display",
    "money",
    "pattern",
    "status_text",
    "status_tone",
    "subtitle",
    "to_chf",
    "value_display",
]

# Asset type name -> short label used in filters and lists.
CATEGORY_LABELS = {
    "Subscription": "Subscriptions",
    "Crypto / Finance": "Finance",
    "Cloud Storage": "Cloud",
    "Social Media": "Social",
}
DASH = "—"

CYCLE_LABELS = {"monthly": "Monthly", "annual": "Yearly", "quarterly": "Quarterly", "weekly": "Weekly"}

# Status -> tone: green = Confirmed/Active/done, amber = Likely/pending, red = needs review/errors.
TONES = {
    "Confirmed": "green",
    "Active": "green",
    "Completed": "green",
    "Likely": "amber",
    "Pending Review": "amber",
    "In Progress": "amber",
    "Needs review": "red",
    "Wrongly Attributed": "red",
    "Cancelled": "muted",
    "Archived": "muted",
    "Removed": "muted",
}

STATUS_TEXT = {
    "Pending Review": "Pending review",
    "In Progress": "In progress",
    "Wrongly Attributed": "Flagged",
}


def category_label(type_name: str) -> str:
    """'Crypto / Finance' -> 'Finance'; custom 'Other' names map to 'Other'."""
    return CATEGORY_LABELS.get(type_name, "Other")


def categories_display(asset: Asset) -> str:
    """Singular category names for a row, e.g. 'Cloud, Subscription'."""
    singular = {"Subscriptions": "Subscription"}
    labels = []
    for t in asset.types:
        label = singular.get(category_label(t), category_label(t))
        if label not in labels:
            labels.append(label)
    return ", ".join(labels)


def status_tone(label: str) -> str:
    return TONES.get(label, "muted")


def status_text(status: str) -> str:
    return STATUS_TEXT.get(status, status)


def monthly_display(asset: Asset) -> str:
    """Monthly recurring cost in the asset's own currency, or a dash."""
    parts = []
    for info in asset.asset_infos:
        cost = info.get_monthly_cost()
        if cost:
            parts.append(money(cost, getattr(info, "currency", None)))
    return " + ".join(parts) if parts else DASH


def value_display(asset: Asset) -> Optional[str]:
    """Approximate balance of a financial account, if known."""
    info = asset.get_info("Crypto / Finance")
    balance = getattr(info, "approximate_balance", None)
    if balance is None:
        return None
    return money(balance, getattr(info, "currency", None))


def pattern(asset: Asset) -> str:
    """'Monthly · CHF 20.90': billing cycle and the most recent charge amount."""
    info = asset.get_info("Subscription")
    cycle = CYCLE_LABELS.get(getattr(info, "billing_cycle", ""), "Recurring")
    charged = [e for e in asset.evidence if e.amount is not None and e.kind == "transaction"] or [
        e for e in asset.evidence if e.amount is not None
    ]
    if charged:
        last = charged[-1]
        return f"{cycle} · {money(last.amount, last.currency)}"
    if info and info.cost_monthly:
        return f"{cycle} · {money(info.cost_monthly, info.currency)} per month"
    return cycle


def _yes_no(value: bool) -> str:
    return "Yes" if value else "No"


def asset_facts(asset: Asset) -> Dict[str, str]:
    """Known details of all the asset's types as label -> value, formatted for a definition list."""
    facts: Dict[str, str] = {}
    for info in asset.asset_infos:
        if isinstance(info, SubscriptionAssetInfo):
            facts["Plan"] = info.plan_tier or ""
            facts["Billing"] = CYCLE_LABELS.get(info.billing_cycle, info.billing_cycle)
            if info.cost_monthly:
                facts["Cost"] = f"{money(info.cost_monthly, info.currency)} per month"
            facts["Next renewal"] = date_display(info.renewal_date)
            facts["Payment method"] = info.payment_method_hint or ""
        elif isinstance(info, FinancialAssetInfo):
            facts["Institution"] = info.institution_type.replace("_", " ").capitalize()
            if info.approximate_balance is not None:
                facts["Approx. value"] = money(info.approximate_balance, info.currency)
            facts["Custody"] = "Custodial" if info.is_custodial else "Self-custody (private key)"
            facts["Probate required"] = _yes_no(info.requires_probate)
            facts["Account hint"] = info.account_number_hint or ""
        elif isinstance(info, CloudStorageAssetInfo):
            if info.storage_capacity_gb:
                used = f"{info.used_storage_gb:.1f} of " if info.used_storage_gb is not None else ""
                facts["Storage"] = f"{used}{info.storage_capacity_gb:.0f} GB"
            facts["Content"] = ", ".join(info.data_types)
            facts["Sensitive documents"] = _yes_no(info.contains_sensitive_data)
        elif isinstance(info, SocialMediaAssetInfo):
            facts["Profile"] = info.profile_url or ""
            facts["Memorialization"] = "Supported" if info.memorialization_supported else "Closure only"
            facts["Legacy contact"] = "Set" if info.has_legacy_contact_set else "Not set"
        elif isinstance(info, GenericAssetInfo):
            if info.category_name and info.category_name != "Other":
                facts["Category"] = info.category_name
            facts.update({str(k): str(v) for k, v in info.custom_properties.items()})
            if info.notes:
                facts["Description"] = info.notes
    return {k: v for k, v in facts.items() if v}


def date_display(value: Optional[str]) -> str:
    """ISO '2026-10-04' -> Swiss '04.10.2026'; other strings unchanged."""
    if value and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        y, m, d = value.split("-")
        return f"{d}.{m}.{y}"
    return value or ""


# The adapter appends the price to unnamed findings ("Gym subscription (79.00 CHF)") to keep
# their dedup keys apart; lists show the bank description on the second line instead.
_PRICE_SUFFIX = re.compile(r" \(\d+(\.\d+)? ?[A-Z]{0,3}\)$")


def display_name(asset: Asset) -> str:
    return _PRICE_SUFFIX.sub("", asset.service) if asset.evidence else asset.service


def subtitle(asset: Asset) -> Optional[str]:
    """Account identifier, or for detected items without one, the most frequent description."""
    if asset.username:
        return asset.username
    descriptions = [e.description for e in asset.evidence if e.description]
    return max(set(descriptions), key=descriptions.count) if descriptions else None
