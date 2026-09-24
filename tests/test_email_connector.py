import json
from urllib.parse import parse_qs, urlparse

import pytest

pytest.importorskip("subscription_finder")

import subscription_finder.auth as finder_auth  # noqa: E402
from digital_estate_manager.discovery import email_connector  # noqa: E402
from digital_estate_manager.discovery import (  # noqa: E402
    EmailConnectionError,
    InvalidOAuthState,
    complete_email_connection,
    connect_email_provider,
)

REDIRECT = "http://localhost:8501"


@pytest.fixture
def web_client(tmp_path):
    path = tmp_path / "credentials_web.json"
    path.write_text(json.dumps({"web": {
        "client_id": "test-client.apps.googleusercontent.com",
        "client_secret": "test-secret",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "redirect_uris": [REDIRECT],
    }}))
    return path


def test_connect_gmail_returns_real_authorization_url(web_client):
    res = connect_email_provider(
        provider="gmail", email_address="alex@gmail.com", client_secrets_path=web_client, redirect_uri=REDIRECT
    )
    assert res["success"] is True
    assert res["provider"] == "gmail"
    assert res["status"] == "ready_for_auth"
    assert res["state"] and res["code_verifier"]

    url = urlparse(res["auth_url"])
    query = parse_qs(url.query)
    assert url.netloc == "accounts.google.com"
    assert query["client_id"] == ["test-client.apps.googleusercontent.com"]
    assert query["redirect_uri"] == [REDIRECT]
    assert query["state"] == [res["state"]]
    assert query["scope"] == ["https://www.googleapis.com/auth/gmail.readonly"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["login_hint"] == ["alex@gmail.com"]


def test_connect_uses_configured_web_client(monkeypatch, web_client):
    monkeypatch.setenv("GOOGLE_WEB_CREDENTIALS", str(web_client))
    monkeypatch.setenv("GOOGLE_OAUTH_REDIRECT_URI", REDIRECT)
    assert connect_email_provider(provider="gmail")["status"] == "ready_for_auth"


def test_missing_web_client_is_reported(tmp_path):
    res = connect_email_provider(provider="gmail", client_secrets_path=tmp_path / "missing.json")
    assert res["success"] is False
    assert res["status"] == "not_configured"


def test_unsupported_provider_rejected():
    res = connect_email_provider(provider="outlook", email_address="alex@outlook.com")
    assert res["success"] is False
    assert res["status"] == "unsupported"


class FakeCreds:
    def to_json(self):
        return json.dumps({"token": "t", "refresh_token": "r"})


@pytest.fixture
def exchange_calls(monkeypatch):
    calls = []

    def fake_exchange(code, state, redirect_uri, code_verifier=None, client_secrets_path=None):
        calls.append({"code": code, "state": state, "redirect_uri": redirect_uri, "verifier": code_verifier,
                      "secrets": client_secrets_path})
        return FakeCreds()

    monkeypatch.setattr(finder_auth, "exchange_code", fake_exchange)
    return calls


def start_login(web_client):
    return connect_email_provider(provider="gmail", client_secrets_path=web_client, redirect_uri=REDIRECT)


def test_complete_connection_uses_remembered_verifier(web_client, exchange_calls):
    started = start_login(web_client)
    creds = complete_email_connection("c0de", started["state"], redirect_uri=REDIRECT, client_secrets_path=web_client)
    assert creds == {"token": "t", "refresh_token": "r"}
    assert exchange_calls == [
        {"code": "c0de", "state": started["state"], "redirect_uri": REDIRECT, "verifier": started["code_verifier"],
         "secrets": web_client}
    ]


@pytest.mark.parametrize("state", [None, "", "forged-state"])
def test_unknown_state_is_rejected_without_exchange(web_client, exchange_calls, state):
    with pytest.raises(InvalidOAuthState):
        complete_email_connection("c0de", state, client_secrets_path=web_client)
    assert exchange_calls == []


def test_state_is_single_use(web_client, exchange_calls):
    state = start_login(web_client)["state"]
    complete_email_connection("c0de", state, client_secrets_path=web_client)
    with pytest.raises(InvalidOAuthState):
        complete_email_connection("c0de", state, client_secrets_path=web_client)
    assert len(exchange_calls) == 1


def test_expired_state_is_rejected(monkeypatch, web_client, exchange_calls):
    state = start_login(web_client)["state"]
    monkeypatch.setattr(email_connector, "PENDING_LOGIN_TTL_SECONDS", -1)
    with pytest.raises(InvalidOAuthState):
        complete_email_connection("c0de", state, client_secrets_path=web_client)


def test_connect_with_auth_code_completes(web_client, exchange_calls):
    state = start_login(web_client)["state"]
    res = connect_email_provider(
        provider="gmail", auth_code="c0de", state=state, client_secrets_path=web_client, redirect_uri=REDIRECT
    )
    assert res["status"] == "connected" and res["credentials"]["token"] == "t"
    assert exchange_calls[0]["secrets"] == web_client
    assert connect_email_provider(provider="gmail", auth_code="c0de", state="forged")["status"] == "error"


def test_complete_connection_wraps_oauth_errors(monkeypatch, web_client):
    def failing_exchange(*args, **kwargs):
        raise ValueError("invalid_grant")

    monkeypatch.setattr(finder_auth, "exchange_code", failing_exchange)
    state = start_login(web_client)["state"]
    with pytest.raises(EmailConnectionError):
        complete_email_connection("c0de", state, client_secrets_path=web_client)
