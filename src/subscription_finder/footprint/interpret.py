"""Batched Apertus classification of services the rules could not type.

Only headers-level facts (sender domain, sender names, subjects, evidence kinds) are sent;
email bodies never leave the machine in this step.
"""

from __future__ import annotations

import logging
from typing import Any

from ..llm.client import LLMClient, LLMError
from ..llm.prompts import FOOTPRINT_SYSTEM, footprint_user
from .accounts import AccountFinding
from .catalog import ACCOUNT_TYPES
from .signals import display_name

log = logging.getLogger(__name__)

NOT_A_SERVICE = "not_a_service"


def service_summary(sid: str, f: AccountFinding) -> dict[str, Any]:
    emails = [s.evidence for s in f.signals if s.evidence.type == "email"]
    names = {n for e in emails if (n := display_name(e.observed["sender"]))}
    return {
        "id": sid,
        "sender_domain": f.domain,
        "sender_names": sorted(names)[:3],
        "subjects": [e.observed["subject"][:100] for e in emails][:5],
        "evidence_kinds": sorted(f.kinds),
    }


def _supported_name(name: Any, summary: dict[str, Any]) -> str | None:
    """Keep the LLM's name only if it appears in the sender names, domain or subjects."""
    if not isinstance(name, str) or not name.strip():
        return None
    name = name.strip()[:60]
    haystack = " ".join([summary["sender_domain"] or "", *summary["sender_names"], *summary["subjects"]]).lower()
    return name if name.lower() in haystack else None


def _validator(ids: set[str]):
    allowed = set(ACCOUNT_TYPES) | {NOT_A_SERVICE}

    def validate(data: Any) -> dict[str, dict[str, Any]]:
        items = data.get("services") if isinstance(data, dict) else data
        if not isinstance(items, list):
            raise ValueError("expected {'services': [...]}")
        by_id = {str(i.get("id")): i for i in items if isinstance(i, dict)}
        missing = ids - set(by_id)
        if missing:
            raise ValueError(f"missing services: {sorted(missing)}")
        for item in by_id.values():
            if item.get("account_type") not in allowed:
                raise ValueError(f"account_type must be one of {sorted(allowed)}")
        return by_id

    return validate


def classify_ambiguous(findings: list[AccountFinding], llm: LLMClient, batch_size: int = 40) -> bool:
    """Type the findings that need it (mutates them). Returns False if any batch failed."""
    todo = [f for f in findings if f.needs_llm]
    ok = True
    for start in range(0, len(todo), batch_size):
        batch = {f"s{i}": f for i, f in enumerate(todo[start : start + batch_size], start=1)}
        summaries = {sid: service_summary(sid, f) for sid, f in batch.items()}
        try:
            answers = llm.complete_json(
                FOOTPRINT_SYSTEM,
                footprint_user(list(summaries.values()), list(ACCOUNT_TYPES)),
                max_tokens=80 * len(batch) + 100,
                validate=_validator(set(batch)),
            )
        except LLMError:
            log.warning("footprint classification failed for %d service(s)", len(batch))
            ok = False
            continue
        for sid, f in batch.items():
            answer = answers[sid]
            f.llm_reason = str(answer.get("reason") or "").strip()[:200] or None
            if answer["account_type"] == NOT_A_SERVICE:
                f.llm_rejected = True
                f.account_type, f.classified_by = "other", "llm"
            else:
                f.account_type, f.classified_by = answer["account_type"], "llm"
            f.name = _supported_name(answer.get("name"), summaries[sid]) or f.name
    return ok
