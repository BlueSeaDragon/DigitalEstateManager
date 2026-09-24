"""Load one person's transactions from a JSONL file (path or file-like object)."""

from __future__ import annotations

import io
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import IO, Any

from ..models import Evidence

log = logging.getLogger(__name__)

REQUIRED_FIELDS = ("timestamp", "amount", "currency")
CHARGE_TYPES = frozenset({"card_payment", "transfer"})


def _read_text(source: str | Path | IO) -> tuple[str, str]:
    """Return (text, source name) for a path or a text/binary file-like object."""
    if isinstance(source, (str, Path)):
        path = Path(source)
        return path.read_text(encoding="utf-8"), path.name
    raw = source.read()
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8-sig")
    name = getattr(source, "name", None) or "upload"
    return raw, Path(str(name)).name


def _iter_records(text: str):
    """Yield (line number, record or None) for JSONL, or for a JSON array as fallback."""
    stripped = text.lstrip()
    if stripped.startswith("["):
        try:
            for i, record in enumerate(json.loads(stripped), start=1):
                yield i, record
            return
        except json.JSONDecodeError:
            pass
    for i, line in enumerate(io.StringIO(text), start=1):
        if not line.strip():
            continue
        try:
            yield i, json.loads(line)
        except json.JSONDecodeError:
            yield i, None


def _parse_date(value: Any):
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text).date()


def load_transactions(
    source: str | Path | IO,
    sample_client_id: str | None = None,
) -> tuple[list[Evidence], dict[str, Any]]:
    """Parse transactions into evidence. Malformed rows are skipped and counted.

    `sample_client_id` selects one person from the multi-person sample dataset;
    real uploads contain a single person and need no filter.
    """
    text, name = _read_text(source)
    evidence: list[Evidence] = []
    skipped = 0
    for line_no, record in _iter_records(text):
        if not isinstance(record, dict):
            skipped += 1
            continue
        if sample_client_id is not None and record.get("client_id") != sample_client_id:
            continue
        try:
            if any(record.get(f) in (None, "") for f in REQUIRED_FIELDS):
                raise ValueError("missing field")
            tx_date = _parse_date(record["timestamp"])
            amount = abs(float(record["amount"]))
            currency = str(record["currency"]).upper()
        except (ValueError, TypeError):
            skipped += 1
            continue
        observed = {
            "date": tx_date.isoformat(),
            "amount": amount,
            "currency": currency,
            "merchant": record.get("merchant"),
            "mcc": str(record["mcc"]) if record.get("mcc") not in (None, "") else None,
            "description": record.get("description"),
            "direction": record.get("direction"),
            "transaction_type": record.get("type"),
        }
        evidence.append(
            Evidence(
                evidence_id=f"tx-{line_no}",
                type="transaction",
                source=name,
                source_ref=f"line:{line_no}",
                date=tx_date,
                amount=amount,
                currency=currency,
                observed=observed,
            )
        )
    evidence.sort(key=lambda e: e.date)
    stats = {"source": name, "rows": len(evidence), "skipped": skipped}
    log.info("loaded %d transaction rows (%d skipped)", len(evidence), skipped)
    return evidence, stats


def is_charge(e: Evidence) -> bool:
    return e.observed.get("direction", "out") == "out" and e.observed.get("transaction_type", "card_payment") in CHARGE_TYPES


def is_refund(e: Evidence) -> bool:
    return e.observed.get("transaction_type") == "refund"
