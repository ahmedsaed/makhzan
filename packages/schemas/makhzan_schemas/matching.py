"""Who put a listing into its product: the grouping rules, or AI matching.

The product page badges an offer that AI matching merged ("Matched by AI"), and
says how many of a product's offers were (docs/DESIGN.md, the shop view). This
module is the one place that answers the question, so the API and anything
after it read the same answer.

PARTIAL: AI matching is not built yet (`ml/`, `docs/ai/`), so every listing is
matched by the rules today and the page shows no badge and no note. When the AI
decisions table exists, `matched_by` reads it: a listing is "ai" when the merge
that put it in its current product was an AI decision the rules alone would not
have made. Nothing else needs to change for the badge to appear.
"""

from __future__ import annotations

from typing import Literal

MatchedBy = Literal["rules", "ai"]


def matched_by(listing: object) -> MatchedBy:
    """How `listing` came to be an offer of its product.

    TODO(ai-matching): read the AI decisions table once it exists. Until then
    no merge is an AI one, so this is "rules" for every listing.
    """
    del listing
    return "rules"
