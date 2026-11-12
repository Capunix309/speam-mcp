"""Perform one startup authentication check for each enabled integration."""

from __future__ import annotations

from . import auth_state, config


def _record_check(name: str, check, description: str) -> None:
    try:
        check()
    except Exception as error:
        auth_state.set_status(
            name,
            "AUTH_FAILURE",
            auth_state.safe_failure_diagnostic(error),
            description,
        )
    else:
        auth_state.set_status(name, "READY", "Startup check succeeded.", description)


def check_xwiki() -> None:
    """Check XWiki access using the legacy page REST API available on 15.10."""
    from ..integrations.xwiki.core import config as xwiki_config
    from ..integrations.xwiki.core.client import page_url, request

    settings = xwiki_config.current()
    if not settings.username or not settings.password:
        raise RuntimeError("XWiki credentials are not configured.")
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
    SheetsClient(settings.spreadsheet_id).check_access()


def check_enabled_integrations() -> None:
    """Check enabled services once, retaining failures without stopping startup."""
    auth_state.reset()
    if config.integration("jira").enabled:
        _record_check("jira", check_jira, "GET Jira current-user REST endpoint")
    else:
        auth_state.set_status("jira", "DISABLED", "Integration is disabled.")
    if config.integration("xwiki").enabled:
        _record_check(
            "xwiki",
            check_xwiki,
            "GET Main.WebHome through the legacy page REST API in the default wiki",
        )
    else:
        auth_state.set_status("xwiki", "DISABLED", "Integration is disabled.")
    if config.automation_settings().get("enabled", False):
        _record_check("sheets", check_sheets, "Read metadata for the configured Google spreadsheet")
    else:
        auth_state.set_status("sheets", "DISABLED", "Google Sheets automation is disabled.")
