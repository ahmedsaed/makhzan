"""Welding and cutting — machines, torches and the consumables that feed them.

Split out of one marketplace's "Machinery & Industrial Equipment", which is nearly half
welding by product count. Welding is its own trade with its own repeat-purchase
pattern: a welder buys nozzles, liners, tips and electrodes continuously, and
would not expect to find them filed beside pallet trucks and concrete mixers.
"""

from __future__ import annotations

from makhzan_schemas.domains.base import DomainProfile, register_profile

TAXONOMY: list[tuple[str, str, str, str | None]] = [
    ("welding-equipment", "Welding & Cutting Machines", "ماكينات اللحام والقطع", None),
    ("torch-consumables", "Torches & Consumables", "الشعلات والمستهلكات", None),
    ("welding-accessories", "Accessories", "الملحقات", None),
    ("welding-machines", "Welding Machines", "ماكينات لحام", "welding-equipment"),
    ("cutting-machines", "Cutting Machines", "ماكينات قطع", "welding-equipment"),
    ("welding-torches", "Welding Torches", "شعلات لحام", "torch-consumables"),
    ("cutting-torches", "Cutting Torches", "شعلات قطع", "torch-consumables"),
    ("torch-parts", "Torch Parts", "قطع الشعلات", "torch-consumables"),
    ("electrodes", "Electrodes & Rods", "أسياخ اللحام", "torch-consumables"),
    ("electrode-holders", "Electrode Holders", "حوامل الأسياخ", "torch-consumables"),
    ("earth-clamps", "Earth Clamps", "مشابك الأرضي", "torch-consumables"),
    ("gas-regulators", "Gas Regulators", "منظّمات الغاز", "welding-accessories"),
    ("flashback-arrestors", "Flashback Arrestors", "مانع ارتداد اللهب", "welding-accessories"),
    ("welding-magnets", "Welding Magnets", "مغناطيس اللحام", "welding-accessories"),
    ("rod-heaters", "Rod Heaters & Ovens", "أفران تسخين الأسياخ", "welding-accessories"),
    ("torch-heaters", "Heating Torches", "شعلات تسخين", "welding-accessories"),
    ("torch-lighters", "Torch Lighters", "قداحات الشعلة", "welding-accessories"),
    ("chipping-hammers", "Chipping Hammers", "شواكيش إزالة الخبث", "welding-accessories"),
]

WELDING = register_profile(
    DomainProfile(
        slug="welding",
        name_en="Welding & Cutting",
        name_ar="اللحام والقطع",
        taxonomy=TAXONOMY,
        category_rules=[],
        search_attributes=("title_en", "title_ar", "brand"),
        identifier_label_en="Model",
        identifier_label_ar="الموديل",
    )
)
