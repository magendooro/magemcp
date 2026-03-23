# MageMCP POC Tool Specifications

## Namespace Design

MageMCP tools are split into two namespaces reflecting fundamentally different access contexts:

### `admin_*` — Back-Office / Operations

- **Auth**: Magento REST API with integration/admin Bearer token
- **Data scope**: All products, orders, customers across all store views
- **Visibility**: Internal/operational data including disabled products, all order statuses, customer records
- **Audience**: Support reps, ops teams, back-office agents
- **PII handling**: Full data returned (no redaction) — admin tools always return complete customer details, addresses, and contact info
- **Transport**: REST API with `searchCriteria` for list operations

### `c_*` — Customer-Facing / Storefront

- **Auth**: Anonymous GraphQL (default) or customer token for authenticated queries
- **Data scope**: Only storefront-visible data — respects catalog visibility rules, category permissions, store view context
- **Visibility**: What a shopper would see on the frontend
- **Audience**: Shopping assistants, self-service bots, customer-facing agents
- **PII handling**: No internal data exposed; storefront-scoped by design
- **Transport**: GraphQL API for field-level control

### Why the Split

1. **Different trust levels**: An admin token can read every order and customer in the system. A storefront query can only see published catalog data. Mixing these in one namespace obscures the blast radius of each tool.

2. **Different auth contexts**: Admin tools require `MAGENTO_TOKEN` (integration token) configured at the server level. Customer-facing tools work anonymously or with short-lived customer tokens. This distinction must be explicit.

3. **Different data contracts**: Admin tools return redacted DTOs that strip PII from rich internal objects. Customer-facing tools return storefront DTOs that match what the frontend would render — no redaction needed because the data is already public.

4. **Mixed-namespace sessions**: A single agent session can use both namespaces. Example: a support agent uses `admin_get_order` to look up a customer's order, then `c_search_products` to find an alternative product to recommend. The namespace prefix makes it immediately clear which auth context and data visibility applies to each call.

---

## Cross-Cutting Patterns

### Store Scope

Every tool accepts an optional `store_scope` parameter:

```python
store_scope: str = Field(
    default="default",
    description="Magento store view code. Determines which store view's data is returned.",
    min_length=1,
    max_length=64,
    pattern=r"^[a-z][a-z0-9_]*$",
)
```

- **Admin tools (REST)**: Included in the URL path: `/rest/{store_scope}/V1/...`
- **Customer-facing tools (GraphQL)**: Sent as the `Store` HTTP header
- **Policy layer**: Validates the caller is authorized for the requested scope before forwarding to Magento

### Pagination — Admin Tools (REST)

Admin tools use Magento's `searchCriteria` pagination:

```python
page: int = Field(default=1, ge=1, description="Page number (1-indexed).")
page_size: int = Field(default=20, ge=1, le=100, description="Results per page. Max 100.")
```

Mapped to `searchCriteria[currentPage]` and `searchCriteria[pageSize]`.

Response includes:

```python
total_count: int
current_page: int
page_size: int
```

### Pagination — Customer-Facing Tools (GraphQL)

Customer-facing tools use GraphQL pagination:

```python
page_size: int = Field(default=20, ge=1, le=50, description="Results per page. Max 50.")
current_page: int = Field(default=1, ge=1, description="Page number (1-indexed).")
```

GraphQL page sizes are capped lower (50) because storefront queries are heavier (media, price ranges, options).

Response includes:

```python
total_count: int
page_info: PageInfo  # current_page, page_size, total_pages
```

### Rate Limiting

All POC tools are read-only and share the **read tier**: 60 calls/minute per client session.

### MCP Annotations

All POC tools share the same annotations:

```python
annotations=ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    openWorldHint=True,  # calls external Magento API
)
```

---

## Admin Namespace Tools

### 1. `admin_search_orders`

**Description**: Search orders by increment ID, customer email, date range, or status. Returns redacted order summaries.

**MCP Annotations**: `readOnlyHint=True`, `destructiveHint=False`

**Magento API Surface**:
- Endpoint: `GET /rest/{store_scope}/V1/orders`
- Method: GET
- Auth: Integration Bearer token
- Key params: `searchCriteria` with filter groups for `increment_id`, `customer_email`, `status`, `created_at`

**Policy Notes**:
- Rate limit: read tier (60/min)
- Authorization: requires valid integration token
- PII: customer email is used as a search filter but never returned in results — responses use `OrderSummary` DTO with redacted customer info

#### Input Schema

```python
class AdminSearchOrdersInput(BaseModel):
    """Search orders with filters. At least one filter must be provided."""

    increment_id: str | None = Field(
        default=None,
        description="Order increment ID (e.g. '000000042'). Exact match.",
        min_length=1,
        max_length=32,
    )
    customer_email: str | None = Field(
        default=None,
        description="Customer email address. Exact match.",
        max_length=255,
    )
    status: str | None = Field(
        default=None,
        description=(
            "Order status filter. Common values: 'pending', 'processing', "
            "'complete', 'closed', 'canceled', 'holded'."
        ),
        max_length=32,
    )
    date_from: str | None = Field(
        default=None,
        description="Filter orders created on or after this date. ISO 8601 format (YYYY-MM-DD).",
        pattern=r"^\d{4}-\d{2}-\d{2}$",
    )
    date_to: str | None = Field(
        default=None,
        description="Filter orders created on or before this date. ISO 8601 format (YYYY-MM-DD).",
        pattern=r"^\d{4}-\d{2}-\d{2}$",
    )
    store_scope: str = Field(
        default="default",
        description="Magento store view code.",
        min_length=1,
        max_length=64,
        pattern=r"^[a-z][a-z0-9_]*$",
    )
    page: int = Field(default=1, ge=1, description="Page number (1-indexed).")
    page_size: int = Field(default=20, ge=1, le=100, description="Results per page. Max 100.")
    sort_field: str = Field(
        default="created_at",
        description="Field to sort by. Options: 'created_at', 'increment_id', 'grand_total'.",
        pattern=r"^(created_at|increment_id|grand_total)$",
    )
    sort_direction: str = Field(
        default="DESC",
        description="Sort direction: 'ASC' or 'DESC'.",
        pattern=r"^(ASC|DESC)$",
    )
```

#### Output Schema

```python
class OrderSummary(BaseModel):
    """Redacted order summary for search results."""

    entity_id: int
    increment_id: str
    status: str
    state: str
    store_name: str
    created_at: str
    updated_at: str
    grand_total: Decimal
    currency_code: str
    total_item_count: int
    customer_initials: str  # e.g. "J.D." — derived from first/last name
    customer_group: str
    has_shipments: bool
    shipment_count: int


class AdminSearchOrdersOutput(BaseModel):
    """Paginated order search results."""

    orders: list[OrderSummary]
    total_count: int
    current_page: int
    page_size: int
```

#### Example

**Request**:
```json
{
  "status": "processing",
  "date_from": "2026-03-01",
  "page_size": 5,
  "sort_field": "created_at",
  "sort_direction": "DESC"
}
```

**Response**:
```json
{
  "orders": [
    {
      "entity_id": 1042,
      "increment_id": "000000042",
      "status": "processing",
      "state": "processing",
      "store_name": "Main Website Store",
      "created_at": "2026-03-15T14:22:00Z",
      "updated_at": "2026-03-15T14:25:00Z",
      "grand_total": 189.99,
      "currency_code": "USD",
      "total_item_count": 3,
      "customer_initials": "J.D.",
      "customer_group": "General",
      "has_shipments": false,
      "shipment_count": 0
    },
    {
      "entity_id": 1039,
      "increment_id": "000000039",
      "status": "processing",
      "state": "processing",
      "store_name": "Main Website Store",
      "created_at": "2026-03-12T09:45:00Z",
      "updated_at": "2026-03-13T11:00:00Z",
      "grand_total": 54.50,
      "currency_code": "USD",
      "total_item_count": 1,
      "customer_initials": "M.S.",
      "customer_group": "Wholesale",
      "has_shipments": true,
      "shipment_count": 1
    }
  ],
  "total_count": 12,
  "current_page": 1,
  "page_size": 5
}
```

---

### 2. `admin_get_order`

**Description**: Get full order detail by entity ID or increment ID. Returns redacted order with line items, shipment summary, and recent internal comments.

**MCP Annotations**: `readOnlyHint=True`, `destructiveHint=False`

**Magento API Surface**:
- Primary: `GET /rest/{store_scope}/V1/orders/{id}` (by entity_id)
- Fallback: `GET /rest/{store_scope}/V1/orders?searchCriteria[filterGroups][0][filters][0][field]=increment_id&...` (by increment_id, resolves to entity_id, then fetches)
- Method: GET
- Auth: Integration Bearer token

**Policy Notes**:
- Rate limit: read tier (60/min)
- Authorization: requires valid integration token
- PII: full response is projected through `OrderSupportView` DTO — payment details stripped, customer info reduced to initials + group, billing/shipping addresses excluded

#### Input Schema

```python
class AdminGetOrderInput(BaseModel):
    """Fetch a single order. Provide either entity_id or increment_id."""

    entity_id: int | None = Field(
        default=None,
        description="Magento internal order entity ID.",
        ge=1,
    )
    increment_id: str | None = Field(
        default=None,
        description="Customer-facing order number (e.g. '000000042').",
        min_length=1,
        max_length=32,
    )
    store_scope: str = Field(
        default="default",
        description="Magento store view code.",
        min_length=1,
        max_length=64,
        pattern=r"^[a-z][a-z0-9_]*$",
    )

    @model_validator(mode="after")
    def require_one_identifier(self) -> Self:
        if self.entity_id is None and self.increment_id is None:
            raise ValueError("Provide either entity_id or increment_id.")
        return self
```

#### Output Schema

```python
class OrderLineItem(BaseModel):
    """Single line item in an order."""

    item_id: int
    sku: str
    name: str
    qty_ordered: Decimal
    qty_shipped: Decimal
    qty_refunded: Decimal
    price: Decimal
    row_total: Decimal
    discount_amount: Decimal
    status: str  # e.g. "Ordered", "Shipped", "Refunded"


class ShipmentSummary(BaseModel):
    """Summary of a shipment attached to an order."""

    shipment_id: int
    created_at: str
    total_qty: Decimal
    tracks: list[TrackInfo]


class TrackInfo(BaseModel):
    """Shipment tracking information."""

    carrier_code: str
    title: str
    track_number: str


class OrderComment(BaseModel):
    """Internal order comment (status history entry)."""

    comment: str
    status: str
    created_at: str
    is_customer_notified: bool
    is_visible_on_front: bool


class OrderSupportView(BaseModel):
    """Full redacted order detail for support use."""

    entity_id: int
    increment_id: str
    status: str
    state: str
    store_name: str
    created_at: str
    updated_at: str

    # Totals
    subtotal: Decimal
    discount_amount: Decimal
    shipping_amount: Decimal
    tax_amount: Decimal
    grand_total: Decimal
    total_paid: Decimal
    total_refunded: Decimal
    currency_code: str

    # Customer (redacted)
    customer_initials: str
    customer_group: str
    customer_is_guest: bool

    # Line items
    items: list[OrderLineItem]

    # Fulfillment
    shipments: list[ShipmentSummary]
    has_shipments: bool
    is_fully_shipped: bool

    # Comments (last 10)
    recent_comments: list[OrderComment]
    total_comment_count: int

    # Payment (type only, no details)
    payment_method: str  # e.g. "checkmo", "stripe_payments"
```

#### Example

**Request**:
```json
{
  "increment_id": "000000042"
}
```

**Response**:
```json
{
  "entity_id": 1042,
  "increment_id": "000000042",
  "status": "processing",
  "state": "processing",
  "store_name": "Main Website Store",
  "created_at": "2026-03-15T14:22:00Z",
  "updated_at": "2026-03-15T14:25:00Z",
  "subtotal": 169.99,
  "discount_amount": 0.00,
  "shipping_amount": 12.50,
  "tax_amount": 7.50,
  "grand_total": 189.99,
  "total_paid": 189.99,
  "total_refunded": 0.00,
  "currency_code": "USD",
  "customer_initials": "J.D.",
  "customer_group": "General",
  "customer_is_guest": false,
  "items": [
    {
      "item_id": 2001,
      "sku": "WJ12-M-Blue",
      "name": "Stellar Running Jacket - M / Blue",
      "qty_ordered": 1,
      "qty_shipped": 0,
      "qty_refunded": 0,
      "price": 89.99,
      "row_total": 89.99,
      "discount_amount": 0.00,
      "status": "Ordered"
    },
    {
      "item_id": 2002,
      "sku": "MT08-L",
      "name": "Helios Endurance Tee - L",
      "qty_ordered": 2,
      "qty_shipped": 0,
      "qty_refunded": 0,
      "price": 40.00,
      "row_total": 80.00,
      "discount_amount": 0.00,
      "status": "Ordered"
    }
  ],
  "shipments": [],
  "has_shipments": false,
  "is_fully_shipped": false,
  "recent_comments": [
    {
      "comment": "Order placed via web checkout.",
      "status": "processing",
      "created_at": "2026-03-15T14:22:00Z",
      "is_customer_notified": true,
      "is_visible_on_front": true
    }
  ],
  "total_comment_count": 1,
  "payment_method": "stripe_payments"
}
```

---

### 3. `admin_get_customer`

**Description**: Look up a customer by ID or email. Returns a redacted profile with hashed email, initials, group, and order history summary.

**MCP Annotations**: `readOnlyHint=True`, `destructiveHint=False`

**Magento API Surface**:
- By ID: `GET /rest/{store_scope}/V1/customers/{id}`
- By email: `GET /rest/{store_scope}/V1/customers/search?searchCriteria[filterGroups][0][filters][0][field]=email&...[value]={email}&...[conditionType]=eq`
- Method: GET
- Auth: Integration Bearer token

**Policy Notes**:
- Rate limit: read tier (60/min)
- Authorization: requires valid integration token
- PII: **highest sensitivity tool in the POC**. Response is always `CustomerRedacted` — email is hashed (SHA-256, truncated), name reduced to initials, no addresses, no payment info. The `pii_mode` parameter allows `masked` (partial email) only when identity verification state is confirmed.

#### Input Schema

```python
class AdminGetCustomerInput(BaseModel):
    """Look up a customer. Provide either customer_id or email + website_id."""

    customer_id: int | None = Field(
        default=None,
        description="Magento customer entity ID.",
        ge=1,
    )
    email: str | None = Field(
        default=None,
        description="Customer email address. Must be paired with website_id.",
        max_length=255,
    )
    website_id: int | None = Field(
        default=None,
        description="Magento website ID for email lookup. Required when using email.",
        ge=0,
    )
    pii_mode: str = Field(
        default="none",
        description=(
            "PII visibility level. "
            "'none' (default): hashed email, initials only. "
            "'masked': partial email (j***@e***.com), first name. "
            "Requires identity verification state."
        ),
        pattern=r"^(none|masked)$",
    )
    store_scope: str = Field(
        default="default",
        description="Magento store view code.",
        min_length=1,
        max_length=64,
        pattern=r"^[a-z][a-z0-9_]*$",
    )

    @model_validator(mode="after")
    def validate_lookup(self) -> Self:
        if self.customer_id is None and self.email is None:
            raise ValueError("Provide either customer_id or email.")
        if self.email is not None and self.website_id is None:
            raise ValueError("website_id is required when looking up by email.")
        return self
```

#### Output Schema

```python
class CustomerRedacted(BaseModel):
    """Redacted customer profile. Never exposes full PII."""

    customer_id: int
    initials: str  # "J.D."
    email_hash: str  # SHA-256 truncated to 12 chars (for correlation, not reversible)
    email_masked: str | None  # "j***@e***.com" — only when pii_mode=masked
    first_name: str | None  # Only when pii_mode=masked
    customer_group: str  # Group name, e.g. "General", "Wholesale"
    website_id: int
    store_id: int
    created_at: str
    is_active: bool

    # Order history summary (aggregated, not individual orders)
    total_order_count: int
    total_lifetime_value: Decimal
    currency_code: str
    last_order_date: str | None
    last_order_increment_id: str | None
```

#### Example

**Request**:
```json
{
  "email": "jane.doe@example.com",
  "website_id": 1,
  "pii_mode": "none"
}
```

**Response**:
```json
{
  "customer_id": 847,
  "initials": "J.D.",
  "email_hash": "a3f2b8c91e04",
  "email_masked": null,
  "first_name": null,
  "customer_group": "General",
  "website_id": 1,
  "store_id": 1,
  "created_at": "2024-06-15T10:30:00Z",
  "is_active": true,
  "total_order_count": 7,
  "total_lifetime_value": 1245.50,
  "currency_code": "USD",
  "last_order_date": "2026-03-10T08:15:00Z",
  "last_order_increment_id": "000000039"
}
```

---

### 4. `admin_get_inventory`

**Description**: Check salable quantity and availability for one or more SKUs in a given stock.

**MCP Annotations**: `readOnlyHint=True`, `destructiveHint=False`

**Magento API Surface**:
- Salable qty: `GET /rest/{store_scope}/V1/inventory/get-product-salable-qty/{sku}/{stockId}`
- Is salable: `GET /rest/{store_scope}/V1/inventory/is-product-salable/{sku}/{stockId}` (called in parallel with salable qty)
- Method: GET
- Auth: Integration Bearer token
- Note: One API call per SKU — multiple SKUs are fetched concurrently via `asyncio.gather`

**Policy Notes**:
- Rate limit: read tier (60/min). Each SKU counts as one call against the limit.
- Authorization: requires valid integration token
- PII: none — inventory data is not sensitive

#### Input Schema

```python
class AdminGetInventoryInput(BaseModel):
    """Check inventory for one or more SKUs."""

    skus: list[str] = Field(
        description="List of product SKUs to check. Max 25 per request.",
        min_length=1,
        max_length=25,
    )
    stock_id: int = Field(
        default=1,
        description="Magento stock ID. Default stock is 1. Multi-source inventory may use other stock IDs.",
        ge=1,
    )
    store_scope: str = Field(
        default="default",
        description="Magento store view code.",
        min_length=1,
        max_length=64,
        pattern=r"^[a-z][a-z0-9_]*$",
    )
```

#### Output Schema

```python
class SkuInventory(BaseModel):
    """Inventory status for a single SKU."""

    sku: str
    stock_id: int
    salable_qty: Decimal
    is_salable: bool


class AdminGetInventoryOutput(BaseModel):
    """Inventory results for requested SKUs."""

    items: list[SkuInventory]
    errors: list[SkuError]  # SKUs that failed lookup (not found, etc.)


class SkuError(BaseModel):
    """Error for a single SKU lookup."""

    sku: str
    error: str  # e.g. "Product not found", "Stock not found"
```

#### Example

**Request**:
```json
{
  "skus": ["WJ12-M-Blue", "MT08-L", "NONEXISTENT-SKU"],
  "stock_id": 1
}
```

**Response**:
```json
{
  "items": [
    {
      "sku": "WJ12-M-Blue",
      "stock_id": 1,
      "salable_qty": 42.0,
      "is_salable": true
    },
    {
      "sku": "MT08-L",
      "stock_id": 1,
      "salable_qty": 0.0,
      "is_salable": false
    }
  ],
  "errors": [
    {
      "sku": "NONEXISTENT-SKU",
      "error": "Product not found for SKU 'NONEXISTENT-SKU' in stock 1."
    }
  ]
}
```

---

### 5. `admin_search_products`

**Description**: Search all products including disabled and not-visible-individually items. Returns admin-level product data with status, visibility, stock, and all standard attributes.

**MCP Annotations**: `readOnlyHint=True`, `destructiveHint=False`

**Magento API Surface**:
- Endpoint: `GET /rest/{store_scope}/V1/products`
- Method: GET
- Auth: Integration Bearer token
- Key params: `searchCriteria` with filter groups for `sku`, `name` (like), `status`, `visibility`, `type_id`, `category_id`

**Policy Notes**:
- Rate limit: read tier (60/min)
- Authorization: requires valid integration token
- PII: none — product data is not sensitive. However, this tool exposes products that are invisible on the storefront (disabled, not-visible-individually), so it's admin-only.

#### Input Schema

```python
class AdminSearchProductsInput(BaseModel):
    """Search products with admin-level filters."""

    search: str | None = Field(
        default=None,
        description="Free-text search across name and SKU.",
        max_length=200,
    )
    sku: str | None = Field(
        default=None,
        description="Exact SKU match or pattern with %% wildcards (e.g. 'WJ12%%').",
        max_length=64,
    )
    status: int | None = Field(
        default=None,
        description="Product status. 1 = Enabled, 2 = Disabled.",
        ge=1,
        le=2,
    )
    visibility: int | None = Field(
        default=None,
        description=(
            "Catalog visibility. "
            "1 = Not Visible Individually, 2 = Catalog, 3 = Search, 4 = Catalog+Search."
        ),
        ge=1,
        le=4,
    )
    type_id: str | None = Field(
        default=None,
        description="Product type: 'simple', 'configurable', 'grouped', 'bundle', 'virtual', 'downloadable'.",
        max_length=32,
    )
    category_id: int | None = Field(
        default=None,
        description="Filter by category ID (products assigned to this category).",
        ge=1,
    )
    store_scope: str = Field(
        default="default",
        description="Magento store view code.",
        min_length=1,
        max_length=64,
        pattern=r"^[a-z][a-z0-9_]*$",
    )
    page: int = Field(default=1, ge=1, description="Page number (1-indexed).")
    page_size: int = Field(default=20, ge=1, le=100, description="Results per page. Max 100.")
    sort_field: str = Field(
        default="name",
        description="Sort field: 'name', 'sku', 'price', 'created_at', 'updated_at'.",
        pattern=r"^(name|sku|price|created_at|updated_at)$",
    )
    sort_direction: str = Field(
        default="ASC",
        description="Sort direction: 'ASC' or 'DESC'.",
        pattern=r"^(ASC|DESC)$",
    )
```

#### Output Schema

```python
class AdminProductSummary(BaseModel):
    """Admin product data from REST API."""

    entity_id: int
    sku: str
    name: str
    type_id: str  # simple, configurable, grouped, bundle, virtual, downloadable
    status: int  # 1=Enabled, 2=Disabled
    status_label: str  # "Enabled" or "Disabled"
    visibility: int  # 1-4
    visibility_label: str  # "Not Visible Individually", "Catalog", "Search", "Catalog, Search"
    price: Decimal | None  # null for configurable parents
    special_price: Decimal | None
    weight: Decimal | None
    created_at: str
    updated_at: str

    # Stock (from extension_attributes.stock_item)
    is_in_stock: bool
    qty: Decimal

    # Categories
    category_ids: list[int]

    # Media
    thumbnail_url: str | None  # first media entry, if available


class AdminSearchProductsOutput(BaseModel):
    """Paginated admin product search results."""

    products: list[AdminProductSummary]
    total_count: int
    current_page: int
    page_size: int
```

#### Example

**Request**:
```json
{
  "sku": "WJ12%",
  "status": 1,
  "page_size": 5
}
```

**Response**:
```json
{
  "products": [
    {
      "entity_id": 401,
      "sku": "WJ12",
      "name": "Stellar Running Jacket",
      "type_id": "configurable",
      "status": 1,
      "status_label": "Enabled",
      "visibility": 4,
      "visibility_label": "Catalog, Search",
      "price": null,
      "special_price": null,
      "weight": 0.8,
      "created_at": "2025-01-10T12:00:00Z",
      "updated_at": "2026-02-20T09:30:00Z",
      "is_in_stock": true,
      "qty": 0,
      "category_ids": [3, 15, 22],
      "thumbnail_url": "/media/catalog/product/w/j/wj12-blue-front.jpg"
    },
    {
      "entity_id": 402,
      "sku": "WJ12-S-Blue",
      "name": "Stellar Running Jacket - S / Blue",
      "type_id": "simple",
      "status": 1,
      "status_label": "Enabled",
      "visibility": 1,
      "visibility_label": "Not Visible Individually",
      "price": 89.99,
      "special_price": null,
      "weight": 0.8,
      "created_at": "2025-01-10T12:00:00Z",
      "updated_at": "2026-02-20T09:30:00Z",
      "is_in_stock": true,
      "qty": 25,
      "category_ids": [],
      "thumbnail_url": "/media/catalog/product/w/j/wj12-blue-front.jpg"
    }
  ],
  "total_count": 8,
  "current_page": 1,
  "page_size": 5
}
```

---

## Customer-Facing Namespace Tools

### 6. `c_search_products`

**Description**: Search the product catalog as a shopper would see it. Returns storefront-visible products with pricing, images, and stock status.

**MCP Annotations**: `readOnlyHint=True`, `destructiveHint=False`

**Magento API Surface**:
- Endpoint: `POST /graphql` (of the storefront)
- Query: `products(search, filter, sort, pageSize, currentPage)`
- Auth: Anonymous (no token) or customer token for personalized pricing
- Store header: `Store: {store_scope}`

**GraphQL Query**:
```graphql
query SearchProducts(
  $search: String
  $filter: ProductAttributeFilterInput
  $sort: ProductAttributeSortInput
  $pageSize: Int!
  $currentPage: Int!
) {
  products(
    search: $search
    filter: $filter
    sort: $sort
    pageSize: $pageSize
    currentPage: $currentPage
  ) {
    items {
      sku
      name
      url_key
      stock_status
      price_range {
        minimum_price {
          regular_price { value currency }
          final_price { value currency }
          discount { amount_off percent_off }
        }
        maximum_price {
          regular_price { value currency }
          final_price { value currency }
        }
      }
      small_image { url label }
      short_description { html }
      __typename
    }
    total_count
    page_info { current_page page_size total_pages }
  }
}
```

**Policy Notes**:
- Rate limit: read tier (60/min)
- Authorization: none required (anonymous storefront access)
- PII: none — only returns published catalog data
- Only returns products with `visibility` in (3, 4) and `status` = Enabled — enforced by Magento's GraphQL layer, not by MageMCP

#### Input Schema

```python
class CSearchProductsInput(BaseModel):
    """Search the storefront catalog."""

    search: str | None = Field(
        default=None,
        description="Free-text search query (e.g. 'blue running jacket').",
        max_length=200,
    )
    category_id: str | None = Field(
        default=None,
        description="Filter by category ID.",
        max_length=20,
    )
    price_from: float | None = Field(
        default=None,
        description="Minimum price filter.",
        ge=0,
    )
    price_to: float | None = Field(
        default=None,
        description="Maximum price filter.",
        ge=0,
    )
    in_stock_only: bool = Field(
        default=False,
        description="If true, only return products that are IN_STOCK.",
    )
    store_scope: str = Field(
        default="default",
        description="Magento store view code. Determines locale, currency, and catalog scope.",
        min_length=1,
        max_length=64,
        pattern=r"^[a-z][a-z0-9_]*$",
    )
    page_size: int = Field(default=20, ge=1, le=50, description="Results per page. Max 50.")
    current_page: int = Field(default=1, ge=1, description="Page number (1-indexed).")
    sort_field: str = Field(
        default="relevance",
        description="Sort by: 'relevance', 'name', 'price', 'position'.",
        pattern=r"^(relevance|name|price|position)$",
    )
    sort_direction: str = Field(
        default="ASC",
        description="Sort direction: 'ASC' or 'DESC'. Ignored when sort_field is 'relevance'.",
        pattern=r"^(ASC|DESC)$",
    )
```

#### Output Schema

```python
class PriceAmount(BaseModel):
    """A monetary value with currency."""

    value: Decimal
    currency: str


class ProductPrice(BaseModel):
    """Price information for a product."""

    regular_price: PriceAmount
    final_price: PriceAmount
    discount_amount: Decimal | None  # null if no discount
    discount_percent: Decimal | None


class StorefrontProduct(BaseModel):
    """Product as seen on the storefront."""

    sku: str
    name: str
    url_key: str
    product_type: str  # "SimpleProduct", "ConfigurableProduct", etc.
    stock_status: str  # "IN_STOCK" or "OUT_OF_STOCK"
    min_price: ProductPrice
    max_price: ProductPrice  # differs from min_price for configurables/bundles
    image_url: str | None
    image_label: str | None
    short_description: str | None  # HTML stripped to plain text


class PageInfo(BaseModel):
    """GraphQL pagination info."""

    current_page: int
    page_size: int
    total_pages: int


class CSearchProductsOutput(BaseModel):
    """Paginated storefront product search results."""

    products: list[StorefrontProduct]
    total_count: int
    page_info: PageInfo
```

#### Example

**Request**:
```json
{
  "search": "running jacket",
  "price_from": 50,
  "price_to": 150,
  "in_stock_only": true,
  "page_size": 3,
  "sort_field": "relevance"
}
```

**Response**:
```json
{
  "products": [
    {
      "sku": "WJ12",
      "name": "Stellar Running Jacket",
      "url_key": "stellar-running-jacket",
      "product_type": "ConfigurableProduct",
      "stock_status": "IN_STOCK",
      "min_price": {
        "regular_price": { "value": 89.99, "currency": "USD" },
        "final_price": { "value": 89.99, "currency": "USD" },
        "discount_amount": null,
        "discount_percent": null
      },
      "max_price": {
        "regular_price": { "value": 89.99, "currency": "USD" },
        "final_price": { "value": 89.99, "currency": "USD" }
      },
      "image_url": "https://magento.example.com/media/catalog/product/w/j/wj12-blue-front.jpg",
      "image_label": "Stellar Running Jacket",
      "short_description": "Lightweight, wind-resistant running jacket with reflective details."
    },
    {
      "sku": "WJ09",
      "name": "Proteus Fitness Jacket",
      "url_key": "proteus-fitness-jacket",
      "product_type": "ConfigurableProduct",
      "stock_status": "IN_STOCK",
      "min_price": {
        "regular_price": { "value": 118.00, "currency": "USD" },
        "final_price": { "value": 94.40, "currency": "USD" },
        "discount_amount": 23.60,
        "discount_percent": 20.00
      },
      "max_price": {
        "regular_price": { "value": 118.00, "currency": "USD" },
        "final_price": { "value": 94.40, "currency": "USD" }
      },
      "image_url": "https://magento.example.com/media/catalog/product/w/j/wj09-green-front.jpg",
      "image_label": "Proteus Fitness Jacket",
      "short_description": "Four-way stretch fitness jacket with moisture-wicking lining."
    }
  ],
  "total_count": 7,
  "page_info": {
    "current_page": 1,
    "page_size": 3,
    "total_pages": 3
  }
}
```

---

### 7. `c_get_product`

**Description**: Get full product detail as shown on a product detail page. Includes description, media gallery, configurable options, price range, reviews summary, and related products.

**MCP Annotations**: `readOnlyHint=True`, `destructiveHint=False`

**Magento API Surface**:
- Endpoint: `POST /graphql`
- Query: Product detail query by SKU or URL key
- Auth: Anonymous or customer token
- Store header: `Store: {store_scope}`

**GraphQL Query**:
```graphql
query GetProduct($filter: ProductAttributeFilterInput!) {
  products(filter: $filter, pageSize: 1) {
    items {
      sku
      name
      url_key
      stock_status
      __typename
      description { html }
      short_description { html }
      meta_title
      meta_description
      price_range {
        minimum_price {
          regular_price { value currency }
          final_price { value currency }
          discount { amount_off percent_off }
        }
        maximum_price {
          regular_price { value currency }
          final_price { value currency }
        }
      }
      media_gallery {
        url
        label
        position
        disabled
      }
      related_products {
        sku
        name
        url_key
        price_range {
          minimum_price { final_price { value currency } }
        }
        small_image { url label }
      }
      reviews {
        items {
          summary
          text
          nickname
          average_rating
          created_at
        }
        page_info { total_pages }
      }
      ... on ConfigurableProduct {
        configurable_options {
          attribute_code
          label
          values { label value_index swatch_data { value } }
        }
      }
      ... on BundleProduct {
        items {
          title
          required
          options { label quantity price }
        }
      }
    }
  }
}
```

**Policy Notes**:
- Rate limit: read tier (60/min)
- Authorization: none required (anonymous storefront)
- PII: review nicknames are storefront-public data — no redaction needed
- Only returns enabled, visible products — Magento enforces this at the GraphQL layer

#### Input Schema

```python
class CGetProductInput(BaseModel):
    """Fetch product detail by SKU or URL key."""

    sku: str | None = Field(
        default=None,
        description="Product SKU (e.g. 'WJ12').",
        max_length=64,
    )
    url_key: str | None = Field(
        default=None,
        description="Product URL key (e.g. 'stellar-running-jacket').",
        max_length=255,
    )
    store_scope: str = Field(
        default="default",
        description="Magento store view code.",
        min_length=1,
        max_length=64,
        pattern=r"^[a-z][a-z0-9_]*$",
    )

    @model_validator(mode="after")
    def require_one_identifier(self) -> Self:
        if self.sku is None and self.url_key is None:
            raise ValueError("Provide either sku or url_key.")
        return self
```

#### Output Schema

```python
class MediaItem(BaseModel):
    """Product media gallery image."""

    url: str
    label: str | None
    position: int


class ConfigurableOption(BaseModel):
    """A configurable product option (e.g. Size, Color)."""

    attribute_code: str
    label: str
    values: list[ConfigurableOptionValue]


class ConfigurableOptionValue(BaseModel):
    """A single value for a configurable option."""

    label: str
    value_index: int
    swatch_value: str | None  # hex color or image URL


class BundleOption(BaseModel):
    """A bundle product option group."""

    title: str
    required: bool
    choices: list[BundleChoice]


class BundleChoice(BaseModel):
    """A single choice within a bundle option."""

    label: str
    quantity: Decimal
    price: Decimal


class ReviewSummary(BaseModel):
    """Single product review."""

    summary: str
    text: str
    nickname: str
    average_rating: Decimal
    created_at: str


class RelatedProduct(BaseModel):
    """Minimal related product info."""

    sku: str
    name: str
    url_key: str
    final_price: PriceAmount
    image_url: str | None


class StorefrontProductDetail(BaseModel):
    """Full product detail page data."""

    sku: str
    name: str
    url_key: str
    product_type: str
    stock_status: str
    description: str | None  # HTML content
    short_description: str | None
    meta_title: str | None
    meta_description: str | None

    # Pricing
    min_price: ProductPrice
    max_price: ProductPrice

    # Media
    media_gallery: list[MediaItem]

    # Product-type-specific
    configurable_options: list[ConfigurableOption] | None  # only for ConfigurableProduct
    bundle_options: list[BundleOption] | None  # only for BundleProduct

    # Related
    related_products: list[RelatedProduct]

    # Reviews
    reviews: list[ReviewSummary]
    review_count: int
```

#### Example

**Request**:
```json
{
  "sku": "WJ12"
}
```

**Response**:
```json
{
  "sku": "WJ12",
  "name": "Stellar Running Jacket",
  "url_key": "stellar-running-jacket",
  "product_type": "ConfigurableProduct",
  "stock_status": "IN_STOCK",
  "description": "<p>The Stellar Running Jacket combines lightweight protection with breathable comfort. Wind-resistant outer shell with reflective details for low-light visibility.</p>",
  "short_description": "Lightweight, wind-resistant running jacket with reflective details.",
  "meta_title": "Stellar Running Jacket | Buy Online",
  "meta_description": "Shop the Stellar Running Jacket. Lightweight, wind-resistant with reflective details.",
  "min_price": {
    "regular_price": { "value": 89.99, "currency": "USD" },
    "final_price": { "value": 89.99, "currency": "USD" },
    "discount_amount": null,
    "discount_percent": null
  },
  "max_price": {
    "regular_price": { "value": 89.99, "currency": "USD" },
    "final_price": { "value": 89.99, "currency": "USD" }
  },
  "media_gallery": [
    { "url": "https://magento.example.com/media/catalog/product/w/j/wj12-blue-front.jpg", "label": "Front view", "position": 1 },
    { "url": "https://magento.example.com/media/catalog/product/w/j/wj12-blue-back.jpg", "label": "Back view", "position": 2 },
    { "url": "https://magento.example.com/media/catalog/product/w/j/wj12-blue-detail.jpg", "label": "Reflective detail", "position": 3 }
  ],
  "configurable_options": [
    {
      "attribute_code": "size",
      "label": "Size",
      "values": [
        { "label": "S", "value_index": 167, "swatch_value": null },
        { "label": "M", "value_index": 168, "swatch_value": null },
        { "label": "L", "value_index": 169, "swatch_value": null },
        { "label": "XL", "value_index": 170, "swatch_value": null }
      ]
    },
    {
      "attribute_code": "color",
      "label": "Color",
      "values": [
        { "label": "Blue", "value_index": 56, "swatch_value": "#1857a4" },
        { "label": "Black", "value_index": 49, "swatch_value": "#000000" },
        { "label": "Red", "value_index": 60, "swatch_value": "#c4232b" }
      ]
    }
  ],
  "bundle_options": null,
  "related_products": [
    {
      "sku": "WJ09",
      "name": "Proteus Fitness Jacket",
      "url_key": "proteus-fitness-jacket",
      "final_price": { "value": 94.40, "currency": "USD" },
      "image_url": "https://magento.example.com/media/catalog/product/w/j/wj09-green-front.jpg"
    }
  ],
  "reviews": [
    {
      "summary": "Great lightweight jacket",
      "text": "Perfect for spring runs. The reflective strips are a nice touch for early morning jogs.",
      "nickname": "RunnerMike",
      "average_rating": 90,
      "created_at": "2026-02-10T15:30:00Z"
    }
  ],
  "review_count": 12
}
```

---

### 8. `c_get_store_config`

**Description**: Get store configuration for the current store view. Returns store name, locale, currency, base URLs, and key CMS page links.

**MCP Annotations**: `readOnlyHint=True`, `destructiveHint=False`

**Magento API Surface**:
- Endpoint: `POST /graphql`
- Query: `storeConfig`
- Auth: Anonymous (no token)
- Store header: `Store: {store_scope}`

**GraphQL Query**:
```graphql
query GetStoreConfig {
  storeConfig {
    store_code
    store_name
    store_group_name
    website_name
    locale
    base_currency_code
    default_display_currency_code
    timezone
    weight_unit
    base_url
    base_link_url
    base_media_url
    secure_base_url
    secure_base_link_url
    copyright
    cms_home_page
    cms_no_route
    catalog_default_sort_by
    grid_per_page
    list_per_page
    head_shortcut_icon
    header_logo_src
    logo_alt
    logo_width
    logo_height
    welcome
  }
}
```

**Policy Notes**:
- Rate limit: read tier (60/min)
- Authorization: none required
- PII: none — store config is public
- Caching: response should be cached for 15 minutes (store config changes rarely)

#### Input Schema

```python
class CGetStoreConfigInput(BaseModel):
    """Fetch store configuration."""

    store_scope: str = Field(
        default="default",
        description="Magento store view code.",
        min_length=1,
        max_length=64,
        pattern=r"^[a-z][a-z0-9_]*$",
    )
```

#### Output Schema

```python
class StoreConfig(BaseModel):
    """Public store configuration."""

    store_code: str
    store_name: str
    store_group_name: str
    website_name: str

    # Locale & currency
    locale: str  # e.g. "en_US"
    base_currency_code: str  # e.g. "USD"
    display_currency_code: str  # what the shopper sees
    timezone: str  # e.g. "America/Chicago"
    weight_unit: str  # "lbs" or "kgs"

    # URLs
    base_url: str
    secure_base_url: str
    base_media_url: str

    # Branding
    copyright: str | None
    welcome_message: str | None
    logo_url: str | None
    logo_alt: str | None

    # CMS pages
    cms_home_page: str | None  # CMS page identifier for homepage
    cms_no_route_page: str | None  # 404 page

    # Catalog defaults
    catalog_default_sort_by: str  # e.g. "position"
    grid_per_page: int
    list_per_page: int
```

#### Example

**Request**:
```json
{
  "store_scope": "default"
}
```

**Response**:
```json
{
  "store_code": "default",
  "store_name": "Default Store View",
  "store_group_name": "Main Website Store",
  "website_name": "Main Website",
  "locale": "en_US",
  "base_currency_code": "USD",
  "display_currency_code": "USD",
  "timezone": "America/Chicago",
  "weight_unit": "lbs",
  "base_url": "https://magento.example.com/",
  "secure_base_url": "https://magento.example.com/",
  "base_media_url": "https://magento.example.com/media/",
  "copyright": "Copyright © 2026 Example Store. All rights reserved.",
  "welcome_message": "Welcome to our store!",
  "logo_url": "https://magento.example.com/media/logo/stores/1/logo.svg",
  "logo_alt": "Example Store",
  "cms_home_page": "home",
  "cms_no_route_page": "no-route",
  "catalog_default_sort_by": "position",
  "grid_per_page": 12,
  "list_per_page": 10
}
```

---

## Cross-Namespace Usage Patterns

### Support Agent: Order Lookup + Product Recommendation

A support agent helping a customer find an alternative for an out-of-stock item:

1. `admin_get_order(increment_id="000000042")` — see what the customer ordered
2. `admin_get_inventory(skus=["WJ12-M-Blue"])` — confirm item is out of stock
3. `c_search_products(search="running jacket", in_stock_only=true, price_to=100)` — find alternatives the customer can actually buy
4. `c_get_product(sku="WJ09")` — get full detail on the recommended alternative

The admin tools provide operational context (order details, real inventory). The customer-facing tools provide recommendation data (only products the customer can actually see and purchase).

### Shopping Assistant: Pure Storefront

A customer-facing shopping assistant uses only `c_*` tools:

1. `c_get_store_config()` — determine locale, currency, catalog defaults
2. `c_search_products(search="gift ideas", price_to=50)` — browse catalog
3. `c_get_product(url_key="proteus-fitness-jacket")` — product detail

No admin tools needed — the assistant operates within storefront visibility.

### Ops Dashboard: Pure Admin

An operations agent checking fulfillment status:

1. `admin_search_orders(status="processing", date_from="2026-03-01")` — find unshipped orders
2. `admin_get_order(entity_id=1042)` — check specific order detail
3. `admin_get_inventory(skus=["WJ12-M-Blue", "MT08-L"])` — verify stock for fulfillment
4. `admin_search_products(sku="WJ12%", status=1)` — check product status and variants

No customer-facing tools needed — all data comes from admin context.

---

## Shared Model Definitions

These models are used across multiple tools and live in `src/magemcp/models/`:

```python
# src/magemcp/models/common.py

class PriceAmount(BaseModel):
    """A monetary value with currency."""
    value: Decimal
    currency: str

class ProductPrice(BaseModel):
    """Price with regular, final, and discount info."""
    regular_price: PriceAmount
    final_price: PriceAmount
    discount_amount: Decimal | None = None
    discount_percent: Decimal | None = None

class PageInfo(BaseModel):
    """GraphQL-style pagination info."""
    current_page: int
    page_size: int
    total_pages: int
```

---

## Implementation Sequence

Recommended build order based on dependencies and testing surface:

| Phase | Tools | Rationale |
|-------|-------|-----------|
| 1 | `c_get_store_config` | Simplest tool. Validates GraphQL connector, store scope pattern, caching. No PII concerns. |
| 2 | `c_search_products`, `c_get_product` | Core catalog tools. Validates GraphQL query building, pagination, price/media handling. |
| 3 | `admin_search_products` | First admin tool. Validates REST connector, `searchCriteria` builder, Bearer auth. |
| 4 | `admin_get_inventory` | Tests concurrent API calls (`asyncio.gather`), error handling for missing SKUs. |
| 5 | `admin_search_orders`, `admin_get_order` | Order tools require the most complex redaction logic (`OrderSupportView` DTO). |
| 6 | `admin_get_customer` | Highest PII sensitivity. Requires PII redaction pipeline, `pii_mode` handling, identity verification integration. Build last. |
