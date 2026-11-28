"""Search Jira users."""



from mcp.types import ToolAnnotations

from ...core.client import request
from ...core.validation import read_project_key
from src.shared.tool_output import compact_json


def register(server) -> None:
    @server.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))
    def jira_search_users(project: str, query: str, include_email: bool = False,
                          include_raw: bool = False) -> str:
        """Find assignable users; request email or complete Jira records only when needed."""
        key = read_project_key(project)
        if not query.strip():
            raise ValueError("query cannot be empty.")
        result = request(
            "GET", "/rest/api/2/user/assignable/search",
            params={"project": key, "query": query.strip(), "maxResults": "50"},
        )
        if include_raw:
            return compact_json(result)
        users = []
        for user in result if isinstance(result, list) else result.get("values", []):
            fields = ("name", "key", "accountId", "displayName", "active", "emailAddress")
            users.append({key: user[key] for key in fields
                          if user.get(key) is not None and (key != "emailAddress" or include_email)})
        return compact_json({"users": users, "count": len(users)})
