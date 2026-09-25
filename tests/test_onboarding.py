"""Guided onboarding (DLV_ONBOARDING=1): landing -> connect -> analyse -> reveal -> dashboard."""

import io
import re
from pathlib import Path

import pytest

from digital_estate_manager.config import onboarding_enabled

st_testing = pytest.importorskip("streamlit.testing.v1")

ROOT = Path(__file__).resolve().parents[1]
APP = str(ROOT / "app.py")
DEMO = ROOT / "samples" / "demo_transactions.jsonl"
EMOJI = re.compile("[\U0001F000-\U0001FAFF⌀-⏿☀-➿⬀-⯿️]")


@pytest.mark.parametrize("value, expected", [
    ("1", True), ("true", True), (" Yes ", True), ("on", True),
    ("", False), ("0", False), ("false", False), ("off", False),
])
def test_flag(monkeypatch, value, expected):
    monkeypatch.setenv("DLV_ONBOARDING", value)
    assert onboarding_enabled() is expected


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv("DLV_ONBOARDING", "1")
    monkeypatch.setenv("SWISSCOM_API_KEY", "")
    monkeypatch.setenv("SWISSCOM_BASE_URL", "")
    return st_testing.AppTest.from_file(APP, default_timeout=120).run()


def text(at) -> str:
    return "\n".join(m.value for m in at.markdown)


def assert_clean(at):
    assert not at.exception, at.exception
    assert not EMOJI.search(text(at)), EMOJI.findall(text(at))


def test_landing_starts_with_an_empty_vault(app):
    assert_clean(app)
    assert "Know what you leave behind." in text(app)
    assert app.session_state["assets"] == []


def test_full_flow_reaches_the_dashboard(app):
    app.button(key="onb_start").click().run()
    assert_clean(app)
    assert "Connect your sources" in text(app)
    assert app.button(key="onb_analyse").disabled

    # AppTest cannot drive a file uploader: hand the statement over as "Analyse" would.
    statement = io.BytesIO(DEMO.read_bytes())
    statement.name = DEMO.name
    app.session_state["onb_file"] = statement
    app.session_state["onboarding"] = "analyse"
    app.run()
    assert_clean(app)

    # No LLM in tests: the app offers rules only, then shows the magic moment.
    app.button(key="onb_rules_only").click().run()
    assert_clean(app)
    assert app.session_state["onboarding"] == "reveal"
    found = [a for a in app.session_state["assets"] if a.status != "Removed"]
    assert found
    assert f'--to:{len(found)}' in text(app)

    app.button(key="onb_open").click().run()
    assert_clean(app)
    assert app.session_state["onboarding"] == "done"
    assert app.session_state["active_page"] == "Assets"
    assert 'class="dlv-kpis"' in text(app)
    assert app.title[0].value == "Accounts and subscriptions"


def test_executor_sees_the_estate_after_the_owner_scanned(app):
    """The pitch's second half: same session, 'View as' switched to Executor."""
    assert "Yearly reminder on" not in text(app)
    statement = io.BytesIO(DEMO.read_bytes())
    statement.name = DEMO.name
    app.session_state["onb_file"] = statement
    app.session_state["onboarding"] = "analyse"
    app.run()
    app.button(key="onb_rules_only").click().run()
    assert "Yearly reminder on" in text(app)
    app.button(key="onb_open").click().run()

    app.session_state["role"] = "Executor"
    app.run()
    assert_clean(app)
    assert app.title[0].value == "Estate overview"
    assert 'class="dlv-kpis"' not in text(app)
