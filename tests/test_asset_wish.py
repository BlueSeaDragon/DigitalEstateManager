"""Tests for the owner's after-death wish: the field, the table round trip and saving to data/wishes.json."""

import pytest

from digital_estate_manager.models import Asset
from digital_estate_manager.vault import get_default_assets, save_wishes, storage


@pytest.fixture(autouse=True)
def wish_file(tmp_path, monkeypatch):
    path = tmp_path / "wishes.json"
    monkeypatch.setattr(storage, "WISH_FILE", path)
    return path


def coinbase():
    return next(a for a in get_default_assets() if a.service == "Coinbase")


def test_wish_is_optional_and_empty_by_default():
    row = {"Service": "Netflix", "Service Address": "https://netflix.com"}
    assert Asset.from_table_row(row).wish == ""


def test_wish_survives_the_table_round_trip():
    row = coinbase().to_table_row()
    assert row["My Wish"] == "Pass to heir: Alex"
    assert Asset.from_table_row(row).wish == "Pass to heir: Alex"


def test_empty_table_cells_give_an_empty_wish():
    # a cleared cell in the data editor arrives as None or NaN
    for empty in (None, float("nan")):
        row = {"Service": "Netflix", "My Wish": empty}
        assert Asset.from_table_row(row).wish == ""


def test_saved_wish_overrides_the_demo_default(wish_file):
    assets = get_default_assets()
    asset = next(a for a in assets if a.service == "Coinbase")
    asset.wish = "Memorialize"
    save_wishes(assets)
    assert wish_file.exists()
    assert coinbase().wish == "Memorialize"  # a fresh session picks it up


def test_a_cleared_wish_stays_cleared():
    assets = get_default_assets()
    for a in assets:
        a.wish = ""
    save_wishes(assets)
    assert all(a.wish == "" for a in get_default_assets())


def test_missing_or_broken_file_keeps_the_defaults(wish_file):
    assert coinbase().wish == "Pass to heir: Alex"
    wish_file.write_text("{oops", encoding="utf-8")
    assert coinbase().wish == "Pass to heir: Alex"


def test_other_wish_carries_a_short_text():
    assert storage.split_wish("Other: give the photos to my sister") == ("Other", "give the photos to my sister")
    assert storage.split_wish("Other") == ("Other", "")
    assert storage.split_wish("Memorialize") == ("Memorialize", "")
    assert storage.join_wish("Other", "  give the photos  ") == "Other: give the photos"
    assert storage.join_wish("Other", "") == "Other"
    assert storage.join_wish("Cancel/Deactivate", "ignored") == "Cancel/Deactivate"


def test_other_wish_text_is_saved_and_reloaded():
    assets = get_default_assets()
    for a in assets:
        if a.service == "Coinbase":
            a.wish = "Other: give the photos to my sister"
    save_wishes(assets)
    assert coinbase().wish == "Other: give the photos to my sister"


def test_old_cancel_and_deactivate_wishes_become_one_option(wish_file):
    wish_file.write_text('{"coinbase.com|alex.crypto@gmail.com": "Delete account"}', encoding="utf-8")
    assert coinbase().wish == "Cancel/Deactivate"


def test_pass_to_heir_carries_the_heir_name():
    assert storage.split_wish("Pass to heir: Jordan") == ("Pass to heir", "Jordan")
    assert storage.split_wish("Pass to heir") == ("Pass to heir", "")
    assert storage.join_wish("Pass to heir", " Jordan ") == "Pass to heir: Jordan"


def test_pass_to_heir_makes_that_person_the_responsible_heir():
    asset = coinbase()
    storage.set_wish(asset, "Pass to heir: Jordan")
    assert asset.heir == "Jordan"
    storage.set_wish(asset, "Memorialize")  # other wishes leave the heir alone
    assert asset.heir == "Jordan"


def test_executor_only_sees_a_heir_for_pass_to_heir():
    asset = coinbase()  # demo data: heir Alex, wish "Pass to heir: Alex"
    assert storage.responsible_heir(asset) == "Alex"
    for wish in ("Cancel/Deactivate", "Memorialize", "Other: give the photos away", ""):
        storage.set_wish(asset, wish)
        assert storage.responsible_heir(asset) == ""
    storage.set_wish(asset, "Pass to heir")  # no name given yet
    assert storage.responsible_heir(asset) == ""
