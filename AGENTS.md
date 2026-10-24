# AGENTS.md

Guidance for coding agents working anywhere in this repository.

## Project Overview

This Model Context Protocol (MCP) server currently exposes 91 tools for interacting with Splunk. The implementation is in `splunk_mcp_server.py`; tool signatures and bodies are the source of truth for behavior.

## Change Scope and Safety

- Keep changes narrowly scoped to the request. Preserve tool names, parameters, defaults, return keys, limits, export formats, and app/owner behavior unless a change is explicitly approved.
- Keep one registered implementation per tool name. The macro and job tools combine capabilities from earlier alternatives; do not discard options while simplifying them.
- Do not introduce automatic fallbacks, substitute versions, or broader-scope retries after failed lookups. Missing required metadata and ambiguous resource matches must fail explicitly.
- Do not bundle dependency upgrades, broad formatting, runtime wrappers, or new test/CI infrastructure into unrelated maintenance.
- Do not change tool annotations, MCP error flags, or the `update_server_settings(kwargs: dict[str, Any])` schema without specific approval.
- Live Splunk operations can modify real data. Obtain authorization before live testing or restarting/refreshing Splunk. Use uniquely named fixtures and delete only exact resources created for that validation; app-scoped listings can include inherited system objects.
- Never log credentials or commit environment files. Do not commit, push, or publish unless requested.

## Development Commands

### Setup and Installation

```bash
# Create and activate a local environment (POSIX shell)
uv venv
source .venv/bin/activate

# Install this checkout, including its console entry point
uv pip install -e .

# Optional development tools declared in pyproject.toml
uv pip install -e ".[dev]"
```

Alternatively, use `python -m pip install -e .` to install the project. Installing only `requirements.txt` is insufficient: startup requires the installed project's package metadata.

### Running the MCP Server

```bash
# Using installed command
mcp-server-splunk

# Or use the already-installed uv environment without resyncing it
uv run --no-sync mcp-server-splunk

# Debug with MCP Inspector
npx @modelcontextprotocol/inspector uv run --no-sync mcp-server-splunk
```

### Configuration

Connection settings are read from the process environment at import time, usually passed through MCP client configuration. `.env.example` documents the variables; the server does not automatically load an `.env` file.

- `SPLUNK_HOST`: Splunk server hostname (default: localhost)
- `SPLUNK_PORT`: Management port (default: 8089)
- `SPLUNK_SCHEME`: Connection scheme (http/https, default: https)
- `SPLUNK_TOKEN`: Authentication token (preferred)
- `SPLUNK_USERNAME` and `SPLUNK_PASSWORD`: Username/password authentication when `SPLUNK_TOKEN` is unset; a failed token login is not retried with these credentials

## Architecture

### Core Components

**Connection Management** (`get_splunk_service()`)
- Creates a fresh `splunklib.client.Service` connection for each call; it is not a singleton
- Supports both token-based and username/password authentication
- Token authentication takes precedence if both are configured
- Uses `splunklib.client` from the Splunk Python SDK

**MCP Server Framework**
- Built on MCPServer (`mcp.server`)
- All tools use the `@mcp.tool()` decorator
- Tools return dictionaries with `success`, `error`, and result data fields
- SDK 2 runs synchronous handlers in worker threads, so calls can overlap. Do not introduce a shared mutable Service connection or custom execution wrappers as incidental cleanup.
- Same-resource writes are not automatically serialized. Use distinct filenames for parallel exports and coordinate writes to the same Splunk object.

**Entry Point**
- `main()` function at end of file for package entry point
- Defined in `pyproject.toml` as `mcp-server-splunk = "splunk_mcp_server:main"`
- The server reports the installed package version via `importlib.metadata`. Missing project metadata is a startup error; install the project instead of supplying a hardcoded substitute version.

### Tool Categories

The tools are organized into these functional groups:

1. **Search & Query**: Execute SPL queries, run saved searches, retrieve results
2. **Index Management**: List indexes, get index details, create/update/delete indexes
3. **Alert Management**: CRUD operations for alerts, view alert history
4. **Dashboard Operations**: Create/read/delete dashboards, manage XML content
5. **Knowledge Objects**: Lookups, field extractions, macros, data models
6. **Data Input Management**: Monitor file inputs, network inputs
7. **User & Access Management**: Users, roles, capabilities, permissions
8. **KV Store Operations**: NoSQL-style storage with CRUD operations
9. **Data Model Tools**: Accelerated data model searches using tstats
10. **Job Management**: Monitor and control search jobs
11. **Server Administration**: Server messages, settings, restart, refresh

### Key Design Patterns

**Namespace Management**
- Many operations set `service.namespace['app']` to control app context
- App/owner defaults vary by tool; many default to app `"search"`, while some support wildcard or cross-app selection. Do not normalize these defaults globally.
- `"-"` is a wildcard namespace; `"nobody"` is an owner value used for app-level objects. Preserve each operation's existing context.
- Macro lookup/update/deletion uses `_find_macro()` with one app-scoped lookup across visible owners. `None`/`"-"` explicitly selects all apps. Missing or multiple matches fail; do not retry with a broader scope or pick the first match.

**Job Lifecycle**
- Search operations create jobs via `service.jobs.create()`.
- Eight completion-wait tools accept optional `timeout_seconds` (a positive finite number or `None`). The default remains `None`, meaning no completion-wait limit. Poll with `_wait_for_search_job()` using a monotonic deadline and a short sleep; failed jobs must fail explicitly. The timeout does not bound connection setup or result downloads.
- Results are retrieved through `job.results(...)`. Preserve per-tool limits and pagination; `max_count=0` means unlimited where documented.
- Tools cancel jobs they create in `finally`, including failures and completion timeouts. `_cleanup_search_job()` preserves each tool's failure shape and includes cleanup failures in `error` without hiding the original error. No alternate cancellation endpoint or automatic retry is used.
- `search_async()` hands off successful jobs to the caller; only a failure before handoff triggers cleanup. `get_job_results()` never cancels the caller's job, including on timeout or failure. `cancel_job()` provides explicit cancellation.

**Error Handling**
- Tools generally return `{"success": bool, ...}` dictionaries, with result data or an `error` field.
- Many handlers translate `KeyError` into a resource-not-found response and catch other operation errors.
- A returned `success=False` dictionary currently remains an ordinary MCP result; the SDK does not infer an MCP error flag from that key. Preserve this contract unless asked to change it.
- Some exceptions, including connection failures raised before a handler's `try` block, reach SDK error handling. Do not assume every failure becomes the same JSON shape.

**Restart Notification**
- `delete_app()` checks `service.restart_required` after deletion
- Returns `restart_required` and `note` fields when restart is needed

## Special Considerations

### Query Auto-Prefixing
The `search_splunk()` tool automatically prefixes queries with `search` if they don't start with recognized commands (`search`, `|`, `from`, `tstats`, `inputlookup`).

### Dashboard XML Format
When creating dashboards via `create_dashboard()`, pass plain XML without CDATA wrappers. The XML must include a `<label>` tag.

### Exports
Preserve existing file paths, overwrite behavior, limits, and CSV/JSON/XML output. Finite JSON exports use `results.JSONResultsReader`; finite XML exports count actual result elements without rewriting the native XML payload. Finite CSV row counts use logical CSV records, including quoted newlines. Unlimited XML exports retain native `<result>` fragments without capturing the `<results>` wrapper. Zero-row unlimited CSV exports create or truncate the destination to an empty file. Do not replace the existing search-result parsers or add silent caps as unrelated cleanup.

### KV Store Operations
KV Store collections use MongoDB-style query syntax. The SDK provides a `.data` property on collections for CRUD operations:
- `collection.data.query(**params)` for queries
- `collection.data.insert(data)` for inserts
- `collection.data.update(key, data)` for updates
- `collection.data.delete_by_id(key)` for record deletion

`create_kvstore_lookup()` must roll back only a collection created by that invocation. A duplicate-create failure must not delete a pre-existing collection.

### Server Settings and Index State

- `update_server_settings()` requires a `kwargs` JSON object, not a JSON-encoded string, and unpacks it into the SDK settings update.
- `update_index()` sends ordinary settings through `index.update()` and uses `index.enable()` / `index.disable()` for state changes. Combined changes use separate requests and are not atomic; do not silently retry or roll back partial changes.

### Server Restart vs Refresh
- `restart_splunk()`: Full splunkd restart using `service.restart()`
- `refresh_splunk()`: Reload configs without restart using `/services/apps/local/_reload`

### Data Model Metadata

Both data-model listing and detailed summaries require valid JSON objects for acceleration and definition metadata. Malformed or missing required metadata must return an error, not imply disabled acceleration or substitute a plain-text description.

### Field Summary
The `get_field_summary()` tool provides introspection into an index's fields, types, and sample values. Useful for understanding data structure before writing SPL queries.

## Validation

There is currently no checked-in test suite or CI workflow. Development extras declare pytest and Ruff, but do not treat their presence as evidence of existing tests.

- For small changes, use syntax/import checks and `git diff --check`; inspect only the affected code rather than mass-formatting the module.
- For SDK/tool changes, compare tool schemas, defaults, and returned data. Check legacy and current MCP clients when protocol compatibility is in scope.
- Keep temporary validation scripts, exports, and captured responses outside the repository where possible. Do not run live mutations merely to validate documentation changes.

## Dependencies

Keep the declarations in `pyproject.toml` and `requirements.txt` aligned:

- **mcp**: `>=2.3.0,<3`, using `MCPServer` from `mcp.server`.
- **splunk-sdk**: `>=2.1.1,<3`, retaining the existing ResultsReader-based search implementations.

## Python Version

Requires Python 3.10+ as specified in pyproject.toml.
