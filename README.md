# Splunk MCP Server

Search and manage Splunk from Pi, Claude Code, and Codex using [MCP](https://modelcontextprotocol.io/).

## Connection

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then run **one** of these Bash examples. Replace `localhost` with your Splunk hostname.

**Token:**

```bash
export SPLUNK_HOST=localhost
read -rsp 'Splunk token: ' SPLUNK_TOKEN; echo
export SPLUNK_TOKEN
```

Create a token in Splunk Web: **Settings → Tokens → New Token**.

**Or username/password:**

```bash
export SPLUNK_HOST=localhost
unset SPLUNK_TOKEN
export SPLUNK_USERNAME=your-username
read -rsp 'Splunk password: ' SPLUNK_PASSWORD; echo
export SPLUNK_PASSWORD
```

Launch your client from the same terminal. Restart it if it is already running.

## Installation

### Pi

```bash
pi mcp add splunk -- uvx mcp-server-splunk@latest
pi mcp list
pi
```

### Claude Code

```bash
claude mcp add --transport stdio --scope user splunk -- uvx mcp-server-splunk@latest
claude mcp list
claude
```

### Codex

Add to `~/.codex/config.toml`:

```toml
[mcp_servers.splunk]
command = "uvx"
args = ["mcp-server-splunk@latest"]
env_vars = [
    "SPLUNK_HOST", "SPLUNK_PORT", "SPLUNK_SCHEME",
    "SPLUNK_TOKEN", "SPLUNK_USERNAME", "SPLUNK_PASSWORD",
]
```

```bash
codex mcp list
codex
```

## Configuration

| Variable | Default | Purpose |
|----------|---------|---------|
| `SPLUNK_HOST` | `localhost` | Splunk hostname, without scheme or port |
| `SPLUNK_PORT` | `8089` | Management API port |
| `SPLUNK_SCHEME` | `https` | `http` or `https` |
| `SPLUNK_TOKEN` | — | Authentication token |
| `SPLUNK_USERNAME` | — | Username when not using a token |
| `SPLUNK_PASSWORD` | — | Password when not using a token |

Use a token **or** username/password. A token takes precedence if both are set. The server does not load `.env` files automatically.

## Tools

91 tools cover searches, indexes, alerts, saved searches, dashboards, lookups, macros, KV Store, inputs, users, roles, apps, and server administration. See [tool definitions](splunk_mcp_server.py) for parameters and behavior.

Some tools modify or delete Splunk resources. Use an account with only the permissions you need.

## Development

With connection variables set as above:

```bash
git clone https://github.com/pahar0/mcp-server-splunk.git
cd mcp-server-splunk
uv sync
uv run mcp-server-splunk
```

## License

[Apache 2.0](LICENSE)
