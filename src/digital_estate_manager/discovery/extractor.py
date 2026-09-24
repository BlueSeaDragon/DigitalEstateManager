"""AI Asset Discovery & Extraction Module.

Main hook for Teammate 2:
Implement bank statement, invoice, and email archive parsers here.
"""

from typing import Any, List, Optional
from digital_estate_manager.models.schemas import Asset, DiscoveryResult


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

    # Default prototype discovery items
    discovered = [
        Asset(
            service="Netflix",
            service_address="https://netflix.com",
            address="user.streaming@gmail.com",
            category="Subscription",
            cost_monthly=15.49,
            cost_display="$15.49/mo",
            heir="Unassigned",
            action="Cancel",
            status="Pending Review",
            notes=f"Auto-detected from {fname}",
        ),
        Asset(
            service="GitHub Pro",
            service_address="https://github.com",
            address="octocat_dev",
            category="Subscription",
            cost_monthly=4.00,
            cost_display="$4.00/mo",
            heir="Unassigned",
            action="Transfer & Archive",
            status="Pending Review",
            notes=f"Recurring developer charge found in {fname}",
        ),
        Asset(
            service="AWS Cloud Services",
            service_address="https://aws.amazon.com",
            address="cloud-admin@domain.com",
            category="Cloud Storage",
            cost_monthly=28.50,
            cost_display="$28.50/mo",
            heir="Unassigned",
            action="Transfer & Archive",
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
