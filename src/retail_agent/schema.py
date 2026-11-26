"""The part of the dataset the agent may read."""

CATALOG = "bigquery-public-data"
DATASET = "thelook_ecommerce"

VISIBLE_COLUMNS: dict[str, tuple[str, ...]] = {
    "orders": (
        "order_id",
        "user_id",
        "status",
        "gender",
        "created_at",
        "returned_at",
        "shipped_at",
        "delivered_at",
        "num_of_item",
    ),
    "order_items": (
        "id",
        "order_id",
        "user_id",
        "product_id",
        "inventory_item_id",
        "status",
        "created_at",
        "shipped_at",
        "delivered_at",
        "returned_at",
        "sale_price",
    ),
    "products": (
        "id",
        "cost",
        "category",
        "name",
        "brand",
        "retail_price",
        "department",
        "sku",
        "distribution_center_id",
    ),
    "users": (
        "id",
        "age",
        "gender",
        "city",
        "state",
        "country",
        "traffic_source",
        "created_at",
    ),
}

PII_COLUMNS = frozenset(
    {
        "first_name",
        "last_name",
        "email",
        "street_address",
        "postal_code",
        "latitude",
        "longitude",
        "user_geom",
    }
)

# orders.num_of_item counts items of every brand in the order.
HIDDEN_FROM_BRAND_SCOPE = frozenset({"num_of_item"})
