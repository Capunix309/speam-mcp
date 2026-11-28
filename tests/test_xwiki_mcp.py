import json
import unittest
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from unittest.mock import patch

from src.integrations.xwiki.core import config as xwiki_config
from src.integrations.xwiki.core.client import normalize_space_path, page_url
from src.integrations.xwiki.tools import reports
from src.integrations.xwiki.tools import pages as page_tools
from src.integrations.xwiki.tools import attachments as attachment_tools
from src.integrations.xwiki.tools import workflow as wiki_workflow
from src.server import create_server
from src.shared import config


class XWikiMCPTests(unittest.TestCase):
    def test_read_page_defaults_to_content_and_supports_metadata_objects_and_raw(self):
        from mcp.server.fastmcp import FastMCP

        server = FastMCP("xwiki-page-output-test")
        page_tools.register(server)
        read_page = server._tool_manager.get_tool("read_page").fn
        data = {"title": "Page title", "content": "0123456789", "syntax": "xwiki/2.1",
                "version": "3.2", "objects": [{"className": "Example"}], "internal": "not in default"}
        with patch("src.integrations.xwiki.tools.pages.get_page", return_value=data):
            default = json.loads(read_page("Space", "Page", max_chars=5))
            details = json.loads(read_page("Space", "Page", include_metadata=True, include_objects=True,
                                           start=5, max_chars=5))
            raw = json.loads(read_page("Space", "Page", include_raw=True))
        self.assertEqual(default, {"page": "Space.Page", "content": "01234", "totalChars": 10,
                                  "truncated": True, "next_start": 5})
        self.assertEqual(details["content"], "56789")
        self.assertEqual(details["metadata"]["title"], "Page title")
        self.assertEqual(details["objects"], [{"className": "Example"}])
        self.assertEqual(raw, data)

    def test_binary_attachment_is_omitted_by_default_and_available_on_request(self):
        from mcp.server.fastmcp import FastMCP

        server = FastMCP("xwiki-attachment-output-test")
        attachment_tools.register(server)
        read_attachment = server._tool_manager.get_tool("read_attachment").fn
        with patch("src.integrations.xwiki.tools.attachments.request", return_value=(bytes([0, 1]), "application/pdf")):
            default = json.loads(read_attachment("Space", "Page", "diagram.pdf"))
            full = json.loads(read_attachment("Space", "Page", "diagram.pdf", include_base64=True))
        self.assertNotIn("base64", default)
        self.assertEqual(default["size"], 2)
        self.assertEqual(full["base64"], "AAE=")

    def test_project_status_returns_a_paginated_task_window(self):
        from mcp.server.fastmcp import FastMCP

        server = FastMCP("xwiki-project-status-output-test")
        wiki_workflow.register(server)
        tool = server._tool_manager.get_tool("project_status").fn
        pages = [
            {"fullName": "wiki:Space.First", "space": "Space", "name": "First", "title": "First"},
            {"fullName": "wiki:Space.Second", "space": "Space", "name": "Second", "title": "Second"},
        ]
        with patch("src.integrations.xwiki.tools.workflow.all_pages", return_value=pages), patch(
            "src.integrations.xwiki.tools.workflow.get_page", side_effect=[
                {"content": "[ ] First task" + chr(10) + "[x] Done task"},
                {"content": "[ ] Third task"},
            ],
        ):
            first = json.loads(tool("Space", task_limit=2))
            # Re-read the deterministic fixtures for the second page of tasks.
            with patch("src.integrations.xwiki.tools.workflow.all_pages", return_value=pages), patch(
                "src.integrations.xwiki.tools.workflow.get_page", side_effect=[
                    {"content": "[ ] First task" + chr(10) + "[x] Done task"},
                    {"content": "[ ] Third task"},
                ],
            ):
                second = json.loads(tool("Space", task_start=2, task_limit=2))
        self.assertEqual(first["total"], 3)
        self.assertEqual(len(first["tasks"]), 2)
        self.assertEqual(first["next_task_start"], 2)
        self.assertEqual(len(second["tasks"]), 1)
        self.assertIsNone(second["next_task_start"])

    def test_nested_space_paths_are_normalized_consistently(self):
        self.assertEqual(normalize_space_path("Planning.Equipe"), "Planning/Equipe")
        self.assertEqual(normalize_space_path("Planning/Equipe"), "Planning/Equipe")
        self.assertEqual(
            page_url("Planning.Equipe", "Sprint 1"),
            page_url("Planning/Equipe", "Sprint 1"),
        )

    def test_central_config_keeps_wikis_and_permissions(self):
        self.assertIn(xwiki_config.DEFAULT_WIKI, xwiki_config.WIKIS)
        self.assertTrue(any(wiki.read_only for wiki in xwiki_config.WIKIS.values()))
        self.assertTrue(any(not wiki.read_only for wiki in xwiki_config.WIKIS.values()))

    def test_combined_server_registers_xwiki_tools_without_upload_tool(self):
        with patch("src.server.auth_check.check_enabled_integrations"):
            server = create_server()
        names = {tool.name for tool in server._tool_manager.list_tools()}
        self.assertIn("read_page", names)
        self.assertIn("list_attachments", names)
        self.assertIn("read_attachment", names)
        self.assertNotIn("upload_attachment", names)
        self.assertNotIn("move_page", names)
        self.assertIn("jira_search", names)
        self.assertIn("get_auth_status", names)
        self.assertIn("changes_between", names)
        self.assertTrue(server._tool_manager.get_tool("changes_between").annotations.readOnlyHint)

    def test_changes_between_includes_start_and_end_dates_in_timezone_and_deduplicates_pages(self):
        from mcp.server.fastmcp import FastMCP

        start_ms = int(datetime(2026, 11, 1, 0, 0, tzinfo=ZoneInfo("Europe/Brussels")).timestamp() * 1000)
        end_ms = int(datetime(2026, 11, 3, 0, 0, tzinfo=ZoneInfo("Europe/Brussels")).timestamp() * 1000)
        items = [
            {"pageId": "wiki:Space.Page", "space": "Space", "name": "Page", "version": "1.1",
             "modified": start_ms, "modifier": "wiki:XWiki.A", "comment": "created"},
            {"pageId": "wiki:Space.Page", "space": "Space", "name": "Page", "version": "1.2",
             "modified": end_ms - 1, "modifier": "wiki:XWiki.B", "comment": "updated"},
            {"pageId": "wiki:Space.Other", "space": "Space", "name": "Other", "version": "1.1",
             "modified": end_ms, "modifier": "wiki:XWiki.C", "comment": "outside"},
        ]
        server = FastMCP("xwiki-changes-test")
        reports.register(server)
        tool = server._tool_manager.get_tool("changes_between")
        with patch("src.integrations.xwiki.tools.reports.get", return_value={"historySummaries": items}) as get:
            result = json.loads(tool.fn(
                "2026-11-01", "2026-11-02", "Europe/Brussels", start=0, limit=10,
            ))

        expected_start = int(datetime(2026, 11, 1, 0, 0, tzinfo=ZoneInfo("Europe/Brussels")).timestamp() * 1000)
        get.assert_called_once_with("modifications", [
            ("date", str(expected_start)), ("start", "0"), ("number", "11"),
        ])
        self.assertEqual(result["changeCount"], 2)
        self.assertEqual(result["pageCount"], 1)
        self.assertEqual(result["pages"][0]["space"], "Space")
        self.assertEqual(result["pages"][0]["page"], "Page")
        self.assertEqual(result["pages"][0]["changeCount"], 2)
        self.assertEqual(result["changes"][1]["version"], "1.2")
        self.assertFalse(result["truncated"])

    def test_changes_between_reports_continuation_for_a_full_page(self):
        from mcp.server.fastmcp import FastMCP

        server = FastMCP("xwiki-changes-pagination-test")
        reports.register(server)
        item = {"pageId": "wiki:Space.Page", "space": "Space", "name": "Page", "version": "1.1",
                "modified": 1795476960000}
        lookahead = {**item, "version": "1.2", "modified": 1795476961000}
        with patch("src.integrations.xwiki.tools.reports.get", return_value={"modifications": [item, lookahead]}) as get:
            result = json.loads(server._tool_manager.get_tool("changes_between").fn(
                "2026-11-01", "2026-11-30", "UTC", 20, 1,
            ))
        get.assert_called_once_with("modifications", [
            ("date", "1793491200000"), ("start", "20"), ("number", "2"),
        ])
        self.assertTrue(result["truncated"])
        self.assertEqual(result["next_start"], 21)

    def test_changes_between_rejects_invalid_ranges_before_request(self):
        from mcp.server.fastmcp import FastMCP

        server = FastMCP("xwiki-changes-validation-test")
        reports.register(server)
        tool = server._tool_manager.get_tool("changes_between")
        with patch("src.integrations.xwiki.tools.reports.get") as get:
            with self.assertRaisesRegex(ValueError, "YYYY-MM-DD"):
                tool.fn("2026/11/01", "2026-11-02")
            with self.assertRaisesRegex(ValueError, "on or before"):
                tool.fn("2026-11-03", "2026-11-02")
            with self.assertRaisesRegex(ValueError, "IANA timezone"):
                tool.fn("2026-11-01", "2026-11-02", "Invalid/Zone")
            get.assert_not_called()

    def test_local_calendar_day_bounds_follow_daylight_saving(self):
        start_ms, end_ms = reports._date_range_bounds("2026-03-29", "2026-03-29", "Europe/Brussels")
        self.assertEqual(end_ms - start_ms, 23 * 60 * 60 * 1000)

    def test_xwiki_tools_declare_read_or_write_on_the_decorator(self):
        with patch("src.shared.config.expose_destructive_tools", return_value=True):
            with patch("src.server.auth_check.check_enabled_integrations"):
                server = create_server()
        tools = {tool.name: tool for tool in server._tool_manager.list_tools()}
        self.assertTrue(tools["read_page"].annotations.readOnlyHint)
        self.assertFalse(tools["edit_page"].annotations.readOnlyHint)

    def test_write_tools_can_be_hidden_from_the_model(self):
        with patch("src.shared.config.expose_write_tools", return_value=False):
            with patch("src.server.auth_check.check_enabled_integrations"):
                server = create_server()
        names = {tool.name for tool in server._tool_manager.list_tools()}
        self.assertIn("read_page", names)
        self.assertIn("jira_search", names)
        self.assertNotIn("edit_page", names)
        self.assertNotIn("jira_create_issue", names)

    def test_disabled_xwiki_tools_are_not_registered(self):
        xwiki = config.IntegrationConfig(False, "", "", "", "", None, None)
        jira = config.IntegrationConfig(True, "https://jira.example", "", "", "", "JIRA_USERNAME", "JIRA_PASSWORD")
        with patch("src.shared.config.validate_config"), patch(
            "src.server.config.integration", side_effect=lambda name: {"xwiki": xwiki, "jira": jira}[name]
        ), patch("src.server.auth_check.check_enabled_integrations"):
            server = create_server()
        names = {tool.name for tool in server._tool_manager.list_tools()}
        self.assertIn("jira_search", names)
        self.assertNotIn("read_page", names)


if __name__ == "__main__":
    unittest.main()
