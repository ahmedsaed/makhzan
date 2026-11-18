"""Photography and video gear — lights, tripods, bags and camera accessories.

Distinct from `electronics`: a studio strobe, a fluid-head tripod or a camera
cage is bought by a photographer or a videographer for a shoot, not by someone
building a circuit. The electronics shops that stock it file it under tags of
its own, and until this department existed it either went uncategorized or
landed in "Accessories" and "LEDs & Optoelectronics" by keyword.

Cameras themselves are not here. What the catalogue sells as a camera is a
camera module, a depth camera, an endoscope or a webcam, and those are
electronics (`electronics:cameras`).

Small on purpose: four leaves, one for each kind of thing the shops actually
group together. It is filled by crosswalk only. Keyword inference runs under a
listing's supplier domain, and no supplier's default domain is photography, so
rules here would never be consulted; none are written.
"""

from __future__ import annotations

from makhzan_schemas.domains.base import DomainProfile, register_profile

TAXONOMY: list[tuple[str, str, str, str | None]] = [
    ("lighting", "Lighting", "الإضاءة", None),
    ("camera-gear", "Camera Gear", "معدات الكاميرا", None),
    ("photo-lights", "Photo & Video Lights", "إضاءة التصوير والفيديو", "lighting"),
    ("tripods", "Tripods & Stands", "الحوامل والستاندات", "camera-gear"),
    ("camera-bags", "Camera Bags", "حقائب الكاميرات", "camera-gear"),
    ("camera-accessories", "Camera Accessories", "إكسسوارات الكاميرات", "camera-gear"),
]

PHOTOGRAPHY = register_profile(
    DomainProfile(
        slug="photography",
        name_en="Photography & Video",
        name_ar="التصوير والفيديو",
        taxonomy=TAXONOMY,
        category_rules=[],
        search_attributes=("title_en", "title_ar", "brand"),
        identifier_label_en="Model",
        identifier_label_ar="الموديل",
    )
)
