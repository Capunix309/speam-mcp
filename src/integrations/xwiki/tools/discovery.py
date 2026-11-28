import re
import urllib.parse

from mcp.types import ToolAnnotations
from ..core import config
from ..core.client import all_pages, get, get_page, normalize_space_path, page_fields, records, value_text
from src.shared.tool_output import compact_json

LINK = re.compile(r"\[\[(.*?)\]\]")


def register(mcp):
    """Register this category of XWiki tools."""
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))
    def find_orphan_pages(space: str | None = None, scan_limit: int = 100,
                          include_metadata: bool = False) -> str:
        """Find pages with no incoming XWiki syntax links among the scanned pages."""
        if not 1 <= scan_limit <= 250:
            raise ValueError("scan_limit must be between 1 and 250.")
        pages = all_pages(space=space, max_pages=scan_limit)
        targets: set[str] = set()
        for item in pages:
            fields = page_fields(item)
            full_name = fields["fullName"]
            if not full_name:
                continue
            page_space = fields["space"]
            page_name = fields["pageName"]
            try:
                body = get_page(page_space, page_name)
            except RuntimeError:
                continue
            for link in LINK.findall(value_text(body, "content")):
                target = link.rsplit(">>", 1)[-1].split("%", 1)[0].strip()
                if target:
                    targets.add(target.replace("/", "."))
        orphans = [page_fields(item) if include_metadata else _page_identity(item) for item in pages
                   if page_fields(item)["fullName"].split(":")[-1] not in targets]
        return compact_json({"scanned": len(pages), "truncated": len(pages) == scan_limit,
                           "orphans": orphans}, ensure_ascii=False, indent=2)

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))
    def get_page_links(space: str, page: str) -> str:
        """List page links found in XWiki syntax on a page."""
        data = get_page(space, page)
        content = value_text(data, "content")
        links = sorted({match.rsplit(">>", 1)[-1].strip() for match in LINK.findall(content) if match.strip()})
        return compact_json({"page": f"{space}.{page}", "links": links}, ensure_ascii=False, indent=2)

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))
    def list_spaces(start: int = 0, limit: int = 100, include_raw: bool = False) -> str:
        """List XWiki spaces; use start/limit for pagination or include_raw for full records."""
        if not isinstance(start, int) or isinstance(start, bool) or start < 0:
            raise ValueError("start must be a non-negative integer.")
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500.")
        data = get("spaces", [("start", str(start)), ("number", str(limit + 1))])
        spaces = records(data, "spaces") or records(data, "space")
        selected = spaces[:limit]
        if include_raw:
            return compact_json({"count": len(selected), "spaces": selected,
                                 "truncated": len(spaces) > limit,
                                 "next_start": start + len(selected) if len(spaces) > limit else None})
        result = [{"name": value_text(row, "name", "id"), "wiki": value_text(row, "wiki"),
                   "home": value_text(row, "home")} for row in selected]
        result.sort(key=lambda row: row["name"].casefold())
        return compact_json({"count": len(result), "spaces": result,
                             "truncated": len(spaces) > limit,
                             "next_start": start + len(selected) if len(spaces) > limit else None})

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))
    def page_tree(space: str | None = None, author: str | None = None,
                  limit: int = 100, include_raw: bool = False) -> str:
        """List pages with creator, last editor, modified date, and version; optionally filter by space or author."""
        if not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500.")
        raw_pages = all_pages(space, author, max_pages=limit)
        pages = raw_pages if include_raw else [page_fields(page) for page in raw_pages]
        if not include_raw:
            pages = [{key: value for key, value in page.items() if value}
                     for page in pages]
        pages.sort(key=lambda row: (row["space"].casefold(), row["pageName"].casefold()))
        return compact_json({"wiki": config.current().wiki, "count": len(pages), "pages": pages,
                           "truncated": len(pages) == limit}, ensure_ascii=False, indent=2)

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))
    def search_pages(query: str, limit: int = 20, start: int = 0,
                     scopes: list[str] | None = None, space: str | None = None,
                     include_raw: bool = False) -> str:
        """Search pages, optionally limited to a space; use start and limit to paginate."""
        if not 1 <= limit <= 50 or start < 0:
            raise ValueError("limit must be 1–50 and start must be zero or greater.")
        selected = scopes or ["name", "title", "content"]
        if not set(selected) <= {"name", "title", "content", "objects"}:
            raise ValueError("scopes may contain name, title, content, or objects.")
        params = [("q", query), ("number", str(limit)), ("start", str(start))]
        params.extend(("scope", scope) for scope in selected)
        resource = (f"spaces/{'/spaces/'.join(urllib.parse.quote(p, safe='') for p in normalize_space_path(space).split('/'))}/search"
                    if space else "search")
        results = get(resource, params)
        if include_raw:
            return compact_json({"wiki": config.current().wiki, "results": results})
        items = (records(results, "searchResults") or records(results, "results")
                 if isinstance(results, dict) else records(results, "searchResults"))
        summaries = [_search_result(item) for item in items]
        return compact_json({"wiki": config.current().wiki, "results": summaries,
                             "count": len(summaries), "start": start, "limit": limit})


def _page_identity(item):
    """Return only the identity needed to locate an orphaned page."""
    page = page_fields(item)
    return {key: page[key] for key in ("fullName", "title", "space", "pageName") if page.get(key)}


def _search_result(item):
    """Project XWiki search hits to a locator, score, and short content excerpt."""
    nested = item.get("pageSummary", item)
    page = page_fields(nested) if isinstance(nested, dict) else {}
    result = {key: page[key] for key in ("fullName", "title", "space", "pageName", "modified", "version")
              if page.get(key)}
    for key in ("score", "url", "type"):
        if item.get(key) is not None:
            result[key] = item[key]
    excerpt = next((item.get(key) for key in ("excerpt", "highlight", "renderedContent", "content", "text")
                    if isinstance(item.get(key), str) and item[key]), None)
    if excerpt:
        result["excerpt"] = excerpt[:500]
        if len(excerpt) > 500:
            result["excerptTruncated"] = True
    return result
