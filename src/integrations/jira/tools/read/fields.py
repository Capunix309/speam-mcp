"""Read project-specific issue types and Jira priorities."""



from mcp.types import ToolAnnotations

from ...core.client import request
from ...core.validation import read_project_key
from src.shared.tool_output import compact_json


def register(server) -> None:
    @server.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))
    def jira_get_issue_types(project: str, include_raw: bool = False) -> str:
        """List issue types; include_raw returns each complete Jira record."""
        key = read_project_key(project)
        result = request("GET", f"/rest/api/2/project/{key}")
        issue_types = result.get("issueTypes", [])
        selected = issue_types if include_raw else [
            {key: item[key] for key in ("id", "name", "description", "subtask") if item.get(key) is not None}
            for item in issue_types
        ]
        return compact_json(selected)

    @server.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))
    def jira_get_priorities(project: str, include_raw: bool = False) -> str:
        """List Jira priorities; include_raw returns each complete Jira record."""
        read_project_key(project)
        result = request("GET", "/rest/api/2/priority")
        priorities = result if isinstance(result, list) else result.get("priorities", result.get("values", []))
        if include_raw:
            return compact_json(result)
        compact = [{key: item[key] for key in ("id", "name", "description", "status") if item.get(key) is not None}
                   for item in priorities]
        return compact_json({"priorities": compact, "count": len(compact)})
