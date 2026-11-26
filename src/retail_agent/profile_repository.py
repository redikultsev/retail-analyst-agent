import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from retail_agent.policy import AllBrands, Brands
from retail_agent.profile import Profile

SCHEMA = """
CREATE TABLE IF NOT EXISTS profiles (
    user_key TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    role TEXT NOT NULL,
    all_brands INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS profile_brands (
    user_key TEXT NOT NULL REFERENCES profiles (user_key),
    brand TEXT NOT NULL,
    PRIMARY KEY (user_key, brand)
);
"""


DEMO_PEOPLE = (
    Profile("alice", "Alice Carter", "CEO", AllBrands()),
    Profile("ben", "Ben Ortiz", "Brand manager", Brands(frozenset({"Diesel", "Joe's Jeans"}))),
    Profile("chloe", "Chloe Nguyen", "Brand manager", Brands(frozenset({"Polo Ralph Lauren"}))),
)


class ProfileError(Exception):
    pass


class UnknownUser(ProfileError):
    def __init__(self, key: str, known: list[str]) -> None:
        self.known = known
        super().__init__(f"Unknown user '{key}'. Known users: {', '.join(known)}.")


class ProfilesUnavailable(ProfileError):
    def __init__(self, database: Path, cause: Exception) -> None:
        super().__init__(f"Cannot use the profile database at {database}: {cause}.")


class ProfileRepository:
    def __init__(self, database: Path) -> None:
        self._database = database
        try:
            database.parent.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise ProfilesUnavailable(database, error) from error
        with self._connect() as connection:
            connection.executescript(SCHEMA)
            if not connection.execute("SELECT 1 FROM profiles LIMIT 1").fetchone():
                _add_demo_people(connection)

    def all(self) -> list[Profile]:
        with self._connect() as connection:
            people = connection.execute(
                "SELECT user_key, name, role, all_brands FROM profiles ORDER BY user_key"
            ).fetchall()
            brands = connection.execute("SELECT user_key, brand FROM profile_brands").fetchall()
        return [
            Profile(key, name, role, _scope(all_brands, key, brands))
            for key, name, role, all_brands in people
        ]

    def get(self, key: str) -> Profile:
        wanted = key.strip().lower()
        people = self.all()
        for person in people:
            if person.key.lower() == wanted:
                return person
        raise UnknownUser(key, [person.key for person in people])

    @contextmanager
    def _connect(self) -> Generator[sqlite3.Connection]:
        try:
            connection = sqlite3.connect(self._database)
            try:
                with connection:
                    yield connection
            finally:
                connection.close()
        except sqlite3.Error as error:
            raise ProfilesUnavailable(self._database, error) from error


def _scope(all_brands: int, key: str, brands: list[tuple[str, str]]) -> AllBrands | Brands:
    if all_brands:
        return AllBrands()
    return Brands(frozenset(brand for owner, brand in brands if owner == key))


def _add_demo_people(connection: sqlite3.Connection) -> None:
    for person in DEMO_PEOPLE:
        sees_everything = isinstance(person.scope, AllBrands)
        connection.execute(
            "INSERT OR IGNORE INTO profiles (user_key, name, role, all_brands) VALUES (?, ?, ?, ?)",
            (person.key, person.name, person.role, sees_everything),
        )
        if isinstance(person.scope, Brands):
            connection.executemany(
                "INSERT OR IGNORE INTO profile_brands (user_key, brand) VALUES (?, ?)",
                [(person.key, brand) for brand in sorted(person.scope.names)],
            )
