"""Seals, bearings and machine maintenance parts.

The largest marketplace files these under "Equipment Spare Parts", which undersells them: 90%
of the catalog is sealing (o-rings, oil seals, mechanical seals, gland packing)
and bearings. The rest — filters, lubricators, PTFE stock, sight glasses — is the
same trade: consumable wear parts a maintenance engineer replaces on running
machinery. Named for what it is rather than for the source's label.

Its own domain rather than a corner of `tools`: someone sourcing an o-ring by
inside diameter and someone buying a cordless drill are not the same buyer.

Identifiers are designations: a bearing's (6205-2RS, with the seal and
clearance suffixes that make it a different product), an O-ring's size and an
oil seal's dimensions and profile. Only one supplier stocks this domain today,
and grouping never merges two listings of one shop, so these create no group
yet; they start working, every veto intact, the day a second bearings source
arrives.
"""

from __future__ import annotations

from makhzan_schemas.domains.base import DomainProfile, register_profile
from makhzan_schemas.identifiers import bearing_designation, o_ring_size, oil_seal_size

TAXONOMY: list[tuple[str, str, str, str | None]] = [
    # Groups
    ("sealing", "Seals & Gaskets", "منتجات الإحكام والجوانات", None),
    ("bearings-transmission", "Bearings & Transmission", "الرولمان بلي والحركة", None),
    ("filtration", "Filtration", "الفلاتر", None),
    ("lubrication", "Lubrication", "التزييت", None),
    ("sealing-materials", "Sealing Materials", "خامات الإحكام", None),
    ("machine-fittings", "Fittings & Spares", "التجهيزات وقطع الغيار", None),
    # Sealing
    ("o-rings", "O-Rings", "حلقات أورينج", "sealing"),
    ("oil-seals", "Oil Seals", "أويل سيل", "sealing"),
    ("mechanical-seals", "Mechanical Seals", "سيل ميكانيكي", "sealing"),
    ("gland-packing", "Gland Packing", "حشو الجلاند", "sealing"),
    ("gaskets", "Gaskets", "الجوانات", "sealing"),
    # Bearings & transmission
    ("bearings", "Bearings", "الرولمان بلي", "bearings-transmission"),
    ("couplings", "Couplings", "الوصلات المرنة", "bearings-transmission"),
    # Filtration
    ("air-filters", "Air Filters", "فلاتر هواء", "filtration"),
    ("oil-filters", "Oil Filters", "فلاتر زيت", "filtration"),
    ("fuel-filters", "Fuel Filters", "فلاتر وقود", "filtration"),
    ("hydraulic-filters", "Hydraulic Filters", "فلاتر هيدروليك", "filtration"),
    ("water-filters", "Water Filters", "فلاتر مياه", "filtration"),
    ("filter-regulators", "Filter Regulators", "منظّمات الفلاتر", "filtration"),
    # Lubrication
    ("oil-cups", "Oil Cups & Lubricators", "كؤوس التزييت", "lubrication"),
    ("auto-lubricators", "Automatic Lubricators", "أنظمة تزييت أوتوماتيكية", "lubrication"),
    # Sealing materials (stock shapes machined into seals and gaskets)
    ("ptfe-stock", "PTFE Sheet & Rod", "ألواح وقضبان تفلون", "sealing-materials"),
    ("graphite-mica", "Graphite & Mica", "الجرافيت والميكا", "sealing-materials"),
    ("sealing-tape", "Sealing Tape", "شرائط الإحكام", "sealing-materials"),
    # Fittings & spares
    ("sight-glasses", "Sight Glasses", "زجاج بيان المستوى", "machine-fittings"),
    ("machine-spares", "Machine Spares", "قطع غيار المعدات", "machine-fittings"),
]

SEALS_BEARINGS = register_profile(
    DomainProfile(
        slug="seals-bearings",
        name_en="Seals & Bearings",
        name_ar="منتجات الإحكام والرولمان",
        taxonomy=TAXONOMY,
        # Sources for this vertical publish their own categories; they are mapped
        # through a crosswalk, never inferred from titles.
        category_rules=[],
        identifier_rules=(bearing_designation, o_ring_size, oil_seal_size),
        search_attributes=("title_en", "title_ar", "brand"),
        identifier_label_en="Reference",
        identifier_label_ar="المرجع",
    )
)
