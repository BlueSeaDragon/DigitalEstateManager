"""Tests for the bridge between the legacy policy crawler and the app's DeathPolicy."""

import json
from datetime import date

import pytest

import legacy_policy_crawler
from legacy_policy_crawler.llm import AuthError

from digital_estate_manager.models import DeathPolicy
from digital_estate_manager.policies import get_policies_for_service
from digital_estate_manager.policies import legacy
from digital_estate_manager.vault import get_default_assets

FOUND = {
    "website": "coinbase.com",
    "legacy_policy_url": "https://help.coinbase.com/deceased",
    "summary": "Coinbase requires probate documents.",
    "tick_boxes": {
        "owner_can_appoint_successor": False,
        "heirs_can_request_access": True,
        "subscription_or_balance_addressed": None,
        "proof_required": True,
    },
    "checked": "2026-09-24",
}
NOT_FOUND = {
    "website": "spotify.com",
    "legacy_policy_url": "not found",
    "summary": "none",
    "tick_boxes": dict.fromkeys(FOUND["tick_boxes"]),
    "checked": "2026-09-24",
}


@pytest.fixture
def policy_file(tmp_path, monkeypatch):
    path = tmp_path / "policies.json"
    path.write_text(json.dumps([FOUND, NOT_FOUND]), encoding="utf-8")
    monkeypatch.setattr(legacy, "LEGACY_POLICY_FILE", path)
    return path


def test_record_is_found_by_exact_website_only(policy_file):
    assert (
        legacy.legacy_record("https://www.Coinbase.com/x")["website"] == "coinbase.com"
    )
    # matching is by exact host, no guessing
    assert legacy.legacy_record("https://drive.google.com") is None
    assert legacy.legacy_record("Coinbase") is None  # a name is not a website
    assert legacy.legacy_record("") is None
    assert legacy.legacy_record(None) is None


def test_missing_or_broken_file_changes_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(legacy, "LEGACY_POLICY_FILE", tmp_path / "missing.json")
    assert legacy.legacy_record("https://coinbase.com") is None
    broken = tmp_path / "broken.json"
    broken.write_text("{oops", encoding="utf-8")
    monkeypatch.setattr(legacy, "LEGACY_POLICY_FILE", broken)
    assert legacy.legacy_record("https://coinbase.com") is None


def test_found_record_is_applied_and_flagged_as_ai_generated():
    base = DeathPolicy(
        summary="Old text.",
        required_documents=["Death Certificate"],
        security_warning="Beware of fraud.",
        data_disposition="transfer_to_heir",
        supports_legacy_contact=True,
    )
    policy = legacy.apply_legacy_record(base, FOUND)
    assert policy.ai_generated and policy.policy_found is True
    assert policy.summary == "Coinbase requires probate documents."
    assert policy.official_portal_url == "https://help.coinbase.com/deceased"
    assert policy.source_checked == "2026-09-24"
    assert policy.tick_boxes["proof_required"] is True
    # the page says owners cannot name a successor
    assert policy.supports_legacy_contact is False
    # hand-written fields survive, and the original object is not modified
    assert policy.required_documents == ["Death Certificate"]
    assert (
        policy.security_warning == "Beware of fraud."
        and policy.data_disposition == "transfer_to_heir"
    )
    assert base.summary == "Old text." and not base.ai_generated


def test_not_found_says_so_and_keeps_the_existing_link():
    base = DeathPolicy(
        summary="Unsourced claim.", official_portal_url="https://example.com/maybe"
    )
    policy = legacy.apply_legacy_record(base, NOT_FOUND)
    assert policy.ai_generated and policy.policy_found is False
    assert policy.summary == legacy.NOT_FOUND_TEXT
    # the existing link stays as a possibly useful one
    assert policy.official_portal_url == "https://example.com/maybe"
    assert legacy.apply_legacy_record(base, None) is base  # no record: untouched


def test_get_policies_for_service_applies_the_saved_record(policy_file):
    death, cancel = get_policies_for_service("Coinbase", "https://coinbase.com")
    assert death.ai_generated and death.summary == FOUND["summary"]
    assert cancel.action_name  # cancellation stays as it was
    death, _ = get_policies_for_service("Spotify", "https://spotify.com")
    # not found, but the hand-written link is kept
    assert death.policy_found is False and death.official_portal_url
    death, _ = get_policies_for_service("Unknown Co", "https://unknown.example")
    assert not death.ai_generated


def test_demo_assets_pick_up_saved_records(policy_file):
    assets = {a.service: a for a in get_default_assets()}
    assert assets["Coinbase"].death_policy.ai_generated
    assert assets["Spotify"].death_policy.policy_found is False


def test_marks_and_table_row(policy_file):
    marks = dict(legacy.policy_marks(FOUND["tick_boxes"]))
    assert marks["Heirs can request access"] == "✔"
    assert marks["Owner can name a successor"] == "✘"
    assert marks["Subscription or balance covered"] == "–"
    coinbase = next(a for a in get_default_assets() if a.service == "Coinbase")
    row = legacy.policy_table_row(coinbase)
    assert row["Source"] == "🤖 AI crawler" and row["Checked"] == "2026-09-24"
    assert row["Link"] == "https://help.coinbase.com/deceased"
    assert row["Heirs can request access"] == "✔"


def test_old_records_are_marked_stale():
    today = date(2026, 9, 24)
    assert legacy.days_since_checked("2026-09-14", today) == 10
    assert not legacy.is_stale("2026-09-14", today)
    assert not legacy.is_stale("2026-06-26", today)  # exactly 90 days: still fresh
    assert legacy.is_stale("2026-06-25", today)
    assert not legacy.is_stale(None, today) and not legacy.is_stale("garbage", today)
    old = DeathPolicy(summary="x", source_checked="2020-01-01", ai_generated=True)
    asset = next(a for a in get_default_assets() if a.service == "Coinbase")
    row = legacy.policy_table_row(asset.model_copy(update={"death_policy": old}))
    assert row["Checked"].endswith("⚠️ old")


def test_provider_key():
    assert legacy.provider_key("https://www.drive.google.com/x") == "drive.google.com"
    assert legacy.provider_key("Spotify") == ""


def test_refresh_reports_success_or_a_friendly_problem(policy_file, monkeypatch):
    calls = []

    def fake_lookup(website, refresh=False, path=None, trace=None):
        calls.append((website, refresh, path))
        return FOUND

    monkeypatch.setattr(legacy_policy_crawler, "lookup_legacy_policy", fake_lookup)
    # None means the record was saved
    assert legacy.refresh_legacy_policy("https://coinbase.com") is None
    assert calls == [("https://coinbase.com", True, str(policy_file))]

    unsaved = {
        **NOT_FOUND,
        "summary": "newsite.com could not be reached (ConnectError).",
    }
    monkeypatch.setattr(
        legacy_policy_crawler, "lookup_legacy_policy", lambda *a, **k: unsaved
    )
    assert "could not be reached" in legacy.refresh_legacy_policy("https://newsite.com")

    def no_token(*args, **kwargs):
        raise AuthError("SWISSCOM_API_KEY is empty")

    monkeypatch.setattr(legacy_policy_crawler, "lookup_legacy_policy", no_token)
    assert "SWISSCOM_API_KEY is empty" in legacy.refresh_legacy_policy(
        "https://coinbase.com"
    )
