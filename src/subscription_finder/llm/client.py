"""Swisscom-hosted Apertus client: OpenAI-compatible, rate-limited, retried, disk-cached."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import time
from pathlib import Path
from typing import Any

from ..config import Settings

log = logging.getLogger(__name__)


class LLMError(Exception):
    """The LLM could not produce a valid answer (after retries and one repair attempt)."""


class LLMConfigError(LLMError):
    """The LLM is enabled but not configured (e.g. missing SWISSCOM_API_KEY)."""


# The server refused the request itself (bad request, auth, unknown model): retrying cannot help.
NON_RETRYABLE_STATUS = frozenset({400, 401, 403, 404, 413, 422})


def describe_error(exc: BaseException) -> str:
    """Status code and the server's error message, e.g. "400 BadRequestError: max_tokens too large"."""
    status = getattr(exc, "status_code", None)
    body = getattr(exc, "body", None)
    message = None
    if isinstance(body, dict):
        error = body.get("error")
        message = body.get("message") or (error.get("message") if isinstance(error, dict) else error)
    text = f"{type(exc).__name__}: {message or exc}"
    return (f"{status} {text}" if status else text)[:300]


def parse_json(text: str) -> Any:
    """Parse JSON from a model answer, tolerating code fences and surrounding prose."""
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fenced:
        text = fenced.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    for opener, closer in (("{", "}"), ("[", "]")):
        start, end = text.find(opener), text.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                continue
    raise ValueError("answer is not valid JSON")


class LLMClient:
    def __init__(self, settings: Settings, client: Any = None):
        self.model = settings.model
        self.retries = settings.llm_retries
        self.cache_dir = Path(settings.cache_dir) if settings.cache_dir else None
        self._min_interval = 1.0 / settings.max_requests_per_second
        self._last_call = 0.0
        self._lock = threading.Lock()
        self.usage = {"requests": 0, "cache_hits": 0, "input_tokens": 0, "output_tokens": 0}
        self.max_tokens = settings.llm_max_tokens
        self.last_error: str | None = None  # status + server message of the last failure (no prompt content)
        if client is None:
            if not settings.api_key:
                raise LLMConfigError(
                    "SWISSCOM_API_KEY is not set. Put it in subscription_finder/.env or run with --no-llm."
                )
            if not settings.base_url:
                raise LLMConfigError(
                    "SWISSCOM_BASE_URL is not set. Put it in subscription_finder/.env or run with --no-llm."
                )
            from openai import OpenAI

            client = OpenAI(api_key=settings.api_key, base_url=settings.base_url, max_retries=0)
        self._client = client

    # -- plumbing -----------------------------------------------------------
    def _cache_path(self, messages: list[dict[str, str]], max_tokens: int) -> Path | None:
        if not self.cache_dir:
            return None
        key = json.dumps({"model": self.model, "messages": messages, "max_tokens": max_tokens}, sort_keys=True)
        return self.cache_dir / f"{hashlib.sha256(key.encode()).hexdigest()}.json"

    def _throttle(self) -> None:
        with self._lock:
            wait = self._last_call + self._min_interval - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last_call = time.monotonic()

    def _raw_call(self, messages: list[dict[str, str]], max_tokens: int) -> str:
        cache = self._cache_path(messages, max_tokens)
        if cache and cache.exists():
            self.usage["cache_hits"] += 1
            return json.loads(cache.read_text(encoding="utf-8"))["content"]
        last_exc: Exception | None = None
        for attempt in range(self.retries):
            self._throttle()
            try:
                response = self._client.chat.completions.create(
                    model=self.model, messages=messages, temperature=0, max_tokens=max_tokens
                )
                content = response.choices[0].message.content or ""
                usage = getattr(response, "usage", None)
                self.usage["requests"] += 1
                self.usage["input_tokens"] += getattr(usage, "prompt_tokens", 0) or 0
                self.usage["output_tokens"] += getattr(usage, "completion_tokens", 0) or 0
                if cache:
                    cache.parent.mkdir(parents=True, exist_ok=True)
                    cache.write_text(json.dumps({"content": content}), encoding="utf-8")
                return content
            except Exception as exc:  # network, rate limit, 5xx
                last_exc = exc
                status = getattr(exc, "status_code", None)
                detail = describe_error(exc)
                log.warning("LLM request failed (attempt %d/%d): %s", attempt + 1, self.retries, detail)
                if (status in NON_RETRYABLE_STATUS) or "EXPIRED_QUOTA" in str(exc):
                    self.last_error = detail
                    raise LLMError(f"LLM request rejected: {detail}") from exc
                time.sleep(min(2**attempt, 8))
        self.last_error = describe_error(last_exc) if last_exc else None
        raise LLMError(f"LLM request failed after {self.retries} attempts: {self.last_error}") from last_exc

    # -- public -------------------------------------------------------------
    def complete_json(self, system: str, user: str, max_tokens: int = 1024, validate=None) -> Any:
        """Ask for JSON. On invalid JSON (or failed `validate`) send one repair request."""
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        max_tokens = min(max_tokens, self.max_tokens)
        answer = self._raw_call(messages, max_tokens)
        try:
            data = parse_json(answer)
            return validate(data) if validate else data
        except (ValueError, KeyError, TypeError) as exc:
            error = str(exc)
        repair = messages + [
            {"role": "assistant", "content": answer},
            {
                "role": "user",
                "content": f"Your answer was invalid ({error}). Reply again with ONLY the corrected JSON, no prose.",
            },
        ]
        answer = self._raw_call(repair, max_tokens)
        try:
            data = parse_json(answer)
            return validate(data) if validate else data
        except (ValueError, KeyError, TypeError) as exc:
            raise LLMError(f"invalid JSON after repair: {exc}") from exc
