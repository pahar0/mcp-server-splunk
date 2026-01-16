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

### Alerts
- `list_alerts` / `create_alert` / `update_alert` / `delete_alert`
- `get_alert_history`

### Saved Searches
- `list_saved_searches` / `create_saved_search` / `update_saved_search` / `delete_saved_search`

### Dashboards
- `list_dashboards` / `get_dashboard` / `create_dashboard` / `delete_dashboard`

### Knowledge Objects
- `list_lookups` / `get_lookup_data` / `update_lookup_data`
- `list_macros` / `create_macro` / `update_macro` / `delete_macro`
- `list_field_extractions`

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
- `get_server_info` / `get_server_settings`
- `check_restart_required` / `restart_splunk` / `refresh_splunk`
- `list_jobs` / `get_job_results` / `cancel_job`

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
