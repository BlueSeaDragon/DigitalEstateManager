"""CHF formatting, the fixed demo FX table and currency-aware metrics."""

import pytest

from digital_estate_manager.currency import FX_TO_CHF, chf, money, to_chf
from digital_estate_manager.models import Asset, CancelPolicy, DeathPolicy, SubscriptionAssetInfo
from digital_estate_manager.vault import calculate_metrics, monthly_cost_chf


def subscription(service, cost, currency):
    return Asset(
        service=service,
        death_policy=DeathPolicy(summary="-"),
        cancel_policy=CancelPolicy(),
        asset_info=SubscriptionAssetInfo(cost_monthly=cost, currency=currency),
    )


@pytest.mark.parametrize(
    "amount, expected",
    [(0, "CHF 0.00"), (20.9, "CHF 20.90"), (1234.5, "CHF 1'234.50"), (1234567.891, "CHF 1'234'567.89"), (-5, "-CHF 5.00")],
)
def test_chf_uses_swiss_grouping(amount, expected):
    assert chf(amount) == expected


def test_money_keeps_the_original_currency():
    assert money(20, "usd") == "USD 20.00"
    assert money(12450, "EUR", decimals=0) == "EUR 12'450"


def test_to_chf_converts_with_the_fixed_table():
    assert to_chf(10, "CHF") == 10
    assert to_chf(20, "USD") == pytest.approx(20 * FX_TO_CHF["USD"])
    assert to_chf(None, "USD") is None
    assert to_chf(10, "XYZ") is None  # unknown currency: left out of totals


def test_monthly_cost_chf_converts_each_type():
    assert monthly_cost_chf(subscription("ChatGPT", 20.0, "USD")) == pytest.approx(16.0)
    assert monthly_cost_chf(subscription("Unknown", 5.0, "XYZ")) == 0


def test_metrics_sum_mixed_currencies_in_chf():
    assets = [subscription("Netflix", 20.90, "CHF"), subscription("ChatGPT", 20.00, "USD")]
    metrics = calculate_metrics(assets)
    expected = round(20.90 + 20.00 * FX_TO_CHF["USD"], 2)
    assert metrics["active_monthly_spend_chf"] == pytest.approx(expected)
    assert metrics["active_monthly_spend"] == chf(expected)
