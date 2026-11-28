import base64
from mcp.types import ToolAnnotations
from ..core.client import get_page, page_url, records, request
from src.shared.tool_output import compact_json


def register(mcp):
    """Register this category of XWiki tools."""
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))
    def list_attachments(space: str, page: str, start: int = 0, limit: int = 30,
                         include_raw: bool = False) -> str:
        """List attachment summaries; paginate with start/limit or request complete records."""
        if not isinstance(start, int) or isinstance(start, bool) or start < 0:
            raise ValueError("start must be a non-negative integer.")
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100.")
        data = get_page(space, page, "attachments", [("start", str(start)), ("number", str(limit + 1))])
        items = records(data, "attachment") or records(data, "attachments") or []
        selected = items[:limit]
        if include_raw:
            return compact_json({"page": f"{space}.{page}", "attachments": data,
                                 "truncated": len(items) > limit,
                                 "next_start": start + len(selected) if len(items) > limit else None})
        fields = ("id", "name", "filename", "mimeType", "size", "author", "date", "version", "downloadUrl")
        attachments = [{key: item[key] for key in fields if item.get(key) is not None} for item in selected]
        return compact_json({"page": f"{space}.{page}", "attachments": attachments,
                             "truncated": len(items) > limit,
                             "next_start": start + len(selected) if len(items) > limit else None})

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))
    def read_attachment(space: str, page: str, attachment: str, max_bytes: int = 1_000_000,
                        start: int = 0, max_chars: int = 12000,
                        include_base64: bool = False) -> str:
        """Read a text attachment in character pages; binary data requires include_base64=true."""
        if not 1 <= max_bytes <= 5_000_000:
            raise ValueError("max_bytes must be between 1 and 5000000.")
        if not isinstance(start, int) or isinstance(start, bool) or start < 0:
            raise ValueError("start must be a non-negative character offset.")
        if not isinstance(max_chars, int) or isinstance(max_chars, bool) or not 1 <= max_chars <= 50000:
            raise ValueError("max_chars must be between 1 and 50000.")
        payload, content_type = request("GET", page_url(space, page, f"attachments/{attachment}"))
        if len(payload) > max_bytes:
            raise ValueError(f"Attachment is {len(payload)} bytes, above max_bytes={max_bytes}.")
        media = content_type.split(";", 1)[0].lower()
        if media.startswith("text/") or media in {"application/json", "application/xml", "application/javascript"}:
            text = payload.decode("utf-8", errors="replace")
            end = min(len(text), start + max_chars)
            return compact_json({"contentType": media, "text": text[start:end], "totalChars": len(text),
                                 "truncated": end < len(text), "next_start": end if end < len(text) else None})
        result = {"contentType": media, "size": len(payload)}
        if include_base64:
            result["base64"] = base64.b64encode(payload).decode("ascii")
        else:
            result["dataOmitted"] = "Set include_base64=true to return binary data."
        return compact_json(result)
