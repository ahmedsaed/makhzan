"""Industrial materials — rubber, resins, flooring and building stock.

What remains of the source's "Industrial & Construction Materials" once timber is
separated out: sheet rubber, casting resins and pigments, safety and sports
flooring, insulation. Sold by the sheet, the roll or the kilo rather than as a
finished article.
"""

from __future__ import annotations

from makhzan_schemas.domains.base import DomainProfile, register_profile

TAXONOMY: list[tuple[str, str, str, str | None]] = [
    ("rubber-plastics", "Rubber & Plastics", "المطاط والبلاستيك", None),
    ("resins-casting", "Resins & Casting", "الراتنجات والصب", None),
    ("flooring", "Flooring", "الأرضيات", None),
    ("building-materials", "Building Materials", "مواد البناء", None),
    ("rubber-sheet", "Rubber Sheet", "ألواح مطاط", "rubber-plastics"),
    ("anti-vibration-pads", "Anti-Vibration Pads", "قواعد مانعة للاهتزاز", "rubber-plastics"),
    ("membranes", "Membranes", "الأغشية العازلة", "rubber-plastics"),
    ("epoxy-resins", "Epoxy Resins", "راتنج إيبوكسي", "resins-casting"),
    ("polyester-resins", "Polyester Resins", "راتنج بوليستر", "resins-casting"),
    ("casting-pigments", "Pigments & Colourants", "الأصباغ", "resins-casting"),
    (
        "decorative-aggregates",
        "Decorative Stone & Sand",
        "الأحجار والرمال الملوّنة",
        "resins-casting",
    ),
    ("safety-flooring", "Safety Flooring", "أرضيات الأمان", "flooring"),
    ("sports-flooring", "Sports & Play Flooring", "أرضيات رياضية", "flooring"),
    ("floor-mats", "Mats", "الدعاسات", "flooring"),
    ("insulation", "Insulation", "مواد العزل", "building-materials"),
    ("parking-supplies", "Parking & Traffic", "مستلزمات المواقف", "building-materials"),
    ("metal-stock", "Metal Stock", "خامات معدنية", "building-materials"),
]

MATERIALS = register_profile(
    DomainProfile(
        slug="materials",
        name_en="Industrial Materials",
        name_ar="الخامات الصناعية",
        taxonomy=TAXONOMY,
        category_rules=[],
        search_attributes=("title_en", "title_ar", "brand"),
        identifier_label_en="Grade / size",
        identifier_label_ar="النوع والمقاس",
    )
)
