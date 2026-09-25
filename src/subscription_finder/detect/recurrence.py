"""Rules that find recurring charge series in a set of dated amounts.

For each billing cycle we search the longest chain of charges whose consecutive gaps
match the cycle (at most one missed period) and whose consecutive amounts are within
the amount tolerance. Non-matching charges (noise) are simply not part of the chain,
so irregular purchases at a similar price do not break detection. The best chain is
extracted, and the search repeats on the remaining charges to find further series.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass

from ..config import CYCLES, Cycle, Settings
from ..models import Candidate, Evidence


@dataclass
class _Node:
    length: int
    deviation: float
    prev: tuple[int, int] | None


def _amounts_compatible(a: float | None, b: float | None, tolerance: float | None) -> bool:
    """`tolerance=None` accepts any amounts (e.g. utility bills that vary every month)."""
    if a is None or b is None or tolerance is None:
        return True
    low, high = sorted((a, b))
    return low > 0 and high / low <= 1 + tolerance


def dedupe_same_day(points: list[Evidence]) -> tuple[list[Evidence], list[Evidence]]:
    """Drop repeated charges on the same day with (almost) the same amount."""
    kept: list[Evidence] = []
    duplicates: list[Evidence] = []
    for e in sorted(points, key=lambda e: e.date):
        if any(k.date == e.date and _amounts_compatible(k.amount, e.amount, 0.01) for k in kept[-3:]):
            duplicates.append(e)
        else:
            kept.append(e)
    return kept, duplicates


def longest_chain(
    points: list[Evidence],
    cycle: Cycle,
    amount_tolerance: float | None,
    max_gap_periods: int = 2,
    max_missed: int = 1,
) -> list[tuple[int, int]]:
    """Return [(index, periods since previous)] of the best chain for `cycle`.

    A gap may span up to `max_gap_periods` periods (k periods = k - 1 missed), with at
    most `max_missed` missed periods in total. State per point: best chain ending there
    with m missed periods. Chains are ranked by length, then fewer missed periods, then
    total deviation from the nominal period.
    """
    n = len(points)
    best: list[list[_Node | None]] = [[_Node(1, 0.0, None)] + [None] * max_missed for _ in range(n)]
    step: dict[tuple[int, int], int] = {}
    p, tol = cycle.period, cycle.tolerance
    for i in range(n):
        for j in range(i):
            gap = (points[i].date - points[j].date).days
            if gap <= 0 or not _amounts_compatible(points[i].amount, points[j].amount, amount_tolerance):
                continue
            # fewest periods that fit: a gap is only a "missed period" if one period does not fit
            periods = next((k for k in range(1, max_gap_periods + 1) if abs(gap - k * p) <= k * tol), None)
            if periods is None:
                continue
            dev = abs(gap - periods * p) / periods
            for m_from in range(max_missed + 1 - (periods - 1)):
                source = best[j][m_from]
                if source is None:
                    continue
                m_to = m_from + periods - 1
                candidate = _Node(source.length + 1, source.deviation + dev, (j, m_from))
                current = best[i][m_to]
                if current is None or (candidate.length, -candidate.deviation) > (current.length, -current.deviation):
                    best[i][m_to] = candidate
                    step[(i, m_to)] = periods
    end, end_rank = None, None
    for i in range(n):
        for m, node in enumerate(best[i]):
            if node is None:
                continue
            rank = (node.length, -m, -node.deviation)
            if end_rank is None or rank > end_rank:
                end, end_rank = (i, m), rank
    chain: list[tuple[int, int]] = []
    while end is not None:
        node = best[end[0]][end[1]]
        chain.append((end[0], step.get(end, 0) if node.prev else 0))
        end = node.prev
    return list(reversed(chain))


def _series(points: list[Evidence], chain: list[tuple[int, int]], cycle: Cycle) -> Candidate:
    charges = [points[i] for i, _ in chain]
    intervals = [
        (charges[k].date - charges[k - 1].date).days / chain[k][1] for k in range(1, len(chain))
    ]
    mean = statistics.fmean(intervals)
    cv = statistics.pstdev(intervals) / mean if len(intervals) > 1 and mean else 0.0
    return Candidate(
        kind=charges[0].type,
        currency=charges[0].currency,
        charges=charges,
        cycle=cycle,
        intervals=intervals,
        median_interval=statistics.median(intervals),
        interval_cv=cv,
        missed_periods=sum(periods - 1 for _, periods in chain[1:]),
    )


def _refit(c: Candidate) -> None:
    """Recompute interval statistics after charges were added to a series."""
    c.charges.sort(key=lambda e: e.date)
    gaps = [(b.date - a.date).days for a, b in zip(c.charges, c.charges[1:])]
    periods = [max(1, round(g / c.cycle.period)) for g in gaps]
    c.intervals = [g / k for g, k in zip(gaps, periods)]
    mean = statistics.fmean(c.intervals)
    c.interval_cv = statistics.pstdev(c.intervals) / mean if len(c.intervals) > 1 and mean else 0.0
    c.median_interval = statistics.median(c.intervals)
    c.missed_periods = sum(k - 1 for k in periods)


def _parent_of(fragment: Candidate, found: list[Candidate], amount_tolerance: float | None) -> Candidate | None:
    """A later series with the same cycle and price whose time span overlaps an earlier
    one is the same subscription split by jitter, not a second subscription."""
    for parent in found:
        if parent.cycle.name != fragment.cycle.name:
            continue
        if not _amounts_compatible(parent.typical_amount, fragment.typical_amount, amount_tolerance):
            continue
        if fragment.dates[0] <= parent.dates[-1] and parent.dates[0] <= fragment.dates[-1]:
            return parent
    return None


MAX_PRICE_CHANGE = 1.5


def _join_price_changes(found: list[Candidate]) -> list[Candidate]:
    """Join a series that starts one period after another ended (same cycle) and whose
    price differs by more than the amount tolerance: a price change, not a new service."""
    found = sorted(found, key=lambda c: c.dates[0])
    joined: list[Candidate] = []
    for series in found:
        for earlier in joined:
            gap = (series.dates[0] - earlier.dates[-1]).days
            p, tol = earlier.cycle.period, earlier.cycle.tolerance
            if (
                earlier.cycle.name == series.cycle.name
                and abs(gap - p) <= tol
                and _amounts_compatible(earlier.typical_amount, series.typical_amount, MAX_PRICE_CHANGE - 1)
            ):
                earlier.charges.extend(series.charges)
                earlier.duplicates.extend(series.duplicates)
                _refit(earlier)
                break
        else:
            joined.append(series)
    return joined


def find_recurring(
    points: list[Evidence],
    settings: Settings,
    cycles: tuple[Cycle, ...] = CYCLES,
    *,
    vary_amounts: bool = False,
    max_gap_periods: int = 2,
    max_missed: int = 1,
) -> list[Candidate]:
    """Find all recurring series among `points` (all of one currency / sender).

    Defaults suit card transactions (stable price, at most one missed period). Billing
    emails from one sender use `vary_amounts=True` and allow more missed periods.
    """
    amount_tolerance = None if vary_amounts else settings.amount_tolerance
    pool, duplicates = dedupe_same_day(points)
    found: list[Candidate] = []
    while len(pool) >= settings.min_charges_yearly:
        best: Candidate | None = None
        for cycle in cycles:
            minimum = settings.min_charges_yearly if cycle.name == "yearly" else settings.min_charges
            chain = longest_chain(pool, cycle, amount_tolerance, max_gap_periods, max_missed)
            if len(chain) < minimum:
                continue
            series = _series(pool, chain, cycle)
            if series.interval_cv >= settings.max_interval_cv:
                continue
            rank = (len(series.charges), -series.missed_periods, -series.interval_cv)
            if best is None or rank > (len(best.charges), -best.missed_periods, -best.interval_cv):
                best = series
        if best is None:
            break
        used = {id(e) for e in best.charges}
        pool = [e for e in pool if id(e) not in used]
        parent = _parent_of(best, found, amount_tolerance)
        if parent is not None:
            parent.charges.extend(best.charges)
            _refit(parent)
        else:
            found.append(best)
    for series in found:
        series.duplicates = [d for d in duplicates if any(d.date == c.date for c in series.charges)]
    return _join_price_changes(found)
