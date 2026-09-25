"""The JSON file with one record per website (data/legacy_policies.json)."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # the repo root
DEFAULT_PATH = ROOT / "data" / "legacy_policies.json"

_lock = threading.Lock()


def load(path: Path | str = DEFAULT_PATH) -> list[dict]:
    """All records; an empty list if the file does not exist yet."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    try:
        data = json.loads(text)
    except ValueError as e:
        raise ValueError(f"{path} is not valid JSON: {e}") from e
    if not isinstance(data, list):
        raise ValueError(f"{path} must contain a JSON array of records")
    return data


def get(website: str, path: Path | str = DEFAULT_PATH) -> dict | None:
    """The saved record of a website, or None."""
    return next(
        (record for record in load(path) if record.get("website") == website), None
    )


def upsert(record: dict, path: Path | str = DEFAULT_PATH) -> None:
    """Add or replace a website's record. Records stay sorted; the write is atomic."""
    path = Path(path)
    with _lock:
        records = [r for r in load(path) if r.get("website") != record["website"]]
        records.append(record)
        records.sort(key=lambda r: r["website"])
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(path.name + ".tmp")
        temp.write_text(
            json.dumps(records, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        os.replace(temp, path)
