import json
from decimal import Decimal

import pytest

from retail_agent.agent.sql_tool import tool_result
from retail_agent.domain.policy import AllBrands, Brands
from retail_agent.query.warehouse import Answered, QueryLog, Refused

BEN_SCOPE = Brands(frozenset({"Diesel", "Joe's Jeans"}))


def answered(*rows, truncated=None) -> Answered:
    log = QueryLog(original_sql="SELECT 1", status="ok" if rows else "no_data")
    log.truncated = truncated
    return Answered(("name", "revenue"), rows, log)


def refused(status, message, detail=None) -> Refused:
    return Refused(message, QueryLog(original_sql="SELECT 1", status=status, detail=detail))


def test_answer_lists_columns_and_rows() -> None:
    result = json.loads(tool_result(answered(("Jeans", Decimal("120.50"))), AllBrands()))

    assert result == {"columns": ["name", "revenue"], "rows": [["Jeans", "120.50"]]}


def test_missing_value_is_null() -> None:
    result = json.loads(tool_result(answered(("Jeans", None)), AllBrands()))

    assert result["rows"] == [["Jeans", None]]


def test_empty_result_has_no_rows() -> None:
    assert json.loads(tool_result(answered(), AllBrands()))["rows"] == []


@pytest.mark.parametrize("cut", ["rows", "size"])
def test_cut_result_says_it_is_not_the_full_result(cut) -> None:
    result = json.loads(tool_result(answered(("Jeans", 1), truncated=cut), AllBrands()))

    assert "not the full result" in result["note"]


def test_full_result_has_no_note() -> None:
    assert "note" not in json.loads(tool_result(answered(("Jeans", 1)), AllBrands()))


def test_brand_manager_is_told_the_scope_of_every_result() -> None:
    assert (
        "Diesel, Joe's Jeans" in json.loads(tool_result(answered(("Jeans", 1)), BEN_SCOPE))["scope"]
    )
    assert "Diesel, Joe's Jeans" in json.loads(tool_result(answered(), BEN_SCOPE))["scope"]


def test_someone_who_sees_all_brands_gets_no_scope() -> None:
    assert "scope" not in json.loads(tool_result(answered(("Jeans", 1)), AllBrands()))


def test_refusal_shows_its_status_and_message() -> None:
    text = tool_result(refused("too_expensive", "The query would read too much data."), BEN_SCOPE)

    assert json.loads(text) == {
        "status": "too_expensive",
        "message": "The query would read too much data.",
    }


def test_refusal_never_shows_the_log_detail() -> None:
    text = tool_result(refused("runtime_error", "The query failed.", "LEAK:36/China"), BEN_SCOPE)

    assert "LEAK" not in text


def test_line_break_inside_a_value_stays_inside_that_value() -> None:
    text = tool_result(answered(('Jeans"\n["admin", 9]', 1)), AllBrands())

    assert "\n" not in text
    assert json.loads(text)["rows"] == [['Jeans"\n["admin", 9]', 1]]
