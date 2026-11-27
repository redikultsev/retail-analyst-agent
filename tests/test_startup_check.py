import pytest
from fakes import FakeExecutor, brands

from retail_agent.policy import AllBrands, Brands, Policy
from retail_agent.startup_check import WarehouseNotReady, verify
from retail_agent.warehouse import Warehouse

BEN_SCOPE = Brands(frozenset({"Diesel", "Joe's Jeans"}))


def warehouse(executor: FakeExecutor, scope: AllBrands | Brands, row_limit: int = 500) -> Warehouse:
    return Warehouse(
        executor,
        Policy(scope=scope, row_limit=row_limit),
        max_bytes=1_000_000,
        max_result_chars=20_000,
        secrets=(),
    )


async def test_ceo_is_ready_when_the_warehouse_answers() -> None:
    executor = FakeExecutor(fetch=brands("Diesel", "Wacoal"))

    assert await verify(warehouse(executor, AllBrands())) == set()


async def test_manager_is_ready_when_every_brand_is_in_the_data() -> None:
    executor = FakeExecutor(fetch=brands("Diesel", "Joe's Jeans"))

    assert await verify(warehouse(executor, BEN_SCOPE)) == set()


async def test_brands_missing_from_the_data_are_named() -> None:
    executor = FakeExecutor(fetch=brands("Diesel"))

    assert await verify(warehouse(executor, BEN_SCOPE)) == {"Joe's Jeans"}


async def test_manager_with_no_brand_in_the_data_is_not_ready() -> None:
    executor = FakeExecutor(fetch=brands())

    with pytest.raises(WarehouseNotReady, match="Diesel"):
        await verify(warehouse(executor, BEN_SCOPE))


async def test_manager_without_brands_is_not_ready_and_nothing_is_queried() -> None:
    executor = FakeExecutor()

    with pytest.raises(WarehouseNotReady):
        await verify(warehouse(executor, Brands(frozenset())))

    assert executor.estimates == []


async def test_refusal_from_the_warehouse_is_reported_with_its_cause() -> None:
    executor = FakeExecutor(estimate=RuntimeError("no credentials found"))

    with pytest.raises(WarehouseNotReady, match="no credentials found"):
        await verify(warehouse(executor, BEN_SCOPE))


async def test_cut_brand_list_does_not_name_missing_brands() -> None:
    executor = FakeExecutor(fetch=brands("Diesel", "Joe's Jeans"))

    assert await verify(warehouse(executor, BEN_SCOPE, row_limit=1)) == set()


async def test_warehouse_that_cannot_be_reached_is_marked_as_such() -> None:
    executor = FakeExecutor(estimate=RuntimeError("ProjectId must be non-empty"))

    with pytest.raises(WarehouseNotReady) as raised:
        await verify(warehouse(executor, BEN_SCOPE))

    assert raised.value.unreachable


@pytest.mark.parametrize("executor", [FakeExecutor(fetch=brands()), FakeExecutor(estimate=10**9)])
async def test_other_reasons_are_not_marked_as_unreachable(executor: FakeExecutor) -> None:

    with pytest.raises(WarehouseNotReady) as raised:
        await verify(warehouse(executor, BEN_SCOPE))

    assert not raised.value.unreachable
