"""Dev-only evaluation on the labelled sample dataset.

Labels name the category of each person's *next* recurring merchant (or `none`), so the
metrics are approximate: recall = labelled category is among the detected active service
types; false alarms = share of `none` people with at least one active detection.

    python scripts/evaluate.py                 # 100 people, rules only
    python scripts/evaluate.py --n 30 --llm    # uses the Apertus token budget
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import random
import statistics
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

from subscription_finder import detect_subscriptions
from subscription_finder.config import Settings

ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--transactions", default=ROOT / "data" / "valid_transactions.jsonl", type=Path)
    parser.add_argument("--labels", default=ROOT / "data" / "valid_labels.csv", type=Path)
    parser.add_argument("--n", type=int, default=100, help="number of sampled people (0 = all)")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--llm", action="store_true", help="use Apertus (spends tokens)")
    parser.add_argument("--out", default="output/eval_report.json", type=Path)
    args = parser.parse_args()

    with args.labels.open(encoding="utf-8") as f:
        labels = {r["client_id"]: (r["target_next_recurring_merchant"], r["cutoff_date"]) for r in csv.DictReader(f)}
    people = sorted(labels)
    if args.n:
        people = sorted(random.Random(args.seed).sample(people, min(args.n, len(people))))
    wanted = set(people)

    lines: dict[str, list[str]] = defaultdict(list)
    with args.transactions.open(encoding="utf-8") as f:
        for line in f:
            client = json.loads(line).get("client_id")
            if client in wanted:
                lines[client].append(line)

    settings = Settings.from_env()
    hits: dict[str, list[bool]] = defaultdict(list)
    none_alarms: list[bool] = []
    counts: list[int] = []
    tokens = {"input_tokens": 0, "output_tokens": 0, "requests": 0}
    for i, client in enumerate(people, start=1):
        label, cutoff = labels[client]
        result = detect_subscriptions(
            transactions=io.StringIO("".join(lines[client])),
            use_llm=args.llm,
            reference_date=date.fromisoformat(cutoff),
            settings=settings,
        )
        active = [s for s in result["subscriptions"] if s["inferred"]["status"] == "active"]
        types = {s["inferred"]["service_type"] for s in active}
        counts.append(len(result["subscriptions"]))
        if label == "none":
            none_alarms.append(bool(active))
        else:
            hits[label].append(label in types)
        for key in tokens:
            tokens[key] += result["run"]["llm_usage"].get(key, 0)
        print(f"\r{i}/{len(people)}", end="", file=sys.stderr)
    print(file=sys.stderr)

    all_hits = [h for values in hits.values() for h in values]
    report = {
        "people": len(people),
        "llm": args.llm,
        "recall": round(statistics.fmean(all_hits), 3) if all_hits else None,
        "per_category_recall": {k: {"n": len(v), "recall": round(statistics.fmean(v), 3)} for k, v in sorted(hits.items())},
        "none_people": len(none_alarms),
        "approx_false_alarm_rate": round(statistics.fmean(none_alarms), 3) if none_alarms else None,
        "avg_subscriptions_per_person": round(statistics.fmean(counts), 2) if counts else 0,
        "llm_usage": tokens,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
