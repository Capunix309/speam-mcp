"""Tests for one-shot startup authentication checks and service gating."""

import unittest
from unittest.mock import patch

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
        self.assertEqual(auth_state.status("xwiki").state, "READY")
        self.assertEqual(auth_state.status("sheets").state, "AUTH_FAILURE")
        self.assertNotIn("secret", auth_state.status("sheets").diagnostic)

    def test_failed_integration_stays_blocked_until_a_new_process_check(self):
        auth_state.set_status("jira", "AUTH_FAILURE", "Rejected credentials.")
        with self.assertRaisesRegex(RuntimeError, "Do not restart"):
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

        auth_state.set_status("xwiki", "AUTH_FAILURE", "Rejected credentials.")
        server = FastMCP("auth-test")
        register(server)
        status_tool = server._tool_manager.get_tool("get_auth_status")
        result = status_tool.fn()
        self.assertIn("AUTH_FAILURE", result)
        self.assertIn("do not restart", status_tool.fn.__doc__.lower())
        self.assertTrue(status_tool.annotations.readOnlyHint)


if __name__ == "__main__":
    unittest.main()
