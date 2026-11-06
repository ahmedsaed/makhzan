"""Timber — hardwood stock and the finishes that go on it.

The README has promised wood since day one; this is it. The largest marketplace files these
under "Industrial & Construction Materials", but 424 of that group's 752 products
are hardwood boards — oak, teak, mahogany, wenge, padauk — which is a timber
merchant's catalogue, not a materials one. A joiner buying oak is not the buyer
looking for anti-vibration matting.

Species are leaves rather than attributes because that is how the trade shops:
you go looking for oak, then for a size.
"""

from __future__ import annotations

from makhzan_schemas.domains.base import DomainProfile, register_profile

TAXONOMY: list[tuple[str, str, str, str | None]] = [
    ("hardwood", "Hardwood", "الأخشاب الصلبة", None),
    ("wood-finishes", "Wood Finishes", "دهانات ومعالجة الأخشاب", None),
    ("oak", "Oak", "زان أوك", "hardwood"),
    ("teak", "Teak", "تيك", "hardwood"),
    ("mahogany", "Mahogany", "ماهوجني", "hardwood"),
    ("pine", "Pine", "سنوبر", "hardwood"),
    ("walnut", "Walnut", "جوز", "hardwood"),
    ("wenge", "Wenge", "ونجيه", "hardwood"),
    ("padauk", "Padauk", "بادوك", "hardwood"),
    ("engineered-wood", "Engineered Wood", "أخشاب مصنّعة", "hardwood"),
    ("wood-stains", "Stains & Dyes", "صبغات الأخشاب", "wood-finishes"),
    ("wood-oils-waxes", "Oils & Waxes", "زيوت وشمع", "wood-finishes"),
    ("wood-fillers", "Fillers", "معجون الأخشاب", "wood-finishes"),
]

TIMBER = register_profile(
    DomainProfile(
        slug="timber",
        name_en="Timber & Wood",
        name_ar="الأخشاب",
        taxonomy=TAXONOMY,
        category_rules=[],
        search_attributes=("title_en", "title_ar", "brand"),
        identifier_label_en="Species / size",
        identifier_label_ar="النوع والمقاس",
    )
)
