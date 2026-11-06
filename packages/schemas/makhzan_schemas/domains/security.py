"""Security and access control — installed systems, not components.

Distinct from `electronics`: an intercom panel or a fingerprint reader is
specified and installed as a system by a security contractor, not assembled from
parts. Small today, but it is a real trade with its own suppliers.
"""

from __future__ import annotations

from makhzan_schemas.domains.base import DomainProfile, register_profile

TAXONOMY: list[tuple[str, str, str, str | None]] = [
    ("access-control", "Access Control", "التحكّم في الدخول", None),
    ("surveillance", "Surveillance", "المراقبة", None),
    ("security-equipment", "Security Equipment", "معدات الأمن", None),
    ("door-access", "Door Access", "أنظمة الأبواب", "access-control"),
    ("intercoms", "Intercoms", "الإنتركم", "access-control"),
    ("biometrics", "Biometric Readers", "أجهزة البصمة", "access-control"),
    ("recorders", "Recorders", "أجهزة التسجيل", "surveillance"),
    ("remote-controls", "Remote Controls", "أجهزة التحكّم", "security-equipment"),
    ("cash-handling", "Cash Handling", "أجهزة عدّ النقود", "security-equipment"),
]

SECURITY = register_profile(
    DomainProfile(
        slug="security",
        name_en="Security & Access",
        name_ar="الأمن والتحكّم في الدخول",
        taxonomy=TAXONOMY,
        category_rules=[],
        search_attributes=("title_en", "title_ar", "brand"),
        identifier_label_en="Model",
        identifier_label_ar="الموديل",
    )
)
