"""Who put a listing into its product: the grouping rules, or AI matching.

The product page badges an offer that AI matching merged ("Matched by AI"), and
says how many of a product's offers were (docs/DESIGN.md, the shop view). This
module is the one place that answers the question, so the API and anything
after it read the same answer.

It reads `Listing.matched_via`, which only the regroup writes
(`grouping.rebuild_products`, `grouping._attribute`): "ai" when the merge that
put the listing in its current product rested on an AI decision the rules alone
would not have made, else "rules". A listing no regroup has attributed yet
(NULL) is "rules". AI decisions are read by the regroup only in `live` mode
(`makhzan_schemas.ai.mode`); until then every listing is "rules" and the page
shows no badge.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Literal, Protocol
from uuid import UUID

MatchedBy = Literal["rules", "ai"]


class _Attributed(Protocol):
    id: UUID
    matched_via: str | None


def matched_by(listings: Iterable[_Attributed]) -> dict[UUID, MatchedBy]:
    """How each of `listings` came to be an offer of its product, by listing id.

    Synchronous and query-free: the answer is a column already loaded with
    each listing.
    """
    return {
        listing.id: "ai" if getattr(listing, "matched_via", None) == "ai" else "rules"
        for listing in listings
    }
