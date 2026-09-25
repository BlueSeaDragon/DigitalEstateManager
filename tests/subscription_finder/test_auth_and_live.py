import json
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import pytest

from subscription_finder.auth import SCOPES, build_authorization_url, credentials_from_dict, credentials_to_dict
from subscription_finder.config import Settings
from subscription_finder.llm.client import LLMClient

CLIENT = {
    "web": {
        "client_id": "123.apps.googleusercontent.com",
        "client_secret": "secret",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "redirect_uris": ["http://localhost:8501"],
    }
}


def test_authorization_url_has_readonly_scope_and_state(tmp_path):
    secrets = tmp_path / "credentials.json"
    secrets.write_text(json.dumps(CLIENT), encoding="utf-8")
    request = build_authorization_url("http://localhost:8501", client_secrets_path=secrets)
    query = parse_qs(urlparse(request.url).query)
    assert query["scope"] == [" ".join(SCOPES)]
    assert query["state"] == [request.state]
    assert query["redirect_uri"] == ["http://localhost:8501"]
    assert query["access_type"] == ["offline"]
    assert request.code_verifier


def test_missing_client_file_points_to_readme(tmp_path):
    with pytest.raises(FileNotFoundError, match="README"):
        build_authorization_url("http://localhost", client_secrets_path=tmp_path / "missing.json")


def test_credentials_dict_round_trip():
    from google.oauth2.credentials import Credentials

    creds = Credentials(
        token="access", refresh_token="refresh", token_uri="https://oauth2.googleapis.com/token",
        client_id="id", client_secret="secret", scopes=SCOPES,
        expiry=(datetime.now(timezone.utc) + timedelta(hours=1)).replace(tzinfo=None),
    )
    data = credentials_to_dict(creds)
    json.dumps(data)  # storable in session state
    restored = credentials_from_dict(data)
    assert restored.token == "access" and restored.refresh_token == "refresh"
    assert restored.valid


@pytest.mark.live
def test_live_apertus_call():
    settings = Settings.from_env()
    settings.cache_dir = None
    llm = LLMClient(settings)
    answer = llm.complete_json("Reply with ONLY a JSON object.", 'Return {"ok": true}', max_tokens=20)
    assert answer == {"ok": True}
