"""Find paid recurring subscriptions in one person's email and transaction history."""

from .config import TOOL_VERSION as __version__
from .llm.client import LLMConfigError, LLMError
from .pipeline import detect_subscriptions
from .sources.email_base import EmailSource, ReconnectRequired
from .sources.gmail import GmailSource

__all__ = [
    "EmailSource",
    "GmailSource",
    "LLMConfigError",
    "LLMError",
    "ReconnectRequired",
    "__version__",
    "detect_subscriptions",
]
