"""Offline tests for the JSON store."""

import json
import threading

import pytest

from legacy_policy_crawler import store


def record(website, url="https://help.example.com/deceased", summary="Summary"):
    return {
        "website": website,
        "legacy_policy_url": url,
        "summary": summary,
        "tick_boxes": {},
        "checked": "2026-09-24",
    }


def test_upsert_keeps_records_sorted_and_replaces_by_website(tmp_path):
    path = tmp_path / "data" / "policies.json"  # the folder does not exist yet
    assert store.load(path) == []
    for site in ("spotify.com", "apple.com", "google.com"):
        store.upsert(record(site), path)
    assert [r["website"] for r in store.load(path)] == [
        "apple.com",
        "google.com",
        "spotify.com",
    ]

    store.upsert(record("apple.com", url="https://new.example.com"), path)
    assert len(store.load(path)) == 3
    assert (
        store.get("apple.com", path)["legacy_policy_url"] == "https://new.example.com"
    )
    assert store.get("unknown.com", path) is None
    # the temp file of the atomic write is gone
    assert not list(path.parent.glob("*.tmp"))


def test_file_is_readable_utf8_json_with_indent(tmp_path):
    path = tmp_path / "policies.json"
    store.upsert(
        record("zuerich.ch", url="not found", summary="Nachlass in Zürich"), path
    )
    text = path.read_text(encoding="utf-8")
    assert "Zürich" in text  # not escaped as ü
    assert text.startswith('[\n  {\n    "website": "zuerich.ch"')
    assert text.endswith("]\n")
    assert json.loads(text)[0]["legacy_policy_url"] == "not found"


def test_broken_file_is_reported_not_overwritten(tmp_path):
    path = tmp_path / "policies.json"
    path.write_text("{oops", encoding="utf-8")
    with pytest.raises(ValueError, match="not valid JSON"):
        store.upsert(record("apple.com"), path)
    assert path.read_text(encoding="utf-8") == "{oops"
    path.write_text('{"a": 1}', encoding="utf-8")
    with pytest.raises(ValueError, match="JSON array"):
        store.load(path)


def test_parallel_upserts_do_not_lose_records(tmp_path):
    path = tmp_path / "policies.json"
    threads = [
        threading.Thread(target=store.upsert, args=(record(f"site{i:02d}.com"), path))
        for i in range(20)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert [r["website"] for r in store.load(path)] == [
        f"site{i:02d}.com" for i in range(20)
    ]
