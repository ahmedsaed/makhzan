"""Industrial machinery — pumps, power equipment, lifting gear and site plant.

What remains of the largest marketplace's "Machinery & Industrial Equipment" once welding is
split out into its own domain. These are capital items and site plant rather than
consumables: a pump, a generator, a pallet truck, a concrete mixer.
"""

from __future__ import annotations

from makhzan_schemas.domains.base import DomainProfile, register_profile

TAXONOMY: list[tuple[str, str, str, str | None]] = [
    ("pumps", "Pumps", "المضخات", None),
    ("power-equipment", "Power Equipment", "معدات الطاقة", None),
    ("lifting-handling", "Lifting & Handling", "الرفع والمناولة", None),
    ("concrete-equipment", "Concrete Equipment", "معدات الخرسانة", None),
    ("machinery-accessories", "Machinery Accessories", "ملحقات المعدات", None),
    ("surface-pumps", "Surface Pumps", "مضخات سطحية", "pumps"),
    ("submersible-pumps", "Submersible Pumps", "مضخات غاطسة", "pumps"),
    ("general-pumps", "Other Pumps", "مضخات أخرى", "pumps"),
    ("pump-controllers", "Pump Controllers", "لوحات تحكّم المضخات", "pumps"),
    ("generators", "Generators", "المولدات", "power-equipment"),
    ("air-compressors", "Air Compressors", "ضواغط الهواء", "power-equipment"),
    ("engines-motors", "Engines & Motors", "المواتير والمحركات", "power-equipment"),
    ("machine-tools", "Machine Tools & CNC", "مكن ومراكز تشغيل", "power-equipment"),
    ("jacks", "Jacks", "الكوريك", "lifting-handling"),
    ("pallet-trucks", "Pallet Trucks", "عربات الباليت", "lifting-handling"),
    ("hydraulic-presses", "Hydraulic Presses", "مكابس هيدروليك", "lifting-handling"),
    ("concrete-mixers", "Concrete Mixers", "خلاطات خرسانة", "concrete-equipment"),
    ("concrete-vibrators", "Concrete Vibrators", "هزّازات الخرسانة", "concrete-equipment"),
    ("concrete-saws", "Concrete Saws", "مناشير الخرسانة", "concrete-equipment"),
    ("concrete-tools", "Concrete Tools", "أدوات الخرسانة", "concrete-equipment"),
    ("lubrication-equipment", "Lubrication Equipment", "معدات التزييت", "machinery-accessories"),
    ("hydraulic-components", "Hydraulic Components", "مكوّنات هيدروليك", "machinery-accessories"),
    ("machine-connectors", "Machine Connectors", "وصلات المعدات", "machinery-accessories"),
]

MACHINERY = register_profile(
    DomainProfile(
        slug="machinery",
        name_en="Industrial Machinery",
        name_ar="المعدات الصناعية",
        taxonomy=TAXONOMY,
        category_rules=[],
        search_attributes=("title_en", "title_ar", "brand"),
        identifier_label_en="Model",
        identifier_label_ar="الموديل",
    )
)
