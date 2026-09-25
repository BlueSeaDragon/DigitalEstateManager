"""Command line: python -m legacy_policy_crawler google.com spotify.com [--refresh] [--trace]

Prints the records as JSON on stdout; the agent trace and token usage go to stderr.
"""

from __future__ import annotations

import argparse
import json
import sys

from . import lookup_legacy_policy
from .llm import USAGE, AuthError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m legacy_policy_crawler",
        description="Find the legacy account/subscription policy page of company websites.",
    )
    parser.add_argument(
        "websites", nargs="+", help="company websites, e.g. www.google.com"
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="crawl again even if the website is already saved",
    )
    parser.add_argument(
        "--trace", action="store_true", help="print the agent's steps to stderr"
    )
    parser.add_argument(
        "--out",
        help="JSON file to read and update (default: data/legacy_policies.json)",
    )
    args = parser.parse_args(argv)

    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")
    trace = (lambda message: print(message, file=sys.stderr)) if args.trace else None

    records = []
    for website in args.websites:
        try:
            records.append(
                lookup_legacy_policy(
                    website, refresh=args.refresh, path=args.out, trace=trace
                )
            )
        except AuthError as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
    print(json.dumps(records, indent=2, ensure_ascii=False))
    if USAGE["calls"]:
        print(f"Apertus tokens used: {USAGE}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
