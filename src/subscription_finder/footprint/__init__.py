"""Digital-footprint detection: evidence that a person has accounts or contracts with services.

Signals (one per email, bank row or detected subscription) are classified by rules, merged
per service into account findings, and only ambiguous services are sent to the LLM.
"""

from .accounts import AccountFinding, add_accounts, group_signals
from .catalog import ACCOUNT_TYPES, SERVICES
from .signals import Signal, email_signals, subscription_signals, transaction_signals

__all__ = [
    "ACCOUNT_TYPES",
    "SERVICES",
    "AccountFinding",
    "Signal",
    "add_accounts",
    "email_signals",
    "group_signals",
    "subscription_signals",
    "transaction_signals",
]
