"""Core data structures: raw evidence, subscription candidates and run metadata."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from .config import Cycle


@dataclass
class Evidence:
    """One observed fact from a raw source (a transaction row or a billing email)."""

    evidence_id: str
    type: str  # "transaction" | "email"
    source: str
    source_ref: str
    date: date
    amount: float | None
    currency: str | None
    observed: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "type": self.type,
            "source": self.source,
            "source_ref": self.source_ref,
            "observed": self.observed,
        }


@dataclass
class EmailMessage:
    """A fetched email, already trimmed. Never written to output in full."""

    message_id: str
    date: date
    sender: str
    subject: str
    body: str
    snippet: str = ""
    account_links: list[str] = field(default_factory=list)  # cancel/manage links found verbatim

    @property
    def sender_domain(self) -> str:
        address = self.sender.rsplit("<", 1)[-1].rstrip(">").strip()
        return address.rsplit("@", 1)[-1].lower() if "@" in address else ""


@dataclass
class Candidate:
    """A recurring charge series found by the rules, before interpretation."""

    kind: str  # "transaction" | "email" | "merged"
    currency: str | None
    charges: list[Evidence]
    cycle: Cycle
    intervals: list[float]  # per-period intervals (missed periods divided out)
    median_interval: float
    interval_cv: float
    missed_periods: int
    refunds: list[Evidence] = field(default_factory=list)
    duplicates: list[Evidence] = field(default_factory=list)
    email_charges: list[Evidence] = field(default_factory=list)  # set on merged candidates
    category: str = "paid_subscription"
    timeline: dict[str, Any] = field(default_factory=dict)  # dates, status (set by the detector)
    # interpretation (filled by rules and optionally the LLM)
    service_type: str = "other"
    name: str | None = None
    url: str | None = None
    cancel_url: str | None = None
    explanation: str = ""
    llm_used: bool = False
    llm_is_subscription: bool | None = None
    llm_reasons: list[str] = field(default_factory=list)
    llm_failed: bool = False

    @property
    def all_charges(self) -> list[Evidence]:
        return sorted(self.charges + self.email_charges, key=lambda e: e.date)

    @property
    def dates(self) -> list[date]:
        return [e.date for e in self.charges]

    @property
    def amounts(self) -> list[float]:
        return [e.amount for e in self.charges if e.amount is not None]

    @property
    def typical_amount(self) -> float | None:
        """Most recent amount (reflects price changes)."""
        amounts = [e.amount for e in self.all_charges if e.amount is not None]
        return amounts[-1] if amounts else None

    def _observed_values(self, key: str, evidence: list[Evidence] | None = None) -> list[str]:
        values = (e.observed.get(key) for e in (evidence or self.all_charges))
        return [v for v, _ in Counter(v for v in values if v).most_common()]

    @property
    def descriptions(self) -> list[str]:
        return self._observed_values("description")

    @property
    def mccs(self) -> list[str]:
        return self._observed_values("mcc")

    @property
    def sender_domains(self) -> list[str]:
        return self._observed_values("sender_domain")

    @property
    def email_merchants(self) -> list[str]:
        return self._observed_values("merchant")

    @property
    def has_email(self) -> bool:
        return any(e.type == "email" for e in self.all_charges)

    @property
    def has_transactions(self) -> bool:
        return any(e.type == "transaction" for e in self.all_charges)


@dataclass
class RunInfo:
    reference_date: date
    model: str | None
    email_sources: list[dict[str, Any]] = field(default_factory=list)
    transaction_sources: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    llm_usage: dict[str, int] = field(default_factory=dict)
