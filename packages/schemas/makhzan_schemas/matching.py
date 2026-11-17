"""Who put a listing into its product: the grouping rules, or AI matching.

The product page badges an offer that AI matching merged ("Matched by AI"), and
says how many of a product's offers were (docs/DESIGN.md, the shop view). This
module is the one place that answers the question, so the API and anything
after it read the same answer.

PARTIAL: AI matching is not built yet (`ml/`, `docs/ai/`), so every listing is
matched by the rules today and the page shows no badge and no note. When the AI
decisions table exists, `matched_by` reads it, in one query for all of a
product's listings: a listing is "ai" when the merge
that put it in its current product was an AI decision the rules alone would not
have made. Nothing else needs to change for the badge to appear.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Literal, Protocol
from uuid import UUID

MatchedBy = Literal["rules", "ai"]


class _HasId(Protocol):
    id: UUID


def matched_by(listings: Iterable[_HasId]) -> dict[UUID, MatchedBy]:
    """How each of `listings` came to be an offer of its product, by listing id.

    Takes all of a product's listings at once so that, once it reads the AI
    decisions table, the product page costs one query rather than one per
    offer.

    STUB: the AI decisions table does not exist yet, so no merge is an AI one
    and this answers "rules" for every listing without reading anything.
    TODO(ai-matching): read that table here, one query for every id given.
    """
    return {listing.id: "rules" for listing in listings}
