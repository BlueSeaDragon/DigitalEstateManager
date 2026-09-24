"""Email Provider Connection (Gmail OAuth2 for the Streamlit app).

Wraps the subscription finder's OAuth helpers (`subscription_finder.auth`) with the
webapp's *Web application* OAuth client (`GOOGLE_WEB_CREDENTIALS`) and redirect URI
(`GOOGLE_OAUTH_REDIRECT_URI`). The CLI's desktop client is not used here.

Flow:
    connect_email_provider()      -> Google authorization URL; remembers state -> PKCE verifier
    (user consents; Google redirects to the app with ?code=...&state=...)
    complete_email_connection()   -> checks the state, returns a credentials dict

Started logins are kept in this module, not in st.session_state: the redirect back from
Google opens a new Streamlit session, while module state is shared by the server process.
"""

import os
import threading
import time
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlencode

from digital_estate_manager.config import google_oauth_redirect_uri, google_web_credentials_path


PENDING_LOGIN_TTL_SECONDS = 600

_pending_logins: Dict[str, Tuple[Optional[str], float]] = {}  # state -> (PKCE verifier, started at)
_pending_lock = threading.Lock()


class EmailConnectionError(Exception):
    """The OAuth exchange with the email provider failed; the user should try connecting again."""


class InvalidOAuthState(EmailConnectionError):
    """The redirect's state was not issued by this server, was already used, or has expired."""


def _remember_login(state: str, verifier: Optional[str]) -> None:
    with _pending_lock:
        now = time.time()
        for old_state, (_, started) in list(_pending_logins.items()):
            if now - started > PENDING_LOGIN_TTL_SECONDS:
                del _pending_logins[old_state]
        _pending_logins[state] = (verifier, now)


def _take_login(state: Optional[str]) -> Optional[str]:
    """Returns the verifier for `state` and forgets it (single use). Raises InvalidOAuthState."""
    with _pending_lock:
        entry = _pending_logins.pop(state, None) if state else None
    if entry is None or time.time() - entry[1] > PENDING_LOGIN_TTL_SECONDS:
        raise InvalidOAuthState("This Gmail sign-in is unknown or has expired. Please connect your Gmail account again.")
    return entry[0]


def connect_email_provider(
    provider: str = "gmail",
    email_address: Optional[str] = None,
    auth_code: Optional[str] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Starts (or, with `auth_code`, completes) an OAuth connection to an email provider.

    Currently only supports 'gmail'.

    Args:
        provider: Name of email provider (e.g. 'gmail').
        email_address: Optional address, passed to Google as a login hint.
        auth_code: Optional OAuth authorization code from the redirect. Requires the
            `state` keyword argument from the redirect.
        **kwargs: `state` when completing; `redirect_uri` / `client_secrets_path` to
            override the configured values.

    Returns:
        Dict with `success`, `status` and `message`. When starting: `auth_url`, `state`
        and `code_verifier` (also remembered server-side for the redirect). When
        completing: `credentials`.
    """
    normalized_provider = provider.strip().lower()

    if normalized_provider != "gmail":
        return {
            "success": False,
            "provider": provider,
            "status": "unsupported",
            "message": f"Provider '{provider}' is not supported yet. Only 'gmail' is currently supported.",
        }

    if auth_code:
        try:
            credentials = complete_email_connection(
                auth_code,
                kwargs.get("state"),
                redirect_uri=kwargs.get("redirect_uri"),
                client_secrets_path=kwargs.get("client_secrets_path"),
            )
        except EmailConnectionError as exc:
            return {"success": False, "provider": "gmail", "status": "error", "message": str(exc)}
        return {
            "success": True,
            "provider": "gmail",
            "status": "connected",
            "credentials": credentials,
            "message": "Gmail connected.",
        }

    client_secrets = kwargs.get("client_secrets_path") or google_web_credentials_path()
    redirect_uri = kwargs.get("redirect_uri") or google_oauth_redirect_uri()
    try:
        from subscription_finder.auth import build_authorization_url

        request = build_authorization_url(redirect_uri, client_secrets_path=client_secrets)
    except ImportError:
        return {
            "success": False,
            "provider": "gmail",
            "status": "unavailable",
            "message": "The subscription finder is not installed. Run: pip install -e ./subscription_finder",
        }
    except FileNotFoundError:
        return {
            "success": False,
            "provider": "gmail",
            "status": "not_configured",
            "message": (
                f"Google OAuth web client not found at {client_secrets}. "
                "Set GOOGLE_WEB_CREDENTIALS or place the file at config/credentials_web.json."
            ),
        }

    _remember_login(request.state, request.code_verifier)
    auth_url = request.url
    if email_address:
        auth_url += "&" + urlencode({"login_hint": email_address})

    return {
        "success": True,
        "provider": "gmail",
        "email_address": email_address,
        "status": "ready_for_auth",
        "auth_url": auth_url,
        "state": request.state,
        "code_verifier": request.code_verifier,
        "message": "Continue to Google to grant read-only Gmail access.",
    }


def complete_email_connection(
    code: str,
    state: Optional[str],
    verifier: Optional[str] = None,
    *,
    redirect_uri: Optional[str] = None,
    client_secrets_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Exchanges the authorization `code` from Google's redirect for Gmail credentials.

    `state` must have been issued by `connect_email_provider()` and is accepted only once
    (CSRF protection). `verifier` defaults to the PKCE verifier remembered for that state.
    Returns a JSON-serializable credentials dict (see `subscription_finder.auth.credentials_to_dict`).
    Raises InvalidOAuthState for an unknown/used/expired state and EmailConnectionError when
    the exchange fails.
    """
    from subscription_finder.auth import credentials_to_dict, exchange_code

    remembered_verifier = _take_login(state)
    verifier = verifier or remembered_verifier

    # Google may return previously granted scopes too (include_granted_scopes); don't fail on that.
    os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")
    try:
        creds = exchange_code(
            code,
            state,
            redirect_uri or google_oauth_redirect_uri(),
            code_verifier=verifier,
            client_secrets_path=client_secrets_path or google_web_credentials_path(),
        )
    except FileNotFoundError as exc:
        raise EmailConnectionError(str(exc)) from exc
    except Exception as exc:  # oauthlib / requests errors: expired code, wrong client, network
        raise EmailConnectionError(f"Google sign-in could not be completed ({type(exc).__name__}). Please connect again.") from exc
    return credentials_to_dict(creds)
