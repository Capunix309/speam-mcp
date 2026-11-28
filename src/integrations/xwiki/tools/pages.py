import re

from mcp.types import ToolAnnotations
from ..core.client import get_page, normalize_space_path, page_content_result, page_url, request, value_text, xml_page
from src.shared.tool_output import compact_json


def register(mcp):
    """Register this category of XWiki tools."""
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False))
    def append_section(space: str, page: str, heading: str, content: str,
                       include_raw: bool = False) -> str:
        """Append a level-two XWiki section to a page."""
        current = get_page(space, page)
        old = value_text(current, "content")
        title = value_text(current, "title") or None
        syntax = value_text(current, "syntax") or "xwiki/2.1"
        addition = f"\n\n== {heading.strip()} ==\n{content.strip()}"
        payload, _ = request("PUT", page_url(space, page), xml_page(old.rstrip() + addition, title, syntax), "application/xml")
        return compact_json({"ok": True, "page": f"{space}.{page}", "section": heading.strip(),
                             **({"response": payload.decode("utf-8", errors="replace")} if include_raw and payload else {})})

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False))
    def create_page(space: str, page: str, content: str, title: str | None = None,
                    syntax: str = "xwiki/2.1", include_raw: bool = False) -> str:
        """Create a page with XWiki syntax content."""
        payload, _ = request("PUT", page_url(space, page), xml_page(content, title, syntax), "application/xml")
        return compact_json({"ok": True, "action": "created", "page": f"{space}.{page}",
                             **({"response": payload.decode("utf-8", errors="replace")} if include_raw and payload else {})})

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False))
    def edit_page(space: str, page: str, content: str, title: str | None = None,
                  syntax: str | None = None, include_raw: bool = False) -> str:
        """Replace a page's content and optionally update its title or syntax."""
        payload, _ = request("PUT", page_url(space, page), xml_page(content, title, syntax), "application/xml")
        return compact_json({"ok": True, "action": "updated", "page": f"{space}.{page}",
                             **({"response": payload.decode("utf-8", errors="replace")} if include_raw and payload else {})})

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False))
    def edit_page_section(space: str, page: str, heading: str, replacement: str,
                          include_raw: bool = False) -> str:
        """Replace a section's body, leaving its heading and sibling sections in place."""
        current = get_page(space, page)
        lines = value_text(current, "content").splitlines()
        start = next((i for i, line in enumerate(lines)
                      if (m := re.match(r"^(={1,6})\s+(.+?)\s*=*\s*$", line))
                      and m.group(2).strip().casefold() == heading.strip().casefold()), None)
        if start is None:
            raise ValueError(f"Heading not found: {heading}")
        level = len(re.match(r"^(={1,6})\s+", lines[start]).group(1))
        end = next((i for i in range(start + 1, len(lines))
                    if (m := re.match(r"^(={1,6})\s+", lines[i])) and len(m.group(1)) <= level), len(lines))
        updated = lines[:start + 1] + replacement.splitlines() + lines[end:]
        payload, _ = request("PUT", page_url(space, page),
                             xml_page("\n".join(updated), value_text(current, "title") or None,
                                      value_text(current, "syntax") or "xwiki/2.1"), "application/xml")
        return compact_json({"ok": True, "page": f"{space}.{page}", "section": heading.strip(),
                             **({"response": payload.decode("utf-8", errors="replace")} if include_raw and payload else {})})

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))
    def read_page(space: str, page: str, include_metadata: bool = False,
                  include_objects: bool = False, include_raw: bool = False,
                  start: int = 0, max_chars: int = 12000) -> str:
        """Read page content; optionally include metadata, objects, or the complete REST response.

        Content is returned in character pages. Use start with next_start to
        continue; include_raw returns the untrimmed XWiki object.
        """
        _validate_page_window(start, max_chars)
        data = get_page(space, page)
        result = page_content_result(data, space, page, include_metadata, include_objects, include_raw)
        if not include_raw:
            result.update(_text_window(result.get("content", ""), start, max_chars))
        return compact_json(result)

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))
    def read_page_section(space: str, page: str, heading: str, start: int = 0,
                          max_chars: int = 12000) -> str:
        """Read the content under a matching XWiki heading until the next heading of the same or higher level."""
        _validate_page_window(start, max_chars)
        data = get_page(space, page)
        content = value_text(data, "content")
        lines = content.splitlines()
        for index, line in enumerate(lines):
            match = re.match(r"^(={1,6})\s+(.+?)\s*=*\s*$", line)
            if match and match.group(2).strip().casefold() == heading.strip().casefold():
                end = len(lines)
                for pos in range(index + 1, len(lines)):
                    next_heading = re.match(r"^(={1,6})\s+", lines[pos])
                    if next_heading and len(next_heading.group(1)) <= len(match.group(1)):
                        end = pos
                        break
                content = "\n".join(lines[index:end])
                return compact_json({"page": f"{space}.{page}", "heading": heading,
                                     **_text_window(content, start, max_chars)})
        raise ValueError(f"Heading not found: {heading}")


def _validate_page_window(start: int, max_chars: int) -> None:
    if not isinstance(start, int) or isinstance(start, bool) or start < 0:
        raise ValueError("start must be a non-negative character offset.")
    if not isinstance(max_chars, int) or isinstance(max_chars, bool) or not 1 <= max_chars <= 50000:
        raise ValueError("max_chars must be between 1 and 50000.")


def _text_window(content: str, start: int, max_chars: int) -> dict:
    end = min(len(content), start + max_chars)
    return {"content": content[start:end], "totalChars": len(content),
            "truncated": end < len(content), "next_start": end if end < len(content) else None}
