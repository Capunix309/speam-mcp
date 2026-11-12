"""Tests for one-shot startup authentication checks and service gating."""

import json
import unittest
from unittest.mock import Mock, patch

from src.integrations.automation.core.sheets.client import SheetsClient
from src.integrations.jira.core import client as jira_client
from src.shared import auth_check, auth_state


class AuthCheckTests(unittest.TestCase):
    def tearDown(self):
        auth_state.reset()

    def test_startup_checks_each_enabled_service_once_and_records_safe_status(self):
        enabled = type("Settings", (), {"enabled": True})()
        with (
            patch.object(auth_check.config, "integration", return_value=enabled),
            patch.object(auth_check.config, "automation_settings", return_value={"enabled": True}),
            patch.object(auth_check, "check_jira", side_effect=RuntimeError("Jira returned HTTP 401: secret")) as jira,
            patch.object(auth_check, "check_xwiki") as xwiki,
            patch.object(auth_check, "check_sheets", side_effect=RuntimeError("token=secret")) as sheets,
        ):
            auth_check.check_enabled_integrations()

        jira.assert_called_once_with()
        xwiki.assert_called_once_with()
        sheets.assert_called_once_with()
        self.assertEqual(auth_state.status("jira").state, "AUTH_FAILURE")
        self.assertIn("HTTP 401", auth_state.status("jira").diagnostic)
        self.assertNotIn("secret", auth_state.status("jira").diagnostic)
        self.assertEqual(auth_state.status("jira").check, "GET Jira current-user REST endpoint")
        self.assertEqual(auth_state.status("xwiki").state, "READY")
        self.assertEqual(
            auth_state.status("xwiki").check,
            "GET Main.WebHome through the legacy page REST API in the default wiki",
        )
        self.assertEqual(auth_state.status("sheets").state, "AUTH_FAILURE")
        self.assertNotIn("secret", auth_state.status("sheets").diagnostic)
        self.assertEqual(auth_state.status("sheets").check, "Read metadata for the configured Google spreadsheet")

    def test_failed_integration_stays_blocked_until_a_new_process_check(self):
        auth_state.set_status(
            "jira",
            "AUTH_FAILURE",
            "The service returned HTTP 404.",
            "GET current-user endpoint",
        )
        with self.assertRaisesRegex(RuntimeError, "HTTP 404"):
            auth_state.require_available("jira")

        auth_state.set_status("jira", "READY", "Startup authentication check succeeded.")
        auth_state.require_available("jira")

    def test_jira_failure_blocks_requests_before_network_access(self):
        auth_state.set_status("jira", "AUTH_FAILURE", "Rejected credentials.")
        with patch.object(jira_client.urllib.request, "urlopen") as urlopen:
            with self.assertRaisesRegex(RuntimeError, "jira is unavailable"):
                jira_client.request("GET", "/rest/api/2/myself")
        urlopen.assert_not_called()

    def test_status_tool_reports_failure_and_user_instruction(self):
        from mcp.server.fastmcp import FastMCP
        from src.shared.auth_tools import register

        auth_state.set_status(
            "xwiki",
            "AUTH_FAILURE",
            "The service returned HTTP 404 (not found).",
            "GET Main.WebHome through the legacy page REST API in the default wiki",
        )
        server = FastMCP("auth-test")
        register(server)
        status_tool = server._tool_manager.get_tool("get_auth_status")
        result = json.loads(status_tool.fn())
        xwiki = result["integrations"]["xwiki"]
        self.assertEqual(xwiki["state"], "AUTH_FAILURE")
        self.assertEqual(
            xwiki["check"],
            "GET Main.WebHome through the legacy page REST API in the default wiki",
        )
        self.assertIn("HTTP 404", xwiki["diagnostic"])
        self.assertIn("Do not assume every AUTH_FAILURE", status_tool.fn.__doc__)
        self.assertIn("Do not assume credentials are wrong", result["assistant_instruction"])
        self.assertTrue(status_tool.annotations.readOnlyHint)

    def test_xwiki_check_uses_legacy_page_resource(self):
        from src.integrations.xwiki.core import config as xwiki_config
        from src.integrations.xwiki.core import client as xwiki_client

        settings = type("Settings", (), {"username": "configured-user", "password": "configured-password"})()
        with (
            patch.object(xwiki_config, "current", return_value=settings),
            patch.object(xwiki_client, "page_url", return_value="https://example.invalid/rest/page") as page_url,
            patch.object(xwiki_client, "request") as request,
        ):
            auth_check.check_xwiki()

        page_url.assert_called_once_with("Main", "WebHome")
        request.assert_called_once_with("GET", "https://example.invalid/rest/page", _skip_auth_check=True)

    def test_failure_diagnostics_distinguish_auth_access_endpoint_and_network_errors(self):
        cases = [
            (RuntimeError("XWiki returned HTTP 401: secret response body"), "does not identify which"),
            (RuntimeError("XWiki returned HTTP 403: secret response body"), "HTTP 403"),
            (RuntimeError("XWiki returned HTTP 404: secret response body"), "does not indicate incorrect credentials"),
            (RuntimeError("XWiki returned HTTP 503: secret response body"), "HTTP 503"),
            (RuntimeError("Could not reach the XWiki REST API: [Errno -2] Name or service not known"), "DNS failure"),
            (RuntimeError("Could not reach the XWiki REST API: [Errno 61] Connection refused"), "connection"),
            (RuntimeError("Could not reach the XWiki REST API: timed out"), "timed out"),
            (RuntimeError("XWiki credentials are not configured."), "Credentials are missing"),
        ]

        for error, expected in cases:
            with self.subTest(error=str(error)):
                diagnostic = auth_state.safe_failure_diagnostic(error)
                self.assertIn(expected.lower(), diagnostic.lower())
                self.assertNotIn("secret response body", diagnostic.lower())

    def test_sheets_access_failure_retains_http_status_without_response_body(self):
        class Response:
            status = 403

        class ApiError(Exception):
            resp = Response()

        client = SheetsClient.__new__(SheetsClient)
        client.spreadsheet_id = "workbook-id"
        client._service = Mock()
        client._service.spreadsheets.return_value.get.return_value.execute.side_effect = ApiError(
            "sensitive response body"
        )

        with self.assertRaisesRegex(RuntimeError, "HTTP 403") as raised:
            client.check_access()

        self.assertNotIn("sensitive response body", str(raised.exception))
        self.assertIn("HTTP 403", auth_state.safe_failure_diagnostic(raised.exception))


if __name__ == "__main__":
    unittest.main()
