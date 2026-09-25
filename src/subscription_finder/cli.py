"""Command line: subscription-finder --gmail --transactions FILE --out output/subscriptions.json"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date

from . import __version__
from .config import Settings
from .llm.client import LLMConfigError
from .output import write_output
from .pipeline import detect_subscriptions
from .sources.email_base import ReconnectRequired


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="subscription-finder",
        description="Find one person's paid recurring subscriptions in Gmail and a transaction file.",
    )
    parser.add_argument("--gmail", action="store_true", help="scan Gmail (opens a browser login the first time)")
    parser.add_argument("--credentials", default="credentials.json", help="Google OAuth client file")
    parser.add_argument("--token", default="token.json", help="cached Gmail token file")
    parser.add_argument("--gmail-max", type=int, default=None, help="max emails to read (default 500)")
    parser.add_argument("--transactions", help="transactions JSONL file of one person (or the sample dataset)")
    parser.add_argument("--sample-client", help="sample dataset only: the client_id to analyse")
    parser.add_argument("--reference-date", type=date.fromisoformat, help="YYYY-MM-DD, default today")
    parser.add_argument("--out", default="output/subscriptions.json", help="output JSON path")
    parser.add_argument("--no-llm", action="store_true", help="rules only; no data sent to the LLM")
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("--version", action="version", version=__version__)
    args = parser.parse_args(argv)
    if not args.gmail and not args.transactions:
        parser.error("give --gmail and/or --transactions")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, format="%(levelname)s %(message)s")
    settings = Settings.from_env()
    if args.gmail_max:
        settings.gmail_max_messages = args.gmail_max

    try:
        sources = []
        if args.gmail:
            from .auth.gmail_auth import local_login
            from .sources.gmail import GmailSource

            creds = local_login(args.credentials, args.token)
            sources.append(
                GmailSource(
                    creds,
                    months=settings.gmail_months,
                    max_messages=settings.gmail_max_messages,
                    body_chars=settings.email_body_chars,
                    snippet_chars=settings.snippet_chars,
                )
            )

        def progress(message: str, fraction: float) -> None:
            print(f"[{fraction:4.0%}] {message}", file=sys.stderr)

        result = detect_subscriptions(
            email_sources=sources,
            transactions=args.transactions,
            sample_client_id=args.sample_client,
            use_llm=not args.no_llm,
            reference_date=args.reference_date,
            progress=progress,
            settings=settings,
        )
    except (LLMConfigError, FileNotFoundError, ReconnectRequired) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    path = write_output(result, args.out)
    subs = result["subscriptions"]
    active = sum(1 for s in subs if s["inferred"]["status"] == "active")
    print(f"{len(subs)} subscription(s) found ({active} active) -> {path}")
    for s in subs:
        inf = s["inferred"]
        label = inf["name"] or inf["service_type"]
        amount = f"{inf['amount']:.2f} {inf['currency']}" if inf["amount"] is not None else "?"
        print(f"  {s['subscription_id']}  {label:<14} {amount:>12} {inf['billing_cycle']:<9} {inf['status']:<18} {s['confidence']}")
    for warning in result["run"]["warnings"]:
        print(f"warning: {warning}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
