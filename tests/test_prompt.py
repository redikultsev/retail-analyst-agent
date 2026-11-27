from datetime import date

from retail_agent.policy import AllBrands, Brands
from retail_agent.profile import Profile
from retail_agent.prompt import system_prompt
from retail_agent.schema import PII_COLUMNS, VISIBLE_COLUMNS

TODAY = date(2026, 11, 27)
ALICE = Profile("alice", "Alice Carter", "CEO", AllBrands())
BEN = Profile("ben", "Ben Ortiz", "Brand manager", Brands(frozenset({"Diesel", "Joe's Jeans"})))


def test_prompt_names_the_person_and_the_role() -> None:
    text = system_prompt(BEN, TODAY)

    assert "Ben Ortiz" in text
    assert "Brand manager" in text


def test_prompt_states_todays_date() -> None:
    assert "2026-11-27" in system_prompt(ALICE, TODAY)


def test_prompt_lists_every_table_with_its_visible_columns() -> None:
    text = system_prompt(ALICE, TODAY)

    for table, columns in VISIBLE_COLUMNS.items():
        assert table in text
        for column in columns:
            assert column in text


def test_prompt_never_names_a_personal_column() -> None:
    text = system_prompt(ALICE, TODAY)

    for column in PII_COLUMNS:
        assert column not in text


def test_brand_manager_is_told_their_brands() -> None:
    text = system_prompt(BEN, TODAY)

    assert "Diesel" in text
    assert "Joe's Jeans" in text


def test_brand_manager_is_not_offered_the_column_that_counts_other_brands() -> None:
    assert "num_of_item" not in system_prompt(BEN, TODAY)
    assert "num_of_item" in system_prompt(ALICE, TODAY)
