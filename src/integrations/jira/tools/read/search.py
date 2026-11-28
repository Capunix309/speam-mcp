"""Search issues in configured Jira projects."""

import re

from mcp.types import ToolAnnotations

from ...core.client import request
from ...core.output import DEFAULT_SEARCH_FIELDS, issue_summary
from ...core.validation import project_selector
from src.shared.tool_output import compact_json


def register(server) -> None:
    @server.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))
    def jira_search(
        project: str | None = None,
        text: str | None = None,
        issue_type: str | None = None,
        status: str | None = None,
        assignee: str | None = None,
        sprint: int | None = None,
        updated_after: str | None = None,
        max_results: int = 50,
        start_at: int = 0,
        fields: list[str] | None = None,
        include_raw: bool = False,
    ) -> str:
        """Search configured Jira projects and return compact issue summaries.

        Pass fields to choose Jira field IDs (including customfield_N). Set
        include_raw=true to receive Jira's complete issue objects for those fields.
        """
        projects = project_selector(project)
        if not 1 <= max_results <= 100 or start_at < 0:
            raise ValueError("max_results must be 1-100 and start_at cannot be negative.")
        selected_fields = fields if fields is not None else DEFAULT_SEARCH_FIELDS
        if not selected_fields or len(selected_fields) > 30 or any(
            not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", item) for item in selected_fields
        ):
            raise ValueError("fields must contain at most 30 Jira field IDs, including customfield_N values.")

        clauses: list[str] = []
        if text:
            clauses.append(f'text ~ "{_quote(text)}"')
        if issue_type:
            clauses.append(f'issuetype = "{_quote(issue_type)}"')
        if status:
            clauses.append(f'status = "{_quote(status)}"')
        if assignee:
            clauses.append(f'assignee = "{_quote(assignee)}"')
        if sprint is not None:
            if sprint <= 0:
                raise ValueError("sprint must be a positive sprint id.")
            clauses.append(f"sprint = {sprint}")
        if updated_after:
            clauses.append(f'updated >= "{_quote(updated_after)}"')

        results = []
        total = 0
        for configured in projects:
            jql = f'project = "{configured["key"]}"'
            if clauses:
                jql += " AND " + " AND ".join(f"({clause})" for clause in clauses)
            params = {"jql": jql, "maxResults": str(max_results), "startAt": str(start_at)}
            if not include_raw or fields is not None:
                params["fields"] = ",".join(selected_fields)
            result = request(
                "GET", "/rest/api/2/search",
                params=params,
            )
            total += int(result.get("total", len(result.get("issues", []))))
            found = result.get("issues", [])
            results.extend(found if include_raw else [issue_summary(item, selected_fields) for item in found])
        return compact_json({"startAt": start_at, "maxResults": max_results, "total": total,
                             "issues": results})


def _quote(value: str) -> str:
    """Escape user text embedded in a quoted JQL value."""
    return value.replace("\\", "\\\\").replace('"', '\\"')
