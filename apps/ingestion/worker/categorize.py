"""Category seeding + assignment.

Seeds the taxonomy into the Category table and resolves a listing's supplier
category strings / title onto a taxonomy leaf. Used by both the pipeline (during
ingestion) and the backfill script.
"""

from __future__ import annotations

from makhzan_schemas.db import SessionLocal
from makhzan_schemas.domains import PROFILES, get_profile
from makhzan_schemas.models import Category
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession


#: Postgres advisory lock key held while the taxonomy is written.
CATEGORIES_LOCK_KEY = 0x6D616B687A6374  # "makhzct"


async def seed_categories(session: AsyncSession) -> dict[tuple[str, str], Category]:
    """Idempotently upsert every domain's taxonomy into the Category table, and
    return (domain, slug) -> Category as loaded in `session`.

    Keyed by (domain, slug): slugs are only unique within a vertical, so two
    domains may legitimately both define "tools".

    Written in a short transaction of its own, under an advisory lock, and
    committed at once. Every source's run seeds as it starts, and the daily
    jobs start together: in the run's own transaction, two runs meeting a
    category neither had seen (a fresh database, or a deploy that grew the
    taxonomy) both inserted it, and all but one failed on the unique key. The
    lock is not held in the run's transaction because that stays open until the
    run's first page commits, which a slow host can make minutes.
    """
    async with SessionLocal() as own:
        await own.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": CATEGORIES_LOCK_KEY})
        await _write_taxonomy(own)
        await own.commit()
    return await load_category_index(session)


async def _write_taxonomy(session: AsyncSession) -> None:
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
