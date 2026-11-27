from retail_agent.domain.policy import AllBrands, Brands, describe
from retail_agent.query.warehouse import Refused, Warehouse

BRANDS_QUERY = "SELECT DISTINCT brand FROM products"


class WarehouseNotReady(Exception):
    def __init__(self, text: str, *, unreachable: bool = False) -> None:
        super().__init__(text)
        self.unreachable = unreachable


async def verify(warehouse: Warehouse) -> frozenset[str]:
    """Return the brands of the warehouse's scope that are missing from the data."""
    scope = warehouse.scope
    if isinstance(scope, Brands) and not scope.names:
        raise WarehouseNotReady("This user has no brands assigned.")
    outcome = await warehouse.run(BRANDS_QUERY)
    if isinstance(outcome, Refused):
        detail = outcome.log.detail
        cause = f": {detail.rstrip('.')}" if detail else ""
        raise WarehouseNotReady(
            f"The data warehouse is not ready ({outcome.log.status}){cause}.",
            unreachable=outcome.log.status == "unavailable",
        )
    if isinstance(scope, AllBrands) or outcome.log.truncated:
        return frozenset()
    present = {row[0] for row in outcome.rows}
    if not scope.names & present:
        raise WarehouseNotReady(f"None of this user's brands is in the data: {describe(scope)}.")
    return scope.names - present
