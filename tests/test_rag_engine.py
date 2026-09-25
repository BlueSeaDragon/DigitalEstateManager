"""RAG cancellation engine output -> webapp models (no network: the LLM and web search are mocked)."""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("openai")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend import rag_engine  # noqa: E402
from digital_estate_manager.models import Asset, CancelPolicy, DeathPolicy  # noqa: E402
from digital_estate_manager.policies import generate_action_email, get_policies_for_service  # noqa: E402

AFTER_DEATH_RAW = {
    "minimum_contract_duration": "Immediate (upon notification of death)",
    "notice_period": "Immediate (upon notification of death)",
    "primary_channel": "email",
    "requires_sub_type_selection": False,
    "sub_type_options": [],
    "channel_instructions": ["Send the letter to support@swisscom.ch", "Attach the Todesurkunde"],
    "portal_url": "https://www.swisscom.ch/de/privatkunden/hilfe.html",
    "contact_email": "support@swisscom.ch",
    "contact_phone": "0800 800 800",
    "mailing_address": "Swisscom (Schweiz) AG\nPostfach\n3050 Bern",
    "required_docs": ["Todesurkunde (Death Certificate)"],
    "has_mourning_portal": True,
    "mourning_portal_url": "https://www.swisscom.ch/de/todesfall",
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


def test_after_death_maps_to_schemas_with_swiss_documents():
    death, cancel = rag_engine.policies_from_rag(AFTER_DEATH_RAW, "Swisscom", "inOne", "after_death")

    assert isinstance(death, DeathPolicy) and isinstance(cancel, CancelPolicy)
    assert cancel.execution_method == "email_notice"
    assert cancel.support_email == "support@swisscom.ch"
    assert cancel.target_url == "https://www.swisscom.ch/de/todesfall"
    assert cancel.steps == AFTER_DEATH_RAW["channel_instructions"]
    assert cancel.required_documents == ["Todesurkunde (Death Certificate)", "Erbenschein"]
    assert cancel.action_payload["legal_basis"] == "OR Art. 405"
    assert cancel.action_payload["mailing_address"] == AFTER_DEATH_RAW["mailing_address"]

    assert "OR Art. 405" in death.summary
    assert death.required_documents == cancel.required_documents
    assert death.official_portal_url == "https://www.swisscom.ch/de/todesfall"


def test_after_death_adds_missing_documents_and_keeps_alternate_spellings():
    raw = {"required_docs": ["Erbschein", "Kopie ID"], "primary_channel": "registered_letter"}
    _, cancel = rag_engine.policies_from_rag(raw, "SBB", mode="after_death")

    assert cancel.required_documents == ["Erbschein", "Kopie ID", "Todesurkunde (Death Certificate)"]
    assert cancel.execution_method == "manual_steps"


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


@pytest.mark.parametrize("mode", ["during_life", "after_death"])
def test_empty_rag_output_still_validates(mode):
    death, cancel = rag_engine.policies_from_rag({"primary_channel": "fax"}, "Unknown Gym", mode=mode)

    assert cancel.execution_method == "manual_steps"
    assert cancel.target_url is None
    CancelPolicy.model_validate(cancel.model_dump())
    DeathPolicy.model_validate(death.model_dump())


def test_enrich_asset_and_letter_feed_the_webapp_dispatcher(monkeypatch):
    monkeypatch.setattr(rag_engine, "SWISSCOM_API_KEY", "test-key")
    monkeypatch.setattr(rag_engine, "_query_policy", lambda *args: AFTER_DEATH_RAW)
    letter = "Betreff: Kündigung {Vertrag 123}\n\nSehr geehrte Damen und Herren,"
    completion = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=letter))])
    monkeypatch.setattr(rag_engine.client.chat.completions, "create", lambda **kwargs: completion)

    death, cancel = get_policies_for_service("Swisscom")
    asset = Asset(service="Swisscom", username="anna@example.ch", death_policy=death, cancel_policy=cancel)
    rag_engine.enrich_asset(asset, mode="after_death", sub_type="inOne")
    assert asset.cancel_policy.action_payload["legal_basis"] == "OR Art. 405"
    Asset.model_validate(asset.model_dump())

    returned = rag_engine.generate_cancellation_letter(
        "Swisscom", "inOne", "Anna Muster", "123", "after_death", asset.cancel_policy, asset.death_policy
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
        rag_engine.search_web_cancellation_policy("Swisscom", mode="after_death")
