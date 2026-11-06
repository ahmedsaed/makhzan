"""Lifting and rigging — hoists, trolleys, slings and blocks.

Separate from the lifting gear in `machinery` (bottle jacks, pallet trucks),
which is workshop handling. Rigging is load-bearing equipment rated by working
load limit and subject to inspection regimes; a rigger and a workshop fitter buy
from different catalogues.
"""

from __future__ import annotations

from makhzan_schemas.domains.base import DomainProfile, register_profile

TAXONOMY: list[tuple[str, str, str, str | None]] = [
    ("hoists", "Hoists", "الروافع", None),
    ("rigging-gear", "Rigging Gear", "معدات التحميل", None),
    ("chain-hoists", "Chain Hoists", "روافع سلسلة", "hoists"),
    ("lever-hoists", "Lever Hoists", "روافع ذراع", "hoists"),
    ("rope-hoists", "Rope Hoists", "روافع حبل", "hoists"),
    ("trolleys", "Trolleys & Clamps", "عربات ومشابك", "hoists"),
    ("rack-jacks", "Rack & Pinion Jacks", "كوريك ترسي", "hoists"),
    ("slings", "Slings", "الأحزمة والسلاسل", "rigging-gear"),
    ("pulleys-blocks", "Pulleys & Blocks", "البكرات", "rigging-gear"),
]

RIGGING = register_profile(
    DomainProfile(
        slug="rigging",
        name_en="Lifting & Rigging",
        name_ar="الرفع والتحميل",
        taxonomy=TAXONOMY,
        category_rules=[],
        search_attributes=("title_en", "title_ar", "brand"),
        identifier_label_en="Capacity / model",
        identifier_label_ar="الحمولة والموديل",
    )
)
