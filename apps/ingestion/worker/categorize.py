"""Category seeding + assignment.

Seeds the taxonomy into the Category table and resolves a listing's supplier
category strings / title onto a taxonomy leaf. Used by both the pipeline (during
ingestion) and the backfill script.
"""

from __future__ import annotations

from makhzan_schemas.domains import PROFILES, get_profile
from makhzan_schemas.models import Category
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def seed_categories(session: AsyncSession) -> dict[tuple[str, str], Category]:
    """Idempotently upsert every domain's taxonomy into the Category table.

    Keyed by (domain, slug): slugs are only unique within a vertical, so two
    domains may legitimately both define "tools".
    """
    existing = {(c.domain, c.slug): c for c in (await session.execute(select(Category))).scalars()}

    for profile in PROFILES.values():
        for slug, name_en, name_ar, _parent in profile.taxonomy:
            cat = existing.get((profile.slug, slug))
            if cat is None:
                cat = Category(domain=profile.slug, slug=slug, name_en=name_en, name_ar=name_ar)
                session.add(cat)
                existing[(profile.slug, slug)] = cat
            else:
                cat.name_en, cat.name_ar = name_en, name_ar
    await session.flush()

    # Second pass: parent links + materialized path (parents exist now).
    for profile in PROFILES.values():
        for slug, _en, _ar, parent in profile.taxonomy:
            cat = existing[(profile.slug, slug)]
            if parent:
                cat.parent_id = existing[(profile.slug, parent)].id
                cat.path = f"/{parent}/{slug}"
            else:
                cat.parent_id = None
                cat.path = f"/{slug}"
    await session.flush()
    return existing


async def load_category_index(session: AsyncSession) -> dict[tuple[str, str], Category]:
    """(domain, slug) -> Category, for mapping resolved slugs to rows."""
    return {(c.domain, c.slug): c for c in (await session.execute(select(Category))).scalars()}


def category_slug_for(
    attributes: dict | None, title: str | None, domain: str | None = None
) -> str | None:
    """Resolve a taxonomy leaf slug from a listing's attributes + title."""
    strings: list[str] = []
    if isinstance(attributes, dict):
        cats = attributes.get("categories")
        if isinstance(cats, list):
            strings.extend(str(c) for c in cats)
        product_type = attributes.get("product_type")
        if product_type:
            strings.append(str(product_type))
    return get_profile(domain).resolve_category_slug(strings, title)
