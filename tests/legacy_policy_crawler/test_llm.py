"""Offline tests for the crawler's Claude client: JSON extraction, prompts, errors and usage bookkeeping."""

import json

import pytest

from digital_estate_manager import claude_cli
from legacy_policy_crawler import llm

MESSAGES = [{"role": "user", "content": "hi"}]


@pytest.fixture
def claude(monkeypatch, tmp_path):
    """claude_cli.ask_with_usage replaced: queue replies (or exceptions) in `replies`."""
    calls, replies = [], []

    def ask_with_usage(prompt, system):
        calls.append((system, prompt))
        reply = replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    monkeypatch.setattr(llm.claude_cli, "ask_with_usage", ask_with_usage)
    monkeypatch.setattr(llm, "USAGE_LOG", tmp_path / "usage.jsonl")
    monkeypatch.setattr(
        llm, "USAGE", {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0}
    )
    return calls, replies


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


def test_chat_sends_system_and_user_prompt_and_counts_usage(claude, tmp_path):
    calls, replies = claude
    replies.append(("pong", {"input_tokens": 2, "cache_read_input_tokens": 10, "output_tokens": 3}))
    reply = llm.chat(
        [{"role": "system", "content": "Be brief."}, {"role": "user", "content": "ping"}]
    )
    assert reply == "pong"
    assert calls == [("Be brief.", "ping")]
    assert llm.USAGE == {"calls": 1, "prompt_tokens": 12, "completion_tokens": 3}
    logged = json.loads((tmp_path / "usage.jsonl").read_text().splitlines()[0])
    assert (logged["prompt_tokens"], logged["completion_tokens"]) == (12, 3)


def test_earlier_turns_are_quoted_in_the_prompt(claude):
    calls, replies = claude
    replies.append(("{}", {}))
    llm.chat(
        [
            {"role": "system", "content": "S"},
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "not json"},
            {"role": "user", "content": "Reply with JSON."},
        ]
    )
    system, prompt = calls[0]
    assert system == "S"
    assert "<user>\nfirst\n</user>" in prompt
    assert "<assistant>\nnot json\n</assistant>" in prompt
    assert prompt.endswith("Reply with JSON.")


def test_missing_or_logged_out_cli_raises_auth_error(claude):
    _, replies = claude
    replies.append(claude_cli.ClaudeCLIUnavailable("Claude is not logged in"))
    with pytest.raises(llm.AuthError, match="not logged in"):
        llm.chat(MESSAGES)


def test_other_failures_raise_llm_error(claude):
    _, replies = claude
    replies.append(claude_cli.ClaudeCLIError("Claude did not answer within 180 s."))
    with pytest.raises(llm.LLMError, match="did not answer") as error:
        llm.chat(MESSAGES)
    assert not isinstance(error.value, llm.AuthError)
