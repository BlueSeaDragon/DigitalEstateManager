"""Claude through the local Claude Code CLI (`claude -p`), using the CLI's own login.

No API key: each call runs `claude -p` as a subprocess, signed in with the account of whoever
runs the app (`claude` once, then log in). Meant for running the app on your own machine;
a shared or deployed app needs an Anthropic API key instead.

Each call is one prompt in, one answer out: no tools, no MCP servers, no project files.
Optional environment variables (also read from the repository .env):
  CLAUDE_MODEL       model for the calls (default "sonnet")
  CLAUDE_CONFIG_DIR  a separate Claude Code profile, to use another account than your usual login
Check everything with:  python -m digital_estate_manager.claude_cli --ping
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

from digital_estate_manager import config as _config  # noqa: F401  (loads the repository .env)

DEFAULT_MODEL = "sonnet"
TIMEOUT = 180.0  # seconds per call; a normal answer takes 10-30 s


class ClaudeCLIError(RuntimeError):
    """Claude could not answer. Usually transient."""


class ClaudeCLIUnavailable(ClaudeCLIError):
    """The `claude` command is missing or not logged in: fix the setup, retrying will not help."""


def _command(system: str) -> list[str]:
    executable = shutil.which("claude")
    if executable is None:
        raise ClaudeCLIUnavailable(
            "The Claude Code CLI (`claude`) is not installed or not on PATH."
        )
    return [
        executable,
        "-p",
        "--output-format", "json",
        "--model", os.getenv("CLAUDE_MODEL") or DEFAULT_MODEL,
        "--tools", "",
        "--strict-mcp-config",
        "--setting-sources", "",
        "--no-session-persistence",
        "--system-prompt", system,
    ]


def ask_with_usage(prompt: str, system: str, timeout: float = TIMEOUT) -> tuple[str, dict]:
    """One answer from Claude and the token usage the CLI reports for it."""
    try:
        # A neutral working directory, so the CLI picks up no CLAUDE.md or files from this repo
        done = subprocess.run(
            _command(system),
            input=prompt,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=tempfile.gettempdir(),
        )
    except subprocess.TimeoutExpired as e:
        raise ClaudeCLIError(f"Claude did not answer within {timeout:.0f} s.") from e
    try:
        reply = json.loads(done.stdout)
    except ValueError:
        detail = (done.stderr or done.stdout).strip()[:300]
        raise ClaudeCLIError(f"Unexpected output from `claude` (exit {done.returncode}): {detail}")
    text = str(reply.get("result") or "")
    if reply.get("is_error") or done.returncode != 0:
        if any(word in text.lower() for word in ("log in", "login", "/login", "authenticat")):
            raise ClaudeCLIUnavailable(f"Claude is not logged in: run `claude` once and log in. ({text[:200]})")
        raise ClaudeCLIError(f"Claude failed: {text[:300] or f'exit {done.returncode}'}")
    return text, reply.get("usage") or {}


def ask(prompt: str, system: str, timeout: float = TIMEOUT) -> str:
    """One answer from Claude, as text."""
    return ask_with_usage(prompt, system, timeout)[0]


def extract_json(text: str) -> dict | None:
    """The first JSON object in a reply (prose or code fences around it are fine), or None."""
    decoder = json.JSONDecoder()
    for start, char in enumerate(text):
        if char == "{":
            try:
                obj, _ = decoder.raw_decode(text[start:])
            except ValueError:
                continue
            if isinstance(obj, dict):
                return obj
    return None


def ask_json(prompt: str, system: str, timeout: float = TIMEOUT) -> dict:
    """One answer from Claude, as a JSON object. Raises ClaudeCLIError if it is not JSON."""
    obj = extract_json(ask(prompt, system, timeout))
    if obj is None:
        raise ClaudeCLIError("Claude did not return a JSON object.")
    return obj


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if "--ping" not in argv:
        print("usage: python -m digital_estate_manager.claude_cli --ping")
        return 2
    started = time.monotonic()
    try:
        reply = ask("Reply with the single word: pong", "You are a connectivity check.")
    except ClaudeCLIError as e:
        print(f"ping failed: {e}", file=sys.stderr)
        return 1
    print(f"Claude replied {reply.strip()!r} in {time.monotonic() - started:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
