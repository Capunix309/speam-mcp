"""Access supported operating-system credential stores without file fallbacks."""

from __future__ import annotations

import json
import platform
from functools import lru_cache


INTEGRATION_CREDENTIAL_SERVICE = "mcp-tools.credentials"
SHEETS_CREDENTIAL_SERVICE = "mcp-tools.google-sheets"
SHEETS_TOKEN_ACCOUNT = "automation"
SHEETS_CLIENT_ACCOUNT = "oauth-client"


class CredentialStoreError(RuntimeError):
    """A safe, user-facing credential-store error with no backend payload."""


def _backend_is_native(system: str, module: str) -> bool:
    """Accept only keyring backends backed by a native system credential store."""
    prefixes = {
        "Darwin": ("keyring.backends.macOS",),
        "Windows": ("keyring.backends.Windows",),
        "Linux": ("keyring.backends.SecretService", "keyring.backends.kwallet"),
    }.get(system, ())
    return any(module.startswith(prefix) for prefix in prefixes)


def keyring_module():
    """Return Python keyring only when it selected a native secure backend."""
    system = platform.system()
    try:
        import keyring
    except ImportError:
        raise CredentialStoreError(
            "The Python keyring dependency is missing. Install MCP-tools dependencies first."
        ) from None
    try:
        backend_module = type(keyring.get_keyring()).__module__
    except Exception as error:
        raise CredentialStoreError(
            f"Could not initialize the {system} credential store ({type(error).__name__})."
        ) from None
    if not _backend_is_native(system, backend_module):
        store_name = {
            "Darwin": "macOS Keychain",
            "Windows": "Windows Credential Manager",
            "Linux": "Linux Secret Service or KWallet",
        }.get(system, "a supported native credential store")
        raise CredentialStoreError(
            f"Python keyring is not using {store_name}; no file-based fallback is allowed."
        )
    return keyring


@lru_cache(maxsize=None)
def get_secret(service: str, account: str) -> str | None:
    """Read a cached secret from the native credential store."""
    try:
        return keyring_module().get_password(service, account)
    except CredentialStoreError:
        raise
    except Exception as error:
        raise CredentialStoreError(
            f"Could not read the native credential store ({type(error).__name__})."
        ) from None


def set_secret(service: str, account: str, value: str) -> None:
    """Save a secret to the native credential store and refresh cached reads."""
    try:
        keyring_module().set_password(service, account, value)
    except CredentialStoreError:
        raise
    except Exception as error:
        raise CredentialStoreError(
            f"Could not write the native credential store ({type(error).__name__})."
        ) from None
    get_secret.cache_clear()


def delete_secret(service: str, account: str) -> None:
    """Remove one secret from the native credential store."""
    try:
        keyring_module().delete_password(service, account)
    except CredentialStoreError:
        raise
    except Exception as error:
        # Missing entries are harmless when clearing an integration's secrets.
        if type(error).__name__ not in {"PasswordDeleteError", "ItemNotFoundException"}:
            raise CredentialStoreError(
                f"Could not remove an entry from the native credential store ({type(error).__name__})."
            ) from None
    get_secret.cache_clear()


def integration_account(integration: str) -> str:
    """Return the stable account key that stores an integration credential pair."""
    if integration not in {"jira", "xwiki"}:
        raise ValueError("Choose Jira or XWiki credentials.")
    return integration


def get_integration_credentials(integration: str) -> tuple[str, str] | None:
    """Read a saved username/password pair without exposing it in diagnostics."""
    raw = get_secret(INTEGRATION_CREDENTIAL_SERVICE, integration_account(integration))
    if raw is None:
        return None
    try:
        saved = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        raise CredentialStoreError(
            f"Saved {integration.upper()} credentials are invalid; save them again with `python -m src.credentials set {integration}`."
        ) from None
    if not isinstance(saved, dict) or not isinstance(saved.get("username"), str) or not isinstance(saved.get("password"), str):
        raise CredentialStoreError(
            f"Saved {integration.upper()} credentials are invalid; save them again with `python -m src.credentials set {integration}`."
        )
    return saved["username"], saved["password"]


def set_integration_credentials(integration: str, username: str, password: str) -> None:
    """Atomically replace an integration's username/password record."""
    account = integration_account(integration)
    set_secret(INTEGRATION_CREDENTIAL_SERVICE, account, json.dumps({
        "username": username,
        "password": password,
    }))


def delete_integration_credentials(integration: str) -> None:
    """Remove an integration's saved username/password pair."""
    delete_secret(INTEGRATION_CREDENTIAL_SERVICE, integration_account(integration))


def sheets_credentials_present() -> bool:
    """Report whether both OAuth client configuration and token are present."""
    return bool(
        get_secret(SHEETS_CREDENTIAL_SERVICE, SHEETS_CLIENT_ACCOUNT)
        and get_secret(SHEETS_CREDENTIAL_SERVICE, SHEETS_TOKEN_ACCOUNT)
    )


def delete_sheets_credentials() -> None:
    """Remove both Google Sheets OAuth entries from the native credential store."""
    delete_secret(SHEETS_CREDENTIAL_SERVICE, SHEETS_TOKEN_ACCOUNT)
    delete_secret(SHEETS_CREDENTIAL_SERVICE, SHEETS_CLIENT_ACCOUNT)
