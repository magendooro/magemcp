# Usage Scenarios

Real examples of what an AI agent can do once MageMCP is connected. Each scenario shows the natural language request, the tools called, and notes on how multi-step flows work.

## Quick Lookups — Single Tool Calls

These questions each resolve to a single tool call and return an answer immediately.

---

**"How many simple products do I have in Magento?"**

*Tool: `admin_search_products` — `type_id=simple`, `page_size=1`*

> You have **106 simple products** in Magento.

---

**"How many orders were placed today?"**

*Tool: `admin_search_orders` — `created_from=today`, `page_size=1`*

> **3 orders** placed today, all in `pending` status.

---

**"How many orders do we have this week?"**

*Tool: `admin_search_orders` — `created_from=this week`, `page_size=1`*

> **9 orders** this week — 3 today, 6 yesterday.

---

**"What's our revenue this month?"**

*Tool: `admin_get_analytics` — `metric=revenue`, `from_date=this month`*

> Revenue this month: **€4,218.40** across 31 orders.

---

**"Is SKU MH01-XS-Black in stock?"**

*Tool: `admin_get_inventory` — `skus=["MH01-XS-Black"]`*

> MH01-XS-Black is **in stock** — 24 units salable.

---

**"What store views do we have configured?"**

*Tool: `admin_get_store_hierarchy`*

> You have 1 website (base), 1 store group (Main Website Store), and 2 store views: **default** (English) and **german** (German).

---

## Product Management

### Viewing and searching products

**"Show me all disabled products"**

*Tool: `admin_search_products` — `status=2`*

---

**"Find products priced between €20 and €40"**

*Tool: `admin_search_products` — `price_min=20`, `price_max=40`*

---

**"Get the full details for SKU 24-MB01"**

*Tool: `admin_get_product` — `sku=24-MB01`*

Returns all EAV attributes, media gallery, stock item with raw warehouse quantity, tier prices, and category assignments.

---

### Updating a product — simple fields

**"Change the price of 24-MB01 to €39.99"**

1. *Tool: `admin_update_product` — `sku=24-MB01`, `price=39.99`, `confirm=False`*
   > I'll update the price of product 24-MB01 to €39.99. Call again with `confirm=True` to proceed.
2. *Tool: `admin_update_product` — `sku=24-MB01`, `price=39.99`, `confirm=True`*
   > Done. Price updated from €34.00 to €39.99.

---

**"Set a sale price on 24-MB01 for the next 7 days"**

1. *Tool: `admin_update_product` — `special_price=27.99`, `special_price_from=2026-03-24`, `special_price_to=2026-03-31`, `confirm=True`*
   > Sale price €27.99 set on 24-MB01, active 2026-03-24 through 2026-03-31.

The sale price appears alongside the regular price on the storefront.

---

### Updating a select/swatch attribute — the EAV lookup flow

**"Change the color of 24-MB01 to Red"**

Select and swatch attributes store integer option IDs, not label text. MageMCP handles this automatically:

1. *Tool: `admin_get_product_attribute` — `attribute_code=color`*
   > color is a `select` attribute. Options: Black → 49, Blue → 50, Red → 59, …

   *(This step lets you verify the available options and confirm "Red" exists.)*

2. *Tool: `admin_update_product` — `sku=24-MB01`, `attributes={"color": "Red"}`, `confirm=True`*
   > Color updated to Red (option ID 59).

The label-to-ID resolution happens automatically inside `admin_update_product`. You can also pass the ID directly (`attributes={"color": "59"}`) to skip the lookup if you already know it.

---

**"Update the material to Leather and set the manufacturer to Acme Corp"**

*Tool: `admin_update_product` — `attributes={"material": "Leather", "manufacturer": "Acme Corp"}`, `confirm=True`*

For `text` attributes like `manufacturer`, the value passes through as-is. For `select` attributes like `material`, the label is auto-resolved to an option ID.

---

## Order Management

### Looking up orders

**"Show me all pending orders from this week"**

*Tool: `admin_search_orders` — `status=pending`, `created_from=this week`*

---

**"Show me the full details of order #000000042"**

*Tool: `admin_get_order` — `increment_id=000000042`*

Returns payment info, line items, shipping address, invoice and shipment records, and the complete status history.

---

**"What are the tracking numbers for order #000000042?"**

*Tool: `admin_get_order_tracking` — order entity ID*

---

**"What orders has customer john@example.com placed?"**

1. *Tool: `admin_search_customers` — `email=%john@example.com%`*  → get customer ID
2. *Tool: `admin_get_customer_orders` — `customer_id=<id>`*

---

### Taking action on orders

**"Cancel order #000000042"**

1. *Tool: `admin_cancel_order` — `order_id=42`, `confirm=False`*
   > I'll cancel order #000000042. This cannot be undone. Call again with `confirm=True` to proceed.
2. *Tool: `admin_cancel_order` — `order_id=42`, `confirm=True`*
   > Order #000000042 cancelled.

---

**"Add a note to order #000000042 saying the customer called about a delay"**

*Tool: `admin_add_order_comment` — `order_id=42`, `comment="Customer called about delivery delay. Advised 2 additional business days."`, `is_visible_on_front=false`*

---

**"Create a shipment for order #000000042 with tracking UPS 1Z999AA10123456784"**

*Tool: `admin_create_shipment` — `order_id=42`, `tracking=[{carrier_code: "ups", title: "UPS", number: "1Z999AA10123456784"}]`, `confirm=True`*

---

## Customer Management

### Finding customers

**"Find customers with the last name Smith"**

*Tool: `admin_search_customers` — `lastname=%Smith%`*

---

**"Show me all Wholesale customers"**

Customer groups use integer IDs that vary per Magento installation. Look them up first:

1. *Tool: `admin_get_customer_groups`*
   > Groups: NOT LOGGED IN → 0, General → 1, Wholesale → 2, Retailer → 3

2. *Tool: `admin_search_customers` — `group_id=2`*
   > Found 14 Wholesale customers.

---

**"Pull up the full profile for jane@example.com"**

*Tool: `admin_get_customer` — `email=jane@example.com`*

Returns all addresses, custom attributes, store/website assignment, and B2B extension attributes.

---

## Promotions

### Viewing promotions

**"What active discount rules do we have?"**

*Tool: `admin_search_sales_rules` — `is_active=true`*

---

**"Which promotions apply to the Wholesale customer group?"**

1. *Tool: `admin_get_customer_groups`* → find that Wholesale = 2
2. *Tool: `admin_search_sales_rules` — `is_active=true`*
3. Filter results where `customer_group_ids` contains 2.

---

**"Show me the full configuration of the Summer Sale rule"**

1. *Tool: `admin_search_sales_rules` — `name=%Summer Sale%`* → get rule ID
2. *Tool: `admin_get_sales_rule` — `rule_id=<id>`*

Returns discount type (percent/fixed/etc.), conditions (minimum cart total, specific categories), usage limits, and times used.

---

### Generating coupons

**"Generate 20 coupon codes for the VIP Friends rule"**

1. *Tool: `admin_search_sales_rules` — `name=%VIP Friends%`* → rule must have `coupon_type=3` (auto-generated)
2. *Tool: `admin_generate_coupons` — `rule_id=<id>`, `quantity=20`, `format=alphanum`, `confirm=True`*
   > Generated 20 codes: XKQR72BN4PL1, …

---

## Returns

**"Show me all pending returns this month"**

*Tool: `admin_search_returns` — `status=pending`*

Valid status values: `pending`, `authorized`, `partial_authorized`, `received`, `rejected`, `approved`, `partial_approved`, `solved`, `closed`.

---

**"Get the full details of return #0000001"**

*Tool: `admin_get_return` — return entity ID*

---

## Reviews

**"Show me the reviews for SKU 24-MB01"**

*Tool: `admin_get_product_reviews` — `sku=24-MB01`*

---

**"Approve the pending review with ID 42"**

*Tool: `admin_moderate_review` — `review_id=42`, `status=approved`, `confirm=True`*

---

## Shopping Assistant (c_* Tools)

These tools use GraphQL with the storefront API — no admin token required.

**"Find me a yoga bag under €40"**

*Tool: `c_search_products` — `search_text=yoga bag`, `price_max=40`*

---

**"Complete a checkout for the Joust Duffle Bag"**

Full checkout flow (agent chains these automatically):

1. `c_create_cart` → get `cart_id`
2. `c_search_products` — find the SKU
3. `c_add_to_cart` — `sku=24-MB01`, `qty=1`
4. `c_set_guest_email` — `email=customer@example.com`
5. `c_set_shipping_address` — returns available shipping methods
6. `c_set_shipping_method` — `carrier_code=flatrate`, `method_code=flatrate`
7. `c_set_payment_method` — `payment_method_code=checkmo`
8. `c_place_order` → order number returned

---

**"What's your return policy?"**

*Tool: `c_get_policy_page` — `identifier=return-policy`*

---

## Bulk Operations

**"Update the prices of these 50 SKUs..."**

*Tool: `admin_bulk_catalog_update` — `products=[{sku, price}, ...]`*

Returns a `bulk_uuid`. Poll with `admin_get_bulk_status` until complete.

---

**"Restock these 20 SKUs to 100 units each"**

*Tool: `admin_bulk_inventory_update` — `items=[{sku, qty}, ...]`*

Returns a `bulk_uuid` for async processing.

---

## Multi-Step Workflow Examples

### "Show me the most recent order from john@example.com with full details"

1. `admin_search_orders` — `customer_email=%john@example.com%`, `page_size=1`, `sort=DESC` → get order ID
2. `admin_get_order` — `increment_id=<id>` → full details

---

### "How much has our top customer spent this year?"

1. `admin_search_orders` — `created_from=this year`, sorted by total, `page_size=1` → find top customer email
2. `admin_get_customer` — full profile
3. `admin_get_customer_orders` — order history for that customer

---

### "Set up a flash sale: 20% off all Bag products for the weekend"

1. `admin_search_products` — `name=%bag%`, get list of SKUs
2. For each SKU: `admin_update_product` — `special_price=<calculated>`, `special_price_from=2026-03-28`, `special_price_to=2026-03-30`, `confirm=True`

Alternatively create a cart price rule via the Magento admin and use `admin_generate_coupons`.
