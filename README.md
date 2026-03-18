# MageMCP

MCP (Model Context Protocol) server for Magento 2 / Adobe Commerce by [Magendoo](https://magendoo.ro). Connects AI agents to a Magento instance, enabling natural-language interaction with catalog, orders, customers, and inventory.

MageMCP runs as a separate Python service — not embedded in Magento. It communicates with Magento via REST and GraphQL APIs and exposes MCP tools to any MCP-compatible client.

## Status

**Phase 2 POC** — 5 read-only tools implemented and unit tested. Integration tests written and validated against a local Magento instance.

## Implemented Tools

| Tool | Domain | Magento API | Description |
|------|--------|-------------|-------------|
| `c_search_products` | Catalog | GraphQL | Search storefront catalog with filters, pagination, sorting |
| `c_get_product` | Catalog | GraphQL | Full product detail by SKU (images, categories, configurable options) |
| `c_get_order` | Orders | REST | Order lookup by increment ID with PII redaction |
| `c_get_customer` | Customers | REST | Customer lookup by ID or email with PII redaction |
| `c_get_inventory` | Inventory | REST | Salable quantity and availability check for SKU(s) |

All tools are read-only, enforce store scope, and use typed Pydantic input/output schemas. Order and customer tools redact PII by default (masked emails, initials, redacted addresses).

## Stack

- Python 3.11+
- FastMCP (official MCP Python SDK)
- FastAPI + Uvicorn
- httpx for async Magento API calls
- Pydantic v2 for validation and DTOs
- hatchling build system

## Quick Start

```bash
# Create venv and install
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Set required environment variables
export MAGENTO_BASE_URL=https://magento.example.com
export MAGENTO_TOKEN=your-integration-token

# Run the server (stdio transport)
magemcp

# Run tests
pytest

# Run integration tests (requires real Magento instance)
pytest tests/test_integration.py -v
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `MAGENTO_BASE_URL` | Yes | Base URL of Magento instance |
| `MAGENTO_TOKEN` | Yes | Integration/admin Bearer token |
| `MAGENTO_STORE_CODE` | No | Default store view code (default: `default`) |

## Project Structure

```
src/magemcp/
├── server.py              # MCP server entry point (FastMCP, tool registration)
├── connectors/
│   └── magento.py         # Async HTTP client (REST + GraphQL), error handling, searchCriteria builder
├── tools/
│   ├── search_products.py # c_search_products (GraphQL)
│   ├── get_product.py     # c_get_product (GraphQL)
│   ├── get_order.py       # c_get_order (REST, PII redaction)
│   ├── get_customer.py    # c_get_customer (REST, PII redaction)
│   └── get_inventory.py   # c_get_inventory (REST)
├── models/
│   ├── catalog.py         # Product, price, pagination DTOs
│   ├── order.py           # Order DTOs, PII masking helpers
│   ├── customer.py        # Customer DTOs
│   └── inventory.py       # Inventory DTOs
└── policy/                # Policy engine (stub — not yet implemented)

tests/
├── test_server.py         # Server smoke test
├── test_connector.py      # Connector unit tests
├── test_search_products.py
├── test_get_product.py
├── test_get_order.py
├── test_get_customer.py
├── test_get_inventory.py
└── test_integration.py    # Integration tests (real Magento, auto-skips)
```

## Customizations

Need custom tools, integrations, or a tailored deployment for your Magento store? Contact us at [Magendoo](https://magendoo.ro) — [info@magendoo.ro](mailto:info@magendoo.ro).

## License

MIT
