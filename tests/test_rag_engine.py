"""RAG cancellation engine output -> webapp models (no network: the LLM and web search are mocked)."""

import sys
import typing
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cancel_policy_finder import rag_engine  # noqa: E402
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



def test_numbers_in_front_of_the_steps_are_dropped():
    """The guide numbers the steps itself, so "1. Open" would show as "1. 1. Open"."""
    raw = dict(EMAIL_RAW, channel_instructions=[
        "1. Open the SBB page",
        "2) Use the form",
        "Step 3: Send an email",
        "Schritt 4 - Anhang beifügen",
        "Note: Keep the confirmation.",
        "24/7 support is available",
        "1.5 GB of photos stay in the account",
        "7.",
    ])
    _, cancel = rag_engine.policies_from_rag(raw, "SBB", "GA")

    assert cancel.steps == [
        "Open the SBB page",
        "Use the form",
        "Send an email",
        "Anhang beifügen",
        "Note: Keep the confirmation.",
        "24/7 support is available",
        "1.5 GB of photos stay in the account",
        "7.",
    ]

AFTER_DEATH_RAW = {
    "notice_period": "Immediate (upon notification of death)",
    "primary_channel": "email",
    "channel_instructions": ["Send the letter to support@swisscom.ch", "Attach the Todesurkunde"],
    "portal_url": "https://www.swisscom.ch/de/privatkunden/hilfe.html",
    "contact_email": "support@swisscom.ch",
    "required_docs": ["Todesurkunde (Death Certificate)"],
    "has_mourning_portal": True,
    "mourning_portal_url": "https://www.swisscom.ch/de/todesfall",
}


def test_after_death_maps_to_schemas_with_swiss_documents():
    death, cancel = rag_engine.policies_from_rag(AFTER_DEATH_RAW, "Swisscom", "inOne", "after_death")

    assert typing.get_args(rag_engine.Mode) == ("during_life", "after_death")
    assert cancel.execution_method == "email_notice"
    assert cancel.target_url == "https://www.swisscom.ch/de/todesfall"
    assert cancel.required_documents == ["Todesurkunde (Death Certificate)", "Erbenschein"]
    assert cancel.action_payload["legal_basis"] == "OR Art. 405"
    assert cancel.action_payload["mode"] == "after_death"
    assert "OR Art. 405" in death.summary
    assert death.official_portal_url == "https://www.swisscom.ch/de/todesfall"


def test_after_death_adds_missing_documents_and_keeps_alternate_spellings():
    raw = {"required_docs": ["Erbschein", "Kopie ID"], "primary_channel": "registered_letter"}
    _, cancel = rag_engine.policies_from_rag(raw, "SBB", mode="after_death")
    assert cancel.required_documents == ["Erbschein", "Kopie ID", "Todesurkunde (Death Certificate)"]


def test_after_death_mourning_portal_must_come_from_the_search_results():
    raw = dict(AFTER_DEATH_RAW, _sources=["Title: Hilfe\nSnippet: support@swisscom.ch\nURL: https://www.swisscom.ch/de/privatkunden/hilfe.html"])
    _, cancel = rag_engine.policies_from_rag(raw, "Swisscom", mode="after_death")
    assert cancel.action_payload["mourning_portal_url"] is None
    assert cancel.target_url == "https://www.swisscom.ch/de/privatkunden/hilfe.html"


def test_during_life_has_no_after_death_rules():
    _, cancel = rag_engine.policies_from_rag(EMAIL_RAW, "Swisscom")
    assert "legal_basis" not in cancel.action_payload
    assert "Erbenschein" not in cancel.required_documents


@pytest.fixture(autouse=True)
def saved_policies(monkeypatch, tmp_path):
    """Saved answers go to a temporary file, never to the real data/ folder."""
    path = tmp_path / "cancel_policies_saved.json"
    monkeypatch.setattr(rag_engine, "SAVED_POLICIES_FILE", path)
    monkeypatch.setattr(rag_engine, "SAVED_LETTERS_FILE", tmp_path / "cancel_letters_saved.json")
    return path


def test_after_death_letter_is_written_by_the_executor_for_the_deceased(monkeypatch):
    prompts = []

    def ask(prompt, system, timeout=None):
        prompts.append(prompt)
        return "Betreff: Kündigung"

    monkeypatch.setattr(rag_engine.claude_cli, "ask", ask)
    _, cancel = rag_engine.policies_from_rag(AFTER_DEATH_RAW, "Swisscom", mode="after_death")
    rag_engine.generate_cancellation_letter(
        "Swisscom", "inOne", "Anna Muster", "123", "after_death", cancel, deceased_name="Hans Muster"
    )
    assert "Deceased account holder: Hans Muster" in prompts[0]
    assert "OR Art. 405" in prompts[0]


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
    monkeypatch.setattr(rag_engine, "_query_policy", lambda *args: EMAIL_RAW)
    letter = "Betreff: Kündigung {Vertrag 123}\n\nSehr geehrte Damen und Herren,"
    monkeypatch.setattr(rag_engine.claude_cli, "ask", lambda prompt, system, timeout=None: letter)

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


def _fail(error):
    def ask_json(prompt, system, timeout=None):
        raise error

    return ask_json


def test_logged_out_claude_raises_engine_error(monkeypatch):
    monkeypatch.setattr(rag_engine, "fetch_web_results_safe", lambda query: SOURCES)
    monkeypatch.setattr(rag_engine.claude_cli, "ask_json", _fail(rag_engine.claude_cli.ClaudeCLIUnavailable("not logged in")))
    with pytest.raises(rag_engine.CancellationEngineError, match="not logged in"):
        rag_engine.search_web_cancellation_policy("Swisscom")


def test_claude_is_tried_once_with_a_short_timeout_then_raises_engine_error(monkeypatch):
    monkeypatch.setattr(rag_engine, "fetch_web_results_safe", lambda query: [])
    calls = []

    def ask_json(prompt, system, timeout):
        calls.append(timeout)
        raise rag_engine.claude_cli.ClaudeCLIError("offline")

    monkeypatch.setattr(rag_engine.claude_cli, "ask_json", ask_json)
    with pytest.raises(rag_engine.CancellationEngineError, match="offline"):
        rag_engine.search_web_cancellation_policy("Swisscom")
    assert calls == [rag_engine.CLAUDE_TIMEOUT] and rag_engine.CLAUDE_TIMEOUT <= 60


def test_letter_falls_back_to_the_template_when_claude_fails(monkeypatch):
    def fail(prompt, system, timeout):
        raise rag_engine.claude_cli.ClaudeCLIError("Claude did not answer within 45 s.")

    monkeypatch.setattr(rag_engine.claude_cli, "ask", fail)
    _, cancel = rag_engine.policies_from_rag(AFTER_DEATH_RAW, "Swisscom", mode="after_death")
    letter = rag_engine.generate_cancellation_letter(
        "Swisscom", "inOne", "Anna Muster", "123", "after_death", cancel, deceased_name="Hans Muster"
    )
    assert letter.startswith("Betreff: Kündigung Swisscom «inOne», Vertragsnummer 123")
    assert "Sehr geehrte Damen und Herren," in letter
    assert "Hans Muster verstorben" in letter and "OR Art. 405" in letter and "Todesurkunde" in letter
    assert letter.endswith("Mit freundlichen Grüssen,\nAnna Muster")
    assert cancel.email_template == letter

    during = rag_engine.generate_cancellation_letter(
        "Spotify", "subscription", "Martina Keller", "-", "during_life", cancel
    )
    assert during.startswith("Betreff: Kündigung Spotify\n")
    assert "Vertragsnummer" not in during and "verstorben" not in during


def test_researched_policy_is_saved_and_used_when_a_later_lookup_fails(monkeypatch, saved_policies):
    monkeypatch.setattr(rag_engine, "fetch_web_results_safe", lambda query: SOURCES)
    monkeypatch.setattr(rag_engine.claude_cli, "ask_json", lambda prompt, system, timeout=None: dict(EMAIL_RAW))
    first = rag_engine._query_policy("Google One", "subscription", "during_life")
    assert first["_sources"] == SOURCES
    assert saved_policies.exists()

    monkeypatch.setattr(rag_engine.claude_cli, "ask_json", _fail(rag_engine.claude_cli.ClaudeCLIError("offline")))
    assert rag_engine._query_policy("Google One", "subscription", "during_life") == first

    # no search results: the saved answer is used without asking Claude
    monkeypatch.setattr(rag_engine, "fetch_web_results_safe", lambda query: [])
    monkeypatch.setattr(rag_engine.claude_cli, "ask_json", _fail(AssertionError("Claude was asked")))
    assert rag_engine._query_policy("Google One", "subscription", "during_life") == first


def test_answers_without_search_results_are_not_saved(monkeypatch, saved_policies):
    monkeypatch.setattr(rag_engine, "fetch_web_results_safe", lambda query: [])
    monkeypatch.setattr(rag_engine.claude_cli, "ask_json", lambda prompt, system, timeout=None: dict(EMAIL_RAW))
    rag_engine._query_policy("Swisscom", "subscription", "during_life")
    assert not saved_policies.exists()


CLAUDE_LETTER = (
    "Betreff: Kündigung Swisscom inOne, Vertragsnummer 123\n\n"
    "Sehr geehrte Damen und Herren,\n\n"
    "im Namen der Erben von Hans Muster kündige ich den Vertrag 123 gemäss OR Art. 405.\n\n"
    "Mit freundlichen Grüssen,\nAnna Muster"
)


def _write_letter(sender="Anna Muster", contract="123", deceased="Hans Muster"):
    _, cancel = rag_engine.policies_from_rag(AFTER_DEATH_RAW, "Swisscom", mode="after_death")
    return rag_engine.generate_cancellation_letter(
        "Swisscom", "inOne", sender, contract, "after_death", cancel, deceased_name=deceased
    )


def _claude_fails(monkeypatch):
    def fail(prompt, system, timeout=None):
        raise rag_engine.claude_cli.ClaudeCLIError("offline")

    monkeypatch.setattr(rag_engine.claude_cli, "ask", fail)


def test_claude_letter_is_saved_without_personal_details_and_refilled_later(monkeypatch):
    monkeypatch.setattr(rag_engine.claude_cli, "ask", lambda prompt, system, timeout=None: CLAUDE_LETTER)
    assert _write_letter() == CLAUDE_LETTER
    saved = rag_engine.SAVED_LETTERS_FILE.read_text(encoding="utf-8")
    assert "Muster" not in saved and "123" not in saved
    assert "[[SENDER]]" in saved and "[[DECEASED]]" in saved and "[[CONTRACT]]" in saved

    _claude_fails(monkeypatch)
    letter = _write_letter("Eva Beispiel", "987", "Martina Keller")
    assert letter == (
        "Betreff: Kündigung Swisscom inOne, Vertragsnummer 987\n\n"
        "Sehr geehrte Damen und Herren,\n\n"
        "im Namen der Erben von Martina Keller kündige ich den Vertrag 987 gemäss OR Art. 405.\n\n"
        "Mit freundlichen Grüssen,\nEva Beispiel"
    )

    # the saved letter needs a contract number: without one the template is used
    assert "Vertragsnummer" not in _write_letter("Eva Beispiel", "-", "Martina Keller")


def test_letter_with_a_leftover_name_part_is_not_saved(monkeypatch):
    letter = CLAUDE_LETTER.replace("Hans Muster", "Herrn Muster")
    monkeypatch.setattr(rag_engine.claude_cli, "ask", lambda prompt, system, timeout=None: letter)
    _write_letter()
    assert not rag_engine.SAVED_LETTERS_FILE.exists()
