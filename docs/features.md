# MageMCP — Feature Inventory

Last updated: 2026-03-23

## Implemented Tools

### Customer-Facing (`c_*`) — GraphQL, no auth required by default

These tools mimic a storefront user or shopper.

| Tool | Description | Input Parameters | Output Type |
|------|-------------|------------------|-------------|
| **Catalog & Navigation** | | | |
| `c_search_products` | Search storefront catalog | search, category_id, price_from, price_to, in_stock_only, store_scope, page_size, current_page, sort_field, sort_direction | `CSearchProductsOutput` (products list + pagination) |
| `c_get_product` | Full product detail | sku, url_key, store_scope | `CGetProductOutput` (full detail with images, categories, configurable options) |
| `c_get_categories` | Fetch category tree | parent_id, name, include_in_menu, store_scope | `CGetCategoriesOutput` (nested categories with product counts) |
| `c_resolve_url` | Resolve SEO-friendly URLs | url, store_scope | `dict` (type, sku/uid, etc.) |
| `c_get_store_config` | Get store configuration | store_scope | `dict` (locale, currency, base URLs) |
| **Cart & Checkout** | | | |
| `c_create_cart` | Create an empty guest cart | store_scope | `dict` (cart_id) |
| `c_get_cart` | Get full cart details | cart_id, store_scope | `Cart` (items, totals, addresses) |
| `c_add_to_cart` | Add a product to the cart | cart_id, sku, quantity, store_scope | `Cart` |
| `c_update_cart_item` | Update item quantity | cart_id, cart_item_uid, quantity, store_scope | `Cart` |
| `c_apply_coupon` | Apply a discount coupon | cart_id, coupon_code, store_scope | `Cart` |
| `c_set_guest_email` | Set guest email | cart_id, email, store_scope | `dict` (email) |
| `c_set_shipping_address` | Set shipping address | cart_id, firstname, lastname, street, city, region, postcode, country_code, telephone, store_scope | `dict` (shipping_addresses) |
| `c_set_billing_address` | Set billing address | cart_id, firstname, lastname, street, city, region, postcode, country_code, telephone, store_scope | `dict` (billing_address) |
| `c_set_shipping_method` | Set shipping method | cart_id, carrier_code, method_code, store_scope | `dict` (shipping_addresses) |
| `c_set_payment_method` | Set payment method | cart_id, payment_method_code, store_scope | `dict` (selected_payment_method) |
| `c_place_order` | Place the order | cart_id, store_scope | `PlaceOrderResult` (order_number) |

### Admin (`admin_*`) — REST, requires admin token

These tools provide back-office capabilities.

| Tool | Magento API | Input Parameters | Output Type |
|------|-------------|------------------|-------------|
| `admin_search_orders` | REST `GET /V1/orders` | status, customer_email, created_from, created_to, grand_total_min/max, page_size, current_page | `dict` (orders list, total_count) |
| `admin_get_order` | REST `GET /V1/orders` | increment_id, store_scope | `CGetOrderOutput` (status, totals, items, addresses, shipments, history — full PII) |
| `admin_get_customer` | REST `GET /V1/customers/{id}` or `/V1/customers/search` | customer_id or email (+website_id), store_scope | `CGetCustomerOutput` (group, dates, full profile) |
| `admin_get_inventory` | REST `GET /V1/inventory/get-product-salable-quantity` + `is-product-salable` | skus (list), stock_id, store_scope | `CGetInventoryOutput` (per-SKU salable qty + is_salable) |
| `admin_cancel_order` | REST `POST /V1/orders/{id}/cancel` | order_id, confirm | `dict` (success, action) |
| `admin_hold_order` | REST `POST /V1/orders/{id}/hold` | order_id, confirm | `dict` (success, action) |
| `admin_unhold_order` | REST `POST /V1/orders/{id}/unhold` | order_id, confirm | `dict` (success, action) |
| `admin_add_order_comment` | REST `POST /V1/orders/{id}/comments` | order_id, comment, status, is_visible_on_front, is_customer_notified | `dict` (success, comment) |
| `admin_create_invoice` | REST `POST /V1/order/{id}/invoice` | order_id, capture, notify_customer | `dict` (success, invoice_id) |
| `admin_create_shipment` | REST `POST /V1/order/{id}/ship` | order_id, tracking_number, carrier_code, title, notify_customer | `dict` (success, shipment_id) |
| `admin_send_order_email` | REST `POST /V1/orders/{id}/emails` | order_id | `dict` (success, action) |

All tools are annotated with `readOnlyHint` (except cart tools and admin write operations which are `readOnlyHint: False` and potentially `destructiveHint: True`).

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

## Test Coverage



**Total: 394 tests**



Test types:

- **Unit tests** — mocked HTTP via respx, test parsing, validation, error handling

- **Integration tests** — real Magento API calls, auto-skip when not configured

- **MCP vs raw API comparison tests** — fetch same data via tool and raw API, verify field-by-field match



| Test File | Description |

|-----------|-------------|

| ... | ... |

| `test_order_actions.py` | Admin order write operations (cancel, hold, comment, invoice, ship) with confirmation logic tests |
