# MageMCP

MCP (Model Context Protocol) server for Magento 2 / Adobe Commerce by [Magendoo](https://magendoo.ro).

Connects AI agents to a live Magento instance via REST and GraphQL APIs, exposing typed tools for catalog, cart, orders, customers, inventory, CMS, and promotions.

## Architecture

MageMCP runs as a standalone Python service — not embedded in Magento. Tools are split into two namespaces based on access context:

```
MCP Client (Claude, agent, etc.)
        │
        ▼
  ┌─────────────────────────────────────┐
  │           MageMCP server            │
  │                                     │
  │   c_* tools          admin_* tools  │
  │   (storefront)       (back-office)  │
  │        │                   │        │
  │  GraphQLClient        RESTClient    │
  │  (guest/customer)   (admin token)   │
  └────────┬──────────────────┬─────────┘
           │                  │
           ▼                  ▼
     /graphql          /rest/V1/...
           └──────────────────┘
              Magento 2 / Adobe Commerce
```

| Namespace | Transport | Auth | Audience |
|-----------|-----------|------|----------|
| `c_*` | GraphQL | None / customer token | Shopping assistants, self-service |
| `admin_*` | REST | Admin Bearer token | Support agents, ops teams |

## Tool Reference

### `c_*` — Customer-Facing Tools

#### Catalog & Navigation

| Tool | Description |
|------|-------------|
| `c_search_products` | Search storefront catalog — text query, category/price filters, sorting, in-stock filter |
| `c_get_product` | Full product detail by SKU — images, categories, configurable options, descriptions |
| `c_get_categories` | Category tree with children and product counts (3 levels deep) |
| `c_resolve_url` | Resolve SEO URL to product, category, or CMS page |
| `c_get_store_config` | Store locale, currency, base URLs |

#### Cart & Checkout

| Tool | Description |
|------|-------------|
| `c_create_cart` | Create an empty guest cart, returns `cart_id` |
| `c_get_cart` | Full cart details — items, prices, addresses, totals |
| `c_add_to_cart` | Add product by SKU and quantity |
| `c_update_cart_item` | Update item quantity or remove item |
| `c_apply_coupon` | Apply a discount coupon code |
| `c_set_guest_email` | Set email for guest checkout |
| `c_set_shipping_address` | Set shipping address |
| `c_set_billing_address` | Set billing address |
| `c_set_shipping_method` | Select a shipping method |
| `c_set_payment_method` | Select a payment method |
| `c_place_order` | Place the order — returns order number |

### `admin_*` — Admin Tools

#### Orders

| Tool | Description |
|------|-------------|
| `admin_search_orders` | Search orders — status, email, date range, total range |
| `admin_get_order` | Full order by increment ID — payment, invoices, credit memos, full status history |
| `admin_cancel_order` | Cancel an order *(requires confirmation)* |
| `admin_hold_order` | Put order on hold *(requires confirmation)* |
| `admin_unhold_order` | Release order from hold *(requires confirmation)* |
| `admin_add_order_comment` | Add internal or customer-visible comment |
| `admin_create_invoice` | Create invoice and optionally capture payment *(requires confirmation)* |
| `admin_create_shipment` | Create shipment with optional tracking *(requires confirmation)* |
| `admin_send_order_email` | Resend order confirmation email *(requires confirmation)* |

#### Customers

| Tool | Description |
|------|-------------|
| `admin_search_customers` | Search by email/name/group — wildcard support, full unmasked data |
| `admin_get_customer` | Full profile by ID or email — all addresses, custom attributes, B2B extension attributes |

#### Products

| Tool | Description |
|------|-------------|
| `admin_search_products` | Search by name/SKU/type/status/visibility/price range |
| `admin_get_product` | Full product — all attributes, media gallery, stock, tier prices, options |
| `admin_update_product` | Partial attribute update — only specified fields changed *(requires confirmation)* |

#### Inventory

| Tool | Description |
|------|-------------|
| `admin_get_inventory` | Salable quantity and availability for one or more SKUs |
| `admin_update_inventory` | Update MSI source item quantity *(requires confirmation)* |

#### CMS

| Tool | Description |
|------|-------------|
| `admin_search_cms_pages` | Search CMS pages by title/identifier/active status |
| `admin_get_cms_page` | Get page by numeric ID or URL identifier — full HTML content |
| `admin_update_cms_page` | Update title, content, active status, meta fields *(requires confirmation)* |

#### Promotions

| Tool | Description |
|------|-------------|
| `admin_search_sales_rules` | Search cart price rules by name/active status |
| `admin_get_sales_rule` | Full rule — conditions, actions, discount config, usage stats |
| `admin_generate_coupons` | Generate coupon codes for a rule *(requires confirmation)* |

> **Confirmation pattern** — Write tools require `confirm=True` on the second call. The first call returns a prompt describing what will happen. Set `MAGEMCP_SKIP_CONFIRMATION=true` to bypass in automated pipelines.

## Quick Start

### From source

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

export MAGENTO_BASE_URL=https://magento.example.com
export MAGEMCP_ADMIN_TOKEN=your-integration-token

magemcp          # runs MCP server on stdio
```

### With Docker

```bash
cp .env.example .env   # fill in MAGENTO_BASE_URL and MAGEMCP_ADMIN_TOKEN
docker compose up -d
docker compose logs -f magemcp
```

### Connect to Claude Desktop

Add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "magemcp": {
      "command": "docker",
      "args": ["compose", "-f", "/path/to/magemcp/docker-compose.yml", "run", "--rm", "-i", "magemcp"],
      "env": {
        "MAGENTO_BASE_URL": "https://magento.example.com",
        "MAGEMCP_ADMIN_TOKEN": "your-token"
      }
    }
  }
}
```

Or with the local venv:

```json
{
  "mcpServers": {
    "magemcp": {
      "command": "/path/to/magemcp/.venv/bin/magemcp",
      "env": {
        "MAGENTO_BASE_URL": "https://magento.example.com",
        "MAGEMCP_ADMIN_TOKEN": "your-token"
      }
    }
  }
}
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `MAGENTO_BASE_URL` | Yes | Base URL of the Magento instance (e.g. `https://magento.example.com`) |
| `MAGEMCP_ADMIN_TOKEN` | Yes | Integration/admin Bearer token — grants access to all `admin_*` tools |
| `MAGENTO_STORE_CODE` | No | Default store view code (default: `default`) |
| `MAGENTO_CUSTOMER_TOKEN` | No | Customer Bearer token for authenticated GraphQL queries |
| `MAGEMCP_LOG_LEVEL` | No | Log verbosity: `DEBUG`, `INFO`, `WARNING` (default: `INFO`) |
| `MAGEMCP_SKIP_CONFIRMATION` | No | Set to `true` to bypass confirmation prompts on write tools |
| `MAGENTO_TOKEN` | No | Legacy alias for `MAGEMCP_ADMIN_TOKEN` (backward compatibility) |

## Project Structure

```
src/magemcp/
├── server.py               # FastMCP entry point — registers all tools
├── connectors/
│   ├── graphql_client.py   # GraphQLClient — storefront, no admin auth
│   ├── rest_client.py      # RESTClient — admin operations with Bearer token
│   ├── errors.py           # Shared exception hierarchy
│   └── magento.py          # Legacy unified client (backward compat)
├── tools/
│   ├── customer/           # c_* tools (GraphQL)
│   │   ├── cart.py
│   │   ├── get_categories.py
│   │   ├── get_product.py
│   │   ├── resolve_url.py
│   │   ├── search_products.py
│   │   └── store_config.py
│   └── admin/              # admin_* tools (REST)
│       ├── _confirmation.py
│       ├── cms.py
│       ├── get_customer.py
│       ├── get_inventory.py
│       ├── get_order.py
│       ├── order_actions.py
│       ├── products.py
│       ├── promotions.py
│       ├── search_customers.py
│       ├── search_orders.py
│       └── update_inventory.py
├── models/
│   ├── catalog.py
│   ├── customer.py
│   ├── inventory.py
│   ├── order.py
│   ├── product.py
│   └── customer_ns/
│       ├── cart.py
│       └── categories.py
└── policy/
    └── engine.py           # Rate limiting, audit logging, tool classification
```

## Testing

```bash
# Unit tests (no Magento needed — uses respx mocks)
pytest tests/ --ignore=tests/test_integration.py --ignore=tests/test_integration_order_actions.py

# Full suite including integration tests
MAGENTO_BASE_URL=https://magento.example.com \
MAGENTO_TOKEN=your-token \
pytest tests/ -v

# Integration tests only
pytest tests/test_integration.py tests/test_integration_order_actions.py -v
```

490 tests: unit tests with mocked HTTP, integration tests against real Magento (auto-skipped when not configured), and MCP-vs-raw-API comparison tests.

## Commercial Support

Need custom tools, enterprise integrations, or a tailored deployment for your Adobe Commerce store?

Contact [Magendoo](https://magendoo.ro) — [info@magendoo.ro](mailto:info@magendoo.ro)

## License

MIT
