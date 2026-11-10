"""Source adapter contract.

Every data source — a scraped site, a manual import, a portal sync — is a
`SourceAdapter`. The pipeline only knows this interface, so sources are fully
swappable and individually toggleable (`enabled`) via config, with no code
changes to turn one off. That's the containment guarantee for the pragmatic
scraping stance in docs/PLAN.md.

Split of responsibility:
  - The adapter owns SOURCE-SPECIFIC knowledge: how to fetch and parse a given
    site/feed into `RawItem`s (including platform quirks like price units).
  - Normalization (RawItem -> NormalizedListing) is a SHARED step
    (worker/normalize.py) so cleaning, Arabic handling, and confidence scoring
    stay consistent everywhere. Adapters may override `normalize` when a source
    needs special handling, but should prefer the shared default.

Each adapter also carries a `SupplierInfo` describing the shop it represents,
which the pipeline uses to get-or-create the Supplier row.
"""

from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from makhzan_schemas.contracts import NormalizedListing, RawItem
from makhzan_schemas.domains.base import DEFAULT_DOMAIN
from makhzan_schemas.enums import SourceType

from worker.http import POLITE_DELAY, CycleFetcher

if TYPE_CHECKING:
    from makhzan_schemas.models import Listing


#: Partition key used by sources that have no natural slicing.
SINGLE_PARTITION = ""

#: The reference-data part that holds the shop's own contact details, which the
#: pipeline writes to `Supplier.contact` as well as keeping.
CONTACT_PART = "contact"


@dataclass(frozen=True)
class Page:
    """One page of results from a partition.

    `has_more` is the adapter's judgement, not the pipeline's: only the adapter
    knows what "the end" looks like for its platform (an empty array, a repeated
    final page, a total-pages header).
    """

    items: list[RawItem] = field(default_factory=list)
    has_more: bool = False
    #: External ids the source says it still sells but has out of stock, without
    #: giving the product itself. A shop that hides out-of-stock items from its
    #: catalogue feed still lists them elsewhere; this is how they stay listed —
    #: as out of stock — instead of being archived at the end of the cycle as if
    #: they were discontinued. Only listings already stored are touched.
    out_of_stock_ids: list[str] = field(default_factory=list)


#: What a change token is made of (`SourceAdapter.token_kind`). "modified" is the
#: shop's own last-write signal, which moves on any edit, the description's
#: included. "card_hash" is a hash of what the listing card shows, so it moves
#: only when the card does: an edit to the description alone leaves it as it was,
#: and only the age-based refresh (`DetailsSettings.max_age_days`) catches that.
TOKEN_MODIFIED = "modified"
TOKEN_CARD_HASH = "card_hash"


def card_hash(fields: dict) -> str:
    """A TOKEN_CARD_HASH change token: a short, stable hash of a card's own fields.

    Only as good as the fields hashed: it moves when one of them does and on
    nothing else, so a description edited without touching the card goes unseen.
    """
    text = json.dumps(fields, sort_keys=True, ensure_ascii=False, default=str)
    return "h" + hashlib.sha256(text.encode()).hexdigest()[:15]


@dataclass(frozen=True)
class DetailsSettings:
    """A source's `details = {...}` setting: whether, and how slowly, to read product pages.

    The details stage fetches at most `per_run` product pages a run, after the
    source's own pages, through the same paced client. A listing is due when its
    change token moved since its page was read, when its page was never read, or
    when it was read more than `max_age_days` ago — the safety net for an edit
    no token shows. Off unless the shop has agreed to the requests.
    """

    enabled: bool = False
    per_run: int = 20
    max_age_days: int = 90

    @classmethod
    def from_config(cls, value: object) -> DetailsSettings:
        """Read the setting from sources.toml, refusing anything it does not know.

        An unknown key is an error, as everywhere in a source's configuration: a
        misspelt `per_rn` silently ignored would leave the default in force.
        """
        if value is None:
            return cls()
        if isinstance(value, DetailsSettings):
            return value
        if not isinstance(value, dict):
            raise TypeError(f"details: expected a table like {{ enabled = false }}, got {value!r}")
        unknown = set(value) - {"enabled", "per_run", "max_age_days"}
        if unknown:
            raise TypeError(f"details: unknown key(s) {sorted(unknown)}")
        settings = cls(**value)
        if not isinstance(settings.enabled, bool):
            raise TypeError("details.enabled must be true or false")
        for name in ("per_run", "max_age_days"):
            number = getattr(settings, name)
            if isinstance(number, bool) or not isinstance(number, int) or number < 1:
                raise ValueError(f"details.{name} must be a whole number of at least 1")
        return settings


@dataclass(frozen=True)
class SupplierInfo:
    """Static description of the shop an adapter represents."""

    slug: str
    name: str
    #: Default vertical for this shop's listings. Only a fallback — a listing
    #: takes its domain from its category, so a multi-vertical marketplace is
    #: handled per listing rather than being forced into one domain here.
    domain: str = DEFAULT_DOMAIN
    website_url: str | None = None
    name_ar: str | None = None
    area: str | None = None
    governorate: str | None = None


class SourceAdapter(ABC):
    #: Stable, unique identifier — persisted on every listing as `source`.
    source_id: str
    #: How items from this source entered the system.
    source_type: SourceType
    #: The shop this adapter represents.
    supplier: SupplierInfo
    #: Config toggle. The pipeline skips disabled sources.
    enabled: bool = True
    #: Seconds to pause between paginated requests to THIS source's host. Sources
    #: run concurrently (different hosts, independent rate limits), so this only
    #: paces one host. Raise it for touchier sources; lower it for lenient ones.
    polite_delay: float = POLITE_DELAY
    #: Origin this source is fetched from. Concrete adapters set it; the pipeline
    #: uses it to look up the host's Crawl-Delay. None means "no host to ask"
    #: (the fixture source), and pacing falls back to polite_delay alone.
    base_url: str | None = None
    #: Cap on pages fetched per partition per run (None = no cap). Hosts with a
    #: hard request budget can take a few pages per run and resume next time
    #: rather than burning the budget and failing — see SourceCursor.
    max_pages_per_run: int | None = None
    #: Cap on how many *partitions* a single run sweeps (None = all of them).
    #: The companion to max_pages_per_run for sources split into many small
    #: partitions, where limiting pages would spread nothing: a marketplace browsed
    #: by 608 categories has a couple of pages in each. Partitions already finished this
    #: cycle are skipped, so consecutive runs work through the rest and the cycle
    #: closes once every partition has been swept.
    max_partitions_per_run: int | None = None

    #: True when the source's categories cover its whole catalogue, so a crosswalk
    #: miss means "genuinely unmapped" rather than "this listing was tagged by
    #: something other than its type". Such sources never fall back to keyword
    #: inference — guessing would overwrite exact information with a worse
    #: estimate, and mis-file across verticals doing it.
    #:
    #: Leave False when the source's categories are a *tag cloud* rather than a
    #: taxonomy. One WooCommerce shop tags listings with a mix of type ("Ceramic Capacitors"),
    #: package facet ("0805") and brand ("Uni-T"), so a crosswalk resolves most
    #: listings and inference still has to cover the rest.
    authoritative_categories: bool = False

    #: Optional crosswalk from the source's own category names to
    #: (domain, taxonomy leaf). Empty when this source's categories are not
    #: mapped. Named on the base class so drift checking can find it.
    categories: dict[str, tuple[str, str]] = {}

    #: Days a cycle should take, when set: each run's page budget is planned
    #: from the last cycle's size to keep the cycle near it, with
    #: `max_pages_per_run` as a hard ceiling (see `pipeline._page_budget`).
    #: Set from a source's config by the registry, so any adapter takes it.
    target_cycle_days: float | None = None

    #: The crosswalk's `ignore` list: source categories left unmapped on
    #: purpose, which the drift check does not report as new.
    ignored_categories: tuple[str, ...] = ()

    #: Who the crawler says it is to this shop: "browser" (the default, what
    #: every source has always sent) or "makhzanbot" (an honest User-Agent,
    #: signed with Web Bot Auth when a key is configured). See
    #: worker/identity.py and docs/crawler-identity.md. Set from a source's
    #: config by the registry, so any adapter takes it.
    identity: str = "browser"

    def source_categories(self, raw: RawItem) -> list[str]:
        """The source's own category names for this item, normalised.

        Used to detect crosswalk drift: a supplier that renames, adds or drops a
        category would otherwise change our categorisation silently. Adapters
        with a crosswalk should implement this; the rest need not.
        """
        return []

    def knows_category(self, raw: RawItem) -> bool:
        """Whether this sweep is in a position to say what the item's category is.

        Almost always yes: a source browsed by category knows it exactly, and a
        source that reads category tags off the item knows when there are none.
        It is *no* only for a sweep that carries no category signal at all — a
        whole-catalogue pass that exists so products filed under nothing are
        still seen. Such a pass must not erase a category another partition
        established, which is what returning False buys.

        On a source with `authoritative_categories`, the pipeline also treats
        a True here as False when the item's category misses the crosswalk: a
        product filed under a mapped and an unmapped category must keep the
        mapped one whichever partition is swept last.
        """
        return True

    def category_for(self, raw: RawItem) -> tuple[str, str] | None:
        """Map an item onto (domain, taxonomy leaf slug), or None if unmapped.

        Always consulted, ahead of keyword inference: a mapping is a fact and
        inference is a guess. What `authoritative_categories` controls is only
        what happens on a miss — no category at all, or fall back to inference.
        """
        return None

    def partitions(self) -> list[str]:
        """Independently fetchable slices of this source's catalog.

        Partitions exist so work is resumable and distributable at a finer grain
        than "the whole supplier". Sources with no natural slicing return a
        single empty-string partition.

        Note that partitions of one source share a host, so they are swept
        sequentially from a single worker — running them in parallel from one IP
        would defeat `polite_delay`. Splitting them across workers only helps
        when those workers have distinct egress IPs.
        """
        return [SINGLE_PARTITION]

    def cycle_data_parts(self) -> list[str]:
        """Names of the reference data this source fetches once a cycle.

        Some of what a shop publishes is per shop rather than per product page:
        its category tree, the price of every variant, its address. The pipeline
        fetches each part named here at the start of a cycle (see
        `fetch_cycle_part`), keeps it on the source's row so the runs of a
        week-long cycle share one copy, and hands it back via `use_cycle_data`
        before any page is fetched. `CONTACT_PART` is also written to the
        supplier. Empty by default: most sources need nothing beyond their pages.
        """
        return []

    async def fetch_cycle_part(self, fetcher: CycleFetcher, part: str) -> object:
        """Fetch one part of this source's reference data (JSON-serialisable).

        Every request goes through `fetcher`, which paces, counts and checks
        robots.txt. Raising leaves the part's previous copy in place.
        """
        raise NotImplementedError(part)

    def use_cycle_data(self, data: dict, fetched_at: dict[str, str] | None = None) -> None:
        """Receive the reference data for this run, keyed by part name.

        A part may be missing (never fetched, or its last fetch failed); the
        adapter then does without it rather than inventing anything.
        `fetched_at` says when each part was read (ISO 8601): it can be weeks
        older than the page a listing comes from, and a listing showing it
        should say so.
        """

    #: Product-page details (see `DetailsSettings`). None for an adapter that
    #: cannot fetch them, and such a source never enters the details stage.
    details: DetailsSettings | None = None
    #: What `change_token` is made of: TOKEN_MODIFIED or TOKEN_CARD_HASH.
    token_kind: str | None = None

    def change_token(self, raw: RawItem) -> str | None:
        """A value that moves when the product changes, from what the list page gave.

        Stored on the listing (`attributes.change_token`) at every upsert, at no
        extra request. The details stage compares it with the one stored when the
        product page was last read, and reads the page again only if it moved.
        None means the source has no such signal.
        """
        return None

    async def fetch_details(self, listing: Listing, fetcher: CycleFetcher) -> dict:
        """Read one listing's product page and return what to keep from it.

        Every request goes through `fetcher` under the label "details" (paced,
        counted, robots.txt checked on the full URL). Recognised keys:
        `description`, `specs`, `documents`, `videos`, `images` (extra photos),
        `brand` and `mfr_part_number`; anything else is kept as an attribute the
        card does not already set. Raising marks the listing failed, and it is
        retried after a backoff. Never return stock counts.
        """
        raise NotImplementedError

    def extra_requests(self) -> dict[str, int]:
        """Requests made inside `fetch_page` beyond the page itself, by label.

        The pipeline counts one request per page; an adapter that makes more to
        build a page (a Shopify shop's collection lists) reports them here, so
        the run's `stats.requests` is every request its host received.
        """
        return {}

    def run_report(self) -> dict:
        """What this run found that is worth a look, kept in `stats.source_report`.

        For checks only the adapter can make, such as a Wix shop's sitemap
        listing a product none of its configured galleries showed. A `warnings`
        list in it is printed by `make status`. Empty by default.
        """
        return {}

    @abstractmethod
    async def fetch_page(self, partition: str, page: int) -> Page:
        """Fetch one 1-based page of one partition.

        Paging is explicit rather than a stream so progress can be checkpointed:
        the pipeline commits after each page and records the resume point, so a
        run that dies partway keeps everything it already fetched.

        Implementations should be polite (rate-limit, cache, identify) and
        resilient — a single bad item should be skipped, not abort the run.
        Raising is reserved for genuine fetch failures (HTTP errors), which the
        pipeline treats as "stop this partition, keep the cursor, try next run".
        """
        raise NotImplementedError

    def normalize(self, raw: RawItem, domain: str | None = None) -> NormalizedListing:
        """Convert a RawItem into an upsert-ready NormalizedListing.

        Default delegates to the shared normalizer. Override only for
        source-specific quirks the shared logic can't handle.
        """
        from worker.normalize import normalize_item

        return normalize_item(raw, domain or self.supplier.domain)
