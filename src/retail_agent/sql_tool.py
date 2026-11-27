import json

from langchain.tools import tool
from langchain_core.tools import BaseTool

from retail_agent.policy import AllBrands, Brands, describe
from retail_agent.warehouse import Answered, Refused, Warehouse

NOT_FULL = "This is not the full result: do not present totals or counts from it."


def sql_tool(warehouse: Warehouse) -> BaseTool:
    @tool
    async def run_sql(sql: str) -> str:
        """Run one BigQuery SELECT over orders, order_items, products and users.

        Returns the rows as JSON, or the reason the query was refused.
        """
        return tool_result(await warehouse.run(sql), warehouse.scope)

    return run_sql


def tool_result(outcome: Answered | Refused, scope: AllBrands | Brands) -> str:
    if isinstance(outcome, Refused):
        return json.dumps({"status": outcome.log.status, "message": outcome.message})
    result: dict[str, object] = {"columns": outcome.columns, "rows": outcome.rows}
    if outcome.log.truncated:
        result["note"] = NOT_FULL
    if isinstance(scope, Brands):
        result["scope"] = f"{describe(scope)} only"
    return json.dumps(result, default=str, ensure_ascii=False)
