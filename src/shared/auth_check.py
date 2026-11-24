"""Perform one startup authentication check for each enabled integration."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed

from . import auth_state, config


def check_xwiki() -> None:
    """Check XWiki access using the legacy page REST API available on 15.10."""
    from ..integrations.xwiki.core import config as xwiki_config
    from ..integrations.xwiki.core.client import page_url, request

    settings = xwiki_config.current()
    if not settings.username or not settings.password:
        store_error = getattr(settings, "credential_store_error", None)
        if store_error:
            raise RuntimeError(store_error)
        raise RuntimeError(
            "XWiki credentials are missing. Save them with `python -m src.credentials set xwiki` "
            "or provide the configured environment variables."
        )
    # The /users REST resource was added in XWiki 18.2. Use the standard home
    # page rather than XWikiPreferences, which may be restricted to administrators.
    request("GET", page_url("Main", "WebHome"), _skip_auth_check=True)


def check_jira() -> None:
    """Check the configured account with Jira's identity endpoint."""
    from ..integrations.jira.core.client import request

    request("GET", "/rest/api/2/myself", _skip_auth_check=True)


def check_sheets() -> None:
    """Check OAuth credentials and access to the configured spreadsheet."""
    from ..integrations.automation.core.settings import load_settings
    from ..integrations.automation.core.sheets.client import SheetsClient

    settings = load_settings()
    SheetsClient.check_startup_access(settings.spreadsheet_id)


def _enabled_checks():
    checks = {}
    if config.integration("jira").enabled:
        checks["jira"] = (check_jira, "GET Jira current-user REST endpoint")
    if config.integration("xwiki").enabled:
        checks["xwiki"] = (
            check_xwiki,
            "GET Main.WebHome through the legacy page REST API in the default wiki",
        )
    if config.automation_settings().get("enabled", False):
        checks["sheets"] = (
            check_sheets,
            "Read metadata for the configured Google spreadsheet",
        )
    return checks


def prepare_enabled_integrations() -> None:
    """Mark enabled integrations as checking before the MCP handshake."""
    auth_state.reset()
    checks = _enabled_checks()
    descriptions = {
        "jira": "GET Jira current-user REST endpoint",
        "xwiki": "GET Main.WebHome through the legacy page REST API in the default wiki",
        "sheets": "Read metadata for the configured Google spreadsheet",
    }
    for name in ("jira", "xwiki", "sheets"):
        if name in checks:
            auth_state.set_status(name, "CHECKING", "Startup authentication check is in progress.", descriptions[name])
        elif name == "sheets":
            auth_state.set_status(name, "DISABLED", "Google Sheets automation is disabled.")
        else:
            auth_state.set_status(name, "DISABLED", "Integration is disabled.")


def run_enabled_integration_checks() -> None:
    """Run each configured startup check concurrently and record its result."""
    checks = _enabled_checks()

    if not checks:
        return

    # These checks are independent network calls. Running them concurrently keeps
    # startup bounded by the slowest integration instead of their combined latency.
    with ThreadPoolExecutor(max_workers=len(checks), thread_name_prefix="mcp-auth") as executor:
        futures = {
            executor.submit(check): (name, description)
            for name, (check, description) in checks.items()
        }
        for future in as_completed(futures):
            name, description = futures[future]
            try:
                future.result()
            except Exception as error:
                auth_state.set_status(
                    name,
                    "AUTH_FAILURE",
                    auth_state.safe_failure_diagnostic(error, integration=name),
                    description,
                )
            else:
                auth_state.set_status(name, "READY", "Startup check succeeded.", description)


def check_enabled_integrations() -> None:
    """Prepare and run startup checks synchronously (useful for direct callers)."""
    prepare_enabled_integrations()
    run_enabled_integration_checks()
