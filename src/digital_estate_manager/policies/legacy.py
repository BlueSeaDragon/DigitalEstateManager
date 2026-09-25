"""Bridge between the legacy policy crawler and the app.

Saved crawler records (data/legacy_policy_demo.json) are laid over a DeathPolicy and flagged
as AI-generated.
"""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from legacy_policy_crawler import store
from legacy_policy_crawler.web import normalize_website

from digital_estate_manager.models.schemas import Asset, DeathPolicy

LEGACY_POLICY_FILE = Path(
    os.getenv("LEGACY_POLICY_FILE") or store.ROOT / "data" / "legacy_policy_demo.json"
)

AI_NOTICE = (
    "Machine-generated from the linked page and may contain errors. "
    "Not legal advice: verify at the source before acting."
)
NOT_FOUND_TEXT = (
    "Not found: the AI crawler found no clear legacy policy for this provider."
)
STALE_AFTER_DAYS = 90  # older records are marked "old" and can be refreshed

TICK_LABELS = {
    "owner_can_appoint_successor": "Owner can name a successor",
    "heirs_can_request_access": "Heirs can request access",
    "subscription_or_balance_addressed": "Subscription or balance covered",
    "proof_required": "Proof required",
}


def days_since_checked(
    checked: Optional[str], today: Optional[date] = None
) -> Optional[int]:
    """Days since an ISO date like '2026-09-24', or None if there is no valid date."""
    try:
        return ((today or date.today()) - date.fromisoformat(checked or "")).days
    except ValueError:
        return None


def is_stale(checked: Optional[str], today: Optional[date] = None) -> bool:
    """True if the record was checked more than STALE_AFTER_DAYS ago."""
    days = days_since_checked(checked, today)
    return days is not None and days > STALE_AFTER_DAYS


def provider_key(service_address: Optional[str]) -> str:
    """The provider's website ('drive.google.com'), or '' if the address is not one."""
    host = normalize_website(service_address or "")
    return host if "." in host else ""


def legacy_record(service_address: Optional[str]) -> Optional[Dict[str, Any]]:
    """The saved record for this exact website, or None."""
    host = provider_key(service_address)
    if not host:
        return None
    try:
        return store.get(host, LEGACY_POLICY_FILE)
    except ValueError:  # a broken file must not break the app
        return None


def apply_legacy_record(
    death_policy: DeathPolicy, record: Optional[Dict[str, Any]]
) -> DeathPolicy:
    """A copy of the policy with the crawler's result on top. Hand-written fields are kept."""
    if not record:
        return death_policy
    ticks = dict(record.get("tick_boxes") or {})
    update: Dict[str, Any] = {
        "ai_generated": True,
        "source_checked": record.get("checked"),
        "tick_boxes": ticks,
    }
    url = str(record.get("legacy_policy_url") or "")
    if url.startswith("http"):
        update.update(
            summary=record.get("summary") or NOT_FOUND_TEXT,
            official_portal_url=url,
            policy_found=True,
        )
        if ticks.get("owner_can_appoint_successor") is not None:
            update["supports_legacy_contact"] = ticks["owner_can_appoint_successor"]
    else:  # not found: the existing link stays as a possibly useful one
        update.update(summary=NOT_FOUND_TEXT, policy_found=False)
    return death_policy.model_copy(update=update)


def with_legacy_record(
    death_policy: DeathPolicy, service_address: Optional[str]
) -> DeathPolicy:
    """The policy with this website's saved record applied, if there is one."""
    return apply_legacy_record(death_policy, legacy_record(service_address))


def policy_marks(tick_boxes: Dict[str, Optional[bool]]) -> List[Tuple[str, str]]:
    """(label, mark) per tick box: ✔ yes, ✘ no, – not stated."""
    marks = {True: "✔", False: "✘", None: "–"}
    return [(label, marks[tick_boxes.get(key)]) for key, label in TICK_LABELS.items()]


def policy_table_row(asset: Asset) -> Dict[str, Any]:
    """One row of the owner's legacy-policy table."""
    policy = asset.death_policy
    link = (
        policy.official_portal_url
        or asset.cancel_policy.target_url
        or asset.service_address
    )
    row: Dict[str, Any] = {
        "Service": asset.service,
        "Source": "🤖 AI crawler" if policy.ai_generated else "Hand-written",
        "Summary": policy.summary,
        "Link": link if link and link.startswith("http") else None,
    }
    for label, mark in policy_marks(policy.tick_boxes):
        row[label] = mark
    row["Checked"] = policy.source_checked or ""
    if is_stale(policy.source_checked):
        row["Checked"] += " ⚠️ old"
    return row


def refresh_legacy_policy(service_address: str) -> Optional[str]:
    """Crawl the provider's website now (10-40 s) and save the record.

    Returns None on success, else a short message for the user.
    """
    # imported here so the app starts without loading the crawler's HTTP stack
    from legacy_policy_crawler import lookup_legacy_policy
    from legacy_policy_crawler.llm import AuthError

    try:
        record = lookup_legacy_policy(
            service_address, refresh=True, path=str(LEGACY_POLICY_FILE)
        )
    except AuthError as error:
        return f"Cannot look up policies right now: {error}"
    return None if legacy_record(service_address) else record["summary"]
