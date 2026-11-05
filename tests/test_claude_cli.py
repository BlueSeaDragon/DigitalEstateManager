"""The Claude Code CLI wrapper: command line, reply parsing and errors (no real `claude` call)."""

import json
import subprocess
from types import SimpleNamespace

import pytest

from digital_estate_manager import claude_cli


@pytest.fixture
def cli(monkeypatch):
    """`claude` on PATH, with subprocess.run replaced: set `result` to the next CompletedProcess."""
    state = {"calls": []}

    def run(command, **kwargs):
        state["calls"].append((command, kwargs))
        result = state["result"]
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(claude_cli.shutil, "which", lambda name: "/usr/local/bin/claude")
    monkeypatch.setattr(claude_cli.subprocess, "run", run)
    monkeypatch.delenv("CLAUDE_MODEL", raising=False)
    return state


def reply(result, is_error=False, returncode=0, usage=None):
    body = {"result": result, "is_error": is_error, "usage": usage or {"output_tokens": 4}}
    return SimpleNamespace(stdout=json.dumps(body), stderr="", returncode=returncode)


def test_ask_runs_a_tool_less_call_outside_the_repository(cli):
    cli["result"] = reply("pong")
    text, usage = claude_cli.ask_with_usage("ping", "Be brief.")
    assert (text, usage) == ("pong", {"output_tokens": 4})
    command, kwargs = cli["calls"][0]
    assert command[:2] == ["/usr/local/bin/claude", "-p"]
    assert command[command.index("--tools") + 1] == ""
    assert command[command.index("--model") + 1] == "sonnet"
    assert command[command.index("--system-prompt") + 1] == "Be brief."
    assert "--strict-mcp-config" in command and "--no-session-persistence" in command
    assert kwargs["input"] == "ping"
    assert "DigitalEstateManager" not in kwargs["cwd"]


def test_model_can_be_changed_in_the_environment(cli, monkeypatch):
    monkeypatch.setenv("CLAUDE_MODEL", "opus")
    cli["result"] = reply("ok")
    claude_cli.ask("hi", "S")
    command = cli["calls"][0][0]
    assert command[command.index("--model") + 1] == "opus"


def test_ask_json_finds_the_object_in_the_reply(cli):
    cli["result"] = reply('Here it is:\n```json\n{"notice_period": "1 month"}\n```')
    assert claude_cli.ask_json("p", "s") == {"notice_period": "1 month"}
    cli["result"] = reply("Sorry, no JSON.")
    with pytest.raises(claude_cli.ClaudeCLIError, match="JSON"):
        claude_cli.ask_json("p", "s")


def test_missing_cli_is_unavailable(monkeypatch):
    monkeypatch.setattr(claude_cli.shutil, "which", lambda name: None)
    with pytest.raises(claude_cli.ClaudeCLIUnavailable, match="not installed"):
        claude_cli.ask("hi", "S")


def test_logged_out_cli_is_unavailable(cli):
    cli["result"] = reply("Invalid API key · Please run /login", is_error=True, returncode=1)
    with pytest.raises(claude_cli.ClaudeCLIUnavailable, match="not logged in"):
        claude_cli.ask("hi", "S")


def test_other_failures_are_reported(cli):
    cli["result"] = reply("API Error: 529 Overloaded", is_error=True, returncode=1)
    with pytest.raises(claude_cli.ClaudeCLIError, match="Overloaded") as error:
        claude_cli.ask("hi", "S")
    assert not isinstance(error.value, claude_cli.ClaudeCLIUnavailable)

    cli["result"] = SimpleNamespace(stdout="", stderr="crashed", returncode=2)
    with pytest.raises(claude_cli.ClaudeCLIError, match="crashed"):
        claude_cli.ask("hi", "S")

    cli["result"] = subprocess.TimeoutExpired("claude", 180)
    with pytest.raises(claude_cli.ClaudeCLIError, match="did not answer"):
        claude_cli.ask("hi", "S")
