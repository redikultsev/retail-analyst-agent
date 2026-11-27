import pytest
from fakes import StubClient

from retail_agent.config import load_settings
from retail_agent.di import build_warehouse
from retail_agent.policy import Brands
from retail_agent.profile import Profile

BEN = Profile("ben", "Ben Ortiz", "Brand manager", Brands(frozenset({"Diesel"})))


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> StubClient:
    stub = StubClient()
    monkeypatch.setattr("retail_agent.bigquery_executor.bigquery.Client", lambda project: stub)
    return stub


async def test_warehouse_filters_queries_by_the_brands_of_the_profile(
    required_env: None, client: StubClient
) -> None:
    await build_warehouse(load_settings(env_file=None), BEN).run("SELECT name FROM products")

    sql, _ = client.sent[-1]
    assert "Diesel" in sql


async def test_row_limit_comes_from_the_settings(
    required_env: None, client: StubClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RESULT_MAX_ROWS", "7")

    await build_warehouse(load_settings(env_file=None), BEN).run("SELECT name FROM products")

    assert client.options["max_results"] == 8
