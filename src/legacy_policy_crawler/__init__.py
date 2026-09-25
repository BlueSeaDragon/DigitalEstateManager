"""Legacy account/subscription policy crawler (Apertus 1.5 70B).

    from legacy_policy_crawler import lookup_legacy_policy
    record = lookup_legacy_policy("www.google.com")

The result of every lookup is saved in data/legacy_policies.json.
"""

__all__ = ["lookup_legacy_policy"]


def lookup_legacy_policy(website, refresh=False, path=None, trace=None):
    """The record for a company website (website, legacy_policy_url, summary, tick_boxes, checked)."""
    # imported here so `python -m legacy_policy_crawler.llm` does not import llm twice
    from .agent import lookup_legacy_policy as _lookup

    return _lookup(website, refresh=refresh, path=path, trace=trace)
