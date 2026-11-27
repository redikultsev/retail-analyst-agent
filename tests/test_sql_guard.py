import pytest
from sqlglot import exp, parse_one

from retail_agent.domain.policy import AllBrands, Brands, Policy
from retail_agent.query.sql_guard import AllowedQuery, Rejected, check

PII = {
    "first_name",
    "last_name",
    "email",
    "street_address",
    "postal_code",
    "latitude",
    "longitude",
    "user_geom",
}
USERS = "`bigquery-public-data`.thelook_ecommerce.users"
CEO = Policy(scope=AllBrands())
MANAGER = Policy(scope=Brands(frozenset({"Diesel"})))
NO_BRANDS = Policy(scope=Brands(frozenset()))


def allowed(sql: str, policy: Policy = MANAGER) -> str:
    verdict = check(sql, policy)
    assert isinstance(verdict, AllowedQuery), verdict
    return verdict.sql


def rejected(sql: str, policy: Policy = MANAGER) -> Rejected:
    verdict = check(sql, policy)
    assert isinstance(verdict, Rejected), verdict
    return verdict


def assert_every_table_is_guarded(sql: str, *, scoped: bool) -> None:
    tree = parse_one(sql, read="bigquery")
    cte_names = {cte.alias for cte in tree.find_all(exp.CTE)}
    tables = list(tree.find_all(exp.Table))
    assert tables
    for table in tables:
        if not table.db:
            assert table.name in cte_names
            continue
        assert (table.catalog, table.db) == ("bigquery-public-data", "thelook_ecommerce")
        select = table.parent_select
        assert select is not None
        assert not select.is_star
        assert {column.alias_or_name for column in select.expressions}.isdisjoint(PII)
        if scoped:
            assert select.args.get("where") is not None


def test_ceo_reads_a_table_without_pii_columns():
    assert allowed("SELECT id FROM users", CEO) == (
        "SELECT id FROM (SELECT id, age, gender, city, state, country, traffic_source, created_at "
        f"FROM {USERS}) AS users LIMIT 501"
    )


def test_manager_sees_only_buyers_of_their_brands():
    sql = allowed("SELECT id FROM users")

    assert "WHERE id IN (SELECT user_id FROM" in sql
    assert "WHERE brand IN ('Diesel')" in sql


def test_manager_sees_only_products_of_their_brands():
    assert "thelook_ecommerce.products WHERE brand IN ('Diesel')) AS p" in allowed(
        "SELECT p.name FROM products AS p"
    )


def test_manager_sees_only_order_items_with_their_products():
    assert "thelook_ecommerce.order_items WHERE product_id IN (SELECT id FROM" in allowed(
        "SELECT sale_price FROM order_items"
    )


def test_manager_sees_only_orders_that_contain_their_products():
    assert "thelook_ecommerce.orders WHERE order_id IN (SELECT order_id FROM" in allowed(
        "SELECT status FROM orders"
    )


def test_brand_names_are_escaped():
    policy = Policy(scope=Brands(frozenset({"Joe's Jeans"})))

    assert r"brand IN ('Joe\'s Jeans')" in allowed("SELECT name FROM products", policy)


@pytest.mark.parametrize("table", ["orders", "order_items", "products", "users"])
def test_empty_scope_returns_no_rows(table: str):
    assert f"thelook_ecommerce.{table} WHERE FALSE)" in allowed(f"SELECT * FROM {table}", NO_BRANDS)


def test_dataset_qualified_column_follows_the_replaced_table():
    sql = allowed("SELECT thelook_ecommerce.users.id FROM thelook_ecommerce.users", CEO)

    assert sql.startswith("SELECT users.id FROM (SELECT id,")


ALLOWED = [
    "SELECT * FROM users",
    "SELECT u.* FROM users AS u",
    "SELECT u FROM users AS u",
    "SELECT TO_JSON_STRING(u) FROM users AS u",
    "SELECT AS STRUCT * FROM users",
    "WITH t AS (SELECT * FROM users) SELECT * FROM t",
    "WITH users AS (SELECT * FROM users) SELECT * FROM users",
    "WITH events AS (SELECT * FROM orders) SELECT * FROM events",
    "SELECT * FROM (SELECT * FROM (SELECT * FROM orders))",
    "SELECT (SELECT COUNT(*) FROM users) AS n",
    "SELECT state FROM users WHERE EXISTS (SELECT 1 FROM orders WHERE user_id = users.id)",
    "SELECT id FROM users UNION ALL SELECT id FROM products",
    "SELECT * FROM `bigquery-public-data.thelook_ecommerce.users`",
    "SELECT * FROM `bigquery-public-data`.thelook_ecommerce.users",
    "SELECT * FROM thelook_ecommerce.users",
    "SELECT * FROM USERS",
    "SELECT * FROM users, orders",
    "SELECT u.state, SUM(oi.sale_price) FROM order_items AS oi "
    "JOIN users AS u ON u.id = oi.user_id GROUP BY 1",
    "SELECT * FROM (SELECT status, user_id FROM orders) "
    "PIVOT(COUNT(user_id) FOR status IN ('Complete', 'Returned'))",
    "SELECT id, ROW_NUMBER() OVER (PARTITION BY state ORDER BY age) AS r FROM users QUALIFY r = 1",
    "WITH RECURSIVE r AS (SELECT 1 AS n UNION ALL SELECT n + 1 FROM r WHERE n < 3) "
    "SELECT r.n, COUNT(*) FROM r JOIN orders ON TRUE GROUP BY 1",
    "SELECT 'a@@b' AS note, COUNT(*) FROM users",
    "SELECT SAFE.PARSE_DATE('%Y', '2024'), COUNT(*) FROM orders",
    "SELECT HLL_COUNT.EXTRACT(HLL_COUNT.INIT(user_id)) FROM orders",
]


@pytest.mark.parametrize("sql", ALLOWED)
@pytest.mark.parametrize("policy", [CEO, MANAGER], ids=["ceo", "manager"])
def test_allowed_query_reads_only_guarded_tables(sql: str, policy: Policy):
    assert_every_table_is_guarded(allowed(sql, policy), scoped=policy is MANAGER)


def test_query_without_tables_is_allowed():
    sql = "SELECT d FROM UNNEST(GENERATE_DATE_ARRAY('2024-01-01', '2024-03-01')) AS d"

    assert allowed(sql).endswith("AS d LIMIT 501")


REJECTED = [
    ("DELETE FROM users WHERE TRUE", "not_select"),
    ("CREATE TABLE x AS SELECT 1", "not_select"),
    ("EXPORT DATA OPTIONS(uri='gs://b/*.csv', format='CSV') AS SELECT id FROM users", "not_select"),
    ("CALL some.proc()", "not_select"),
    ("SELECT * INTO ds.t FROM users", "not_select"),
    ("SELECT 1; SELECT 2", "multiple_statements"),
    ("SELEC id FRM users", "sql_error"),
    ("SELECT", "sql_error"),
    ("SELECT * FROM events", "table_not_allowed"),
    ("SELECT * FROM `bigquery-public-data.samples.shakespeare`", "table_not_allowed"),
    ("SELECT * FROM other.users", "table_not_allowed"),
    (
        "SELECT * FROM `bigquery-public-data.thelook_ecommerce.INFORMATION_SCHEMA.COLUMNS`",
        "table_not_allowed",
    ),
    ("SELECT * FROM `bigquery-public-data.thelook_ecommerce.order*`", "table_not_allowed"),
    ("SELECT * FROM EXTERNAL_QUERY('conn', 'select 1')", "table_function"),
    ("SELECT * FROM ML.PREDICT(MODEL `x.y.z`, (SELECT * FROM users))", "table_function"),
    ("SELECT email FROM users", "pii_column"),
    ("SELECT id FROM users WHERE email LIKE '%acme%'", "pii_column"),
    ("SELECT u.email AS e FROM users AS u", "pii_column"),
    ("SELECT * EXCEPT (email) FROM users", "pii_column"),
    ("SELECT num_of_item FROM orders", "hidden_column"),
    ("SELECT SESSION_USER()", "function_not_allowed"),
    ("SELECT @@project_id", "function_not_allowed"),
    ("SELECT bqutil.fn.int(1.5)", "function_not_allowed"),
    ("SELECT `bqutil.fn.int`(1.5)", "function_not_allowed"),
    ("SELECT `proj.ds.send`(TO_JSON_STRING(u)) FROM users AS u", "function_not_allowed"),
    (
        "SELECT COUNT(*) FROM (users AS u JOIN orders AS o ON o.user_id = u.id)",
        "unsupported_construct",
    ),
    (
        "SELECT * FROM products PIVOT(COUNT(id) FOR department IN ('Men', 'Women'))",
        "unsupported_construct",
    ),
    ("SELECT * FROM users TABLESAMPLE SYSTEM (10 PERCENT)", "unsupported_construct"),
    (
        "SELECT * FROM users FOR SYSTEM_TIME AS OF TIMESTAMP '2024-01-01'",
        "unsupported_construct",
    ),
    ("SELECT 100000 IN UNNEST((SELECT [COUNT(*)] FROM users))", "unsupported_construct"),
    (
        "SELECT 1 IN UNNEST((SELECT [COUNT(*)] FROM thelook_ecommerce.users))",
        "unsupported_construct",
    ),
    (
        "SELECT x FROM UNNEST(GENERATE_ARRAY(0, 9)) AS x "
        "WHERE x IN UNNEST((SELECT [COUNT(*)] FROM INFORMATION_SCHEMA.SCHEMATA)) "
        "AND (SELECT COUNT(*) FROM "
        "(WITH `INFORMATION_SCHEMA.SCHEMATA` AS (SELECT 1 AS c) SELECT 1)) = 1",
        "unsupported_construct",
    ),
    (
        "WITH users AS (SELECT 1 AS x) SELECT (SELECT 1 IN UNNEST((SELECT [COUNT(*)] FROM users)))",
        "unsupported_construct",
    ),
]


@pytest.mark.parametrize(("sql", "code"), REJECTED)
def test_rejects(sql: str, code: str):
    assert rejected(sql).code == code


@pytest.mark.parametrize("sql", [sql for sql, _ in REJECTED])
@pytest.mark.parametrize("policy", [CEO, MANAGER], ids=["ceo", "manager"])
def test_whatever_is_not_rejected_reads_only_guarded_tables(sql: str, policy: Policy):
    verdict = check(sql, policy)

    if isinstance(verdict, AllowedQuery):
        assert_every_table_is_guarded(verdict.sql, scoped=policy is MANAGER)


def test_ceo_may_read_item_count_of_an_order():
    assert "num_of_item" in allowed("SELECT num_of_item FROM orders", CEO)


def test_pii_message_names_every_column_and_the_alternative():
    message = rejected("SELECT first_name, last_name, email FROM users").message

    assert message == (
        "Columns email, first_name, last_name are not available. Identify customers by id."
    )


def test_table_message_lists_available_tables():
    message = rejected("SELECT * FROM events").message

    assert message == (
        "Table events is not available. Available tables: orders, order_items, products, users."
    )


def test_hidden_column_message_points_to_order_items():
    assert "order_items" in rejected("SELECT num_of_item FROM orders").message


def test_reject_message_never_contains_python_error_text():
    assert rejected("SELECT").message == "The query could not be parsed as BigQuery SQL."


@pytest.mark.parametrize(
    ("sql", "ending"),
    [
        ("SELECT id FROM users", "LIMIT 501"),
        ("SELECT id FROM users ORDER BY age DESC LIMIT 10", "ORDER BY age DESC LIMIT 10"),
        ("SELECT id FROM users LIMIT 100000", "LIMIT 501"),
        ("SELECT id FROM users LIMIT 10 OFFSET 20", "LIMIT 10 OFFSET 20"),
        (
            "(SELECT id FROM users) UNION ALL (SELECT id FROM products) ORDER BY 1",
            "ORDER BY 1 LIMIT 501",
        ),
        ("WITH t AS (SELECT id FROM users LIMIT 5) SELECT * FROM t", "FROM t LIMIT 501"),
    ],
)
def test_row_limit_is_applied_to_the_top_level_query(sql: str, ending: str):
    assert allowed(sql, CEO).endswith(ending)


def test_row_limit_comes_from_the_policy():
    assert allowed("SELECT id FROM users", Policy(scope=AllBrands(), row_limit=50)).endswith(
        "LIMIT 51"
    )


def test_row_limit_must_be_positive():
    with pytest.raises(ValueError, match="row_limit"):
        Policy(scope=AllBrands(), row_limit=0)


def test_internal_failure_is_rejected_and_logged(monkeypatch, caplog):
    def broken(_query):
        raise RuntimeError("boom")

    monkeypatch.setattr("retail_agent.query.sql_guard.traverse_scope", broken)

    verdict = rejected("SELECT id FROM users")

    assert verdict.code == "guard_error"
    assert "boom" not in verdict.message
    assert "sql_guard failed" in caplog.text


def test_parse_error_says_where_the_query_broke() -> None:
    message = rejected("SELECT (1 FROM users").message

    assert message == "The query could not be parsed as BigQuery SQL near line 1, column 14."
