import io

from tests.subscription_finder.conftest import jsonl_rows, row

from subscription_finder.sources.transactions_jsonl import is_charge, is_refund, load_transactions


def test_load_from_path(tmp_path):
    path = tmp_path / "tx.jsonl"
    path.write_text(jsonl_rows([row(), row(ts="2025-02-05T10:00:00Z")]), encoding="utf-8")
    evidence, stats = load_transactions(path)
    assert stats == {"source": "tx.jsonl", "rows": 2, "skipped": 0}
    assert evidence[0].currency == "CHF"
    assert evidence[0].source_ref == "line:1"
    assert evidence[0].observed["description"] == "video access"


def test_load_from_binary_file_like():
    upload = io.BytesIO(jsonl_rows([row()]).encode("utf-8"))
    upload.name = "statement.jsonl"
    evidence, stats = load_transactions(upload)
    assert stats["source"] == "statement.jsonl"
    assert len(evidence) == 1


def test_sample_client_filter():
    text = jsonl_rows([row(client="C1"), row(client="C2"), row(client="C1")])
    evidence, stats = load_transactions(io.StringIO(text), sample_client_id="C1")
    assert stats["rows"] == 2
    assert stats["skipped"] == 0


def test_malformed_rows_are_skipped_and_counted():
    bad = row()
    del bad["amount"]
    text = jsonl_rows([row(), bad]) + "{not json\n" + jsonl_rows([row(ts="yesterday")])
    evidence, stats = load_transactions(io.StringIO(text))
    assert stats["rows"] == 1
    assert stats["skipped"] == 3


def test_json_array_is_accepted():
    evidence, _ = load_transactions(io.StringIO("[" + jsonl_rows([row()]).strip() + "]"))
    assert len(evidence) == 1


def test_charge_and_refund_rules():
    text = jsonl_rows([
        row(),
        row(kind="transfer"),
        row(kind="refund", direction="in"),
        row(kind="p2p_transfer"),
        row(kind="atm"),
        row(direction="in", kind="topup"),
    ])
    evidence, _ = load_transactions(io.StringIO(text))
    assert [is_charge(e) for e in evidence] == [True, True, False, False, False, False]
    assert [is_refund(e) for e in evidence] == [False, False, True, False, False, False]
