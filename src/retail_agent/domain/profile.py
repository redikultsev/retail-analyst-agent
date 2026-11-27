from dataclasses import dataclass

from retail_agent.domain.policy import AllBrands, Brands


@dataclass(frozen=True)
class Profile:
    key: str
    name: str
    role: str
    scope: AllBrands | Brands
