"""Industrial cleaning equipment — pressure washers, vacuums and floor machines.

Equipment rather than chemicals: the consumable side (degreasers, detergents)
belongs with `chemicals`. This is the machine a contractor buys once.
"""

from __future__ import annotations

from makhzan_schemas.domains.base import DomainProfile, register_profile

TAXONOMY: list[tuple[str, str, str, str | None]] = [
    ("cleaning-equipment", "Cleaning Equipment", "معدات النظافة", None),
    ("cleaning-accessories", "Accessories", "الملحقات", None),
    ("pressure-washers", "Pressure Washers", "ماكينات ضغط الماء", "cleaning-equipment"),
    ("vacuum-cleaners", "Vacuum Cleaners", "المكانس", "cleaning-equipment"),
    ("floor-machines", "Floor Machines", "ماكينات تنظيف الأرضيات", "cleaning-equipment"),
    ("foam-machines", "Foam Machines", "ماكينات الرغوة", "cleaning-equipment"),
    ("washer-accessories", "Washer Accessories", "ملحقات الغسيل", "cleaning-accessories"),
]

CLEANING = register_profile(
    DomainProfile(
        slug="cleaning",
        name_en="Cleaning Equipment",
        name_ar="معدات النظافة",
        taxonomy=TAXONOMY,
        category_rules=[],
        search_attributes=("title_en", "title_ar", "brand"),
        identifier_label_en="Model",
        identifier_label_ar="الموديل",
    )
)
