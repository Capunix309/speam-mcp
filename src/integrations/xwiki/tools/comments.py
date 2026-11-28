import xml.etree.ElementTree as ET

from mcp.types import ToolAnnotations
from ..core.client import get_page, page_url, records, request
from src.shared.tool_output import compact_json


def register(mcp):
    """Register this category of XWiki tools."""
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False))
    def add_comment(space: str, page: str, text: str, include_raw: bool = False) -> str:
        """Post a comment on a page."""
        root = ET.Element("comment", xmlns="http://www.xwiki.org")
        ET.SubElement(root, "text").text = text
        response, _ = request("POST", page_url(space, page, "comments"),
                              ET.tostring(root, encoding="utf-8", xml_declaration=True), "application/xml")
        return compact_json({"ok": True, "page": f"{space}.{page}",
                             **({"response": response.decode("utf-8", errors="replace")} if include_raw and response else {})})

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))
    def list_comments(space: str, page: str, limit: int = 50, include_raw: bool = False) -> str:
        """List concise comment records; include_raw returns the complete records."""
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100.")
        data = get_page(space, page, "comments", [("start", "0"), ("number", str(limit))])
        comments = records(data, "comment") or records(data, "comments") or []
        if include_raw:
            comments = data
        else:
            fields = ("id", "author", "date", "highlight", "replyTo", "text")
            comments = [{key: item[key] for key in fields if item.get(key) is not None} for item in comments]
        return compact_json({"page": f"{space}.{page}", "comments": comments})
