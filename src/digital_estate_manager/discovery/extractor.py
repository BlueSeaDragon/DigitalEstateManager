"""AI Asset Discovery & Extraction Module.

Main hook for Teammate 2:
Implement bank statement, invoice, and email archive parsers here.
"""

from typing import Any, List, Optional
from digital_estate_manager.models.schemas import (
    Asset,
    CloudStorageAssetInfo,
    DiscoveryResult,
    SubscriptionAssetInfo,
)
from digital_estate_manager.policies.rules import get_policies_for_service


def parse_and_extract(
    uploaded_file: Any,
    filename: Optional[str] = None,
) -> DiscoveryResult:
    """Parses an uploaded bank statement or email export and extracts recurring subscriptions

    and digital accounts.

    Args:
        uploaded_file: A file-like object (such as Streamlit's UploadedFile) or raw bytes.
        filename: Optional name of the uploaded file.

    Returns:
        DiscoveryResult containing the list of newly identified Asset models.
    """
    fname = filename or getattr(uploaded_file, "name", "uploaded_statement")

    # =========================================================================
    # TEAMMATE 2 HOOK:
    # Replace this placeholder logic with your document parser / OCR / LLM call.
    # (e.g. PyPDF / pdfplumber + OpenAI / Anthropic / Gemini function calling)
    # =========================================================================

    netflix_death, netflix_cancel = get_policies_for_service("Netflix", "https://netflix.com")
    gh_death, gh_cancel = get_policies_for_service("GitHub", "https://github.com")
    gh_cancel.action_name = "Transfer & Archive"
    gh_cancel.action_type = "transfer_and_archive"
    aws_death, aws_cancel = get_policies_for_service("AWS", "https://aws.amazon.com")
    aws_cancel.action_name = "Transfer & Archive"
    aws_cancel.action_type = "transfer_and_archive"

    # Default prototype discovery items
    discovered = [
        Asset(
            service="Netflix",
            service_address="https://netflix.com",
            username="user.streaming@gmail.com",
            death_policy=netflix_death,
            cancel_policy=netflix_cancel,
            asset_info=SubscriptionAssetInfo(
                cost_monthly=15.49,
                plan_tier="Standard with Ads",
                billing_cycle="monthly",
            ),
            heir="Unassigned",
            status="Pending Review",
            notes=f"Auto-detected from {fname}",
        ),
        Asset(
            service="GitHub Pro",
            service_address="https://github.com",
            username="octocat_dev",
            death_policy=gh_death,
            cancel_policy=gh_cancel,
            asset_info=SubscriptionAssetInfo(
                cost_monthly=4.00,
                plan_tier="Developer Pro",
                billing_cycle="monthly",
            ),
            heir="Unassigned",
            status="Pending Review",
            notes=f"Recurring developer charge found in {fname}",
        ),
        Asset(
            service="AWS Cloud Services",
            service_address="https://aws.amazon.com",
            username="cloud-admin@domain.com",
            death_policy=aws_death,
            cancel_policy=aws_cancel,
            asset_info=CloudStorageAssetInfo(
                storage_capacity_gb=500.0,
                used_storage_gb=180.5,
                contains_sensitive_data=True,
                data_types=["S3 Buckets", "Database Backups"],
            ),
            heir="Unassigned",
            status="Pending Review",
            notes=f"Infrastructure bill found in {fname}",
        ),
    ]

    total_drain = sum(a.cost_monthly for a in discovered if a.cost_monthly)

    return DiscoveryResult(
        source_name=fname,
        extracted_assets=discovered,
        confidence_score=0.92,
        detected_recurring_monthly_drain=total_drain,
        notes=f"Successfully extracted {len(discovered)} potential digital assets from {fname}.",
    )
