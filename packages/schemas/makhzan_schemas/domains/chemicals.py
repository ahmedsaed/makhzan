"""Chemicals, lubricants and adhesives — the consumables shelf.

Bought by the same person maintaining the machine, but a different purchase from
a bearing or a valve: shelf life matters, quantity matters, and selection is by
application (threadlocking, rust removal, sealing a joint) rather than by a
dimension or a catalogue reference.
"""

from __future__ import annotations

from makhzan_schemas.domains.base import DomainProfile, register_profile

TAXONOMY: list[tuple[str, str, str, str | None]] = [
    ("adhesives", "Adhesives", "المواد اللاصقة", None),
    ("lubricants", "Lubricants", "الزيوت والشحوم", None),
    ("coatings", "Paints & Coatings", "الدهانات والطلاءات", None),
    ("sealants-fillers", "Sealants & Fillers", "مواد السد والحشو", None),
    ("maintenance-chemicals", "Maintenance Chemicals", "كيماويات الصيانة", None),
    ("industrial-adhesives", "Industrial Adhesives", "لواصق صناعية", "adhesives"),
    ("instant-adhesives", "Instant Adhesives", "لواصق فورية", "adhesives"),
    ("construction-adhesives", "Construction Adhesives", "لواصق البناء", "adhesives"),
    ("adhesive-tapes", "Adhesive Tapes", "الشرائط اللاصقة", "adhesives"),
    ("greases", "Greases", "الشحوم", "lubricants"),
    ("oils-fluids", "Oils & Fluids", "الزيوت والسوائل", "lubricants"),
    ("spray-paints", "Spray Paints", "بويات الرش", "coatings"),
    ("paints", "Paints", "الدهانات", "coatings"),
    ("silicone-sealants", "Silicone Sealants", "سيليكون", "sealants-fillers"),
    ("sealants", "Sealants", "مواد السد", "sealants-fillers"),
    ("foams", "Foams", "الفوم", "sealants-fillers"),
    ("rust-removers", "Rust Removers", "مزيلات الصدأ", "maintenance-chemicals"),
    ("general-chemicals", "General Chemicals", "كيماويات عامة", "maintenance-chemicals"),
]

CHEMICALS = register_profile(
    DomainProfile(
        slug="chemicals",
        name_en="Chemicals & Lubricants",
        name_ar="الكيماويات والزيوت",
        taxonomy=TAXONOMY,
        category_rules=[],
        search_attributes=("title_en", "title_ar", "brand"),
        identifier_label_en="Product code",
        identifier_label_ar="كود المنتج",
    )
)
