"""The owner's wish dropdown on an account card, driven through the real app."""

import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from digital_estate_manager.vault import storage

APP = str(Path(__file__).resolve().parents[1] / "app.py")
PICKER = "Your wish after death"
OTHER_TEXT = "Your wish, in a few words"


@pytest.fixture(autouse=True)
def normal_app(monkeypatch):
    monkeypatch.setenv("DLV_ONBOARDING", "0")  # a local .env may turn the guided onboarding on


@pytest.fixture
def owner_card(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "WISH_FILE", tmp_path / "wishes.json")
    at = AppTest.from_file(APP, default_timeout=60).run()
    at.sidebar.radio[0].set_value("Assets").run()
    next(b for b in at.button if b.label == "Details").click().run()
    return at


def test_dropdown_saves_the_wish(owner_card):
    picker = next(s for s in owner_card.selectbox if s.label == PICKER)
    picker.select("Memorialize").run()
    assert not owner_card.exception
    assert "Memorialize" in json.loads(storage.WISH_FILE.read_text(encoding="utf-8")).values()


def test_other_shows_a_short_text_box_and_saves_it(owner_card):
    next(s for s in owner_card.selectbox if s.label == PICKER).select("Other").run()
    next(t for t in owner_card.text_input if t.label == OTHER_TEXT).set_value("give the photos to my sister").run()
    assert not owner_card.exception
    saved = json.loads(storage.WISH_FILE.read_text(encoding="utf-8")).values()
    assert "Other: give the photos to my sister" in saved


def test_table_view_still_renders(owner_card):
    next(t for t in owner_card.toggle if t.label == "Table view").set_value(True).run()
    assert not owner_card.exception


def test_executor_details_have_no_generated_action_line(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "WISH_FILE", tmp_path / "wishes.json")
    at = AppTest.from_file(APP, default_timeout=60).run()
    at.sidebar.radio[0].set_value("Assets").run()
    at.session_state["role"] = "Executor"
    at.run()
    next(b for b in at.button if b.label == "Details").click().run()
    assert not at.exception
    assert "<dt>Action</dt>" not in " ".join(m.value for m in at.markdown)
