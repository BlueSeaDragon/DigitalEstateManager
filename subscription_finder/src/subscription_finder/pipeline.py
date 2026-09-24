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
from .llm.client import LLMClient
from .llm.interpret import interpret
from .models import Evidence, RunInfo
from .output import build_output
from .sources.email_base import EmailSource, ReconnectRequired
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
    settings = settings or Settings.from_env()
    reference_date = reference_date or date.today()
    report = progress or (lambda message, fraction: None)
    llm = LLMClient(settings, client=llm_client) if use_llm else None
    run = RunInfo(reference_date=reference_date, model=settings.model if use_llm else None)
    evidence: list[Evidence] = []

    if transactions is not None:
        report("Reading transactions", 0.05)
        tx_evidence, stats = load_transactions(transactions, sample_client_id)
        evidence.extend(tx_evidence)
        run.transaction_sources.append(stats)
        if stats["skipped"]:
            run.warnings.append(f"{stats['skipped']} malformed transaction row(s) skipped")

    account_email = None
    for source in email_sources:
        report(f"Reading {source.provider} emails", 0.15)
        try:
            messages = source.fetch(progress=lambda m, f: report(m, 0.15 + 0.25 * f))
            account = source.account
            account_email = account_email or account
            em_evidence, counts = extract_emails(
                messages,
                f"{source.provider}:{account or 'unknown'}",
                llm,
                settings.snippet_chars,
                progress=lambda m, f: report(m, 0.4 + 0.3 * f),
            )
            evidence.extend(em_evidence)
            if counts["llm_failures"]:
                run.warnings.append(
                    f"{counts['llm_failures']} email(s) interpreted by rules only (LLM unavailable)"
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

    if not evidence:
        run.warnings.append("No transactions or billing emails found; nothing to analyse")

    report("Detecting recurring charges", 0.75)
    candidates = []
    for detector in detectors or [PaidSubscriptionDetector()]:
        candidates.extend(detector.detect(evidence, reference_date, settings))

    if llm is not None and candidates:
        report("AI review of findings", 0.85)
        if not interpret(candidates, llm):
            run.warnings.append("LLM interpretation unavailable; results are rules-only with reduced confidence")
    if llm is not None:
        run.llm_usage = dict(llm.usage)

    report("Done", 1.0)
    return build_output(candidates, run, settings, account_email)
