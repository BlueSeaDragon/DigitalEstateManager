"""Subscription finder output -> webapp models.

Fixtures follow the finder's `subscriptions.json` format (see subscription_finder/README.md).
The schema tests fail if the webapp models change in a way the adapter no longer fits.
"""

import copy
import typing

import pytest

from digital_estate_manager.discovery.subscription_adapter import (
    BILLING_CYCLES,
    STATUSES,
    MalformedFinderResult,
    monthly_cost,
    subscription_to_asset,
    to_discovery_result,
)
from digital_estate_manager.models import Asset, AssetStatus, DiscoveryResult, SubscriptionAssetInfo


def finder_subscription(**inferred_overrides):
    inferred = {
        "category": "paid_subscription",
        "service_type": "streaming",
        "name": "Netflix",
        "url": "https://www.netflix.com",
        "cancel_url": "https://www.netflix.com/cancelplan",
        "amount": 15.99,
        "currency": "CHF",
        "billing_cycle": "monthly",
        "recurrence_pattern": "30 ± 2 days",
        "first_seen_date": "2025-01-05",
        "last_charge_date": "2025-12-05",
        "next_expected_date": "2026-01-05",
        "status": "active",
        "account_email": "alex@gmail.com",
        "payment_method": "card",
    }
    inferred.update(inferred_overrides)
    return {
        "subscription_id": "sub-0001",
        "evidence_ids": ["ev-0001", "ev-0002", "ev-0003"],
        "observed": {
            "charge_dates": ["2025-10-05", "2025-11-05", "2025-12-05"],
            "amounts": [15.99, 15.99, 15.99],
            "currency": "CHF",
            "descriptions": ["NETFLIX.COM"],
            "mccs": ["4899"],
            "email_senders": ["info@account.netflix.com"],
            "refunds": [],
        },
        "inferred": inferred,
        "explanation": "Charged 15.99 CHF monthly, confirmed by receipts from netflix.com.",
        "confidence": "high",
        "confidence_reasons": ["3 charges on a monthly cycle", "confirmed by both bank transactions and billing emails"],
    }


def finder_result(*subscriptions, warnings=()):
    return {
        "run": {"tool_version": "0.1.0", "model": None, "warnings": list(warnings)},
        "evidence": [
            {"evidence_id": "ev-0001", "type": "transaction", "source": "tx.jsonl", "source_ref": "line:1", "observed": {}},
            {"evidence_id": "ev-0002", "type": "email", "source": "gmail:alex@gmail.com", "source_ref": "m1", "observed": {}},
            {"evidence_id": "ev-0003", "type": "transaction", "source": "tx.jsonl", "source_ref": "line:9", "observed": {}},
        ],
        "subscriptions": list(subscriptions),
    }


# --- Schema contract ----------------------------------------------------------


def literal_values(model, field):
    return set(typing.get_args(model.model_fields[field].annotation))


def test_adapter_values_are_allowed_by_webapp_literals():
    assert {cycle for cycle, _ in BILLING_CYCLES.values()} <= literal_values(SubscriptionAssetInfo, "billing_cycle")
    assert set(STATUSES.values()) | {"Pending Review"} <= set(typing.get_args(AssetStatus))


def test_result_validates_against_webapp_models():
    result = to_discovery_result(finder_result(finder_subscription()))
    assert isinstance(result, DiscoveryResult)
    DiscoveryResult.model_validate(result.model_dump())
    for asset in result.extracted_assets:
        assert Asset.model_validate(asset.model_dump()) == asset
        assert isinstance(asset.asset_info, SubscriptionAssetInfo)
        # the renderers used by app.py must work on discovered assets
        asset.to_table_row()
        asset.to_type_specific_dict()
        asset.asset_info.display_details()


# --- Field mapping ------------------------------------------------------------


def test_maps_service_account_url_currency_and_policy():
    asset = to_discovery_result(finder_result(finder_subscription())).extracted_assets[0]
    assert asset.service == "Netflix"
    assert asset.service_address == "https://www.netflix.com"
    assert asset.username == "alex@gmail.com"
    assert asset.category == "Subscription"
    assert asset.asset_info.currency == "CHF"
    assert asset.asset_info.billing_cycle == "monthly"
    assert asset.cost_monthly == 15.99
    assert asset.cost_display == "CHF 15.99/mo"
    assert asset.asset_info.renewal_date == "2026-01-05"
    assert asset.asset_info.payment_method_hint == "card"
    assert asset.cancel_policy.target_url == "https://www.netflix.com/cancelplan"
    assert asset.cancel_policy.action_type == "cancel_subscription"
    assert asset.death_policy.summary
    assert asset.status == "Active"
    assert asset.user_verified is False
    assert asset.heir == "Unassigned"


def test_known_service_uses_policy_knowledge_base():
    sub = finder_subscription(name="Spotify", url="https://www.spotify.com", cancel_url=None)
    asset = subscription_to_asset(sub)
    assert asset.cancel_policy.support_email == "support@spotify.com"
    assert asset.cancel_policy.target_url == "https://support.spotify.com/article/deceased-user/"
    assert asset.death_policy.data_disposition == "lapse_on_nonpayment"


@pytest.mark.parametrize(
    "finder_cycle, amount, webapp_cycle, expected_monthly",
    [
        ("weekly", 10.0, "weekly", round(10.0 * 52 / 12, 2)),
        ("biweekly", 37.05, "weekly", round(37.05 * 26 / 12, 2)),
        ("monthly", 15.99, "monthly", 15.99),
        ("quarterly", 30.0, "quarterly", 10.0),
        ("yearly", 120.0, "annual", 10.0),
    ],
)
def test_billing_cycle_and_monthly_cost(finder_cycle, amount, webapp_cycle, expected_monthly):
    asset = subscription_to_asset(finder_subscription(billing_cycle=finder_cycle, amount=amount))
    assert asset.asset_info.billing_cycle == webapp_cycle
    assert asset.cost_monthly == pytest.approx(expected_monthly)
    assert monthly_cost(amount, finder_cycle) == pytest.approx(expected_monthly)


def test_possibly_cancelled_becomes_pending_review_and_is_not_counted_as_drain():
    active = finder_subscription()
    lapsed = finder_subscription(name="Disney+", url="https://www.disneyplus.com", status="possibly_cancelled", amount=9.0)
    result = to_discovery_result(finder_result(active, lapsed))
    statuses = {a.service: a.status for a in result.extracted_assets}
    assert statuses == {"Netflix": "Active", "Disney+": "Pending Review"}
    assert result.detected_recurring_monthly_drain == 15.99
    lapsed_notes = next(a.notes for a in result.extracted_assets if a.service == "Disney+")
    assert "Possibly cancelled" in lapsed_notes and "2025-12-05" in lapsed_notes


def test_notes_keep_explanation_confidence_and_evidence():
    asset = to_discovery_result(finder_result(finder_subscription())).extracted_assets[0]
    assert "confidence: high" in asset.notes
    assert "Charged 15.99 CHF monthly" in asset.notes
    assert "confirmed by both bank transactions and billing emails" in asset.notes
    assert "3 charge(s) 2025-10-05 to 2025-12-05 from bank transactions and billing emails" in asset.notes


def test_transaction_only_finding_with_missing_optional_values():
    sub = finder_subscription(
        name=None, url=None, cancel_url=None, account_email=None, payment_method=None,
        next_expected_date=None, currency=None, service_type="gym", amount=37.05, billing_cycle="biweekly",
    )
    asset = subscription_to_asset(sub)
    assert asset.service == "Gym subscription (37.05)"
    assert asset.service_address == ""
    assert asset.username == ""
    assert asset.asset_info.currency == "USD"  # webapp default when the finder saw no currency
    assert asset.asset_info.renewal_date is None
    assert asset.asset_info.payment_method_hint is None
    assert asset.cancel_policy.target_url is None
    assert asset.cancel_policy.action_name == "Cancel Gym subscription (37.05)"

    unnamed = subscription_to_asset(finder_subscription(name=None, service_type="other", amount=None, currency=None))
    assert unnamed.service == "Unidentified subscription"
    assert unnamed.cost_monthly == 0.0


def test_result_level_fields():
    result = to_discovery_result(
        finder_result(finder_subscription(), warnings=["LLM interpretation unavailable"]), source_name="Gmail + tx.jsonl"
    )
    assert result.source_name == "Gmail + tx.jsonl"
    assert result.confidence_score == 0.9
    assert "Found 1 paid subscription(s)" in result.notes
    assert "LLM interpretation unavailable" in result.notes

    empty = to_discovery_result(finder_result())
    assert empty.extracted_assets == []
    assert empty.detected_recurring_monthly_drain == 0.0


# --- Malformed input ----------------------------------------------------------


@pytest.mark.parametrize("bad", [None, [], {}, {"subscriptions": "nope"}])
def test_malformed_result_raises(bad):
    with pytest.raises(MalformedFinderResult):
        to_discovery_result(bad)


def test_malformed_subscriptions_are_skipped_and_reported():
    no_inferred = {"subscription_id": "sub-0002"}
    bad_cycle = finder_subscription(name="Odd", billing_cycle="fortnightly-ish")
    result = to_discovery_result(finder_result(finder_subscription(), no_inferred, bad_cycle, "junk"))
    assert [a.service for a in result.extracted_assets] == ["Netflix"]
    assert "3 malformed subscription(s) skipped" in result.notes


# --- Deduplication (app.py adds assets whose unique_key is not in the vault) ----


def test_repeated_discovery_produces_the_same_dedup_keys():
    subs = [finder_subscription(), finder_subscription(name=None, url=None, account_email=None, service_type="gym", amount=37.05)]
    first = to_discovery_result(finder_result(*copy.deepcopy(subs))).extracted_assets
    second = to_discovery_result(finder_result(*copy.deepcopy(subs))).extracted_assets
    assert [a.unique_key for a in first] == [a.unique_key for a in second]
    assert len({a.unique_key for a in first}) == 2
    assert first[0].id != second[0].id  # ids are per object; dedup must use unique_key


def test_same_service_on_two_accounts_stays_distinct():
    a = subscription_to_asset(finder_subscription(account_email="alex@gmail.com"))
    b = subscription_to_asset(finder_subscription(account_email="jordan@gmail.com"))
    assert a.unique_key != b.unique_key
