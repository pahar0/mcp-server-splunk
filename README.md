# Splunk MCP Server

A [Model Context Protocol](https://modelcontextprotocol.io/) server for Splunk. Enables AI assistants like Claude to search, manage, and analyze data in Splunk instances.

## Installation

### Claude Desktop

Add to your Claude Desktop config:

**macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
**Windows**: `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "splunk": {
      "command": "uvx",
      "args": ["mcp-server-splunk"],
      "env": {
        "SPLUNK_HOST": "your-splunk-host",
        "SPLUNK_TOKEN": "your-token"
      }
    }
  }
}
```

### Claude Code (CLI)

```bash
claude mcp add splunk -- uvx mcp-server-splunk \
  -e SPLUNK_HOST=your-splunk-host \
  -e SPLUNK_TOKEN=your-token
```

### OpenAI Codex

Add to `~/.codex/config.toml`:

```toml
[mcp_servers.splunk]
command = "uvx"
args = ["mcp-server-splunk"]

[mcp_servers.splunk.env]
SPLUNK_HOST = "your-splunk-host"
SPLUNK_TOKEN = "your-token"
```

### OpenCode

Add to your OpenCode config:

```yaml
mcp:
  splunk:
    type: local
    command: uvx mcp-server-splunk
    env:
      SPLUNK_HOST: your-splunk-host
      SPLUNK_TOKEN: your-token
```

## Configuration

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `SPLUNK_HOST` | Yes | localhost | Splunk server hostname |
| `SPLUNK_PORT` | No | 8089 | Splunk management port |
| `SPLUNK_SCHEME` | No | https | Connection scheme (http/https) |
| `SPLUNK_TOKEN` | * | - | Authentication token (recommended) |
| `SPLUNK_USERNAME` | * | - | Username (if not using token) |
| `SPLUNK_PASSWORD` | * | - | Password (if not using token) |

*Provide either `SPLUNK_TOKEN` or both `SPLUNK_USERNAME` and `SPLUNK_PASSWORD`.

### Getting a Splunk Token

1. Log into Splunk Web
2. Go to **Settings > Tokens**
3. Click **New Token**
4. Copy the token value

## Tools

### Search & Query
- `search_splunk` - Execute SPL queries
- `search_async` - Non-blocking searches
- `search_realtime` - Real-time streaming
- `export_search_results` - Export to file
- `run_saved_search` - Execute saved searches

### Index Management
- `list_indexes` / `get_index_info`
- `create_index` / `update_index` / `delete_index`
- `send_event` - Ingest events

`update_index` uses separate requests for ordinary settings and enable/disable operations. Combined changes are not atomic; a later failure does not roll back an earlier change.

### Alerts
- `list_alerts` / `create_alert` / `update_alert` / `delete_alert`
- `get_alert_history`

### Saved Searches
- `list_saved_searches` / `get_saved_search` / `run_saved_search`
- `create_saved_search` / `update_saved_search` / `delete_saved_search`

### Dashboards
- `list_dashboards` / `get_dashboard` / `create_dashboard` / `delete_dashboard`

### Knowledge Objects
- `list_lookups` / `get_lookup_data`
- `list_macros` / `get_macro` / `create_macro` / `update_macro` / `delete_macro`
- `list_field_extractions` / `get_field_summary`

### KV Store
- `list_kvstore_collections` / `create_kvstore_collection` / `delete_kvstore_collection`
- `query_kvstore_collection` / `insert_kvstore_data` / `update_kvstore_data` / `delete_kvstore_data`

### Data Inputs
- `list_inputs` / `get_input_info`
- `create_monitor_input` / `delete_input`

### Users & Roles
- `list_users` / `get_user_info` / `create_user` / `update_user` / `delete_user`
- `list_roles` / `get_role_info` / `create_role` / `update_role` / `delete_role`

### Apps
- `list_apps` / `create_app` / `update_app` / `delete_app`

### Server
- `get_server_info` / `get_server_settings` / `update_server_settings`
- `check_restart_required` / `restart_splunk` / `refresh_splunk`
- `list_jobs` / `get_job_status` / `get_job_results` / `cancel_job`

### Search Waiting and Cleanup

These tools accept optional `timeout_seconds`: `search_splunk`, `export_search_results`, `run_saved_search`, `get_alert_history`, `get_lookup_data`, `search_data_model`, `get_job_results`, and `get_field_summary`.

Use a positive number of seconds. The default `null` leaves completion waiting unlimited. This timeout covers waiting for the job to finish, not connection setup or downloading results. Real-time search keeps its existing timeout behavior.

```json
{"query": "index=main | head 10", "timeout_seconds": 30}
```

Tools clean up jobs they create even on errors or timeouts. `search_async` keeps successfully handed-off jobs, and `get_job_results` never cancels the caller's job. Cleanup failures are reported in `error` alongside the original failure.

A zero-row unlimited CSV export creates or truncates the destination to an empty file. Invalid data-model metadata returns an error instead of silently implying that acceleration is disabled.

### Updating Server Settings

`update_server_settings` requires a `kwargs` JSON object, not a JSON-encoded string:

```json
{"kwargs": {"sessionTimeout": "1h"}}
```

## Example Prompts

- "Search for errors in the last hour"
- "List all indexes and their sizes"
- "Create an alert for failed logins"
- "Show dashboards in the security app"

## Development

```bash
# Clone and install
git clone https://github.com/pahar0/mcp-server-splunk.git
cd mcp-server-splunk
uv sync

# Run locally
export SPLUNK_HOST=localhost SPLUNK_TOKEN=your-token
uv run mcp-server-splunk

# Debug with MCP Inspector
npx @modelcontextprotocol/inspector uv run mcp-server-splunk
```

## License

Apache 2.0
