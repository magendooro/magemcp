# MageMCP — Feature Inventory

Last updated: 2026-03-18

## Implemented Tools

| Tool | Domain | Magento API | Input Parameters | Output Type | PII Handling |
|------|--------|-------------|------------------|-------------|--------------|
| `c_search_products` | Catalog | GraphQL `products` query | search, category_id, price_from, price_to, in_stock_only, store_scope, page_size, current_page, sort_field, sort_direction | `CSearchProductsOutput` (products list + pagination) | None (storefront data only) |
| `c_get_product` | Catalog | GraphQL product detail | sku, store_scope | `CGetProductOutput` (full detail with images, categories, configurable options) | None (storefront data only) |
| `c_get_order` | Orders | REST `GET /V1/orders` | increment_id, store_scope, pii_mode | `CGetOrderOutput` (status, totals, items, addresses, shipments, history) | Default redacted: masked email/phone/name, street `[REDACTED]`, last 3 comments only |
| `c_get_customer` | Customers | REST `GET /V1/customers/{id}` or `/V1/customers/search` | customer_id or email (+website_id), store_scope, pii_mode | `CGetCustomerOutput` (group, dates, profile) | Default redacted: masked email, initials, masked DOB |
| `c_get_inventory` | Inventory | REST `GET /V1/inventory/get-product-salable-quantity` + `is-product-salable` | skus (list), stock_id, store_scope | `CGetInventoryOutput` (per-SKU salable qty + is_salable) | None |

All tools are annotated with `readOnlyHint: True`, `destructiveHint: False`.

## Connector Capabilities

**`MagentoClient`** (`src/magemcp/connectors/magento.py`):

| Capability | Details |
|------------|---------|
| REST GET | `client.get(endpoint, params, store_code)` |
| REST POST | `client.post(endpoint, json, store_code)` |
| REST PUT | `client.put(endpoint, json, store_code)` |
| GraphQL | `client.graphql(query, variables, store_code)` with Store header |
| searchCriteria builder | `MagentoClient.search_params(filters, page_size, current_page, sort_field, sort_direction)` |
| Error handling | Typed exceptions: `MagentoAuthError` (401/403), `MagentoNotFoundError` (404), `MagentoValidationError` (400), `MagentoRateLimitError` (429), `MagentoServerError` (5xx) |
| Error message parsing | Extracts Magento's `%1`-style parameter substitution from error responses |
| Configuration | `MagentoConfig` via pydantic-settings (env vars: `MAGENTO_BASE_URL`, `MAGENTO_TOKEN`, `MAGENTO_STORE_CODE`) |
| Context manager | Async `async with MagentoClient(...) as client:` with proper cleanup |
| External client injection | Accepts optional `httpx.AsyncClient` for testing |

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
| `CGetOrderOutput` | Order support view (increment_id, state, status, totals, items, addresses, shipments, last 3 history entries) |
| `OrderAddress` | Billing/shipping address (may be redacted) |
| `OrderItem` | Line item (sku, name, qty, price, row_total) |
| `ShipmentSummary` | Shipment with tracking numbers |
| `ShipmentTrack` | Tracking number + carrier |
| `StatusHistoryEntry` | Status comment with visibility flags |
| `PiiMode` | Enum: redacted, full |

PII masking helpers: `mask_email()`, `mask_phone()`, `mask_name()`, `mask_street()`.

### Customer (`models/customer.py`)

| Model | Purpose |
|-------|---------|
| `CGetCustomerInput` | Customer lookup input (customer_id or email required, website_id, store_scope, pii_mode) |
| `CGetCustomerOutput` | Customer support view (id, group, dates, masked PII fields) |

Validation: model_validator ensures at least one of customer_id or email is provided.

### Inventory (`models/inventory.py`)

| Model | Purpose |
|-------|---------|
| `CGetInventoryInput` | Inventory check input (skus list 1-50, stock_id > 0, store_scope) |
| `CGetInventoryOutput` | Inventory results for multiple SKUs |
| `SkuInventory` | Per-SKU result (salable_quantity, is_salable, error) |

## Test Coverage

| Test File | What It Tests | Test Count (approx) |
|-----------|---------------|---------------------|
| `test_server.py` | Server smoke test (MCP instance exists, correct name) | 1 |
| `test_connector.py` | Client construction, URL building, REST GET/POST/PUT, GraphQL, error handling (401/403/404/400/429/500/502), searchCriteria builder, context manager | ~25 |
| `test_search_products.py` | strip_html, input validation (defaults/limits/enums), variable building, product parsing (prices/discounts/images/stock), response parsing (pagination/in_stock_only), e2e with mocked GraphQL, serialization | ~30 |
| `test_get_product.py` | Input validation, media gallery (sorting/disabled filtering), category breadcrumbs, configurable options, product detail parsing, e2e with mocked GraphQL, serialization | ~25 |
| `test_get_order.py` | PII masking (email/phone/name/street), input validation, address parsing (redacted/full), item parsing (child skipping), shipment parsing, status history (limit 3), shipping method extraction, full order parsing (redacted/full), e2e with mocked REST, serialization | ~35 |
| `test_get_customer.py` | Input validation (id/email/both/neither), customer parsing (redacted/full), e2e with mocked REST (by ID/by email/store scope/not found/full PII), serialization | ~20 |
| `test_get_inventory.py` | Input validation (skus list/stock_id/store_scope), model tests, e2e with mocked REST (in stock/out of stock/store scope/custom stock/not found/multiple SKUs), serialization | ~15 |
| `test_integration.py` | Real Magento: connector smoke (REST/GraphQL), product search/pagination, product detail, order lookup/structure, customer by ID/email/not found, inventory salable/is_salable, full tool invocations, cross-tool scenarios | ~20 |

Test patterns used:
- `respx` for HTTP mocking (no real network calls in unit tests)
- `pytest-asyncio` with `asyncio_mode = "auto"` for async tests
- Factory functions (`_make_gql_product()`, `_make_rest_order()`, etc.) for realistic test fixtures
- Separate test classes for: input validation, parsing logic, e2e tool invocation, output serialization

## Known Limitations

- **No policy engine**: PII mode `full` is not gated by authorization — any caller can request full PII
- **No rate limiting**: server-side rate limits are not enforced
- **No audit logging**: tool invocations are not logged for compliance
- **stdio transport only**: no HTTP transport, no session management, no Origin validation
- **Sequential inventory calls**: `c_get_inventory` makes 2 REST calls per SKU sequentially (salable qty + is_salable) — could be parallelized
- **No admin namespace**: all tools use `c_` prefix; admin-level tools (`admin_*`) not yet implemented
- **No write tools**: all tools are read-only; guarded-write operations require policy engine first
- **Client-per-call**: each tool invocation creates a new `MagentoClient` via `from_config()` — no connection pooling across calls

## Planned Features by Phase

### Phase 3: Pilot — Guarded Writes
- Policy engine (authorization, audit logging, rate limiting)
- `update_order_note` tool (idempotency key required)
- `create_ticket` tool (adapter pattern for ticketing providers)
- `add_ticket_comment` tool

### Phase 4: Production Hardening
- Docker deployment (Dockerfile, docker-compose, .env.example)
- HTTP transport (Streamable HTTP with session management)
- Additional read-only tools (search_orders, get_order_tracking, get_category_tree, get_store_config)
- Connection pooling / shared client lifecycle
- Custom Magento module for safe agent write endpoints
