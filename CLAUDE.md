# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Model Context Protocol (MCP) server that provides 50+ tools for interacting with Splunk. It enables LLM applications like Claude to search, retrieve, and manage data in Splunk instances through a comprehensive REST API wrapper.

## Development Commands

### Setup and Installation

```bash
# Install with uv (recommended)
uv pip install -e .

# Or install dependencies only
pip install -r requirements.txt
```

### Running the MCP Server

```bash
# Using installed command
mcp-server-splunk

# Or via uv
uv run mcp-server-splunk

# Debug with MCP Inspector
npx @modelcontextprotocol/inspector uv run mcp-server-splunk
```

### Configuration

The server requires environment variables for Splunk connection (passed via MCP client config):
- `SPLUNK_HOST`: Splunk server hostname (default: localhost)
- `SPLUNK_PORT`: Management port (default: 8089)
- `SPLUNK_SCHEME`: Connection scheme (http/https, default: https)
- `SPLUNK_TOKEN`: Authentication token (preferred)
- `SPLUNK_USERNAME` and `SPLUNK_PASSWORD`: Username/password authentication (fallback)

## Architecture

### Core Components

**Connection Management** (`get_splunk_service()`)
- Singleton pattern for Splunk service connections
- Supports both token-based and username/password authentication
- Token authentication takes precedence if both are configured
- Uses `splunklib.client` from the Splunk Python SDK

**MCP Server Framework**
- Built on FastMCP (`mcp.server.fastmcp`)
- All tools use the `@mcp.tool()` decorator
- Tools return dictionaries with `success`, `error`, and result data fields
- Consistent error handling pattern across all tools

**Entry Point**
- `main()` function at end of file for package entry point
- Defined in `pyproject.toml` as `mcp-server-splunk = "splunk_mcp_server:main"`

### Tool Categories

The 50+ tools are organized into these functional groups:

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
- Default app is typically "search" but can be specified per operation
- Owner defaults to "-" (all users) or "nobody" (global scope)
- Many tools accept an optional `app` parameter for filtering (saved searches, alerts, lookups, macros)

**Job Lifecycle**
- Search operations create jobs via `service.jobs.create()`
- Jobs are polled with `while not job.is_done(): pass`
- Results are retrieved with `job.results(count=max_count)`
- Jobs are cancelled with `job.cancel()` to free resources

**Error Handling**
- All tools return `{"success": bool, ...}` dictionaries
- KeyError exceptions indicate resource not found
- Generic exceptions are caught and returned in `error` field
- No exceptions propagate to the MCP layer

**Restart Notification**
- `delete_app()` checks `service.restart_required` after deletion
- Returns `restart_required` and `note` fields when restart is needed

## Special Considerations

### Query Auto-Prefixing
The `search_splunk()` tool automatically prefixes queries with `search` if they don't start with recognized commands (`search`, `|`, `from`, `tstats`, `inputlookup`).

### Dashboard XML Format
When creating dashboards via `create_dashboard()`, pass plain XML without CDATA wrappers. The XML must include a `<label>` tag.

### KV Store Operations
KV Store collections use MongoDB-style query syntax. The SDK provides a `.data` property on collections for CRUD operations:
- `collection.data.query(**params)` for queries
- `collection.data.insert(data)` for inserts
- `collection.data.update(key, data)` for updates
- Direct REST API call for deletes

### Lookup Table Updates
The `update_lookup_data()` tool replaces ALL existing data in the lookup table. It converts the list of dictionaries to CSV format before posting to the REST API.

### Server Restart vs Refresh
- `restart_splunk()`: Full splunkd restart using `service.restart()`
- `refresh_splunk()`: Reload configs without restart using `/services/apps/local/_reload`

### Field Summary
The `get_field_summary()` tool provides introspection into an index's fields, types, and sample values. Useful for understanding data structure before writing SPL queries.

## Dependencies

- **mcp**: FastMCP framework for building MCP servers
- **splunk-sdk**: Official Splunk Python SDK for REST API interaction

## Python Version

Requires Python 3.10+ as specified in pyproject.toml.
