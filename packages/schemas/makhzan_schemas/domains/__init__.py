"""Domain profiles. Importing this package registers every built-in vertical."""

from makhzan_schemas.domains.base import (
    DEFAULT_DOMAIN,
    PROFILES,
    CategoryRule,
    DomainProfile,
    TaxonomyNode,
    get_profile,
    register_profile,
)
from makhzan_schemas.domains.automotive import AUTOMOTIVE
from makhzan_schemas.domains.chemicals import CHEMICALS
from makhzan_schemas.domains.cleaning import CLEANING
from makhzan_schemas.domains.electrical import ELECTRICAL
from makhzan_schemas.domains.electronics import ELECTRONICS
from makhzan_schemas.domains.garden import GARDEN
from makhzan_schemas.domains.machinery import MACHINERY
from makhzan_schemas.domains.materials import MATERIALS
from makhzan_schemas.domains.piping import PIPING
from makhzan_schemas.domains.rigging import RIGGING
from makhzan_schemas.domains.safety import SAFETY
from makhzan_schemas.domains.seals_bearings import SEALS_BEARINGS
from makhzan_schemas.domains.security import SECURITY
from makhzan_schemas.domains.timber import TIMBER
from makhzan_schemas.domains.welding import WELDING
from makhzan_schemas.domains.tools import TOOLS

__all__ = [
    "DEFAULT_DOMAIN",
    "PROFILES",
    "CategoryRule",
    "DomainProfile",
    "AUTOMOTIVE",
    "CHEMICALS",
    "CLEANING",
    "ELECTRICAL",
    "ELECTRONICS",
    "GARDEN",
    "MACHINERY",
    "MATERIALS",
    "PIPING",
    "RIGGING",
    "SAFETY",
    "SEALS_BEARINGS",
    "SECURITY",
    "TIMBER",
    "WELDING",
    "TOOLS",
    "TaxonomyNode",
    "get_profile",
    "register_profile",
]
