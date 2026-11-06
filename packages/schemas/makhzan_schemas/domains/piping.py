"""Piping and fluid systems — valves, flange gaskets and line fittings.

Flange gaskets live here rather than with `seals-bearings`, even though both are
sealing products. A spiral-wound gasket is specified by flange size and pressure
rating and is bought alongside valves by whoever is building the line; an o-ring
is specified by inside diameter and bought by whoever maintains the machine.
Same physics, different trade and different aisle.
"""

from __future__ import annotations

from makhzan_schemas.domains.base import DomainProfile, register_profile

TAXONOMY: list[tuple[str, str, str, str | None]] = [
    ("valves", "Valves", "المحابس", None),
    ("flange-gaskets", "Flange Gaskets", "جوانات الفلنشات", None),
    ("line-fittings", "Fittings & Accessories", "تجهيزات الخطوط", None),
    ("butterfly-valves", "Butterfly Valves", "محابس فراشة", "valves"),
    ("ball-valves", "Ball Valves", "محابس كروية", "valves"),
    ("globe-valves", "Globe Valves", "محابس جلوب", "valves"),
    ("gate-valves", "Gate Valves", "محابس بوابة", "valves"),
    ("check-valves", "Check Valves", "محابس عدم رجوع", "valves"),
    ("sheet-gaskets", "Gasket Sheets", "ألواح الجوانات", "flange-gaskets"),
    ("spiral-wound-gaskets", "Spiral Wound Gaskets", "جوانات لولبية", "flange-gaskets"),
    ("strainers", "Strainers", "المصافي", "line-fittings"),
    ("flexible-joints", "Flexible Joints", "وصلات مرنة", "line-fittings"),
]

PIPING = register_profile(
    DomainProfile(
        slug="piping",
        name_en="Piping & Fluid Systems",
        name_ar="المواسير وأنظمة السوائل",
        taxonomy=TAXONOMY,
        category_rules=[],
        search_attributes=("title_en", "title_ar", "brand"),
        identifier_label_en="Reference",
        identifier_label_ar="المرجع",
    )
)
