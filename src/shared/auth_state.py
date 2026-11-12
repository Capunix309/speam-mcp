"""Keep startup authentication results for the lifetime of the MCP process."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class AuthStatus:
    state: str
    diagnostic: str
    check: str | None = None


_statuses: dict[str, AuthStatus] = {}


def reset() -> None:
    """Clear statuses before a server instance performs startup checks."""
    _statuses.clear()


def set_status(
    integration: str,
    state: str,
    diagnostic: str,
    check: str | None = None,
) -> None:
    """Store a safe, non-secret status for one integration."""
    _statuses[integration] = AuthStatus(state, diagnostic, check)


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
        check = result.check or "the integration's configured startup check"
        raise RuntimeError(
            f"{integration} is unavailable because {check} failed. {result.diagnostic} "
            "Fix the reported cause before restarting the MCP server; the check runs at startup."
        )


def safe_failure_diagnostic(error: Exception) -> str:
    """Classify a failed check without exposing response bodies or credentials."""
    message = str(error)
    lowered = message.lower()

    if "credentials are not configured" in lowered:
        return "Credentials are missing from the MCP configuration or environment. Check the configured variable names and that both values are available to the server."

    status_match = re.search(r"returned HTTP (\d{3})\b", message, flags=re.IGNORECASE)
    if status_match:
        code = int(status_match.group(1))
        if code == 401:
            return (
                "The service returned HTTP 401 (unauthenticated or unauthorized). This can mean "
                "the request was not authenticated or the account cannot access the checked resource; "
                "HTTP 401 alone does not identify which."
            )
        if code == 403:
            return (
                "The service returned HTTP 403 (forbidden). The account or integration is not allowed "
                "to access the checked resource; review its permissions."
            )
        if code == 404:
            return (
                "The service returned HTTP 404 (not found). Check the configured base URL, API path, "
                "and resource identifier; this status alone does not indicate incorrect credentials."
            )
        if code == 429:
            return "The service returned HTTP 429 (rate limited). The check was rejected temporarily; wait before retrying."
        if code >= 500:
            return f"The service returned HTTP {code} (server error). Check the service or reverse proxy status."
        if 400 <= code < 500:
            return f"The service returned HTTP {code} (request rejected). Check the integration endpoint and configured resource."
        return f"The service returned unexpected HTTP status {code}. Check the service endpoint and response configuration."

    if "could not reach" in lowered or "urlopen error" in lowered:
        dns_errors = (
            "name or service not known",
            "nodename nor servname",
            "getaddrinfo failed",
            "name resolution",
            "could not resolve",
        )
        if any(term in lowered for term in dns_errors):
            return "The service hostname could not be resolved (DNS failure). Check the configured base URL and network/DNS access."
        if "connection refused" in lowered:
            return "The service refused the network connection. Check the configured host, port, and service availability."
        if "timed out" in lowered or "timeout" in lowered:
            return "The service did not respond before the connection timed out. Check network access and service availability."
        if any(term in lowered for term in ("certificate verify failed", "ssl", "tls")):
            return "The TLS connection could not be verified. Check the configured HTTPS endpoint and certificate trust."
        return "The MCP could not reach the service. Check the configured base URL, network access, and service availability."

    error_type = type(error).__name__
    return f"The startup check failed with {error_type}; its details were withheld. Check the integration configuration and server logs."
