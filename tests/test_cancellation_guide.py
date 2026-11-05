"""Cancellation guide in the app: owner and executor open it and get the researched policy (engine mocked)."""

from pathlib import Path

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


def test_executor_opens_the_guide_in_after_death_mode(research):
    at = open_assets("Executor")
    next(b for b in at.button if b.key and b.key.startswith("toggle_exe_")).click().run()
    next(b for b in at.button if b.key and b.key.endswith("_exec_cancel")).click().run()

    assert not at.exception
    assert research and research[0][2] == "after_death"
    # The deceased's name comes from onboarding; the executor only enters their own name
    assert not any(t.key and t.key.startswith("cxl_deceased_") for t in at.text_input)
    write = next(b for b in at.button if b.key and b.key.startswith("cxl_write_"))
    assert write.disabled and write.help == "Enter your name first."


def test_owner_opens_the_guide_in_during_life_mode(research):
    at = open_assets("Owner")
    next(b for b in at.button if b.key and b.key.startswith("toggle_")).click().run()
    next(b for b in at.button if b.key and b.key.endswith("_close")).click().run()

    assert not at.exception
    assert research and research[0][2] == "during_life"
    assert any(b.key and b.key.startswith("cxl_write_") for b in at.button)
