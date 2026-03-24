# Usage Examples

Once MageMCP is connected to an AI agent, the agent can answer commerce questions in natural language backed by live Magento data. Below are real examples run against a Magento 2 instance using Claude as the agent.

## Example Conversations

---

**How many simple products do I have in Magento?**

*Tool called: `admin_search_products` — `type_id=simple`, `page_size=1`*

> You have **106 simple products** in Magento.

---

**How many orders were placed today?**

*Tool called: `admin_search_orders` — `created_from=<today>`*

> **3 orders** were placed today, all in `pending` status.

---

**How many orders do we have this week?**

*Tool called: `admin_search_orders` — `created_from=<Monday>`*

> **9 orders** this week — 3 placed today, 6 the day before.

---

These questions each resolve to a single tool call. More complex questions compose several tools — for example, "show me the full details of the most recent order from john@example.com" would chain `admin_search_orders` → `admin_get_order`.

## Connecting an Agent (local / same machine)

MageMCP uses stdio transport by default. The MCP client spawns a fresh container (or process) per session — no persistent daemon needed.

### Claude Desktop

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

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
        "MAGENTO_BASE_URL": "https://your-magento.example.com",
        "MAGEMCP_ADMIN_TOKEN": "your-integration-token"
      }
    }
  }
}
```

> **Local Magento on the same machine?** Docker containers cannot reach the host via `127.0.0.1`. Use `http://host.docker.internal:<port>` instead — Docker Desktop on macOS and Windows resolves this automatically.

Restart Claude Desktop to pick up the new server.

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
        "MAGENTO_BASE_URL": "https://your-magento.example.com",
        "MAGEMCP_ADMIN_TOKEN": "your-integration-token"
      }
    }
  }
}
```

Run `/mcp` to reload the server list without restarting.

### Local venv (no Docker)

If you have the source installed, reference the binary directly — `127.0.0.1` works without translation:

```json
{
  "mcpServers": {
    "magemcp": {
      "command": "/path/to/magemcp/.venv/bin/magemcp",
      "env": {
        "MAGENTO_BASE_URL": "http://localhost:8082",
        "MAGEMCP_ADMIN_TOKEN": "your-integration-token"
      }
    }
  }
}
```

---

## Dedicated Server Deployment

Run MageMCP on a remote server so multiple team members can connect without installing anything locally. The server also connects to a Magento instance on a separate machine over your private network.

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

### Option A — SSH stdio (zero code changes, single user)

The MCP client connects via SSH. No HTTP transport or reverse proxy needed — SSH pipes stdin/stdout over the network.

**On the server**, install MageMCP:
```bash
git clone https://github.com/magendooro/magemcp.git /opt/magemcp
cd /opt/magemcp
python -m venv .venv && source .venv/bin/activate
pip install -e .
```

**On your laptop**, point the MCP client at SSH:

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

Or with Docker on the server (no venv needed):

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

> Requires SSH key auth (no password prompts). Add your public key to `~/.ssh/authorized_keys` on the server.

**Pros:** works immediately, no TLS setup, credentials stay on the server.
**Cons:** one container spawned per session (1–2 s startup), single-user SSH key per client.

---

### Option B — Streamable HTTP (multi-user, production)

A persistent MCP server behind nginx or Caddy. Any number of clients connect simultaneously with a shared API key.

#### Step 1 — Deploy MageMCP on the server

```bash
git clone https://github.com/magendooro/magemcp.git /opt/magemcp
cd /opt/magemcp

# Build the image
docker compose build magemcp

# Create .env with your values
cp .env.example .env
# Edit .env: set MAGENTO_BASE_URL, MAGEMCP_ADMIN_TOKEN

# Start the HTTP service
docker compose --profile http up -d magemcp-http
docker compose --profile http logs -f magemcp-http
```

The container binds to `127.0.0.1:8000` on the host — not accessible from outside yet.

#### Step 2 — Set up a reverse proxy

Choose **Caddy** (recommended — automatic TLS) or **nginx**.

**Caddy:**

```bash
# Install Caddy
apt install -y caddy   # Debian/Ubuntu

# Generate a random API key
export MAGEMCP_API_KEY=$(openssl rand -hex 32)
echo "API key: $MAGEMCP_API_KEY"   # save this — clients need it

export MCP_DOMAIN=mcp.example.com  # must have an A record pointing here

# Apply config
envsubst < /opt/magemcp/deploy/Caddyfile | tee /etc/caddy/Caddyfile
systemctl reload caddy
```

**nginx:**

```bash
# Get a TLS certificate first
certbot --nginx -d mcp.example.com

export MAGEMCP_API_KEY=$(openssl rand -hex 32)
echo "API key: $MAGEMCP_API_KEY"

export MCP_DOMAIN=mcp.example.com

envsubst '${MCP_DOMAIN} ${MAGEMCP_API_KEY}' \
  < /opt/magemcp/deploy/nginx.conf.template \
  > /etc/nginx/sites-available/magemcp

ln -sf /etc/nginx/sites-available/magemcp /etc/nginx/sites-enabled/magemcp
nginx -t && systemctl reload nginx
```

#### Step 3 — Connect your MCP client

**Claude Desktop** (`~/Library/Application Support/Claude/claude_desktop_config.json`):

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

**Claude Code** (`.mcp.json` in project root):

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

#### Verify the server is responding

```bash
curl -s -X POST https://mcp.example.com/mcp \
  -H "Authorization: Bearer your-api-key" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"curl","version":"0"}}}' | jq .
```

Expected: `{"jsonrpc":"2.0","id":1,"result":{"serverInfo":{"name":"MageMCP",...}}}`

---

### Magento on a separate server

Whether using SSH or HTTP transport, the `MAGENTO_BASE_URL` should be the **private / internal address** of your Magento server, not the public storefront URL. The MageMCP container calls Magento directly — use the private network IP or internal DNS name if available:

```
MAGENTO_BASE_URL=http://10.0.0.5       # private IP
MAGENTO_BASE_URL=http://magento.internal   # internal DNS
```

Ensure the MageMCP server has outbound access to the Magento host on port 80/443.

---

## What the Agent Can Do

### Read (no confirmation needed)

| Domain | Example questions |
|--------|-------------------|
| Catalog | "Find all bags under €50", "Show me the full details for SKU 24-MB01" |
| Categories | "What top-level categories do we have?", "Which category has the most products?" |
| Orders | "Show pending orders from this week", "What's in order #000000042?" |
| Customers | "Find customers named Smith", "Pull up the full profile for jane@example.com" |
| Inventory | "Is SKU MH01-XS-Black in stock?", "What's the salable quantity for these 5 SKUs?" |
| CMS | "Show me the content of the homepage CMS block", "List all active CMS pages" |
| Promotions | "What active discount rules do we have?", "List coupon codes for rule #5" |
| Store | "What currency and locale is the store using?", "Resolve /yoga.html to a product or category" |

### Write (require `confirm=True` on second call)

| Domain | Example actions |
|--------|-----------------|
| Orders | Cancel, hold/unhold, add comment, create invoice, create shipment, resend email |
| Products | Update name, price, description, or any attribute |
| Inventory | Set MSI source item quantity |
| CMS | Update page title, content, active status, or meta fields |
| Promotions | Generate new coupon codes for a cart price rule |

Set `MAGEMCP_SKIP_CONFIRMATION=true` to bypass confirmation in automated pipelines.

See the [Tool Reference](README.md#tool-reference) for the complete list.
