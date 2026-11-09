"""Adapter registry, built from the `sources` table.

Which suppliers exist, and how each is crawled, is data: one `Source` row per
source, seeded from `sources.toml` (see worker/sources/sync.py). The adapters
here hold no supplier knowledge of their own — `build_adapter` turns a row into
one by picking the class and passing the row's settings as constructor
arguments, so adding or disabling a source never requires a code change.

The pipeline looks adapters up by `source_id`. `load_adapters` rebuilds the
registry from the table each time it is called, so the daily refresh picks up a
changed row without a restart.
"""

from __future__ import annotations

import importlib
import logging

from makhzan_schemas.db import SessionLocal
from makhzan_schemas.domains.crosswalks import load_crosswalk
from makhzan_schemas.models import Source
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from worker.sources.base import SourceAdapter, SupplierInfo

log = logging.getLogger(__name__)

#: Adapter types usable by name. Anything else in `Source.adapter` is read as an
#: import path, which is how an adapter kept in another package is wired in.
BUILTIN_ADAPTERS = {
    "fixture": "worker.sources.fixture:FixtureAdapter",
    "odoo": "worker.sources.odoo:OdooAdapter",
    "shopify": "worker.sources.shopify:ShopifyAdapter",
    "wix": "worker.sources.wix:WixStoresAdapter",
    "woocommerce": "worker.sources.woocommerce:WooCommerceAdapter",
}

_REGISTRY: dict[str, SourceAdapter] = {}


def adapter_class(adapter: str) -> type[SourceAdapter]:
    """Resolve a built-in adapter name or a "package.module:Class" path."""
    target = BUILTIN_ADAPTERS.get(adapter, adapter)
    module_name, sep, class_name = target.partition(":")
    if not sep:
        raise ValueError(
            f"unknown adapter {adapter!r}: expected one of {sorted(BUILTIN_ADAPTERS)} "
            "or an import path like 'package.module:Class'"
        )
    cls = getattr(importlib.import_module(module_name), class_name)
    if not (isinstance(cls, type) and issubclass(cls, SourceAdapter)):
        raise TypeError(f"{target} is not a SourceAdapter")
    return cls


def build_adapter(source: Source) -> SourceAdapter:
    """Construct the adapter a Source row describes.

    `config` is passed through as keyword arguments, so a key the adapter does
    not accept is a TypeError here rather than a setting silently ignored. The
    one key resolved on the way is `crosswalk`, a file name, which becomes the
    `categories` table — and, for a source browsed by category, the
    `partition_keys` to sweep, or for a tag-cloud source its `prefer` order.
    """
    options = dict(source.config or {})
    crosswalk = options.pop("crosswalk", None)
    if crosswalk is not None:
        loaded = load_crosswalk(crosswalk)
        options["categories"] = loaded.categories
        if loaded.partitions:
            options["partition_keys"] = loaded.partitions
        if loaded.prefer:
            # Only a source that reads several tags per listing takes this; any
            # other adapter refuses the keyword, which is the right failure.
            options["prefer"] = loaded.prefer
    if source.base_url is not None:
        options["base_url"] = source.base_url
    adapter = adapter_class(source.adapter)(
        source_id=source.source_id,
        supplier=SupplierInfo(**source.supplier),
        enabled=source.enabled,
        **options,
    )
    if crosswalk is not None and loaded.ignore:
        # Read only by the drift check, so set here rather than passed in:
        # every adapter has it, a bespoke one kept elsewhere included.
        adapter.ignored_categories = loaded.ignore
    return adapter


def register(adapter: SourceAdapter) -> SourceAdapter:
    if adapter.source_id in _REGISTRY:
        raise ValueError(f"duplicate source_id: {adapter.source_id}")
    _REGISTRY[adapter.source_id] = adapter
    return adapter


def get(source_id: str) -> SourceAdapter:
    return _REGISTRY[source_id]


def all_enabled() -> list[SourceAdapter]:
    return [a for a in _REGISTRY.values() if a.enabled]


async def load_adapters(session: AsyncSession | None = None) -> dict[str, str]:
    """Rebuild the registry from the `sources` table.

    Disabled sources are built too, so one can still be run by hand; the
    scheduler skips them via `all_enabled`. A row that fails to build is skipped
    and logged rather than taking every other source down with it, and returned
    as {source_id: error} so callers can report it. A source that is skipped
    simply has no run, and archiving is cycle-gated, so nothing is lost.
    """
    if session is None:
        async with SessionLocal() as own:
            return await load_adapters(own)

    rows = (await session.execute(select(Source).order_by(Source.source_id))).scalars().all()
    _REGISTRY.clear()
    errors: dict[str, str] = {}
    for row in rows:
        try:
            register(build_adapter(row))
        except Exception as exc:  # noqa: BLE001 — one bad row must not stop the rest
            errors[row.source_id] = f"{type(exc).__name__}: {exc}"
            log.error("source %s not loaded: %s", row.source_id, errors[row.source_id])
    if not rows:
        log.warning("the sources table is empty; run `python -m worker.sources.sync`")
    return errors
