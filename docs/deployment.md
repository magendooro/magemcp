# Deployment Guide

How to install, configure, and connect MageMCP to your AI client.

## Prerequisites

- Python 3.11+ (or Docker)
- A Magento 2 / Adobe Commerce instance with a configured integration token
- An MCP-compatible client (Claude Desktop, Claude Code, or any MCP client)

## Creating a Magento Integration Token

In Magento Admin: **System → Extensions → Integrations → Add New Integration**

1. Give it a name (e.g. "MageMCP")
2. Under **API** tab, select the resource access you need:
   - For read-only: Catalog, Sales, Customers, CMS
   - For write tools: include Orders, Products, Inventory, CMS write permissions
3. Save and **Activate** — copy the **Access Token** (this is your `MAGEMCP_ADMIN_TOKEN`)

## Installation Options

### From source

```bash
git clone https://github.com/magendooro/magemcp.git
cd magemcp
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

### From PyPI (when published)

```bash
pip install magemcp
```

### Docker

```bash
git clone https://github.com/magendooro/magemcp.git
cd magemcp
docker compose build magemcp
```

---

## Local Connection (same machine as the MCP client)

MageMCP uses **stdio** transport by default. The MCP client spawns a fresh process per session.

### Claude Desktop

Edit `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) or `%APPDATA%\Claude\claude_desktop_config.json` (Windows):

**With Docker:**
```json
{
  "mcpServers": {
    "magemcp": {
      "command": "docker",
      "args": [
        "compose", "-f", "/path/to/magemcp/docker-compose.yml",
        "run", "--rm", "-i", "magemcp"
      ],
      "env": {
        "MAGENTO_BASE_URL": "https://magento.example.com",
        "MAGEMCP_ADMIN_TOKEN": "your-integration-token"
      }
    }
  }
}
```

**With local venv (no Docker):**
```json
{
  "mcpServers": {
    "magemcp": {
      "command": "/path/to/magemcp/.venv/bin/magemcp",
      "env": {
        "MAGENTO_BASE_URL": "https://magento.example.com",
        "MAGEMCP_ADMIN_TOKEN": "your-integration-token"
      }
    }
  }
}
```

Restart Claude Desktop to pick up changes.

> **Local Magento?** Docker containers cannot reach the host via `127.0.0.1`. Use `http://host.docker.internal:<port>` instead. The local venv option does not have this limitation.

### Claude Code

Add `.mcp.json` to your project root:

```json
{
  "mcpServers": {
    "magemcp": {
      "command": "docker",
      "args": [
        "compose", "-f", "/path/to/magemcp/docker-compose.yml",
        "run", "--rm", "-i", "magemcp"
      ],
      "env": {
        "MAGENTO_BASE_URL": "https://magento.example.com",
        "MAGEMCP_ADMIN_TOKEN": "your-integration-token"
      }
    }
  }
}
```

Run `/mcp` in Claude Code to reload the server list without restarting.

### Other MCP Clients

Any MCP client that supports stdio transport can launch MageMCP as a subprocess:

```bash
MAGENTO_BASE_URL=https://magento.example.com \
MAGEMCP_ADMIN_TOKEN=your-token \
magemcp
```

---

## Dedicated Server Deployment

Run MageMCP on a remote server so multiple team members connect without installing anything locally.

```
Claude Desktop / Claude Code (laptop)
          │
          │  HTTPS  POST /mcp
          │  Bearer token auth
          ▼
  ┌──────────────────────────────┐
  │      Dedicated Server        │
  │  ┌────────────────────────┐  │
  │  │  nginx or Caddy        │  │
  │  │  TLS + Bearer auth     │  │
  │  └───────────┬────────────┘  │
  │              │ :8000         │
  │  ┌───────────▼────────────┐  │
  │  │  MageMCP container     │  │
  │  │  streamable-http       │  │
  │  └───────────┬────────────┘  │
  └──────────────│───────────────┘
                 │  REST / GraphQL (private network)
                 ▼
        Magento server
```

### Option A — SSH stdio (zero config, single user)

The MCP client pipes stdin/stdout over SSH. No HTTP transport or TLS setup needed.

**On the server:**

```bash
git clone https://github.com/magendooro/magemcp.git /opt/magemcp
cd /opt/magemcp
python -m venv .venv && source .venv/bin/activate
pip install -e .
```

**On your laptop (Claude Desktop or Claude Code config):**

```json
{
  "mcpServers": {
    "magemcp": {
      "command": "ssh",
      "args": [
        "user@your-server",
        "MAGENTO_BASE_URL=http://magento-internal MAGEMCP_ADMIN_TOKEN=xxx /opt/magemcp/.venv/bin/magemcp"
      ]
    }
  }
}
```

Or with Docker on the server:

```json
{
  "mcpServers": {
    "magemcp": {
      "command": "ssh",
      "args": [
        "user@your-server",
        "docker run --rm -i -e MAGENTO_BASE_URL=http://magento-internal -e MAGEMCP_ADMIN_TOKEN=xxx magemcp-magemcp"
      ]
    }
  }
}
```

Requires SSH key authentication — no password prompts.

**Pros:** works immediately, credentials stay on the server, no TLS setup.
**Cons:** one container started per session (~1–2 s), one SSH key per client.

---

### Option B — Streamable HTTP (multi-user, production)

A persistent MageMCP server behind a reverse proxy. Any number of clients connect simultaneously with a shared API key.

#### Step 1 — Deploy MageMCP

```bash
git clone https://github.com/magendooro/magemcp.git /opt/magemcp
cd /opt/magemcp
docker compose build magemcp

# Create config
cp .env.example .env
# Edit .env: set MAGENTO_BASE_URL, MAGEMCP_ADMIN_TOKEN

# Start the HTTP service
docker compose --profile http up -d magemcp-http
docker compose --profile http logs -f magemcp-http
```

The container binds to `127.0.0.1:8000` — not exposed to the internet yet.

#### Step 2 — Set up a reverse proxy

Choose **Caddy** (automatic TLS) or **nginx**.

**Caddy:**

```bash
apt install -y caddy

export MAGEMCP_API_KEY=$(openssl rand -hex 32)
echo "Your API key: $MAGEMCP_API_KEY"   # clients need this

export MCP_DOMAIN=mcp.example.com       # must have an A/AAAA record

envsubst < /opt/magemcp/deploy/Caddyfile | tee /etc/caddy/Caddyfile
systemctl reload caddy
```

**nginx:**

```bash
certbot --nginx -d mcp.example.com

export MAGEMCP_API_KEY=$(openssl rand -hex 32)
echo "Your API key: $MAGEMCP_API_KEY"

export MCP_DOMAIN=mcp.example.com

envsubst '${MCP_DOMAIN} ${MAGEMCP_API_KEY}' \
  < /opt/magemcp/deploy/nginx.conf.template \
  > /etc/nginx/sites-available/magemcp

ln -sf /etc/nginx/sites-available/magemcp /etc/nginx/sites-enabled/magemcp
nginx -t && systemctl reload nginx
```

#### Step 3 — Connect your MCP client

**Claude Desktop:**

```json
{
  "mcpServers": {
    "magemcp": {
      "url": "https://mcp.example.com/mcp",
      "headers": {
        "Authorization": "Bearer your-api-key"
      }
    }
  }
}
```

**Claude Code** (`.mcp.json`):

```json
{
  "mcpServers": {
    "magemcp": {
      "url": "https://mcp.example.com/mcp",
      "headers": {
        "Authorization": "Bearer your-api-key"
      }
    }
  }
}
```

Restart Claude Desktop (or run `/mcp` in Claude Code) to connect.

#### Verify connectivity

```bash
curl -s -X POST https://mcp.example.com/mcp \
  -H "Authorization: Bearer your-api-key" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"curl","version":"0"}}}' | jq .
```

Expected: `{"jsonrpc":"2.0","id":1,"result":{"serverInfo":{"name":"MageMCP",...}}}`

---

## Magento on a Separate Server

Use the **internal/private address** of your Magento server — not the public storefront URL. MageMCP calls Magento directly from the server side:

```bash
MAGENTO_BASE_URL=http://10.0.0.5          # private IP
MAGENTO_BASE_URL=http://magento.internal  # internal DNS name
```

Ensure the MageMCP server has outbound TCP access to the Magento host on port 80 or 443.

---

## Audit Logging

MageMCP records every tool invocation with trace ID, parameters, result, and HTTP calls made to Magento.

### File-based audit log

Set `MAGEMCP_AUDIT_LOG_FILE` to append structured JSON entries to a file:

```bash
MAGEMCP_AUDIT_LOG_FILE=/var/log/magemcp/audit.jsonl magemcp
```

Each line is a self-contained JSON object:

```json
{
  "tool": "admin_update_product",
  "params": {"sku": "24-MB01", "price": 39.99},
  "success": true,
  "duration_ms": 143.2,
  "timestamp": "2026-03-24T09:45:00Z",
  "trace_id": "018fdb00a7c4479b",
  "tool_class": "write",
  "result": {"sku": "24-MB01", "updated_fields": ["price"], "after": {"price": 39.99}},
  "http_calls": [
    {
      "method": "PUT",
      "url": "https://magento.example.com/rest/default/V1/products/24-MB01",
      "body": {"product": {"sku": "24-MB01", "price": 39.99}},
      "status": 200,
      "response": {"sku": "24-MB01", "price": 39.99}
    }
  ]
}
```

### Before-state capture

Set `MAGEMCP_AUDIT_BEFORE_STATE=true` to record the field values before a product update (costs one extra GET call per write):

```json
{
  "result": {
    "before": {"price": 29.99},
    "after":  {"price": 39.99},
    ...
  }
}
```

### HTTP audit endpoint

When running with HTTP transport, query recent entries in-memory:

```bash
# Last 50 entries
curl https://mcp.example.com/audit -H "Authorization: Bearer key"

# Filter by tool and classification
curl "https://mcp.example.com/audit?tool=admin_update_product&class=write&limit=20" \
  -H "Authorization: Bearer key"
```

---

## All Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `MAGENTO_BASE_URL` | Yes | Magento base URL (e.g. `https://magento.example.com`) |
| `MAGEMCP_ADMIN_TOKEN` | Yes* | Admin/integration Bearer token for `admin_*` tools |
| `MAGENTO_STORE_CODE` | No | Default store view code (default: `default`) |
| `MAGENTO_CUSTOMER_TOKEN` | No | Customer token for authenticated GraphQL queries |
| `MAGENTO_VERIFY_SSL` | No | `true` (default), `false`, or path to CA bundle |
| `MAGEMCP_LOG_LEVEL` | No | `DEBUG` / `INFO` / `WARNING` (default: `INFO`) |
| `MAGEMCP_SKIP_CONFIRMATION` | No | `true` to bypass confirmation on all write tools |
| `MAGEMCP_AUDIT_LOG_FILE` | No | Path for append-only JSONL audit log |
| `MAGEMCP_AUDIT_BEFORE_STATE` | No | `true` to capture before-state on product updates |
| `MAGEMCP_TRANSPORT` | No | `stdio` (default) or `streamable-http` |
| `MAGEMCP_HOST` | No | HTTP bind address (default: `127.0.0.1`) |
| `MAGEMCP_PORT` | No | HTTP bind port (default: `8000`) |
| `MAGEMCP_AUTH_ISSUER_URL` | No | OAuth issuer URL — enables JWT auth on HTTP transport |
| `MAGEMCP_AUTH_RESOURCE_SERVER_URL` | No | This server's URL, used as OAuth resource identifier |
| `MAGEMCP_AUTH_AUDIENCE` | No | Expected JWT `aud` claim (defaults to resource server URL) |
| `MAGEMCP_AUTH_REQUIRED_SCOPES` | No | Comma-separated required JWT scopes |
| `MAGENTO_TOKEN` | No | Legacy alias for `MAGEMCP_ADMIN_TOKEN` |

*`MAGEMCP_ADMIN_TOKEN` is required only for `admin_*` tools. `c_*` tools work without it.
