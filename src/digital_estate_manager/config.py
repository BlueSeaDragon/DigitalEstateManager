"""Webapp configuration: repository-rooted paths and environment variables.

Paths are resolved from the repository root, not the current working directory,
so `streamlit run app.py` works from anywhere.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# src/digital_estate_manager/config.py -> repository root
REPO_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_GOOGLE_WEB_CREDENTIALS = "config/credentials_web.json"
DEFAULT_GOOGLE_OAUTH_REDIRECT_URI = "http://localhost:8501"

# Existing environment variables win over the repository-level .env file.
load_dotenv(REPO_ROOT / ".env", override=False)


def resolve_repo_path(value: str) -> Path:
    """Returns `value` as an absolute path; relative paths are taken from the repository root."""
    path = Path(value).expanduser()
    return path if path.is_absolute() else REPO_ROOT / path


def google_web_credentials_path() -> Path:
    """OAuth *Web application* client used by the Streamlit app (not the CLI's desktop client)."""
    return resolve_repo_path(os.environ.get("GOOGLE_WEB_CREDENTIALS") or DEFAULT_GOOGLE_WEB_CREDENTIALS)


def google_oauth_redirect_uri() -> str:
    """Must match an authorized redirect URI of the web OAuth client."""
    return os.environ.get("GOOGLE_OAUTH_REDIRECT_URI") or DEFAULT_GOOGLE_OAUTH_REDIRECT_URI
