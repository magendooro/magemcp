# Changelog

## v2 (current)

### Breaking changes from v1

- **Connector split**: `MagentoClient` is retained for backward compatibility but new code should use `RESTClient` (admin operations) or `GraphQLClient` (storefront queries) directly.
- **Admin token variable renamed**: `MAGENTO_TOKEN` → `MAGEMCP_ADMIN_TOKEN`. The old name still works as a fallback.
- **Tool namespace split**: All tools now use a `c_*` (customer) or `admin_*` (admin) prefix. The original flat tool names are removed.

### New in v2

#### Architecture

- Dual-namespace tool model: `c_*` tools use `GraphQLClient` (no admin auth), `admin_*` tools use `RESTClient` (admin Bearer token).
- `RESTClient` and `GraphQLClient` are independent async clients. `MagentoClient` wraps both for backward compatibility.
- Policy engine (`policy/engine.py`): rate limiting, structured audit logging, tool classification.
- Confirmation pattern on all write/destructive tools: first call returns a prompt, second call with `confirm=True` proceeds. `MAGEMCP_SKIP_CONFIRMATION=true` bypasses for pipelines.

#### New tools

**Customer namespace (`c_*`)**
- `c_get_categories` — category tree (3 levels, product counts)
- `c_resolve_url` — SEO URL resolver for products, categories, CMS pages
- `c_get_store_config` — store locale, currency, base URLs
- `c_create_cart`, `c_get_cart`, `c_add_to_cart`, `c_update_cart_item` — cart management
- `c_apply_coupon`, `c_set_guest_email` — checkout helpers
- `c_set_shipping_address`, `c_set_billing_address`, `c_set_shipping_method`, `c_set_payment_method` — checkout flow
- `c_place_order` — order placement

**Admin namespace (`admin_*`)**
- `admin_search_orders` — order search with filters (status, email, date range, total range)
- `admin_get_order` — enhanced: payment info, invoice/credit memo IDs, full status history
- `admin_search_customers` — customer search with wildcard email/name filters
- `admin_get_customer` — enhanced: all addresses, custom attributes, extension attributes (B2B)
- `admin_search_products`, `admin_get_product`, `admin_update_product` — full product management
- `admin_update_inventory` — MSI source item quantity update
- `admin_cancel_order`, `admin_hold_order`, `admin_unhold_order` — order state changes
- `admin_add_order_comment`, `admin_create_invoice`, `admin_create_shipment`, `admin_send_order_email` — order operations
- `admin_get_cms_page`, `admin_search_cms_pages`, `admin_update_cms_page` — CMS management
- `admin_search_sales_rules`, `admin_get_sales_rule`, `admin_generate_coupons` — promotions

#### Models

- `models/product.py` — `ProductSummary`, `ProductDetail`, `MediaGalleryEntry`, `StockItem`, `TierPrice`, `ProductOption`
- `models/customer.py` — `CustomerAddress`, `CustomerSummary` added
- `models/order.py` — `OrderSummary` added; `CGetOrderOutput` extended with payment/invoice/credit memo fields

#### Testing

- 490 tests (up from 7 at v1 launch)
- Integration tests auto-skip when Magento is not configured
- MCP-vs-raw-API comparison tests verify tool output matches direct API calls field-by-field

## v1

Initial proof-of-concept with 5 read-only tools:

- `c_search_products` — GraphQL catalog search
- `c_get_product` — GraphQL product detail
- `c_get_order` — REST order lookup (PII-redacted)
- `c_get_customer` — REST customer lookup (PII-redacted)
- `c_get_inventory` — REST salable quantity check
