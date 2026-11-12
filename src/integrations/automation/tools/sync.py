"""Register the single public sprint-to-sheet automation tool."""

from __future__ import annotations

import json

from mcp.types import ToolAnnotations

from ..sync.service import sync_sprint


def register(server) -> None:
    @server.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False))
    def sync_sprint_sheet(
        sprint_name: str,
        start_date: str | None = None,
        end_date: str | None = None,
        sprint_names: list[str] | None = None,
    ) -> str:
        """Fetch Jira data and update the configured sprint analysis sheet.

        For one sprint, provide its exact name as sprint_name. To roll up subsprints,
        provide the review label as sprint_name and the exact child Jira sprint names
        as sprint_names; the tool combines their issues and uses their earliest start
        and latest end dates unless date overrides are supplied. Date overrides use
        YYYY-MM-DD and change only the reporting window.
        This tool writes to the configured Google Sheet and requires approval.
        """
        result = sync_sprint(
            sprint_name, start_date=start_date, end_date=end_date, sprint_names=sprint_names,
        )
        return json.dumps(result, ensure_ascii=False, indent=2)
