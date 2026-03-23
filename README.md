# MageMCP

MCP (Model Context Protocol) server for Magento 2 / Adobe Commerce by [Magendoo](https://magendoo.ro). Connects AI agents to a Magento instance, enabling natural-language interaction with catalog, orders, customers, inventory, and carts.

MageMCP runs as a separate Python service — not embedded in Magento. It communicates with Magento via REST and GraphQL APIs and exposes MCP tools to any MCP-compatible client.

## Status

**v2.2** — 27 tools across dual namespaces, split REST/GraphQL clients, 394 tests passing against real Magento instances.

## Tools

MageMCP uses two namespaces reflecting different access contexts:

### `c_*` — Customer-Facing (GraphQL, no auth required by default)

These tools mimic a storefront user or shopper.

| Tool | Description |
|------|-------------|
| **Catalog & Navigation** | |
| `c_search_products` | Search storefront catalog with filters, pagination, sorting |
| `c_get_product` | Full product detail by SKU (images, categories, configurable options) |
| `c_get_categories` | Fetch category tree with children and product counts |
| `c_resolve_url` | Resolve SEO-friendly URLs to products, categories, or CMS pages |
| `c_get_store_config` | Get store configuration (locale, currency, base URLs) |
| **Cart & Checkout** | |
| `c_create_cart` | Create an empty guest cart |
| `c_get_cart` | Get full cart details (items, totals, addresses) |
| `c_add_to_cart` | Add a product to the cart by SKU |
| `c_update_cart_item` | Update item quantity or remove item |
| `c_apply_coupon` | Apply a discount coupon code |
| `c_set_guest_email` | Set email address for guest checkout |
| `c_set_shipping_address` | Set shipping address |
| `c_set_billing_address` | Set billing address |
| `c_set_shipping_method` | Select a shipping method |
| `c_set_payment_method` | Select a payment method |
| `c_place_order` | Place the order (returns order number) |

### `admin_*` — Admin Operations (REST, requires admin token)

These tools provide back-office capabilities.

| Tool | Description |
|------|-------------|
| **Read Operations** | |
| `admin_search_orders` | Search orders with filters (status, email, date range, total) |
| `admin_get_order` | Order lookup by increment ID — full customer details, addresses, tracking |
| `admin_get_customer` | Customer lookup by ID or email — full profile data |
| `admin_get_inventory` | Salable quantity and availability check for SKU(s) |
| **Write Operations** | |
| `admin_cancel_order` | Cancel an order (requires confirmation) |
| `admin_hold_order` | Put an order on hold (requires confirmation) |
| `admin_unhold_order` | Release an order from hold (requires confirmation) |
| `admin_add_order_comment` | Add a comment to order history |
| `admin_create_invoice` | Create an invoice (capture payment) |
| `admin_create_shipment` | Create a shipment (with optional tracking) |
| `admin_send_order_email` | Resend order confirmation email |

All tools enforce store scope and use typed Pydantic input/output schemas.

## Stack

- Python 3.11+
- FastMCP (official MCP Python SDK)
- httpx for async Magento API calls
- Pydantic v2 for validation and DTOs

## Quick Start

```bash
# Create venv and install
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Set required environment variables
export MAGENTO_BASE_URL=http://127.0.0.1:8082
export MAGEMCP_ADMIN_TOKEN=your-integration-token

# Run the server (stdio transport)
magemcp

# Run tests
pytest

# Run integration tests (requires running Magento instance)
pytest tests/test_integration.py -v
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `MAGENTO_BASE_URL` | Yes | Base URL of Magento instance |
| `MAGEMCP_ADMIN_TOKEN` | Yes (admin tools) | Integration/admin Bearer token for REST API |
| `MAGENTO_CUSTOMER_TOKEN` | No | Customer token for authenticated GraphQL queries |
| `MAGENTO_STORE_CODE` | No | Default store view code (default: `default`) |
| `MAGENTO_TOKEN` | No | Legacy alias for `MAGEMCP_ADMIN_TOKEN` (backward compat) |

## Architecture

```
src/magemcp/
├── server.py                  # MCP server entry point, dual-namespace registration
├── connectors/
│   ├── graphql_client.py      # GraphQLClient — storefront queries
│   ├── rest_client.py         # RESTClient — admin operations
│   ├── errors.py              # Shared exception hierarchy
│   └── magento.py             # Backward-compatible unified client wrapper
├── tools/
│   ├── customer/              # c_* tools (GraphQL)
│   │   ├── cart.py            # Cart management (create, add, checkout)
│   │   ├── get_categories.py  # Category tree
│   │   ├── get_product.py     # Product details
│   │   ├── resolve_url.py     # URL resolver
│   │   ├── search_products.py # Catalog search
│   │   └── store_config.py    # Store configuration
│   └── admin/                 # admin_* tools (REST)
│       ├── get_customer.py
│       ├── get_inventory.py
│       ├── get_order.py
│       └── search_orders.py
├── models/
│   ├── catalog.py             # Product, price, pagination DTOs
│   ├── order.py               # Order DTOs
│   ├── customer.py            # Customer DTOs
│   ├── inventory.py           # Inventory DTOs
│   └── customer_ns/           # GraphQL-specific DTOs
│       ├── cart.py
│       └── categories.py
└── policy/                    # Policy engine (stub)
```

### Why Two Clients?

| | GraphQLClient | RESTClient |
|---|---|---|
| **Auth** | None (guest) or customer token | Always admin Bearer token |
| **Used by** | `c_*` tools | `admin_*` tools |
| **Data scope** | Storefront-visible only | All data across all store views |
| **Audience** | Shopping assistants, self-service bots | Support reps, ops teams |

## Testing

Comprehensive test suite:

```bash
# Unit tests only (no Magento needed)
pytest tests/ --ignore=tests/test_integration.py

# Full suite with integration + comparison tests
MAGENTO_BASE_URL=http://127.0.0.1:8082 \
MAGENTO_TOKEN=your-token \
pytest tests/ -v
```

Test types:
- **Unit tests** — mocked HTTP via respx, test parsing, validation, error handling
- **Integration tests** — real Magento API calls, auto-skip when not configured
- **MCP vs raw API comparison tests** — fetch same data via tool and raw API, verify field-by-field match

## Customizations

Need custom tools, integrations, or a tailored deployment for your Magento store? Contact us at [Magendoo](https://magendoo.ro) — [info@magendoo.ro](mailto:info@magendoo.ro).

## License

MIT