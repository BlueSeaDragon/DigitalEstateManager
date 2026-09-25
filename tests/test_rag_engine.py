"""RAG cancellation engine output -> webapp models (no network: the LLM and web search are mocked)."""

import sys
import typing
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("openai")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend import rag_engine  # noqa: E402
from digital_estate_manager.models import Asset, CancelPolicy, DeathPolicy  # noqa: E402
from digital_estate_manager.policies import generate_action_email, get_policies_for_service  # noqa: E402

EMAIL_RAW = {
    "minimum_contract_duration": "12 months",
    "notice_period": "2 months to the end of the month",
    "primary_channel": "email",
    "requires_sub_type_selection": False,
    "sub_type_options": [],
    "channel_instructions": ["Write to support@swisscom.ch", "Quote your customer number"],
    "portal_url": "https://www.swisscom.ch/de/privatkunden/hilfe.html",
    "contact_email": "support@swisscom.ch",
    "contact_phone": "0800 800 800",
    "mailing_address": "Swisscom (Schweiz) AG\nPostfach\n3050 Bern",
    "required_docs": ["Customer number", "customer number"],
}

DURING_LIFE_RAW = {
    "minimum_contract_duration": "12 months",
    "notice_period": "2 months",
    "primary_channel": "web_portal",
    "channel_instructions": ["Log in", "Cancel under Abos"],
    "portal_url": "https://www.spotify.com/account",
    "policy_url": "https://www.spotify.com/legal/end-user-agreement/",
    "contact_email": "",
    "required_docs": "Account email",
}


def test_email_channel_maps_to_cancel_policy():
    death, cancel = rag_engine.policies_from_rag(EMAIL_RAW, "Swisscom", "blue Mobile M")

    assert isinstance(death, DeathPolicy) and isinstance(cancel, CancelPolicy)
    assert cancel.execution_method == "email_notice"
    assert cancel.support_email == "support@swisscom.ch"
    assert cancel.target_url == "https://www.swisscom.ch/de/privatkunden/hilfe.html"
    assert cancel.steps == EMAIL_RAW["channel_instructions"]
    assert cancel.required_documents == ["Customer number"]
    assert cancel.action_payload["mode"] == "during_life"
    assert cancel.action_payload["sub_type"] == "blue Mobile M"
    assert cancel.action_payload["mailing_address"] == EMAIL_RAW["mailing_address"]


def test_after_death_is_disabled():
    """Posthumous policies come from the legacy policy crawler, not from this engine."""
    assert typing.get_args(rag_engine.Mode) == ("during_life",)
    _, cancel = rag_engine.policies_from_rag(EMAIL_RAW, "Swisscom")
    assert "legal_basis" not in cancel.action_payload
    assert "Erbenschein" not in cancel.required_documents


SOURCES = [
    "Title: Google One-Abo kündigen\nSnippet: So kündigen Sie ...\n"
    "URL: https://support.google.com/googleone/answer/9056360?hl=de-ch",
    "Title: Kauf, Kündigung und Erstattung\nSnippet: Fragen an googleone-support@google.com\n"
    "URL: https://support.google.com/googleone/answer/2736362?hl=de-DE",
]


def test_links_and_email_must_come_from_the_search_results():
    raw = {
        "portal_url": "https://support.google.com/googleone/answer/9056360",  # found (without query)
        "policy_url": "https://one.google.com/terms-of-service",  # invented
        "contact_email": "support@google.com",  # invented
        "_sources": SOURCES,
    }
    _, cancel = rag_engine.policies_from_rag(raw, "Google One")

    assert cancel.target_url == "https://support.google.com/googleone/answer/9056360?hl=de-ch"
    assert cancel.action_payload["policy_url"] is None
    assert cancel.support_email is None


def test_found_email_is_kept_and_homepages_are_dropped():
    raw = {
        "portal_url": "https://one.google.com/",
        "policy_url": "https://support.google.com/googleone/answer/2736362",
        "contact_email": "googleone-support@google.com",
        "_sources": SOURCES + ["Title: Google One\nSnippet: ...\nURL: https://one.google.com/"],
    }
    _, cancel = rag_engine.policies_from_rag(raw, "Google One")

    assert cancel.target_url is None
    assert cancel.action_payload["policy_url"] == "https://support.google.com/googleone/answer/2736362?hl=de-DE"
    assert cancel.support_email == "googleone-support@google.com"


def test_no_search_results_means_no_links():
    raw = {"portal_url": "https://www.spotify.com/account", "contact_email": "support@spotify.com", "_sources": []}
    _, cancel = rag_engine.policies_from_rag(raw, "Spotify")
    assert cancel.target_url is None and cancel.support_email is None


def test_registered_letter_maps_to_manual_steps():
    _, cancel = rag_engine.policies_from_rag({"primary_channel": "registered_letter"}, "Fitnesspark")
    assert cancel.execution_method == "manual_steps"
    assert cancel.action_payload["primary_channel"] == "registered_letter"


def test_during_life_keeps_known_death_policy_and_tolerates_messy_output():
    death, cancel = rag_engine.policies_from_rag(DURING_LIFE_RAW, "Spotify", mode="during_life")

    known_death, _ = get_policies_for_service("Spotify")
    assert death == known_death
    assert cancel.execution_method == "web_portal"
    assert cancel.target_url == "https://www.spotify.com/account"
    assert cancel.support_email is None
    assert cancel.required_documents == ["Account email"]
    assert "legal_basis" not in cancel.action_payload
    assert cancel.action_payload["notice_period"] == "2 months"
    assert cancel.action_payload["policy_url"] == "https://www.spotify.com/legal/end-user-agreement/"


def test_empty_rag_output_still_validates():
    death, cancel = rag_engine.policies_from_rag({"primary_channel": "fax"}, "Unknown Gym")

    assert cancel.execution_method == "manual_steps"
    assert cancel.target_url is None
    CancelPolicy.model_validate(cancel.model_dump())
    DeathPolicy.model_validate(death.model_dump())


def test_enrich_asset_and_letter_feed_the_webapp_dispatcher(monkeypatch):
    monkeypatch.setattr(rag_engine, "SWISSCOM_API_KEY", "test-key")
    monkeypatch.setattr(rag_engine, "_query_policy", lambda *args: EMAIL_RAW)
    letter = "Betreff: Kündigung {Vertrag 123}\n\nSehr geehrte Damen und Herren,"
    completion = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=letter))])
    monkeypatch.setattr(rag_engine.client.chat.completions, "create", lambda **kwargs: completion)

    death, cancel = get_policies_for_service("Swisscom")
    asset = Asset(service="Swisscom", username="anna@example.ch", death_policy=death, cancel_policy=cancel)
    rag_engine.enrich_asset(asset, sub_type="blue Mobile M")
    assert asset.cancel_policy.support_email == "support@swisscom.ch"
    Asset.model_validate(asset.model_dump())

    returned = rag_engine.generate_cancellation_letter(
        "Swisscom", "blue Mobile M", "Anna Muster", "123", "during_life", asset.cancel_policy
    )
    assert returned == letter
    assert letter in generate_action_email(asset)


def test_missing_api_key_raises_engine_error(monkeypatch):
    monkeypatch.setattr(rag_engine, "SWISSCOM_API_KEY", "")
    with pytest.raises(rag_engine.CancellationEngineError, match="SWISSCOM_API_KEY"):
        rag_engine.search_web_cancellation_policy("Swisscom")


def test_api_failure_raises_engine_error(monkeypatch):
    monkeypatch.setattr(rag_engine, "SWISSCOM_API_KEY", "test-key")
    monkeypatch.setattr(rag_engine, "fetch_web_results_safe", lambda query: [])
    monkeypatch.setattr(rag_engine.time, "sleep", lambda seconds: None)

    def fail(**kwargs):
        raise ConnectionError("offline")

    monkeypatch.setattr(rag_engine.client.chat.completions, "create", fail)
    with pytest.raises(rag_engine.CancellationEngineError):
        rag_engine.search_web_cancellation_policy("Swisscom")
