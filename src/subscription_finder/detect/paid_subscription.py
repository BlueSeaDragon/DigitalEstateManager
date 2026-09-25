"""Detector for paid recurring subscriptions (transactions + billing emails)."""

from __future__ import annotations

import re
import statistics
from collections import Counter, defaultdict
from datetime import date, timedelta

from ..config import SUBSCRIPTION_MCCS, Settings
from ..models import Candidate, Evidence
from ..sources.transactions_jsonl import is_charge, is_refund
from .recurrence import find_recurring

SERVICE_KEYWORDS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("music", re.compile(r"audio|music|spotify|podcast|deezer|tidal", re.I)),
    ("streaming", re.compile(r"video|stream|netflix|disney|hulu|\btv\b|media|movie|film", re.I)),
    ("cloud", re.compile(r"cloud|storage|backup|dropbox|icloud|\bdrive\b", re.I)),
    ("software", re.compile(r"saas|software|productivity|suite|licen[cs]e|adobe|office", re.I)),
    ("mobile", re.compile(r"phone|mobile|telecom|\bsim\b|internet|broadband|festnetz|swisscom|sunrise|\bsalt\b|talktalk", re.I)),
    ("gym", re.compile(r"gym|fitness|fit club|member pass|yoga|sport", re.I)),
    ("insurance", re.compile(r"insur|policy|\bcover\b|versicherung|assurance", re.I)),
)
MCC_SERVICE = {"7997": "gym", "6300": "insurance", "4814": "mobile", "5734": "software", "4899": "streaming"}
KNOWN_DOMAINS = {
    "netflix.com": "streaming", "disneyplus.com": "streaming", "primevideo.com": "streaming",
    "spotify.com": "music", "deezer.com": "music", "tidal.com": "music",
    "dropbox.com": "cloud", "icloud.com": "cloud",
    "adobe.com": "software", "microsoft.com": "software",
    "swisscom.ch": "mobile", "sunrise.ch": "mobile", "salt.ch": "mobile",
}
SUBSCRIPTION_HINT = re.compile(
    r"subscri|member|plan\b|premium|renew|monthly|annual|yearly|abo\b|abonnement|licen[cs]e", re.I
)
MULTI_PART_TLDS = {"co", "com", "org", "net", "ac", "gov", "edu"}


def registrable_domain(host: str) -> str:
    parts = [p for p in host.lower().strip(".").split(".") if p]
    if len(parts) >= 3 and parts[-2] in MULTI_PART_TLDS and len(parts[-1]) == 2:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def infer_service_type(c: Candidate) -> str:
    votes: Counter[str] = Counter()
    for e in c.all_charges:
        text = " ".join(str(e.observed.get(k) or "") for k in ("description", "merchant", "subject"))
        for service, pattern in SERVICE_KEYWORDS:
            if pattern.search(text):
                votes[service] += 1
                break
        if e.observed.get("mcc") in MCC_SERVICE:
            votes[MCC_SERVICE[e.observed["mcc"]]] += 1
    for domain in c.sender_domains:
        service = KNOWN_DOMAINS.get(registrable_domain(domain))
        if service:
            votes[service] += 10 * len(c.all_charges)
    return votes.most_common(1)[0][0] if votes else "other"


def _name_from_email(c: Candidate) -> tuple[str | None, str | None]:
    domains = [registrable_domain(d) for d in c.sender_domains if d]
    if not domains:
        return None, None
    domain = Counter(domains).most_common(1)[0][0]
    merchants = c.email_merchants
    name = merchants[0] if merchants else domain.split(".")[0].capitalize()
    return name, f"https://{domain}"


def has_subscription_signal(c: Candidate) -> bool:
    """At least half the charges carry a subscription-typical MCC or wording."""
    hits = 0
    for e in c.charges:
        text = " ".join(str(e.observed.get(k) or "") for k in ("description", "merchant"))
        if e.observed.get("mcc") in SUBSCRIPTION_MCCS or SUBSCRIPTION_HINT.search(text) or any(
            p.search(text) for _, p in SERVICE_KEYWORDS
        ):
            hits += 1
    return hits * 2 >= len(c.charges)


def amount_cv(c: Candidate) -> float:
    amounts = c.amounts
    mean = statistics.fmean(amounts) if amounts else 0
    return statistics.pstdev(amounts) / mean if len(amounts) > 1 and mean else 0.0


def is_plausible(c: Candidate, settings: Settings) -> bool:
    """Series with only the minimum number of charges are weak evidence: keep them only
    with a subscription signal and a stable price, or with an exact repeated price."""
    minimum = settings.min_charges_yearly if c.cycle.name == "yearly" else settings.min_charges
    if len(c.charges) > minimum or c.kind == "email":
        return True
    cv = amount_cv(c)
    if cv <= settings.exact_price_amount_cv and c.cycle.name != "yearly":
        return True
    return has_subscription_signal(c) and cv <= settings.weak_series_max_amount_cv


def _match_refunds(c: Candidate, refunds: list[Evidence], used: set[str], settings: Settings) -> None:
    window = timedelta(days=settings.refund_window_days)
    for r in refunds:
        if r.evidence_id in used or r.currency != c.currency or r.amount is None:
            continue
        for charge in c.charges:
            if charge.amount and charge.date <= r.date <= charge.date + window and abs(r.amount - charge.amount) <= settings.merge_amount_tolerance * charge.amount:
                c.refunds.append(r)
                used.add(r.evidence_id)
                break


def _timeline(c: Candidate, reference_date: date) -> dict:
    charges = c.all_charges
    last = max(e.date for e in c.charges)
    period = round(c.median_interval)
    next_expected = last + timedelta(days=period)
    grace = timedelta(days=2 * c.cycle.tolerance)
    status = "active" if next_expected + grace >= reference_date else "possibly_cancelled"
    last_charge = max(c.charges, key=lambda e: e.date)
    if any(
        r.date >= last_charge.date and last_charge.amount and r.amount >= 0.95 * last_charge.amount
        for r in c.refunds
    ):
        status = "possibly_cancelled"
    spread = max(1, round(statistics.pstdev(c.intervals))) if len(c.intervals) > 1 else c.cycle.tolerance
    return {
        "first_seen_date": charges[0].date,
        "last_charge_date": last,
        "next_expected_date": next_expected,
        "status": status,
        "recurrence_pattern": f"{period} ± {spread} days",
    }


def merge_sources(tx: list[Candidate], em: list[Candidate], settings: Settings) -> list[Candidate]:
    """Attach email series to the transaction series they corroborate."""
    remaining: list[Candidate] = []
    window = timedelta(days=settings.merge_date_days)
    for e in em:
        match = None
        for t in tx:
            if t.email_charges or t.cycle.name != e.cycle.name:
                continue
            if e.currency and t.currency != e.currency:
                continue
            ta, ea = t.typical_amount, e.typical_amount
            if ea is not None and ta and abs(ea - ta) > settings.merge_amount_tolerance * ta:
                continue
            if any(abs(ed - td) <= window for ed in e.dates for td in t.dates):
                match = t
                break
        if match is None:
            remaining.append(e)
            continue
        match.kind = "merged"
        match.email_charges = e.charges
    return tx + remaining


class PaidSubscriptionDetector:
    category = "paid_subscription"

    def detect(self, evidence: list[Evidence], reference_date: date, settings: Settings) -> list[Candidate]:
        evidence = [e for e in evidence if e.date <= reference_date]
        transactions = [e for e in evidence if e.type == "transaction"]
        refunds = [e for e in transactions if is_refund(e)]
        by_currency: dict[str | None, list[Evidence]] = defaultdict(list)
        for e in transactions:
            if is_charge(e):
                by_currency[e.currency].append(e)
        tx_candidates = [c for points in by_currency.values() for c in find_recurring(points, settings)]
        tx_candidates = [c for c in tx_candidates if is_plausible(c, settings)]

        # Emails are grouped by sender only: bills vary in amount (and sometimes miss a currency).
        by_sender: dict[str, list[Evidence]] = defaultdict(list)
        for e in evidence:
            if e.type == "email":
                by_sender[registrable_domain(e.observed.get("sender_domain") or "")].append(e)
        em_candidates = [
            c
            for points in by_sender.values()
            for c in find_recurring(
                points,
                settings,
                vary_amounts=True,
                max_gap_periods=settings.email_max_gap_periods,
                max_missed=settings.email_max_missed,
            )
        ]
        for c in em_candidates:
            currencies = Counter(e.currency for e in c.charges if e.currency)
            c.currency = currencies.most_common(1)[0][0] if currencies else None

        used_refunds: set[str] = set()
        for c in tx_candidates:
            _match_refunds(c, refunds, used_refunds, settings)

        candidates = merge_sources(tx_candidates, em_candidates, settings)
        for c in candidates:
            c.category = self.category
            c.service_type = infer_service_type(c)
            c.name, c.url = _name_from_email(c)
            c.timeline = _timeline(c, reference_date)
            c.explanation = rule_explanation(c)
        return candidates


def rule_explanation(c: Candidate) -> str:
    t = c.timeline
    amount = c.typical_amount
    amounts = [e.amount for e in c.all_charges if e.amount]
    if amounts and max(amounts) > 1.1 * min(amounts):
        price = f"between {min(amounts):.2f} and {max(amounts):.2f} {c.currency or ''} (varies)".rstrip()
    elif amount is not None:
        price = f"about {amount:.2f} {c.currency or ''}".strip()
    else:
        price = "an unknown amount"
    parts = [
        f"Charged {price} every ~{round(c.median_interval)} days ({c.cycle.name}), "
        f"{len(c.charges)} times between {c.charges[0].date.isoformat()} and {t['last_charge_date'].isoformat()}."
    ]
    if c.has_transactions:
        descriptions = ", ".join(f"'{d}'" for d in c.descriptions[:3])
        parts.append(f"Found in bank transactions described as {descriptions}.")
    if c.has_email:
        parts.append(f"Billing emails from {', '.join(c.sender_domains[:2])}.")
    if c.refunds:
        parts.append(f"{len(c.refunds)} refund(s) matched.")
    if t["status"] == "possibly_cancelled":
        parts.append("No recent charge, so it may have been cancelled.")
    return " ".join(parts)
