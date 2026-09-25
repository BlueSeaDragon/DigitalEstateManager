"""Streamlit AppTest smoke tests: every page renders for both roles, without emojis."""

import re
from pathlib import Path

import pytest

st_testing = pytest.importorskip("streamlit.testing.v1")

APP = str(Path(__file__).resolve().parents[1] / "app.py")

EMOJI = re.compile(
    "[\U0001F000-\U0001FAFF⌀-⏿☀-➿⬀-⯿️]"
)


def rendered_text(at) -> str:
    """All element protos of the main area and sidebar as text."""
    parts = []

    def walk(node):
        proto = getattr(node, "proto", None)
        if proto is not None:
            parts.append(str(proto))
        for child in getattr(node, "children", {}).values():
            walk(child)

    walk(at.main)
    walk(at.sidebar)
    return "\n".join(parts)


@pytest.fixture
def app(monkeypatch):
    # No LLM in tests: the finder raises LLMConfigError and the app offers rules only.
    monkeypatch.setenv("SWISSCOM_API_KEY", "")
    monkeypatch.setenv("SWISSCOM_BASE_URL", "")
    return st_testing.AppTest.from_file(APP, default_timeout=60).run()


def goto(at, page):
    at.sidebar.radio(key="active_page").set_value(page).run()
    return at


def assert_clean(at):
    assert not at.exception, at.exception
    text = rendered_text(at)
    assert not EMOJI.search(text), EMOJI.findall(text)
    assert "$" not in "".join(m.value for m in at.markdown)


@pytest.mark.parametrize("role", ["Owner", "Executor"])
@pytest.mark.parametrize("page", ["Overview", "Assets", "Discover"])
def test_pages_render_without_emoji(app, page, role):
    app.segmented_control(key="role").set_value(role).run()
    goto(app, page)
    assert_clean(app)


def test_overview_before_scan_offers_the_scan(app):
    assert_clean(app)
    assert app.title[0].value == "Know what you leave behind."
    assert any(b.label == "Scan my digital footprint" for b in app.button)


def test_owner_details_show_actions(app):
    goto(app, "Assets")
    app.button(key=next(b.key for b in app.button if b.key and b.key.startswith("toggle_own_"))).click().run()
    assert_clean(app)
    labels = {b.label for b in app.button}
    assert "Cancel subscription" in labels and "Remove" in labels


def test_executor_details_show_notification_letter(app):
    app.segmented_control(key="role").set_value("Executor").run()
    goto(app, "Assets")
    app.text_input(key="deceased_name").input("Anna Muster").run()
    app.button(key=next(b.key for b in app.button if b.key and b.key.startswith("toggle_exe_"))).click().run()
    assert_clean(app)
    letter = next(t for t in app.text_area if t.key.startswith("exec_notice_"))
    assert "Anna Muster" in letter.value


def test_demo_scan_rules_only_adds_reviewable_findings(app):
    before = len(app.session_state["assets"])
    goto(app, "Discover")
    app.button(key="scan_demo").click().run()
    # Without an LLM key the app asks before falling back to rules only.
    app.button(key="disc_rules_only_btn").click().run()
    assert_clean(app)

    assets = app.session_state["assets"]
    found = assets[before:]
    assert found, "the demo dataset should produce findings"
    assert all(not a.user_verified and a.evidence for a in found)
    assert {a.review_label for a in found} >= {"Likely", "Needs review"}

    goto(app, "Overview")
    assert_clean(app)
    assert any(b.label.startswith("Review ") for b in app.button)
