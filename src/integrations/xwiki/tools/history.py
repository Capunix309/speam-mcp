import difflib

from mcp.types import ToolAnnotations
from ..core.client import get_page, records, value_text
from src.shared.tool_output import compact_json


def register(mcp):
    """Register this category of XWiki tools."""
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))
    def diff_page_versions(space: str, page: str, old_version: str, new_version: str,
                           start: int = 0, max_chars: int = 12000) -> str:
        """Return a unified diff in character pages; use next_start for long diffs."""
        if not isinstance(start, int) or isinstance(start, bool) or start < 0:
            raise ValueError("start must be a non-negative character offset.")
        if not isinstance(max_chars, int) or isinstance(max_chars, bool) or not 1 <= max_chars <= 50000:
            raise ValueError("max_chars must be between 1 and 50000.")
        old = get_page(space, page, f"history/{old_version}")
        new = get_page(space, page, f"history/{new_version}")
        diff = "".join(difflib.unified_diff(
            value_text(old, "content").splitlines(keepends=True),
            value_text(new, "content").splitlines(keepends=True),
            fromfile=old_version, tofile=new_version,
        ))
        end = min(len(diff), start + max_chars)
        return compact_json({"page": f"{space}.{page}", "oldVersion": old_version,
                             "newVersion": new_version, "diff": diff[start:end], "totalChars": len(diff),
                             "truncated": end < len(diff), "next_start": end if end < len(diff) else None})

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))
    def page_history(space: str, page: str, limit: int = 30, include_raw: bool = False) -> str:
        """List concise version records; include_raw returns complete XWiki records."""
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100.")
        data = get_page(space, page, "history", [("start", "0"), ("number", str(limit))])
        versions = records(data, "version") or records(data, "versions") or []
        if include_raw:
            versions = data
        else:
            fields = ("version", "number", "author", "date", "modified", "comment", "minorEdit")
            versions = [{key: item[key] for key in fields if item.get(key) is not None} for item in versions]
        return compact_json({"page": f"{space}.{page}", "history": versions})
