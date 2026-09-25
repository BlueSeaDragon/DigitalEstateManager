"""Signals: one classified piece of evidence that a person has a relationship with a service.

A signal extractor turns records from one source into `Signal`s. Email, bank transaction and
subscription extractors live here; a new source (e.g. uploaded documents) only needs a function
that returns `Signal`s with an `Evidence` record attached. The account layer does the rest.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Any, Iterable, Protocol

from ..detect.paid_subscription import registrable_domain
from ..extract.email_extractor import AD_WORDS, RECEIPT_WORDS
from ..models import EmailMessage, Evidence
from .catalog import (
    SERVICE_TYPE_TO_ACCOUNT,
    is_personal_sender,
    lookup_domain,
    lookup_text,
    type_from_keywords,
)

STRENGTHS = ("weak", "medium", "strong")

# Email kinds, strongest first. Each rule is (kind, strength, pattern on subject + body).
EMAIL_RULES: tuple[tuple[str, str, re.Pattern[str]], ...] = (
    ("security", "strong", re.compile(
        r"new (sign-?in|login|device)|sign-?in (attempt|alert)|login (attempt|alert)|security (alert|notice|code)|"
        r"password (reset|change|was changed)|reset your password|verification code|one-time (code|password)|"
        r"two-(factor|step)|\b2fa\b|neue anmeldung|anmeldung bei|sicherheitswarnung|passwort zurücksetzen|"
        r"nouvelle connexion|code de vérification|mot de passe", re.I)),
    ("account_created", "strong", re.compile(
        r"welcome to|thanks for (signing up|joining|registering)|confirm your (email|account|registration)|"
        r"verify your (email|account)|account (has been )?(created|opened|activated)|activate your account|"
        r"willkommen bei|konto (wurde )?(erstellt|eröffnet)|bestätigen sie ihre e-mail|bienvenue", re.I)),
    ("statement", "strong", re.compile(
        r"(account|monthly|annual|quarterly|portfolio|card) statement|statement (is )?(ready|available)|"
        r"kontoauszug|depotauszug|vermögensausweis|steuerausweis|tax (statement|document|certificate)|"
        r"relevé|annual report|jahresauszug|e-document", re.I)),
    ("invoice", "strong", RECEIPT_WORDS),
    ("contract", "strong", re.compile(
        r"your policy|policy (number|documents?|renewal)|ihre police|policennummer|contract (confirmation|renewal)|"
        r"vertragsbestätigung|ihr vertrag|your contract|premium (notice|invoice)|prämienrechnung|terms of your plan", re.I)),
    ("order", "medium", re.compile(
        r"order confirmation|your order|order number|has shipped|out for delivery|booking confirmation|"
        r"your (booking|reservation|trip|itinerary)|boarding pass|e-ticket|bestellbestätigung|ihre bestellung|"
        r"buchungsbestätigung|votre commande|confirmation de réservation", re.I)),
    ("account_notice", "medium", re.compile(
        r"your account|account (update|settings|activity|notification)|terms of (service|use) (update|change)|"
        r"privacy policy (update|change)|we('re| are) updating our (terms|privacy)|ihr konto|votre compte|"
        r"mentioned you|tagged you|new follower|friend request|sent you a message|shared .* with you", re.I)),
    ("marketing", "weak", re.compile(
        rf"newsletter|unsubscribe|abmelden|se désabonner|{AD_WORDS.pattern}", re.I)),
)
KIND_LABELS = {
    "security": "security/login email", "account_created": "account creation email", "statement": "statement",
    "invoice": "invoice/receipt", "contract": "contract/policy document", "order": "order or booking",
    "account_notice": "account notice", "marketing": "newsletter/marketing", "other": "other email",
    "subscription": "recurring payment", "payment": "bank transaction", "connected_mailbox": "connected mailbox",
}
# Security and sign-up emails often carry one-time codes; never copy them into the output.
_CODE = re.compile(r"\b[0-9]{4,8}\b|\b[A-Z0-9]{3,4}-[A-Z0-9]{3,4}\b")
REDACTED_KINDS = frozenset({"security", "account_created"})


@dataclass
class Signal:
    """One piece of evidence for one service. `account_type` is None when still unknown."""

    evidence: Evidence
    service_key: str
    service_name: str | None
    domain: str | None
    kind: str
    strength: str
    rule: str  # human-readable reason the signal was classified this way
    account_type: str | None = None
    type_source: str | None = None  # "catalog" | "keywords" | "subscription"
    subscription_id: str | None = None
    subscription_confidence: str | None = None
    text: str = ""  # classification text (never written to output)


class SignalExtractor(Protocol):
    """Extension point: turn one source's records into signals."""

    def __call__(self, records: Iterable[Any], source: str) -> list[Signal]: ...


def _address(sender: str) -> str:
    return sender.rsplit("<", 1)[-1].rstrip(">").strip().lower()


def display_name(sender: str) -> str | None:
    name = sender.split("<", 1)[0].strip().strip('"') if "<" in sender else ""
    return name or None


def classify_email(msg: EmailMessage) -> tuple[str, str, str]:
    """(kind, strength, rule) from the subject first (it states the purpose), then the body."""
    for text in (msg.subject, f"{msg.subject}\n{msg.body}"):
        for kind, strength, rx in EMAIL_RULES:
            match = rx.search(text or "")
            if match:
                return kind, strength, f"{KIND_LABELS[kind]}: matched '{match.group(0).strip()[:40]}'"
    return "other", "weak", "no account-related wording"


def email_signals(messages: Iterable[EmailMessage], source: str, snippet_chars: int = 200) -> list[Signal]:
    signals = []
    for msg in messages:
        host = msg.sender_domain
        if not host or is_personal_sender(_address(msg.sender), host):
            continue
        kind, strength, rule = classify_email(msg)
        service = lookup_domain(host)
        text = f"{display_name(msg.sender) or ''}\n{msg.subject}\n{msg.body}"
        snippet = (msg.snippet or msg.body)[:snippet_chars]
        if kind in REDACTED_KINDS:
            snippet = _CODE.sub("[redacted]", snippet)
        domain = registrable_domain(host)
        evidence = Evidence(
            evidence_id=f"em-{msg.message_id}",
            type="email",
            source=source,
            source_ref=f"msg:{msg.message_id}",
            date=msg.date,
            amount=None,
            currency=None,
            observed={
                "date": msg.date.isoformat(),
                "sender": msg.sender,
                "sender_domain": host,
                "subject": _CODE.sub("[redacted]", msg.subject) if kind in REDACTED_KINDS else msg.subject,
                "snippet": snippet,
            },
        )
        if service:
            account_type, type_source = service.account_type, "catalog"
        else:
            account_type = type_from_keywords(text)
            type_source = "keywords" if account_type else None
        signals.append(Signal(
            evidence=evidence,
            service_key=service.key if service else domain,
            service_name=service.name if service else display_name(msg.sender),
            domain=domain,
            kind=kind,
            strength=strength,
            rule=rule,
            account_type=account_type,
            type_source=type_source,
            text=text[:600],
        ))
    return signals


def transaction_signals(evidence: Iterable[Evidence], source: str = "transactions") -> list[Signal]:
    """Bank rows that name a known service (e.g. 'COINBASE' or 'PAYPAL *SHOP')."""
    signals = []
    for e in evidence:
        if e.type != "transaction":
            continue
        text = " ".join(str(e.observed.get(k) or "") for k in ("merchant", "description"))
        service = lookup_text(text)
        if service is None:
            continue
        direction = "from" if e.observed.get("direction") == "in" else "to"
        signals.append(Signal(
            evidence=e,
            service_key=service.key,
            service_name=service.name,
            domain=service.domains[0],
            kind="payment",
            strength="medium",
            rule=f"bank transaction {direction} {service.name}",
            account_type=service.account_type,
            type_source="catalog",
        ))
    return signals


def subscription_signals(subscriptions: list[dict[str, Any]], evidence_by_id: dict[str, dict[str, Any]]) -> list[Signal]:
    """Detected subscriptions (from `build_output`) are strong evidence of an account."""
    signals = []
    for sub in subscriptions:
        inferred = sub["inferred"]
        records = [evidence_by_id[i] for i in sub["evidence_ids"] if i in evidence_by_id]
        hosts = [r["observed"].get("sender_domain") for r in records if r["type"] == "email"]
        host = next((h for h in hosts if h), None)
        service = lookup_domain(host) if host else None
        if service is None and not host:
            service = next((s for r in records if (s := lookup_text(" ".join(
                str(r["observed"].get(k) or "") for k in ("merchant", "description"))))), None)
        if service:
            key, name, domain = service.key, service.name, service.domains[0]
            account_type, type_source = service.account_type, "catalog"
        elif host:
            domain = registrable_domain(host)
            key, name = domain, inferred.get("name")
            account_type = SERVICE_TYPE_TO_ACCOUNT.get(inferred.get("service_type") or "other", "other")
            type_source = "subscription"
        else:  # transaction-only subscription with a generic description: its own finding
            key, name, domain = f"subscription:{sub['subscription_id']}", None, None
            account_type = SERVICE_TYPE_TO_ACCOUNT.get(inferred.get("service_type") or "other", "other")
            type_source = "subscription"
        latest = records[-1] if records else None
        evidence = Evidence(
            evidence_id=sub["subscription_id"],
            type="subscription",
            source="subscriptions",
            source_ref=sub["subscription_id"],
            date=_parse(inferred.get("last_charge_date")) or _parse(latest["observed"].get("date") if latest else None),
            amount=inferred.get("amount"),
            currency=inferred.get("currency"),
            observed={},
        )
        signals.append(Signal(
            evidence=evidence,
            service_key=key,
            service_name=name,
            domain=domain,
            kind="subscription",
            strength="strong",
            rule=f"recurring {inferred.get('billing_cycle')} payment ({sub['subscription_id']}, {sub['confidence']} confidence)",
            account_type=account_type,
            type_source=type_source,
            subscription_id=sub["subscription_id"],
            subscription_confidence=sub["confidence"],
        ))
    return signals


def _parse(value: Any) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except (TypeError, ValueError):
        return None


def connected_mailbox_signal(account: str | None, source: str, today: date) -> Signal | None:
    """The connected mailbox is itself an email account the heirs need to know about."""
    if not account or "@" not in account:
        return None
    host = account.rsplit("@", 1)[1].lower()
    service = lookup_domain(host)
    key = service.key if service else registrable_domain(host)
    name = service.name if service else host
    evidence = Evidence(
        evidence_id=f"mailbox-{account}",
        type="connected_source",
        source=source,
        source_ref=f"account:{account}",
        date=today,
        amount=None,
        currency=None,
        observed={"account": account, "note": "mailbox connected by the user for this scan"},
    )
    return Signal(
        evidence=evidence, service_key=key, service_name=name, domain=registrable_domain(host),
        kind="connected_mailbox", strength="strong", rule=f"the scanned mailbox {account}",
        account_type="email", type_source="catalog",
    )

