"""Tests for the owner's after-death wish on an asset."""

from digital_estate_manager.models import Asset
from digital_estate_manager.vault import get_default_assets


def test_wish_is_optional_and_empty_by_default():
    row = {"Service": "Netflix", "Service Address": "https://netflix.com"}
    assert Asset.from_table_row(row).wish == ""


def test_wish_survives_the_table_round_trip():
    asset = next(a for a in get_default_assets() if a.service == "Coinbase")
    assert asset.wish == "Pass to Alex"
    row = asset.to_table_row()
    assert row["My Wish"] == "Pass to Alex"
    assert Asset.from_table_row(row).wish == "Pass to Alex"


def test_empty_table_cells_give_an_empty_wish():
    # a cleared cell in the data editor arrives as None or NaN
    for empty in (None, float("nan")):
        row = {"Service": "Netflix", "My Wish": empty}
        assert Asset.from_table_row(row).wish == ""
