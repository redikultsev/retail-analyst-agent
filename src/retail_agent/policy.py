from dataclasses import dataclass


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
