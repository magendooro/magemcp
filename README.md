# MageMCP

MCP (Model Context Protocol) server for Magento 2 / Adobe Commerce by [Magendoo](https://magendoo.ro).

Connects AI agents to a live Magento instance via REST and GraphQL APIs — 60 typed tools across catalog, cart, orders, customers, inventory, CMS, promotions, reviews, analytics, and more.

| | |
|---|---|
| **Deployment** | [docs/deployment.md](docs/deployment.md) — installation, Docker, SSH, HTTP, reverse proxy |
| **Usage scenarios** | [docs/scenarios.md](docs/scenarios.md) — example agent conversations by domain |

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

### `c_*` — Customer-Facing Tools (18)

#### Catalog & Navigation

| Tool | Description |
|------|-------------|
| `c_search_products` | Search storefront catalog — text query, category/price filters, sorting, in-stock filter |
| `c_get_product` | Full product detail by SKU — images, categories, configurable options, descriptions |
| `c_get_categories` | Category tree with children and product counts (3 levels deep) |
| `c_resolve_url` | Resolve a SEO URL to product, category, or CMS page |
| `c_get_store_config` | Store locale, currency, and base URLs |
| `c_get_policy_page` | Fetch a CMS page by URL identifier — returns, shipping, privacy, etc. |

#### Cart & Checkout

| Tool | Description |
|------|-------------|
| `c_create_cart` | Create an empty guest cart, returns `cart_id` |
| `c_get_cart` | Full cart — items, applied coupons, addresses, totals |
| `c_add_to_cart` | Add product by SKU and quantity |
| `c_update_cart_item` | Update item quantity or remove item |
| `c_apply_coupon` | Apply a discount coupon code |
| `c_set_guest_email` | Set email for guest checkout |
| `c_set_shipping_address` | Set shipping address — returns available shipping methods |
| `c_set_billing_address` | Set billing address |
| `c_set_shipping_method` | Select a shipping method |
| `c_set_payment_method` | Select a payment method |
| `c_place_order` | Place the order — returns order number |

#### Returns

| Tool | Description |
|------|-------------|
| `c_initiate_return` | Initiate an RMA return request via GraphQL *(requires confirmation; Adobe Commerce only)* |

---

### `admin_*` — Admin Tools (42)

#### Orders — Read

| Tool | Description |
|------|-------------|
| `admin_search_orders` | Search orders — status, email, date range, total range, customer ID |
| `admin_get_order` | Full order by increment ID — payment, invoices, shipments, credit memos, full status history |
| `admin_get_order_tracking` | All shipment tracking numbers for an order |
| `admin_get_customer_orders` | Order history for a specific customer by ID or email |

#### Orders — Write

| Tool | Description |
|------|-------------|
| `admin_cancel_order` | Cancel an order *(requires confirmation)* |
| `admin_hold_order` | Put order on hold *(requires confirmation)* |
| `admin_unhold_order` | Release order from hold *(requires confirmation)* |
| `admin_add_order_comment` | Add internal or customer-visible comment with optional status update |
| `admin_create_invoice` | Create invoice and optionally capture payment *(requires confirmation)* |
| `admin_create_shipment` | Create shipment with optional tracking numbers *(requires confirmation)* |
| `admin_send_order_email` | Resend order confirmation email *(requires confirmation)* |

#### Invoices, Shipments & Credit Memos

| Tool | Description |
|------|-------------|
| `admin_search_invoices` | Search invoices by order ID or state |
| `admin_get_invoice` | Full invoice detail by entity ID |
| `admin_search_shipments` | Search shipments by order ID |
| `admin_get_shipment` | Full shipment detail — items, tracking numbers, comments |
| `admin_get_credit_memo` | Full credit memo (refund document) detail |

#### Customers

| Tool | Description |
|------|-------------|
| `admin_search_customers` | Search by email, name, group, or registration date — full unmasked data |
| `admin_get_customer` | Full profile — addresses, custom attributes, B2B extension attributes |
| `admin_get_customer_groups` | List all customer groups with integer IDs — use before filtering by group |

#### Products

| Tool | Description |
|------|-------------|
| `admin_search_products` | Search by name, SKU, type, status, visibility, or price range |
| `admin_get_product` | Full product — all EAV attributes, media gallery, stock, tier prices, options |
| `admin_update_product` | Partial attribute update — named fields or any EAV attribute via `attributes={}` *(requires confirmation)* |
| `admin_get_product_attribute` | Get attribute definition and option list — required before updating select/swatch attributes by label |

#### Inventory

| Tool | Description |
|------|-------------|
| `admin_get_inventory` | Salable quantity and availability for one or more SKUs |
| `admin_update_inventory` | Update MSI source item quantity *(requires confirmation)* |

#### Returns (Admin)

| Tool | Description |
|------|-------------|
| `admin_search_returns` | Search RMA return requests by order, status, or customer |
| `admin_get_return` | Full return detail — items, resolution, tracking |

#### Quotes (Carts)

| Tool | Description |
|------|-------------|
| `admin_search_quotes` | Search active and abandoned shopping carts |

#### CMS

| Tool | Description |
|------|-------------|
| `admin_search_cms_pages` | Search CMS pages by title, identifier, or active status |
| `admin_get_cms_page` | Full page by numeric ID or URL identifier — title, content, meta fields |
| `admin_update_cms_page` | Update title, content, active status, or meta fields *(requires confirmation)* |

#### Promotions

| Tool | Description |
|------|-------------|
| `admin_search_sales_rules` | Search cart price rules by name or active status |
| `admin_get_sales_rule` | Full rule — conditions, actions, discount config, usage stats, applicable customer groups |
| `admin_generate_coupons` | Generate coupon codes for a cart price rule *(requires confirmation)* |

#### Reviews

| Tool | Description |
|------|-------------|
| `admin_get_product_reviews` | Customer reviews for a product by SKU |
| `admin_get_review` | Single review detail by review ID |
| `admin_moderate_review` | Approve, reject, or reset a review to pending *(requires confirmation)* |

#### Analytics

| Tool | Description |
|------|-------------|
| `admin_get_analytics` | Aggregate order metrics — revenue, order count, AOV — for a date range |

#### Store

| Tool | Description |
|------|-------------|
| `admin_get_store_hierarchy` | Full Magento store hierarchy: websites → store groups → store views |

#### Bulk Operations

| Tool | Description |
|------|-------------|
| `admin_bulk_catalog_update` | Update multiple products in a single async bulk operation |
| `admin_bulk_inventory_update` | Update inventory for multiple SKUs in one async bulk operation |
| `admin_get_bulk_status` | Check the status of a bulk operation by `bulk_uuid` |

---

> **Confirmation pattern** — Write tools require `confirm=True` on the second call. The first call returns a description of what will happen. Set `MAGEMCP_SKIP_CONFIRMATION=true` to bypass in automated pipelines.

> **EAV attribute resolution** — `admin_update_product` automatically resolves human labels to option IDs for `select`, `multiselect`, `swatch_visual`, and `swatch_text` attributes. Pass `"Red"` and the correct option ID is looked up. Use `admin_get_product_attribute` to inspect available options first.

> **Customer group lookup** — Customer groups are referenced by integer ID. Use `admin_get_customer_groups` to map a group name like "Wholesale" to its ID before filtering customers or interpreting sales rule `customer_group_ids`.

## Quick Start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

export MAGENTO_BASE_URL=https://magento.example.com
export MAGEMCP_ADMIN_TOKEN=your-integration-token

magemcp          # MCP server on stdio (default)
```

See [docs/deployment.md](docs/deployment.md) for Docker, SSH, and HTTP transport options.

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `MAGENTO_BASE_URL` | Yes | Base URL of the Magento instance (e.g. `https://magento.example.com`) |
| `MAGEMCP_ADMIN_TOKEN` | Yes* | Integration/admin Bearer token — grants access to all `admin_*` tools |
| `MAGENTO_STORE_CODE` | No | Default store view code (default: `default`) |
| `MAGENTO_CUSTOMER_TOKEN` | No | Customer Bearer token for authenticated `c_*` queries |
| `MAGENTO_VERIFY_SSL` | No | SSL verification: `true` (default), `false`, or path to CA bundle |
| `MAGEMCP_LOG_LEVEL` | No | Log verbosity: `DEBUG`, `INFO`, `WARNING` (default: `INFO`) |
| `MAGEMCP_SKIP_CONFIRMATION` | No | Set to `true` to bypass confirmation prompts on write tools |
| `MAGEMCP_AUDIT_LOG_FILE` | No | Append-only audit log file path — one JSON entry per tool invocation |
| `MAGEMCP_AUDIT_BEFORE_STATE` | No | Set to `true` to capture before-state on product updates (extra GET call) |
| `MAGEMCP_TRANSPORT` | No | `stdio` (default) or `streamable-http` |
| `MAGEMCP_HOST` | No | HTTP bind address (default: `127.0.0.1`) — HTTP transport only |
| `MAGEMCP_PORT` | No | HTTP bind port (default: `8000`) — HTTP transport only |
| `MAGENTO_TOKEN` | No | Legacy alias for `MAGEMCP_ADMIN_TOKEN` |

*`MAGEMCP_ADMIN_TOKEN` is required for `admin_*` tools. `c_*` tools work without it (GraphQL, public catalog).

## HTTP Endpoints (HTTP transport only)

When running with `MAGEMCP_TRANSPORT=streamable-http`:

| Endpoint | Description |
|----------|-------------|
| `POST /mcp` | MCP protocol endpoint |
| `GET /health` | Server health — status, tool count, uptime |
| `GET /metrics` | Tool invocation counts per tool |
| `GET /audit` | Recent audit log entries (`?limit=50&tool=admin_update_product&class=write`) |

## Project Structure

```
src/magemcp/
├── server.py               # FastMCP entry point — registers all 60 tools
├── audit_context.py        # ContextVar for audit log propagation
├── connectors/
│   ├── graphql_client.py   # GraphQLClient — storefront, no admin auth
│   ├── rest_client.py      # RESTClient — admin operations with Bearer token
│   └── errors.py           # Typed exception hierarchy
├── tools/
│   ├── customer/           # c_* tools (GraphQL)
│   └── admin/              # admin_* tools (REST)
├── models/                 # Pydantic DTOs
├── policy/
│   └── engine.py           # Rate limiting, audit buffer, tool classification
└── health.py               # Health check data
```

## Testing

```bash
# Unit tests (no Magento needed — uses respx mocks)
pytest tests/ -q

# Integration tests against a real Magento instance
MAGENTO_BASE_URL=https://magento.example.com \
MAGEMCP_ADMIN_TOKEN=your-token \
pytest tests/test_integration.py -v
```

895 tests: unit tests with mocked HTTP, integration tests against real Magento (auto-skipped when not configured).

## Commercial Support

Need custom tools, enterprise integrations, or a tailored deployment for your Adobe Commerce store?

Contact [Magendoo](https://magendoo.ro) — [info@magendoo.ro](mailto:info@magendoo.ro)

## License

MIT
