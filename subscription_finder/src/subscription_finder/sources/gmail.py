"""Gmail source: fetch candidate billing emails with read-only credentials."""

from __future__ import annotations

import base64
import html
import logging
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable

from ..models import EmailMessage
from .email_base import ReconnectRequired

log = logging.getLogger(__name__)

BILLING_TERMS = (
    'receipt OR invoice OR subscription OR renewal OR "your plan" OR Abo OR Rechnung OR Quittung OR facture'
)


# Regex twin of BILLING_TERMS: in a footprint scan (broader query) only these emails get the
# per-email billing extraction, so the subscription finder sees the same emails as before.
BILLING_PATTERN = re.compile(
    r"\b(receipts?|invoices?|subscriptions?|renewals?|your plan|abo|rechnung(en)?|quittung(en)?|factures?)\b", re.I
)
# Wording of emails that show an account exists: security/login, sign-up, statements, contracts, orders.
FOOTPRINT_TERMS = BILLING_TERMS + (
    ' OR "sign-in" OR "sign in" OR login OR "security alert" OR password OR "verify your" OR "confirm your"'
    ' OR welcome OR Willkommen OR bienvenue OR statement OR Kontoauszug OR "your account" OR "Ihr Konto"'
    ' OR "votre compte" OR policy OR Police OR contract OR Vertrag OR "order confirmation" OR booking'
    ' OR Buchung OR reservation OR membership OR Mitgliedschaft'
)


def build_query(months: int = 24, terms: str = BILLING_TERMS) -> str:
    return f"newer_than:{months}m ({terms}) -in:spam"


def _decode(data: str) -> str:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", errors="replace")


def _html_to_text(markup: str) -> str:
    markup = re.sub(r"(?is)<(script|style|head)\b.*?</\1>", " ", markup)
    markup = re.sub(r"(?s)<[^>]+>", " ", markup)
    return html.unescape(markup)


def extract_body(payload: dict[str, Any]) -> str:
    """Return the plain-text body of a Gmail message payload (text/plain preferred)."""
    plain: list[str] = []
    rich: list[str] = []

    def walk(part: dict[str, Any]) -> None:
        mime = part.get("mimeType", "")
        data = part.get("body", {}).get("data")
        if data and mime == "text/plain":
            plain.append(_decode(data))
        elif data and mime == "text/html":
            rich.append(_html_to_text(_decode(data)))
        for sub in part.get("parts", []) or []:
            walk(sub)

    walk(payload)
    text = "\n".join(plain) if plain else "\n".join(rich)
    return re.sub(r"\s+", " ", text).strip()


ACCOUNT_LINK_WORDS = re.compile(
    r"cancel|unsubscribe-plan|subscription|account|billing|manage|abo|kuendig|kündig|k%C3%BCndig|konto|resili|abonnement",
    re.I,
)
STATIC_FILE = re.compile(r"\.(woff2?|ttf|otf|png|jpe?g|gif|svg|webp|ico|css|js)$", re.I)
URL_PATTERN = re.compile(r"""https?://[^\s"'<>)\]]+""")


def extract_account_links(payload: dict[str, Any], limit: int = 5) -> list[str]:
    """Links that look like account/cancel pages, without query strings (may hold tokens)."""
    found: list[str] = []

    def walk(part: dict[str, Any]) -> None:
        data = part.get("body", {}).get("data")
        if data and part.get("mimeType", "").startswith("text/"):
            for url in URL_PATTERN.findall(html.unescape(_decode(data))):
                clean = url.split("?", 1)[0].split("#", 1)[0].rstrip(".,;")
                if ACCOUNT_LINK_WORDS.search(clean) and not STATIC_FILE.search(clean) and clean not in found:
                    found.append(clean)
        for sub in part.get("parts", []) or []:
            walk(sub)

    walk(payload)
    return [u for u in found if len(u) <= 200][:limit]


def _is_auth_error(exc: Exception) -> bool:
    try:
        from google.auth.exceptions import RefreshError
    except ImportError:  # pragma: no cover
        RefreshError = ()  # type: ignore[assignment]
    if RefreshError and isinstance(exc, RefreshError):
        return True
    status = getattr(getattr(exc, "resp", None), "status", None)
    return status == 401


class GmailSource:
    """Read-only Gmail source. Pass OAuth credentials (see `subscription_finder.auth`).

    `terms` selects which emails are fetched: `BILLING_TERMS` (subscriptions, default) or
    `FOOTPRINT_TERMS` (also security, sign-up, statement, contract and order emails).

    `service` may be injected (e.g. a fake in tests) instead of credentials.
    """

    provider = "gmail"

    def __init__(
        self,
        credentials: Any = None,
        *,
        service: Any = None,
        months: int = 24,
        max_messages: int = 500,
        body_chars: int = 1500,
        snippet_chars: int = 200,
        today: date | None = None,
        terms: str = BILLING_TERMS,
    ):
        if credentials is None and service is None:
            raise ValueError("GmailSource needs credentials or a service")
        self._credentials = credentials
        self._service = service
        self.months = months
        self.max_messages = max_messages
        self.body_chars = body_chars
        self.snippet_chars = snippet_chars
        self.query = build_query(months, terms)
        self._today = today or date.today()
        self._account: str | None = None
        self._scanned = 0
        self._skipped = 0

    @property
    def service(self):
        if self._service is None:
            from googleapiclient.discovery import build

            self._service = build("gmail", "v1", credentials=self._credentials, cache_discovery=False)
        return self._service

    def _execute(self, request):
        try:
            return request.execute(num_retries=6)  # Gmail answers bursts with 403 rateLimitExceeded
        except Exception as exc:
            if _is_auth_error(exc):
                raise ReconnectRequired("Gmail access expired or was revoked; please connect again") from exc
            raise

    @property
    def account(self) -> str | None:
        if self._account is None:
            try:
                profile = self._execute(self.service.users().getProfile(userId="me"))
                self._account = profile.get("emailAddress")
            except ReconnectRequired:
                raise
            except Exception:  # profile is informational only
                log.warning("could not read Gmail profile")
        return self._account

    def _list_ids(self) -> list[str]:
        ids: list[str] = []
        page_token = None
        while len(ids) < self.max_messages:
            request = self.service.users().messages().list(
                userId="me", q=self.query, pageToken=page_token, maxResults=min(100, self.max_messages - len(ids))
            )
            response = self._execute(request)
            ids.extend(m["id"] for m in response.get("messages", []))
            page_token = response.get("nextPageToken")
            if not page_token:
                break
        return ids[: self.max_messages]

    def _parse(self, message: dict[str, Any]) -> EmailMessage:
        payload = message.get("payload", {})
        headers = {h["name"].lower(): h["value"] for h in payload.get("headers", [])}
        millis = int(message["internalDate"])
        msg_date = datetime.fromtimestamp(millis / 1000, tz=timezone.utc).date()
        snippet = html.unescape(message.get("snippet", ""))[: self.snippet_chars]
        return EmailMessage(
            message_id=message["id"],
            date=msg_date,
            sender=headers.get("from", ""),
            subject=headers.get("subject", ""),
            body=extract_body(payload)[: self.body_chars],
            snippet=snippet,
            account_links=extract_account_links(payload),
        )

    def fetch(self, progress: Callable[[str, float], None] | None = None) -> list[EmailMessage]:
        ids = self._list_ids()
        log.info("gmail: %d candidate messages", len(ids))
        messages: list[EmailMessage] = []
        for i, message_id in enumerate(ids):
            if progress and i % 20 == 0:
                progress(f"Reading emails ({i}/{len(ids)})", i / max(len(ids), 1))
            try:
                raw = self._execute(self.service.users().messages().get(userId="me", id=message_id, format="full"))
                messages.append(self._parse(raw))
                self._scanned += 1
            except ReconnectRequired:
                raise
            except Exception:
                self._skipped += 1
        log.info("gmail: %d parsed, %d skipped", self._scanned, self._skipped)
        return messages

    def stats(self) -> dict[str, Any]:
        start = self._today - timedelta(days=round(self.months * 30.44))
        return {
            "provider": self.provider,
            "account": self._account,
            "query": self.query,
            "date_range": [start.isoformat(), self._today.isoformat()],
            "messages_scanned": self._scanned,
            "skipped": self._skipped,
        }
