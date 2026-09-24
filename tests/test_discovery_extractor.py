import io
import json
from datetime import date, timedelta

import pytest

pytest.importorskip("subscription_finder")

from subscription_finder import LLMConfigError  # noqa: E402
from digital_estate_manager.discovery import (  # noqa: E402
    DiscoveryInputError,
    UnsupportedFileFormat,
    parse_and_extract,
)
from digital_estate_manager.models import Asset, SubscriptionAssetInfo  # noqa: E402


def transactions_upload(name="transactions.jsonl"):
    start = date(2025, 1, 5)
    rows = [
        {
            "timestamp": f"{start + timedelta(days=30 * i)}T10:00:00Z", "amount": -9.9, "currency": "chf",
            "direction": "out", "type": "card_payment", "description": "video access", "mcc": "5815",
        }
        for i in range(8)
    ]
    upload = io.BytesIO("".join(json.dumps(r) + "\n" for r in rows).encode())
    upload.name = name
    return upload


def test_jsonl_upload_runs_finder_and_returns_assets():
    result = parse_and_extract(transactions_upload(), use_llm=False)
    assert result.source_name == "transactions.jsonl"
    assert len(result.extracted_assets) == 1
    asset = result.extracted_assets[0]
    assert isinstance(asset, Asset) and isinstance(asset.asset_info, SubscriptionAssetInfo)
    assert asset.asset_info.billing_cycle == "monthly"
    assert asset.asset_info.currency == "CHF"
    assert asset.cost_monthly == pytest.approx(9.9)
    assert asset.user_verified is False


def test_upload_is_reread_from_the_start():
    upload = transactions_upload()
    upload.read()  # Streamlit may have consumed the buffer on an earlier rerun
    assert len(parse_and_extract(upload, use_llm=False).extracted_assets) == 1


@pytest.mark.parametrize("name", ["statement.pdf", "export.csv", "notes.txt"])
def test_unsupported_formats_are_rejected(name):
    with pytest.raises(UnsupportedFileFormat, match="not supported for subscription discovery yet"):
        parse_and_extract(io.BytesIO(b"whatever"), filename=name)


def test_nothing_to_scan():
    with pytest.raises(DiscoveryInputError):
        parse_and_extract(None)


def test_missing_llm_config_is_raised_so_the_ui_can_offer_rules_only(monkeypatch):
    monkeypatch.setattr(
        "subscription_finder.config.Settings.from_env",
        classmethod(lambda cls: cls(api_key=None, base_url=None)),
    )
    with pytest.raises(LLMConfigError):
        parse_and_extract(transactions_upload(), use_llm=True)
