"""Storage and Estate Metrics Helper."""

from typing import Any, Dict, List

from digital_estate_manager.currency import chf, to_chf
from digital_estate_manager.models.schemas import (
    Asset,
    CancelPolicy,
    CloudStorageAssetInfo,
    DeathPolicy,
    FinancialAssetInfo,
    SocialMediaAssetInfo,
    SubscriptionAssetInfo,
)
from digital_estate_manager.policies.rules import get_policies_for_service


def get_default_assets() -> List[Asset]:
    """Returns baseline starter assets for new sessions or demo mode."""
    spot_death, spot_cancel = get_policies_for_service("Spotify", "https://spotify.com")
    spot_death2, spot_cancel2 = get_policies_for_service("Spotify", "https://spotify.com")
    g_death, g_cancel = get_policies_for_service("Google Drive", "https://drive.google.com")
    cb_death, cb_cancel = get_policies_for_service("Coinbase", "https://coinbase.com")

    return [
        Asset(
            service="Spotify",
            service_address="https://spotify.com",
            username="alex.personal@gmail.com",
            death_policy=spot_death,
            cancel_policy=spot_cancel,
            asset_info=SubscriptionAssetInfo(
                currency="CHF",
                cost_monthly=10.99,
                plan_tier="Premium Individual",
                billing_cycle="monthly",
                renewal_date="2026-10-01",
                payment_method_hint="Visa ending 4242",
            ),
            heir="Alex",
            status="Active",
            notes="Personal Spotify Premium account",
        ),
        Asset(
            service="Spotify",
            service_address="https://spotify.com",
            username="family.plan@gmail.com",
            death_policy=spot_death2,
            cancel_policy=spot_cancel2,
            asset_info=SubscriptionAssetInfo(
                currency="CHF",
                cost_monthly=16.99,
                plan_tier="Premium Family",
                billing_cycle="monthly",
                renewal_date="2026-10-15",
                payment_method_hint="Mastercard ending 9811",
            ),
            heir="Jordan",
            status="Active",
            notes="Shared Spotify Family plan",
        ),
        Asset(
            service="Google Drive",
            service_address="https://drive.google.com",
            username="jordan.backup@gmail.com",
            death_policy=g_death,
            cancel_policy=g_cancel,
            asset_infos=[
                CloudStorageAssetInfo(
                    storage_capacity_gb=100.0,
                    used_storage_gb=42.3,
                    contains_sensitive_data=True,
                    data_types=["Tax Documents", "Family Photos", "Legal Contracts"],
                ),
                SubscriptionAssetInfo(
                    currency="CHF",
                    cost_monthly=1.99,
                    plan_tier="Google One 100 GB Plan",
                    billing_cycle="monthly",
                    renewal_date="2026-10-12",
                    payment_method_hint="Google Pay (Mastercard ending 9811)",
                ),
            ],
            heir="Jordan",
            status="Active",
            notes="100GB Google One storage plan & active recurring subscription",
        ),
        Asset(
            service="Coinbase",
            service_address="https://coinbase.com",
            username="alex.crypto@gmail.com",
            death_policy=cb_death,
            cancel_policy=cb_cancel,
            asset_infos=[
                FinancialAssetInfo(
                    currency="CHF",
                    institution_type="crypto_exchange",
                    approximate_balance=12450.00,
                    is_custodial=True,
                    requires_probate=True,
                    account_number_hint="Vault-ETH/BTC",
                ),
                SubscriptionAssetInfo(
                    currency="CHF",
                    cost_monthly=29.99,
                    plan_tier="Coinbase One (Zero-Fee Trading)",
                    billing_cycle="monthly",
                    renewal_date="2026-10-20",
                    payment_method_hint="Visa ending 4242",
                ),
            ],
            heir="Alex",
            status="Active",
            notes="Crypto exchange wallet with active Coinbase One membership",
        ),
        Asset(
            service="LinkedIn",
            service_address="https://linkedin.com",
            username="alex.professional@linkedin.com",
            death_policy=DeathPolicy(
                summary="LinkedIn allows accounts to be memorialized or closed upon submission of executor verification and death certificate.",
                supports_legacy_contact=False,
                official_portal_url="https://www.linkedin.com/help/linkedin/answer/a1340639",
            ),
            cancel_policy=CancelPolicy(
                action_name="Memorialize Profile",
                action_type="memorialize",
                execution_method="web_portal",
                target_url="https://www.linkedin.com/help/linkedin/answer/a1340639",
                steps=[
                    "Visit LinkedIn Deceased Member Request form",
                    "Provide link to member profile",
                    "Attach death certificate or obituary link",
                    "Choose whether to memorialize or delete the account",
                ],
            ),
            asset_infos=[
                SocialMediaAssetInfo(
                    profile_url="https://linkedin.com/in/alex-legacy",
                    platform_handle="alex-legacy",
                    memorialization_supported=True,
                    has_legacy_contact_set=False,
                ),
                SubscriptionAssetInfo(
                    currency="CHF",
                    cost_monthly=39.99,
                    plan_tier="Premium Career",
                    billing_cycle="monthly",
                    renewal_date="2026-11-01",
                    payment_method_hint="American Express ending 1002",
                ),
            ],
            heir="Jordan",
            status="Active",
            notes="Professional profile and active Premium Career subscription",
        ),
    ]


def monthly_cost_chf(asset: Asset) -> float:
    """Monthly recurring cost in CHF (approx.), converting each subscription from its own currency.

    Amounts in currencies missing from the FX table are left out.
    """
    total = 0.0
    for info in asset.asset_infos:
        converted = to_chf(info.get_monthly_cost(), getattr(info, "currency", None))
        if converted:
            total += converted
    return round(total, 2)


def calculate_metrics(assets: List[Asset]) -> Dict[str, Any]:
    """Computes estate overview statistics."""
    # Active accounts (excluding cancelled, removed, and wrongly attributed)
    active_services = [a for a in assets if a.status not in ["Cancelled", "Removed", "Wrongly Attributed"]]
    cancelled_services = [a for a in assets if a.status == "Cancelled"]
    removed_services = [a for a in assets if a.status == "Removed"]
    wrongly_attributed_services = [a for a in assets if a.status == "Wrongly Attributed"]

    valid_estate_assets = [a for a in assets if a.status != "Removed"]
    total_services = len(valid_estate_assets)
    unique_providers = len({f"{a.service.lower()}|{a.service_address.lower()}" for a in valid_estate_assets})

    # Active monthly recurring drain, in CHF (rows can be in different currencies)
    active_monthly_spend = round(sum(monthly_cost_chf(a) for a in active_services), 2)

    # Monthly drain prevented (cancelled items or flagged for cancellation, excluding removed)
    drain_prevented = round(
        sum(
            monthly_cost_chf(a) for a in valid_estate_assets
            if a.status == "Cancelled" or "cancel" in a.cancel_policy.action_name.lower()
        ),
        2,
    )

    critical_recoveries = [
        a for a in valid_estate_assets
        if a.has_type("Crypto / Finance")
        or a.death_policy.requires_probate
        or a.cancel_policy.action_type == "probate_recovery"
    ]

    return {
        "total_services": total_services,
        "unique_providers": unique_providers,
        "active_count": len(active_services),
        "cancelled_count": len(cancelled_services),
        "removed_count": len(removed_services),
        "wrongly_attributed_count": len(wrongly_attributed_services),
        "active_monthly_spend_chf": active_monthly_spend,
        "monthly_drain_prevented_chf": drain_prevented,
        "active_monthly_spend": chf(active_monthly_spend),
        "monthly_drain_prevented": chf(drain_prevented),
        "critical_recovery_count": len(critical_recoveries),
        "critical_services_summary": f"{len(critical_recoveries)} ({', '.join(a.service for a in critical_recoveries)})"
        if critical_recoveries
        else "0",
    }
