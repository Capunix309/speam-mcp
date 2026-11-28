"""List sprints belonging to a configured project's boards."""



from mcp.types import ToolAnnotations

from ...core.client import request
from ...core.validation import read_project_key
from src.shared.tool_output import compact_json


def register(server) -> None:
    @server.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))
    def jira_list_sprints(project: str, board_id: int, state: str | None = None,
                          include_raw: bool = False) -> str:
        """List board sprints; include_raw returns Jira's complete response."""
        key = read_project_key(project)
        _positive_id(board_id)
        boards = request(
            "GET", "/rest/agile/1.0/board",
            params={"projectKeyOrId": key, "maxResults": "100"},
        )
        if not any(str(board.get("id")) == str(board_id) for board in boards.get("values", [])):
            raise ValueError(f"Board {board_id} does not belong to configured project '{key}'.")
        params = {"maxResults": "100"}
        if state:
            if state.casefold() not in {"active", "future", "closed"}:
                raise ValueError("state must be active, future, or closed.")
            params["state"] = state.casefold()
        result = request("GET", f"/rest/agile/1.0/board/{board_id}/sprint", params=params)
        if include_raw:
            return compact_json(result)
        sprints = [{key: item[key] for key in ("id", "name", "state", "startDate", "endDate",
                                                "completeDate", "goal", "originBoardId")
                    if item.get(key) is not None} for item in result.get("values", [])]
        return compact_json({"sprints": sprints, "total": result.get("total", len(sprints)),
                             "isLast": result.get("isLast", True)})


def _positive_id(value: int) -> int:
    if value <= 0:
        raise ValueError("board_id must be a positive integer.")
    return value
