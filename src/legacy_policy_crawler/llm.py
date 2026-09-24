"""Apertus client: plain HTTP calls to an OpenAI-compatible endpoint (Swisscom, Swiss AI Weeks).

The token is the only thing in the git-ignored .env file (APERTUS_API_KEY). URL and model have
defaults below; environment variables of the same name override them.
Check everything with:  python -m legacy_policy_crawler.llm --ping
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]  # the repo root
USAGE_LOG = ROOT / ".cache" / "legacy_policy_crawler" / "usage.jsonl"

# A key only works on its own product URL: on .../products/swiss-ai-platform/... the same key
# gets HTTP 401 NO_PRODUCT_FOUND_FOR_KEY.
DEFAULT_BASE_URL = "https://api.swisscom.com/products/swiss-ai-weeks/apertus-1.5-70b/v1"
DEFAULT_MODEL = "swiss-ai/Apertus-v1.5-70B"
MIN_INTERVAL = 0.25  # seconds between calls: the quota is 5 requests/s, this stays at 4
MAX_TRIES = 4

USAGE = {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0}  # used by this process

for _env_file in (ROOT / ".env", Path.cwd() / ".env"):
    if _env_file.is_file():
        load_dotenv(_env_file)
        break


class LLMError(RuntimeError):
    """Apertus could not be reached or answered badly. Usually transient."""


class AuthError(LLMError):
    """Missing or rejected token, or a wrong URL or model: fix the configuration."""


class JSONError(LLMError):
    """The reply contained no valid JSON object."""


_client = httpx.Client(timeout=httpx.Timeout(60.0, connect=15.0))
_throttle_lock = threading.Lock()
_usage_lock = threading.Lock()
_last_call = 0.0


def _settings() -> tuple[str, str, str]:
    key = os.getenv("APERTUS_API_KEY", "").strip()
    if not key:
        raise AuthError(
            "APERTUS_API_KEY is empty. Paste your token into the .env file (see .env.example)."
        )
    base_url = os.getenv("APERTUS_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
    return base_url, os.getenv("APERTUS_MODEL", DEFAULT_MODEL), key


def _rejected(response: httpx.Response) -> str:
    """Message for a 401/403, with the gateway's error code (e.g. NO_PRODUCT_FOUND_FOR_KEY)."""
    try:
        code = str(response.json().get("code") or "")
    except (ValueError, AttributeError):
        code = ""
    detail = f": {code}" if code else ""
    return (
        f"Apertus rejected the key (HTTP {response.status_code}{detail}). "
        "Check APERTUS_API_KEY in .env and that APERTUS_BASE_URL is the product URL the key belongs to."
    )


def _throttle() -> None:
    """Keep MIN_INTERVAL seconds between calls, across threads."""
    global _last_call
    with _throttle_lock:
        wait = _last_call + MIN_INTERVAL - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_call = time.monotonic()


def _retry_after(response: httpx.Response) -> float:
    try:
        return min(float(response.headers.get("Retry-After", 0)), 30.0)
    except ValueError:
        return 0.0


def _count(usage: dict) -> None:
    """Count the tokens of one reply and append them to the usage log."""
    prompt = int(usage.get("prompt_tokens") or 0)
    completion = int(usage.get("completion_tokens") or 0)
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


def chat(messages: list[dict], max_tokens: int = 300, temperature: float = 0.0) -> str:
    """One chat completion: the reply text. Retries 429, 5xx and network errors."""
    base_url, model, key = _settings()
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "top_p": 0.9,
        "max_tokens": max_tokens,
    }
    headers = {
        "Authorization": f"Bearer {key}",
        "User-Agent": "DigitalEstateManager/0.1",
    }
    delay = 1.0
    for attempt in range(1, MAX_TRIES + 1):
        _throttle()
        try:
            response = _client.post(
                f"{base_url}/chat/completions", json=payload, headers=headers
            )
        except httpx.TransportError as e:
            problem = f"network error ({type(e).__name__})"
        else:
            status = response.status_code
            if status in (401, 403):
                raise AuthError(_rejected(response))
            if status == 404:
                raise AuthError(
                    "Apertus endpoint or model not found (HTTP 404). Check APERTUS_BASE_URL / APERTUS_MODEL."
                )
            if status == 429 or status >= 500:
                problem = f"HTTP {status}"
                delay = max(delay, _retry_after(response))
            elif status >= 400:
                raise LLMError(f"Apertus error HTTP {status}: {response.text[:200]}")
            else:
                try:
                    data = response.json()
                    text = data["choices"][0]["message"]["content"] or ""
                except (ValueError, KeyError, IndexError, TypeError) as e:
                    raise LLMError("Unexpected reply format from Apertus") from e
                _count(data.get("usage") or {})
                return text
        if attempt == MAX_TRIES:
            raise LLMError(f"Apertus unavailable: {problem}")
        time.sleep(delay)
        delay *= 2
    raise LLMError("Apertus unavailable")  # not reached


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
        raise JSONError("Apertus did not return valid JSON")
    return obj


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if "--ping" not in argv:
        print("usage: python -m legacy_policy_crawler.llm --ping")
        return 2
    started = time.monotonic()
    try:
        reply = chat(
            [{"role": "user", "content": "Reply with the single word: pong"}],
            max_tokens=10,
        )
    except LLMError as e:
        print(f"ping failed: {e}", file=sys.stderr)
        return 1
    print(
        f"Apertus replied {reply.strip()!r} in {time.monotonic() - started:.1f}s; tokens used: {USAGE}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
