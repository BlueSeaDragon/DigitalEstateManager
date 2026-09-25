"""One Apertus call per person: judge, name, categorize and explain all candidates."""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import urlparse

from ..config import SERVICE_TYPES
from ..detect.paid_subscription import registrable_domain
from ..models import Candidate
from .client import LLMClient, LLMError
from .prompts import INTERPRET_SYSTEM, interpret_user

log = logging.getLogger(__name__)


def candidate_summary(cid: str, c: Candidate) -> dict[str, Any]:
    t = c.timeline
    amounts = [e.amount for e in c.all_charges if e.amount is not None]
    return {
        "id": cid,
        "sources": sorted({e.type for e in c.all_charges}),
        "billing_cycle": c.cycle.name,
        "latest_amount": c.typical_amount,
        "amount_range": [min(amounts), max(amounts)] if amounts else None,
        "currency": c.currency,
        "charges": len(c.charges),
        "first_seen": t["first_seen_date"].isoformat(),
        "last_charge": t["last_charge_date"].isoformat(),
        "status": t["status"],
        "transaction_descriptions": c.descriptions[:5],
        "mccs": c.mccs[:3],
        "email_sender_domains": c.sender_domains[:3],
        "email_merchant_names": c.email_merchants[:3],
        "email_subjects": [e.observed["subject"] for e in c.all_charges if e.type == "email"][:3],
        "links_found_in_emails": account_links(c),
        "rule_based_service_type": c.service_type,
    }


def account_links(c: Candidate) -> list[str]:
    links: list[str] = []
    for e in c.all_charges:
        for link in e.observed.get("account_links") or []:
            if link not in links:
                links.append(link)
    return links[:5]


def _same_link(a: str, b: str) -> bool:
    def norm(u: str) -> str:
        u = u.strip().split("?", 1)[0].split("#", 1)[0].rstrip("/").lower()
        return re.sub(r"^https?://(www\.)?", "", u)

    return norm(a) == norm(b)


def _host_domain(url: str | None) -> str | None:
    if not url:
        return None
    host = urlparse(url if "://" in url else f"https://{url}").hostname
    return registrable_domain(host) if host else None


def apply_guardrail(c: Candidate, name: Any, url: Any, cancel_url: Any) -> tuple[str | None, str | None, str | None]:
    """Keep name/url only when backed by an email sender domain, and cancel_url only
    when it is one of the links found verbatim in the emails (never an invented path)."""
    domains = {registrable_domain(d) for d in c.sender_domains if d}
    if not domains:
        return None, None, None
    name = str(name).strip() or None if name else None
    url = str(url) if url and _host_domain(str(url)) in domains else None
    links = account_links(c)
    cancel_url = next((link for link in links if cancel_url and _same_link(str(cancel_url), link)), None)
    return name, url, cancel_url


def _validator(ids: set[str]):
    def validate(data: Any) -> dict[str, dict[str, Any]]:
        items = data.get("candidates") if isinstance(data, dict) else data
        if not isinstance(items, list):
            raise ValueError("expected {'candidates': [...]}")
        by_id = {str(item.get("id")): item for item in items if isinstance(item, dict)}
        missing = ids - set(by_id)
        if missing:
            raise ValueError(f"missing candidates: {sorted(missing)}")
        for item in by_id.values():
            if not isinstance(item.get("is_subscription"), bool):
                raise ValueError("is_subscription must be true or false")
        return by_id

    return validate


def interpret(candidates: list[Candidate], llm: LLMClient) -> bool:
    """Mutate candidates with the LLM's judgement. Returns False on fallback to rules only."""
    if not candidates:
        return True
    ids = {f"c{i}": c for i, c in enumerate(candidates, start=1)}
    summaries = [candidate_summary(cid, c) for cid, c in ids.items()]
    try:
        answers = llm.complete_json(
            INTERPRET_SYSTEM, interpret_user(summaries), max_tokens=250 * len(ids) + 200, validate=_validator(set(ids))
        )
    except LLMError:
        log.warning("LLM interpretation failed; using rules only")
        for c in candidates:
            c.llm_failed = True
        return False
    for cid, c in ids.items():
        answer = answers[cid]
        c.llm_used = True
        c.llm_is_subscription = answer["is_subscription"]
        service = answer.get("service_type")
        if service in SERVICE_TYPES and service != "other":
            c.service_type = service
        name, url, cancel_url = apply_guardrail(c, answer.get("name"), answer.get("url"), answer.get("cancel_url"))
        c.name = name or c.name
        c.url = url or c.url
        c.cancel_url = cancel_url
        if isinstance(answer.get("explanation"), str) and answer["explanation"].strip():
            c.explanation = answer["explanation"].strip()
        reasons = answer.get("llm_reasons") or []
        c.llm_reasons = [str(r) for r in reasons if r][:5] if isinstance(reasons, list) else []
    return True
