"""Email source protocol. Sources receive ready credentials; they never run a login flow."""

from __future__ import annotations

from typing import Any, Callable, Iterable, Protocol, runtime_checkable

from ..models import EmailMessage


class ReconnectRequired(Exception):
    """The stored email credentials are expired or revoked; the user must connect again."""


@runtime_checkable
class EmailSource(Protocol):
    provider: str

    @property
    def account(self) -> str | None: ...

    def fetch(self, progress: Callable[[str, float], None] | None = None) -> Iterable[EmailMessage]:
        """Return candidate billing emails (headers + trimmed body)."""
        ...

    def stats(self) -> dict[str, Any]:
        """Scan metadata for `run.sources_scanned.email` (no message content)."""
        ...
