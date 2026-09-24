from __future__ import annotations

import base64
import json
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from subscription_finder.config import Settings
from subscription_finder.models import Evidence


@pytest.fixture
def settings(tmp_path):
    return Settings(api_key="test", base_url="http://localhost", cache_dir=None, max_requests_per_second=1000)


def tx(day: date, amount: float, description="monthly plan", mcc="5734", currency="CHF", kind="card_payment", direction="out", n=[0]):
    n[0] += 1
    return Evidence(
        evidence_id=f"tx-{n[0]}",
        type="transaction",
        source="test.jsonl",
        source_ref=f"line:{n[0]}",
        date=day,
        amount=amount,
        currency=currency,
        observed={
            "date": day.isoformat(),
            "amount": amount,
            "currency": currency,
            "merchant": None,
            "mcc": mcc,
            "description": description,
            "direction": direction,
            "transaction_type": kind,
        },
    )


def series(start: date, count: int, every: int, amount: float, **kw) -> list[Evidence]:
    return [tx(start + timedelta(days=every * i), amount, **kw) for i in range(count)]


def jsonl_rows(rows: list[dict]) -> str:
    return "".join(json.dumps(r) + "\n" for r in rows)


def row(client="C1", ts="2025-01-05T10:00:00Z", amount=9.9, description="video access", mcc="5815", kind="card_payment", direction="out", currency="chf"):
    return {
        "client_id": client, "timestamp": ts, "amount": amount, "currency": currency, "direction": direction,
        "type": kind, "description": description, "mcc": mcc, "fee": 0.0,
    }


class FakeLLM:
    """Stands in for openai.OpenAI: returns queued answers (str or callable(messages) -> str)."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls: list[list[dict]] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, model, messages, **kwargs):
        self.calls.append(messages)
        if not self.answers:
            raise RuntimeError("no more fake answers")
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        content = answer(messages) if callable(answer) else answer
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
        )


def gmail_message(message_id: str, day: date, sender: str, subject: str, body: str) -> dict:
    millis = int(datetime(day.year, day.month, day.day, 12, tzinfo=timezone.utc).timestamp() * 1000)
    return {
        "id": message_id,
        "internalDate": str(millis),
        "snippet": body[:100],
        "payload": {
            "mimeType": "multipart/alternative",
            "headers": [{"name": "From", "value": sender}, {"name": "Subject", "value": subject}],
            "parts": [
                {"mimeType": "text/plain", "body": {"data": base64.urlsafe_b64encode(body.encode()).decode()}},
            ],
        },
    }


class _Request:
    def __init__(self, result):
        self.result = result

    def execute(self, num_retries=0):
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class FakeGmailService:
    """Minimal stand-in for googleapiclient's Gmail service."""

    def __init__(self, messages: list[dict], account="owner@example.org", list_error: Exception | None = None):
        self.messages_by_id = {m["id"]: m for m in messages}
        self.account = account
        self.list_error = list_error
        self.queries: list[str] = []

    def users(self):
        return self

    def getProfile(self, userId):
        return _Request({"emailAddress": self.account})

    def messages(self):
        return self

    def list(self, userId, q, pageToken=None, maxResults=100):
        self.queries.append(q)
        if self.list_error:
            return _Request(self.list_error)
        return _Request({"messages": [{"id": i} for i in self.messages_by_id]})

    def get(self, userId, id, format="full"):
        return _Request(self.messages_by_id[id])
