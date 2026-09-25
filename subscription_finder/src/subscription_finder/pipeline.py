"""End-to-end run for one person: sources -> evidence -> detection -> interpretation -> output."""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import IO, Any, Callable, Iterable

from .config import Settings
from .detect.base import Detector
from .detect.paid_subscription import PaidSubscriptionDetector
from .extract.email_extractor import extract_emails
from .footprint.accounts import add_accounts, group_signals, keep
from .footprint.interpret import classify_ambiguous
from .footprint.signals import Signal, connected_mailbox_signal, email_signals, subscription_signals, transaction_signals
from .llm.client import LLMClient
from .llm.interpret import interpret
from .models import EmailMessage, Evidence, RunInfo
from .output import build_output
from .sources.email_base import EmailSource, ReconnectRequired
from .sources.gmail import BILLING_PATTERN
from .sources.transactions_jsonl import load_transactions

log = logging.getLogger(__name__)

Progress = Callable[[str, float], None]


def detect_subscriptions(
    email_sources: Iterable[EmailSource] = (),
    transactions: str | Path | IO | None = None,
    sample_client_id: str | None = None,
    use_llm: bool = True,
    reference_date: date | None = None,
    progress: Progress | None = None,
    *,
    settings: Settings | None = None,
    llm_client: Any = None,
    detectors: list[Detector] | None = None,
) -> dict[str, Any]:
    """Find one person's paid recurring subscriptions. Returns the `subscriptions.json` dict.

    Raises `LLMConfigError` if `use_llm` is set but the API key/endpoint is missing, and
    `ReconnectRequired` if an email source's credentials are expired or revoked.
    """
    return _run(email_sources, transactions, sample_client_id, use_llm, reference_date, progress,
                settings, llm_client, detectors, footprint=False)


def discover_footprint(
    email_sources: Iterable[EmailSource] = (),
    transactions: str | Path | IO | None = None,
    sample_client_id: str | None = None,
    use_llm: bool = True,
    reference_date: date | None = None,
    progress: Progress | None = None,
    *,
    settings: Settings | None = None,
    llm_client: Any = None,
    detectors: list[Detector] | None = None,
) -> dict[str, Any]:
    """Find one person's subscriptions *and* the services they have a relationship with.

    Returns the `detect_subscriptions` dict plus `accounts` (one per service, with evidence).
    For Gmail, pass `GmailSource(..., terms=FOOTPRINT_TERMS)` so security, sign-up, statement
    and contract emails are fetched too. Same exceptions as `detect_subscriptions`.
    """
    return _run(email_sources, transactions, sample_client_id, use_llm, reference_date, progress,
                settings, llm_client, detectors, footprint=True)


def _run(
    email_sources: Iterable[EmailSource],
    transactions: str | Path | IO | None,
    sample_client_id: str | None,
    use_llm: bool,
    reference_date: date | None,
    progress: Progress | None,
    settings: Settings | None,
    llm_client: Any,
    detectors: list[Detector] | None,
    footprint: bool,
) -> dict[str, Any]:
    settings = settings or Settings.from_env()
    reference_date = reference_date or date.today()
    report = progress or (lambda message, fraction: None)
    llm = LLMClient(settings, client=llm_client) if use_llm else None
    run = RunInfo(reference_date=reference_date, model=settings.model if use_llm else None)
    evidence: list[Evidence] = []
    signals: list[Signal] = []

    if transactions is not None:
        report("Reading transactions", 0.05)
        tx_evidence, stats = load_transactions(transactions, sample_client_id)
        evidence.extend(tx_evidence)
        run.transaction_sources.append(stats)
        if stats["skipped"]:
            run.warnings.append(f"{stats['skipped']} malformed transaction row(s) skipped")
        if footprint:
            signals.extend(transaction_signals(tx_evidence, stats["source"]))

    account_email = None
    for source in email_sources:
        report(f"Reading {source.provider} emails", 0.15)
        try:
            messages: list[EmailMessage] = list(source.fetch(progress=lambda m, f: report(m, 0.15 + 0.25 * f)))
            account = source.account
            account_email = account_email or account
            source_name = f"{source.provider}:{account or 'unknown'}"
            billing = messages
            if footprint:
                signals.extend(email_signals(messages, source_name, settings.snippet_chars))
                mailbox = connected_mailbox_signal(account, source_name, reference_date)
                if mailbox:
                    signals.append(mailbox)
                billing = [m for m in messages if BILLING_PATTERN.search(f"{m.subject}\n{m.body}")]
            em_evidence, counts = extract_emails(
                billing,
                source_name,
                llm,
                settings.snippet_chars,
                progress=lambda m, f: report(m, 0.4 + 0.3 * f),
            )
            evidence.extend(em_evidence)
            if counts["llm_failures"]:
                run.warnings.append(
                    f"{counts['llm_failures']} email(s) interpreted by rules only (LLM unavailable)" + _reason(llm)
                )
        except ReconnectRequired:
            raise
        except Exception as exc:
            log.warning("%s source failed: %s", source.provider, type(exc).__name__)
            run.warnings.append(
                f"{source.provider} could not be read ({type(exc).__name__}); results use the other sources only"
            )
        stats = source.stats()
        if stats.get("skipped"):
            run.warnings.append(f"{stats['skipped']} {source.provider} message(s) could not be read and were skipped")
        run.email_sources.append(stats)

    if not evidence and not signals:
        run.warnings.append("No transactions or billing emails found; nothing to analyse")

    report("Detecting recurring charges", 0.75)
    candidates = []
    for detector in detectors or [PaidSubscriptionDetector()]:
        candidates.extend(detector.detect(evidence, reference_date, settings))

    if llm is not None and candidates:
        report("AI review of findings", 0.85)
        if not interpret(candidates, llm, settings.interpret_batch_size):
            run.warnings.append(
                "LLM interpretation unavailable; results are rules-only with reduced confidence" + _reason(llm)
            )

    result = build_output(candidates, run, settings, account_email)
    if footprint:
        report("Mapping the digital footprint", 0.9)
        _footprint(result, signals, llm, settings, account_email)
    if llm is not None:
        result["run"]["llm_usage"] = dict(llm.usage)

    report("Done", 1.0)
    return result


def _reason(llm: LLMClient | None) -> str:
    return f" (last error: {llm.last_error})" if llm is not None and llm.last_error else ""


def _footprint(
    result: dict[str, Any], signals: list[Signal], llm: LLMClient | None, settings: Settings, account_email: str | None
) -> None:
    evidence_by_id = {e["evidence_id"]: e for e in result["evidence"]}
    signals = signals + subscription_signals(result["subscriptions"], evidence_by_id)
    findings = group_signals(signals)
    kept = [f for f in findings if keep(f, settings.footprint_keep_unknown_weak)]
    ambiguous = sum(f.needs_llm for f in kept)
    if llm is not None and ambiguous:
        if not classify_ambiguous(kept, llm, settings.footprint_llm_batch_size):
            result["run"]["warnings"].append(
                "AI classification of unknown services unavailable; their account type is left as 'other'"
                + _reason(llm)
            )
    add_accounts(result, kept, account_email, settings.footprint_max_evidence_per_account)
    result["run"]["footprint"] = {
        "signals": len(signals),
        "services": len(findings),
        "accounts": len(kept),
        "dropped_weak_unknown": len(findings) - len(kept),
        "ambiguous_services": ambiguous,
        "llm_classified": sum(f.classified_by == "llm" for f in kept),
    }
