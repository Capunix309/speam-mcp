"""Compact JSON serialization for MCP tool results."""

from __future__ import annotations

import json
from typing import Any


def compact_json(value: Any, **_options: Any) -> str:
    """Serialize a tool result without pretty-print whitespace."""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
