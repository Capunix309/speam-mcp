"""Create Jira issues and update common issue fields."""


import math
from typing import Any

from mcp.types import ToolAnnotations

from ...core.client import request
from .....shared import config
from src.shared.tool_output import compact_json


def register(server) -> None:
    @server.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False))
    def jira_create_issue(
        project: str,
        issue_type: str,
        summary: str,
        description: str,
        labels: list[str] | None = None,
        epic_name: str | None = None,
        story_points: float | None = None,
        epic_key: str | None = None,
        parent_issue: str | None = None,
        include_raw: bool = False,
    ) -> str:
        """Create an issue or sub-task; include_raw returns Jira's response object."""
        project_settings = config.jira_project(project, write=True)
        key = project_settings["key"]
        if not issue_type.strip() or not summary.strip():
            raise ValueError("issue_type and summary are required.")
        description_text = description.strip()
        if not description_text:
            raise ValueError("description is required.")
        if not description_text.startswith("[AI]"):
            description_text = f"[AI] {description_text}"
        issue_labels = list(dict.fromkeys([*(labels or []), "ai-assisted"]))
        issue_fields: dict[str, Any] = {
            "project": {"key": key},
            "issuetype": {"name": issue_type.strip()},
            "summary": summary.strip(),
            "description": description_text,
            "labels": issue_labels,
        }
        if parent_issue is not None:
            if epic_key is not None:
                raise ValueError("A sub-task parent and parent Epic cannot both be set.")
            parent_key = _parent_key(parent_issue, key)
            subtask_type = _subtask_issue_type(key, issue_type)
            issue_fields["issuetype"] = _issue_type_reference(subtask_type)
            issue_fields["parent"] = {"key": parent_key}
        is_epic = issue_type.strip().casefold() == "epic"
        if is_epic and (epic_name is None or not epic_name.strip()):
            raise ValueError("epic_name is required when creating an Epic.")
        if epic_name is not None:
            if not is_epic:
                raise ValueError("epic_name can only be set when issue_type is Epic.")
            issue_fields[_jira_field(project_settings, "epic_name_field", "Epic Name")] = epic_name.strip()
        if story_points is not None:
            issue_fields[_jira_field(project_settings, "story_points_field", "Story Points")] = _story_points(story_points)
        if epic_key is not None:
            issue_fields[_jira_field(project_settings, "epic_link_field", "Epic Link")] = _epic_key(epic_key)
        body = {"fields": issue_fields}
        result = request("POST", "/rest/api/2/issue", body=body)
        return _format(result if include_raw else {
            "ok": True, "action": "created", "key": result.get("key"), "id": result.get("id"),
        })

    @server.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False))
    def jira_update_issue(
        issue: str,
        summary: str | None = None,
        description: str | None = None,
        assignee: str | None = None,
        priority: str | None = None,
        labels: list[str] | None = None,
        story_points: float | None = None,
        epic_key: str | None = None,
        clear_epic_link: bool = False,
        parent_issue: str | None = None,
        subtask_issue_type: str | None = None,
        clear_parent: bool = False,
        include_raw: bool = False,
    ) -> str:
        """Update issue fields and parent; include_raw returns Jira's response object."""
        key = config.jira_issue_key(issue, write=True)
        project_settings = config.jira_project(key.rsplit("-", 1)[0], write=True)
        if epic_key is not None and clear_epic_link:
            raise ValueError("Set epic_key or clear_epic_link, not both.")
        if parent_issue is not None and clear_parent:
            raise ValueError("Set parent_issue or clear_parent, not both.")
        if subtask_issue_type is not None and parent_issue is None:
            raise ValueError("subtask_issue_type requires parent_issue.")
        if subtask_issue_type is not None and not subtask_issue_type.strip():
            raise ValueError("subtask_issue_type cannot be empty.")
        fields: dict[str, Any] = {}
        if summary is not None:
            if not summary.strip():
                raise ValueError("summary cannot be empty.")
            fields["summary"] = summary.strip()
        if description is not None:
            fields["description"] = description
        if assignee is not None:
            if not assignee.strip():
                raise ValueError("assignee cannot be empty; use an account id or username.")
            fields["assignee"] = {"name": assignee.strip()}
        if priority is not None:
            if not priority.strip():
                raise ValueError("priority cannot be empty.")
            fields["priority"] = {"name": priority.strip()}
        if labels is not None:
            fields["labels"] = labels
        if story_points is not None:
            fields[_jira_field(project_settings, "story_points_field", "Story Points")] = _story_points(story_points)
        if epic_key is not None:
            fields[_jira_field(project_settings, "epic_link_field", "Epic Link")] = _epic_key(epic_key)
        if clear_epic_link:
            fields[_jira_field(project_settings, "epic_link_field", "Epic Link")] = None
        update: dict[str, Any] = {}
        if parent_issue is not None:
            parent_key = _parent_key(parent_issue, project_settings["key"])
            current = request("GET", f"/rest/api/2/issue/{key}", params={"fields": "issuetype"})
            current_type = current.get("fields", {}).get("issuetype", {})
            if "subtask" not in current_type:
                raise RuntimeError("Jira did not return the current issue type; no update was attempted.")
            if subtask_issue_type is not None:
                target_type = _subtask_issue_type(project_settings["key"], subtask_issue_type)
                fields["issuetype"] = _issue_type_reference(target_type)
            elif not current_type.get("subtask", False):
                target_type = _subtask_issue_type(project_settings["key"])
                fields["issuetype"] = _issue_type_reference(target_type)
            fields["parent"] = {"key": parent_key}
        elif clear_parent:
            current = request("GET", f"/rest/api/2/issue/{key}", params={"fields": "issuetype"})
            current_type = current.get("fields", {}).get("issuetype", {})
            if "subtask" not in current_type:
                raise RuntimeError("Jira did not return the current issue type; no update was attempted.")
            if current_type.get("subtask", False):
                raise ValueError("A Jira sub-task must have a parent; convert it to a standard issue before clearing its parent.")
            # Jira's edit API uses the explicit 'none' operation to clear parent.
            update["parent"] = [{"set": {"none": True}}]
        if not fields and not update:
            raise ValueError("Provide at least one field to update.")
        body: dict[str, Any] = {}
        if fields:
            body["fields"] = fields
        if update:
            body["update"] = update
        result = request("PUT", f"/rest/api/2/issue/{key}", body=body)
        return _format(result if include_raw else {"ok": True, "action": "updated", "key": key})


def _format(value: Any) -> str:
    return compact_json(value, ensure_ascii=False, indent=2)


def _jira_field(project: dict, setting: str, display_name: str) -> str:
    """Resolve a Jira custom field from the selected project's settings."""
    field_id = project.get(setting)
    if not isinstance(field_id, str) or not field_id:
        raise ValueError(f"Configure {setting} on the Jira project before setting {display_name}.")
    return field_id


def _story_points(value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("story_points must be a non-negative number.")
    if not math.isfinite(value) or value < 0:
        raise ValueError("story_points must be a finite, non-negative number.")
    return value


def _epic_key(value: str) -> str:
    key = config.jira_issue_key(value)
    return key


def _parent_key(value: str, project_key: str) -> str:
    """Validate that a parent is writable and belongs to the same configured project."""
    key = config.jira_issue_key(value, write=True)
    if key.rsplit("-", 1)[0].casefold() != project_key.casefold():
        raise ValueError(f"Parent issue '{key}' must belong to configured project '{project_key}'.")
    return key


def _subtask_issue_type(project_key: str, requested: str | None = None) -> dict[str, Any]:
    """Find a configured project's sub-task type, requiring a choice if ambiguous."""
    result = request("GET", f"/rest/api/2/project/{project_key}")
    types = result.get("issueTypes", [])
    candidates = [item for item in types if item.get("subtask") is True]
    if requested is not None:
        selected = requested.strip().casefold()
        if not selected:
            raise ValueError("subtask_issue_type cannot be empty.")
        match = next((item for item in candidates if selected in {
            str(item.get("name", "")).casefold(), str(item.get("id", "")).casefold(),
        }), None)
        if match is None:
            raise ValueError(f"'{requested}' is not a sub-task issue type available in project '{project_key}'.")
        return match
    if not candidates:
        raise ValueError(f"Project '{project_key}' has no available sub-task issue type.")
    if len(candidates) > 1:
        choices = ", ".join(str(item.get("name", item.get("id", ""))) for item in candidates)
        raise ValueError(f"Specify subtask_issue_type; available sub-task types are: {choices}.")
    return candidates[0]


def _issue_type_reference(issue_type: dict[str, Any]) -> dict[str, str]:
    """Return Jira's stable issue type identifier when available."""
    if issue_type.get("id"):
        return {"id": str(issue_type["id"])}
    return {"name": str(issue_type["name"])}
