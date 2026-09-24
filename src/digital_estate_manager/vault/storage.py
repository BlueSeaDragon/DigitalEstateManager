"""Storage and Estate Metrics Helper."""

from typing import Any, Dict, List
from digital_estate_manager.models.schemas import Asset


def get_default_assets() -> List[Asset]:
    """Returns baseline starter assets for new sessions or demo mode."""
    return [
        Asset(
            service="Spotify",
            service_address="https://spotify.com",
            address="alex.personal@gmail.com",
            category="Subscription",
            cost_monthly=10.99,
            cost_display="$10.99/mo",
            heir="Alex",
            action="Cancel",
            status="Active",
            notes="Personal Spotify Premium account",
        ),
        Asset(
            service="Spotify",
            service_address="https://spotify.com",
            address="family.plan@gmail.com",
            category="Subscription",
            cost_monthly=16.99,
            cost_display="$16.99/mo",
            heir="Jordan",
            action="Cancel",
            status="Active",
            notes="Shared Spotify Family account",
        ),
        Asset(
            service="Google Drive",
            service_address="https://drive.google.com",
            address="jordan.backup@gmail.com",
            category="Cloud Storage",
            cost_monthly=2.99,
            cost_display="$2.99/mo",
            heir="Jordan",
            action="Transfer & Archive",
            status="Active",
            notes="100GB Google One storage plan",
        ),
        Asset(
            service="Coinbase",
            service_address="https://coinbase.com",
            address="alex.crypto@gmail.com",
            category="Crypto / Finance",
            cost_monthly=None,
            cost_display="N/A",
            heir="Alex",
            action="Probate Recovery",
            status="Active",
            notes="Hardware 2FA active on personal device",
        ),
    ]


def calculate_metrics(assets: List[Asset]) -> Dict[str, Any]:
    """Computes estate overview statistics."""
    total_services = len(assets)
    # Distinct providers (by service + service_address)
    unique_providers = len({f"{a.service.lower()}|{a.service_address.lower()}" for a in assets})
    monthly_drain = sum(a.cost_monthly for a in assets if a.cost_monthly and a.action == "Cancel")
    critical_recoveries = [a for a in assets if a.category == "Crypto / Finance" or a.action == "Probate Recovery"]

    return {
        "total_services": total_services,
        "unique_providers": unique_providers,
        "monthly_drain_prevented": f"${monthly_drain:.2f}" if monthly_drain > 0 else "$0.00",
        "critical_recovery_count": len(critical_recoveries),
        "critical_services_summary": f"{len(critical_recoveries)} ({', '.join(a.service for a in critical_recoveries)})"
        if critical_recoveries
        else "0",
    }
