"""Garden and outdoor equipment.

Lifted out of `tools`, where it was originally filed. That was a mistake of the
kind this project is trying to avoid: mowers, hedge trimmers, shovels and
irrigation sprinklers ended up under Tools because they had nowhere else to go,
not because a groundskeeper and a fitter shop the same way. A vertical gets its
own domain unless it is genuinely the same trade.
"""

from __future__ import annotations

from makhzan_schemas.domains.base import DomainProfile, register_profile

TAXONOMY: list[tuple[str, str, str, str | None]] = [
    ("garden-hand-tools", "Garden Hand Tools", "أدوات حدائق يدوية", None),
    ("garden-power-equipment", "Garden Power Equipment", "معدات حدائق كهربائية", None),
    ("irrigation", "Irrigation", "الري", None),
    ("digging-tools", "Digging & Earth Tools", "أدوات الحفر", "garden-hand-tools"),
    ("cutting-garden", "Pruning & Cutting", "التقليم والقطع", "garden-hand-tools"),
    ("mowers-trimmers", "Mowers & Trimmers", "ماكينات القص والتشذيب", "garden-power-equipment"),
    (
        "garden-power-other",
        "Other Garden Power Tools",
        "معدات حدائق أخرى",
        "garden-power-equipment",
    ),
    ("sprinklers", "Sprinklers & Watering", "الرشاشات والري", "irrigation"),
]

GARDEN = register_profile(
    DomainProfile(
        slug="garden",
        name_en="Garden & Outdoor",
        name_ar="الحدائق والمساحات الخارجية",
        taxonomy=TAXONOMY,
        category_rules=[],
        search_attributes=("title_en", "title_ar", "brand"),
        identifier_label_en="Model",
        identifier_label_ar="الموديل",
    )
)
