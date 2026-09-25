"""Turn fetched emails into billing evidence (Apertus extraction, heuristic fallback)."""

from __future__ import annotations

import logging
import re
from typing import Any, Callable

from ..llm.client import LLMClient, LLMError
from ..llm.prompts import EXTRACT_SYSTEM, extract_user
from ..models import EmailMessage, Evidence

log = logging.getLogger(__name__)

CURRENCY_SYMBOLS = {"€": "EUR", "$": "USD", "£": "GBP", "fr.": "CHF", "sfr": "CHF"}
_CODE = r"CHF|EUR|USD|GBP|Fr\.|SFr|€|\$|£"
_NUM = r"\d{1,5}(?:[.,']\d{3})*(?:[.,]\d{1,2})?"
AMOUNT_BEFORE = re.compile(rf"({_CODE})\s?({_NUM})", re.I)
AMOUNT_AFTER = re.compile(rf"({_NUM})\s?({_CODE})\b", re.I)
BILLING_WORDS = re.compile(
    r"receipt|invoice|renew|subscription|your plan|membership|billing|payment|charged|"
    r"abo|rechnung|quittung|zahlung|facture|abonnement|paiement",
    re.I,
)
# Advertising names prices too; only a clear receipt/invoice wording outweighs these.
AD_WORDS = re.compile(
    r"\d+\s?% off|\boffers?\b|\bdeals?\b|\benjoy\b|discount|\bsave\b|upgrade|\btry\b|free trial|limited time|"
    r"don't miss|unlock|grow your|angebot|rabatt|sparen|jetzt testen|offre|promo",
    re.I,
)
RECEIPT_WORDS = re.compile(
    r"receipt|invoice|you were charged|payment (received|confirmation|successful)|your bill|order number|"
    r"quittung|rechnung|zahlungsbestätigung|facture|reçu",
    re.I,
)
CYCLE_WORDS = {
    "yearly": re.compile(r"annual|yearly|per year|/\s?y(ea)?r|jährlich|annuel", re.I),
    "monthly": re.compile(r"monthly|per month|/\s?mo(nth)?|monatlich|mensuel", re.I),
    "quarterly": re.compile(r"quarterly|vierteljährlich|trimestriel", re.I),
    "weekly": re.compile(r"weekly|per week|wöchentlich|hebdomadaire", re.I),
}
CYCLES = ("weekly", "monthly", "quarterly", "yearly")


def _to_number(text: str) -> float | None:
    text = text.replace("'", "")
    if "," in text and "." in text:
        text = text.replace(",", "") if text.rfind(".") > text.rfind(",") else text.replace(".", "").replace(",", ".")
    elif "," in text:
        head, _, tail = text.rpartition(",")
        text = f"{head.replace(',', '')}.{tail}" if len(tail) <= 2 else text.replace(",", "")
    try:
        return float(text)
    except ValueError:
        return None


def _currency(token: str) -> str:
    return CURRENCY_SYMBOLS.get(token.lower(), token.upper())


def heuristic_extract(msg: EmailMessage) -> dict[str, Any]:
    """Rules-only extraction used with --no-llm or when the LLM fails."""
    text = f"{msg.subject}\n{msg.body}"
    amount = currency = None
    match = AMOUNT_BEFORE.search(text)
    if match:
        currency, amount = _currency(match.group(1)), _to_number(match.group(2))
    else:
        match = AMOUNT_AFTER.search(text)
        if match:
            amount, currency = _to_number(match.group(1)), _currency(match.group(2))
    cycle = next((name for name, rx in CYCLE_WORDS.items() if rx.search(text)), None)
    display_name = msg.sender.split("<", 1)[0].strip().strip('"') or None
    return {
        "is_billing_email": bool(BILLING_WORDS.search(text))
        and amount is not None
        and not (AD_WORDS.search(text) and not RECEIPT_WORDS.search(text)),
        "merchant": display_name,
        "amount": amount,
        "currency": currency,
        "billing_cycle_hint": cycle,
        "date": msg.date.isoformat(),
    }


def _validate(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict) or "is_billing_email" not in data:
        raise ValueError("expected an object with is_billing_email")
    out = {
        "is_billing_email": bool(data.get("is_billing_email")),
        "merchant": (str(data["merchant"]).strip() or None) if data.get("merchant") else None,
        "amount": None,
        "currency": str(data["currency"]).upper()[:3] if data.get("currency") else None,
        "billing_cycle_hint": data.get("billing_cycle_hint") if data.get("billing_cycle_hint") in CYCLES else None,
        "date": data.get("date"),
    }
    if data.get("amount") not in (None, ""):
        amount = data["amount"] if isinstance(data["amount"], (int, float)) else _to_number(str(data["amount"]))
        out["amount"] = abs(float(amount)) if amount is not None else None
    return out


def extract_emails(
    messages: list[EmailMessage],
    source: str,
    llm: LLMClient | None,
    snippet_chars: int = 200,
    progress: Callable[[str, float], None] | None = None,
) -> tuple[list[Evidence], dict[str, int]]:
    """Return evidence for billing emails only, plus counters (no content)."""
    evidence: list[Evidence] = []
    counts = {"billing": 0, "not_billing": 0, "llm_failures": 0}
    for i, msg in enumerate(messages):
        if progress and i % 10 == 0:
            progress(f"Interpreting emails ({i}/{len(messages)})", i / max(len(messages), 1))
        facts = None
        if llm is not None:
            try:
                facts = llm.complete_json(
                    EXTRACT_SYSTEM,
                    extract_user(msg.sender, msg.subject, msg.date.isoformat(), msg.body),
                    max_tokens=200,
                    validate=_validate,
                )
            except LLMError:
                counts["llm_failures"] += 1
        if facts is None:
            facts = heuristic_extract(msg)
        if not facts["is_billing_email"]:
            counts["not_billing"] += 1
            continue
        counts["billing"] += 1
        # The message date is authoritative for recurrence; the extracted date is informational.
        evidence.append(
            Evidence(
                evidence_id=f"em-{msg.message_id}",
                type="email",
                source=source,
                source_ref=f"msg:{msg.message_id}",
                date=msg.date,
                amount=facts["amount"],
                currency=facts["currency"],
                observed={
                    "date": msg.date.isoformat(),
                    "sender": msg.sender,
                    "sender_domain": msg.sender_domain,
                    "subject": msg.subject,
                    "snippet": (msg.snippet or msg.body)[:snippet_chars],
                    "amount": facts["amount"],
                    "currency": facts["currency"],
                    "merchant": facts["merchant"],
                    "billing_cycle_hint": facts["billing_cycle_hint"],
                    "account_links": msg.account_links,
                },
            )
        )
    log.info("emails: %d billing, %d not billing, %d LLM failures", counts["billing"], counts["not_billing"], counts["llm_failures"])
    return evidence, counts

