"""Generates `demo_transactions.jsonl`: 18 months of card and bank transactions for a
fictional Zurich resident, used to demo discovery without a real inbox or bank account.

The finder judges "active" vs "possibly cancelled" against today's date, so regenerate
shortly before a demo or recording:

    python samples/make_demo_transactions.py            # history ends today
    python samples/make_demo_transactions.py 2026-10-15 # history ends on that date
"""

import json
import random
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

CLIENT_ID = "DEMO-ZH-001"
MONTHS = 18
OUT = Path(__file__).with_name("demo_transactions.jsonl")

# (description, mcc, day of month, amount, currency, first month offset, last month offset or None)
# Month offsets count back from the end month: 0 = end month, 17 = first month of history.
MONTHLY = [
    ("NETFLIX.COM Amsterdam", "4899", 7, 20.90, "CHF", 17, None),
    ("SPOTIFY P2F3A8C Stockholm Premium Family", "5815", 12, 25.95, "CHF", 17, None),
    ("SWISSCOM (SCHWEIZ) AG Mobile Abo", "4814", 28, 65.00, "CHF", 17, None),
    ("GOOGLE *Google One Storage", "5818", 3, 2.50, "CHF", 17, None),
    ("APPLE.COM/BILL iCloud+ 200GB", "5818", 15, 3.00, "CHF", 17, None),
    ("OPENAI *CHATGPT SUBSCR San Francisco", "5734", 19, 20.00, "USD", 11, None),
    ("ADOBE *CREATIVE CLOUD PHOTO Dublin", "5734", 22, 13.50, "CHF", 17, 6),  # cancelled ~6 months ago
    ("UPDATE FITNESS AG Mitgliedschaft", "7997", 1, 79.00, "CHF", 17, None),
    ("NZZ Digital Abo monthly", "5994", 9, 39.00, "CHF", 17, None),
    ("DISNEY PLUS Monthly subscription", "4899", 24, 12.90, "CHF", 3, None),  # new, few charges
]
YEARLY = [
    ("MICROSOFT*365 FAMILY annual renewal", "5734", 5, 99.00, "CHF", 5),
    ("SBB CFF FFS Halbtax Abo renewal", "4112", 2, 190.00, "CHF", 3),
]
# Supplementary health insurance, paid by standing order.
INSURANCE = ("Dauerauftrag HELSANA Zusatzversicherung", "6300", 1, 48.60, "CHF")


def _month_start(end: date, offset: int) -> date:
    y, m = end.year, end.month - offset
    while m <= 0:
        m += 12
        y -= 1
    return date(y, m, 1)


def _day(end: date, offset: int, day: int, rng: random.Random) -> date:
    start = _month_start(end, offset)
    # Card charges settle a day or two late now and then, like real statements.
    return start + timedelta(days=min(day, 28) - 1 + rng.choice([0, 0, 0, 1, 2]))


def _row(when: date, amount: float, description: str, mcc: str | None, currency="CHF",
         kind="card_payment", direction="out", rng: random.Random | None = None) -> dict:
    hour = rng.randint(7, 22) if rng else 10
    return {
        "client_id": CLIENT_ID,
        "timestamp": datetime(when.year, when.month, when.day, hour, rng.randint(0, 59) if rng else 0).isoformat() + "Z",
        "amount": round(amount, 2),
        "currency": currency,
        "direction": direction,
        "type": kind,
        "description": description,
        "mcc": mcc,
        "fee": 0.0,
    }


def _noise_amount(rng: random.Random, mu: float, sigma: float) -> float:
    """A random everyday amount at least 15 % away from every subscription price."""
    prices = [m[3] for m in MONTHLY] + [y[3] for y in YEARLY] + [INSURANCE[3]]
    while True:
        value = rng.lognormvariate(mu, sigma)
        if all(abs(value - p) / p > 0.15 for p in prices):
            return value


def generate(end: date, seed: int = 11) -> list[dict]:
    rng = random.Random(seed)
    rows: list[dict] = []

    for description, mcc, day, amount, currency, first, last in MONTHLY:
        for offset in range(first, (last or 0) - 1, -1):
            when = _day(end, offset, day, rng)
            if when > end:
                continue
            rows.append(_row(when, amount, description, mcc, currency, rng=rng))

    for description, mcc, day, amount, currency, month_offset in YEARLY:
        for offset in (month_offset + 12, month_offset):
            if offset < MONTHS:
                rows.append(_row(_day(end, offset, day, rng), amount, description, mcc, currency, rng=rng))

    description, mcc, day, amount, currency = INSURANCE
    for offset in range(MONTHS - 1, -1, -1):
        rows.append(_row(_day(end, offset, day, rng), amount, description, mcc, currency, kind="transfer", rng=rng))

    # Everyday spending the finder must ignore.
    for offset in range(MONTHS - 1, -1, -1):
        start = _month_start(end, offset)
        rows.append(_row(start + timedelta(days=24), 7850.00, "Lohn ACME Treuhand AG", None,
                         kind="transfer", direction="in", rng=rng))
        # The finder chains card charges by amount and timing (not by merchant), so noise
        # amounts are spread widely to keep coincidental "series" out of the demo.
        for _ in range(rng.randint(1, 3)):
            shop = rng.choice(["MIGROS ZUERICH OERLIKON", "COOP-1234 ZUERICH", "DENNER ZUERICH"])
            rows.append(_row(start + timedelta(days=rng.randint(0, 27)), _noise_amount(rng, 4.3, 1.2), shop, "5411", rng=rng))
        for _ in range(rng.randint(0, 2)):
            place = rng.choice(["ZEUGHAUSKELLER ZUERICH", "TIBITS ZUERICH", "CAFE SCHOBER", "HILTL AG"])
            rows.append(_row(start + timedelta(days=rng.randint(0, 27)), _noise_amount(rng, 3.8, 0.8), place, "5812", rng=rng))
        if rng.random() < 0.6:
            rows.append(_row(start + timedelta(days=rng.randint(0, 27)), _noise_amount(rng, 3.0, 0.9),
                             "SBB CFF FFS Billett", "4111", rng=rng))
        if rng.random() < 0.45:
            rows.append(_row(start + timedelta(days=rng.randint(0, 27)), _noise_amount(rng, 4.6, 0.6),
                             "DIGITEC GALAXUS AG", "5732", rng=rng))

    # A returned online order.
    refund_day = _month_start(end, 4) + timedelta(days=11)
    rows.append(_row(refund_day - timedelta(days=6), 149.00, "ZALANDO SE Berlin", "5651", rng=rng))
    rows.append(_row(refund_day, 149.00, "ZALANDO SE Berlin Gutschrift", "5651", kind="refund", direction="in", rng=rng))

    rows = [r for r in rows if r["timestamp"][:10] <= end.isoformat()]
    rows.sort(key=lambda r: r["timestamp"])
    return rows


def main() -> None:
    end = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else date.today()
    rows = generate(end)
    OUT.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    print(f"wrote {len(rows)} transactions to {OUT} (history ends {end})")


if __name__ == "__main__":
    main()
