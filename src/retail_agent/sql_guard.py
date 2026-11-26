"""Decides whether model-written SQL may run and rewrites it to read only permitted data.

Data access is guaranteed by construction: every table is replaced by a subquery with the
visible columns and the brand filter, and a query is allowed only if no other table is left.
The column and function checks on top of that are a short deny-list: clear messages for
columns the subquery already hides, and no calls that reach outside the dataset.
"""

import logging
from dataclasses import dataclass

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError
from sqlglot.optimizer.scope import Scope, traverse_scope

from retail_agent.schema import (
    CATALOG,
    DATASET,
    HIDDEN_FROM_BRAND_SCOPE,
    PII_COLUMNS,
    VISIBLE_COLUMNS,
)

logger = logging.getLogger(__name__)
# sqlglot warns when it falls back to an opaque command; check() rejects that case itself.
logging.getLogger("sqlglot").addFilter(
    lambda record: "Falling back to parsing as a 'Command'" not in record.getMessage()
)

DIALECT = "bigquery"
BUILTIN_NAMESPACES = frozenset({"HLL_COUNT"})
# Anything else attached to a table node (PIVOT, TABLESAMPLE, a parenthesised join) would be
# lost when the node is replaced.
PLAIN_TABLE_ARGS = frozenset({"this", "db", "catalog", "alias"})
GUARDED = "guarded"
CTE_REFERENCE = "cte_reference"


@dataclass(frozen=True)
class AllBrands:
    pass


@dataclass(frozen=True)
class Brands:
    names: frozenset[str]


@dataclass(frozen=True)
class Policy:
    scope: AllBrands | Brands
    row_limit: int = 500

    def __post_init__(self) -> None:
        if self.row_limit < 1:
            raise ValueError("row_limit must be at least 1")


@dataclass(frozen=True)
class Allowed:
    sql: str


@dataclass(frozen=True)
class Rejected:
    code: str
    message: str


class _Reject(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.verdict = Rejected(code, message)


def check(sql: str, policy: Policy) -> Allowed | Rejected:
    try:
        query = _parse(sql)
        _check_columns(query, policy)
        _check_functions(query)
        _replace_tables(query, policy)
        _require_no_other_tables(query)
        _apply_row_limit(query, policy.row_limit)
        return Allowed(query.sql(dialect=DIALECT))
    except _Reject as reject:
        return reject.verdict
    except Exception:
        logger.exception("sql_guard failed on a query it could not handle")
        return Rejected(
            "unsupported_construct",
            "The query uses a construct that cannot be verified. Rewrite it in a simpler form.",
        )


def _parse(sql: str) -> exp.Query:
    unparsable = _Reject("sql_error", "The query could not be parsed as BigQuery SQL.")
    try:
        statements = [s for s in sqlglot.parse(sql, read=DIALECT) if s is not None]
    except SqlglotError:
        raise unparsable from None
    if not statements:
        raise unparsable
    if len(statements) > 1:
        raise _Reject("multiple_statements", "Send exactly one SELECT statement.")
    statement = statements[0]
    if not isinstance(statement, exp.Query) or statement.find(exp.Into):
        raise _Reject("not_select", "Only SELECT statements are allowed.")
    if isinstance(statement, exp.Select) and not statement.expressions:
        raise unparsable
    return statement


def _check_columns(query: exp.Query, policy: Policy) -> None:
    names = {column.name.lower() for column in query.find_all(exp.Column)}
    pii = sorted(names & PII_COLUMNS)
    if pii:
        subject = f"Column {pii[0]} is" if len(pii) == 1 else f"Columns {', '.join(pii)} are"
        raise _Reject("pii_column", f"{subject} not available. Identify customers by id.")
    hidden = sorted(names & HIDDEN_FROM_BRAND_SCOPE)
    if isinstance(policy.scope, Brands) and hidden:
        raise _Reject(
            "hidden_column",
            f"Column {hidden[0]} is not available for a brand scope. "
            "Count rows in order_items instead.",
        )


def _check_functions(query: exp.Query) -> None:
    for node in query.find_all(exp.SessionUser, exp.Parameter, exp.Dot, exp.Anonymous):
        if isinstance(node, exp.SessionUser):
            what = "SESSION_USER"
        elif _is_system_variable(node):
            what = "System variables (@@)"
        elif _is_foreign_function(node):
            what = f"Function {node.sql(dialect=DIALECT).split('(')[0]}"
        else:
            continue
        raise _Reject("function_not_allowed", f"{what} is not available.")


def _is_system_variable(node: exp.Expr) -> bool:
    # @@name parses as a parameter wrapped in a parameter.
    return isinstance(node, exp.Parameter) and isinstance(node.this, exp.Parameter)


def _is_foreign_function(node: exp.Expr) -> bool:
    """A function called through a project or dataset path, with or without backticks."""
    if isinstance(node, exp.Anonymous):
        return "." in node.name
    return (
        isinstance(node, exp.Dot)
        and isinstance(node.expression, exp.Func)
        and node.this.sql(dialect=DIALECT).upper() not in BUILTIN_NAMESPACES
    )


def _replace_tables(query: exp.Query, policy: Policy) -> None:
    for table in _real_tables(query):
        name = _permitted_name(table)
        table.replace(_guarded_table(name, table.alias_or_name, policy.scope))
    _drop_dataset_path_from_columns(query)


def _real_tables(query: exp.Query) -> list[exp.Table]:
    """Tables read from the warehouse. References to a CTE are marked and left in place."""
    real: list[exp.Table] = []
    for scope in traverse_scope(query):
        for table in scope.tables:
            if isinstance(scope.sources.get(table.alias_or_name), Scope):
                table.meta[CTE_REFERENCE] = True
            else:
                real.append(table)
    return real


def _permitted_name(table: exp.Table) -> str:
    if not isinstance(table.this, exp.Identifier):
        raise _Reject("table_function", "Table functions are not available.")
    parts = [part.name for part in table.parts]
    name = parts[-1].lower()
    if name not in VISIBLE_COLUMNS or tuple(parts[:-1]) not in ((), (DATASET,), (CATALOG, DATASET)):
        raise _Reject(
            "table_not_allowed",
            f"Table {'.'.join(parts)} is not available. "
            f"Available tables: {', '.join(VISIBLE_COLUMNS)}.",
        )
    alias = table.args.get("alias")
    has_extras = any(value for key, value in table.args.items() if key not in PLAIN_TABLE_ARGS)
    if has_extras or (alias is not None and alias.args.get("columns")):
        raise _Reject(
            "unsupported_construct",
            f"Select from {name} in a subquery before applying PIVOT, TABLESAMPLE, "
            "FOR SYSTEM_TIME, column aliases or a parenthesised join.",
        )
    return name


def _guarded_table(name: str, alias: str, scope: AllBrands | Brands) -> exp.Subquery:
    columns = [
        column
        for column in VISIBLE_COLUMNS[name]
        if isinstance(scope, AllBrands) or column not in HIDDEN_FROM_BRAND_SCOPE
    ]
    select = exp.select(*columns).from_(_dataset_table(name))
    if isinstance(scope, Brands):
        select = select.where(_brand_filter(name, scope.names))
    for table in select.find_all(exp.Table):
        table.meta[GUARDED] = True
    return select.subquery(alias=alias)


def _dataset_table(name: str) -> exp.Table:
    return exp.table_(name, db=DATASET, catalog=CATALOG)


def _brand_filter(table: str, brands: frozenset[str]) -> exp.Condition:
    if not brands:
        return exp.false()
    match table:
        case "products":
            return _is_brand(brands)
        case "order_items":
            return _has_brand_product(brands)
        case "orders":
            return _in_brand_items("order_id", "order_id", brands)
        case "users":
            return _in_brand_items("id", "user_id", brands)
        case _:
            raise ValueError(f"no brand filter for table {table}")


def _is_brand(brands: frozenset[str]) -> exp.Condition:
    return exp.column("brand").isin(*(exp.Literal.string(brand) for brand in sorted(brands)))


def _has_brand_product(brands: frozenset[str]) -> exp.Condition:
    products = exp.select("id").from_(_dataset_table("products")).where(_is_brand(brands))
    return exp.column("product_id").isin(query=products)


def _in_brand_items(column: str, item_column: str, brands: frozenset[str]) -> exp.Condition:
    """The column matches `item_column` of an order item with a product of these brands."""
    order_items = _dataset_table("order_items")
    items = exp.select(item_column).from_(order_items).where(_has_brand_product(brands))
    return exp.column(column).isin(query=items)


def _drop_dataset_path_from_columns(query: exp.Query) -> None:
    """`thelook_ecommerce.users.id` becomes `users.id`, the alias of the replaced table."""
    for column in query.find_all(exp.Column):
        if column.db == DATASET and column.catalog in ("", CATALOG):
            column.set("db", None)
            column.set("catalog", None)


def _require_no_other_tables(query: exp.Query) -> None:
    # The scope walk misses tables in some places, for example a subquery inside
    # IN UNNEST(...). Whatever it missed is still a plain table here and gets rejected.
    cte_names = {cte.alias.lower() for cte in query.find_all(exp.CTE)}
    for table in query.find_all(exp.Table):
        if table.meta.get(GUARDED):
            continue
        # A name with a dataset or with dots is never a CTE, even if a CTE is named like it.
        is_cte_reference = (
            table.meta.get(CTE_REFERENCE)
            and not table.db
            and table.name.isidentifier()
            and table.name.lower() in cte_names
        )
        if not is_cte_reference:
            raise _Reject(
                "unsupported_construct",
                "A table is used in a place that cannot be verified. "
                "Move the subquery into a WITH clause or a JOIN.",
            )


def _apply_row_limit(query: exp.Query, row_limit: int) -> None:
    current = query.args.get("limit")
    if current is not None:
        count = current.expression
        if isinstance(count, exp.Literal) and count.is_int and int(count.name) <= row_limit:
            return
    query.limit(row_limit + 1, copy=False)
