# MageMCP — Feature Inventory

Last updated: 2026-03-23

## Implemented Tools

### Customer-Facing (`c_*`) — GraphQL, no auth required

| Tool | Magento API | Input Parameters | Output Type |
|------|-------------|------------------|-------------|
| `c_search_products` | GraphQL `products` query | search, category_id, price_from, price_to, in_stock_only, store_scope, page_size, current_page, sort_field, sort_direction | `CSearchProductsOutput` (products list + pagination) |
| `c_get_product` | GraphQL product detail | sku, store_scope | `CGetProductOutput` (full detail with images, categories, configurable options) |

### Admin (`admin_*`) — REST, requires admin token

| Tool | Magento API | Input Parameters | Output Type |
|------|-------------|------------------|-------------|
| `admin_get_order` | REST `GET /V1/orders` | increment_id, store_scope | `CGetOrderOutput` (status, totals, items, addresses, shipments, history — full PII) |
| `admin_get_customer` | REST `GET /V1/customers/{id}` or `/V1/customers/search` | customer_id or email (+website_id), store_scope | `CGetCustomerOutput` (group, dates, full profile) |
| `admin_get_inventory` | REST `GET /V1/inventory/get-product-salable-quantity` + `is-product-salable` | skus (list), stock_id, store_scope | `CGetInventoryOutput` (per-SKU salable qty + is_salable) |

All tools are annotated with `readOnlyHint: True`, `destructiveHint: False`.

Admin tools always return full data — no PII masking. PII masking helpers (`mask_email`, `mask_phone`, `mask_name`, `mask_street`) remain in `models/order.py` for future customer-facing tools.

## Connector Architecture

### `GraphQLClient` (`connectors/graphql_client.py`)

| Capability | Details |
|------------|---------|
| Query execution | `client.query(query, variables, store_code)` with Store header |
| Auth | None by default (guest browsing); optional `customer_token` for authenticated queries |
| Factory | `GraphQLClient.from_env()` reads `MAGENTO_BASE_URL`, `MAGENTO_CUSTOMER_TOKEN` (optional), `MAGENTO_STORE_CODE` |
| Context manager | `async with GraphQLClient.from_env() as client:` |

### `RESTClient` (`connectors/rest_client.py`)

| Capability | Details |
|------------|---------|
| HTTP methods | `get`, `post`, `put`, `delete` — all with store_code scoping |
| searchCriteria builder | `RESTClient.search_params(filters, page_size, current_page, sort_field, sort_direction)` |
| Auth | Always sends `Authorization: Bearer <admin_token>` |
| Factory | `RESTClient.from_env()` reads `MAGENTO_BASE_URL`, `MAGEMCP_ADMIN_TOKEN` (falls back to `MAGENTO_TOKEN`), `MAGENTO_STORE_CODE` |
| Context manager | `async with RESTClient.from_env() as client:` |

### Shared Error Hierarchy (`connectors/errors.py`)

| Exception | HTTP Status |
|-----------|-------------|
| `MagentoAuthError` | 401, 403 |
| `MagentoNotFoundError` | 404 |
| `MagentoValidationError` | 400 |
| `MagentoRateLimitError` | 429 |
| `MagentoServerError` | 5xx |

Error message parsing extracts Magento's `%1`-style parameter substitution from error responses.

### `MagentoClient` (`connectors/magento.py`) — Backward Compat

Unified client that wraps both REST and GraphQL. Used by integration tests and legacy code. Delegates `search_params` to `RESTClient`. New code should use `GraphQLClient` or `RESTClient` directly.

## Model/DTO Inventory

### Catalog (`models/catalog.py`)

| Model | Purpose |
|-------|---------|
| `CSearchProductsInput` | Search input with validation (search max 200 chars, page_size 1-50, sort enum, store_scope pattern) |
| `CSearchProductsOutput` | Paginated product list |
| `StorefrontProduct` | Product summary (sku, name, url_key, type, stock_status, prices, image, short_description) |
| `CGetProductInput` | Product detail input (sku max 64 chars, store_scope) |
| `CGetProductOutput` | Full product detail (descriptions, meta, images, categories with breadcrumbs, configurable options) |
| `ProductPrice` | Regular + final price with discount amounts |
| `PriceAmount` | Decimal value + currency code |
| `PageInfo` | Pagination metadata |
| `MediaGalleryEntry` | Product image (url, label, position) |
| `CategoryBreadcrumb` | Category with full path (e.g., "Women > Tops > Jackets") |
| `CustomAttribute` | Configurable option (attribute_code, label, values) |

Helper: `strip_html()` — removes HTML tags from product descriptions.

### Order (`models/order.py`)

| Model | Purpose |
|-------|---------|
| `CGetOrderInput` | Order lookup input (increment_id max 32 chars, store_scope, pii_mode literal) |
| `CGetOrderOutput` | Order view (increment_id, state, status, totals, items, addresses, shipments, last 3 history entries) |
| `OrderAddress` | Billing/shipping address |
| `OrderItem` | Line item (sku, name, qty, price, row_total) |
| `ShipmentSummary` | Shipment with tracking numbers |
| `ShipmentTrack` | Tracking number + carrier |
| `StatusHistoryEntry` | Status comment with visibility flags |
| `PiiMode` | Enum: redacted, full |

PII masking helpers: `mask_email()`, `mask_phone()`, `mask_name()`, `mask_street()` — available for future customer-facing tools.

### Customer (`models/customer.py`)

| Model | Purpose |
|-------|---------|
| `CGetCustomerInput` | Customer lookup input (customer_id or email required, website_id, store_scope, pii_mode) |
| `CGetCustomerOutput` | Customer profile (id, group, dates, name, email, dob, gender) |

Validation: model_validator ensures at least one of customer_id or email is provided.

### Inventory (`models/inventory.py`)

| Model | Purpose |
|-------|---------|
| `CGetInventoryInput` | Inventory check input (skus list 1-50, stock_id > 0, store_scope) |
| `CGetInventoryOutput` | Inventory results for multiple SKUs |
| `SkuInventory` | Per-SKU result (salable_quantity, is_salable, error) |

## Test Coverage

| Test File | What It Tests | Tests |
|-----------|---------------|-------|
| `test_server.py` | Server smoke test (MCP instance exists, correct name) | 1 |
| `test_connector.py` | Legacy MagentoClient: construction, URL building, REST GET/POST/PUT, GraphQL, error handling, searchCriteria builder, context manager | ~34 |
| `test_graphql_client.py` | GraphQLClient: construction, no-auth guest mode, customer token auth, from_env, Store header, variables, GraphQL errors, context manager | ~14 |
| `test_rest_client.py` | RESTClient: construction, auth header, from_env (+ fallback + missing), URL building, GET/POST/PUT/DELETE, error handling (401/404/400/429/500), searchCriteria, context manager | ~30 |
| `test_search_products.py` | strip_html, input validation, variable building (+ empty search fallback), product parsing, response parsing, e2e with mocked GraphQL, serialization | ~31 |
| `test_get_product.py` | Input validation, media gallery, category breadcrumbs, configurable options, product detail parsing, e2e with mocked GraphQL, serialization | ~25 |
| `test_get_order.py` | PII masking helpers, input validation, address parsing (full only), item parsing, shipment parsing, status history, full order parsing, admin full PII assertions, e2e with mocked REST, serialization | ~33 |
| `test_get_customer.py` | Input validation, customer parsing (full only), admin full data assertions, e2e with mocked REST, serialization | ~17 |
| `test_get_inventory.py` | Input validation, model tests, e2e with mocked REST, serialization | ~15 |
| `test_integration.py` | Real Magento: connector smoke, product search/pagination, product detail, order lookup, customer by ID/email, inventory, tool invocations, cross-tool scenarios, **MCP vs raw API comparisons** (5 tests) | ~30 |

**Total: 274 tests** (244 unit + 30 integration)

Test patterns:
- `respx` for HTTP mocking (no real network calls in unit tests)
- `pytest-asyncio` with `asyncio_mode = "auto"`
- Factory functions for realistic test fixtures
- MCP vs raw API comparison tests verify field-by-field accuracy

## Known Limitations

- **No policy engine**: authorization rules, role scopes, and tenant boundaries are not enforced
- **No rate limiting**: server-side per-tool rate limits are not enforced
- **No audit logging**: tool invocations are not logged for compliance
- **stdio transport only**: no HTTP transport, no session management, no Origin validation
- **Sequential inventory calls**: `admin_get_inventory` makes 2 REST calls per SKU sequentially — could be parallelized
- **No write tools**: all tools are read-only; guarded-write operations require policy engine first
- **Client-per-call**: each tool invocation creates a new client via `from_env()` — no connection pooling across calls

## Planned Features

### Phase 3: Pilot — Guarded Writes
- Policy engine (authorization, audit logging, rate limiting)
- `update_order_note` tool (idempotency key required)
- `create_ticket` tool (adapter pattern for ticketing providers)
- `add_ticket_comment` tool

### Phase 4: Production Hardening
- HTTP transport (Streamable HTTP with session management)
- Additional read-only tools (search_orders, get_order_tracking, get_category_tree, get_store_config)
- Connection pooling / shared client lifecycle
- Custom Magento module for safe agent write endpoints
- Docker deployment
