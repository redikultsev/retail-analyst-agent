import sqlite3
from pathlib import Path

import pytest

from retail_agent.policy import AllBrands, Brands
from retail_agent.profile import Profile
from retail_agent.profile_repository import ProfileRepository, ProfilesUnavailable, UnknownUser


@pytest.fixture
def database(tmp_path: Path) -> Path:
    return tmp_path / "data" / "retail_agent.db"


def test_new_store_starts_with_three_people(database: Path) -> None:
    people = ProfileRepository(database).all()

    assert [person.key for person in people] == ["alice", "ben", "chloe"]


def test_ceo_sees_all_brands(database: Path) -> None:
    alice = ProfileRepository(database).get("alice")

    assert alice == Profile(key="alice", name="Alice Carter", role="CEO", scope=AllBrands())


def test_manager_sees_only_their_brands(database: Path) -> None:
    store = ProfileRepository(database)

    assert store.get("ben").scope == Brands(frozenset({"Diesel", "Joe's Jeans"}))
    assert store.get("chloe").scope == Brands(frozenset({"Polo Ralph Lauren"}))


def test_user_key_ignores_case_and_spaces(database: Path) -> None:
    store = ProfileRepository(database)

    assert store.get(" Ben ") == store.get("ben")


def test_unknown_user_names_the_known_ones(database: Path) -> None:
    with pytest.raises(UnknownUser) as raised:
        ProfileRepository(database).get("dave")

    assert raised.value.known == ["alice", "ben", "chloe"]
    assert "dave" in str(raised.value)


def test_missing_directory_is_created(database: Path) -> None:
    ProfileRepository(database)

    assert database.exists()


def test_reopening_does_not_add_people_twice(database: Path) -> None:
    ProfileRepository(database)

    assert len(ProfileRepository(database).all()) == 3


def test_brands_edited_by_hand_survive_reopening(database: Path) -> None:
    ProfileRepository(database)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO profile_brands (user_key, brand) VALUES ('chloe', 'Wacoal')"
        )

    chloe = ProfileRepository(database).get("chloe")

    assert chloe.scope == Brands(frozenset({"Polo Ralph Lauren", "Wacoal"}))


def test_key_added_by_hand_with_capital_letters_is_found(database: Path) -> None:
    ProfileRepository(database)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO profiles (user_key, name, role, all_brands) "
            "VALUES ('Dave', 'Dave Klein', 'CFO', 1)"
        )

    assert ProfileRepository(database).get("dave").name == "Dave Klein"


def test_folder_that_cannot_be_created_is_reported(tmp_path: Path) -> None:
    (tmp_path / "data").write_text("not a folder")

    with pytest.raises(ProfilesUnavailable):
        ProfileRepository(tmp_path / "data" / "retail_agent.db")


def test_damaged_database_is_reported(database: Path) -> None:
    database.parent.mkdir()
    database.write_bytes(b"this is not a database" * 100)

    with pytest.raises(ProfilesUnavailable):
        ProfileRepository(database)
