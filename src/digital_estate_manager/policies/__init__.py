from digital_estate_manager.policies.generator import generate_action_email
from digital_estate_manager.policies.rules import (
    KNOWN_CANCEL_POLICIES,
    KNOWN_DEATH_POLICIES,
    get_policies_for_service,
    lookup_policy,
)

# Backwards compatibility alias
KNOWN_POLICIES = KNOWN_DEATH_POLICIES

__all__ = [
    "KNOWN_CANCEL_POLICIES",
    "KNOWN_DEATH_POLICIES",
    "KNOWN_POLICIES",
    "get_policies_for_service",
    "lookup_policy",
    "generate_action_email",
]
