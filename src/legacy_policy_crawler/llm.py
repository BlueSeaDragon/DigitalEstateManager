"""Claude client for the crawler, through the local Claude Code CLI (no API key).

Runs `claude -p` via `digital_estate_manager.claude_cli`, signed in with the CLI's own login.
Optional environment variable: CLAUDE_MODEL (default "sonnet").
Check everything with:  python -m legacy_policy_crawler.llm --ping
"""

from __future__ import annotations

import json
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from digital_estate_manager import claude_cli

ROOT = Path(__file__).resolve().parents[2]  # the repo root
USAGE_LOG = ROOT / ".cache" / "legacy_policy_crawler" / "usage.jsonl"

USAGE = {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0}  # used by this process


class LLMError(RuntimeError):
    """Claude could not be reached or answered badly. Usually transient."""


class AuthError(LLMError):
    """The `claude` CLI is missing or not logged in: fix the setup."""


class JSONError(LLMError):
    """The reply contained no valid JSON object."""


_usage_lock = threading.Lock()


def _count(usage: dict) -> None:
    """Count the tokens of one reply and append them to the usage log."""
    prompt = sum(
        int(usage.get(key) or 0)
        for key in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
    )
    completion = int(usage.get("output_tokens") or 0)
    with _usage_lock:
        USAGE["calls"] += 1
        USAGE["prompt_tokens"] += prompt
        USAGE["completion_tokens"] += completion
        try:
            USAGE_LOG.parent.mkdir(parents=True, exist_ok=True)
            line = {
                "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "prompt_tokens": prompt,
                "completion_tokens": completion,
            }
            with USAGE_LOG.open("a", encoding="utf-8") as log:
                log.write(json.dumps(line) + "\n")
        except OSError:
            pass  # the log is only a convenience


def _as_prompt(messages: list[dict]) -> tuple[str, str]:
    """Chat messages -> (system prompt, one user prompt). Earlier turns are quoted in the prompt."""
    system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
    turns = [m for m in messages if m["role"] != "system"]
    if len(turns) == 1:
        return system, turns[0]["content"]
    lines = [f"<{m['role']}>\n{m['content']}\n</{m['role']}>" for m in turns[:-1]]
    return system, "Conversation so far:\n" + "\n".join(lines) + "\n\n" + turns[-1]["content"]


def chat(messages: list[dict], max_tokens: int = 300, temperature: float = 0.0) -> str:
    """One reply from Claude. `max_tokens` and `temperature` are kept for callers; the CLI ignores them."""
    system, prompt = _as_prompt(messages)
    try:
        text, usage = claude_cli.ask_with_usage(prompt, system or "You are a helpful assistant.")
    except claude_cli.ClaudeCLIUnavailable as e:
        raise AuthError(str(e)) from e
    except claude_cli.ClaudeCLIError as e:
        raise LLMError(str(e)) from e
    _count(usage)
    return text


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


def chat_json(messages: list[dict], max_tokens: int = 300) -> dict:
    """Ask for a JSON object. Retries once if the reply is not JSON, then raises JSONError."""
    text = chat(messages, max_tokens)
    obj = extract_json(text)
    if obj is None:
        retry = messages + [
            {"role": "assistant", "content": text},
            {
                "role": "user",
                "content": "That was not valid JSON. Reply with one JSON object only.",
            },
        ]
        obj = extract_json(chat(retry, max_tokens))
    if obj is None:
        raise JSONError("Claude did not return valid JSON")
    return obj


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if "--ping" not in argv:
        print("usage: python -m legacy_policy_crawler.llm --ping")
        return 2
    started = time.monotonic()
    try:
        reply = chat([{"role": "user", "content": "Reply with the single word: pong"}])
    except LLMError as e:
        print(f"ping failed: {e}", file=sys.stderr)
        return 1
    print(
        f"Claude replied {reply.strip()!r} in {time.monotonic() - started:.1f}s; tokens used: {USAGE}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
