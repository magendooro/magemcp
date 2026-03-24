# Use Cases by Role

MageMCP connects an AI agent to a live Magento store. The agent can search, read, and write — following multi-step workflows just like a human operator, but instantly and at scale.

This page shows what that looks like for real roles in an e-commerce business.

---

## Roles

- [SEO Specialist](#seo-specialist)
- [E-commerce Manager / Merchandiser](#e-commerce-manager--merchandiser)
- [Customer Support Agent](#customer-support-agent)
- [Operations Manager](#operations-manager)
- [Sales Manager](#sales-manager)
- [CEO / Business Owner](#ceo--business-owner)
- [CTO / IT Manager](#cto--it-manager)

---

## SEO Specialist

You're responsible for organic visibility. That means product pages need compelling titles, meta descriptions, and rich content — consistently, across hundreds or thousands of SKUs. Manual audits are time-consuming, and bulk updates are error-prone.

---

### Workflow: Product Content Gap Audit + Bulk Fix

**Problem:** You suspect many products are missing meta titles and meta descriptions. You want a prioritised report, then want to fix the gaps without touching a spreadsheet.

**Sample prompt:**
> "Audit all enabled simple products and give me a report of which ones are missing a meta title or meta description. Then generate appropriate values for each and update them."

**What the agent does:**

1. **Paginate all enabled simple products** — calls `admin_search_products` with `status=1`, `type_id=simple`, iterating pages of 50 until exhausted.

2. **Fetch full attribute data per product** — calls `admin_get_product` for each SKU to retrieve `meta_title`, `meta_description`, `description`, `short_description`, and `url_key` from the full EAV attribute set. (Product search summaries don't include custom attributes, so full detail is required.)

3. **Identify gaps** — builds an internal list of products where `meta_title` is empty/null, `meta_description` is empty/null, or both. Scores severity: both missing = high, one missing = medium.

4. **Generate a report:**

   | SKU | Name | Missing | Priority |
   |-----|------|---------|----------|
   | MH01-XS-Black | Chaz Kangeroo Hoodie XS Black | meta_title, meta_description | High |
   | WH01-S-Blue | Mona Pullover Hoodie S Blue | meta_description | Medium |
   | … | … | … | … |

   *43 products missing meta content (18 high priority, 25 medium priority).*

5. **Generate content** — for each flagged product, the agent drafts a `meta_title` (55–60 chars, includes brand/size/colour) and `meta_description` (150–160 chars, benefit-led, includes a call to action).

6. **Confirm before writing** — presents the first few to you for approval. Once confirmed, calls `admin_update_product` per SKU:
   ```
   admin_update_product(
       sku="MH01-XS-Black",
       attributes={"meta_title": "Chaz Kangeroo Hoodie — Men's XS Black | Brand",
                   "meta_description": "Shop the Chaz Kangeroo Hoodie in XS Black. ..."},
       confirm=True
   )
   ```

**Outcome:** A prioritised content gap report and all meta fields populated — in minutes, not days. No spreadsheet, no CSV export, no manual re-import.

---

### Workflow: URL and Redirect Health Check

**Problem:** After a category restructure, you want to verify that key product and category URLs still resolve correctly and haven't been orphaned.

**Sample prompt:**
> "Check that these 10 URLs still resolve to active products: [list]. Flag any that are 404 or point to a disabled product."

**What the agent does:**

1. For each URL, calls `c_resolve_url` to get the resolved entity type, ID, and relative URL.
2. If it resolves to a product, calls `c_get_product` (or `admin_get_product`) to check `status=1` (enabled).
3. Flags any URL that returns not-found or resolves to a disabled/out-of-catalogue product.
4. Returns a clean summary: ✓ resolved, ✗ broken, ⚠ disabled.

**Outcome:** Instant redirect audit without crawling tools. Useful before and after migrations.

---

### Workflow: Short Description Consistency Audit

**Problem:** Some product imports left `short_description` populated with HTML tags or truncated copy that looks broken on category pages.

**Sample prompt:**
> "Find all products where the short_description contains raw HTML tags or is longer than 300 characters and give me a list."

**What the agent does:**

1. Paginates products via `admin_search_products`.
2. Fetches `short_description` via `admin_get_product` per SKU.
3. Applies the rule: flag if content contains `<p>`, `<div>`, `<br>`, `<ul>`, or exceeds 300 characters.
4. Returns a sorted report with character count and a snippet preview.
5. Optionally rewrites each short_description to plain text and updates via `admin_update_product`.

---

## E-commerce Manager / Merchandiser

You own the catalogue day-to-day. You manage product launches, promotions, CMS banners, and pricing. You need to move fast without breaking things.

---

### Workflow: New Product Launch Checklist

**Problem:** A new product needs to go live — status enabled, full description, correct attributes, and sufficient stock confirmed — before you flip it on.

**Sample prompt:**
> "Prepare SKU NEW-JACKET-M-RED for launch: enable it, set the short description to '...', set the colour attribute to Red, and confirm we have at least 10 units in stock."

**What the agent does:**

1. `admin_get_product(sku="NEW-JACKET-M-RED")` — checks current status, existing description, stock extension attributes.
2. `admin_get_inventory(skus=["NEW-JACKET-M-RED"])` — confirms salable quantity ≥ 10.
3. `admin_get_product_attribute(attribute_code="color")` — fetches the option list so it can resolve "Red" to the correct option ID.
4. Presents a pre-flight summary: current status, stock level, which fields will change.
5. On confirmation, calls `admin_update_product`:
   ```
   admin_update_product(
       sku="NEW-JACKET-M-RED",
       status=1,
       short_description="Lightweight technical jacket ...",
       attributes={"color": "Red"},
       confirm=True
   )
   ```

**Outcome:** One prompt replaces: find SKU in admin → check stock in a different panel → edit attributes → save. The agent handles the lookup, attribute resolution, and the write — with a confirmation gate before any change is made.

---

### Workflow: Promotion Audit — What's Live and What's Expiring?

**Problem:** It's Monday morning. You want to know which cart price rules are currently active, which expire this week, and whether any have hit their usage limit.

**Sample prompt:**
> "Give me a summary of all active promotions — name, discount, expiry date, and how many times each has been used."

**What the agent does:**

1. `admin_search_sales_rules(is_active=True, page_size=50)` — gets all active rules with discount_amount, simple_action, from_date, to_date, coupon_code.
2. For rules where usage data is needed, calls `admin_get_sales_rule(rule_id=...)` — adds `times_used`, `uses_per_coupon`, customer_group_ids.
3. Sorts by `to_date` ascending — soonest to expire first.
4. Highlights rules expiring within 7 days in the summary.

**Outcome:** A Monday briefing in seconds. No navigating the promotions grid in the admin panel.

---

### Workflow: Generate Coupon Codes for a Campaign

**Problem:** Marketing needs 200 unique single-use coupon codes for a flash sale email campaign, linked to an existing 15%-off rule.

**Sample prompt:**
> "Generate 200 unique alphanum coupon codes for sales rule 42 (15% flash sale) and give me the list."

**What the agent does:**

1. `admin_get_sales_rule(rule_id=42)` — confirms the rule exists and has `coupon_type=3` (auto-generated).
2. Presents the confirmation prompt: "Generate 200 codes for rule 42 — 15% off all orders, valid until Friday."
3. On confirm: `admin_generate_coupons(rule_id=42, quantity=200, format="alphanum", length=12, confirm=True)`.
4. Returns the full list of codes, ready to paste into your email platform.

---

## Customer Support Agent

You handle enquiries all day — order status, where's my parcel, I want to return this. Speed and accuracy matter. Switching between tabs in the admin panel is friction you don't need.

---

### Workflow: Order Inquiry Resolution

**Problem:** A customer emails: "My order #000000042 still hasn't arrived. I ordered 5 days ago."

**Sample prompt:**
> "Look up order 000000042 — status, tracking, and latest comments."

**What the agent does:**

1. `admin_get_order(increment_id="000000042")` — returns status, shipment tracking numbers, full status history, invoice state, line items.
2. Surfaces the relevant facts: shipped 3 days ago, tracking number DHL 1234567890, last comment "Handed to courier".
3. You can immediately tell the customer the tracking number and suggest they check the DHL portal.
4. If you want to add an internal note: `admin_add_order_comment(order_id=..., comment="Customer chased delivery — tracking shared", is_customer_notified=False, confirm=True)`.

**Outcome:** Order lookup + comment in one conversation. No tab-switching, no copy-pasting tracking numbers from shipment sub-panels.

---

### Workflow: Customer Profile + Order History

**Problem:** A customer calls saying they have multiple accounts and can't find an old order. You need to check both possible email addresses.

**Sample prompt:**
> "Search for customers with email like %john.smith% and show me their recent orders."

**What the agent does:**

1. `admin_search_customers(email="%john.smith%")` — finds all matching accounts.
2. For each customer found: `admin_get_customer_orders(customer_id=...)` — last 10 orders with status and total.
3. Surfaces: two accounts found, one with 3 orders (most recent: €89.50, delivered), one with 1 order (abandoned).
4. You identify the right account and can proceed with the inquiry.

**Outcome:** Multi-account lookup resolved in one prompt, without navigating to customer grid → orders sub-tab for each account.

---

### Workflow: Return / RMA Processing

**Problem:** A customer requests a return. You need to check if their order qualifies, view existing return requests, and add a comment to progress the case.

**Sample prompt:**
> "Check order 000000097 — is there an existing return request? If not, what's the order status?"

**What the agent does:**

1. `admin_get_order(increment_id="000000097")` — checks order status and whether it's eligible (shipped, not cancelled).
2. `admin_search_returns(order_id=...)` — checks for existing RMA requests.
3. If an RMA exists: `admin_get_return(return_id=...)` — full detail: items, quantities, reason, resolution, comments.
4. You can ask the agent: "Add a comment to return 15: 'Label sent to customer via email on 2026-03-24'", which triggers `admin_add_order_comment` on the originating order.

---

## Operations Manager

You run fulfilment. Every morning you need to know what needs to ship, what's on hold, and whether any orders have issues. Bulk operations need to be reliable.

---

### Workflow: Morning Fulfilment Queue

**Problem:** It's 8 AM. You need to know which orders are pending, how many are on hold, and whether any orders placed yesterday still haven't been invoiced.

**Sample prompt:**
> "Give me this morning's operations briefing: pending orders, orders on hold, and any orders from yesterday that aren't invoiced yet."

**What the agent does:**

1. `admin_search_orders(status="pending", page_size=50)` — count and list pending.
2. `admin_search_orders(status="holded", page_size=50)` — count and list held orders.
3. `admin_search_orders(created_from="yesterday", created_to="yesterday", page_size=50)` — yesterday's orders; cross-references invoice state from `admin_get_order` for flagged ones.
4. Returns a structured briefing:
   - **14 orders pending** — oldest placed 18h ago
   - **3 orders on hold** — requires manual review
   - **2 orders from yesterday not yet invoiced** — #000000091, #000000088

**Outcome:** A 30-second briefing that replaces 10 minutes of admin panel navigation.

---

### Workflow: Inventory Restock Alert

**Problem:** You want to identify all SKUs where salable quantity has dropped below 5 units so you can raise purchase orders.

**Sample prompt:**
> "Check inventory for all SKUs in the 'Jackets' category and flag anything with fewer than 5 units salable."

**What the agent does:**

1. `c_get_categories()` — finds the Jackets category ID.
2. `admin_search_products(category_id=..., page_size=50)` — gets all SKUs in the category.
3. `admin_get_inventory(skus=[...])` — batch-checks salable quantity.
4. Filters to those below threshold and returns:

   | SKU | Name | Salable Qty |
   |-----|------|-------------|
   | MJ01-L-Black | Montana Wind Jacket L Black | 2 |
   | MJ02-M-Red | Proteus Zip-Up M Red | 4 |

5. Optionally: `admin_update_inventory(sku=..., qty=50, confirm=True)` to push a manual stock adjustment when stock arrives.

---

### Workflow: Bulk Shipment Creation

**Problem:** A batch of 30 orders has been picked and packed. You have tracking numbers and want to create shipments for all of them at once.

**Sample prompt:**
> "Create shipments for these order IDs with the following DHL tracking numbers: [list of order_id → tracking pairs]."

**What the agent does:**

1. For each order: `admin_create_shipment(order_id=..., tracks=[{"carrier_code": "dhl", "title": "DHL", "number": "..."}], confirm=True)` — uses the `POST /V1/order/{id}/ship` endpoint (not `/V1/shipment`) to prevent duplicate shipments.
2. Reports back: 29 shipments created successfully, 1 failed (order already shipped — already has a shipment).
3. If bulk scale is needed: `admin_bulk_catalog_update` / `admin_bulk_inventory_update` for async operations that return a `bulk_uuid` to poll.

---

## Sales Manager

You own revenue. You need to understand what's selling, which promotions are driving conversions, who your best customers are, and where you're leaving money on the table.

---

### Workflow: Revenue Dashboard — On Demand

**Problem:** Your weekly reporting takes a morning to assemble from multiple admin views. You want the key numbers instantly.

**Sample prompt:**
> "Give me the revenue summary for this month vs last month — total revenue, order count, AOV, and compare the two periods."

**What the agent does:**

1. `admin_get_analytics(from_date="this month", to_date="today", metric="revenue")` — this month's revenue, order count, AOV.
2. `admin_get_analytics(from_date="last month", metric="revenue")` — last month's totals.
3. Computes delta and percentage change.
4. Returns:

   | Metric | This Month | Last Month | Change |
   |--------|-----------|------------|--------|
   | Revenue | €18,420 | €14,780 | +24.6% |
   | Orders | 138 | 112 | +23.2% |
   | AOV | €133.48 | €131.96 | +1.2% |

**Outcome:** Instant period comparison without exporting reports or waiting for BI tools to refresh.

---

### Workflow: Promotion Performance Deep Dive

**Problem:** The summer sale ran for two weeks. You want to know how many coupons were redeemed, total discount given, and which customer groups used it most.

**Sample prompt:**
> "Analyse the performance of the 'SUMMER20' promotion — how many times was it used, and which customer groups were targeted?"

**What the agent does:**

1. `admin_search_sales_rules(name="%SUMMER20%")` — finds the rule.
2. `admin_get_sales_rule(rule_id=...)` — gets `times_used`, `uses_per_coupon`, `discount_amount`, `simple_action`, `customer_group_ids`, validity dates.
3. `admin_get_customer_groups()` — maps group IDs to names.
4. Summarises: 847 uses, 20% off, applied to General + Wholesale groups, €4,230 total discount given (calculated from times_used × AOV × 0.20).

---

### Workflow: Abandoned Cart Recovery Intelligence

**Problem:** You want to understand the value sitting in abandoned carts and identify your highest-value abandonments to prioritise outreach.

**Sample prompt:**
> "Show me the 10 highest-value active carts that haven't been converted to orders."

**What the agent does:**

1. `admin_search_quotes(page_size=50)` — returns active/abandoned quotes with grand_total, customer_email, items_count, created_at, updated_at.
2. Sorts by `grand_total` descending.
3. Returns top 10 with cart value, customer email, item count, and time since last activity.
4. You can then look up the customer: `admin_search_customers(email="...")` and `admin_get_customer_orders(customer_id=...)` to assess lifetime value before prioritising outreach.

---

## CEO / Business Owner

You don't live in the admin panel — you make decisions. You need the right numbers fast, without depending on someone else to pull a report.

---

### Workflow: Morning Business Pulse

**Problem:** You start every day wanting to know if the business is healthy. Revenue, orders, anything unusual.

**Sample prompt:**
> "Give me yesterday's numbers and how they compare to the same day last week."

**What the agent does:**

1. `admin_get_analytics(from_date="yesterday", to_date="yesterday")` — yesterday's revenue, orders, AOV.
2. Computes the same-day-last-week date and calls again for comparison.
3. `admin_search_orders(status="pending", page_size=1)` — flags if there's an unusual order backlog.
4. Returns a clean briefing:

   > **Yesterday:** €1,840 revenue · 13 orders · €141.54 AOV — up 18% vs same day last week.
   > 6 orders currently pending fulfilment.

**Outcome:** A 10-second pulse check before your first meeting. No dashboards, no logins.

---

### Workflow: Pre-Board-Meeting Summary

**Problem:** You need a one-page view of the month's performance: revenue trend, top-performing promotions, inventory health, and any operational flags.

**Sample prompt:**
> "Prepare a board summary for March 2026: revenue vs February, active promotions, any fulfilment issues, and top inventory concerns."

**What the agent does:**

1. `admin_get_analytics` — March and February revenue/orders/AOV.
2. `admin_search_sales_rules(is_active=True)` — active promotions with usage stats.
3. `admin_search_orders(status="holded")` + `admin_search_orders(status="pending")` — operational health.
4. `admin_get_inventory` for top SKUs — flags low-stock items.
5. Composes a structured markdown summary ready to paste into a slide or email.

---

## CTO / IT Manager

You own the technical platform. You need confidence that the store is configured correctly, that integrations are healthy, and that any large operations complete without silent failures.

---

### Workflow: Store Configuration Audit

**Problem:** The business operates two store views (EN and DE). You want to confirm that both are configured correctly — correct base URLs, currency, locale, and that no store view is accidentally using a wrong setting.

**Sample prompt:**
> "Audit the store configuration across all store views — show base URLs, locale, currency, and timezone for each."

**What the agent does:**

1. `admin_get_store_hierarchy()` — gets the full website → store group → store view tree with IDs and codes.
2. For each store view code: `c_get_store_config(store_scope=<code>)` — base_url, base_link_url, locale, base_currency_code, timezone, weight_unit.
3. Compares values side by side and flags any anomaly (e.g., DE store using USD instead of EUR).

**Outcome:** Cross-store configuration diff in one conversation. Catches misconfiguration before it affects customers.

---

### Workflow: Bulk Operation Monitoring

**Problem:** You triggered a bulk catalog update (e.g., price change across 500 products). You need to know when it completes and whether all items succeeded.

**Sample prompt:**
> "Check the status of bulk operation abc123def456 and tell me how many items succeeded, are pending, and failed."

**What the agent does:**

1. `admin_get_bulk_status(bulk_uuid="abc123def456")` — returns overall status, item counts by state (open/complete/failed/retriable_failed).
2. If any items failed: lists the failed SKUs and error messages.
3. You can re-trigger failed items selectively via `admin_update_product` or `admin_bulk_catalog_update` with just the failed SKUs.

---

### Workflow: CMS Content Deployment

**Problem:** Legal has updated the Returns Policy. The new copy needs to go live on the `returns-policy` CMS page. You want to verify the current content first, then deploy.

**Sample prompt:**
> "Show me the current content of the returns-policy CMS page, then update it with the following text: [new copy]."

**What the agent does:**

1. `admin_get_cms_page(identifier="returns-policy")` — returns current title, content, meta_description, is_active, store IDs.
2. Displays the current content for review.
3. On confirmation: `admin_update_cms_page(page_id=..., content="...", confirm=True)`.
4. Optionally: `c_get_policy_page(identifier="returns-policy")` to verify the live storefront reflects the update.

**Outcome:** Content deployment with before/after verification, no FTP, no admin panel copy-paste, no risk of publishing to the wrong page ID.

---

## What These Workflows Have in Common

Across every role, the pattern is the same:

1. **Natural language in** — no SQL, no API syntax, no navigating nested admin panels
2. **Multi-step reasoning** — the agent decides which tools to call, in which order, and how to combine the results
3. **Confirmation before writes** — destructive or irreversible actions always show you what will happen before they execute
4. **Structured output** — tables, bullet points, numbers — ready to act on or paste into a report

The tools don't change the business logic. They give every role in your business access to the data and operations they need — without waiting for a developer, without building a BI dashboard, and without learning Magento's admin panel.
