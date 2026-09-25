"""Merge signals into one account finding per service, and write them to the output.

A finding states that there is *evidence of a relationship* with a service (an account,
contract or customer relationship). It never claims that the account was accessed.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from ..confidence import LEVELS
from .catalog import ACCOUNT_TYPES, SERVICES_BY_KEY, TYPE_LABELS, TYPE_ORDER
from .signals import KIND_LABELS, STRENGTHS, Signal

STRENGTH_WEIGHT = {"weak": 1, "medium": 2, "strong": 3}
# which strength gives which confidence that the relationship exists
STRENGTH_CONFIDENCE = {"strong": "high", "medium": "medium", "weak": "low"}


@dataclass
class AccountFinding:
    service_key: str
    signals: list[Signal] = field(default_factory=list)
    name: str | None = None
    domain: str | None = None
    account_type: str | None = None  # None until resolved (rules, then LLM)
    classified_by: str | None = None  # "catalog" | "keywords" | "subscription" | "llm"
    llm_reason: str | None = None
    llm_rejected: bool = False  # the AI review judged it is not a service account

    @property
    def strength(self) -> str:
        return max((s.strength for s in self.signals), key=STRENGTHS.index)

    @property
    def kinds(self) -> Counter[str]:
        return Counter(s.kind for s in self.signals)

    @property
    def dated(self) -> list[date]:
        return sorted(s.evidence.date for s in self.signals if s.evidence.date)

    @property
    def subscription_ids(self) -> list[str]:
        return [s.subscription_id for s in self.signals if s.subscription_id]

    @property
    def in_catalog(self) -> bool:
        return self.service_key in SERVICES_BY_KEY

    @property
    def needs_llm(self) -> bool:
        """Unknown type, but the evidence is good enough to be worth a classification call."""
        return self.account_type is None and self.strength != "weak"


def group_signals(signals: list[Signal]) -> list[AccountFinding]:
    by_key: dict[str, AccountFinding] = {}
    for s in signals:
        f = by_key.setdefault(s.service_key, AccountFinding(s.service_key))
        f.signals.append(s)
    for f in by_key.values():
        _resolve(f)
    return list(by_key.values())


def _resolve(f: AccountFinding) -> None:
    service = SERVICES_BY_KEY.get(f.service_key)
    if service:
        f.name, f.domain, f.account_type, f.classified_by = service.name, service.domains[0], service.account_type, "catalog"
        return
    names = Counter(s.service_name for s in f.signals if s.service_name)
    f.name = names.most_common(1)[0][0] if names else None
    f.domain = next((s.domain for s in f.signals if s.domain), None)
    votes: Counter[tuple[str, str]] = Counter()
    for s in f.signals:
        if s.account_type:
            votes[(s.account_type, s.type_source or "keywords")] += STRENGTH_WEIGHT[s.strength]
    if votes:
        (f.account_type, f.classified_by), _ = votes.most_common(1)[0]


def keep(f: AccountFinding, include_unknown_weak: bool = False) -> bool:
    """Newsletters from unknown senders are noise; a known service or better evidence is kept."""
    return f.strength != "weak" or f.in_catalog or include_unknown_weak


def assess(f: AccountFinding) -> tuple[str, list[str]]:
    level = STRENGTH_CONFIDENCE[f.strength]
    reasons = [f"{f.strength} evidence: {_kinds_text(f)}"]
    if f.strength == "weak":
        reasons.append("only newsletters or marketing, which do not prove that an account exists")
    if f.subscription_ids:
        reasons.append(f"linked to detected subscription(s) {', '.join(f.subscription_ids)}")
    if f.llm_rejected:
        level = "low"
        reasons.append(f"AI review: probably not an online service account ({f.llm_reason or 'no reason given'})")
    if f.classified_by == "llm":
        reasons.append(f"account type classified by AI: {f.llm_reason or 'no reason given'}")
    elif f.classified_by == "keywords":
        reasons.append("account type inferred from email wording")
    elif f.account_type is None:
        reasons.append("account type could not be determined")
    return level, reasons


def _kinds_text(f: AccountFinding) -> str:
    """e.g. 'security/login email (2), statement (1)', strongest kinds first."""
    weight = {k: max(STRENGTH_WEIGHT[s.strength] for s in f.signals if s.kind == k) for k in f.kinds}
    ordered = sorted(f.kinds.items(), key=lambda kv: (-weight[kv[0]], -kv[1], kv[0]))
    return ", ".join(f"{KIND_LABELS.get(k, k)} ({n})" for k, n in ordered)


def explanation(f: AccountFinding) -> str:
    label = TYPE_LABELS.get(f.account_type or "other", "online account")
    who = f.name or (f"an unnamed service (subscription {f.subscription_ids[0]})" if f.subscription_ids else "an unnamed service")
    dates = f.dated
    span = ""
    if dates:
        span = f" on {dates[0].isoformat()}" if dates[0] == dates[-1] else f" between {dates[0].isoformat()} and {dates[-1].isoformat()}"
    parts = [f"Evidence of a {label} with {who}: {_kinds_text(f)}{span}."]
    latest = next((s for s in sorted(f.signals, key=lambda s: s.evidence.date or date.min, reverse=True)
                   if s.evidence.type == "email"), None)
    if latest:
        parts.append(f"Latest email: '{latest.evidence.observed['subject'][:80]}'.")
    parts.append("This indicates a relationship with the service; the account itself was not accessed.")
    return " ".join(parts)


def _rank(s: Signal) -> tuple:
    return (-STRENGTH_WEIGHT[s.strength], -(s.evidence.date or date.min).toordinal())


def add_accounts(
    result: dict[str, Any],
    findings: list[AccountFinding],
    account_email: str | None = None,
    max_evidence: int = 10,
) -> dict[str, Any]:
    """Append `accounts` to a `subscriptions.json` dict, reusing evidence ids for shared records."""
    evidence = result["evidence"]
    by_ref = {(e["source"], e["source_ref"]): e for e in evidence}
    counter = len(evidence)
    accounts = []
    for f in findings:
        ids: list[str] = []
        records = [s for s in sorted(f.signals, key=_rank) if s.kind != "subscription"]
        for s in records[:max_evidence]:
            ref = (s.evidence.source, s.evidence.source_ref)
            record = by_ref.get(ref)
            if record is None:
                counter += 1
                record = s.evidence.to_dict()
                record["evidence_id"] = f"ev-{counter:04d}"
                evidence.append(record)
                by_ref[ref] = record
            record.setdefault("signal", {"kind": s.kind, "strength": s.strength, "rule": s.rule})
            if record["evidence_id"] not in ids:
                ids.append(record["evidence_id"])
        confidence, reasons = assess(f)
        dates = f.dated
        account_type = f.account_type or "other"
        has_email = any(s.evidence.type == "email" for s in f.signals)
        accounts.append({
            "service": {"key": f.service_key, "name": f.name, "domain": f.domain},
            "account_type": account_type,
            "account_type_label": TYPE_LABELS[account_type],
            "estate_relevance": list(ACCOUNT_TYPES[account_type]),
            "classified_by": f.classified_by,
            "evidence_ids": ids,
            "subscription_ids": f.subscription_ids,
            "observed": {
                "first_seen": dates[0].isoformat() if dates else None,
                "last_seen": dates[-1].isoformat() if dates else None,
                "evidence_count": len(f.signals),
                "evidence_kinds": dict(f.kinds.most_common()),
                "email_senders": sorted({s.evidence.observed["sender"] for s in f.signals if s.evidence.type == "email"})[:5],
                "evidence_omitted": max(0, len(records) - max_evidence),
            },
            "account_email": account_email if has_email else None,
            "evidence_strength": f.strength,
            "confidence": confidence,
            "confidence_reasons": reasons,
            "explanation": explanation(f),
        })
    accounts.sort(key=lambda a: (
        -LEVELS.index(a["confidence"]),
        TYPE_ORDER[a["account_type"]],
        -(date.fromisoformat(a["observed"]["last_seen"]).toordinal() if a["observed"]["last_seen"] else 0),
    ))
    result["accounts"] = [{"account_id": f"acc-{i:04d}", **a} for i, a in enumerate(accounts, start=1)]
    return result
