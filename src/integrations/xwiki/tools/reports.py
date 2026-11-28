from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from mcp.types import ToolAnnotations
from ..core import config
from ..core.client import all_pages, normalize_space_path, page_fields
from ..core.client import get, records
from src.shared.tool_output import compact_json


def _date_range_bounds(start_date: str, end_date: str, timezone_name: str) -> tuple[int, int]:
    """Convert inclusive ISO calendar dates to XWiki's millisecond time bounds."""
    try:
        if len(start_date) != 10 or len(end_date) != 10:
            raise ValueError
        first = date.fromisoformat(start_date)
        last = date.fromisoformat(end_date)
    except (TypeError, ValueError):
        raise ValueError("start_date and end_date must use YYYY-MM-DD format.") from None
    if first > last:
        raise ValueError("start_date must be on or before end_date.")
    try:
        zone = ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, TypeError):
        raise ValueError("timezone_name must be a valid IANA timezone.") from None

    start = datetime.combine(first, time.min, tzinfo=zone)
    try:
        day_after_last = last + timedelta(days=1)
    except OverflowError:
        raise ValueError("end_date is outside the supported calendar range.") from None
    end_exclusive = datetime.combine(day_after_last, time.min, tzinfo=zone)
    return int(start.timestamp() * 1000), int(end_exclusive.timestamp() * 1000)


def _modified_millis(value: object, timezone_name: str) -> int | None:
    """Read XWiki's millisecond timestamps or ISO timestamps safely."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return int(value)
    if isinstance(value, str):
        if value.isdigit():
            return int(value)
        try:
            modified = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if modified.tzinfo is None:
            modified = modified.replace(tzinfo=ZoneInfo(timezone_name))
        return int(modified.timestamp() * 1000)
    return None


def _change_fields(item: dict) -> dict:
    """Return only the page-change metadata needed to discover and diff pages."""
    raw_space = item.get("space", "")
    space = normalize_space_path(str(raw_space)) if raw_space else ""
    return {
        "pageId": item.get("pageId") or item.get("fullName") or item.get("pageFullName", ""),
        "space": space,
        "page": item.get("name") or item.get("pageName", ""),
        "version": item.get("version", ""),
        "author": item.get("modifier") or item.get("author", ""),
        "modified": item.get("modified", ""),
        "summary": item.get("comment", ""),
    }


def register(mcp):
    """Register this category of XWiki tools."""
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))
    def recent_changes(days: int = 30, limit: int = 50, include_raw: bool = False) -> str:
        """List recent page-change summaries; include_raw returns the complete REST records."""
        if not 1 <= days <= 3650 or not 1 <= limit <= 100:
            raise ValueError("days must be 1–3650 and limit must be 1–100.")
        timestamp = int((datetime.now(timezone.utc).timestamp() - days * 86400) * 1000)
        data = get("modifications", [("date", str(timestamp)), ("start", "0"), ("number", str(limit))])
        changes = records(data, "modification") or records(data, "modifications") or []
        if include_raw:
            changes = data
        else:
            changes = [_change_fields(item) for item in changes]
        return compact_json({"wiki": config.current().wiki, "days": days, "changes": changes})

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))
    def changes_between(
        start_date: str,
        end_date: str,
        timezone_name: str = "UTC",
        start: int = 0,
        limit: int = 99,
    ) -> str:
        """List XWiki page versions changed during an inclusive date window.

        Dates use YYYY-MM-DD in timezone_name. Use start and next_start to
        continue a truncated result; changes are read from the selected wiki.
        """
        if not isinstance(start, int) or isinstance(start, bool) or start < 0:
            raise ValueError("start must be a non-negative integer.")
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 99:
            raise ValueError("limit must be between 1 and 99.")
        if start > 1_000_000:
            raise ValueError("start must not exceed 1000000.")
        start_ms, end_exclusive_ms = _date_range_bounds(start_date, end_date, timezone_name)
        requested = limit + 1
        data = get("modifications", [
            ("date", str(start_ms)),
            ("start", str(start)),
            ("number", str(requested)),
        ])
        fetched_items = (
            records(data, "historySummaries")
            or records(data, "modification")
            or records(data, "modifications")
        )
        items = fetched_items[:limit]
        changes = []
        unparsed_timestamps = 0
        for item in items:
            modified_ms = _modified_millis(item.get("modified"), timezone_name)
            if modified_ms is None:
                unparsed_timestamps += 1
            elif start_ms <= modified_ms < end_exclusive_ms:
                changes.append(_change_fields(item))

        truncated = len(fetched_items) > limit
        next_start = start + len(items) if truncated else None
        unique_pages = {}
        for change in changes:
            page_key = change["pageId"] or f'{change["space"]}.{change["page"]}'
            page = unique_pages.setdefault(page_key, {
                "pageId": change["pageId"],
                "space": change["space"],
                "page": change["page"],
                "changeCount": 0,
            })
            page["changeCount"] += 1

        return compact_json({
            "wiki": config.current().wiki,
            "startDate": start_date,
            "endDate": end_date,
            "timezone": timezone_name,
            "pages": list(unique_pages.values()),
            "pageCount": len(unique_pages),
            "changes": changes,
            "changeCount": len(changes),
            "unparsedTimestampCount": unparsed_timestamps,
            "warnings": ([f"Skipped {unparsed_timestamps} change records without a parseable modified timestamp."]
                         if unparsed_timestamps else []),
            "truncated": truncated,
            "next_start": next_start,
        }, ensure_ascii=False, indent=2)

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))
    def who_wrote_pages(space: str | None = None, author: str | None = None,
                        limit: int = 100, include_raw: bool = False) -> str:
        """List page authorship summaries; include_raw returns all normalized metadata."""
        if not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500.")
        raw_pages = all_pages(space, author, max_pages=limit)
        pages = raw_pages if include_raw else [page_fields(item) for item in raw_pages]
        if not include_raw:
            pages = [{key: page[key] for key in ("fullName", "title", "space", "pageName", "author", "lastEditor", "modified")
                      if page.get(key)} for page in pages]
        return compact_json({"wiki": config.current().wiki, "pages": pages, "count": len(pages),
                           "truncated": len(pages) == limit}, ensure_ascii=False, indent=2)
