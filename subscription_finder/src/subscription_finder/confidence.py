"""Rule-based confidence. The LLM only contributes reasons and disagreement."""

from __future__ import annotations

from .config import SUBSCRIPTION_MCCS, Settings
from .models import Candidate

LEVELS = ("low", "medium", "high")


def assess(c: Candidate, settings: Settings) -> tuple[str, list[str]]:
    n = len(c.charges)
    reasons = [
        f"{n} charges on a {c.cycle.name} cycle (median interval {c.median_interval:.0f} days, "
        f"timing variation {c.interval_cv:.0%})"
    ]
    if c.missed_periods:
        reasons.append(f"{c.missed_periods} missed period(s) tolerated")
    typical_mccs = [m for m in c.mccs if m in SUBSCRIPTION_MCCS]

    level = "medium"
    if c.kind == "merged":
        level = "high"
        reasons.append("confirmed by both bank transactions and billing emails")
    if n >= settings.high_confidence_min_charges and c.interval_cv < settings.high_confidence_cv and typical_mccs:
        level = "high"
        reasons.append(
            f"very regular timing and subscription-typical merchant category (MCC {typical_mccs[0]})"
        )
    if level == "medium":
        reasons.append("meets the recurring-charge threshold")

    if n <= 2:
        level = "low"
        reasons.append("only 2 charges observed")
    if c.llm_is_subscription is False:
        level = "low"
        reasons.append("the AI review judged this is probably not a subscription")
    if c.llm_failed:
        level = LEVELS[max(0, LEVELS.index(level) - 1)]
        reasons.append("LLM interpretation unavailable")
    if c.refunds:
        reasons.append(f"{len(c.refunds)} refund(s) matched to charges")
    if c.duplicates:
        reasons.append(f"{len(c.duplicates)} same-day duplicate charge(s) ignored")
    reasons.extend(f"AI review: {r}" for r in c.llm_reasons)
    return level, reasons
