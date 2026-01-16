# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Model Context Protocol (MCP) server that provides 50+ tools for interacting with Splunk. It enables LLM applications like Claude to search, retrieve, and manage data in Splunk instances through a comprehensive REST API wrapper.

## Development Commands

### Setup and Installation

```bash
# Install dependencies
pip install -r requirements.txt
# or with uv (recommended)
uv pip install -r requirements.txt
```

### Running the MCP Server

```bash
# Development mode with MCP Inspector
uv run mcp dev splunk_mcp_server.py

# Direct execution
python splunk_mcp_server.py

# Install in Claude Desktop
uv run mcp install splunk_mcp_server.py
```

### Configuration

The server requires environment variables for Splunk connection. Copy `.env.example` to `.env` and configure:
- `SPLUNK_HOST`: Splunk server hostname (default: localhost)
- `SPLUNK_PORT`: Management port (default: 8089)
- `SPLUNK_SCHEME`: Connection scheme (http/https, default: https)
- `SPLUNK_TOKEN`: Authentication token (preferred)
- `SPLUNK_USERNAME` and `SPLUNK_PASSWORD`: Username/password authentication (fallback)

## Architecture

### Core Components

**Connection Management** (`get_splunk_service()` at line 39)
- Singleton pattern for Splunk service connections
- Supports both token-based and username/password authentication
- Token authentication takes precedence if both are configured
- Uses `splunklib.client` from the Splunk Python SDK

**MCP Server Framework**
- Built on FastMCP (`mcp.server.fastmcp`)
- All tools use the `@mcp.tool()` decorator
- Tools return dictionaries with `success`, `error`, and result data fields
- Consistent error handling pattern across all tools

### Tool Categories

The 50+ tools are organized into these functional groups:

1. **Search & Query** (lines 73-287): Execute SPL queries, run saved searches, retrieve results
2. **Index Management** (lines 150-183, 499-543): List indexes, get index details, retrieve statistics
3. **Alert Management** (lines 682-923): CRUD operations for alerts, view alert history
4. **Dashboard Operations** (lines 930-1079): Create/read/delete dashboards, manage XML content
5. **Knowledge Objects** (lines 1086-1280): Lookups, field extractions, data models
6. **Data Input Management** (lines 1287-1452): Monitor file inputs, network inputs, scripts
7. **User & Access Management** (lines 1459-1614): Users, roles, capabilities, permissions
8. **KV Store Operations** (lines 1621-1851): NoSQL-style storage with CRUD operations
9. **Data Model Tools** (lines 1858-2057): Accelerated data model searches using tstats
10. **Job Management** (lines 2064-2176): Monitor and control search jobs
11. **Search Macros** (lines 2183-2427): Reusable search components
12. **Server Administration** (lines 2434-2783): Server messages, settings, restart checks

### Key Design Patterns

**Namespace Management**
- Many operations set `service.namespace['app']` to control app context
- Default app is typically "search" but can be specified per operation
- Owner defaults to "-" (all users) or "nobody" (global scope)

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

**Data Serialization**
- REST API responses are parsed from JSON when needed
- Some endpoints return JSON-encoded strings that require double parsing
- CSV data for lookups is manually constructed from dictionaries
- Dashboard XML is passed directly without CDATA wrappers

## Special Considerations

### Query Auto-Prefixing
The `search_splunk()` tool automatically prefixes queries with `search` if they don't start with recognized commands (`search`, `|`, `from`, `tstats`, `inputlookup`). This is at line 95.

### Dashboard XML Format
When creating dashboards via `create_dashboard()`, pass plain XML without CDATA wrappers. The XML must include a `<label>` tag. The tool uses `eai:data` parameter for the XML content (line 1037).

### KV Store Operations
KV Store collections use MongoDB-style query syntax. The SDK provides a `.data` property on collections for CRUD operations:
- `collection.data.query(**params)` for queries
- `collection.data.insert(data)` for inserts
- `collection.data.update(key, data)` for updates
- Direct REST API call for deletes (line 1832)

### Lookup Table Updates
The `update_lookup_data()` tool replaces ALL existing data in the lookup table. It converts the list of dictionaries to CSV format manually (lines 1204-1212) before posting to the REST API.

### Large Response Mitigation
Some tools like `get_data_model()` accept a `summary_only` parameter (default: True) to avoid returning massive JSON payloads. Always use summary mode unless full details are explicitly needed.

## Dependencies

- **mcp[cli]**: FastMCP framework for building MCP servers
- **splunk-sdk**: Official Splunk Python SDK for REST API interaction
- **python-dotenv**: Environment variable management from .env files

## Python Version

Requires Python 3.10+ as specified in pyproject.toml.
