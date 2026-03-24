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

## Connecting an Agent

MageMCP uses stdio transport. The MCP client spawns a fresh container (or process) per session — no persistent daemon needed.

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
