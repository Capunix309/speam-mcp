# MCP Tools

One stdio MCP server exposes the enabled XWiki and Jira integrations. Production code lives under `src/`; each integration has a `core/` directory for shared client/configuration logic and a `tools/` directory organized by responsibility. Tests live separately under `tests/`, one file per integration.

## 1. Configure the integrations

These settings belong to the current operating-system user, not to the project that uses the MCP or to Codex/Claude configuration. From the `MCP-tools/` folder, install dependencies and initialize the per-user configuration:

```sh
pip install -r requirements.txt
python -m src.setup
```

The command creates `config.toml` in the platform's standard per-user application config directory (Windows: `%APPDATA%\\Capunix\\mcp-tools`, macOS: `~/Library/Application Support/mcp-tools`, Linux: `$XDG_CONFIG_HOME/mcp-tools`, usually `~/.config/mcp-tools`). If it finds an old checkout-local `config.toml`, it moves it there once without overwriting an existing user config. The file contains the server host, enabled integrations, wiki and project access, and environment-variable names only. Never put credentials in Codex or Claude's MCP registration file.

### Add or configure XWiki wikis

Each `[[integrations.xwiki.wikis]]` entry represents one wiki. Keep `id` as a short, unique selector the model will pass to tools. Set `wiki` to the XWiki wiki identifier: it is the segment after `/xwiki/wiki/` in a wiki URL (for example, `example` in `/xwiki/wiki/example/view/...`). Set `read_only = true` unless that wiki is explicitly approved for writing. `default_wiki` must match one of the configured `id` values.

Add another wiki by copying this block into `config.toml` and replacing its values:

```toml
[[integrations.xwiki.wikis]]
id = "research"
wiki = "wiki-id-from-url"
read_only = true
```

Replace `wiki-id-from-url` with the segment after `/xwiki/wiki/` in that wiki's URL.

The example contains generic wiki entries to show the configuration format. Replace each wiki identifier and access mode with values for your environment. To disable XWiki, set `enabled = false` under `[integrations.xwiki]`.

### Add or configure Jira projects

Add one `[[integrations.jira.projects]]` block per project. `id` is a unique selector for tool calls. `key` is the Jira project key, usually the prefix of an issue key (`ABC` in `ABC-123`); you can also find it in the Jira project URL or project details. Set `read_only = true` to prevent all Jira changes in that project.

```toml
[[integrations.jira.projects]]
id = "primary"
key = "ABC"
read_only = true
epic_name_field = "customfield_12347"
story_points_field = "customfield_12345"
epic_link_field = "customfield_12346"
```

Replace `YOUR_PROJECT_KEY` in the supplied template with a configured project key. Add more blocks for other projects. Searches can cover all configured projects or select one by `id` or key. To disable Jira entirely, set `enabled = false` under `[integrations.jira]`.

Jira custom-field IDs belong on each `[[integrations.jira.projects]]` entry, because field IDs can differ between Jira projects. Configure `epic_name_field`, `story_points_field`, and `epic_link_field` using the IDs from that project's Jira instance. Find them in Jira field metadata or by inspecting an issue that already has each value. Automation uses the fields from the Jira project selected by `jira_project`.

### Credentials and tool visibility

Use the same `set`, `status`, and `remove` interface for all three integrations. Jira and XWiki prompt for a username and hidden password; Sheets starts the Google OAuth flow and optionally accepts the downloaded Desktop client JSON path:

```sh
python -m src.credentials set jira
python -m src.credentials set xwiki
python -m src.credentials set sheets /path/to/oauth-client.json
python -m src.credentials status sheets
python -m src.credentials status jira
python -m src.credentials remove sheets
```

Python `keyring` uses macOS Keychain, Windows Credential Manager, or Linux Secret Service/KWallet. File-based keyring backends are rejected. Explicit process environment variables still take precedence; saved keyring entries take precedence over a legacy `.env` file. `.env` remains supported for existing installations and automation, but should contain only configured credential variables.

The MCP server advertises its configured tools immediately and starts the enabled Jira, XWiki, and Google Sheets checks in the background, concurrently and once per process; the Sheets check verifies OAuth and access to the configured workbook. Until an integration check finishes successfully, calls to its tools return a waiting error; after a failure, they return the safe diagnostic and direct the assistant to `get_auth_status`. A failed check does not prevent server startup and only blocks that integration. Do not assume every failure means the credentials are wrong. Fix the reported cause before restarting Codex, Claude, or the MCP client to avoid repeated authentication attempts. The server does not retry failed checks automatically.

### Configure sprint-sheet automation

The `[integrations.automation]` table configures the sprint sync. It references a Jira project by its existing project `id`, so the Jira project key and access mode stay in one place:

```toml
[integrations.automation]
enabled = true
jira_project = "primary"
board_id = 1
spreadsheet_url = "https://docs.google.com/spreadsheets/d/REPLACE_WITH_SPREADSHEET_ID/edit"
timezone = "UTC"
team_members = ["Person One", "Person Two", "Person Three", "Person Four", "Person Five"]
```

Replace the Jira project selector, board ID, spreadsheet URL, roster, and timezone with values for your setup. Find a board ID in the Jira board URL or with `jira_list_boards`. The custom field IDs are configured on the selected Jira project above. The spreadsheet URL may be copied from the browser address bar. The configured roster should match the person names used in that workbook.

Dates are controlled by the caller for each sync. Pass optional `start_date` and `end_date` values in `YYYY-MM-DD` format when Jira's sprint dates do not match the reporting window. If omitted, the tool uses the sprint dates returned by Jira. If Jira does not provide a required date, pass it in the tool call.

#### Google Sheets authorization

To diagnose Python's read access to the native credential store without changing or displaying stored values, run:

```sh
.venv/bin/python -m src.integrations.automation.core.sheets.authorize --check-credential-store
```

The command reports whether credential-store reads work and whether the OAuth client and token entries exist. It does not test writes. Authorization errors distinguish credential-store access, Google OAuth setup, sign-in/token exchange, TLS connection failures, and saving the token; they never include credential values.

To test HTTPS to Google's OAuth endpoint without opening a sign-in flow or sending credentials, run:

```sh
.venv/bin/python -m src.integrations.automation.core.sheets.authorize --check-google-tls
```

Create a Google Cloud project, enable the Google Sheets API, and create an OAuth client with application type **Desktop app**. Download its JSON, then pass its path to the shared credential command:

```sh
.venv/bin/python -m src.credentials set sheets "/path/to/oauth-client.json"
```

`python -m src.credentials set sheets /path/to/oauth-client.json` opens Google sign-in, stores both the OAuth client settings and refreshable token in the native credential store, then removes the imported JSON file from its original location. After the first import, the path can be omitted when reauthorizing:

```sh
.venv/bin/python -m src.credentials set sheets
```

The command never prints credential contents and does not create token files. To remove stored Sheets credentials, run `python -m src.credentials remove sheets`; you can also revoke the app from your Google Account's third-party connections. If authorization expires or is revoked, run `python -m src.credentials set sheets` again.

The automation only registers when `enabled = true`. It requires Jira to be enabled, the configured project to exist, and Google OAuth to be completed before a sync call can write the workbook.

Write tools are visible by default. Set `[tools].expose_write = false` to hide them. Destructive tools are hidden by default; set `[tools].expose_destructive = true` to expose them. A destructive write tool appears only when both settings allow it. Restart the MCP client after changing the server configuration.

## 2. Install the MCP in a project

Install the MCP server once, then register it only in each project where you want it available. The project gets a small client configuration file; the MCP's own `config.toml` and credentials remain in the per-user config directory and native credential manager.

From the MCP-tools repository root, install its dependencies:

```sh
python3.13 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

In each project root, add the relevant client file:

```text
my-project/
├── .codex/
│   └── config.toml   # Codex project registration
└── .mcp.json         # Claude Code project registration (if used)
```

Replace `/absolute/path/to/MCP-tools` below with the full path to the MCP-tools checkout on your machine.

### Codex

Create `my-project/.codex/config.toml`:

```toml
[mcp_servers.mcp-tools]
command = "/absolute/path/to/MCP-tools/.venv/bin/python"
args = ["-m", "src.server"]
cwd = "/absolute/path/to/MCP-tools"
default_tools_approval_mode = "writes"
```

Codex loads project `.codex/config.toml` for trusted projects. Trust the project when prompted. The `writes` approval mode uses each tool's `readOnlyHint`: reads run without a prompt and writes request approval. Codex starts the server automatically; no separate server terminal is needed. See the [Codex MCP configuration guide](https://learn.chatgpt.com/docs/extend/mcp).

### Claude Code

Create `my-project/.mcp.json` (replace both occurrences of the path with your MCP-tools checkout):

```json
{
  "mcpServers": {
    "mcp-tools": {
      "command": "/absolute/path/to/MCP-tools/.venv/bin/python",
      "args": ["-m", "src.server"],
      "env": {
        "PYTHONPATH": "/absolute/path/to/MCP-tools"
      }
    }
  }
}
```

Claude Code starts project `.mcp.json` servers from the project directory; `PYTHONPATH` points Python to the MCP-tools checkout. Open the project in Claude Code and approve the project-scoped server when prompted. Run `/mcp` or `claude mcp list` to check its connection. See the [Claude Code MCP guide](https://docs.anthropic.com/en/docs/claude-code/mcp).

To run the server manually for debugging only, open a terminal in the MCP-tools repository and run `python -m src.server`.

## Jira tools

- `get_auth_status` (read) reports the startup check performed for each enabled integration and a safe, cause-specific diagnostic. The XWiki check reads the standard `Main.WebHome` page through the legacy page REST API for compatibility with XWiki 15.10.16. Status distinguishes HTTP 401 (authentication or resource access), denied access (403), missing endpoints/resources (404), other HTTP errors, missing credentials, and common network failures. It never returns response bodies or credential values. Tell the user what the diagnostic indicates rather than assuming every failure is an invalid credential. The failed integration remains blocked until its cause is fixed and the MCP server starts again.

- `jira_search` (read) searches configured projects by text, issue type, status, assignee, sprint, or update date. Omit `project` to search all configured projects.
- `jira_get_issue` (read) returns issue details, optionally including comments, worklogs, change history, or an epic's child issues.
- `jira_list_boards` (read) lists boards associated with a configured project.
- `jira_list_sprints` (read) lists sprints for a project board, optionally filtered by active, future, or closed state.
- `jira_search_users` (read) finds users assignable to a project by name or email.
- `jira_get_issue_types` (read) lists the issue types available in a project.
- `jira_get_priorities` (read) lists Jira priorities for a configured project.
- `jira_create_issue` (write) creates an issue with a required description prefixed by `[AI]` and adds the `ai-assisted` label; it can set an Epic's required name, story points, and parent Epic.
- `jira_update_issue` (write) updates an issue's summary, description, assignee, priority, labels, story points, and/or parent Epic; set `clear_epic_link = true` to remove its Epic assignment.
- `jira_add_comment` (write) adds an issue comment prefixed with `[AI]`.
- `jira_add_worklog` (write) records time spent with a required comment prefixed with `[AI]`.
- `jira_transition_issue` (write) moves an issue through one of its currently available workflow transitions.
- `jira_add_issue_to_sprint` (write) adds an issue to a sprint on a board belonging to the configured project.

Every Jira tool is scoped to projects in `config.toml`; read-only projects reject writes. Write tools are annotated as writes so Codex can request approval according to the MCP server approval mode. The Jira MCP does not expose arbitrary HTTP requests or issue deletion.

## Automation tool

- `sync_sprint_sheet` (write) fetches sprint issues, story points, and project worklogs from Jira, then updates the existing multi-sprint Google Sheet, formulas, analysis, and charts. For one sprint, provide its exact name as `sprint_name`. To combine subsprints for one review, provide the review label as `sprint_name` and the exact child Jira sprint names in `sprint_names`; the tool unions their issues and uses the earliest child start and latest child end as the reporting window. Optional `start_date` and `end_date` values override the corresponding window boundary. Each sync replaces that review label's Worklogs rows from the current Jira snapshot, while preserving rows for other labels, so reruns do not create duplicates.

The sync includes project worklogs within the reporting window, even when their issue is outside the selected sprint or subsprints. For a multi-subsprint review, it writes those worklogs under the parent review label so the Analysis selector and charts cover the whole review window. The tool is a write and follows the MCP client's configured write approval behavior.

For a given review, sync either the individual subsprints or one parent roll-up. Do not do both in the same workbook: each selection label is retained in the multi-sprint data, so syncing both would make `All sprints` count the same worklogs and issue scope more than once.

The Analysis sheet starts with a compact per-sprint time budget view. Team expected hours are calculated in the sheet as `Duration (weeks) × Expected hours per week × team size`; edit sprint durations in `Sprint Setup!D3:D` and the per-member weekly rate in `Sprint Setup!G1`. Each member and the team total have separate Value and Delta columns. Sprint deltas are zero until at least one team member logs time for that sprint, so the grand-total delta reflects current progress rather than future sprints. The table includes Sprint 0–4. The daily chart shows each member's cumulative hours from the start of the selected period; it excludes a team-sum series so individual lines remain easy to compare.

## XWiki tools

- `read_page` (read) returns a page's content and metadata.
- `read_page_section` (read) returns the content under a matching heading.
- `create_page` (write) creates a page with the supplied content, optional title, and syntax.
- `edit_page` (write) replaces a page's content and can update its title or syntax.
- `append_section` (write) adds a level-two section to an existing page.
- `edit_page_section` (write) replaces one section's body while preserving its heading and sibling sections.
- `list_spaces` (read) lists the spaces available in the selected wiki.
- `page_tree` (read) lists pages with creator, last editor, modification date, and version; it can filter by space or author.
- `search_pages` (read) searches page names, titles, content, or objects, with optional space filtering and pagination.
- `get_page_links` (read) lists XWiki syntax links found on a page.
- `find_orphan_pages` (read) finds scanned pages with no incoming XWiki syntax links.
- `list_attachments` (read) lists attachment metadata for a page.
- `read_attachment` (read) returns a text attachment as text or a binary attachment as base64, within the configured size limit.
- `add_comment` (write) posts a comment on a page.
- `list_comments` (read) lists comments attached to a page.
- `add_tags` (write) adds one or more tags to a page.
- `page_history` (read) lists recent versions of a page, including authors and dates when available.
- `diff_page_versions` (read) compares the text content of two page versions.
- `changes_between` (read) lists page versions modified during an inclusive `start_date`–`end_date` window. Pass `timezone_name` to interpret the calendar dates, then use each result's `space`, `page`, and `version` with `diff_page_versions`. If the result is truncated, continue with its `next_start` value and the same date/timezone arguments.
- `recent_changes` (read) lists pages modified within a selected number of days.
- `who_wrote_pages` (read) lists page creators, last editors, and modification dates, with optional space or author filters.
- `consistency_check` (read) checks scanned pages for required headings and unresolved internal links.
- `create_page_from_template` (write) creates a meeting, decision, task, or report page from supplied fields.
- `decision_log` (read) finds likely decision statements and reports their source pages and matching lines.
- `project_status` (read) collects checkbox tasks and nearby owner labels from pages in a space.
- `wiki_digest` (read) lists recently changed pages with titles, authors, and modification dates.

Every XWiki tool accepts the `wiki` selector. It defaults to the configured `default_wiki`; page names use `space` and `page`, with nested spaces separated by `/`.

The Jira integration provides bounded project-scoped reads and writes. Issue creation adds an `ai-assisted` label, and AI-generated comments and worklogs carry a visible `[AI]` prefix.
