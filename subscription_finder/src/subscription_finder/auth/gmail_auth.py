"""Gmail OAuth helpers, decoupled from fetching.

- CLI / local dev: `local_login()` opens a browser and caches `token.json`.
- Web (Streamlit): `build_authorization_url()` -> user consents at Google ->
  `exchange_code()` -> store `credentials_to_dict()` in session state ->
  `credentials_from_dict()` when running the scan.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..sources.email_base import ReconnectRequired

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
DEFAULT_CLIENT_SECRETS = "credentials.json"
DEFAULT_TOKEN = "token.json"


def _require_file(path: str | Path) -> Path:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(
            f"Gmail OAuth client file not found: {path}. "
            "Create a Desktop/Web OAuth client in Google Cloud Console and save it as "
            "credentials.json (see subscription_finder/README.md, 'Gmail setup')."
        )
    return path


def _refresh(creds):
    from google.auth.exceptions import RefreshError
    from google.auth.transport.requests import Request

    try:
        creds.refresh(Request())
    except RefreshError as exc:
        raise ReconnectRequired("Gmail token could not be refreshed; please connect again") from exc
    return creds


def local_login(
    client_secrets_path: str | Path = DEFAULT_CLIENT_SECRETS,
    token_path: str | Path = DEFAULT_TOKEN,
):
    """Interactive local OAuth (browser + loopback server). Caches the token file."""
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    token_path = Path(token_path)
    creds = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
        if creds and not creds.valid and creds.expired and creds.refresh_token:
            try:
                creds = _refresh(creds)
            except ReconnectRequired:
                creds = None
    if not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file(str(_require_file(client_secrets_path)), SCOPES)
        creds = flow.run_local_server(port=0)
    token_path.write_text(creds.to_json(), encoding="utf-8")
    return creds


@dataclass
class AuthorizationRequest:
    url: str
    state: str
    code_verifier: str | None  # keep with `state` (e.g. st.session_state) until the redirect returns


def _flow(client_secrets_path, redirect_uri, state=None, code_verifier=None):
    from google_auth_oauthlib.flow import Flow

    flow = Flow.from_client_secrets_file(
        str(_require_file(client_secrets_path)),
        scopes=SCOPES,
        state=state,
        redirect_uri=redirect_uri,
        code_verifier=code_verifier,
        autogenerate_code_verifier=code_verifier is None,
    )
    return flow


def build_authorization_url(
    redirect_uri: str, client_secrets_path: str | Path = DEFAULT_CLIENT_SECRETS
) -> AuthorizationRequest:
    """Start the web OAuth flow. Redirect the user to `.url`."""
    flow = _flow(client_secrets_path, redirect_uri)
    url, state = flow.authorization_url(access_type="offline", include_granted_scopes="true", prompt="consent")
    return AuthorizationRequest(url=url, state=state, code_verifier=flow.code_verifier)


def exchange_code(
    code: str,
    state: str,
    redirect_uri: str,
    code_verifier: str | None = None,
    client_secrets_path: str | Path = DEFAULT_CLIENT_SECRETS,
):
    """Finish the web OAuth flow with the `code` and `state` Google sent to `redirect_uri`."""
    flow = _flow(client_secrets_path, redirect_uri, state=state, code_verifier=code_verifier)
    flow.fetch_token(code=code)
    return flow.credentials


def credentials_to_dict(creds) -> dict[str, Any]:
    return json.loads(creds.to_json())


def credentials_from_dict(data: dict[str, Any]):
    """Rebuild credentials; refreshes if expired. Raises ReconnectRequired when that fails."""
    from google.oauth2.credentials import Credentials

    creds = Credentials.from_authorized_user_info(data, SCOPES)
    if not creds.valid:
        if creds.refresh_token:
            creds = _refresh(creds)
        else:
            raise ReconnectRequired("Gmail credentials are no longer valid; please connect again")
    return creds
