"""Storage and Estate Metrics Helper."""

from typing import Any, Dict, List
from digital_estate_manager.models.schemas import (
    Asset,
    CloudStorageAssetInfo,
    FinancialAssetInfo,
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
            asset_info=CloudStorageAssetInfo(
                storage_capacity_gb=100.0,
                used_storage_gb=42.3,
                contains_sensitive_data=True,
                data_types=["Tax Documents", "Family Photos", "Legal Contracts"],
            ),
            heir="Jordan",
            status="Active",
            notes="100GB Google One storage plan",
        ),
        Asset(
            service="Coinbase",
            service_address="https://coinbase.com",
            username="alex.crypto@gmail.com",
            death_policy=cb_death,
            cancel_policy=cb_cancel,
            asset_info=FinancialAssetInfo(
                institution_type="crypto_exchange",
                approximate_balance=12450.00,
                is_custodial=True,
                requires_probate=True,
                account_number_hint="Vault-ETH/BTC",
            ),
            heir="Alex",
            status="Active",
            notes="Hardware 2FA active on personal device",
        ),
    ]


def calculate_metrics(assets: List[Asset]) -> Dict[str, Any]:
    """Computes estate overview statistics."""
    total_services = len(assets)
    unique_providers = len({f"{a.service.lower()}|{a.service_address.lower()}" for a in assets})
    monthly_drain = sum(
        a.cost_monthly for a in assets
        if a.cost_monthly and ("cancel" in a.cancel_policy.action_name.lower() or a.cancel_policy.action_type == "cancel_subscription")
    )
    critical_recoveries = [
        a for a in assets
        if isinstance(a.asset_info, FinancialAssetInfo)
        or a.death_policy.requires_probate
        or a.cancel_policy.action_type == "probate_recovery"
    ]

    return {
        "total_services": total_services,
        "unique_providers": unique_providers,
        "monthly_drain_prevented": f"${monthly_drain:.2f}" if monthly_drain > 0 else "$0.00",
        "critical_recovery_count": len(critical_recoveries),
        "critical_services_summary": f"{len(critical_recoveries)} ({', '.join(a.service for a in critical_recoveries)})"
        if critical_recoveries
        else "0",
    }
