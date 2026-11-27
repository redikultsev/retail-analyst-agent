import sqlite3

import pytest

from retail_agent.report_repository import ReportRepository, ReportsUnavailable


def test_saved_report_is_found_by_its_owner(reports) -> None:
    saved = reports.add("ben", "talk-1", "Diesel returns", "Returns grew in March.")

    assert reports.find("ben") == [saved]


def test_report_of_someone_else_is_not_found(reports) -> None:
    reports.add("chloe", "talk-1", "Polo revenue", "body")

    assert reports.find("ben") == []


def test_search_looks_at_the_title_and_the_body(reports) -> None:
    by_title = reports.add("ben", "talk-1", "Diesel returns", "body")
    by_body = reports.add("ben", "talk-1", "Returns", "Mostly Diesel jeans.")
    reports.add("ben", "talk-1", "Joe's Jeans revenue", "body")

    assert reports.find("ben", mentioning="Diesel") == [by_title, by_body]


def test_search_ignores_case(reports) -> None:
    saved = reports.add("ben", "talk-1", "Diesel returns", "body")

    assert reports.find("ben", mentioning="dIESEL") == [saved]


@pytest.mark.parametrize("sign", ["%", "_"])
def test_wildcard_signs_are_searched_as_plain_text(reports, sign) -> None:
    reports.add("ben", "talk-1", "Diesel returns", "body")

    assert reports.find("ben", mentioning=sign) == []


def test_this_conversation_finds_only_its_own_reports(reports) -> None:
    reports.add("ben", "talk-1", "Diesel returns", "body")
    today = reports.add("ben", "talk-2", "Joe's Jeans revenue", "body")

    assert reports.find("ben", conversation_id="talk-2") == [today]


def test_reports_are_found_by_id(reports) -> None:
    first = reports.add("ben", "talk-1", "Diesel returns", "body")
    reports.add("ben", "talk-1", "Joe's Jeans revenue", "body")

    assert reports.find("ben", ids=[first.id, 999]) == [first]


def test_deleted_report_is_no_longer_found(reports) -> None:
    first = reports.add("ben", "talk-1", "Diesel returns", "body")
    kept = reports.add("ben", "talk-1", "Joe's Jeans revenue", "body")

    reports.delete("ben", [first.id])

    assert reports.find("ben") == [kept]


def test_delete_says_how_many_reports_it_deleted(reports) -> None:
    first = reports.add("ben", "talk-1", "Diesel returns", "body")
    second = reports.add("ben", "talk-1", "Joe's Jeans revenue", "body")

    assert reports.delete("ben", [first.id, second.id, 999]) == 2


def test_report_of_someone_else_cannot_be_deleted(reports) -> None:
    theirs = reports.add("chloe", "talk-1", "Polo revenue", "body")

    assert reports.delete("ben", [theirs.id]) == 0
    assert reports.find("chloe") == [theirs]


def test_deleted_report_stays_in_the_database_with_a_deletion_date(reports, tmp_path) -> None:
    first = reports.add("ben", "talk-1", "Diesel returns", "body")

    reports.delete("ben", [first.id])

    connection = sqlite3.connect(tmp_path / "retail_agent.db")
    title, deleted_at = connection.execute("SELECT title, deleted_at FROM reports").fetchone()
    connection.close()
    assert title == "Diesel returns"
    assert deleted_at is not None


def test_unusable_database_is_reported_as_reports_unavailable(tmp_path) -> None:
    (tmp_path / "retail_agent.db").mkdir()

    with pytest.raises(ReportsUnavailable):
        ReportRepository(tmp_path / "retail_agent.db")


def test_unusable_folder_is_reported_as_reports_unavailable(tmp_path) -> None:
    (tmp_path / "taken").write_text("not a folder")

    with pytest.raises(ReportsUnavailable):
        ReportRepository(tmp_path / "taken" / "retail_agent.db")
