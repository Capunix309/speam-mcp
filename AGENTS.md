# Agent Instructions — MCP-tools

## Project Context
This repository runs a Python stdio MCP server (`src/server.py`) with Jira, XWiki, and Jira-to-Google-Sheets sprint automation integrations. Service clients and configuration live under integration `core/` modules, exposed tools under `tools/`, shared authentication and policy under `src/shared/`, and tests under `tests/`. Read `README.md` for the supported configuration and tool contracts.

## Rule 01 — Trace registration, policy, and implementation
Before changing a tool, inspect its registration path, handler, underlying client, shared authorization checks, and existing tests. Determine whether the tool is a read, write, or destructive write and which configured wiki/project it targets. Avoid adding an isolated handler that bypasses established registries or policy gates. Keep changes narrow enough to audit.

## Rule 02 — Separate MCP contracts from service clients
Keep tool schemas, argument validation, and MCP-facing responses in the tool layer; keep HTTP/API communication and reusable service logic in `core/`. Use shared helpers for configuration, normalization, authentication, and error handling rather than duplicating them. Return bounded, understandable errors without leaking tokens, headers, or internal service responses containing sensitive data.

## Rule 03 — Enforce configured access boundaries
Every Jira operation must remain scoped to configured projects and every XWiki operation to configured wikis. Respect per-project/per-wiki `read_only` settings and disabled integrations, including when requests supply unexpected identifiers. Never add arbitrary HTTP passthroughs or broaden allowed destinations as a shortcut. Validate the target before any network write and test that forbidden targets fail safely.

## Rule 04 — Preserve write and destructive-tool safeguards
Keep the distinction between reads, writes, and destructive writes in tool metadata and visibility policy. Write tools are exposed according to `expose_write`; destructive tools require explicit `expose_destructive` in addition. Do not silently relax these defaults, approval hints, or authentication checks. For ambiguous external modifications, clarify the exact target and intended change before acting.

## Rule 05 — Protect credentials and authentication state
Use `config.example.toml` and documented environment-variable names for shareable setup; local `config.toml`, `.env`, and Google OAuth Keychain entries are private. Never print, commit, log, or paste secrets or tokens into client registration files. Authentication is checked at server startup; a failed integration remains blocked for that process. `get_auth_status` must report which check failed and a safe cause-specific diagnostic; do not label every failure as bad credentials. Never expose response bodies or secrets, and do not implement hidden retries or access bypasses.

## Rule 06 — Preserve Jira and XWiki provenance conventions
Jira-created issues carry the `ai-assisted` label and AI-generated issue descriptions, comments, and worklogs use the documented `[AI]` marker where applicable. Keep project-specific custom field IDs configurable rather than hardcoding them globally. XWiki page operations must preserve the selected wiki, page hierarchy, and existing content outside the requested edit. Treat page moves and broad replacements as high-impact writes.

## Rule 07 — Keep sprint-sheet synchronization repeatable
The `sync_sprint_sheet` automation reads Jira sprint issues and worklogs and updates an existing Google Sheet. Preserve the documented date-window semantics, roster and board configuration, and replacement of the selected sprint's Worklogs rows without duplicating rows on rerun. Do not accidentally erase other sprints or assume all worklogs belong to issues assigned to the selected sprint. Test repeated synchronization against mocked Jira and Sheets data.

## Rule 08 — Test both permissions and failure paths
For every new or changed tool, test valid input, invalid input, disabled integration, read-only denial, wrong project/wiki, and external API failures as applicable. Use mocks or controlled fixtures rather than modifying live Jira, XWiki, or Sheets data during automated tests. Run focused tests and then `python -m pytest -q` where feasible. Explicitly report untested live behavior.

## Rule 09 — Keep tools discoverable and documented
Update `README.md`, example configuration, tool descriptions, and tests whenever arguments, access modes, or behavior change. Use `mcp-development` for tool design, `testing-validation` for regression tests, `coding-practices` for structure, `technical-documentation` for user-facing instructions, and `git-workflow` for changes. Avoid duplicating generic skill instructions here.
