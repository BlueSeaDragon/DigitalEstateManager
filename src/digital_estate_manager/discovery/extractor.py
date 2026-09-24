"""AI Asset Discovery & Extraction Module.

Runs the subscription finder on a connected Gmail account and/or an uploaded
transaction file and converts its findings into webapp `Asset` models.
"""

import io
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from digital_estate_manager.discovery.subscription_adapter import to_discovery_result
from digital_estate_manager.models.schemas import DiscoveryResult

# Transaction formats the subscription finder reads (JSON Lines, or a JSON array of rows).
SUPPORTED_TRANSACTION_EXTENSIONS = (".jsonl", ".json")


class DiscoveryInputError(ValueError):
    """Discovery cannot run with the given inputs; the message is safe to show to the user."""


class UnsupportedFileFormat(DiscoveryInputError):
    """The uploaded file is not a transaction format the subscription finder supports."""


def parse_and_extract(
    uploaded_file: Any = None,
    filename: Optional[str] = None,
    *,
    gmail_credentials: Optional[Dict[str, Any]] = None,
    use_llm: bool = True,
    progress: Optional[Callable[[str, float], None]] = None,
) -> DiscoveryResult:
    """Finds paid recurring subscriptions and returns them as a DiscoveryResult.

    Args:
        uploaded_file: Optional file-like object (such as Streamlit's UploadedFile) or raw
            bytes with one person's transactions as JSONL / JSON.
        filename: Optional name of the uploaded file (defaults to `uploaded_file.name`).
        gmail_credentials: Optional credentials dict from `complete_email_connection()`.
        use_llm: Whether the finder may use the LLM (needs SWISSCOM_API_KEY / SWISSCOM_BASE_URL).
        progress: Optional callback `(message, fraction)`.

    Returns:
        DiscoveryResult containing the list of newly identified Asset models.

    Raises:
        DiscoveryInputError / UnsupportedFileFormat: nothing to scan, or an unsupported file.
        subscription_finder.LLMConfigError: `use_llm` is set but the LLM is not configured.
        subscription_finder.ReconnectRequired: the Gmail credentials expired or were revoked.
        MalformedFinderResult: the finder returned an unexpected result.
    """
    fname = filename or getattr(uploaded_file, "name", None) or ("uploaded_statement" if uploaded_file else None)

    if uploaded_file is not None and Path(fname).suffix.lower() not in SUPPORTED_TRANSACTION_EXTENSIONS:
        raise UnsupportedFileFormat(
            "This file format is not supported for subscription discovery yet. "
            "Upload transactions as JSONL or JSON."
        )
    if uploaded_file is None and not gmail_credentials:
        raise DiscoveryInputError("Connect a Gmail account or upload a JSONL transaction file first.")

    try:
        from subscription_finder import GmailSource, detect_subscriptions
        from subscription_finder.auth import credentials_from_dict
    except ImportError as exc:
        raise DiscoveryInputError(
            "The subscription finder is not installed. Run: pip install -e ./subscription_finder"
        ) from exc

    transactions = uploaded_file
    if isinstance(transactions, (bytes, bytearray)):
        transactions = io.BytesIO(transactions)
        transactions.name = fname
    elif transactions is not None and hasattr(transactions, "seek"):
        transactions.seek(0)  # Streamlit reuses the same buffer across reruns

    email_sources = []
    if gmail_credentials:
        # Raises ReconnectRequired if the token cannot be refreshed.
        email_sources.append(GmailSource(credentials_from_dict(gmail_credentials)))

    result = detect_subscriptions(
        email_sources=email_sources,
        transactions=transactions,
        use_llm=use_llm,
        progress=progress,
    )

    sources = (["Gmail"] if email_sources else []) + ([fname] if uploaded_file is not None else [])
    source_name = " + ".join(sources)
    return to_discovery_result(result, source_name=source_name)
