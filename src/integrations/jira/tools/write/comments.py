"""Add AI-attributed comments to Jira issues."""



from mcp.types import ToolAnnotations

from ...core.client import request
from .....shared import config
from src.shared.tool_output import compact_json


def register(server) -> None:
    @server.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False))
    def jira_add_comment(issue: str, comment: str, include_raw: bool = False) -> str:
        """Add an [AI]-attributed issue comment; include_raw returns Jira's response."""
        key = config.jira_issue_key(issue, write=True)
        text = comment.strip()
        if not text:
            raise ValueError("comment cannot be empty.")
        if not text.startswith("[AI]"):
            text = f"[AI] {text}"
        result = request("POST", f"/rest/api/2/issue/{key}/comment", body={"body": text})
        return compact_json(result if include_raw else {"ok": True, "issue": key,
                                                       "comment_id": result.get("id")})
