# MageMCP

MCP (Model Context Protocol) server for Magento 2 / Adobe Commerce by [Magendoo](https://magendoo.ro). Connects AI agents to a Magento instance, enabling natural-language interaction with catalog, orders, customers, and inventory.

MageMCP runs as a separate Python service — not embedded in Magento. It communicates with Magento via REST and GraphQL APIs and exposes MCP tools to any MCP-compatible client.

## Status

**v2** — 5 read-only tools across dual namespaces, split REST/GraphQL clients, 274 tests passing against a real Magento instance.

## Tools

MageMCP uses two namespaces reflecting different access contexts:

### `c_*` — Customer-Facing (GraphQL, no auth required)

| Tool | Description |
|------|-------------|
| `c_search_products` | Search storefront catalog with filters, pagination, sorting |
| `c_get_product` | Full product detail by SKU (images, categories, configurable options) |

### `admin_*` — Admin Operations (REST, requires admin token)

| Tool | Description |
|------|-------------|
| `admin_get_order` | Order lookup by increment ID — full customer details, addresses, tracking |
| `admin_get_customer` | Customer lookup by ID or email — full profile data |
| `admin_get_inventory` | Salable quantity and availability check for SKU(s) |

All tools are read-only, enforce store scope, and use typed Pydantic input/output schemas.

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
│   ├── graphql_client.py      # GraphQLClient — storefront queries, no auth by default
│   ├── rest_client.py         # RESTClient — admin operations, requires Bearer token
│   ├── errors.py              # Shared exception hierarchy
│   └── magento.py             # Backward-compatible unified client wrapper
├── tools/
│   ├── customer/              # c_* tools (GraphQL)
│   │   ├── search_products.py
│   │   └── get_product.py
│   └── admin/                 # admin_* tools (REST)
│       ├── get_order.py
│       ├── get_customer.py
│       └── get_inventory.py
├── models/
│   ├── catalog.py             # Product, price, pagination DTOs
│   ├── order.py               # Order DTOs, PII masking helpers
│   ├── customer.py            # Customer DTOs
│   └── inventory.py           # Inventory DTOs
└── policy/                    # Policy engine (stub — not yet implemented)
```

### Why Two Clients?

| | GraphQLClient | RESTClient |
|---|---|---|
| **Auth** | None (guest) or customer token | Always admin Bearer token |
| **Used by** | `c_*` tools | `admin_*` tools |
| **Data scope** | Storefront-visible only | All data across all store views |
| **Audience** | Shopping assistants, self-service bots | Support reps, ops teams |

## Testing

274 tests across 10 test files:

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
