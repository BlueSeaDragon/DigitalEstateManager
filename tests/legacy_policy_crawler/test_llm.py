"""Offline tests for the Apertus client: JSON extraction, retries, errors and quota bookkeeping."""

import json
import time
import types

import httpx
import pytest

from legacy_policy_crawler import llm

MESSAGES = [{"role": "user", "content": "hi"}]


def ok(text, prompt=10, completion=5):
    body = {
        "choices": [{"message": {"content": text}}],
        "usage": {"prompt_tokens": prompt, "completion_tokens": completion},
    }
    return httpx.Response(200, json=body)


class Api:
    """Apertus behind a fake transport: queue responses (or exceptions) in `responses`."""

    def __init__(self):
        self.requests, self.responses, self.sleeps = [], [], []

    def handler(self, request):
        self.requests.append(request)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


@pytest.fixture
def api(monkeypatch, tmp_path):
    fake = Api()
    monkeypatch.setattr(
        llm, "_client", httpx.Client(transport=httpx.MockTransport(fake.handler))
    )
    monkeypatch.setattr(
        llm,
        "time",
        types.SimpleNamespace(monotonic=time.monotonic, sleep=fake.sleeps.append),
    )
    monkeypatch.setattr(llm, "MIN_INTERVAL", 0.0)
    monkeypatch.setattr(llm, "USAGE_LOG", tmp_path / "usage.jsonl")
    monkeypatch.setattr(
        llm, "USAGE", {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0}
    )
    monkeypatch.setenv("APERTUS_API_KEY", "test-key")
    monkeypatch.delenv("APERTUS_BASE_URL", raising=False)
    monkeypatch.delenv("APERTUS_MODEL", raising=False)
    return fake


def test_extract_json():
    assert llm.extract_json('{"a": 1}') == {"a": 1}
    assert llm.extract_json('Sure!\n```json\n{"action": "open", "id": 3}\n```') == {
        "action": "open",
        "id": 3,
    }
    assert llm.extract_json('x {"a": {"b": [1, 2]}} y {"c": 1}') == {"a": {"b": [1, 2]}}
    assert llm.extract_json('{nope} {"ok": true}') == {"ok": True}
    assert llm.extract_json('{"broken": ') is None
    assert llm.extract_json("[1, 2]") is None
    assert llm.extract_json("no json here") is None


def test_chat_json_retries_once_then_gives_up(monkeypatch):
    replies = iter(["I cannot do that", '{"a": 1}'])
    seen = []

    def fake_chat(messages, max_tokens=300, temperature=0.1):
        seen.append(messages)
        return next(replies)

    monkeypatch.setattr(llm, "chat", fake_chat)
    assert llm.chat_json(MESSAGES) == {"a": 1}
    assert len(seen) == 2
    assert seen[1][-2] == {"role": "assistant", "content": "I cannot do that"}
    assert "not valid JSON" in seen[1][-1]["content"]

    monkeypatch.setattr(llm, "chat", lambda *args, **kwargs: "still no json")
    with pytest.raises(llm.JSONError):
        llm.chat_json(MESSAGES)


def test_chat_sends_token_model_and_counts_usage(api, tmp_path):
    api.responses = [ok("pong", prompt=12, completion=3)]
    assert llm.chat([{"role": "user", "content": "ping"}], max_tokens=10) == "pong"
    request = api.requests[0]
    assert (
        str(request.url)
        == "https://api.swisscom.com/products/swiss-ai-weeks/apertus-1.5-70b/v1/chat/completions"
    )
    assert request.headers["authorization"] == "Bearer test-key"
    assert request.headers["user-agent"] == "DigitalEstateManager/0.1"
    body = json.loads(request.content)
    assert body["model"] == "swiss-ai/Apertus-v1.5-70B"
    assert (body["max_tokens"], body["temperature"], body["top_p"]) == (10, 0.0, 0.9)
    assert body["messages"] == [{"role": "user", "content": "ping"}]
    assert llm.USAGE == {"calls": 1, "prompt_tokens": 12, "completion_tokens": 3}
    logged = json.loads(
        (tmp_path / "usage.jsonl").read_text(encoding="utf-8").splitlines()[0]
    )
    assert (logged["prompt_tokens"], logged["completion_tokens"]) == (12, 3)


def test_chat_uses_environment_overrides(api, monkeypatch):
    monkeypatch.setenv("APERTUS_BASE_URL", "https://other.example/v1/")
    monkeypatch.setenv("APERTUS_MODEL", "swiss-ai/other")
    api.responses = [ok("x")]
    llm.chat(MESSAGES)
    assert str(api.requests[0].url) == "https://other.example/v1/chat/completions"
    assert json.loads(api.requests[0].content)["model"] == "swiss-ai/other"


def test_chat_retries_rate_limits_and_server_errors_with_backoff(api):
    api.responses = [
        httpx.Response(429, headers={"Retry-After": "3"}),
        httpx.Response(503),
        ok("fine"),
    ]
    assert llm.chat(MESSAGES) == "fine"
    assert len(api.requests) == 3
    assert api.sleeps == [3.0, 6.0]  # Retry-After is honoured, then the delay doubles


def test_chat_gives_up_after_four_tries(api):
    api.responses = [httpx.Response(500) for _ in range(4)]
    with pytest.raises(llm.LLMError, match="HTTP 500") as error:
        llm.chat(MESSAGES)
    assert not isinstance(error.value, llm.AuthError)
    assert len(api.requests) == 4


def test_chat_retries_network_errors(api):
    api.responses = [httpx.ConnectError("down"), ok("back")]
    assert llm.chat(MESSAGES) == "back"
    api.responses = [httpx.ConnectError("down") for _ in range(4)]
    with pytest.raises(llm.LLMError, match="network error"):
        llm.chat(MESSAGES)


def test_configuration_problems_raise_auth_error_without_retrying(api, monkeypatch):
    for status in (401, 403, 404):
        api.responses = [httpx.Response(status)]
        with pytest.raises(llm.AuthError):
            llm.chat(MESSAGES)
    assert len(api.requests) == 3
    monkeypatch.setenv("APERTUS_API_KEY", "   ")
    with pytest.raises(llm.AuthError, match="APERTUS_API_KEY is empty"):
        llm.chat(MESSAGES)
    assert len(api.requests) == 3  # no request was sent without a token


def test_rejected_key_reports_the_gateway_error_code_but_never_the_key(api):
    api.responses = [
        httpx.Response(401, json={"status": "401", "code": "NO_PRODUCT_FOUND_FOR_KEY"})
    ]
    with pytest.raises(llm.AuthError, match="NO_PRODUCT_FOUND_FOR_KEY") as error:
        llm.chat(MESSAGES)
    # the usual cause is the wrong product URL
    assert "APERTUS_BASE_URL" in str(error.value)
    assert "test-key" not in str(error.value)
    api.responses = [httpx.Response(403, text="<html>")]  # no JSON body: still clear
    with pytest.raises(llm.AuthError, match="HTTP 403"):
        llm.chat(MESSAGES)


def test_other_errors_are_reported(api):
    api.responses = [httpx.Response(400, text="bad request body")]
    with pytest.raises(llm.LLMError, match="HTTP 400"):
        llm.chat(MESSAGES)
    for odd in (
        httpx.Response(200, json={"unexpected": True}),
        httpx.Response(200, text="<html>"),
    ):
        api.responses = [odd]
        with pytest.raises(llm.LLMError, match="Unexpected reply"):
            llm.chat(MESSAGES)


def test_calls_are_spaced_to_stay_under_the_quota(monkeypatch):
    clock = {"now": 100.0}
    slept = []

    def sleep(seconds):
        slept.append(seconds)
        clock["now"] += seconds

    monkeypatch.setattr(
        llm, "time", types.SimpleNamespace(monotonic=lambda: clock["now"], sleep=sleep)
    )
    monkeypatch.setattr(llm, "_last_call", 0.0)
    monkeypatch.setattr(llm, "MIN_INTERVAL", 0.25)
    for _ in range(3):
        llm._throttle()
    # 4 requests/s at most; the quota is 5
    assert slept == [pytest.approx(0.25), pytest.approx(0.25)]


def test_ping(api, capsys, monkeypatch):
    api.responses = [ok("pong")]
    assert llm.main(["--ping"]) == 0
    assert "pong" in capsys.readouterr().out
    monkeypatch.setenv("APERTUS_API_KEY", "")
    assert llm.main(["--ping"]) == 1
    assert "APERTUS_API_KEY is empty" in capsys.readouterr().err
    assert llm.main([]) == 2
