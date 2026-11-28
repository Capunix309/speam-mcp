"""Purpose-built Jira projections for compact MCP responses."""

from __future__ import annotations

from typing import Any


DEFAULT_SEARCH_FIELDS = ["summary", "issuetype", "status", "assignee", "priority", "labels", "updated", "parent"]


def issue_summary(issue: dict[str, Any], fields: list[str] | None = None) -> dict[str, Any]:
    """Project a Jira issue into useful scalar fields while retaining selected custom fields."""
    source = issue.get("fields", {})
    selected = fields or DEFAULT_SEARCH_FIELDS
    result: dict[str, Any] = {"key": issue.get("key")}
    for field in selected:
        if field not in source or source[field] is None:
            continue
        value = source[field]
        if field in {"issuetype", "status", "priority", "assignee", "reporter", "project", "parent"}:
            value = _named_value(value)
        result[_field_name(field)] = value
    return result


def _named_value(value: Any) -> Any:
    if not isinstance(value, dict):
        return value
    if value.get("displayName") is not None:
        return {key: value[key] for key in ("displayName", "accountId", "name") if value.get(key) is not None}
    if value.get("name") is not None:
        return value["name"]
    if value.get("key") is not None:
        return value["key"]
    return {key: value[key] for key in ("id", "key", "name") if value.get(key) is not None}


def _field_name(field: str) -> str:
    return {"issuetype": "type"}.get(field, field)
