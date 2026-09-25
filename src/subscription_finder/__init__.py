"""Find paid recurring subscriptions and the wider digital footprint in one person's email and transactions."""

from .config import TOOL_VERSION as __version__
from .llm.client import LLMConfigError, LLMError
from .pipeline import detect_subscriptions, discover_footprint
from .sources.email_base import EmailSource, ReconnectRequired
from .sources.gmail import BILLING_TERMS, FOOTPRINT_TERMS, GmailSource

__all__ = [
    "BILLING_TERMS",
    "FOOTPRINT_TERMS",
    "EmailSource",
    "GmailSource",
    "LLMConfigError",
    "LLMError",
    "ReconnectRequired",
    "__version__",
    "detect_subscriptions",
    "discover_footprint",
]
