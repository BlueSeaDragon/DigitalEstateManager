"""Cancellation guide in the app: owner and executor open it and get the researched policy (engine mocked)."""

from pathlib import Path
from types import SimpleNamespace

import pytest

st_testing = pytest.importorskip("streamlit.testing.v1")
pytest.importorskip("openai")

from cancel_policy_finder import rag_engine  # noqa: E402

APP = str(Path(__file__).resolve().parents[1] / "app.py")
RAW = {
    "primary_channel": "registered_letter",
    "channel_instructions": ["Write the letter", "Send it by registered mail"],
    "mailing_address": "Provider AG\nPostfach\n8000 Zürich",
}


@pytest.fixture
def research(monkeypatch):
    """Replaces web search + Apertus; records (provider, plan, mode) of each research."""
    calls = []
    monkeypatch.setattr(rag_engine, "_query_policy", lambda provider, plan, mode: calls.append((provider, plan, mode)) or RAW)
    return calls


def open_assets(role: str):
    at = st_testing.AppTest.from_file(APP, default_timeout=60)
    at.session_state["onboarding"] = "done"
    at.session_state["role"] = role
    at.session_state["active_page"] = "Assets"
    return at.run()


def test_executor_gets_the_same_guide_with_after_death_research(research, monkeypatch):
    prompts = []
    letter = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="Betreff: Kündigung"))])
    monkeypatch.setattr(rag_engine, "SWISSCOM_API_KEY", "test-key")
    monkeypatch.setattr(rag_engine.client.chat.completions, "create",
                        lambda **kwargs: prompts.append(kwargs["messages"][1]["content"]) or letter)

    at = open_assets("Executor")
    at.text_input(key="deceased_name").input("Hans Muster").run()
    next(b for b in at.button if b.key and b.key.startswith("toggle_exe_")).click().run()
    cancel_key = next(b.key for b in at.button if b.key and b.key.endswith("_exec_cancel"))
    at.button(key=cancel_key).click().run()

    assert not at.exception
    assert research and research[0][2] == "after_death"
    # Same form as the owner: only the sender's name is needed
    assert [t.label for t in at.text_input if t.key and t.key.startswith("cxl_")] == [
        "Your full name", "Customer or contract number"]

    # The dialog stays open in the browser; AppTest reopens it with each action
    at.text_input(key=next(t.key for t in at.text_input if t.key.startswith("cxl_sender_"))).input("Anna Beispiel")
    at.button(key=cancel_key).click().run()
    write = next(b for b in at.button if b.key and b.key.startswith("cxl_write_"))
    assert not write.disabled
    write.click()
    at.button(key=cancel_key).click().run()
    assert not at.exception
    assert "Deceased account holder: Hans Muster" in prompts[-1]


def test_owner_opens_the_guide_in_during_life_mode(research):
    at = open_assets("Owner")
    next(b for b in at.button if b.key and b.key.startswith("toggle_")).click().run()
    next(b for b in at.button if b.key and b.key.endswith("_close")).click().run()

    assert not at.exception
    assert research and research[0][2] == "during_life"
    assert any(b.key and b.key.startswith("cxl_write_") for b in at.button)
