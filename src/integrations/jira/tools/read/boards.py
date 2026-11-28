"""List Jira boards belonging to configured projects."""



from mcp.types import ToolAnnotations

from ...core.client import request
from ...core.validation import read_project_key
from src.shared.tool_output import compact_json


def register(server) -> None:
    @server.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))
    def jira_list_boards(project: str, include_raw: bool = False) -> str:
        """List boards for a configured project; include_raw returns Jira's complete response."""
        key = read_project_key(project)
        result = request("GET", "/rest/agile/1.0/board", params={"projectKeyOrId": key, "maxResults": "100"})
        if include_raw:
            return compact_json(result)
        boards = [{key: board[key] for key in ("id", "name", "type", "self") if board.get(key) is not None}
                  for board in result.get("values", [])]
        return compact_json({"boards": boards, "total": result.get("total", len(boards)),
                             "isLast": result.get("isLast", True)})
