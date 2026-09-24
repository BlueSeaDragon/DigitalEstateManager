"""Email Provider Connection Interface.

Interface function to initiate OAuth2/API connection with an email provider
(e.g., Gmail) to discover subscription receipts, statements, and digital accounts.

NOTE: Backend authentication and email crawling are to be implemented by teammates.
This file defines the interface required by the UI.
"""

from typing import Any, Dict, Optional


def connect_email_provider(
    provider: str = "gmail",
    email_address: Optional[str] = None,
    auth_code: Optional[str] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Interface function to connect to an email provider to scan for receipts and subscriptions.

    Currently only supports 'gmail'. Backend integration hook for OAuth2 token exchange.

    Args:
        provider: Name of email provider (e.g. 'gmail').
        email_address: The target email address to connect.
        auth_code: Optional OAuth authorization code from redirect.
        **kwargs: Additional provider-specific settings.

    Returns:
        Dict with connection response, status, and instructions for the UI.
    """
    normalized_provider = provider.strip().lower()

    if normalized_provider != "gmail":
        return {
            "success": False,
            "provider": provider,
            "status": "unsupported",
            "message": f"Provider '{provider}' is not supported yet. Only 'gmail' is currently supported.",
        }

    # =========================================================================
    # BACKEND HOOK:
    # Teammate 2 hook goes here:
    # 1. Exchange auth_code for OAuth2 tokens via Google API client.
    # 2. Spawn email crawler task / background receipt parser.
    # =========================================================================

    return {
        "success": True,
        "provider": "gmail",
        "email_address": email_address or "user@gmail.com",
        "status": "ready_for_auth",
        "auth_url": (
            "https://accounts.google.com/o/oauth2/v2/auth?"
            "client_id=DEM_DEMO_CLIENT_ID&"
            "redirect_uri=urn:ietf:wg:oauth:2.0:oob&"
            "response_type=code&"
            "scope=https://www.googleapis.com/auth/gmail.readonly"
        ),
        "message": (
            f"Gmail connection interface initialized for {email_address or 'Google account'}. "
            "Backend OAuth2 exchange ready to be connected."
        ),
    }
