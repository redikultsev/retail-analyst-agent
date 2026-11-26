from dataclasses import dataclass

from retail_agent.policy import AllBrands, Brands


@dataclass(frozen=True)
class Profile:
    key: str
    name: str
    role: str
    scope: AllBrands | Brands
