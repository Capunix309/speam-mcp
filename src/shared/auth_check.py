"""Perform one startup authentication check for each enabled integration."""

from __future__ import annotations

from urllib.parse import quote

from . import auth_state, config


def _record_check(name: str, check) -> None:
    try:
        check()
    except Exception as error:
        auth_state.set_status(name, "AUTH_FAILURE", auth_state.safe_failure_diagnostic(error))
    else:
        auth_state.set_status(name, "READY", "Startup authentication check succeeded.")


def check_xwiki() -> None:
    """Check credentials against the configured default wiki user resource."""
    from ..integrations.xwiki.core import config as xwiki_config
    from ..integrations.xwiki.core.client import request, wiki_url

    settings = xwiki_config.current()
    if not settings.username or not settings.password:
        raise RuntimeError("XWiki credentials are not configured.")
    request("GET", wiki_url(f"users/{quote(settings.username, safe='')}"), _skip_auth_check=True)


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
        _record_check("jira", check_jira)
    else:
        auth_state.set_status("jira", "DISABLED", "Integration is disabled.")
    if config.integration("xwiki").enabled:
        _record_check("xwiki", check_xwiki)
    else:
        auth_state.set_status("xwiki", "DISABLED", "Integration is disabled.")
    if config.automation_settings().get("enabled", False):
        _record_check("sheets", check_sheets)
    else:
        auth_state.set_status("sheets", "DISABLED", "Google Sheets automation is disabled.")
