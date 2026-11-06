"""Automotive — vehicle diagnostics, servicing and accessories.

Its own domain rather than a corner of `tools`. A garage buys by vehicle system —
battery, fuel, alignment — and its equipment does not generalise: an oil drain
machine is useful nowhere else.
"""

from __future__ import annotations

from makhzan_schemas.domains.base import DomainProfile, register_profile

TAXONOMY: list[tuple[str, str, str, str | None]] = [
    ("vehicle-diagnostics", "Diagnostics", "أجهزة الفحص", None),
    ("vehicle-service", "Servicing Equipment", "معدات الصيانة", None),
    ("vehicle-accessories", "Accessories & Consumables", "الملحقات والمستهلكات", None),
    (
        "battery-testers",
        "Battery & Alternator Testers",
        "أجهزة فحص البطاريات",
        "vehicle-diagnostics",
    ),
    ("electrical-testers", "Electrical Testers", "أجهزة الفحص الكهربائي", "vehicle-diagnostics"),
    ("alignment", "Alignment Equipment", "أجهزة الضبط", "vehicle-diagnostics"),
    ("oil-service", "Oil & Fluid Service", "خدمة الزيوت والسوائل", "vehicle-service"),
    ("body-shop", "Body Shop Equipment", "معدات السمكرة", "vehicle-service"),
    ("vehicle-cleaning", "Vehicle Cleaning Equipment", "معدات غسيل السيارات", "vehicle-service"),
    ("booster-cables", "Booster Cables", "كابلات الشحن", "vehicle-accessories"),
    ("tie-downs", "Tie-Downs", "أحزمة التثبيت", "vehicle-accessories"),
    ("car-care", "Car Care", "العناية بالسيارة", "vehicle-accessories"),
    ("belts", "Belts", "السيور", "vehicle-accessories"),
]

AUTOMOTIVE = register_profile(
    DomainProfile(
        slug="automotive",
        name_en="Automotive",
        name_ar="السيارات",
        taxonomy=TAXONOMY,
        category_rules=[],
        search_attributes=("title_en", "title_ar", "brand"),
        identifier_label_en="Model",
        identifier_label_ar="الموديل",
    )
)
