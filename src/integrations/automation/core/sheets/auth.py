"""Load and refresh Google OAuth credentials from the native credential store."""

from __future__ import annotations

import json
from src.shared.credential_store import (
    SHEETS_CREDENTIAL_SERVICE,
    SHEETS_TOKEN_ACCOUNT,
    SHEETS_CLIENT_ACCOUNT,
    keyring_module,
)


# Retain these aliases for existing imports and stored entry compatibility.
KEYCHAIN_SERVICE = SHEETS_CREDENTIAL_SERVICE
KEYCHAIN_ACCOUNT = SHEETS_TOKEN_ACCOUNT
KEYCHAIN_CLIENT_ACCOUNT = SHEETS_CLIENT_ACCOUNT


SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def _keychain():
    """Legacy alias retained for callers/tests; only native backends are accepted."""
    try:
        return keyring_module()
    except Exception as error:
        raise RuntimeError(str(error)) from None


def load_credentials():
    """Load or refresh a token saved by the local authorization flow."""
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
    except ImportError:
        raise RuntimeError("Install MCP-tools dependencies before using Google Sheets automation.") from None

    keyring = _keychain()
    token = keyring.get_password(KEYCHAIN_SERVICE, KEYCHAIN_ACCOUNT)
    if not token:
        raise RuntimeError(
            f"Google Sheets has not been authorized yet. Run "
            "python -m src.credentials set sheets."
        )
    try:
        credentials = Credentials.from_authorized_user_info(json.loads(token), SCOPES)
        if credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
            keyring.set_password(KEYCHAIN_SERVICE, KEYCHAIN_ACCOUNT, credentials.to_json())
        if not credentials.valid:
            raise RuntimeError("The saved Google authorization is expired or revoked; authorize again locally.")
        return credentials
    except RuntimeError:
        raise
    except Exception:
        raise RuntimeError(
            "Could not load Google Sheets authorization; rerun `python -m src.credentials set sheets`."
        ) from None
