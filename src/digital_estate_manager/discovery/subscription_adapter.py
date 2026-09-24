"""Converts subscription-finder output (`subscriptions.json` dict) into webapp models.

Pure data mapping: this module does not import `subscription_finder`, so it can be
tested without the finder's dependencies.
"""

from typing import Any, Dict, List, Optional, Tuple

from digital_estate_manager.models.schemas import (
    Asset,
    AssetStatus,
    DiscoveryResult,
    SubscriptionAssetInfo,
)
from digital_estate_manager.policies.rules import get_policies_for_service

# finder billing_cycle -> (webapp billing_cycle, factor to convert one charge to a monthly cost)
BILLING_CYCLES: Dict[str, Tuple[str, float]] = {
    "weekly": ("weekly", 52 / 12),
    "biweekly": ("weekly", 26 / 12),
    "monthly": ("monthly", 1.0),
    "quarterly": ("quarterly", 1 / 3),
    "yearly": ("annual", 1 / 12),
}

STATUSES: Dict[str, AssetStatus] = {
    "active": "Active",
    "possibly_cancelled": "Pending Review",
}

CONFIDENCE_SCORES: Dict[str, float] = {"low": 0.4, "medium": 0.7, "high": 0.9}

EVIDENCE_LABELS = {"transaction": "bank transactions", "email": "billing emails"}


class MalformedFinderResult(ValueError):
    """The subscription finder returned something that is not a `subscriptions.json` document."""


def monthly_cost(amount: Optional[float], billing_cycle: str) -> float:
    """Monthly equivalent of one charge on the given finder billing cycle."""
    if amount is None:
        return 0.0
    _, factor = BILLING_CYCLES[billing_cycle]
    return round(float(amount) * factor, 2)


def _service_name(inferred: Dict[str, Any]) -> str:
    """The finder only names services found in billing emails; transaction-only findings get
    a label from the service type (bank descriptions are often generic, e.g. 'monthly plan')."""
    if inferred.get("name"):
        return str(inferred["name"]).strip()
    service_type = inferred.get("service_type") or "other"
    label = "Unidentified subscription" if service_type == "other" else f"{service_type.capitalize()} subscription"
    # Include the price so two unnamed subscriptions don't share a dedup key.
    amount = inferred.get("amount")
    price = " ".join(p for p in (f"{amount:.2f}" if amount is not None else "", inferred.get("currency") or "") if p)
    return f"{label} ({price})" if price else label


def _notes(sub: Dict[str, Any], evidence_types: Dict[str, str]) -> str:
    inferred = sub["inferred"]
    observed = sub.get("observed") or {}
    lines = [f"Detected automatically by the subscription finder (confidence: {sub.get('confidence', 'unknown')})."]
    if sub.get("explanation"):
        lines.append(str(sub["explanation"]))
    if sub.get("confidence_reasons"):
        lines.append("Why: " + "; ".join(str(r) for r in sub["confidence_reasons"]) + ".")

    dates = observed.get("charge_dates") or []
    kinds = sorted({EVIDENCE_LABELS.get(evidence_types.get(e, ""), "") for e in sub.get("evidence_ids", [])} - {""})
    if dates:
        span = dates[0] if len(dates) == 1 else f"{dates[0]} to {dates[-1]}"
        source = f" from {' and '.join(kinds)}" if kinds else ""
        lines.append(f"Evidence: {len(dates)} charge(s) {span}{source}.")

    if inferred.get("status") == "possibly_cancelled":
        lines.append(
            f"Possibly cancelled: no charge since {inferred.get('last_charge_date') or 'unknown'} "
            f"(expected around {inferred.get('next_expected_date') or 'unknown'})."
        )
    return "\n".join(lines)


def subscription_to_asset(sub: Dict[str, Any], evidence_types: Optional[Dict[str, str]] = None) -> Asset:
    """Converts one finder subscription into an `Asset`. Raises KeyError/TypeError/ValueError if malformed."""
    inferred = sub["inferred"]
    finder_cycle = inferred["billing_cycle"]
    if finder_cycle not in BILLING_CYCLES:
        raise ValueError(f"unknown billing cycle {finder_cycle!r}")
    billing_cycle, _ = BILLING_CYCLES[finder_cycle]

    service = _service_name(inferred)
    service_address = str(inferred.get("url") or "").strip()
    death_policy, cancel_policy = get_policies_for_service(service, service_address or None)
    if inferred.get("cancel_url"):
        cancel_policy.target_url = inferred["cancel_url"]

    info_kwargs: Dict[str, Any] = {
        "cost_monthly": monthly_cost(inferred.get("amount"), finder_cycle),
        "billing_cycle": billing_cycle,
        "renewal_date": inferred.get("next_expected_date"),
        "payment_method_hint": inferred.get("payment_method"),
    }
    if inferred.get("currency"):
        info_kwargs["currency"] = str(inferred["currency"]).upper()

    return Asset(
        service=service,
        service_address=service_address,
        username=str(inferred.get("account_email") or "").strip(),
        death_policy=death_policy,
        cancel_policy=cancel_policy,
        asset_info=SubscriptionAssetInfo(**info_kwargs),
        status=STATUSES.get(inferred.get("status"), "Pending Review"),
        notes=_notes(sub, evidence_types or {}),
        user_verified=False,
    )


def to_discovery_result(result: Dict[str, Any], source_name: str = "Subscription finder") -> DiscoveryResult:
    """Converts a full `detect_subscriptions()` result into a `DiscoveryResult`.

    Malformed individual subscriptions are skipped and reported in `notes`; a result
    without a `subscriptions` list raises `MalformedFinderResult`.
    """
    if not isinstance(result, dict) or not isinstance(result.get("subscriptions"), list):
        raise MalformedFinderResult("subscription finder result has no 'subscriptions' list")

    evidence_types = {
        e["evidence_id"]: e.get("type", "")
        for e in result.get("evidence") or []
        if isinstance(e, dict) and "evidence_id" in e
    }

    assets: List[Asset] = []
    scores: List[float] = []
    skipped = 0
    for sub in result["subscriptions"]:
        try:
            assets.append(subscription_to_asset(sub, evidence_types))
        except (KeyError, TypeError, ValueError):
            skipped += 1
            continue
        scores.append(CONFIDENCE_SCORES.get(sub.get("confidence"), CONFIDENCE_SCORES["low"]))

    warnings = list((result.get("run") or {}).get("warnings") or [])
    if skipped:
        warnings.append(f"{skipped} malformed subscription(s) skipped")
    notes = f"Found {len(assets)} paid subscription(s)."
    if warnings:
        notes += " Warnings: " + "; ".join(warnings)

    extra: Dict[str, Any] = {}
    if scores:
        extra["confidence_score"] = round(sum(scores) / len(scores), 2)

    return DiscoveryResult(
        source_name=source_name,
        extracted_assets=assets,
        detected_recurring_monthly_drain=round(
            sum(a.cost_monthly or 0.0 for a in assets if a.status == "Active"), 2
        ),
        notes=notes,
        **extra,
    )
