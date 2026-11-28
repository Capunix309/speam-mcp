import re

from mcp.types import ToolAnnotations
from ..core import config
from ..core.client import all_pages, get_page, page_fields, page_url, request, value_text, xml_page
from src.shared.tool_output import compact_json

LINK = re.compile(r"\[\[(.*?)\]\]")
HEADING = re.compile(r"^(={1,6})\s+(.+?)\s*=*\s*$", re.M)
TEMPLATES = {
    "meeting": "= Meeting: {title} =\n\nDate: {date}\nAttendees: {attendees}\n\n== Agenda ==\n{agenda}\n\n== Notes ==\n{notes}\n\n== Decisions ==\n{decisions}\n\n== Actions ==\n{actions}",
    "decision": "= Decision: {title} =\n\nDate: {date}\nStatus: Proposed\n\n== Context ==\n{context}\n\n== Decision ==\n{decision}\n\n== Consequences ==\n{consequences}",
    "task": "= {title} =\n\nStatus: To do\nOwner: {owner}\nDue date: {due_date}\n\n== Description ==\n{description}\n\n== Notes ==\n{notes}",
    "report": "= {title} =\n\nDate: {date}\n\n== Summary ==\n{summary}\n\n== Details ==\n{details}\n\n== Next steps ==\n{next_steps}",
}
DECISION = re.compile(r"\b(decision|decided|we will|agreed to|chosen option)\b", re.I)
TASK = re.compile(r"^\s*(?:[-*]\s*)?\[([ xX])\]\s*(.+)$")
OWNER = re.compile(r"(?:owner|responsible|assigned\s+to)\s*:\s*([^,;]+)", re.I)


def register(mcp):
    """Register this category of XWiki tools."""
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))
    def consistency_check(space: str, required_headings: list[str] | None = None,
                          scan_limit: int = 100, issue_limit: int = 50) -> str:
        """Check pages for required headings and unresolved internal page links."""
        if not 1 <= scan_limit <= 250:
            raise ValueError("scan_limit must be between 1 and 250.")
        if not 1 <= issue_limit <= 250:
            raise ValueError("issue_limit must be between 1 and 250.")
        required = [heading.casefold() for heading in (required_headings or [])]
        pages = all_pages(space, max_pages=scan_limit)
        known = {page_fields(item)["fullName"].split(":")[-1] for item in pages}
        issues = []
        for item in pages:
            meta = page_fields(item)
            try:
                body = get_page(meta["space"], meta["pageName"])
            except RuntimeError as exc:
                issues.append({"page": meta["fullName"], "error": str(exc)})
                continue
            content = value_text(body, "content")
            headings = {match.group(2).casefold() for match in HEADING.finditer(content)}
            missing = [heading for heading in required if heading not in headings]
            broken = []
            for raw in LINK.findall(content):
                target = raw.rsplit(">>", 1)[-1].strip().split("#", 1)[0]
                if not target or target.startswith(("http:", "https:", "mailto:")):
                    continue
                normalized = target.replace("/", ".").strip(".")
                if "." in normalized and normalized not in known:
                    broken.append(target)
            if missing or broken:
                issues.append({"page": meta["fullName"], "missingHeadings": missing,
                               "unresolvedLinks": sorted(set(broken))})
        return compact_json({"space": space, "pagesScanned": len(pages), "scanTruncated": len(pages) == scan_limit,
                             "issues": issues[:issue_limit], "issueCount": len(issues),
                             "issuesTruncated": len(issues) > issue_limit})

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False))
    def create_page_from_template(space: str, page: str, template: str, title: str,
                                  fields: dict[str, str] | None = None,
                                  include_raw: bool = False) -> str:
        """Create a meeting, decision, task, or report page using supplied field values."""
        if template not in TEMPLATES:
            raise ValueError("template must be meeting, decision, task, or report.")
        values = {key: "" for key in {part.split("}")[0] for part in TEMPLATES[template].split("{")[1:]}}
        values.update(fields or {})
        values["title"] = title
        try:
            content = TEMPLATES[template].format_map(values)
        except KeyError as exc:
            raise ValueError(f"Missing template field: {exc.args[0]}") from None
        response, _ = request("PUT", page_url(space, page), xml_page(content, title, "xwiki/2.1"), "application/xml")
        return compact_json({"ok": True, "action": "created", "template": template,
                             "page": f"{space}.{page}",
                             **({"response": response.decode("utf-8", errors="replace")}
                                if include_raw and response else {})})

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))
    def decision_log(space: str, scan_limit: int = 100, start: int = 0, limit: int = 50,
                     include_full_lines: bool = False) -> str:
        """Find decisions with source pages; paginate matches with start/limit."""
        if not 1 <= scan_limit <= 250:
            raise ValueError("scan_limit must be between 1 and 250.")
        if not isinstance(start, int) or isinstance(start, bool) or start < 0:
            raise ValueError("start must be a non-negative integer.")
        if not 1 <= limit <= 250:
            raise ValueError("limit must be between 1 and 250.")
        pages = all_pages(space, max_pages=scan_limit)
        matches = []
        for item in pages:
            meta = page_fields(item)
            try:
                body = get_page(meta["space"], meta["pageName"])
            except RuntimeError:
                continue
            lines = [line.strip() for line in value_text(body, "content").splitlines()
                     if line.strip() and DECISION.search(line)]
            if not include_full_lines:
                lines = [line[:500] for line in lines]
            if lines:
                matches.append({"page": meta["fullName"], "title": meta["title"], "statements": lines[:20]})
        selected = matches[start:start + limit]
        next_start = start + len(selected) if start + len(selected) < len(matches) else None
        return compact_json({"space": space, "pagesScanned": len(pages), "scanTruncated": len(pages) == scan_limit,
                             "decisions": selected, "decisionCount": len(matches),
                             "truncated": next_start is not None, "next_start": next_start})

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))
    def project_status(space: str, scan_limit: int = 100, task_start: int = 0,
                       task_limit: int = 100) -> str:
        """Collect checkbox tasks and owners; paginate the task list with task_start/task_limit."""
        if not 1 <= scan_limit <= 250:
            raise ValueError("scan_limit must be between 1 and 250.")
        if not isinstance(task_start, int) or isinstance(task_start, bool) or task_start < 0:
            raise ValueError("task_start must be a non-negative integer.")
        if not 1 <= task_limit <= 5000:
            raise ValueError("task_limit must be between 1 and 5000.")
        pages = all_pages(space, max_pages=scan_limit)
        tasks = []
        errors = []
        for item in pages:
            meta = page_fields(item)
            try:
                body = get_page(meta["space"], meta["pageName"])
            except RuntimeError as exc:
                errors.append({"page": meta["fullName"], "error": str(exc)})
                continue
            lines = value_text(body, "content").splitlines()
            owner = next((match.group(1).strip() for line in lines if (match := OWNER.search(line))), "")
            for line in lines:
                match = TASK.match(line)
                if match:
                    tasks.append({"page": meta["fullName"], "task": match.group(2).strip(),
                                  "complete": match.group(1).lower() == "x", "owner": owner})
        selected = tasks[task_start:task_start + task_limit]
        next_task_start = task_start + len(selected) if task_start + len(selected) < len(tasks) else None
        return compact_json({"space": space, "pagesScanned": len(pages), "scanTruncated": len(pages) == scan_limit,
                           "readErrors": errors,
                           "total": len(tasks), "completed": sum(task["complete"] for task in tasks),
                           "tasks": selected, "tasksTruncated": next_task_start is not None,
                           "next_task_start": next_task_start})

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))
    def wiki_digest(days: int = 14, limit: int = 30, include_metadata: bool = False) -> str:
        """List recent page changes; include_metadata adds creator, version, and space details."""
        if not 1 <= days <= 3650 or not 1 <= limit <= 100:
            raise ValueError("days must be 1–3650 and limit must be 1–100.")
        pages = [page_fields(item) for item in all_pages(max_pages=500)]
        from datetime import datetime, timedelta, timezone
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        selected = []
        for page in pages:
            try:
                modified = datetime.fromisoformat(page["modified"].replace("Z", "+00:00"))
            except (ValueError, TypeError):
                continue
            if modified >= cutoff:
                selected.append(page)
        selected.sort(key=lambda row: row["modified"], reverse=True)
        if not include_metadata:
            selected = [{key: page[key] for key in ("fullName", "title", "author", "modified") if page.get(key)}
                        for page in selected]
        return compact_json({"wiki": config.current().wiki, "days": days, "changes": selected[:limit],
                             "truncated": len(selected) > limit})
