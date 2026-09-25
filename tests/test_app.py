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
    monkeypatch.setenv("DLV_ONBOARDING", "0")  # a local .env may turn the guided onboarding on
    return st_testing.AppTest.from_file(APP, default_timeout=60).run()


def goto(at, page):
    at.sidebar.radio[0].set_value(page).run()
    return at


def set_role(at, role):
    at.segmented_control(key="role").set_value(role).run()
    return at


def assert_clean(at):
    assert not at.exception, at.exception
    text = rendered_text(at)
    assert not EMOJI.search(text), EMOJI.findall(text)
    assert "$" not in "".join(m.value for m in at.markdown)


@pytest.mark.parametrize("role", ["Owner", "Executor"])
@pytest.mark.parametrize("page", ["Assets", "Discover"])
def test_pages_render_without_emoji(app, page, role):
    set_role(app, role)
    goto(app, page)
    assert_clean(app)


def test_inventory_is_the_start_page_and_offers_the_scan(app):
    assert_clean(app)
    assert app.session_state["active_page"] == "Assets"
    assert app.title[0].value == "Accounts and subscriptions"
    assert any(b.label == "Scan my digital footprint" for b in app.button)
    assert any(b.key.startswith("toggle_own_") for b in app.button if b.key)


def test_executor_view_is_marked_and_relabelled(app):
    assert "Owner view" in rendered_text(app)
    set_role(app, "Executor")
    assert_clean(app)
    text = rendered_text(app)
    assert "Executor view" in text and "Worklist" in text
    assert app.title[0].value == "Estate overview"
    app.text_input(key="deceased_name").input("Anna Muster").run()
    assert app.title[0].value == "Estate of Anna Muster"


def test_owner_details_show_actions(app):
    goto(app, "Assets")
    app.button(key=next(b.key for b in app.button if b.key and b.key.startswith("toggle_own_"))).click().run()
    assert_clean(app)
    labels = {b.label for b in app.button}
    assert "Cancel subscription" in labels and "Remove" in labels


def test_executor_details_have_no_generated_guidance(app):
    set_role(app, "Executor")
    app.button(key=next(b.key for b in app.button if b.key and b.key.startswith("toggle_exe_"))).click().run()
    assert_clean(app)
    text = rendered_text(app)
    assert not any(t.key and t.key.startswith("exec_notice_") for t in app.text_area)
    for removed in ("Notification letter", "Checklist", "Documents:"):
        assert removed not in text


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

    goto(app, "Assets")
    assert_clean(app)
    app.button(key="btn_review").click().run()
    assert_clean(app)
    assert app.segmented_control(key="owner_filter").value == "To review"
