from datetime import date, timedelta

from tests.subscription_finder.conftest import series, tx

from subscription_finder.detect.recurrence import find_recurring

START = date(2025, 1, 10)


def test_exact_monthly(settings):
    [found] = find_recurring(series(START, 8, 30, 12.9), settings)
    assert found.cycle.name == "monthly"
    assert len(found.charges) == 8
    assert found.interval_cv == 0


def test_monthly_with_jitter(settings):
    offsets = [0, 29, 61, 89, 122, 150, 181, 212]
    points = [tx(START + timedelta(days=o), 12.9 + (o % 3) * 0.05) for o in offsets]
    [found] = find_recurring(points, settings)
    assert found.cycle.name == "monthly"
    assert len(found.charges) == 8
    assert found.interval_cv < 0.1


def test_weekly_and_biweekly(settings):
    [weekly] = find_recurring(series(START, 6, 7, 5.0), settings)
    assert weekly.cycle.name == "weekly"
    [biweekly] = find_recurring(series(START, 6, 14, 5.0), settings)
    assert biweekly.cycle.name == "biweekly"


def test_yearly_needs_two_charges(settings):
    [found] = find_recurring(series(START, 2, 365, 99.0), settings)
    assert found.cycle.name == "yearly"


def test_single_charge_is_never_a_subscription(settings):
    assert find_recurring([tx(START, 10.0)], settings) == []


def test_two_monthly_charges_are_not_enough(settings):
    assert find_recurring(series(START, 2, 30, 10.0), settings) == []


def test_price_change_within_tolerance(settings):
    points = series(START, 4, 30, 9.99) + series(START + timedelta(days=120), 4, 30, 10.90)
    [found] = find_recurring(points, settings)
    assert len(found.charges) == 8
    assert found.typical_amount == 10.90


def test_large_price_change_continues_the_series(settings):
    points = series(START, 4, 30, 15.90) + series(START + timedelta(days=120), 4, 30, 19.90)
    [found] = find_recurring(points, settings)
    assert len(found.charges) == 8
    assert found.typical_amount == 19.90


def test_one_missed_month_is_tolerated(settings):
    points = [p for i, p in enumerate(series(START, 8, 30, 20.0)) if i != 4]
    [found] = find_recurring(points, settings)
    assert len(found.charges) == 7
    assert found.missed_periods == 1
    assert 29 <= found.median_interval <= 31


def test_same_day_duplicates_are_removed(settings):
    points = series(START, 5, 30, 15.0)
    duplicate = tx(points[2].date, 15.0)
    [found] = find_recurring(points + [duplicate], settings)
    assert len(found.charges) == 5
    assert len(found.duplicates) == 1


def test_noise_at_similar_price_is_ignored(settings):
    points = series(START, 6, 30, 20.0) + [tx(START + timedelta(days=d), 20.5, description="coffee shop") for d in (7, 50, 95)]
    [found] = find_recurring(points, settings)
    assert len(found.charges) == 6
    assert all(c.observed["description"] == "monthly plan" for c in found.charges)


def test_different_prices_are_separate_subscriptions(settings):
    points = series(START, 6, 30, 9.9) + series(START + timedelta(days=5), 6, 30, 49.0)
    found = find_recurring(points, settings)
    assert sorted(round(f.typical_amount, 1) for f in found) == [9.9, 49.0]


def test_irregular_charges_are_not_recurring(settings):
    offsets = [0, 3, 40, 47, 101, 160, 170]
    assert find_recurring([tx(START + timedelta(days=o), 20.0) for o in offsets], settings) == []


BILL_DATES = [date(2025, 12, 4), date(2026, 2, 4), date(2026, 5, 1), date(2026, 5, 4), date(2026, 6, 3), date(2026, 8, 5), date(2026, 9, 3)]
BILL_AMOUNTS = [21.0, 11.0, 12.0, 14.8, 0.0, 20.3, 12.0]


def test_varying_bills_with_missing_months(settings):
    bills = [tx(d, a, description="phone bill") for d, a in zip(BILL_DATES, BILL_AMOUNTS)]
    assert find_recurring(bills, settings) == []  # card rules: stable price, one missed period
    [found] = find_recurring(bills, settings, vary_amounts=True, max_gap_periods=3, max_missed=6)
    assert found.cycle.name == "monthly"
    assert len(found.charges) == 6  # one of the two May bills is left out
    assert found.missed_periods == 4
    assert 29 <= found.median_interval <= 31


def test_multiple_missed_periods_are_capped(settings):
    # monthly bills; gaps of 1, 2, 2 and 3 months = 4 missed periods in total
    points = [tx(START + timedelta(days=d), 10.0) for d in (0, 30, 90, 150, 240)]
    [capped] = find_recurring(points, settings, vary_amounts=True, max_gap_periods=3, max_missed=2)
    assert len(capped.charges) == 4 and capped.missed_periods == 2  # last bill would exceed the cap
    [full] = find_recurring(points, settings, vary_amounts=True, max_gap_periods=3, max_missed=6)
    assert full.cycle.name == "monthly" and len(full.charges) == 5 and full.missed_periods == 4
