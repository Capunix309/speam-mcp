"""Keep startup authentication results for the lifetime of the MCP process."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AuthStatus:
    state: str
    diagnostic: str


_statuses: dict[str, AuthStatus] = {}


def reset() -> None:
    """Clear statuses before a server instance performs startup checks."""
    _statuses.clear()


def set_status(integration: str, state: str, diagnostic: str) -> None:
    """Store a safe, non-secret status for one integration."""
    _statuses[integration] = AuthStatus(state, diagnostic)


def status(integration: str) -> AuthStatus:
    """Return the current status, defaulting to enabled-but-unchecked."""
    return _statuses.get(integration, AuthStatus("UNKNOWN", "No startup check was recorded."))


def all_statuses() -> dict[str, AuthStatus]:
    """Return a copy of all known integration statuses."""
    return dict(_statuses)


def require_available(integration: str) -> None:
    """Prevent calls to an integration whose startup authentication failed."""
    result = status(integration)
    if result.state == "AUTH_FAILURE":
        raise RuntimeError(
            f"{integration} is unavailable because its startup authentication check failed. "
            "Tell the user to correct the credentials. Do not restart the MCP client "
            "until they are corrected, to avoid repeated authentication attempts."
        )


def safe_failure_diagnostic(error: Exception) -> str:
    """Describe a failed check without exposing response bodies or credentials."""
    message = str(error)
    for code in (401, 403):
        if f"HTTP {code}" in message:
            return f"The service rejected authentication or access (HTTP {code})."
    return "The authentication or access check failed. Verify credentials, authorization, and service availability."
