"""Safety — personal protective equipment and fire protection.

One domain covering both, deliberately. They are bought by the same person for
the same reason: a site or facility meeting its safety obligations. Splitting a
131-product fire catalogue into a vertical of its own would leave both halves too
thin to browse, and an HSE buyer looking for helmets and extinguishers in one
visit would have to know which domain to be in.

Note what is *not* here. The largest marketplace files flashlights (110 products) and webbing
slings under PPE; a torch is a work light and a sling is rigging gear. Both are
corrected in the crosswalk — that is what a curated mapping is for.
"""

from __future__ import annotations

from makhzan_schemas.domains.base import DomainProfile, register_profile

TAXONOMY: list[tuple[str, str, str, str | None]] = [
    ("personal-protection", "Personal Protection", "الوقاية الشخصية", None),
    ("fire-protection", "Fire Protection", "مكافحة الحريق", None),
    ("gloves", "Gloves", "القفازات", "personal-protection"),
    ("safety-footwear", "Safety Footwear", "أحذية السلامة", "personal-protection"),
    ("eye-protection", "Eye Protection", "حماية العين", "personal-protection"),
    ("head-protection", "Head Protection", "الخوذات", "personal-protection"),
    ("welding-protection", "Welding Protection", "أقنعة اللحام", "personal-protection"),
    ("hearing-protection", "Hearing Protection", "حماية السمع", "personal-protection"),
    ("respiratory", "Respiratory Protection", "أقنعة التنفس", "personal-protection"),
    ("workwear", "Workwear & Hi-Vis", "ملابس العمل", "personal-protection"),
    ("knee-protection", "Knee Protection", "واقيات الركبة", "personal-protection"),
    ("first-aid", "First Aid", "الإسعافات الأولية", "personal-protection"),
    ("safety-signage", "Safety Signage", "لافتات التحذير", "personal-protection"),
    ("fire-extinguishers", "Fire Extinguishers", "طفايات الحريق", "fire-protection"),
    ("fire-alarms", "Fire Alarms & Evacuation", "إنذار وإخلاء", "fire-protection"),
    ("fire-cabinets", "Cabinets, Reels & Racks", "خزائن وبكرات الحريق", "fire-protection"),
    ("rescue-equipment", "Rescue Equipment", "معدات الإنقاذ", "fire-protection"),
]

SAFETY = register_profile(
    DomainProfile(
        slug="safety",
        name_en="Safety & Protection",
        name_ar="السلامة والوقاية",
        taxonomy=TAXONOMY,
        category_rules=[],
        search_attributes=("title_en", "title_ar", "brand"),
        identifier_label_en="Standard / size",
        identifier_label_ar="المواصفة والمقاس",
    )
)
