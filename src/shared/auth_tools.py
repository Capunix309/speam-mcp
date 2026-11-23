"""Expose startup authentication health and recovery guidance to the model."""

from __future__ import annotations

import json

from mcp.types import ToolAnnotations

from . import auth_state


def register(server) -> None:
    """Register a read-only tool that reports service authentication state."""

    @server.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))
    def get_auth_status() -> str:
        """Report each startup check and a safe, cause-specific failure diagnosis.

        Do not assume every AUTH_FAILURE means invalid credentials. Use the check
        and diagnostic to distinguish rejected authentication, denied access,
        missing resources, configuration errors, and connectivity failures.
        While a check is in progress, wait before retrying that integration's
        tools. If a check fails, report its diagnostic to the user and recommend
        fixing the cause before restarting Codex, Claude, or the MCP client.
        """
        return json.dumps({
            "integrations": {
                name: {
                    "state": value.state,
                    "check": value.check,
                    "diagnostic": value.diagnostic,
                }
                for name, value in auth_state.all_statuses().items()
            },
            "assistant_instruction": (
                "For CHECKING integrations, tell the user the check is still running and wait before "
                "calling those tools again. For AUTH_FAILURE, report the diagnostic and do not assume "
                "credentials are wrong: follow the reported cause and recommend correcting that setting, "
                "access, endpoint, or network issue as appropriate. The failed integration remains blocked "
                "until the cause is fixed and the MCP server starts again. Do not restart Codex, Claude, "
                "or the MCP client before the user fixes the cause, to avoid repeated authentication attempts."
            ),
        }, ensure_ascii=False, indent=2)
