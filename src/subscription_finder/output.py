"""Build the `subscriptions.json` document: run info, evidence, subscriptions."""

from __future__ import annotations

import json
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from .config import TOOL_VERSION, Settings
from .confidence import LEVELS, assess
from .models import Candidate, Evidence, RunInfo

STATUS_ORDER = {"active": 0, "possibly_cancelled": 1}


def _iso(value: Any) -> Any:
    return value.isoformat() if isinstance(value, date) else value


def _payment_method(c: Candidate) -> str | None:
    types = Counter(e.observed.get("transaction_type") for e in c.charges if e.type == "transaction")
    if not types:
        return None
    kind = types.most_common(1)[0][0]
    return {"card_payment": "card", "transfer": "bank transfer"}.get(kind, kind)


def _subscription(c: Candidate, ids: dict[int, str], account_email: str | None, settings: Settings) -> dict[str, Any]:
    confidence, reasons = assess(c, settings)
    t = c.timeline
    charges = c.all_charges
    return {
        "evidence_ids": [ids[id(e)] for e in charges + c.refunds],
        "observed": {
            "charge_dates": [e.date.isoformat() for e in charges],
            "amounts": [e.amount for e in charges],
            "currency": c.currency,
            "descriptions": c.descriptions,
            "mccs": c.mccs,
            "email_senders": sorted({e.observed["sender"] for e in charges if e.type == "email"}),
            "refunds": [
                {"date": r.date.isoformat(), "amount": r.amount, "evidence_id": ids[id(r)]} for r in c.refunds
            ],
        },
        "inferred": {
            "category": c.category,
            "service_type": c.service_type,
            "name": c.name,
            "url": c.url,
            "cancel_url": c.cancel_url,
            "amount": c.typical_amount,
            "currency": c.currency,
            "billing_cycle": c.cycle.name,
            "recurrence_pattern": t["recurrence_pattern"],
            "first_seen_date": _iso(t["first_seen_date"]),
            "last_charge_date": _iso(t["last_charge_date"]),
            "next_expected_date": _iso(t["next_expected_date"]),
            "status": t["status"],
            "account_email": account_email if c.has_email else None,
            "payment_method": _payment_method(c),
        },
        "explanation": c.explanation,
        "confidence": confidence,
        "confidence_reasons": reasons,
    }


def build_output(
    candidates: list[Candidate],
    run: RunInfo,
    settings: Settings,
    account_email: str | None = None,
) -> dict[str, Any]:
    """Only evidence referenced by a subscription is included (counts are in `run`)."""
    ids: dict[int, str] = {}
    evidence: list[Evidence] = []
    for c in candidates:
        for e in c.all_charges + c.refunds:
            if id(e) not in ids:
                ids[id(e)] = f"ev-{len(ids) + 1:04d}"
                evidence.append(e)

    subscriptions = [_subscription(c, ids, account_email, settings) for c in candidates]
    subscriptions.sort(
        key=lambda s: (
            STATUS_ORDER.get(s["inferred"]["status"], 2),
            -LEVELS.index(s["confidence"]),
            -(s["inferred"]["amount"] or 0),
        )
    )
    for i, s in enumerate(subscriptions, start=1):
        s["subscription_id"] = f"sub-{i:04d}"
    subscriptions = [{"subscription_id": s.pop("subscription_id"), **s} for s in subscriptions]

    evidence_dicts = []
    for e in evidence:
        d = e.to_dict()
        d["evidence_id"] = ids[id(e)]
        evidence_dicts.append(d)

    return {
        "run": {
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "tool_version": TOOL_VERSION,
            "model": run.model,
            "reference_date": run.reference_date.isoformat(),
            "sources_scanned": {"email": run.email_sources, "transactions": run.transaction_sources},
            "llm_usage": run.llm_usage,
            "warnings": run.warnings,
        },
        "evidence": evidence_dicts,
        "subscriptions": subscriptions,
    }


def write_output(result: dict[str, Any], path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return path
