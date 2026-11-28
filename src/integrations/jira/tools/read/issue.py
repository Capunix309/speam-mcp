"""Retrieve issue details and optionally its related records."""


from mcp.types import ToolAnnotations

from ...core.client import request
from ...core.output import issue_summary
from .....shared import config
from src.shared.tool_output import compact_json


def register(server) -> None:
    @server.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))
    def jira_get_issue(
        issue: str,
        include_comments: bool = False,
        include_worklogs: bool = False,
        include_changelog: bool = False,
        include_epic_issues: bool = False,
        include_raw: bool = False,
    ) -> str:
        """Get a concise issue record with optional comments, worklogs, history, or epic children.

        Set include_raw=true to preserve Jira's full response objects for every
        requested detail section.
        """
        key = config.jira_issue_key(issue)
        fields = ["summary", "description", "issuetype", "status", "assignee", "reporter",
                  "priority", "labels", "parent", "project", "created", "updated"]
        if include_comments:
            fields.append("comment")
        if include_worklogs:
            fields.append("worklog")
        params = {"fields": ",".join(fields)}
        if include_changelog:
            params["expand"] = "changelog"
        result = request("GET", f"/rest/api/2/issue/{key}", params=params)
        issue_type = str(result.get("fields", {}).get("issuetype", {}).get("name", ""))
        child_issues = None
        if include_epic_issues and issue_type.casefold() == "epic":
            child_search = request(
                "GET", "/rest/api/2/search",
                params={"jql": f'"Epic Link" = "{key}"', "maxResults": "100"},
            )
            child_issues = child_search.get("issues", [])
            if include_raw:
                result["epic_issues"] = child_issues
        if include_raw:
            return compact_json(result)
        source = result.get("fields", {})
        fields_for_summary = ["summary", "description", "issuetype", "status", "assignee",
                              "reporter", "priority", "labels", "parent", "created", "updated"]
        output = issue_summary(result, fields_for_summary)
        for field in ("description", "created", "updated"):
            if source.get(field) is not None:
                output[field] = source[field]
        if include_comments:
            comments = source.get("comment", {}).get("comments", [])
            output["comments"] = [{"author": _person(item.get("author")), "created": item.get("created"),
                                   "body": item.get("body")} for item in comments]
        if include_worklogs:
            worklogs = source.get("worklog", {}).get("worklogs", [])
            output["worklogs"] = [{"author": _person(item.get("author")), "started": item.get("started"),
                                   "timeSpent": item.get("timeSpent"), "comment": item.get("comment")}
                                  for item in worklogs]
        if include_changelog:
            histories = result.get("changelog", {}).get("histories", [])
            output["changelog"] = [{"author": _person(item.get("author")), "created": item.get("created"),
                                    "items": [{key: change.get(key) for key in ("field", "fromString", "toString")}
                                              for change in item.get("items", [])]}
                                   for item in histories]
        if child_issues is not None:
            output["epic_issues"] = [issue_summary(item) for item in child_issues]
        return compact_json(output)


def _person(value):
    if not isinstance(value, dict):
        return value
    return {key: value[key] for key in ("displayName", "accountId", "name") if value.get(key) is not None}
