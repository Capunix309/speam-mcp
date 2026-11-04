"""Expose startup authentication health and recovery guidance to the model."""

from __future__ import annotations

import json

from mcp.types import ToolAnnotations

from . import auth_state


def register(server) -> None:
    """Register a read-only tool that reports service authentication state."""

    @server.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))
    def get_auth_status() -> str:
        """Report startup authentication results. If any service is AUTH_FAILURE,
        tell the user which service failed and ask them to correct its credentials
        or authorization. Do not restart the MCP server or its Codex/Claude app
        until credentials are corrected; repeated startup attempts can lock the
        account. The failed service remains blocked until the next server start.
        """
        return json.dumps({
            "integrations": {
                name: {"state": value.state, "diagnostic": value.diagnostic}
                for name, value in auth_state.all_statuses().items()
            },
            "assistant_instruction": (
                "Report any AUTH_FAILURE to the user, ask them to correct credentials, "
                "and do not restart the MCP server or Codex/Claude app until correction. "
                "The service remains blocked until a later server start."
            ),
        }, ensure_ascii=False, indent=2)
